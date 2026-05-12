"""M5.2 sweep orchestrator — five-cohort transport-vs-tuning sweep.

Per ``specs/019-m5-2-transport-tuning/`` (T030-T034, T041, T042). Drives the
18-cell matrix (2 paths x 3 widths x 3 concurrencies), dispatching the
five cohorts per cell:

* ``rest_https_edge`` over Modal's HTTPS edge (TLS-terminated, anycast).
* ``rest_plain_tcp`` over Modal's plain-TCP tunnel.
* ``default_grpc`` (M1-default channel, multiplexed).
* ``tuned_grpc_multiplexed`` (c >= 2) — frozen-tuned channel, multiplexed.
* ``tuned_grpc_channels``  (c >= 2) — frozen-tuned channel, c connections.
* ``tuned_grpc``           (c == 1)  — degenerate collapse of the two above
  per FR-006.

Per request, the orchestrator writes one labelled event to a gzipped JSONL
sidecar (see ``m5_2_events``). On run end the writer is closed, the
sidecar is gzipped + SHA-256 hashed, and the run config JSON is written
under ``bench-results/m5_2-full/``. The harness MUST NOT emit the markdown
or aggregate JSON directly — those come out of the regenerator (per
FR-012b).

The frozen-tuned channel composition (``frozen_tuned_channel_config``) is
inherited from M5.1; M5.2 does NOT re-tune (FR-007). The smoke-specific
assertion surface (``assert_both_rest_transports_reach_same_modal_deploy``
etc.) is exercised by ``--m5_2-smoke`` before any cohort dispatches.
"""

from __future__ import annotations

import json
import os
import random
import statistics
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from vllm_grpc_bench.channel_config import M1_BASELINE, ChannelConfig
from vllm_grpc_bench.m3_types import (
    M5_2CohortKind,
    NetworkPath,
    ProtocolComparisonRow,
    ProtocolComparisonVerdict,
    Sample,
    TransportOnlyRow,
    TransportOnlyVerdict,
)
from vllm_grpc_bench.m5_1_grpc_cohort import GRPCCohortResult, run_grpc_cohort
from vllm_grpc_bench.m5_1_sweep import (
    CellSpec,
    enumerate_cells,
    frozen_tuned_channel_config,
)
from vllm_grpc_bench.m5_2_events import (
    EventsSidecarWriter,
    PerRequestEventRecord,
)
from vllm_grpc_bench.m5_2_symmetry import (
    CohortConfigInput,
    SymmetryBlock,
    assert_symmetry,
    build_symmetry_block,
    canonical_digest,
)
from vllm_grpc_bench.rest_cohort import RESTCohortResult, RESTCohortSample, run_rest_cohort

# Re-export so importers can grab CellSpec / enumerate_cells from m5_2_sweep
# without reaching into m5_1_sweep.
__all__ = [
    "CellSpec",
    "M5_2CellMeasurement",
    "M5_2SmokeAssertionFailure",
    "M5_2SweepConfig",
    "M5_2Run",
    "SMOKE_CELLS",
    "assert_both_rest_transports_reach_same_modal_deploy",
    "assert_m5_2_json_schema_round_trips",
    "assert_per_cohort_rtt_probe_within_thresholds_all_five_cohorts",
    "dispatch_cell",
    "emit_cell_verdicts",
    "enumerate_cells",
    "frozen_tuned_channel_config",
    "run_m5_2_sweep",
]


SMOKE_CELLS: tuple[CellSpec, ...] = (
    CellSpec(path="chat_stream", hidden_size=2048, concurrency=1),
    CellSpec(path="chat_stream", hidden_size=2048, concurrency=4),
    CellSpec(path="embed", hidden_size=2048, concurrency=4),
    CellSpec(path="embed", hidden_size=2048, concurrency=1),
)


# ---------------------------------------------------------------------------
# Sweep config + cell measurement container
# ---------------------------------------------------------------------------


@dataclass
class M5_2SweepConfig:
    """Configuration for the M5.2 sweep. Top-level entry point.

    The full M5.2 sweep deploys to Modal, runs the 18-cell matrix at
    n=250 per cohort, emits the events sidecar + run config, and tears
    down. Operator-triggered; not part of CI.
    """

    rest_https_edge_url: str
    rest_plain_tcp_url: str
    grpc_target: str

    run_id: str
    events_sidecar_out_dir: Path

    token_env_var: str = "MODAL_BENCH_TOKEN"
    modal_app_handle: str = "vllm-grpc-bench-rest-grpc-mock"
    modal_region: str = "eu-west-1"
    modal_instance_class: str = "cpu"
    https_edge_endpoint: str = ""

    n_per_cohort: int = 250  # M5.2 resolution target per FR-011.
    expand_n: int = 250  # M5.2 explicitly does NOT expand beyond 250.
    timeout_s: float = 60.0
    rtt_probe_n: int = 16
    warmup_n: int = 20
    rtt_validity_threshold_ms: float = 1.0
    rtt_exercise_threshold_ms: float = 20.0
    shim_overhead_warn_pct: float = 5.0
    seed: int = 0

    skip_geolocation_lookup: bool = False
    client_external_geolocation_country: str | None = None
    client_external_geolocation_region: str | None = None

    m5_report_path: Path = field(
        default_factory=lambda: Path("docs/benchmarks/m5-cross-host-validation.json")
    )
    cells_override: tuple[CellSpec, ...] | None = None

    smoke: bool = False


@dataclass(frozen=True)
class M5_2CellMeasurement:
    """Aggregated cohort data for one M5.2 cell — five cohorts at c >= 2,
    four at c == 1.

    All fields are populated except the tuned-pair / collapsed-tuned
    fields, which carry the c-aware exclusivity:

    * c == 1: ``tuned_grpc`` is set; ``tuned_multiplexed`` and
      ``tuned_channels`` are ``None``.
    * c >= 2: ``tuned_multiplexed`` and ``tuned_channels`` are set;
      ``tuned_grpc`` is ``None``.
    """

    cell: CellSpec
    rest_https_edge: RESTCohortResult
    rest_plain_tcp: RESTCohortResult
    default_grpc: GRPCCohortResult
    tuned_multiplexed: GRPCCohortResult | None
    tuned_channels: GRPCCohortResult | None
    tuned_grpc: GRPCCohortResult | None


# ---------------------------------------------------------------------------
# Cell dispatch
# ---------------------------------------------------------------------------


async def dispatch_cell(
    cell: CellSpec,
    *,
    rest_https_edge_url: str,
    rest_plain_tcp_url: str,
    grpc_target: str,
    token: str,
    n: int,
    tuned_channel_config: ChannelConfig,
    default_channel_config: ChannelConfig = M1_BASELINE,
    rest_client_https_edge: httpx.AsyncClient | None = None,
    rest_client_plain_tcp: httpx.AsyncClient | None = None,
    timeout_s: float = 60.0,
    rtt_probe_n: int = 16,
    warmup_n: int = 0,
    https_edge_endpoint: str = "",
    client_external_geolocation_country: str | None = None,
    client_external_geolocation_region: str | None = None,
) -> M5_2CellMeasurement:
    """Run a cell's five cohorts in series per research R-1 ordering:

    rest_https_edge -> rest_plain_tcp -> default_grpc ->
    tuned_grpc_multiplexed (c>=2) -> tuned_grpc_channels (c>=2) OR
    tuned_grpc (c=1)
    """
    metadata: tuple[tuple[str, str], ...] = (("authorization", f"Bearer {token}"),)
    seed = (hash(cell.key) & 0x7FFFFFFF) ^ 0xABCD

    rest_https_edge = await run_rest_cohort(
        path=cell.path,
        base_url=rest_https_edge_url,
        token=token,
        concurrency=cell.concurrency,
        n=n,
        hidden_size=cell.hidden_size,
        timeout_s=timeout_s,
        rtt_probe_n=rtt_probe_n,
        warmup_n=warmup_n,
        client=rest_client_https_edge,
        network_path="https_edge",
        https_edge_endpoint=https_edge_endpoint,
        client_external_geolocation_country=client_external_geolocation_country,
        client_external_geolocation_region=client_external_geolocation_region,
        # M5.2 chat-path parity (FR-005c): the cell_id thread to the REST
        # cohort matches the cell_id the gRPC cohorts already receive, so
        # both protocols build the same chat prompt via build_chat_prompt.
        cell_id=f"rest-edge:{cell.key}",
    )

    rest_plain_tcp = await run_rest_cohort(
        path=cell.path,
        base_url=rest_plain_tcp_url,
        token=token,
        concurrency=cell.concurrency,
        n=n,
        hidden_size=cell.hidden_size,
        timeout_s=timeout_s,
        rtt_probe_n=rtt_probe_n,
        warmup_n=warmup_n,
        client=rest_client_plain_tcp,
        network_path="plain_tcp",
        cell_id=f"rest-tcp:{cell.key}",
    )

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

    tuned_multiplexed: GRPCCohortResult | None = None
    tuned_channels: GRPCCohortResult | None = None
    tuned_grpc: GRPCCohortResult | None = None

    if cell.concurrency == 1:
        tuned_grpc = await run_grpc_cohort(
            path=cell.path,  # type: ignore[arg-type]
            target=grpc_target,
            credentials=None,
            metadata=metadata,
            channel_config=tuned_channel_config,
            sub_cohort_kind="tuned_grpc",
            concurrency=cell.concurrency,
            n=n,
            hidden_size=cell.hidden_size,
            seed=seed,
            timeout_s=timeout_s,
            cell_id=f"grpc-tuned:{cell.key}",
            rtt_probe_n=rtt_probe_n,
            warmup_n=warmup_n,
        )
    else:
        tuned_multiplexed = await run_grpc_cohort(
            path=cell.path,  # type: ignore[arg-type]
            target=grpc_target,
            credentials=None,
            metadata=metadata,
            channel_config=tuned_channel_config,
            sub_cohort_kind="tuned_grpc_multiplexed",
            concurrency=cell.concurrency,
            n=n,
            hidden_size=cell.hidden_size,
            seed=seed,
            timeout_s=timeout_s,
            cell_id=f"grpc-tuned-mux:{cell.key}",
            rtt_probe_n=rtt_probe_n,
            warmup_n=warmup_n,
        )
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

    return M5_2CellMeasurement(
        cell=cell,
        rest_https_edge=rest_https_edge,
        rest_plain_tcp=rest_plain_tcp,
        default_grpc=default_grpc,
        tuned_multiplexed=tuned_multiplexed,
        tuned_channels=tuned_channels,
        tuned_grpc=tuned_grpc,
    )


# ---------------------------------------------------------------------------
# Per-request event emission to the sidecar
# ---------------------------------------------------------------------------


def _ts_offset_ms(base_ms: float, cumulative_s: float) -> float:
    return base_ms + cumulative_s * 1000.0


def _rest_samples_for_cell(
    cell: CellSpec,
    result: RESTCohortResult,
    cohort: M5_2CohortKind,
    network_path: NetworkPath,
    base_ms: float,
    phase: str,
    *,
    samples_override: tuple[RESTCohortSample, ...] | None = None,
) -> list[PerRequestEventRecord]:
    """Build per-request events for a REST cohort. The base monotonic
    timestamp is a fixed offset so the regenerator's aggregate computation
    is byte-stable across re-runs on the same in-memory samples.

    ``samples_override`` lets the sidecar writer build warmup events from
    ``result.warmup_samples`` while still using the cohort's measurement
    rtt_record for the rtt_at_issue snapshot (per FR-012a (f); for warmup
    records the snapshot is 0.0 since the RTT probe hadn't run yet).
    """
    measurement_phase = phase == "measurement"
    rtt_med = (
        (0.0 if result.rtt_record is None else result.rtt_record.median_ms)
        if measurement_phase
        else 0.0
    )
    samples = result.samples if samples_override is None else samples_override
    records: list[PerRequestEventRecord] = []
    cumulative = 0.0
    rng = random.Random(hash(cell.key) & 0x7FFFFFFF ^ (0 if measurement_phase else 0xDEADBEEF))
    for sample in samples:
        issue = _ts_offset_ms(base_ms, cumulative)
        done = _ts_offset_ms(base_ms, cumulative + sample.wall_clock_seconds)
        first_byte = done if cell.path == "chat_stream" else None
        records.append(
            PerRequestEventRecord(
                cohort=cohort,
                path=cell.path,  # type: ignore[arg-type]
                hidden_size=cell.hidden_size,
                concurrency=cell.concurrency,
                network_path=network_path,
                # uuid4 is normally non-deterministic; for sidecar byte-
                # stability we seed it via the cohort+cell+index hash.
                request_uuid=str(uuid.UUID(int=rng.getrandbits(128))),
                issue_ts_ms=issue,
                first_byte_ts_ms=first_byte,
                done_ts_ms=done,
                rtt_at_issue_ms=rtt_med,
                phase=phase,  # type: ignore[arg-type]
                server_bound=False,
                request_body_bytes=sample.request_bytes,
                response_body_bytes=sample.response_bytes,
                status="success",
            )
        )
        cumulative += sample.wall_clock_seconds
    return records


def _grpc_samples_for_cell(
    cell: CellSpec,
    result: GRPCCohortResult,
    cohort: M5_2CohortKind,
    base_ms: float,
    phase: str,
    *,
    samples_override: tuple[Sample, ...] | None = None,
) -> list[PerRequestEventRecord]:
    measurement_phase = phase == "measurement"
    rtt_med = result.rtt_record.median_ms if measurement_phase else 0.0
    samples = result.samples if samples_override is None else samples_override
    records: list[PerRequestEventRecord] = []
    cumulative = 0.0
    seed_xor = 0 if measurement_phase else 0xDEADBEEF
    rng = random.Random((hash(cell.key) & 0x7FFFFFFF) ^ (hash(cohort) & 0x7FFFFFFF) ^ seed_xor)
    for sample in samples:
        issue = _ts_offset_ms(base_ms, cumulative)
        done = _ts_offset_ms(base_ms, cumulative + sample.wall_clock_seconds)
        first_byte: float | None = None
        if cell.path == "chat_stream" and sample.time_to_first_token_seconds is not None:
            first_byte = _ts_offset_ms(base_ms, cumulative + sample.time_to_first_token_seconds)
        status = "success"
        if sample.error is not None:
            status = f"error:{sample.error_kind or 'unknown'}"
        records.append(
            PerRequestEventRecord(
                cohort=cohort,
                path=cell.path,  # type: ignore[arg-type]
                hidden_size=cell.hidden_size,
                concurrency=cell.concurrency,
                network_path="plain_tcp",
                request_uuid=str(uuid.UUID(int=rng.getrandbits(128))),
                issue_ts_ms=issue,
                first_byte_ts_ms=first_byte,
                done_ts_ms=done,
                rtt_at_issue_ms=rtt_med,
                phase=phase,  # type: ignore[arg-type]
                server_bound=False,
                request_body_bytes=sample.request_wire_bytes,
                response_body_bytes=sample.response_wire_bytes,
                status=status,
            )
        )
        cumulative += sample.wall_clock_seconds
    return records


def write_cell_events_to_sidecar(
    measurement: M5_2CellMeasurement,
    writer: EventsSidecarWriter,
    *,
    base_ms_per_cohort: float = 0.0,
    phase: str = "measurement",
) -> None:
    """Stream every cohort's per-request events to the sidecar for one
    M5.2 cell. Records are written in cohort dispatch order (research R-1):
    rest_https_edge → rest_plain_tcp → default_grpc → (tuned variants).

    For each cohort, ``warmup_samples`` (if any) are written FIRST with
    ``phase="warmup"`` and ``rtt_at_issue_ms=0`` (the RTT probe hadn't run
    yet at warmup-issue time), then the measurement samples follow with
    ``phase="measurement"`` and the cohort's measured RTT median. This
    matches FR-012a (g)'s rule that warmup is persisted for audit but
    excluded from aggregates.

    The ``phase`` kwarg overrides the per-cohort behavior — used by tests
    that want every record stamped with a single phase.
    """

    def _write_rest(
        cohort_name: M5_2CohortKind,
        network_path: NetworkPath,
        result: RESTCohortResult,
    ) -> None:
        if phase == "measurement" and result.warmup_samples:
            for rec in _rest_samples_for_cell(
                measurement.cell,
                result,
                cohort=cohort_name,
                network_path=network_path,
                base_ms=base_ms_per_cohort,
                phase="warmup",
                samples_override=result.warmup_samples,
            ):
                writer.write(rec)
        for rec in _rest_samples_for_cell(
            measurement.cell,
            result,
            cohort=cohort_name,
            network_path=network_path,
            base_ms=base_ms_per_cohort,
            phase=phase,
        ):
            writer.write(rec)

    def _write_grpc(cohort_name: M5_2CohortKind, result: GRPCCohortResult | None) -> None:
        if result is None:
            return
        if phase == "measurement" and result.warmup_samples:
            for rec in _grpc_samples_for_cell(
                measurement.cell,
                result,
                cohort=cohort_name,
                base_ms=base_ms_per_cohort,
                phase="warmup",
                samples_override=result.warmup_samples,
            ):
                writer.write(rec)
        for rec in _grpc_samples_for_cell(
            measurement.cell,
            result,
            cohort=cohort_name,
            base_ms=base_ms_per_cohort,
            phase=phase,
        ):
            writer.write(rec)

    _write_rest("rest_https_edge", "https_edge", measurement.rest_https_edge)
    _write_rest("rest_plain_tcp", "plain_tcp", measurement.rest_plain_tcp)
    _write_grpc("default_grpc", measurement.default_grpc)
    _write_grpc("tuned_grpc", measurement.tuned_grpc)
    _write_grpc("tuned_grpc_multiplexed", measurement.tuned_multiplexed)
    _write_grpc("tuned_grpc_channels", measurement.tuned_channels)


# ---------------------------------------------------------------------------
# CI math (paired-percentile bootstrap on medians) — milliseconds
# ---------------------------------------------------------------------------


def _bootstrap_delta_ci_ms(
    a_metric_seconds: list[float],
    b_metric_seconds: list[float],
    *,
    n_bootstrap: int = 1000,
    seed: int = 42,
) -> tuple[float, tuple[float, float]]:
    """Compute the (A - B) delta in milliseconds + 95% CI.

    A is the "first" cohort and B the "second" — for protocol-comparison
    rows, A is the gRPC cohort and B is the REST cohort (so negative delta
    means gRPC wins). For transport-only rows, A is rest_https_edge and B
    is rest_plain_tcp (so positive delta means HTTPS-edge is slower).
    """
    if not a_metric_seconds or not b_metric_seconds:
        return 0.0, (0.0, 0.0)
    median_a = statistics.median(a_metric_seconds)
    median_b = statistics.median(b_metric_seconds)
    delta_ms = (median_a - median_b) * 1000.0

    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(n_bootstrap):
        ras = [rng.choice(a_metric_seconds) for _ in range(len(a_metric_seconds))]
        rbs = [rng.choice(b_metric_seconds) for _ in range(len(b_metric_seconds))]
        deltas.append((statistics.median(ras) - statistics.median(rbs)) * 1000.0)
    if not deltas:
        return delta_ms, (delta_ms, delta_ms)
    deltas.sort()
    ci_low = deltas[int(0.025 * len(deltas))]
    ci_high = deltas[int(0.975 * len(deltas)) - 1] if len(deltas) > 1 else deltas[0]
    return delta_ms, (ci_low, ci_high)


def _grpc_metric_samples(result: GRPCCohortResult, path: str) -> list[float]:
    """Per-sample metric: TTFT seconds for chat_stream; wall_clock_seconds
    for embed."""
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


def _rest_metric_samples(result: RESTCohortResult) -> list[float]:
    """REST per-sample metric: ``wall_clock_seconds`` is TTFT for chat_stream
    and total wall-clock for embed."""
    return [s.wall_clock_seconds for s in result.samples]


def _protocol_comparison_verdict_literal(
    grpc_kind: M5_2CohortKind,
    ci_lower_ms: float,
    ci_upper_ms: float,
) -> ProtocolComparisonVerdict:
    """Decide the protocol-comparison verdict literal.

    Convention: delta = gRPC_median - REST_median. Negative means gRPC
    faster. Verdict is CI-supported only when the 95% CI is strictly on
    one side of zero. CI spans zero → ``no_winner``.
    """
    if ci_upper_ms < 0:
        # gRPC wins.
        if grpc_kind == "tuned_grpc_multiplexed":
            return "tuned_grpc_multiplexed_recommend"
        if grpc_kind == "tuned_grpc_channels":
            return "tuned_grpc_channels_recommend"
        if grpc_kind == "tuned_grpc":
            return "tuned_grpc_recommend"
        if grpc_kind == "default_grpc":
            return "default_grpc_recommend"
        raise ValueError(f"protocol comparison: unexpected grpc_kind {grpc_kind!r}")
    if ci_lower_ms > 0:
        return "rest_https_edge_recommend"
    return "no_winner"


def _transport_only_verdict_literal(ci_lower_ms: float, ci_upper_ms: float) -> TransportOnlyVerdict:
    """Decide the transport-only verdict literal.

    Convention: delta = rest_https_edge_median - rest_plain_tcp_median.
    Negative means HTTPS-edge is faster (rest_https_edge wins). Positive
    means plain-TCP wins. CI spans zero → no_winner.
    """
    if ci_upper_ms < 0:
        return "rest_https_edge_recommend"
    if ci_lower_ms > 0:
        return "rest_plain_tcp_recommend"
    return "no_winner"


# ---------------------------------------------------------------------------
# Verdict emission per cell
# ---------------------------------------------------------------------------


def emit_cell_verdicts(
    measurement: M5_2CellMeasurement,
    *,
    rtt_exercise_threshold_ms: float = 20.0,
) -> tuple[list[ProtocolComparisonRow], TransportOnlyRow]:
    """Emit the two verdict-family rows for one M5.2 cell per FR-009.

    Returns a list of ProtocolComparisonRow (one per gRPC cohort vs
    rest_https_edge) and a single TransportOnlyRow (rest_https_edge vs
    rest_plain_tcp).
    """
    cell = measurement.cell
    rest_https_samples = _rest_metric_samples(measurement.rest_https_edge)
    rest_tcp_samples = _rest_metric_samples(measurement.rest_plain_tcp)

    # Aggregate RTT across cohorts at this cell.
    rtt_medians = [
        measurement.rest_https_edge.rtt_record.median_ms
        if measurement.rest_https_edge.rtt_record is not None
        else 0.0,
        measurement.rest_plain_tcp.rtt_record.median_ms
        if measurement.rest_plain_tcp.rtt_record is not None
        else 0.0,
        measurement.default_grpc.rtt_record.median_ms,
    ]
    if measurement.tuned_grpc is not None:
        rtt_medians.append(measurement.tuned_grpc.rtt_record.median_ms)
    if measurement.tuned_multiplexed is not None:
        rtt_medians.append(measurement.tuned_multiplexed.rtt_record.median_ms)
    if measurement.tuned_channels is not None:
        rtt_medians.append(measurement.tuned_channels.rtt_record.median_ms)
    cell_rtt_median = statistics.median(rtt_medians)
    low_rtt = cell_rtt_median < rtt_exercise_threshold_ms

    # Protocol-comparison family.
    protocol_rows: list[ProtocolComparisonRow] = []
    grpc_cohorts: list[tuple[M5_2CohortKind, GRPCCohortResult]] = []
    if measurement.tuned_grpc is not None:
        grpc_cohorts.append(("tuned_grpc", measurement.tuned_grpc))
    if measurement.tuned_multiplexed is not None:
        grpc_cohorts.append(("tuned_grpc_multiplexed", measurement.tuned_multiplexed))
    if measurement.tuned_channels is not None:
        grpc_cohorts.append(("tuned_grpc_channels", measurement.tuned_channels))
    grpc_cohorts.append(("default_grpc", measurement.default_grpc))

    for kind, result in grpc_cohorts:
        grpc_samples = _grpc_metric_samples(result, cell.path)
        if not grpc_samples or not rest_https_samples:
            protocol_rows.append(
                ProtocolComparisonRow(
                    path=cell.path,  # type: ignore[arg-type]
                    hidden_size=cell.hidden_size,
                    concurrency=cell.concurrency,
                    grpc_cohort=kind,
                    verdict="comparison_unavailable",
                    comparison_unavailable_reason="empty_cohort_samples",
                    delta_median_ms=0.0,
                    ci_lower_ms=0.0,
                    ci_upper_ms=0.0,
                    low_rtt_caveat=low_rtt,
                )
            )
            continue
        delta_ms, (ci_low, ci_high) = _bootstrap_delta_ci_ms(grpc_samples, rest_https_samples)
        verdict = _protocol_comparison_verdict_literal(kind, ci_low, ci_high)
        protocol_rows.append(
            ProtocolComparisonRow(
                path=cell.path,  # type: ignore[arg-type]
                hidden_size=cell.hidden_size,
                concurrency=cell.concurrency,
                grpc_cohort=kind,
                verdict=verdict,
                comparison_unavailable_reason=None,
                delta_median_ms=delta_ms,
                ci_lower_ms=ci_low,
                ci_upper_ms=ci_high,
                low_rtt_caveat=low_rtt,
            )
        )

    # Transport-only family.
    if not rest_https_samples or not rest_tcp_samples:
        transport_row = TransportOnlyRow(
            path=cell.path,  # type: ignore[arg-type]
            hidden_size=cell.hidden_size,
            concurrency=cell.concurrency,
            verdict="comparison_unavailable",
            comparison_unavailable_reason="empty_cohort_samples",
            delta_median_ms=0.0,
            ci_lower_ms=0.0,
            ci_upper_ms=0.0,
            low_rtt_caveat=low_rtt,
        )
    else:
        delta_ms, (ci_low, ci_high) = _bootstrap_delta_ci_ms(rest_https_samples, rest_tcp_samples)
        transport_row = TransportOnlyRow(
            path=cell.path,  # type: ignore[arg-type]
            hidden_size=cell.hidden_size,
            concurrency=cell.concurrency,
            verdict=_transport_only_verdict_literal(ci_low, ci_high),
            comparison_unavailable_reason=None,
            delta_median_ms=delta_ms,
            ci_lower_ms=ci_low,
            ci_upper_ms=ci_high,
            low_rtt_caveat=low_rtt,
        )

    return protocol_rows, transport_row


# ---------------------------------------------------------------------------
# Smoke-specific assertion surface (FR-005a)
# ---------------------------------------------------------------------------


class M5_2SmokeAssertionFailure(RuntimeError):
    """Raised by the smoke assertion surface when an FR-005a clause fails.

    The exception message names the assertion + diverging field + observed
    vs expected so the operator can paste the line into the PR description
    if the smoke fails.
    """

    def __init__(self, name: str, diverging_field: str, observed: str, expected: str) -> None:
        self.name = name
        self.diverging_field = diverging_field
        self.observed = observed
        self.expected = expected
        super().__init__(
            f"M5_2SmokeAssertionFailure: {name}, field={diverging_field}, "
            f"observed={observed!r}, expected={expected!r}"
        )


class _HealthzProbe(Protocol):
    """Callable that returns (status_code, response_body, modal_deploy_header)."""

    async def __call__(self, url: str) -> tuple[int, str, str]: ...


async def assert_both_rest_transports_reach_same_modal_deploy(
    https_edge_url: str,
    plain_tcp_url: str,
    *,
    probe: _HealthzProbe,
) -> None:
    """FR-005a clause 1: both REST transports MUST reach the same in-container
    FastAPI shim. Verified by GET /healthz on both URLs and comparing the
    response body + Modal deploy handle header.
    """
    edge_status, edge_body, edge_handle = await probe(f"{https_edge_url.rstrip('/')}/healthz")
    tcp_status, tcp_body, tcp_handle = await probe(f"{plain_tcp_url.rstrip('/')}/healthz")
    if edge_status != 200 or tcp_status != 200:
        raise M5_2SmokeAssertionFailure(
            name="both_rest_transports_reach_same_modal_deploy",
            diverging_field="status_code",
            observed=f"{edge_status}/{tcp_status}",
            expected="200/200",
        )
    if edge_body != tcp_body:
        raise M5_2SmokeAssertionFailure(
            name="both_rest_transports_reach_same_modal_deploy",
            diverging_field="response_body",
            observed=tcp_body,
            expected=edge_body,
        )
    if edge_handle and tcp_handle and edge_handle != tcp_handle:
        raise M5_2SmokeAssertionFailure(
            name="both_rest_transports_reach_same_modal_deploy",
            diverging_field="modal_deploy_handle",
            observed=tcp_handle,
            expected=edge_handle,
        )


def assert_m5_2_json_schema_round_trips(tmp_path: Path) -> None:
    """FR-005a clause 2: writing a sample additive-fields payload and reading
    it back yields equivalent state. The smoke runs this BEFORE cohort
    dispatch so a schema break is surfaced early.
    """
    sample: dict[str, Any] = {
        "m5_2_run": {"run_id": "smoke-schema-roundtrip"},
        "symmetry": {
            "tier_a": {
                "prompt_corpus_hash": "0" * 64,
                "modal_deploy_handle": "smoke-handle",
                "mock_engine_config_digest": "1" * 64,
                "warmup_batch_policy": "discard_first_5_measurement_n_5",
            },
            "tier_b": {
                "rest_client_config_digest_url_excepted": "2" * 64,
                "tuned_grpc_channel_config_digest_topology_excepted": None,
            },
            "tier_c": [],
        },
        "events_sidecar_path": "bench-results/m5_2-full/smoke.events.jsonl.gz",
        "events_sidecar_sha256": "3" * 64,
        "protocol_comparison_verdicts": [],
        "transport_only_verdicts": [],
        "supersedes_m5_1": [],
        "payload_parity_audit": {
            "no_regression_confirmed_against_pr": "smoke",
            "measured_payload_bytes": {},
        },
        "smoke_run_outcome": {
            "iso": "2026-05-12T12:00:00Z",
            "asserted_clauses_count": 4,
            "per_cohort_rtt_probe_medians_ms": {},
        },
        "https_edge_vs_plain_tcp_rtt_delta_median_ms": 0.0,
        "https_edge_vs_plain_tcp_rtt_delta_p95_ms": 0.0,
        "modal_region": "eu-west-1",
        "modal_instance_class": "cpu",
        "https_edge_endpoint": "https://smoke.modal.run",
        "client_external_geolocation": None,
    }
    schema_path = tmp_path / "smoke_m5_2_schema.json"
    schema_path.write_text(
        json.dumps(sample, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    read_back = json.loads(schema_path.read_text())
    if read_back != sample:
        raise M5_2SmokeAssertionFailure(
            name="m5_2_json_schema_round_trips",
            diverging_field="payload",
            observed=str(read_back)[:200],
            expected=str(sample)[:200],
        )


def assert_per_cohort_rtt_probe_within_thresholds_all_five_cohorts(
    cohort_rtt_medians_ms: dict[str, float],
    *,
    validity_threshold_ms: float = 1.0,
) -> None:
    """FR-005a clause 3: every cohort's RTT probe must clear the validity
    threshold. ``cohort_rtt_medians_ms`` keys are the cohort names. At
    c >= 2 all five are expected; at c == 1 the two tuned cohorts collapse
    to ``tuned_grpc`` (four keys instead of five).
    """
    expected_keys = {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
    }
    # The caller can pass either the c>=2 quintet or the c=1 quadruple.
    tuned_keys = {"tuned_grpc_multiplexed", "tuned_grpc_channels", "tuned_grpc"}
    observed_tuned = cohort_rtt_medians_ms.keys() & tuned_keys
    if not observed_tuned:
        raise M5_2SmokeAssertionFailure(
            name="per_cohort_rtt_probe_within_thresholds_all_five_cohorts",
            diverging_field="tuned_cohort_present",
            observed="<none>",
            expected="at least one of tuned_grpc{,_multiplexed,_channels}",
        )
    expected_keys |= observed_tuned
    missing = expected_keys - cohort_rtt_medians_ms.keys()
    if missing:
        raise M5_2SmokeAssertionFailure(
            name="per_cohort_rtt_probe_within_thresholds_all_five_cohorts",
            diverging_field="missing_cohorts",
            observed=",".join(sorted(missing)),
            expected="all five cohorts present",
        )
    for cohort, rtt in cohort_rtt_medians_ms.items():
        if rtt < validity_threshold_ms:
            raise M5_2SmokeAssertionFailure(
                name="per_cohort_rtt_probe_within_thresholds_all_five_cohorts",
                diverging_field=f"rtt_{cohort}",
                observed=f"{rtt:.3f} ms",
                expected=f">= {validity_threshold_ms:.3f} ms",
            )


# ---------------------------------------------------------------------------
# Run config + top-level orchestrator
# ---------------------------------------------------------------------------


@dataclass
class M5_2Run:
    """Top-level result of an M5.2 sweep run. Returned by run_m5_2_sweep.

    Carries the in-memory artifacts the regenerator + reporter consume to
    produce the markdown + aggregate JSON. The harness writes the run
    config JSON sidecar to disk; the markdown is the regenerator's job.
    """

    run_id: str
    run_started_at_iso: str
    run_realized_runtime_s: float
    seed: int

    symmetry: SymmetryBlock

    events_sidecar_path: Path
    events_sidecar_sha256: str

    protocol_comparison_verdicts: list[ProtocolComparisonRow]
    transport_only_verdicts: list[TransportOnlyRow]

    rest_https_edge_results: list[RESTCohortResult]
    rest_plain_tcp_results: list[RESTCohortResult]
    grpc_results: list[tuple[M5_2CohortKind, GRPCCohortResult]]

    modal_region: str
    modal_instance_class: str
    https_edge_endpoint: str
    client_external_geolocation_country: str | None
    client_external_geolocation_region: str | None

    https_edge_vs_plain_tcp_rtt_delta_median_ms: float
    https_edge_vs_plain_tcp_rtt_delta_p95_ms: float

    smoke: bool = False
    # Per-cell crash log per FR-005. One entry per (cell × exception) when the
    # sweep's per-cell try/except catches a dispatch failure. The regenerator
    # surfaces these as comparison_unavailable rows in the markdown's
    # negative-results appendix so a reader can see which cells were
    # incomplete and why. Empty on a clean run.
    failed_cells: list[dict[str, Any]] = field(default_factory=list)


def _build_cohort_configs_for_symmetry(config: M5_2SweepConfig) -> list[CohortConfigInput]:
    """Build the per-cohort symmetry-block inputs from the sweep config.

    Five cohorts are present at every config (c >= 2 cells); at c == 1
    the tuned-pair collapses to a single tuned_grpc. The pre-flight
    symmetry assertion uses the c-aware skip path in
    :func:`assert_symmetry`.
    """
    common = {
        "prompt_corpus_hash": canonical_digest({"seed": config.seed, "n": config.n_per_cohort}),
        "modal_deploy_handle": f"{config.modal_app_handle}-{config.run_id}",
        "modal_app_handle": config.modal_app_handle,
        "modal_region": config.modal_region,
        "mock_engine_config_digest": canonical_digest(
            {"hidden_size": 4096, "seed": 0, "tokens_per_second": 200.0, "pace_tokens": False}
        ),
        "warmup_batch_policy": (
            f"discard_first_{config.warmup_n}_measurement_n_{config.n_per_cohort}"
        ),
        "warmup_batch_size": config.warmup_n,
    }
    cfgs: list[CohortConfigInput] = []
    cfgs.append(
        CohortConfigInput(
            cohort="rest_https_edge",
            client_config_full={
                "base_url": config.rest_https_edge_url,
                "http2": False,
                "timeout_s": config.timeout_s,
            },
            rest_url_excepted_field="base_url",
            **common,
        )
    )
    cfgs.append(
        CohortConfigInput(
            cohort="rest_plain_tcp",
            client_config_full={
                "base_url": config.rest_plain_tcp_url,
                "http2": False,
                "timeout_s": config.timeout_s,
            },
            rest_url_excepted_field="base_url",
            **common,
        )
    )
    cfgs.append(
        CohortConfigInput(
            cohort="default_grpc",
            client_config_full={"channel_topology": "default", "channel_config": "m1_baseline"},
            **common,
        )
    )
    cells = list(config.cells_override) if config.cells_override else enumerate_cells()
    has_c1 = any(c.concurrency == 1 for c in cells)
    has_cge2 = any(c.concurrency >= 2 for c in cells)
    if has_cge2:
        cfgs.append(
            CohortConfigInput(
                cohort="tuned_grpc_multiplexed",
                client_config_full={
                    "channel_topology": "multiplexed",
                    "channel_config": "m5_1_frozen_tuned",
                    "timeout_s": config.timeout_s,
                },
                grpc_topology_excepted_field="channel_topology",
                **common,
            )
        )
        cfgs.append(
            CohortConfigInput(
                cohort="tuned_grpc_channels",
                client_config_full={
                    "channel_topology": "channels",
                    "channel_config": "m5_1_frozen_tuned",
                    "timeout_s": config.timeout_s,
                },
                grpc_topology_excepted_field="channel_topology",
                **common,
            )
        )
    if has_c1 and not has_cge2:
        cfgs.append(
            CohortConfigInput(
                cohort="tuned_grpc",
                client_config_full={
                    "channel_topology": "single",
                    "channel_config": "m5_1_frozen_tuned",
                    "timeout_s": config.timeout_s,
                },
                **common,
            )
        )
    return cfgs


async def run_m5_2_sweep(config: M5_2SweepConfig, *, progress: bool = True) -> M5_2Run:
    """Top-level entry point.

    Steps per ``contracts/m5_2-bench-cli.md`` §"Behavior — `--m5_2`":

    1. Resolve token, build the 3-tier symmetry block, assert tier (a) +
       tier (b) (skipping c=1 tuned-pair).
    2. Open the EventsSidecarWriter and write a skeleton run config
       (``events_sidecar_sha256=""`` placeholder). A crash before the first
       cell still leaves a regeneratable metadata artifact.
    3. Run warmup cohorts (writer phase=warmup); records persist but are
       excluded from aggregates.
    4. For each cell: try ``dispatch_cell → write_cell_events →
       emit_cell_verdicts``. On exception, log type + traceback to stderr,
       record the cell in ``failed_cells``, continue. Per-cell isolation
       per FR-005 — a single cohort failure is documented, not fatal.
    5. Close the writer; capture (gzipped_path, sha256). Update the run
       config with the real sha + failed_cells list. The regenerator can
       then run on the partial sweep.
    """
    token = os.environ.get(config.token_env_var, "")
    if not token:
        raise RuntimeError(f"Bearer-token env var {config.token_env_var!r} is not set.")

    cells = list(config.cells_override) if config.cells_override else enumerate_cells()
    concurrency_levels = sorted({c.concurrency for c in cells})

    cohort_configs = _build_cohort_configs_for_symmetry(config)
    block = build_symmetry_block(
        cohort_configs,
        client_external_geolocation_country=config.client_external_geolocation_country,
        client_external_geolocation_region=config.client_external_geolocation_region,
    )
    assert_symmetry(block, cohort_configs, concurrency_levels=concurrency_levels)

    rest_https_results: list[RESTCohortResult] = []
    rest_tcp_results: list[RESTCohortResult] = []
    grpc_results: list[tuple[M5_2CohortKind, GRPCCohortResult]] = []
    protocol_rows: list[ProtocolComparisonRow] = []
    transport_rows: list[TransportOnlyRow] = []
    failed_cells: list[dict[str, Any]] = []

    run_started = time.monotonic()
    run_started_at_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    config.events_sidecar_out_dir.mkdir(parents=True, exist_ok=True)

    # Skeleton run config — written before any cell dispatches so a crash
    # before the first measurement still leaves a regeneratable metadata
    # artifact. The events_sidecar_sha256 is filled in at sweep completion
    # (the gzipped sidecar's hash isn't knowable until __exit__ runs).
    _write_skeleton_run_config(
        config=config,
        block=block,
        run_started_at_iso=run_started_at_iso,
    )

    writer = EventsSidecarWriter(config.events_sidecar_out_dir, config.run_id)
    writer.__enter__()
    try:
        for idx, cell in enumerate(cells):
            if progress:
                print(
                    f"[m5_2] {idx + 1}/{len(cells)} dispatching cell {cell.key}",
                    flush=True,
                )
            try:
                tuned_cfg = frozen_tuned_channel_config(
                    cell.path,
                    cell.hidden_size,
                    m5_report_path=config.m5_report_path,
                )
                measurement = await dispatch_cell(
                    cell,
                    rest_https_edge_url=config.rest_https_edge_url,
                    rest_plain_tcp_url=config.rest_plain_tcp_url,
                    grpc_target=config.grpc_target,
                    token=token,
                    n=config.n_per_cohort,
                    tuned_channel_config=tuned_cfg,
                    timeout_s=config.timeout_s,
                    rtt_probe_n=config.rtt_probe_n,
                    warmup_n=config.warmup_n,
                    https_edge_endpoint=config.https_edge_endpoint,
                    client_external_geolocation_country=config.client_external_geolocation_country,
                    client_external_geolocation_region=config.client_external_geolocation_region,
                )
                write_cell_events_to_sidecar(measurement, writer)
                rows, t_row = emit_cell_verdicts(
                    measurement,
                    rtt_exercise_threshold_ms=config.rtt_exercise_threshold_ms,
                )
                protocol_rows.extend(rows)
                transport_rows.append(t_row)
                rest_https_results.append(measurement.rest_https_edge)
                rest_tcp_results.append(measurement.rest_plain_tcp)
                grpc_results.append(("default_grpc", measurement.default_grpc))
                if measurement.tuned_grpc is not None:
                    grpc_results.append(("tuned_grpc", measurement.tuned_grpc))
                if measurement.tuned_multiplexed is not None:
                    grpc_results.append(("tuned_grpc_multiplexed", measurement.tuned_multiplexed))
                if measurement.tuned_channels is not None:
                    grpc_results.append(("tuned_grpc_channels", measurement.tuned_channels))
            except Exception as cell_exc:  # noqa: BLE001
                import traceback as _tb

                tb_str = "".join(_tb.format_exception(cell_exc))
                print(
                    f"[m5_2] CELL FAILED {idx + 1}/{len(cells)} {cell.key}: "
                    f"type={type(cell_exc).__name__} repr={cell_exc!r}",
                    file=sys.stderr,
                    flush=True,
                )
                print(tb_str, file=sys.stderr, flush=True)
                failed_cells.append(
                    {
                        "path": cell.path,
                        "hidden_size": cell.hidden_size,
                        "concurrency": cell.concurrency,
                        "exception_type": type(cell_exc).__name__,
                        "exception_repr": repr(cell_exc),
                        "traceback": tb_str,
                    }
                )
                continue
    finally:
        writer.__exit__(None, None, None)

    sidecar_path, sidecar_sha = writer.result

    # Run-level HTTPS-edge vs plain-TCP RTT delta.
    edge_rtts = [r.rtt_record.median_ms for r in rest_https_results if r.rtt_record is not None]
    tcp_rtts = [r.rtt_record.median_ms for r in rest_tcp_results if r.rtt_record is not None]
    delta_med = (
        statistics.median(edge_rtts) - statistics.median(tcp_rtts)
        if edge_rtts and tcp_rtts
        else 0.0
    )
    edge_p95 = [r.rtt_record.p95_ms for r in rest_https_results if r.rtt_record is not None]
    tcp_p95 = [r.rtt_record.p95_ms for r in rest_tcp_results if r.rtt_record is not None]
    delta_p95 = (
        statistics.median(edge_p95) - statistics.median(tcp_p95) if edge_p95 and tcp_p95 else 0.0
    )

    run = M5_2Run(
        run_id=config.run_id,
        run_started_at_iso=run_started_at_iso,
        run_realized_runtime_s=time.monotonic() - run_started,
        seed=config.seed,
        symmetry=block,
        events_sidecar_path=sidecar_path,
        events_sidecar_sha256=sidecar_sha,
        protocol_comparison_verdicts=protocol_rows,
        transport_only_verdicts=transport_rows,
        rest_https_edge_results=rest_https_results,
        rest_plain_tcp_results=rest_tcp_results,
        grpc_results=grpc_results,
        modal_region=config.modal_region,
        modal_instance_class=config.modal_instance_class,
        https_edge_endpoint=config.https_edge_endpoint,
        client_external_geolocation_country=config.client_external_geolocation_country,
        client_external_geolocation_region=config.client_external_geolocation_region,
        https_edge_vs_plain_tcp_rtt_delta_median_ms=delta_med,
        https_edge_vs_plain_tcp_rtt_delta_p95_ms=delta_p95,
        smoke=config.smoke,
        failed_cells=failed_cells,
    )

    _write_run_config_json(run, config)
    if failed_cells and progress:
        print(
            f"[m5_2] sweep complete with {len(failed_cells)} failed cell(s): "
            + ", ".join(
                f"{f['path']}:h{f['hidden_size']}:c{f['concurrency']}({f['exception_type']})"
                for f in failed_cells
            ),
            file=sys.stderr,
            flush=True,
        )
    return run


def _write_skeleton_run_config(
    *,
    config: M5_2SweepConfig,
    block: SymmetryBlock,
    run_started_at_iso: str,
) -> Path:
    """Write a placeholder run config JSON before any cell dispatches.

    A crash before the first measurement still leaves a metadata artifact
    on disk (with ``events_sidecar_sha256=""`` as the placeholder). The
    final run config — overwriting this file — is written by
    :func:`_write_run_config_json` once the sidecar has been gzipped and
    its SHA-256 is known.
    """
    out_path = config.events_sidecar_out_dir / f"{config.run_id}.run_config.json"
    payload: dict[str, Any] = {
        "run_id": config.run_id,
        "run_started_at_iso": run_started_at_iso,
        "run_realized_runtime_s": 0.0,
        "seed": config.seed,
        "symmetry": _symmetry_to_dict(block),
        "events_sidecar_path": str(
            config.events_sidecar_out_dir / f"{config.run_id}.events.jsonl.gz"
        ),
        "events_sidecar_sha256": "",
        "modal_region": config.modal_region,
        "modal_instance_class": config.modal_instance_class,
        "https_edge_endpoint": config.https_edge_endpoint,
        "client_external_geolocation": (
            None
            if config.client_external_geolocation_country is None
            else {
                "country": config.client_external_geolocation_country,
                "region": config.client_external_geolocation_region or "",
            }
        ),
        "payload_parity_audit": {
            "no_regression_confirmed_against_pr": "",
            "measured_payload_bytes": {},
        },
        "smoke_run_outcome": {
            "iso": run_started_at_iso,
            "asserted_clauses_count": 0,
            "per_cohort_rtt_probe_medians_ms": {},
        },
        "failed_cells": [],
    }
    out_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return out_path


def _write_run_config_json(run: M5_2Run, config: M5_2SweepConfig) -> Path:
    """Persist the run config JSON sidecar under
    ``bench-results/m5_2-full/{run_id}.run_config.json``. The regenerator
    reads this to validate the events sidecar's SHA-256 and to re-assert
    the symmetry block at report-build time per FR-012b.

    Overwrites the skeleton written by :func:`_write_skeleton_run_config`
    at sweep start; on a clean sweep these two files are identical except
    for the now-real ``events_sidecar_sha256`` and ``run_realized_runtime_s``.
    """
    out_path = config.events_sidecar_out_dir / f"{run.run_id}.run_config.json"

    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "run_started_at_iso": run.run_started_at_iso,
        "run_realized_runtime_s": run.run_realized_runtime_s,
        "seed": run.seed,
        "symmetry": _symmetry_to_dict(run.symmetry),
        "events_sidecar_path": str(run.events_sidecar_path),
        "events_sidecar_sha256": run.events_sidecar_sha256,
        "modal_region": run.modal_region,
        "modal_instance_class": run.modal_instance_class,
        "https_edge_endpoint": run.https_edge_endpoint,
        "failed_cells": run.failed_cells,
        "client_external_geolocation": (
            None
            if run.client_external_geolocation_country is None
            else {
                "country": run.client_external_geolocation_country,
                "region": run.client_external_geolocation_region or "",
            }
        ),
        # Operator-supplied (Phase J) — pre-populated empty by the harness so
        # the schema validates; the operator updates this in-place before
        # invoking the regenerator.
        "payload_parity_audit": {
            "no_regression_confirmed_against_pr": "",
            "measured_payload_bytes": {},
        },
        # Operator copies the smoke-gate's structured PASS line into this
        # block; the harness emits empties so the schema validates.
        "smoke_run_outcome": {
            "iso": run.run_started_at_iso,
            "asserted_clauses_count": 0,
            "per_cohort_rtt_probe_medians_ms": {},
        },
    }
    out_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return out_path


def _symmetry_to_dict(block: SymmetryBlock) -> dict[str, Any]:
    """Serialize a SymmetryBlock to a plain dict for the run config JSON."""
    return {
        "tier_a": {
            "prompt_corpus_hash": block.tier_a.prompt_corpus_hash,
            "modal_deploy_handle": block.tier_a.modal_deploy_handle,
            "mock_engine_config_digest": block.tier_a.mock_engine_config_digest,
            "warmup_batch_policy": block.tier_a.warmup_batch_policy,
        },
        "tier_b": {
            "rest_client_config_digest_url_excepted": (
                block.tier_b.rest_client_config_digest_url_excepted
            ),
            "tuned_grpc_channel_config_digest_topology_excepted": (
                block.tier_b.tuned_grpc_channel_config_digest_topology_excepted
            ),
        },
        "tier_c": [
            {
                "cohort": m.cohort,
                "client_config_digest_full": m.client_config_digest_full,
                "modal_app_handle": m.modal_app_handle,
                "modal_region": m.modal_region,
                "warmup_batch_size": m.warmup_batch_size,
                "tier_b_skipped_c1_tuned_grpc_pair": m.tier_b_skipped_c1_tuned_grpc_pair,
            }
            for m in block.tier_c
        ],
        "client_external_geolocation_country": block.client_external_geolocation_country,
        "client_external_geolocation_region": block.client_external_geolocation_region,
    }
