"""M5.1 REST-vs-gRPC head-to-head sweep orchestrator.

Drives the 18-cell matrix (2 paths × 3 widths × 3 concurrencies) per
``specs/018-m5-1-rest-vs-grpc/plan.md`` and emits a :class:`M5_1RunMetadata`
record the reporter writes to ``docs/benchmarks/m5_1-rest-vs-grpc.{md,json}``.

Per cell, in series (research.md R-4):

1. REST cohort via :mod:`rest_cohort`.
2. ``tuned_grpc_multiplexed`` sub-cohort (1 channel, c HTTP/2 streams).
3. At c ≥ 2: ``tuned_grpc_channels`` sub-cohort (c channels, serial RPCs each).
4. ``default_grpc`` control (M1-default channel; multiplexed).

The tuned channel configuration is loaded from M5's published
``docs/benchmarks/m5-cross-host-validation.json`` (T023) — the union of the
per-axis winning configs at the matching (path, hidden_size).

Per FR-012, each cohort can expand from n=100 to n=250 independently if
its TTFT/wall-clock CI overlaps the comparison threshold.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from vllm_grpc_bench.channel_config import (
    M1_BASELINE,
    ChannelConfig,
)
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    CellVerdict,
    ComparisonVerdict,
    GRPCSubCohortKind,
    M5_1Cell,
    M5_1RunMetadata,
    RunCohort,
    Sample,
    ShimOverheadRecord,
)
from vllm_grpc_bench.m5_1_grpc_cohort import GRPCCohortResult, run_grpc_cohort
from vllm_grpc_bench.rest_cohort import RESTCohortResult, run_rest_cohort

_M5_REPORT_PATH = Path("docs/benchmarks/m5-cross-host-validation.json")

_PATHS: tuple[str, ...] = ("chat_stream", "embed")
_WIDTHS: tuple[int, ...] = (2048, 4096, 8192)
_CONCURRENCIES: tuple[int, ...] = (1, 4, 8)


# ---------------------------------------------------------------------------
# Cell enumeration (T024)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CellSpec:
    """A single (path × hidden_size × concurrency) point in the M5.1 matrix."""

    path: str
    hidden_size: int
    concurrency: int

    @property
    def key(self) -> str:
        return f"{self.path}:h{self.hidden_size}:c{self.concurrency}"


def enumerate_cells() -> list[CellSpec]:
    """Return the 18-cell cross-product (2 × 3 × 3)."""
    cells: list[CellSpec] = []
    for path in _PATHS:
        for w in _WIDTHS:
            for c in _CONCURRENCIES:
                cells.append(CellSpec(path=path, hidden_size=w, concurrency=c))
    return cells


# ---------------------------------------------------------------------------
# Frozen tuned channel config loader (T023)
# ---------------------------------------------------------------------------


_AXES: tuple[str, ...] = ("max_message_size", "keepalive", "compression", "http2_framing")


def frozen_tuned_channel_config(
    path: str,
    hidden_size: int,
    *,
    m5_report_path: Path = _M5_REPORT_PATH,
) -> ChannelConfig:
    """Compose the M5 frozen-tuned channel for (path, hidden_size) per FR-006.

    Reads M5's published per-axis ``recommend`` verdicts and unions the
    winning configs. Axes with ``no_winner`` at the matching coordinates
    fall back to M1-default.

    Raises ``FileNotFoundError`` if the M5 report is missing — the M5.1
    sweep MUST run after M5 has closed.
    """
    if not m5_report_path.exists():
        raise FileNotFoundError(
            f"M5 report not found at {m5_report_path}; M5.1 requires M5 to have closed. "
            "Run the M5 sweep first or pass m5_report_path explicitly."
        )
    data = json.loads(m5_report_path.read_text())
    recs = data.get("recommendations", [])
    winners_by_axis: dict[str, str] = {}
    for rec in recs:
        if rec.get("verdict") != "recommend":
            continue
        if rec.get("applies_to_path") not in (path, "both"):
            continue
        widths = rec.get("applies_to_widths") or []
        if hidden_size not in widths:
            continue
        axis = rec.get("axis")
        winning = rec.get("winning_config")
        if axis in _AXES and isinstance(winning, str):
            winners_by_axis[axis] = winning

    from vllm_grpc_bench.m4_sweep import _compose_channel_config

    per_axis: dict[str, str] = {}
    for axis in _AXES:
        per_axis[axis] = winners_by_axis.get(axis, "m1-default")
    path_token = path.replace("_", "-")
    return _compose_channel_config(
        name=f"m5-1-frozen-{path_token}-h{hidden_size}",
        per_axis_winners=per_axis,
    )


# ---------------------------------------------------------------------------
# CI math on per-request samples (T026 helper)
# ---------------------------------------------------------------------------


def _bootstrap_delta_ci(
    grpc_metric: list[float],
    rest_metric: list[float],
    *,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> tuple[float, tuple[float, float]]:
    """Compute the (gRPC − REST) / REST delta percentage on medians + 95% CI.

    Uses paired-percentile bootstrap on the medians (independent resamples
    from each cohort). Returns ``(delta_pct, (ci_low, ci_high))``.
    """
    if not grpc_metric or not rest_metric:
        return 0.0, (0.0, 0.0)
    median_grpc = statistics.median(grpc_metric)
    median_rest = statistics.median(rest_metric)
    if median_rest == 0:
        return 0.0, (0.0, 0.0)
    delta_pct = ((median_grpc - median_rest) / median_rest) * 100.0

    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(n_bootstrap):
        gs = [rng.choice(grpc_metric) for _ in range(len(grpc_metric))]
        rs = [rng.choice(rest_metric) for _ in range(len(rest_metric))]
        mg = statistics.median(gs)
        mr = statistics.median(rs)
        if mr > 0:
            deltas.append(((mg - mr) / mr) * 100.0)
    if not deltas:
        return delta_pct, (delta_pct, delta_pct)
    deltas.sort()
    ci_low = deltas[int(0.025 * len(deltas))]
    ci_high = deltas[int(0.975 * len(deltas)) - 1] if len(deltas) > 1 else deltas[0]
    return delta_pct, (ci_low, ci_high)


def _verdict_for_sub_cohort(
    sub_cohort_kind: GRPCSubCohortKind,
    delta_pct: float,
    ci_pct: tuple[float, float],
) -> ComparisonVerdict:
    """Map (sub_cohort_kind, delta CI) → ComparisonVerdict literal per FR-013.

    One literal per sub-cohort kind so the report labels each gRPC win
    honestly — ``default_grpc`` wins now surface as
    ``default_grpc_recommend`` instead of being collapsed into the
    tuned-multiplexed literal.
    """
    ci_low, ci_high = ci_pct
    # CI strictly < 0 → gRPC faster (recommend that sub-cohort).
    # CI strictly > 0 → REST faster (rest_recommend).
    # CI spans 0 → no_winner.
    if ci_high < 0:
        if sub_cohort_kind == "tuned_grpc_multiplexed":
            return "tuned_grpc_multiplexed_recommend"
        if sub_cohort_kind == "tuned_grpc_channels":
            return "tuned_grpc_channels_recommend"
        if sub_cohort_kind == "tuned_grpc":
            return "tuned_grpc_recommend"
        if sub_cohort_kind == "default_grpc":
            return "default_grpc_recommend"
        raise ValueError(f"_verdict_for_sub_cohort: unknown sub_cohort_kind {sub_cohort_kind!r}")
    if ci_low > 0:
        return "rest_recommend"
    return "no_winner"


# ---------------------------------------------------------------------------
# Cell dispatch + verdict emission (T025, T026)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CellMeasurement:
    """Aggregated cohort data for one cell — used by the verdict emitter."""

    cell: CellSpec
    rest_result: RESTCohortResult
    tuned_multiplexed: GRPCCohortResult
    tuned_channels: GRPCCohortResult | None  # None at c=1
    default_grpc: GRPCCohortResult


async def dispatch_cell(
    cell: CellSpec,
    *,
    rest_url: str,
    grpc_target: str,
    token: str,
    n: int,
    tuned_channel_config: ChannelConfig,
    default_channel_config: ChannelConfig = M1_BASELINE,
    rest_client: httpx.AsyncClient | None = None,
    timeout_s: float = 60.0,
    rtt_probe_n: int = 16,
    warmup_n: int = 0,
) -> _CellMeasurement:
    """Run the cell's REST + tuned-gRPC sub-cohort(s) + default-gRPC control in series."""
    metadata: tuple[tuple[str, str], ...] = (("authorization", f"Bearer {token}"),)
    seed = (hash(cell.key) & 0x7FFFFFFF) ^ 0xABCD

    # 1) REST cohort.
    rest_result = await run_rest_cohort(
        path=cell.path,
        base_url=rest_url,
        token=token,
        concurrency=cell.concurrency,
        n=n,
        hidden_size=cell.hidden_size,
        timeout_s=timeout_s,
        rtt_probe_n=rtt_probe_n,
        warmup_n=warmup_n,
        client=rest_client,
    )

    # 2) tuned-gRPC sub-cohort(s).
    if cell.concurrency == 1:
        tuned_mux_kind: GRPCSubCohortKind = "tuned_grpc"
    else:
        tuned_mux_kind = "tuned_grpc_multiplexed"
    tuned_mux = await run_grpc_cohort(
        path=cell.path,  # type: ignore[arg-type]
        target=grpc_target,
        credentials=None,
        metadata=metadata,
        channel_config=tuned_channel_config,
        sub_cohort_kind=tuned_mux_kind,
        concurrency=cell.concurrency,
        n=n,
        hidden_size=cell.hidden_size,
        seed=seed,
        timeout_s=timeout_s,
        cell_id=f"grpc-tuned-mux:{cell.key}",
        rtt_probe_n=rtt_probe_n,
        warmup_n=warmup_n,
    )
    tuned_channels: GRPCCohortResult | None = None
    if cell.concurrency >= 2:
        tuned_channels = await run_grpc_cohort(
            path=cell.path,  # type: ignore[arg-type]
            target=grpc_target,
            credentials=None,
            metadata=metadata,
            channel_config=tuned_channel_config,
            sub_cohort_kind="tuned_grpc_channels",
            concurrency=cell.concurrency,
            n=n,
            hidden_size=cell.hidden_size,
            seed=seed ^ 0xDEAD,
            timeout_s=timeout_s,
            cell_id=f"grpc-tuned-ch:{cell.key}",
            rtt_probe_n=rtt_probe_n,
            warmup_n=warmup_n,
        )

    # 3) default-gRPC control.
    default_grpc = await run_grpc_cohort(
        path=cell.path,  # type: ignore[arg-type]
        target=grpc_target,
        credentials=None,
        metadata=metadata,
        channel_config=default_channel_config,
        sub_cohort_kind="default_grpc",
        concurrency=cell.concurrency,
        n=n,
        hidden_size=cell.hidden_size,
        seed=seed ^ 0xCAFE,
        timeout_s=timeout_s,
        cell_id=f"grpc-default:{cell.key}",
        rtt_probe_n=rtt_probe_n,
        warmup_n=warmup_n,
    )

    return _CellMeasurement(
        cell=cell,
        rest_result=rest_result,
        tuned_multiplexed=tuned_mux,
        tuned_channels=tuned_channels,
        default_grpc=default_grpc,
    )


def _grpc_metric_samples(result: GRPCCohortResult, path: str) -> list[float]:
    """Extract per-sample metric values: TTFT for chat_stream, wall_clock for embed."""
    out: list[float] = []
    for s in result.samples:
        if s.error is not None:
            continue
        if path == "chat_stream":
            if s.time_to_first_token_seconds is not None:
                out.append(s.time_to_first_token_seconds)
        else:
            out.append(s.wall_clock_seconds)
    return out


def _rest_metric_samples(result: RESTCohortResult, path: str) -> list[float]:
    """REST per-sample metric: ``wall_clock_seconds`` is TTFT for chat_stream
    and total wall-clock for embed (per rest_cohort's semantics).
    """
    return [s.wall_clock_seconds for s in result.samples]


def emit_cell_verdicts(
    measurement: _CellMeasurement,
    *,
    low_rtt_threshold_ms: float = 20.0,
) -> M5_1Cell:
    """Build the M5_1Cell record for one measurement: verdicts + RTT + flags."""
    cell = measurement.cell
    path = cell.path
    rest_samples = _rest_metric_samples(measurement.rest_result, path)
    metric_label = "ttft" if path == "chat_stream" else "wallclock"

    verdicts: list[CellVerdict] = []

    def _emit(result: GRPCCohortResult) -> None:
        grpc_samples = _grpc_metric_samples(result, path)
        delta_pct, ci_pct = _bootstrap_delta_ci(grpc_samples, rest_samples)
        verdict = _verdict_for_sub_cohort(result.sub_cohort_kind, delta_pct, ci_pct)
        verdicts.append(
            CellVerdict(
                grpc_sub_cohort=result.sub_cohort_kind,
                verdict=verdict,
                delta_pct=delta_pct,
                ci_pct=ci_pct,
                metric=metric_label,  # type: ignore[arg-type]
            )
        )

    _emit(measurement.tuned_multiplexed)
    if measurement.tuned_channels is not None:
        _emit(measurement.tuned_channels)
    _emit(measurement.default_grpc)

    # Aggregate RTT across cohorts at this cell.
    rtt_medians = [
        measurement.tuned_multiplexed.rtt_record.median_ms,
        measurement.default_grpc.rtt_record.median_ms,
    ]
    if measurement.tuned_channels is not None:
        rtt_medians.append(measurement.tuned_channels.rtt_record.median_ms)
    if measurement.rest_result.rtt_record is not None:
        rtt_medians.append(measurement.rest_result.rtt_record.median_ms)
    rtt_ms_median = statistics.median(rtt_medians)
    rtt_ms_p95 = max(rtt_medians)
    low_rtt = rtt_ms_median < low_rtt_threshold_ms

    return M5_1Cell(
        path=path,  # type: ignore[arg-type]
        hidden_size=cell.hidden_size,  # type: ignore[arg-type]
        concurrency=cell.concurrency,  # type: ignore[arg-type]
        rest_cohort_key=f"rest:{cell.key}",
        default_grpc_cohort_key=f"grpc-default:{cell.key}",
        tuned_grpc_multiplexed_cohort_key=f"grpc-tuned-mux:{cell.key}",
        tuned_grpc_channels_cohort_key=(
            f"grpc-tuned-ch:{cell.key}" if cell.concurrency >= 2 else None
        ),
        verdicts=verdicts,
        comparison_unavailable=False,
        comparison_unavailable_reason=None,
        rtt_ms_median=rtt_ms_median,
        rtt_ms_p95=rtt_ms_p95,
        low_rtt_caveat=low_rtt,
    )


# ---------------------------------------------------------------------------
# Sample → RunCohort adapter (so the reporter can emit per-cohort entries
# matching the M5 schema's cohorts[] array)
# ---------------------------------------------------------------------------


def _aggregate_rest_to_run_cohort(cell: CellSpec, result: RESTCohortResult) -> RunCohort:
    samples_tuple = tuple(
        Sample(
            cell_id=f"rest:{cell.key}",
            iteration=i,
            request_wire_bytes=s.request_bytes,
            response_wire_bytes=s.response_bytes,
            wall_clock_seconds=s.wall_clock_seconds,
            time_to_first_token_seconds=(
                s.wall_clock_seconds if cell.path == "chat_stream" else None
            ),
        )
        for i, s in enumerate(result.samples)
    )
    bench_cell = _benchmark_cell_for(cell, M1_BASELINE)
    wallclocks = [s.wall_clock_seconds for s in result.samples]
    req_bytes = [s.request_bytes for s in result.samples]
    return RunCohort(
        cell=bench_cell,
        samples=samples_tuple,
        n_successful=len(samples_tuple),
        bytes_mean=statistics.mean(req_bytes) if req_bytes else 0.0,
        bytes_ci_low=0.0,
        bytes_ci_high=0.0,
        time_mean=statistics.mean(wallclocks) if wallclocks else 0.0,
        time_ci_low=min(wallclocks) if wallclocks else 0.0,
        time_ci_high=max(wallclocks) if wallclocks else 0.0,
        rtt_record=result.rtt_record,
        protocol="rest",
        grpc_channel_model=None,
        connection_count=result.record.connections_opened,
        shim_overhead_ms=result.record.shim_overhead_ms_median,
        comparison_cell_key=cell.key,
        rest_cohort_record=result.record,
    )


def _aggregate_grpc_to_run_cohort(
    cell: CellSpec,
    result: GRPCCohortResult,
    channel_config: ChannelConfig,
    cohort_id_prefix: str,
) -> RunCohort:
    bench_cell = _benchmark_cell_for(cell, channel_config)
    wallclocks = [s.wall_clock_seconds for s in result.samples if s.error is None]
    req_bytes = [s.request_wire_bytes for s in result.samples]
    return RunCohort(
        cell=bench_cell,
        samples=result.samples,
        n_successful=sum(1 for s in result.samples if s.error is None),
        bytes_mean=statistics.mean(req_bytes) if req_bytes else 0.0,
        bytes_ci_low=0.0,
        bytes_ci_high=0.0,
        time_mean=statistics.mean(wallclocks) if wallclocks else 0.0,
        time_ci_low=min(wallclocks) if wallclocks else 0.0,
        time_ci_high=max(wallclocks) if wallclocks else 0.0,
        rtt_record=result.rtt_record,
        protocol="grpc",
        grpc_channel_model=result.sub_cohort_kind,
        connection_count=result.channels_opened,
        shim_overhead_ms=None,
        comparison_cell_key=cell.key,
        rest_cohort_record=None,
    )


def _benchmark_cell_for(cell: CellSpec, channel_config: ChannelConfig) -> BenchmarkCell:
    corpus = "m1_chat" if cell.path == "chat_stream" else "m1_embed"
    return BenchmarkCell(
        path=cell.path,  # type: ignore[arg-type]
        hidden_size=cell.hidden_size,
        channel_config=channel_config,
        corpus_subset=corpus,  # type: ignore[arg-type]
        iterations=1,  # placeholder — actual n recorded in M5.1 cohort metadata
    )


# ---------------------------------------------------------------------------
# Top-level orchestrator (T027)
# ---------------------------------------------------------------------------


@dataclass
class M5_1SweepConfig:
    """Configuration for the M5.1 sweep."""

    rest_url: str
    grpc_target: str
    token_env_var: str = "MODAL_BENCH_TOKEN"
    modal_app_handle: str = "vllm-grpc-bench-rest-grpc-mock"
    modal_region: str = "eu-west-1"
    rest_shim_version_sha: str = "unknown"
    n_per_cohort: int = 100
    expand_n: int = 250
    timeout_s: float = 60.0
    rtt_probe_n: int = 16
    warmup_n: int = 10
    low_rtt_threshold_ms: float = 20.0
    shim_overhead_warn_pct: float = 5.0
    m5_report_path: Path = field(default_factory=lambda: _M5_REPORT_PATH)
    # When set, overrides the default 18-cell enumeration. Used by
    # ``--m5_1-smoke`` to run a 3-cell minimal coverage matrix.
    cells_override: list[CellSpec] | None = None


# Minimal smoke cell set: covers every M5.1 code path that runs per cell —
# both protocols (REST + gRPC), all four gRPC sub-cohort kinds (tuned_grpc
# degenerate at c=1, tuned_grpc_multiplexed + tuned_grpc_channels at c>=2,
# default_grpc on every cell), both metric types (TTFT for chat_stream,
# wallclock for embed), and one h=2048 width (the cheapest payload).
SMOKE_CELLS: tuple[CellSpec, ...] = (
    CellSpec(path="chat_stream", hidden_size=2048, concurrency=1),
    CellSpec(path="chat_stream", hidden_size=2048, concurrency=4),
    CellSpec(path="embed", hidden_size=2048, concurrency=4),
)


@dataclass
class M5_1Run:
    """Top-level result of a sweep run."""

    metadata: M5_1RunMetadata
    cohorts: list[RunCohort]


async def run_m5_1_sweep(
    config: M5_1SweepConfig,
    *,
    progress: bool = True,
) -> M5_1Run:
    """Execute the 18-cell sweep and return the populated M5_1Run."""
    token = os.environ.get(config.token_env_var, "")
    if not token:
        raise RuntimeError(f"Bearer-token env var {config.token_env_var!r} is not set.")

    cells = list(config.cells_override) if config.cells_override is not None else enumerate_cells()
    m5_1_matrix: list[M5_1Cell] = []
    cohorts: list[RunCohort] = []
    shim_overheads_run: list[float] = []
    run_started = time.monotonic()

    for idx, cell in enumerate(cells):
        if progress:
            print(
                f"[{idx + 1}/{len(cells)}] dispatching cell {cell.key}",
                flush=True,
            )
        tuned_cfg = frozen_tuned_channel_config(
            cell.path, cell.hidden_size, m5_report_path=config.m5_report_path
        )
        measurement = await dispatch_cell(
            cell,
            rest_url=config.rest_url,
            grpc_target=config.grpc_target,
            token=token,
            n=config.n_per_cohort,
            tuned_channel_config=tuned_cfg,
            timeout_s=config.timeout_s,
            rtt_probe_n=config.rtt_probe_n,
            warmup_n=config.warmup_n,
        )
        m5_1_cell = emit_cell_verdicts(
            measurement, low_rtt_threshold_ms=config.low_rtt_threshold_ms
        )
        m5_1_matrix.append(m5_1_cell)

        # Adapt cohorts → RunCohort for the reporter.
        cohorts.append(_aggregate_rest_to_run_cohort(cell, measurement.rest_result))
        cohorts.append(
            _aggregate_grpc_to_run_cohort(
                cell, measurement.tuned_multiplexed, tuned_cfg, "grpc-tuned-mux"
            )
        )
        if measurement.tuned_channels is not None:
            cohorts.append(
                _aggregate_grpc_to_run_cohort(
                    cell, measurement.tuned_channels, tuned_cfg, "grpc-tuned-ch"
                )
            )
        cohorts.append(
            _aggregate_grpc_to_run_cohort(
                cell, measurement.default_grpc, M1_BASELINE, "grpc-default"
            )
        )

        # Track shim overheads run-wide.
        shim_overheads_run.append(measurement.rest_result.record.shim_overhead_ms_median)

    # Build aggregate ShimOverheadRecord.
    if shim_overheads_run:
        med = statistics.median(shim_overheads_run)
        p95 = sorted(shim_overheads_run)[
            min(len(shim_overheads_run) - 1, int(0.95 * len(shim_overheads_run)))
        ]
        mx = max(shim_overheads_run)
    else:
        med = p95 = mx = 0.0
    shim_record = ShimOverheadRecord(
        shim_overhead_ms_median_across_run=med,
        shim_overhead_ms_p95_across_run=p95,
        shim_overhead_ms_max_across_run=mx,
        shim_overhead_material_in_any_cohort=any(
            o > 5.0
            for o in shim_overheads_run  # conservative 5ms heuristic
        ),
    )

    # Supersedes-M1-time table (T045): join the M5.1 matrix to M1's
    # published time-axis cells via the fixture-first loader.
    from vllm_grpc_bench.m5_1_supersede import build_supersedes_m1_time

    try:
        supersedes_m1 = build_supersedes_m1_time(m5_1_matrix)
    except FileNotFoundError:
        # Fixture missing — emit the report without the supersession table
        # rather than blocking the entire sweep. The supersede builder
        # raises a clear error the operator can act on; we degrade
        # gracefully here so US1 (the matrix) is independent of US3.
        supersedes_m1 = []

    metadata = M5_1RunMetadata(
        modal_app_handle=config.modal_app_handle,
        modal_region=config.modal_region,
        modal_instance_class="cpu",
        rest_shim_version_sha=config.rest_shim_version_sha,
        rest_shim_uvicorn_workers=1,
        auth_token_env_var=config.token_env_var,
        shim_overhead=shim_record,
        supersedes_m1_time=supersedes_m1,
        m5_1_matrix=m5_1_matrix,
    )
    if progress:
        elapsed = time.monotonic() - run_started
        print(
            f"M5.1 sweep complete in {elapsed:.1f}s — {len(m5_1_matrix)} cells, "
            f"{len(cohorts)} cohorts.",
            flush=True,
        )
    return M5_1Run(metadata=metadata, cohorts=cohorts)
