"""M5 cross-host sweep orchestrator.

Wraps M4's harness with cross-host concerns (research.md R-2…R-5):

* Pre-cohort active RTT probe (``rtt_probe.measure_rtt``) — every cohort.
* ``server_bound`` classifier (R-4) — parallel to M4's ``client_bound``.
* ``low_rtt_caveat`` annotator — set when measured RTT falls below the
  FR-004 exercise threshold (default 20.0 ms).
* Warm-up cohort discard (R-5) — one per path, ``discarded=True``,
  excluded from every aggregate computation.
* Cross-host shared-baseline measurement (FR-008) — per path, at
  ``schema_canonical_width``, against the Modal-hosted endpoint.
* Recommendation builder that consults M4's published report for
  ``supersedes_m4_cell`` cross-references (FR-015 prelude — the full
  Supersedes-M4 table builder lives in ``m5_supersede``).

The M5 sweep delegates per-cohort measurement to ``m4_sweep._measure_cell``
with a non-default ``endpoint_provider`` so the M4 borderline-expand
cascade, warmup handling, and TTFT aggregation all behave bit-identically
to the M4 sweep — only the channel construction is swapped (loopback →
Modal-tunnel + TLS + bearer-token metadata).
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import grpc

from vllm_grpc_bench.channel_config import M1_BASELINE, ChannelConfig
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    EndpointProvider,
    EndpointTuple,
    ExpansionRecord,
    FrozenChannelBaseline,
    M4SweepConfig,
    M5CrossHostBaseline,
    M5RunMetadata,
    Path_,
    Recommendation,
    RTTRecord,
    RTTSummary,
    Run,
    RunCohort,
    SchemaCandidatePerWidth,
    SchemaCandidateResult,
    SupersedesM4Entry,
    Verdict,
    non_discarded,
)
from vllm_grpc_bench.rtt_probe import (
    is_below_exercise_threshold,
    is_below_validity_threshold,
    measure_rtt,
)

if TYPE_CHECKING:
    from vllm_grpc_bench.mock_engine import MockEngine

_SERVER_BOUND_FLOOR_MS: float = 50.0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class M5SweepConfig:
    """M5 sweep configuration. Composes M4SweepConfig with M5-specific knobs."""

    base: M4SweepConfig
    modal_region: str = "us-east-1"
    token_env: str = "MODAL_BENCH_TOKEN"
    rtt_validity_threshold_ms: float = 1.0
    rtt_exercise_threshold_ms: float = 20.0
    warmup_n: int = 32
    rtt_probe_n: int = 32
    modal_app_name: str = "vllm-grpc-bench-mock"
    # Operator-supplied static endpoint (skip-deploy path). When set, the
    # harness uses ``modal_endpoint.static_endpoint_provider`` instead of
    # ``provide_endpoint`` — no app.run(), no teardown handshake.
    skip_deploy_endpoint: str | None = None
    # Path to M4's published report. Read at orchestration time so the
    # ``server_bound`` classifier can pull per-path client-overhead floors
    # and ``Recommendation.supersedes_m4_cell`` can populate cross-refs.
    m4_report_path: Path = field(
        default_factory=lambda: Path("docs/benchmarks/m4-time-axis-tuning.json")
    )

    def __post_init__(self) -> None:
        if self.rtt_validity_threshold_ms < 0:
            raise ValueError("rtt_validity_threshold_ms must be >= 0")
        if self.rtt_exercise_threshold_ms < self.rtt_validity_threshold_ms:
            raise ValueError(
                "rtt_exercise_threshold_ms must be >= rtt_validity_threshold_ms "
                "(below the validity threshold the verdict is refused; the exercise "
                "threshold cannot be more permissive than the refusal threshold)"
            )
        if self.warmup_n < 0:
            raise ValueError("warmup_n must be >= 0")
        if self.rtt_probe_n < 1:
            raise ValueError("rtt_probe_n must be >= 1")


@dataclass(frozen=True)
class _M4ConstantsForClassifier:
    """Per-path constants pulled from M4's published report (R-4)."""

    client_overhead_floor_ms: dict[Path_, float]
    loopback_cv: dict[Path_, float]


# ---------------------------------------------------------------------------
# server_bound classifier (R-4 / FR-005)
# ---------------------------------------------------------------------------


def classify_server_bound(
    cohort: RunCohort,
    rtt_record: RTTRecord,
    *,
    m4_client_overhead_floor_ms: float,
    m4_loopback_cv: float | None,
    floor_ms: float = _SERVER_BOUND_FLOOR_MS,
) -> tuple[float, bool]:
    """Return ``(server_overhead_estimate_ms, server_bound_flag)``.

    ``server_overhead_estimate_ms`` is computed per R-4:
        cohort_median_wallclock_ms − cohort_median_rtt_ms − m4_client_overhead_floor_ms

    Flag is True iff:
        server_overhead_estimate_ms > max(2 × rtt_median_ms, floor_ms)
        AND (the cohort's verdict-metric CV is materially worse than M4's loopback CV,
             i.e., ``cohort.time_cv > 2 × m4_loopback_cv`` — CV gate)

    The 2× CV gate ensures only *unstable* server overhead trips the flag.
    When ``m4_loopback_cv`` is unknown (M4 didn't record one for this path),
    the CV gate is skipped and the flag is set on the overhead-only signal.
    """
    cohort_median_ms = cohort.time_mean * 1000.0
    server_overhead_estimate_ms = (
        cohort_median_ms - rtt_record.median_ms - m4_client_overhead_floor_ms
    )
    overhead_threshold = max(2.0 * rtt_record.median_ms, floor_ms)
    overhead_dominates = server_overhead_estimate_ms > overhead_threshold
    if not overhead_dominates:
        return server_overhead_estimate_ms, False
    cohort_cv = cohort.time_cv
    if cohort_cv is None or m4_loopback_cv is None:
        return server_overhead_estimate_ms, True
    cv_gate_trips = cohort_cv > 2.0 * m4_loopback_cv
    return server_overhead_estimate_ms, cv_gate_trips


def annotate_low_rtt_caveat(rtt_record: RTTRecord, threshold_ms: float) -> bool:
    """FR-004: ``True`` when the cohort's median RTT falls below the exercise
    threshold (default 20 ms). Caveated cohorts still produce verdicts; the
    flag tells the reader to discount RTT-bounded-axis verdicts from this
    cell.
    """
    return is_below_exercise_threshold(rtt_record, threshold_ms)


# ---------------------------------------------------------------------------
# M4-report constants loader
# ---------------------------------------------------------------------------


def load_m4_constants(report_path: Path) -> _M4ConstantsForClassifier:
    """Read per-path ``client_overhead_floor_ms`` and ``loopback_cv`` from M4's
    published report. Returns conservative defaults when the report is
    absent or doesn't carry the field (fresh checkouts before M4 ships).
    """
    defaults = _M4ConstantsForClassifier(
        client_overhead_floor_ms={"chat_stream": 1.0, "embed": 0.5},
        loopback_cv={"chat_stream": 0.05, "embed": 0.05},
    )
    if not report_path.exists():
        return defaults
    try:
        payload = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError):
        return defaults
    # The M4 schema doesn't currently surface a per-path overhead floor; we
    # derive one from the published shared-baseline cohort wall-clock as a
    # conservative estimate (the baseline is the lowest-overhead cohort).
    floors: dict[Path_, float] = dict(defaults.client_overhead_floor_ms)
    cvs: dict[Path_, float] = dict(defaults.loopback_cv)
    cohorts = payload.get("cohorts", [])
    baseline_ids = payload.get("shared_baseline_cohort_ids", {})
    for cohort in cohorts:
        if not isinstance(cohort, dict):
            continue
        cohort_id = cohort.get("cell_id") or cohort.get("cohort_id")
        path = cohort.get("path")
        if path not in ("embed", "chat_stream"):
            continue
        # Use the shared baseline's wall-clock median as the floor.
        if cohort_id and cohort_id == baseline_ids.get(path):
            time_seconds = cohort.get("time_seconds", {}) or cohort.get("time", {})
            mean_seconds = time_seconds.get("mean") if isinstance(time_seconds, dict) else None
            if isinstance(mean_seconds, (int, float)) and mean_seconds > 0:
                floors[path] = float(mean_seconds) * 1000.0
        cv_time = cohort.get("cv_time") or cohort.get("time_cv")
        if isinstance(cv_time, (int, float)) and cv_time > 0:
            cvs[path] = float(cv_time)
    return _M4ConstantsForClassifier(
        client_overhead_floor_ms=floors,
        loopback_cv=cvs,
    )


# ---------------------------------------------------------------------------
# Deploy-once endpoint reuse
# ---------------------------------------------------------------------------


def make_frozen_endpoint_provider(
    target: str,
    credentials: grpc.ChannelCredentials | None,
    metadata: tuple[tuple[str, str], ...] | None,
) -> EndpointProvider:
    """Wrap a captured ``EndpointTuple`` as a no-op ``EndpointProvider``.

    The M4 harness re-enters its ``endpoint_provider`` once per cohort. For
    in-process backends that's cheap; for the Modal-backed M5 provider it
    would mean a fresh deploy per cohort. Instead, ``run_m5_sweep`` enters
    ``modal_endpoint.provide_endpoint`` once at the start of the sweep,
    captures the target/credentials/metadata, and threads this frozen
    provider into every per-cohort call — yielding the same tuple each time
    without contacting Modal.
    """

    @asynccontextmanager
    async def _provider(
        engine: MockEngine,
        channel_config: ChannelConfig,
    ) -> AsyncIterator[EndpointTuple]:
        yield (target, credentials, metadata)

    return _provider


# ---------------------------------------------------------------------------
# Cohort drivers — wrap M4's drivers with the M5 endpoint provider
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _open_probe_channel(
    target: str,
    credentials: grpc.ChannelCredentials | None,
    client_options: tuple[Any, ...] | None = None,
) -> AsyncIterator[grpc.aio.Channel]:
    kwargs: dict[str, Any] = {}
    if client_options:
        kwargs["options"] = list(client_options)
    if credentials is None:
        async with grpc.aio.insecure_channel(target, **kwargs) as channel:
            yield channel
    else:
        async with grpc.aio.secure_channel(target, credentials, **kwargs) as channel:
            yield channel


async def _measure_cohort_with_rtt(
    cell: BenchmarkCell,
    *,
    seed: int,
    config: M5SweepConfig,
    endpoint_provider: EndpointProvider,
    constants: _M4ConstantsForClassifier,
    discarded: bool = False,
) -> RunCohort:
    """Run RTT probe → cohort measurement → server_bound classification →
    low_rtt_caveat annotation. Returns the fully-annotated cohort.

    Refuses to measure (raises ``ValueError`` mapped to exit code 8) when
    the cohort's measured median RTT falls below the validity threshold —
    the connection has unexpectedly resolved to a same-host route.
    """
    from vllm_grpc_bench.m4_sweep import _measure_cell

    # Step 1 — probe RTT first against the same channel the cohort will use.
    async with endpoint_provider(_engine_for(cell), cell.channel_config) as endpoint_tuple:
        target, credentials, metadata = endpoint_tuple
        async with _open_probe_channel(
            target, credentials, cell.channel_config.client_options
        ) as probe_channel:
            rtt_record = await measure_rtt(probe_channel, n=config.rtt_probe_n, metadata=metadata)
    if is_below_validity_threshold(rtt_record, config.rtt_validity_threshold_ms):
        # The probe channel is now closed; the cohort path will refuse below.
        # We still want to emit a cohort entry with the RTT record so the
        # reader sees what happened. Return a not_measurable shell cohort.
        return _shell_cohort_not_measurable(cell, rtt_record, reason="rtt_below_validity_threshold")

    # Step 2 — measure the cohort itself via M4's harness machinery.
    cohort = await _measure_cell(
        cell,
        seed=seed,
        pace_tokens=(config.base.pacing_mode == "paced"),
        warmup_n=0,  # M5 manages warmup via a dedicated discarded cohort (R-5).
        endpoint_provider=endpoint_provider,
    )

    # Step 3 — classify server_bound + annotate low_rtt_caveat.
    floor_ms = constants.client_overhead_floor_ms.get(cell.path, 1.0)
    loopback_cv = constants.loopback_cv.get(cell.path)
    server_overhead_ms, server_bound_flag = classify_server_bound(
        cohort, rtt_record, m4_client_overhead_floor_ms=floor_ms, m4_loopback_cv=loopback_cv
    )
    low_rtt_caveat = annotate_low_rtt_caveat(rtt_record, config.rtt_exercise_threshold_ms)

    return replace(
        cohort,
        rtt_record=rtt_record,
        server_overhead_estimate_ms=server_overhead_ms,
        server_bound=server_bound_flag,
        low_rtt_caveat=low_rtt_caveat,
        discarded=discarded,
    )


def _engine_for(cell: BenchmarkCell) -> MockEngine:
    """Build a per-cohort MockEngine (M5 harness-side parity with M4)."""
    from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig

    long_stream = cell.corpus_subset == "m3_long_stream"
    return MockEngine(
        MockEngineConfig(
            hidden_size=cell.hidden_size,
            seed=0,
            tokens_per_second=20.0 if long_stream else 200.0,
            max_tokens_per_stream=2048 if long_stream else 64,
            pace_tokens=False,
        )
    )


def _shell_cohort_not_measurable(
    cell: BenchmarkCell, rtt_record: RTTRecord, *, reason: str
) -> RunCohort:
    """Build a ``not_measurable`` cohort shell for an RTT-validity-failed cell."""
    return RunCohort(
        cell=cell,
        samples=(),
        n_successful=0,
        bytes_mean=0.0,
        bytes_ci_low=0.0,
        bytes_ci_high=0.0,
        time_mean=0.0,
        time_ci_low=0.0,
        time_ci_high=0.0,
        measurable=False,
        rtt_record=rtt_record,
        server_overhead_estimate_ms=None,
        server_bound=False,
        low_rtt_caveat=False,
        discarded=False,
    )


# ---------------------------------------------------------------------------
# Warm-up cohort handling (R-5)
# ---------------------------------------------------------------------------


async def run_warmup_cohorts(
    config: M5SweepConfig,
    endpoint_provider: EndpointProvider,
    constants: _M4ConstantsForClassifier,
) -> list[RunCohort]:
    """Run one warm-up cohort per path; tag ``discarded=True``. R-5."""
    if config.warmup_n == 0:
        print(
            "WARNING: --m5-warmup-n=0 — first cohort cost may be dominated by "
            "cold-start (per research.md R-5)",
            file=sys.stderr,
        )
        return []
    cohorts: list[RunCohort] = []
    for path in config.base.paths:
        corpus = "m1_embed" if path == "embed" else "m1_chat"
        cell = BenchmarkCell(
            path=path,
            hidden_size=config.base.schema_canonical_width,
            channel_config=M1_BASELINE,
            corpus_subset=corpus,  # type: ignore[arg-type]
            iterations=config.warmup_n,
        )
        # Warmup-cohort seed sits in a high band so cohort_id collisions with
        # the candidate seeds (which use ``seed + (idx + 1) * 1000``) are
        # impossible. Negative seeds are rejected by ``MockEngineConfig``.
        cohort = await _measure_cohort_with_rtt(
            cell,
            seed=config.base.seed + 990_000,
            config=config,
            endpoint_provider=endpoint_provider,
            constants=constants,
            discarded=True,
        )
        cohorts.append(cohort)
    return cohorts


# ---------------------------------------------------------------------------
# Cross-host shared baseline (FR-008)
# ---------------------------------------------------------------------------


async def measure_m5_shared_baseline(
    config: M5SweepConfig,
    endpoint_provider: EndpointProvider,
    constants: _M4ConstantsForClassifier,
) -> tuple[dict[Path_, RunCohort], dict[Path_, M5CrossHostBaseline]]:
    """Measure one M5 shared-baseline cohort per path. FR-008."""
    baselines: dict[Path_, RunCohort] = {}
    metadata: dict[Path_, M5CrossHostBaseline] = {}
    for path in config.base.paths:
        corpus = "m1_embed" if path == "embed" else "m1_chat"
        cell = BenchmarkCell(
            path=path,
            hidden_size=config.base.schema_canonical_width,
            channel_config=M1_BASELINE,
            corpus_subset=corpus,  # type: ignore[arg-type]
            iterations=config.base.baseline_n,
        )
        cohort = await _measure_cohort_with_rtt(
            cell,
            seed=config.base.seed,
            config=config,
            endpoint_provider=endpoint_provider,
            constants=constants,
        )
        if not cohort.measurable:
            raise ValueError(
                f"M5 shared-baseline measurement failed on path={path!r} — "
                "see cohort.rtt_record for the validity result"
            )
        cohort = replace(
            cohort,
            is_baseline=True,
            baseline_role="m1_shared",
            expansion_record=None,
        )
        baselines[path] = cohort
        assert cohort.rtt_record is not None
        metadata[path] = M5CrossHostBaseline(
            path=path,
            cohort_id=cohort.cell.cell_id,
            modal_app_name=config.modal_app_name,
            modal_region=config.modal_region,
            measured_rtt=cohort.rtt_record,
            n=cohort.cell.iterations,
        )
    return baselines, metadata


# ---------------------------------------------------------------------------
# Channel-sweep driver
# ---------------------------------------------------------------------------


async def run_channel_sweep(
    config: M5SweepConfig,
    endpoint_provider: EndpointProvider,
    constants: _M4ConstantsForClassifier,
    shared_baselines: dict[Path_, RunCohort],
) -> list[RunCohort]:
    """Drive the axis × width × path cartesian product against the cross-host
    endpoint. Returns the list of candidate cohorts (with cascade applied
    via M4's borderline-expand logic — inherited through ``_measure_cell``).
    """
    from vllm_grpc_bench.channel_config import presets_for_axis

    cohorts: list[RunCohort] = []
    cells: list[BenchmarkCell] = []
    for axis in config.base.axes:
        for cfg in presets_for_axis(axis):  # type: ignore[arg-type]
            if cfg.name == M1_BASELINE.name:
                continue
            for w in config.base.widths:
                for path in config.base.paths:
                    corpus = "m1_embed" if path == "embed" else "m1_chat"
                    cells.append(
                        BenchmarkCell(
                            path=path,
                            hidden_size=w,
                            channel_config=cfg,
                            corpus_subset=corpus,  # type: ignore[arg-type]
                            iterations=config.base.candidate_n,
                        )
                    )

    for idx, cell in enumerate(cells):
        cohort = await _measure_cohort_with_rtt(
            cell,
            seed=config.base.seed + (idx + 1) * 1000,
            config=config,
            endpoint_provider=endpoint_provider,
            constants=constants,
        )
        # M5 cells always carry expansion_record (set by M4's _measure_cell);
        # ensure the field is at least populated for cohorts that didn't go
        # through the borderline-expand path (probe-failed shells).
        if cohort.expansion_record is None and cohort.measurable:
            cohort = replace(
                cohort,
                expansion_record=ExpansionRecord(
                    initial_n=cell.iterations,
                    initial_ci_overlapped=False,
                    expanded=False,
                    final_n=cell.iterations,
                ),
            )
        cohorts.append(cohort)
    return cohorts


# ---------------------------------------------------------------------------
# Recommendation builder (FR-009)
# ---------------------------------------------------------------------------


def build_m5_recommendations(
    cohorts: list[RunCohort],
    shared_baselines: dict[Path_, RunCohort],
) -> list[Recommendation]:
    """Apply FR-009 strict-CI-clearance against the M5 shared baseline.

    Cohorts flagged ``client_bound``, ``server_bound``, or ``discarded`` are
    excluded from ``recommend`` tallies. ``Recommendation.supersedes_m4_cell``
    is populated by ``m5_supersede`` downstream; this builder leaves it None.
    """
    from vllm_grpc_bench.m4_sweep import build_recommendations

    measurable_cohorts = [c for c in non_discarded(cohorts) if not c.server_bound]
    recs = build_recommendations(
        measurable_cohorts,
        shared_baselines={p: c for p, c in shared_baselines.items()},
    )
    # M4's builder already excludes baselines + emits client_bound. Verify the
    # FR-007 guard (no noise_bounded literal from M5).
    for r in recs:
        if r.verdict == "noise_bounded":
            raise ValueError(
                f"M5 recommendation builder emitted noise_bounded for "
                f"{r.axis}/{r.applies_to_path}/{sorted(r.applies_to_widths)} — "
                "FR-007 forbids this literal in M5 reports"
            )
    # Add server_bound entries for the cohorts the M4 builder skipped.
    from vllm_grpc_bench.m3_sweep import CITATIONS

    seen = {(r.axis, r.applies_to_path, frozenset(r.applies_to_widths)) for r in recs}
    for cohort in cohorts:
        if cohort.is_baseline or cohort.discarded:
            continue
        if not cohort.server_bound:
            continue
        axis = cohort.cell.channel_config.axis
        if axis not in CITATIONS:
            continue
        applies = frozenset({cohort.cell.hidden_size})
        key = (axis, cohort.cell.path, applies)
        if key in seen:
            continue
        seen.add(key)
        recs.append(
            Recommendation(
                axis=axis,
                applies_to_path=cohort.cell.path,
                applies_to_widths=applies,
                verdict="server_bound",
                baseline_ci_upper=0.0,
                citation=CITATIONS[axis],
                notes=(
                    f"{cohort.cell.cell_id}: remote-server overhead dominates "
                    f"(server_overhead_estimate_ms="
                    f"{cohort.server_overhead_estimate_ms or 0:.1f}); "
                    "excluded from recommend tallies (FR-005 / R-4)"
                ),
                corpus_subset=cohort.cell.corpus_subset,
            )
        )
    return recs


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


async def run_m5_sweep(
    config: M5SweepConfig,
    *,
    endpoint_provider: EndpointProvider | None = None,
    progress: bool = True,
) -> Run:
    """Execute the full M5 sweep and return the populated ``Run`` record.

    When ``endpoint_provider`` is None, the harness deploys via
    ``modal_endpoint.provide_endpoint`` once at the top of the sweep,
    captures the published ``(target, credentials, metadata)`` tuple, and
    threads a *frozen* provider into the rest of the sweep so every cohort
    reuses the same Modal endpoint instead of re-deploying per-cohort
    (which would multiply Modal cost by ~50× and the AsyncUsageWarning by
    the same factor). Tests pass a stub provider directly (typically
    ``serve_in_process_adapter``) and bypass the deploy-once wrapper.
    """
    if endpoint_provider is not None:
        # Test path / explicit provider — call directly, no deploy-once
        # wrapper.
        return await _run_m5_sweep_impl(config, endpoint_provider, progress)

    # No provider given → deploy via Modal and freeze the tuple. We pass a
    # minimal ``MockEngine`` instance for ``EndpointProvider`` Protocol
    # parity — the Modal-side server runs its own engine, so this instance
    # is never actually invoked, but the type signature requires a real
    # ``MockEngine`` (mypy --strict rejects a placeholder class).
    from vllm_grpc_bench import modal_endpoint
    from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig

    placeholder_engine = MockEngine(MockEngineConfig(hidden_size=4096, seed=0))
    if config.skip_deploy_endpoint:
        # --m5-skip-deploy → static_endpoint_provider is cheap (no app.run),
        # but the frozen-tuple wrapper still keeps the per-cohort flow uniform.
        deploy_ctx = modal_endpoint.static_endpoint_provider(
            placeholder_engine,
            M1_BASELINE,
            target=config.skip_deploy_endpoint,
            token_env=config.token_env,
        )
    else:
        deploy_ctx = modal_endpoint.provide_endpoint(
            placeholder_engine,
            M1_BASELINE,
            region=config.modal_region,
            token_env=config.token_env,
        )
    async with deploy_ctx as endpoint_tuple:
        target, credentials, metadata = endpoint_tuple
        if progress:
            print(
                f"[deploy] M5 endpoint={target} (deploy once for the full sweep)",
                flush=True,
            )
        frozen = make_frozen_endpoint_provider(target, credentials, metadata)
        return await _run_m5_sweep_impl(config, frozen, progress)


async def _run_m5_sweep_impl(
    config: M5SweepConfig,
    endpoint_provider: EndpointProvider,
    progress: bool,
) -> Run:
    """Inner sweep body — assumes ``endpoint_provider`` is already set up.

    Split out from ``run_m5_sweep`` so the Modal deploy-once wrapper can
    enter ``provide_endpoint`` exactly once at the top of the sweep and
    pass a frozen tuple-yielding provider here for per-cohort reuse.
    """
    constants = load_m4_constants(config.m4_report_path)
    run_started = time.monotonic()
    cohorts: list[RunCohort] = []

    # Warm-up (R-5).
    warmup_cohorts = await run_warmup_cohorts(config, endpoint_provider, constants)
    cohorts.extend(warmup_cohorts)
    if progress and warmup_cohorts:
        for c in warmup_cohorts:
            assert c.rtt_record is not None
            print(
                f"[warmup] cohort={c.cell.cell_id} discarded n={c.cell.iterations} "
                f"rtt_median_ms={c.rtt_record.median_ms:.2f}",
                flush=True,
            )

    # Cross-host shared baseline (FR-008).
    shared_baselines, baseline_metadata = await measure_m5_shared_baseline(
        config, endpoint_provider, constants
    )
    cohorts.extend(shared_baselines.values())
    if progress:
        for p, c in shared_baselines.items():
            assert c.rtt_record is not None
            print(
                f"[baseline] path={p} cohort={c.cell.cell_id} "
                f"n={c.n_successful} rtt_median_ms={c.rtt_record.median_ms:.2f}",
                flush=True,
            )

    # Channel sweep.
    candidate_cohorts = await run_channel_sweep(
        config, endpoint_provider, constants, shared_baselines
    )
    cohorts.extend(candidate_cohorts)
    if progress:
        for idx, c in enumerate(candidate_cohorts):
            assert c.rtt_record is not None
            tag = (
                "server_bound"
                if c.server_bound
                else "client_bound"
                if c.client_bound
                else "measured"
            )
            print(
                f"[{idx + 1}/{len(candidate_cohorts)}] cell={c.cell.cell_id} "
                f"verdict={tag} rtt_median_ms={c.rtt_record.median_ms:.2f}",
                flush=True,
            )

    # US2 — per-path frozen baselines + schema candidates.
    frozen_baselines: dict[Path_, FrozenChannelBaseline] = {}
    schema_results: list[SchemaCandidateResult] = []
    if not config.base.skip_schema:
        frozen_baselines, frozen_cohorts = await build_m5_frozen_channel_baselines(
            config, endpoint_provider, constants, shared_baselines, candidate_cohorts
        )
        cohorts.extend(frozen_cohorts)
        schema_results, schema_cohorts, _negatives = await measure_schema_candidates(
            config, endpoint_provider, constants, frozen_baselines, frozen_cohorts
        )
        cohorts.extend(schema_cohorts)

    runtime_seconds = time.monotonic() - run_started

    rtt_summary = _summarize_rtt(cohorts)
    server_bound_count = sum(1 for c in cohorts if c.server_bound and not c.discarded)
    run = Run(
        mode="m5-cross-host-validation",
        axes=list(config.base.axes),
        widths=list(config.base.widths),
        paths=list(config.base.paths),
        iterations_per_cell=config.base.candidate_n,
        seed=config.base.seed,
        cohorts=cohorts,
        pacing_mode=config.base.pacing_mode,
        shared_baseline_cohort_ids={
            path: shared_baselines[path].cell.cell_id for path in config.base.paths
        },
        candidate_sizing_policy={
            "default_n": config.base.candidate_n,
            "expand_n": config.base.expand_n,
            "expand_rule": "ci_overlap",
        },
        # M5 cells never carry the loopback caveat (FR-007).
        loopback_caveat_axes=[],
        m5_metadata=M5RunMetadata(
            m5_methodology_version=1,
            m5_modal_app_name=config.modal_app_name,
            m5_modal_region=config.modal_region,
            m5_runtime_wallclock_seconds=runtime_seconds,
            m5_rtt_summary_ms=rtt_summary,
            rtt_validity_threshold_ms=config.rtt_validity_threshold_ms,
            rtt_exercise_threshold_ms=config.rtt_exercise_threshold_ms,
            warmup_n=config.warmup_n,
            server_bound_overhead_threshold_ms=_SERVER_BOUND_FLOOR_MS,
            server_bound_cohort_count=server_bound_count,
        ),
        m5_cross_host_baselines={str(k): v for k, v in baseline_metadata.items()},
        frozen_channel_baselines=(
            {str(k): v for k, v in frozen_baselines.items()} if frozen_baselines else None
        ),
    )
    run.recommendations.extend(build_m5_recommendations(cohorts, shared_baselines))
    run.schema_candidate_results.extend(schema_results)
    # US3 — supersedes M4 table.
    from vllm_grpc_bench.m5_supersede import build_supersedes_m4_table

    supersedes = build_supersedes_m4_table(run, config.m4_report_path)
    run.supersedes_m4.extend(supersedes)
    # Annotate per-recommendation supersedes_m4_cell for direct reader access.
    by_key: dict[tuple[str, str, int], SupersedesM4Entry] = {
        (str(e.m4_axis), str(e.m4_path), int(e.m4_hidden_size)): e for e in supersedes
    }
    for i, rec in enumerate(run.recommendations):
        for w in rec.applies_to_widths:
            entry = by_key.get((str(rec.axis), str(rec.applies_to_path), int(w)))
            if entry is not None:
                run.recommendations[i] = replace(rec, supersedes_m4_cell=entry)
                break
    return run


def _summarize_rtt(cohorts: list[RunCohort]) -> RTTSummary:
    """Aggregate RTT distribution across non-discarded cohorts (FR-014 root)."""
    medians: list[float] = []
    for c in non_discarded(cohorts):
        if c.rtt_record is None:
            continue
        medians.append(c.rtt_record.median_ms)
    if not medians:
        return RTTSummary(min_ms=0.0, median_ms=0.0, p95_ms=0.0, max_ms=0.0)
    ordered = sorted(medians)
    return RTTSummary(
        min_ms=ordered[0],
        median_ms=statistics.median(ordered),
        p95_ms=_percentile(ordered, 95.0),
        max_ms=ordered[-1],
    )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    rank = (pct / 100.0) * (len(values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    frac = rank - lower
    return values[lower] + (values[upper] - values[lower]) * frac


# ---------------------------------------------------------------------------
# US2 — per-path frozen-channel baselines + schema candidates
# ---------------------------------------------------------------------------


async def build_m5_frozen_channel_baselines(
    config: M5SweepConfig,
    endpoint_provider: EndpointProvider,
    constants: _M4ConstantsForClassifier,
    shared_baselines: dict[Path_, RunCohort],
    candidate_cohorts: list[RunCohort],
) -> tuple[dict[Path_, FrozenChannelBaseline], list[RunCohort]]:
    """Compose per-path frozen-channel cohorts from US1's per-axis winners.

    For each path, the cohort combines that path's winning channel configs at
    ``schema_canonical_width``. Axes with no winner fall back to M3 default.
    The composed config is measured as its own n >= ``baseline_n`` cohort
    against the cross-host endpoint.
    """
    from vllm_grpc_bench.m4_sweep import _compose_channel_config

    recs = build_m5_recommendations(
        list(shared_baselines.values()) + candidate_cohorts,
        shared_baselines,
    )
    winners_by_path_axis: dict[Path_, dict[str, str]] = {p: {} for p in config.base.paths}
    for rec in recs:
        if rec.verdict != "recommend" or rec.winning_config is None:
            continue
        path = rec.applies_to_path
        if path == "both":
            continue
        if (
            rec.applies_to_widths
            and config.base.schema_canonical_width not in rec.applies_to_widths
        ):
            continue
        winners_by_path_axis.setdefault(path, {})[rec.axis] = rec.winning_config.name

    frozen_baselines: dict[Path_, FrozenChannelBaseline] = {}
    frozen_cohorts: list[RunCohort] = []
    for path in config.base.paths:
        per_axis = dict(winners_by_path_axis.get(path, {}))
        for axis in config.base.axes:
            per_axis.setdefault(axis, "m1-default")
        path_token = path.replace("_", "-")
        composed = _compose_channel_config(
            name=f"frozen-{path_token}-h{config.base.schema_canonical_width}-m5",
            per_axis_winners=per_axis,
        )
        corpus = "m1_embed" if path == "embed" else "m1_chat"
        cell = BenchmarkCell(
            path=path,
            hidden_size=config.base.schema_canonical_width,
            channel_config=composed,
            corpus_subset=corpus,  # type: ignore[arg-type]
            iterations=config.base.baseline_n,
        )
        cohort = await _measure_cohort_with_rtt(
            cell,
            seed=config.base.seed + 999_000,
            config=config,
            endpoint_provider=endpoint_provider,
            constants=constants,
        )
        cohort = replace(
            cohort,
            is_baseline=True,
            baseline_role="frozen_channel",
            expansion_record=None,
        )
        frozen_cohorts.append(cohort)
        frozen_baselines[path] = FrozenChannelBaseline(
            path=path,
            cohort_id=cohort.cell.cell_id,
            channel_config_name=composed.name,
            per_axis_winners=dict(per_axis),
            measured_at_hidden_size=config.base.schema_canonical_width,
        )
    return frozen_baselines, frozen_cohorts


# Map candidate name → proto-stub module path. The candidate protos under
# ``proto/vllm_grpc/v1/m4-candidates/`` carry MESSAGE types only (no
# services), so the US2 measurement is a *wire-bytes* delta against the M5
# frozen-baseline cohort: we re-serialize equivalent messages through the
# candidate's stub and compare byte counts. The time-metric verdict reuses
# the frozen-baseline cohort's own wall-clock since the same gRPC service
# carries both shapes (per contract m5-modal-app.md "Servicers registered").
_CANDIDATE_STUBS: dict[str, str] = {
    "packed_token_ids": "vllm_grpc.v1.m4_candidates.packed_token_ids_pb2",
    "oneof_flattened_input": "vllm_grpc.v1.m4_candidates.oneof_flattened_input_pb2",
    "chunk_granularity": "vllm_grpc.v1.m4_candidates.chunk_granularity_pb2",
}


def _candidate_message_bytes(candidate_name: str, hidden_size: int, seed: int = 0) -> int:
    """Build one representative candidate message and return its serialized size.

    Uses a tiny deterministic payload for each candidate so byte counts are
    reproducible across runs. The production-shape ``CompletionRequest`` /
    ``ChatStreamChunk`` are used as the comparison baseline (the frozen-channel
    cohort's wire bytes).
    """
    module_path = _CANDIDATE_STUBS.get(candidate_name)
    if module_path is None:
        return 0
    import importlib

    try:
        mod = importlib.import_module(module_path)
    except ImportError:
        return 0
    if candidate_name == "packed_token_ids":
        msg = mod.ChatStreamChunk(
            delta_content="hello world ",
            finish_reason="",
            token_index=0,
            token_ids=list(range(64)),
        )
        return len(msg.SerializeToString())
    if candidate_name == "chunk_granularity":
        msg = mod.ChatStreamChunk(
            delta_content="hello world chunk granularity test payload",
            finish_reason="",
            token_index=0,
            tokens_in_chunk=4,
            token_ids=list(range(64)),
        )
        return len(msg.SerializeToString())
    if candidate_name == "oneof_flattened_input":
        import numpy as np

        rng = np.random.default_rng(seed ^ hidden_size)
        arr = rng.standard_normal((16, hidden_size), dtype=np.float32)
        msg = mod.CompletionRequest(
            model="mock-engine",
            max_tokens=10,
            input_kind=mod.InputKind.INPUT_KIND_EMBEDS,
            prompt=b"" if False else "",
            prompt_embeds=arr.tobytes(),
        )
        return len(msg.SerializeToString())
    return 0


def _production_message_bytes(path: Path_, hidden_size: int, seed: int = 0) -> int:
    """Reference: production-proto wire bytes for the same payload shape."""
    if path == "embed":
        import numpy as np
        from vllm_grpc.v1 import completions_pb2

        rng = np.random.default_rng(seed ^ hidden_size)
        arr = rng.standard_normal((16, hidden_size), dtype=np.float32)
        req = completions_pb2.CompletionRequest(
            model="mock-engine", max_tokens=10, prompt_embeds=arr.tobytes()
        )
        return len(req.SerializeToString())
    # chat_stream: one ChatStreamChunk reference message
    from vllm_grpc.v1 import chat_pb2

    chunk = chat_pb2.ChatStreamChunk(
        delta_content="hello world chunk granularity test payload",
        finish_reason="",
        token_index=0,
    )
    return len(chunk.SerializeToString())


def schema_widths_to_measure(
    *,
    primary_verdict_at_canonical: str,
    canonical_width: int,
    full_widths: tuple[int, ...],
) -> list[int]:
    """FR-012 cascade: canonical-first; cascade to 2048 + 8192 only on
    ``recommend`` or borderline at the canonical width.
    """
    if primary_verdict_at_canonical in ("recommend", "borderline"):
        return sorted(set(full_widths))
    return [canonical_width]


def _byte_verdict(
    candidate_bytes: int,
    baseline_bytes: float,
    baseline_ci_low: float,
    baseline_ci_high: float,
) -> tuple[Verdict, float]:
    """Per-cell bytes verdict: candidate WINS iff its serialized size strictly
    clears the baseline CI low (smaller wire is better).
    """
    delta_pct = (
        ((candidate_bytes - baseline_bytes) / baseline_bytes) * 100.0 if baseline_bytes > 0 else 0.0
    )
    if candidate_bytes < baseline_ci_low:
        return "recommend", delta_pct
    if candidate_bytes > baseline_ci_high:
        return "no_winner", delta_pct
    return "no_winner", delta_pct


def _ci_overlaps(cand_low: float, cand_high: float, base_low: float, base_high: float) -> bool:
    return cand_low <= base_high and cand_high >= base_low


async def measure_schema_candidates(
    config: M5SweepConfig,
    endpoint_provider: EndpointProvider,
    constants: _M4ConstantsForClassifier,
    frozen_baselines: dict[Path_, FrozenChannelBaseline],
    frozen_cohorts: list[RunCohort],
) -> tuple[list[SchemaCandidateResult], list[RunCohort], list[dict[str, object]]]:
    """Measure each schema candidate against the M5 frozen-channel baseline.

    Returns (schema_results, candidate_cohorts, negative_results_list).
    Negative results are candidates whose CIs overlap the baseline CI on
    both bytes and time at every measured width.
    """
    if config.base.skip_schema or not config.base.schema_candidates:
        return [], [], []

    # Index frozen cohorts by path for quick lookup.
    frozen_by_path: dict[Path_, RunCohort] = {}
    for c in frozen_cohorts:
        if c.baseline_role == "frozen_channel":
            frozen_by_path[c.cell.path] = c

    schema_results: list[SchemaCandidateResult] = []
    candidate_cohorts: list[RunCohort] = []
    negatives: list[dict[str, object]] = []
    canonical = config.base.schema_canonical_width
    for candidate_name in config.base.schema_candidates:
        proto_file = f"proto/vllm_grpc/v1/m4-candidates/{candidate_name}.proto"
        per_widths: list[SchemaCandidatePerWidth] = []
        notes: list[str] = []
        # Decide cascade by measuring at the canonical width first.
        all_widths = (canonical,)
        for w in all_widths:
            for path in config.base.paths:
                baseline_cohort = frozen_by_path.get(path)
                if baseline_cohort is None:
                    notes.append(f"no frozen baseline for path={path}")
                    continue
                # bytes: serialize the candidate vs production message.
                cand_bytes = _candidate_message_bytes(candidate_name, w)
                if cand_bytes == 0:
                    notes.append(
                        f"candidate stub {candidate_name!r} not importable — run `make proto`"
                    )
                    continue
                prod_bytes_ref = _production_message_bytes(path, w)
                bytes_verdict, bytes_delta = _byte_verdict(
                    cand_bytes,
                    baseline_bytes=float(prod_bytes_ref),
                    baseline_ci_low=float(prod_bytes_ref) * 0.999,
                    baseline_ci_high=float(prod_bytes_ref) * 1.001,
                )
                # time: candidate cohort reuses the frozen baseline's cell
                # (same servicer, same channel, same workload) — for
                # candidates that don't change the servicer-level wire shape,
                # the time delta is zero by construction. We still record a
                # candidate cohort so the JSON carries the per-width entry
                # with an RTT record.
                cand_cell = BenchmarkCell(
                    path=path,
                    hidden_size=w,
                    channel_config=baseline_cohort.cell.channel_config,
                    corpus_subset=baseline_cohort.cell.corpus_subset,
                    iterations=config.base.candidate_n,
                )
                cand_cohort = await _measure_cohort_with_rtt(
                    cand_cell,
                    seed=config.base.seed + 999_900,
                    config=config,
                    endpoint_provider=endpoint_provider,
                    constants=constants,
                )
                cand_cohort = replace(
                    cand_cohort,
                    expansion_record=cand_cohort.expansion_record
                    or ExpansionRecord(
                        initial_n=cand_cell.iterations,
                        initial_ci_overlapped=False,
                        expanded=False,
                        final_n=cand_cell.iterations,
                    ),
                )
                candidate_cohorts.append(cand_cohort)
                time_overlaps = _ci_overlaps(
                    cand_cohort.time_ci_low,
                    cand_cohort.time_ci_high,
                    baseline_cohort.time_ci_low,
                    baseline_cohort.time_ci_high,
                )
                time_verdict: Verdict = (
                    "no_winner"
                    if time_overlaps
                    else (
                        "recommend"
                        if cand_cohort.time_ci_high < baseline_cohort.time_ci_low
                        else "no_winner"
                    )
                )
                if baseline_cohort.time_mean > 0:
                    delta_time = (
                        (cand_cohort.time_mean - baseline_cohort.time_mean)
                        / baseline_cohort.time_mean
                    ) * 100.0
                else:
                    delta_time = 0.0
                per_widths.append(
                    SchemaCandidatePerWidth(
                        hidden_size=w,
                        frozen_baseline_cohort_id=baseline_cohort.cell.cell_id,
                        candidate_cohort_id=cand_cohort.cell.cell_id,
                        bytes_verdict=bytes_verdict,
                        time_verdict=time_verdict,
                        primary_metric="bytes" if bytes_verdict == "recommend" else "time",
                        delta_bytes_pct=bytes_delta,
                        delta_time_pct=delta_time,
                        ci_overlap_initial=time_overlaps,
                        expanded=False,
                    )
                )
        is_negative = bool(per_widths) and all(
            pw.bytes_verdict == "no_winner" and pw.time_verdict == "no_winner" for pw in per_widths
        )
        schema_results.append(
            SchemaCandidateResult(
                candidate_name=candidate_name,
                proto_file=proto_file,
                measured_widths=[pw.hidden_size for pw in per_widths],
                per_width=per_widths,
                is_negative_result=is_negative,
                notes="; ".join(notes) if notes else None,
            )
        )
        if is_negative:
            negatives.append(
                {
                    "candidate_name": candidate_name,
                    "rationale": "bytes and time both `no_winner` at every measured width",
                }
            )
    return schema_results, candidate_cohorts, negatives
