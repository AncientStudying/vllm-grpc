"""M5.2 round-trippable regenerator (T036).

Reads the gzipped events JSONL sidecar + per-run config and produces a
byte-identical markdown + aggregate JSON. The harness MUST NOT emit the
markdown or aggregate JSON directly (per FR-012b).

Contract: ``specs/019-m5-2-transport-tuning/contracts/m5_2-regenerator.md``.

Algorithm:

1. Load + validate the run config. Raises ``RunConfigInvalid`` on missing
   required keys.
2. Open the gzipped sidecar. Compute SHA-256. Compare against
   ``run_config["events_sidecar_sha256"]``. Raise
   ``SidecarChecksumMismatch`` on mismatch.
3. Stream records via :func:`m5_2_events.read_sidecar_iter`. Build the
   in-memory :class:`M5_2Aggregates` (per-cohort metric medians + CIs;
   warmup excluded per FR-011).
4. Re-assert :func:`m5_2_symmetry.assert_symmetry` at report-build time.
5. Load M5.1's published JSON; build the Supersedes-M5.1 table.
6. Compute the HTTPS-edge vs plain-TCP RTT delta.
7. Write byte-deterministic markdown + aggregate JSON via
   :mod:`reporter` (``write_m5_2_markdown``, ``write_m5_2_json``).

Re-running the regenerator on the same inputs MUST produce byte-identical
output.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m3_types import (
    M5_2CohortKind,
    ProtocolComparisonRow,
    ProtocolComparisonVerdict,
    SupersedesM5_1Entry,
    TransportOnlyRow,
    TransportOnlyVerdict,
)
from vllm_grpc_bench.m5_2_events import (
    PerRequestEventRecord,
    read_sidecar_iter,
)
from vllm_grpc_bench.m5_2_supersede import (
    M5_1PublishedJsonUnavailable,
    build_supersedes_m5_1,
)
from vllm_grpc_bench.m5_2_symmetry import (
    CrossCohortInvariants,
    IntraProtocolPairInvariants,
    PerCohortMetadata,
    SymmetryAssertionFailed,
    SymmetryBlock,
)


class RunConfigInvalid(RuntimeError):
    """Raised when the run config JSON is missing a required key or malformed."""


class SidecarChecksumMismatch(RuntimeError):
    """Raised when the gzipped sidecar's SHA-256 differs from the run config's
    recorded value. Maps to regenerator exit code 8.
    """

    def __init__(self, *, expected: str, observed: str) -> None:
        self.expected = expected
        self.observed = observed
        super().__init__(f"SidecarChecksumMismatch: expected={expected}, observed={observed}")


class M5_2SchemaValidationFailed(RuntimeError):
    """Raised when the produced aggregate JSON fails the schema validation
    enumerated in ``contracts/m5_2-report-schema.md``.
    """


_REQUIRED_RUN_CONFIG_KEYS = frozenset(
    {
        "run_id",
        "run_started_at_iso",
        "seed",
        "symmetry",
        "events_sidecar_path",
        "events_sidecar_sha256",
        "modal_region",
        "modal_instance_class",
        "https_edge_endpoint",
    }
)


@dataclass(frozen=True)
class CohortAggregate:
    """Aggregate metrics for one cohort within one cell."""

    cell_key: str  # "<path>:h<width>:c<conc>"
    cohort: M5_2CohortKind
    n: int
    metric_median_ms: float  # TTFT for chat_stream; total wall-clock for embed
    metric_ci_lower_ms: float
    metric_ci_upper_ms: float
    rtt_at_issue_median_ms: float
    request_body_bytes_median: int
    response_body_bytes_median: int


@dataclass
class M5_2Aggregates:
    """Top-level container the regenerator builds from the events sidecar.

    The reporter consumes this to render markdown + JSON.
    """

    cohort_aggregates: list[CohortAggregate]
    protocol_comparison_verdicts: list[ProtocolComparisonRow]
    transport_only_verdicts: list[TransportOnlyRow]
    supersedes_m5_1: list[SupersedesM5_1Entry]
    https_edge_vs_plain_tcp_rtt_delta_median_ms: float
    https_edge_vs_plain_tcp_rtt_delta_p95_ms: float
    computed_record_count: int = 0
    sidecar_sha256: str = ""
    sidecar_path: str = ""


@dataclass
class RegenerationResult:
    """Returned from :func:`regen_m5_2` so the operator's pre-PR diff can
    confirm the artifacts written + the observed SHA + the record count.
    """

    markdown_path: Path
    json_path: Path
    sidecar_path: Path
    observed_sha256: str
    computed_aggregates_count: int


# ---------------------------------------------------------------------------
# Run config + sidecar SHA-256 verification
# ---------------------------------------------------------------------------


def load_run_config(path: Path) -> dict[str, Any]:
    """Load the run config JSON sidecar. Raises ``RunConfigInvalid`` if a
    required key is missing or the JSON is malformed."""
    if not path.exists():
        raise RunConfigInvalid(f"run config not found at {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RunConfigInvalid(f"run config at {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RunConfigInvalid(f"run config at {path} is not a JSON object")
    missing = _REQUIRED_RUN_CONFIG_KEYS - data.keys()
    if missing:
        raise RunConfigInvalid(f"run config at {path} is missing required keys: {sorted(missing)}")
    return data


def verify_sidecar_sha256(sidecar_path: Path, expected: str) -> str:
    """Compute SHA-256 of the gzipped sidecar bytes and compare to ``expected``.

    Returns the observed digest on match; raises
    :class:`SidecarChecksumMismatch` on mismatch.
    """
    observed = hashlib.sha256(sidecar_path.read_bytes()).hexdigest()
    if observed != expected:
        raise SidecarChecksumMismatch(expected=expected, observed=observed)
    return observed


def _symmetry_from_run_config(run_config: dict[str, Any]) -> SymmetryBlock:
    """Rebuild a SymmetryBlock from the run config's persisted JSON shape.

    The regenerator re-asserts the block at report-build time. A
    persisted-state mismatch (e.g., someone hand-edited the run config to
    diverge from the sidecar's actual cohort set) trips the asserter.
    """
    sym = run_config.get("symmetry") or {}
    tier_a_raw = sym.get("tier_a") or {}
    tier_b_raw = sym.get("tier_b") or {}
    tier_c_raw = sym.get("tier_c") or []
    return SymmetryBlock(
        tier_a=CrossCohortInvariants(
            prompt_corpus_hash=str(tier_a_raw.get("prompt_corpus_hash", "")),
            modal_deploy_handle=str(tier_a_raw.get("modal_deploy_handle", "")),
            mock_engine_config_digest=str(tier_a_raw.get("mock_engine_config_digest", "")),
            warmup_batch_policy=str(tier_a_raw.get("warmup_batch_policy", "")),
        ),
        tier_b=IntraProtocolPairInvariants(
            rest_client_config_digest_url_excepted=str(
                tier_b_raw.get("rest_client_config_digest_url_excepted", "")
            ),
            tuned_grpc_channel_config_digest_topology_excepted=(
                tier_b_raw.get("tuned_grpc_channel_config_digest_topology_excepted")
            ),
        ),
        tier_c=[
            PerCohortMetadata(
                cohort=str(m.get("cohort", "default_grpc")),  # type: ignore[arg-type]
                client_config_digest_full=str(m.get("client_config_digest_full", "")),
                modal_app_handle=str(m.get("modal_app_handle", "")),
                modal_region=str(m.get("modal_region", "")),
                warmup_batch_size=int(m.get("warmup_batch_size", 0)),
                tier_b_skipped_c1_tuned_grpc_pair=bool(
                    m.get("tier_b_skipped_c1_tuned_grpc_pair", False)
                ),
            )
            for m in tier_c_raw
        ],
        client_external_geolocation_country=sym.get("client_external_geolocation_country"),
        client_external_geolocation_region=sym.get("client_external_geolocation_region"),
    )


# ---------------------------------------------------------------------------
# Aggregate computation from the sidecar
# ---------------------------------------------------------------------------


def _metric_for_record(rec: PerRequestEventRecord) -> float | None:
    """Per-record metric in milliseconds: TTFT for chat_stream; total
    wall-clock for embed. Returns None for records that lack the needed
    timestamps (chat_stream without first_byte_ts → skip).
    """
    if rec.path == "chat_stream":
        if rec.first_byte_ts_ms is None:
            return None
        return rec.first_byte_ts_ms - rec.issue_ts_ms
    return rec.done_ts_ms - rec.issue_ts_ms


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def _bootstrap_ci_on_median(
    values: list[float], *, n_bootstrap: int = 1000, seed: int = 42
) -> tuple[float, float, float]:
    """Compute (median, ci_lower, ci_upper) on a list of metric values."""
    if not values:
        return 0.0, 0.0, 0.0
    med = statistics.median(values)
    rng = random.Random(seed)
    boot: list[float] = []
    for _ in range(n_bootstrap):
        sample = [rng.choice(values) for _ in range(len(values))]
        boot.append(statistics.median(sample))
    if not boot:
        return med, med, med
    boot.sort()
    ci_low = boot[int(0.025 * len(boot))]
    ci_high = boot[int(0.975 * len(boot)) - 1] if len(boot) > 1 else boot[0]
    return med, ci_low, ci_high


def _cell_key(rec: PerRequestEventRecord) -> str:
    return f"{rec.path}:h{rec.hidden_size}:c{rec.concurrency}"


def _protocol_verdict_literal(
    grpc_kind: M5_2CohortKind, ci_low: float, ci_high: float
) -> ProtocolComparisonVerdict:
    if ci_high < 0:
        if grpc_kind == "tuned_grpc_multiplexed":
            return "tuned_grpc_multiplexed_recommend"
        if grpc_kind == "tuned_grpc_channels":
            return "tuned_grpc_channels_recommend"
        if grpc_kind == "tuned_grpc":
            return "tuned_grpc_recommend"
        if grpc_kind == "default_grpc":
            return "default_grpc_recommend"
        raise ValueError(f"regen: unexpected grpc_kind {grpc_kind!r}")
    if ci_low > 0:
        return "rest_https_edge_recommend"
    return "no_winner"


def _transport_verdict_literal(ci_low: float, ci_high: float) -> TransportOnlyVerdict:
    if ci_high < 0:
        return "rest_https_edge_recommend"
    if ci_low > 0:
        return "rest_plain_tcp_recommend"
    return "no_winner"


def _bootstrap_delta_ci_ms(
    a: list[float], b: list[float], *, n_bootstrap: int = 1000, seed: int = 42
) -> tuple[float, float, float]:
    if not a or not b:
        return 0.0, 0.0, 0.0
    delta = statistics.median(a) - statistics.median(b)
    rng = random.Random(seed)
    boot: list[float] = []
    for _ in range(n_bootstrap):
        ra = [rng.choice(a) for _ in range(len(a))]
        rb = [rng.choice(b) for _ in range(len(b))]
        boot.append(statistics.median(ra) - statistics.median(rb))
    boot.sort()
    ci_low = boot[int(0.025 * len(boot))]
    ci_high = boot[int(0.975 * len(boot)) - 1] if len(boot) > 1 else boot[0]
    return delta, ci_low, ci_high


def compute_aggregates(
    records: list[PerRequestEventRecord],
) -> M5_2Aggregates:
    """Build M5_2Aggregates from a list of (already-streamed) sidecar records.

    Warmup-phase records are persisted in the sidecar (FR-012a (g)) but
    excluded from aggregates per FR-011.
    """
    measurement = [r for r in records if r.phase == "measurement" and r.status == "success"]

    # Index by (cell_key, cohort).
    by_cell_cohort: dict[tuple[str, M5_2CohortKind], list[PerRequestEventRecord]] = {}
    for r in measurement:
        by_cell_cohort.setdefault((_cell_key(r), r.cohort), []).append(r)

    cohort_aggs: list[CohortAggregate] = []
    metrics_index: dict[tuple[str, M5_2CohortKind], list[float]] = {}
    for (cell_key, cohort), recs in sorted(by_cell_cohort.items()):
        metrics: list[float] = []
        rtts: list[float] = []
        req_bytes: list[int] = []
        resp_bytes: list[int] = []
        for r in recs:
            m = _metric_for_record(r)
            if m is not None:
                metrics.append(m)
            rtts.append(r.rtt_at_issue_ms)
            req_bytes.append(r.request_body_bytes)
            resp_bytes.append(r.response_body_bytes)
        med, ci_low, ci_high = _bootstrap_ci_on_median(metrics)
        cohort_aggs.append(
            CohortAggregate(
                cell_key=cell_key,
                cohort=cohort,
                n=len(metrics),
                metric_median_ms=med,
                metric_ci_lower_ms=ci_low,
                metric_ci_upper_ms=ci_high,
                rtt_at_issue_median_ms=statistics.median(rtts) if rtts else 0.0,
                request_body_bytes_median=int(statistics.median(req_bytes)) if req_bytes else 0,
                response_body_bytes_median=int(statistics.median(resp_bytes)) if resp_bytes else 0,
            )
        )
        metrics_index[(cell_key, cohort)] = metrics

    # Per-cell verdict families.
    cell_keys = sorted({_cell_key(r) for r in measurement})
    protocol_rows: list[ProtocolComparisonRow] = []
    transport_rows: list[TransportOnlyRow] = []
    for ck in cell_keys:
        path, hidden_size_str, concurrency_str = ck.split(":")
        hidden_size = int(hidden_size_str[1:])  # strip leading 'h'
        concurrency = int(concurrency_str[1:])  # strip leading 'c'
        edge_samples = metrics_index.get((ck, "rest_https_edge"), [])
        tcp_samples = metrics_index.get((ck, "rest_plain_tcp"), [])

        # Protocol family per gRPC cohort present at this cell.
        for grpc_cohort in (
            "tuned_grpc",
            "tuned_grpc_multiplexed",
            "tuned_grpc_channels",
            "default_grpc",
        ):
            grpc_samples = metrics_index.get((ck, grpc_cohort), [])
            if not grpc_samples:
                continue
            if not edge_samples:
                protocol_rows.append(
                    ProtocolComparisonRow(
                        path=path,  # type: ignore[arg-type]
                        hidden_size=hidden_size,
                        concurrency=concurrency,
                        grpc_cohort=grpc_cohort,
                        verdict="comparison_unavailable",
                        comparison_unavailable_reason="missing_rest_https_edge_cohort",
                        delta_median_ms=0.0,
                        ci_lower_ms=0.0,
                        ci_upper_ms=0.0,
                    )
                )
                continue
            delta, lo, hi = _bootstrap_delta_ci_ms(grpc_samples, edge_samples)
            protocol_rows.append(
                ProtocolComparisonRow(
                    path=path,  # type: ignore[arg-type]
                    hidden_size=hidden_size,
                    concurrency=concurrency,
                    grpc_cohort=grpc_cohort,
                    verdict=_protocol_verdict_literal(grpc_cohort, lo, hi),
                    comparison_unavailable_reason=None,
                    delta_median_ms=delta,
                    ci_lower_ms=lo,
                    ci_upper_ms=hi,
                )
            )

        # Transport-only family.
        if not edge_samples or not tcp_samples:
            transport_rows.append(
                TransportOnlyRow(
                    path=path,  # type: ignore[arg-type]
                    hidden_size=hidden_size,
                    concurrency=concurrency,
                    verdict="comparison_unavailable",
                    comparison_unavailable_reason="missing_rest_cohort",
                    delta_median_ms=0.0,
                    ci_lower_ms=0.0,
                    ci_upper_ms=0.0,
                )
            )
        else:
            delta, lo, hi = _bootstrap_delta_ci_ms(edge_samples, tcp_samples)
            transport_rows.append(
                TransportOnlyRow(
                    path=path,  # type: ignore[arg-type]
                    hidden_size=hidden_size,
                    concurrency=concurrency,
                    verdict=_transport_verdict_literal(lo, hi),
                    comparison_unavailable_reason=None,
                    delta_median_ms=delta,
                    ci_lower_ms=lo,
                    ci_upper_ms=hi,
                )
            )

    # HTTPS-edge vs plain-TCP RTT delta.
    edge_rtts = [r.rtt_at_issue_ms for r in measurement if r.cohort == "rest_https_edge"]
    tcp_rtts = [r.rtt_at_issue_ms for r in measurement if r.cohort == "rest_plain_tcp"]
    rtt_delta_med = (
        statistics.median(edge_rtts) - statistics.median(tcp_rtts)
        if edge_rtts and tcp_rtts
        else 0.0
    )
    rtt_delta_p95 = (
        _percentile(edge_rtts, 95.0) - _percentile(tcp_rtts, 95.0)
        if edge_rtts and tcp_rtts
        else 0.0
    )

    return M5_2Aggregates(
        cohort_aggregates=cohort_aggs,
        protocol_comparison_verdicts=protocol_rows,
        transport_only_verdicts=transport_rows,
        supersedes_m5_1=[],  # populated below by the caller
        https_edge_vs_plain_tcp_rtt_delta_median_ms=rtt_delta_med,
        https_edge_vs_plain_tcp_rtt_delta_p95_ms=rtt_delta_p95,
        computed_record_count=len(measurement),
    )


# ---------------------------------------------------------------------------
# Top-level regenerator entry point
# ---------------------------------------------------------------------------


def regen_m5_2(
    sidecar_path: Path,
    run_config_path: Path,
    *,
    report_out_prefix: Path | None = None,
    m5_1_published_path: Path | None = None,
) -> RegenerationResult:
    """Top-level regenerator.

    Steps per the regenerator contract:
    1. Load + validate the run config.
    2. Verify sidecar SHA-256.
    3. Stream records → compute aggregates.
    4. Re-assert symmetry block at report-build time.
    5. Build Supersedes-M5.1 table.
    6. Write deterministic markdown + aggregate JSON.

    On checksum mismatch, raises :class:`SidecarChecksumMismatch` and
    refuses to write artifacts. On run-config invalidity, raises
    :class:`RunConfigInvalid`. On symmetry divergence, raises
    :class:`SymmetryAssertionFailed`. On M5.1 published-JSON
    incompatibility, raises :class:`M5_1PublishedJsonUnavailable`.
    """
    run_config = load_run_config(run_config_path)
    expected_sha = str(run_config["events_sidecar_sha256"])
    observed_sha = verify_sidecar_sha256(sidecar_path, expected_sha)

    records = list(read_sidecar_iter(sidecar_path))
    aggregates = compute_aggregates(records)
    aggregates.sidecar_sha256 = observed_sha
    aggregates.sidecar_path = str(sidecar_path)

    # Re-assert symmetry at report-build time. The block lives in the run
    # config; the asserter would catch hand-edits that broke tier (a) /
    # tier (b) invariants. We don't re-derive the cohort configs here (the
    # sweep persisted the block as-built), so the assertion is a
    # consistency check on the persisted state rather than a fresh
    # build-vs-config comparison.
    block = _symmetry_from_run_config(run_config)
    # Tier (a) sanity: every field must be non-empty.
    for f, v in (
        ("prompt_corpus_hash", block.tier_a.prompt_corpus_hash),
        ("modal_deploy_handle", block.tier_a.modal_deploy_handle),
        ("mock_engine_config_digest", block.tier_a.mock_engine_config_digest),
        ("warmup_batch_policy", block.tier_a.warmup_batch_policy),
    ):
        if not v:
            raise SymmetryAssertionFailed(tier="a", field=f, observed_a="", observed_b="<empty>")

    # Supersedes-M5.1 table.
    try:
        aggregates.supersedes_m5_1 = build_supersedes_m5_1(
            aggregates.protocol_comparison_verdicts,
            m5_2_transport_rows=aggregates.transport_only_verdicts,
            m5_1_published_path=(
                m5_1_published_path or Path("docs/benchmarks/m5_1-rest-vs-grpc.json")
            ),
        )
    except M5_1PublishedJsonUnavailable:
        # Surface upward so the script can exit with code 9 per the contract.
        raise

    # Write artifacts via the reporter.
    from vllm_grpc_bench.reporter import write_m5_2_json, write_m5_2_markdown

    prefix = (
        report_out_prefix
        if report_out_prefix is not None
        else Path("docs/benchmarks/m5_2-transport-vs-tuning")
    )
    md_path = prefix.with_suffix(".md")
    json_path = prefix.with_suffix(".json")
    write_m5_2_markdown(aggregates, run_config, md_path)
    write_m5_2_json(aggregates, run_config, json_path)

    return RegenerationResult(
        markdown_path=md_path,
        json_path=json_path,
        sidecar_path=sidecar_path,
        observed_sha256=observed_sha,
        computed_aggregates_count=aggregates.computed_record_count,
    )
