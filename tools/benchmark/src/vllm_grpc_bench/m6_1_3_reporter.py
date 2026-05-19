"""M6.1.3 — Phase 1 Attribution Closure: artifact writer.

Mirrors :mod:`m6_1_2_reporter`'s structure (the canonical 3-key network /
cohort_set / cohort_omissions block + the cohort + per-cell measurement
sections), and ADDS:

* Per-cell ``seg_ingress_ms`` / ``seg_egress_ms`` columns in the timing
  table (FR-005 + FR-007 + ``contracts/artifact-schema.md``).
* Classifier narratives for the 7-bucket labels including the two new
  ``proxy_*_dominated`` base labels and the FR-008a compound-label form
  ``multi_factor_<a>_<b>`` (FR-009 + round-2 Q2).
* The identifier legend per FR-009a + round-2 Q2 (a single-line mapping
  from abbreviated identifier to driving segment field, rendered once per
  published markdown).
* Conditional ``frontend_arrival_jitter`` dormancy note per round-4 Q1.
* The Phase B trigger verdict line scaffold (FR-044 — wired by US3 T037).
* Audit + per-run audit appendix sections (FR-016 / FR-016a — wired by
  US2 T030).
* Between-run variance section (FR-025 — wired by US3 T037).

Three-path routing (FR-038 + round-2 Q1 + R-7) is delegated to
:func:`m6_1_3_validate.infer_output_path`; this reporter writes to the
paths it receives without re-inferring them.

Strict-superset over M6.1.1 / M6.1.2 schemas per FR-010 + round-3 Q1:
``schema_version`` stays at ``"m6_1_1.v1"`` (the new keys are additive;
pre-M6.1.3 readers ignore them without parse error).
"""

from __future__ import annotations

import dataclasses
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_1_1_types import MultiPointTimings, PerSegmentAggregate
from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2CohortKind,
    M6_1_2CohortOmissions,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    build_cohort_set_and_omissions,
)
from vllm_grpc_bench.m6_1_3_types import (
    M6_1_3BetweenRunVariance,
    M6_1_3PerCellAuditAggregate,
    M6_1_3PerRunAuditVerdict,
    M6_1_3PhaseBTriggerVerdict,
    M6_1_3SweepMode,
)

# --- Reporter dataclasses ---------------------------------------------------


@dataclass(frozen=True)
class M6_1_3RunMeta:
    """Per-sweep run metadata. Extends M6.1.2's RunMeta with the M6.1.3
    modifier-flag values so the published artifact records the exact
    invocation (validate vs full vs Phase B; symmetric prompts on/off).
    """

    git_sha: str
    modal_region: str
    base_seed: int
    model_identifier: str
    sweep_mode: M6_1_3SweepMode
    seq_len: int
    run_started_at: str
    run_completed_at: str
    m6_1_1_baseline_pointer: str
    # M6.1.3 modifier-flag values per FR-022 + FR-023 + FR-019.
    m6_1_3_diagnose_repeat: int
    m6_1_3_diagnose_n: int
    m6_1_3_symmetric_prompts: bool


@dataclass(frozen=True)
class M6_1_3CellMeasurement:
    """Per-(cell, cohort) measurement summary written into the artifact.

    Extends M6.1.2's M6_1_2CellMeasurement with a per-segment aggregate
    block (mirrors M6.1.1's MultiPointTimings shape) so the M6.1.3 reporter
    can render seg_ingress_ms / seg_egress_ms alongside the inherited
    seg_ab / seg_queue / seg_prefill columns. M6.1.3 also persists the
    per-RPC audit samples that feed
    :func:`m6_1_3_audit.compute_pooled_verdict` (FR-016 + round-1 Q5).

    ``per_segment`` is ``None`` when no successful RPC in this (cell,
    cohort) populated the M6.1.1-vintage timing payload (legacy clients,
    or every RPC failed before the wire-emission point).

    ``audit_samples`` is a list of ``(tokenized_prompt_length,
    tokenized_prompt_hash)`` tuples — one entry per successful RPC whose
    timing payload populated the M6.1.3 audit wire fields. Empty when no
    sample carried the audit data (pre-M6.1.3 server vintage, or every
    RPC failed before emission).
    """

    path: str  # "embed" | "chat_stream"
    concurrency: int
    cohort: M6_1_2CohortKind
    n_attempts: int
    n_successes: int
    wall_clock_ms_mean: float | None
    engine_ttft_ms_mean: float | None
    top_failure_reasons: dict[str, int]
    per_segment: PerSegmentAggregate | None = None
    audit_samples: list[tuple[int, str]] = field(default_factory=list)


def _cell_id(path: str, concurrency: int) -> str:
    """Canonical cell identifier used as keys throughout the artifact.

    Format: ``"chat_stream_c4"``, ``"embed_c1"``, etc. — matches the
    examples in ``contracts/artifact-schema.md`` + ``contracts/classifier.md``.
    """
    return f"{path}_c{concurrency}"


@dataclass(frozen=True)
class M6_1_3SweepArtifact:
    """The full M6.1.3 artifact payload handed to the reporter.

    Strict-superset over M6.1.2's artifact per FR-010: every M6.1.2
    top-level field is preserved, and three new top-level fields are
    added (``classifications`` for the per-cell labels, ``audit`` for the
    per-cohort prompt-content audit per FR-016, ``between_run_variance``
    + ``phase_b_trigger`` for the US3 multi-run + Phase B verdict).
    """

    schema_version: str  # always "m6_1_1.v1" per FR-010 + round-3 Q1
    dispatch_mode: str  # always "concurrent" per M6.0a
    run_id: str
    run_started_at: str
    run_completed_at: str
    run_meta: M6_1_3RunMeta
    network_paths: dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError]
    cohort_set: list[M6_1_2CohortKind]
    cohort_omissions: M6_1_2CohortOmissions | None
    measurements: list[M6_1_3CellMeasurement]
    # M6.1.3 NEW: per-cell classifier verdicts (cell_id → label per the
    # 7-bucket / compound / outer-override vocabulary).
    classifications: dict[str, str]
    classifier_notes: list[str] = field(default_factory=list)
    # M6.1.3 NEW (US2 T030 wires the populated dataclasses; for US1 these
    # stay None so the reporter omits the audit section cleanly).
    audit: list[M6_1_3PerCellAuditAggregate] | None = None
    audit_per_run: list[M6_1_3PerRunAuditVerdict] | None = None
    # M6.1.3 NEW (US3 T036/T037 wires these; for US1/US2 they stay None).
    between_run_variance: M6_1_3BetweenRunVariance | None = None
    phase_b_trigger: M6_1_3PhaseBTriggerVerdict | None = None
    # M6.1.3 NEW (US3 T036): per-run measurements accumulator for the
    # multi-run sweep. ``None`` on US1/US2 single-run sweeps (the
    # ``measurements`` field carries the single run's data). On multi-run
    # publish sweeps, ``measurements`` is the LAST run's measurements
    # (used as the representative classifier input) and ``phase_1_runs``
    # carries all N runs for the variance compute + audit pooling.
    phase_1_runs: list[list[M6_1_3CellMeasurement]] | None = None


# --- Identifier legend (FR-009a + round-2 Q2) -------------------------------

_IDENTIFIER_LEGEND_LINE: str = (
    "Identifier legend: "
    "channel_batching = seg_ab_ms; "
    "queue_batching = seg_queue_ms; "
    "engine_compute = seg_prefill_ms; "
    "frontend_arrival = seg_arrival_ms (dormant in M6.1.3 per FR-008a); "
    "proxy_ingress = seg_ingress_ms; "
    "proxy_egress = seg_egress_ms."
)


_BASE_LABEL_NARRATIVES: dict[str, str] = {
    "channel_dependent_batching": (
        "The budget lives in the auxiliary batching segment (channel-config dependent)."
    ),
    "queue_dependent_batching": "The budget lives in the engine-side queue wait segment.",
    "engine_compute_variation": (
        "The budget lives in the post-schedule engine prefill compute segment."
    ),
    "proxy_ingress_dominated": (
        "The budget lives in the proxy → engine handoff (frontend's "
        "`pre_engine` to vLLM's `arrival_time`)."
    ),
    "proxy_egress_dominated": (
        "The budget lives in the engine → proxy yield (vLLM's "
        "`first_token_ts` to frontend's `first_chunk`)."
    ),
    "inconclusive": (
        "No single segment carries the dominant share of the per-cohort spread; "
        "attribution is unattributed."
    ),
    "frontend_arrival_jitter": (
        "Frontend arrival jitter (legacy-fallback label; dormant in M6.1.3's "
        "7-bucket native tree per round-4 Q1)."
    ),
}


# --- Serialization helpers --------------------------------------------------


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert non-JSON-serialisable values to JSON-safe shapes.

    Mirrors :func:`m6_1_2_reporter._sanitize_for_json`; tuple keys collapse
    to ``"part0|part1|..."``; dataclass instances are converted via
    ``dataclasses.asdict``.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _sanitize_for_json(dataclasses.asdict(obj))
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            key = "|".join(str(part) for part in k) if isinstance(k, tuple) else k
            out[key] = _sanitize_for_json(v)
        return out
    if isinstance(obj, list):
        return [_sanitize_for_json(item) for item in obj]
    return obj


def _per_cell_row(measurement: M6_1_3CellMeasurement) -> dict[str, Any]:
    """Convert a M6_1_3CellMeasurement to a JSON-ready per-cell row dict.

    Per ``contracts/artifact-schema.md`` "Per-cell row shape": each row
    carries the M6.1.1 + M6.1.2 + M6.1.3 segment columns plus the
    classifier-related metadata. The audit fields (clock_anomaly_*) are
    folded into the per-segment block.
    """
    row: dict[str, Any] = {
        "cell_id": _cell_id(measurement.path, measurement.concurrency),
        "path": measurement.path,
        "concurrency": measurement.concurrency,
        "cohort": measurement.cohort,
        "n_attempts": measurement.n_attempts,
        "n_successes": measurement.n_successes,
        "wall_clock_ms_mean": measurement.wall_clock_ms_mean,
        "engine_ttft_ms_mean": measurement.engine_ttft_ms_mean,
        "top_failure_reasons": dict(measurement.top_failure_reasons),
    }
    if measurement.per_segment is not None:
        ps = measurement.per_segment
        row["per_segment"] = {
            "seg_ab_ms_mean": ps.seg_ab_ms_mean,
            "seg_ab_ms_ci_half_width": ps.seg_ab_ms_ci_half_width,
            "seg_bc_ms_mean": ps.seg_bc_ms_mean,
            "seg_bc_ms_ci_half_width": ps.seg_bc_ms_ci_half_width,
            "seg_cd_ms_mean": ps.seg_cd_ms_mean,
            "seg_cd_ms_ci_half_width": ps.seg_cd_ms_ci_half_width,
            "seg_queue_ms_mean": ps.seg_queue_ms_mean,
            "seg_queue_ms_ci_half_width": ps.seg_queue_ms_ci_half_width,
            "seg_prefill_ms_mean": ps.seg_prefill_ms_mean,
            "seg_prefill_ms_ci_half_width": ps.seg_prefill_ms_ci_half_width,
            # M6.1.3 new fields per FR-005 + FR-007.
            "seg_ingress_ms_mean": ps.seg_ingress_ms_mean,
            "seg_ingress_ms_ci_half_width": ps.seg_ingress_ms_ci_half_width,
            "seg_egress_ms_mean": ps.seg_egress_ms_mean,
            "seg_egress_ms_ci_half_width": ps.seg_egress_ms_ci_half_width,
            "clock_anomaly_fraction": ps.clock_anomaly_fraction,
            "clock_anomaly_warning": ps.clock_anomaly_warning,
            "n_samples": ps.n_samples,
        }
    return row


def render_json(artifact: M6_1_3SweepArtifact) -> dict[str, Any]:
    """Render the M6.1.3 artifact dict ready for ``json.dumps``.

    Performs the FR-016 pre-write invariant check (cohort_set ∪
    cohort_omissions == canonical universe; ∩ = ∅) by re-invoking
    :func:`build_cohort_set_and_omissions` — raises ``ValueError`` if the
    pair is malformed.
    """
    build_cohort_set_and_omissions(set(artifact.cohort_set), artifact.cohort_omissions)

    payload: dict[str, Any] = {
        "schema_version": artifact.schema_version,
        "dispatch_mode": artifact.dispatch_mode,
        "run_id": artifact.run_id,
        "run_started_at": artifact.run_started_at,
        "run_completed_at": artifact.run_completed_at,
        "run_meta": _sanitize_for_json(artifact.run_meta),
        "measurements": [_per_cell_row(m) for m in artifact.measurements],
        "classifications": dict(artifact.classifications),
        "classifier_notes": list(artifact.classifier_notes),
        "network_paths": {
            cohort: _sanitize_for_json(entry) for cohort, entry in artifact.network_paths.items()
        },
        "cohort_set": list(artifact.cohort_set),
    }
    if artifact.cohort_omissions:
        payload["cohort_omissions"] = dict(artifact.cohort_omissions)
    if artifact.audit is not None:
        payload["audit"] = [_sanitize_for_json(a) for a in artifact.audit]
    if artifact.audit_per_run is not None:
        payload["audit_per_run"] = [_sanitize_for_json(a) for a in artifact.audit_per_run]
    if artifact.between_run_variance is not None:
        payload["between_run_variance"] = _sanitize_for_json(artifact.between_run_variance)
    if artifact.phase_b_trigger is not None:
        payload["phase_b_trigger"] = _sanitize_for_json(artifact.phase_b_trigger)
    if artifact.phase_1_runs is not None:
        # Each per-run snapshot is a list of M6_1_3CellMeasurement; emit
        # them via the same _per_cell_row helper so consumers see
        # consistent shapes across the single-run ``measurements`` field
        # and the multi-run ``phase_1_runs`` accumulator.
        payload["phase_1_runs"] = [
            [_per_cell_row(m) for m in run_measurements]
            for run_measurements in artifact.phase_1_runs
        ]
    return payload


# --- Markdown rendering -----------------------------------------------------


def _fmt(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{decimals}f}"


def _compute_segment_shares(
    measurements: list[M6_1_3CellMeasurement],
    cell_id: str,
) -> dict[str, float]:
    """Compute the share-of-ttft-spread for each driving segment for a cell.

    Used in the compound-label narrative so the reporter can cite the
    contributing per-segment shares. Returns a dict
    ``{abbreviated_id: share}`` for the 5 active candidate identifiers.
    Returns an empty dict when the cell has no measurements or zero TTFT
    spread.
    """
    rows = [m for m in measurements if _cell_id(m.path, m.concurrency) == cell_id]
    if not rows:
        return {}
    ttft_means = [m.engine_ttft_ms_mean for m in rows if m.engine_ttft_ms_mean is not None]
    if len(ttft_means) < 2:
        return {}
    spread_ttft = max(ttft_means) - min(ttft_means)
    if spread_ttft <= 0:
        return {}
    shares: dict[str, float] = {}
    for seg_attr, abbrev_id in (
        ("seg_ab_ms_mean", "channel_batching"),
        ("seg_queue_ms_mean", "queue_batching"),
        ("seg_prefill_ms_mean", "engine_compute"),
        ("seg_ingress_ms_mean", "proxy_ingress"),
        ("seg_egress_ms_mean", "proxy_egress"),
    ):
        per_cohort_means: list[float] = []
        all_present = True
        for m in rows:
            if m.per_segment is None:
                all_present = False
                break
            val = getattr(m.per_segment, seg_attr, None)
            if val is None:
                all_present = False
                break
            per_cohort_means.append(float(val))
        if not all_present or not per_cohort_means:
            continue
        spread = max(per_cohort_means) - min(per_cohort_means)
        shares[abbrev_id] = spread / spread_ttft
    return shares


def _render_classifier_narrative(
    cell_id: str,
    label: str,
    shares: dict[str, float],
) -> list[str]:
    """Render the one-or-two-line classifier narrative for one cell.

    Handles base labels, compound labels, and outer-override-wrapped
    labels per ``contracts/classifier.md`` "Reporter narrative". For US1
    the outer-override branch is reachable only when US3 wires
    ``between_run_variance``; the base + compound branches cover the US1
    output space.
    """
    lines: list[str] = [f"#### {cell_id} → `{label}`", ""]

    # Outer override: "inconclusive_high_variance (<inner>)".
    if label.startswith("inconclusive_high_variance"):
        inner = label.removeprefix("inconclusive_high_variance").strip(" ()")
        lines.append(
            "Between-run variance dominates attribution. "
            f"Inner attribution: `{inner}`. Run Phase B "
            "(`--m6_1_3 --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200`) "
            "to verify whether sample-size scaling closes the gap."
        )
        lines.append("")
        return lines

    # Compound label: "multi_factor_<a>_<b>".
    if label.startswith("multi_factor_"):
        # Strip the prefix; the remainder is "<a>_<b>" with each id being
        # one of the abbreviated identifiers. Each identifier contains an
        # underscore (e.g., "channel_batching"), so we split on the known
        # set rather than naïvely on '_'.
        suffix = label.removeprefix("multi_factor_")
        ids_sorted = sorted(shares.keys())
        contributing: list[str] = []
        for abbrev in ids_sorted:
            if abbrev in suffix:
                contributing.append(abbrev)
        # Cite the two contributing shares (sorted by share descending).
        contributing.sort(key=lambda abbrev: shares.get(abbrev, 0.0), reverse=True)
        if len(contributing) >= 2:
            top, runner = contributing[0], contributing[1]
            top_share = shares.get(top, 0.0) * 100.0
            runner_share = shares.get(runner, 0.0) * 100.0
            lines.append(
                f"multi-factor: `{top}` carries {top_share:.0f}% of spread, "
                f"`{runner}` carries {runner_share:.0f}% (within the 5pp dominance "
                "margin); attribution is not single-source."
            )
        else:
            lines.append(
                "multi-factor near-tie attribution; see the per-cell timing table "
                "for contributing segment values."
            )
        lines.append("")
        return lines

    # Base label.
    narrative = _BASE_LABEL_NARRATIVES.get(label)
    if narrative is None:
        lines.append(f"(no narrative defined for label `{label}`)")
    else:
        lines.append(narrative)
    lines.append("")
    return lines


def _render_audit_section(
    pooled: list[M6_1_3PerCellAuditAggregate],
    per_run: list[M6_1_3PerRunAuditVerdict] | None,
) -> list[str]:
    """Render the Per-Cohort Prompt-Content Audit section + spec recommendation.

    Three subsections per ``contracts/artifact-schema.md`` "The Per-Cohort
    Prompt-Content Audit reporter section":

    * Per-cell pooled distribution table (mean / stddev / n_rpcs /
      unique_hash_count per cohort).
    * One-line H1 / H2 / rejection verdict per cell.
    * Spec-decision recommendation block drawn from chat_stream_c1's
      pooled verdict (FR-017 / FR-018 / H2 note).
    * Conditional per-run audit appendix per FR-016a + round-2 Q5 (when
      any per-run verdict diverges from the pooled verdict for any cell).
    """
    from vllm_grpc_bench.m6_1_3_audit import (  # local import avoids cycle at module load
        extract_h1_recommendation,
        should_render_audit_appendix,
    )

    lines: list[str] = []
    lines.append("## Per-Cohort Prompt-Content Audit")
    lines.append("")

    for cell_agg in pooled:
        cell_id = cell_agg.cell_id
        any_dist = next(iter(cell_agg.per_cohort.values()), None)
        n_pooled = any_dist.n_rpcs if any_dist is not None else 0
        lines.append(f"### {cell_id} (pooled n={n_pooled} per cohort)")
        lines.append("")
        lines.append(
            "| Cohort | mean_tokenized_prompt_length | stddev | n_rpcs | unique_hash_count |"
        )
        lines.append(
            "|--------|------------------------------:|-------:|-------:|-------------------:|"
        )
        for cohort in sorted(cell_agg.per_cohort.keys()):
            dist = cell_agg.per_cohort[cohort]
            lines.append(
                f"| `{cohort}` | {dist.mean_tokenized_prompt_length:.2f} | "
                f"{dist.stddev_tokenized_prompt_length:.2f} | {dist.n_rpcs} | "
                f"{dist.unique_hash_count} |"
            )
        lines.append("")
        lines.append("**H1 verdict** (per FR-016 + round-1 Q5):")
        lines.append("")
        lines.append(f"> {cell_agg.pooled_verdict}")
        lines.append("")

    # Spec-decision recommendation block (FR-017 / FR-018 / H2 note).
    recommendation = extract_h1_recommendation(pooled)
    lines.append("**Recommendation** (per FR-017 / FR-018):")
    lines.append("")
    lines.append(f"> {recommendation}")
    lines.append("")

    # Conditional per-run audit appendix (FR-016a + round-2 Q5).
    if per_run is not None and should_render_audit_appendix(pooled, per_run):
        lines.extend(_render_per_run_audit_appendix(pooled, per_run))

    return lines


def _render_per_run_audit_appendix(
    pooled: list[M6_1_3PerCellAuditAggregate],
    per_run: list[M6_1_3PerRunAuditVerdict],
) -> list[str]:
    """Render the per-run audit verdict appendix per FR-016a + round-2 Q5.

    Per round-2 Q5: when one cell's per-run / pooled disagreement triggers
    rendering, the appendix renders ALL cells (not just the disagreeing
    ones) so a reader sees the full context.
    """
    lines: list[str] = []
    lines.append(
        "### Per-Run Audit Verdict Appendix (rendered because per-run / "
        "pooled disagreement detected)"
    )
    lines.append("")

    # Group per-run verdicts by cell_id.
    by_cell: dict[str, list[M6_1_3PerRunAuditVerdict]] = {}
    for v in per_run:
        by_cell.setdefault(v.cell_id, []).append(v)

    pooled_by_cell = {agg.cell_id: agg.pooled_verdict for agg in pooled}

    for cell_id in sorted(pooled_by_cell.keys()):
        lines.append(f"#### {cell_id}")
        lines.append("")
        lines.append("| Run | Per-run verdict |")
        lines.append("|-----|------------------|")
        for v in sorted(by_cell.get(cell_id, []), key=lambda x: x.run_idx):
            lines.append(f"| {v.run_idx}   | {v.verdict} |")
        lines.append(f"| **Pooled** | **{pooled_by_cell[cell_id]}** |")
        lines.append("")

    return lines


def render_markdown(artifact: M6_1_3SweepArtifact) -> str:
    """Render the human-readable companion markdown."""
    lines: list[str] = []
    lines.append("# M6.1.3 — Phase 1 Attribution Closure")
    lines.append("")
    lines.append(f"- run_id: `{artifact.run_id}`")
    lines.append(f"- sweep_mode: `{artifact.run_meta.sweep_mode}`")
    lines.append(f"- modal_region: `{artifact.run_meta.modal_region}`")
    lines.append(f"- model: `{artifact.run_meta.model_identifier}`")
    lines.append(f"- base_seed: `{artifact.run_meta.base_seed}`")
    lines.append(f"- m6_1_3_diagnose_repeat: `{artifact.run_meta.m6_1_3_diagnose_repeat}`")
    lines.append(f"- m6_1_3_diagnose_n: `{artifact.run_meta.m6_1_3_diagnose_n}`")
    lines.append(f"- m6_1_3_symmetric_prompts: `{artifact.run_meta.m6_1_3_symmetric_prompts}`")
    lines.append(f"- run_started_at: `{artifact.run_started_at}`")
    lines.append(f"- run_completed_at: `{artifact.run_completed_at}`")
    lines.append("")

    # Method / Background with the reciprocal cross-reference per FR-041.
    lines.append("## Method / Background")
    lines.append("")
    lines.append(
        "Updates the c=4 / c=8 verdicts from "
        "[M6.1.1](m6_1_1-engine-cost-instrumentation.md); see that artifact's "
        "leading note for the bidirectional pointer."
    )
    lines.append("")

    # Cohort set.
    lines.append("## Cohort set")
    lines.append("")
    for c in artifact.cohort_set:
        lines.append(f"- `{c}`")
    if artifact.cohort_omissions:
        lines.append("")
        lines.append("### Intentional omissions")
        lines.append("")
        for cohort, reason in sorted(artifact.cohort_omissions.items()):
            lines.append(f"- `{cohort}` — {reason}")
    lines.append("")

    # Network paths.
    lines.append("## Network paths")
    lines.append("")
    lines.append("| cohort | cloud_provider | region | endpoint_ip | probe_status |")
    lines.append("|--------|----------------|--------|-------------|--------------|")
    for cohort, entry in artifact.network_paths.items():
        if isinstance(entry, M6_1_2NetworkPath):
            lines.append(
                f"| `{cohort}` | {entry.cloud_provider} | "
                f"{entry.region or '—'} | `{entry.endpoint_ip}` | ok |"
            )
        else:
            lines.append(f"| `{cohort}` | — | — | — | error: `{entry.error}` |")
    lines.append("")

    # Per-cell timing table.
    lines.append("## Per-cell timing table")
    lines.append("")
    lines.append(
        "| cell | cohort | n_succ/n_att | engine_ttft_ms | seg_ab_ms | "
        "seg_queue_ms | seg_prefill_ms | seg_ingress_ms | seg_egress_ms |"
    )
    lines.append(
        "|------|--------|--------------|----------------|-----------|"
        "--------------|-----------------|-----------------|----------------|"
    )
    for m in artifact.measurements:
        ps = m.per_segment
        seg_ab = _fmt(ps.seg_ab_ms_mean if ps else None)
        seg_queue = _fmt(ps.seg_queue_ms_mean if ps else None)
        seg_prefill = _fmt(ps.seg_prefill_ms_mean if ps else None)
        seg_ingress = _fmt(ps.seg_ingress_ms_mean if ps else None)
        seg_egress = _fmt(ps.seg_egress_ms_mean if ps else None)
        lines.append(
            f"| `{_cell_id(m.path, m.concurrency)}` | `{m.cohort}` | "
            f"{m.n_successes}/{m.n_attempts} | {_fmt(m.engine_ttft_ms_mean)} | "
            f"{seg_ab} | {seg_queue} | {seg_prefill} | {seg_ingress} | "
            f"{seg_egress} |"
        )
    lines.append("")

    # FR-044 override fallback when the variance section is suppressed.
    phase_b = artifact.phase_b_trigger
    if phase_b is not None and phase_b.variance_section_suppressed:
        lines.append(
            "**Phase B trigger verdict** (per FR-044): Phase B trigger verdict "
            "unavailable (requires --m6_1_3-diagnose-repeat >= 3 for between-run "
            "variance compute)."
        )
        lines.append("")

    # Classifier-narratives subsection.
    lines.append("## Classifier verdicts")
    lines.append("")
    lines.append(_IDENTIFIER_LEGEND_LINE)
    lines.append("")
    for cell_id in sorted(artifact.classifications.keys()):
        label = artifact.classifications[cell_id]
        shares = _compute_segment_shares(artifact.measurements, cell_id)
        lines.extend(_render_classifier_narrative(cell_id, label, shares))

    # Per-Cohort Prompt-Content Audit (FR-016 + FR-016a + FR-017 + FR-018).
    if artifact.audit:
        lines.extend(
            _render_audit_section(
                artifact.audit,
                artifact.audit_per_run,
            )
        )

    # Between-run variance section (FR-025: rendered only when ≥ 3 runs
    # collected). The compute may have populated artifact.between_run_variance
    # on a 2-run sweep for programmatic inspection, but per FR-025 the
    # markdown section is suppressed; the FR-044 override fallback above
    # carries the operator-facing signal in that case.
    variance_should_render = (
        artifact.between_run_variance is not None
        and artifact.phase_b_trigger is not None
        and not artifact.phase_b_trigger.variance_section_suppressed
    )
    if artifact.between_run_variance and variance_should_render:
        lines.append("## Between-Run Variance")
        lines.append("")
        lines.append("| Cell × Cohort | mean_of_means (ms) | stddev_of_means (ms) | n_runs |")
        lines.append("|---|---:|---:|---:|")
        for cell_id in sorted(artifact.between_run_variance.keys()):
            per_cohort = artifact.between_run_variance[cell_id]
            for cohort in sorted(per_cohort.keys()):
                cell = per_cohort[cohort]
                lines.append(
                    f"| `{cell_id}` / `{cohort}` | "
                    f"{_fmt(cell.mean_of_means_ms)} | "
                    f"{_fmt(cell.stddev_of_means_ms)} | {cell.n_runs} |"
                )
        lines.append("")
        phase_b = artifact.phase_b_trigger
        if phase_b is not None and not phase_b.variance_section_suppressed:
            if phase_b.required:
                cells = ", ".join(phase_b.trigger_cells)
                lines.append(f"**Phase B trigger verdict**: Phase B required: {cells}")
            else:
                lines.append("**Phase B trigger verdict**: Phase B not required.")
            lines.append("")

    return "\n".join(lines) + "\n"


def write_m6_1_3_report(
    artifact: M6_1_3SweepArtifact,
    md_path: Path,
    json_path: Path,
) -> None:
    """Write the markdown report + JSON companion atomically.

    The FR-016 invariant check fires inside :func:`render_json` BEFORE
    either file is written — if the invariant is violated, ``ValueError``
    is raised and no partial artifact lands on disk.
    """
    payload = render_json(artifact)
    md = render_markdown(artifact)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# --- Helpers for sweep callers ----------------------------------------------


def aggregate_per_cohort_for_cell(
    measurements: list[M6_1_3CellMeasurement],
    cell_path: str,
    concurrency: int,
) -> dict[M6_1_2CohortKind, MultiPointTimings]:
    """Reshape per-cell-cohort measurements into the per_cohort dict the
    classifier expects.

    Used by the sweep orchestrator after :func:`_summarize_cell` to feed
    the classifier. Skips cohorts whose ``per_segment`` is ``None`` (the
    classifier handles missing per-cohort data via the legacy fallback /
    no-candidate-emits-inconclusive path).
    """
    per_cohort: dict[M6_1_2CohortKind, MultiPointTimings] = {}
    for m in measurements:
        if m.path != cell_path or m.concurrency != concurrency:
            continue
        if m.engine_ttft_ms_mean is None or m.per_segment is None:
            continue
        # The classifier reads engine_ttft_ms_mean + per_segment.seg_*_mean.
        # We synthesize a MultiPointTimings-shaped value here without
        # circular imports — the sweep doesn't strictly need M6_1_1Cell.
        from vllm_grpc_bench.m6_1_types import M6_1Cell

        cell = M6_1Cell(
            path=m.path,  # type: ignore[arg-type]
            hidden_size=4096,
            concurrency=m.concurrency,  # type: ignore[arg-type]
        )
        per_cohort[m.cohort] = MultiPointTimings(
            cohort=m.cohort,  # type: ignore[arg-type]
            cell=cell,
            engine_ttft_ms_mean=m.engine_ttft_ms_mean,
            engine_ttft_ms_ci_half_width=0.0,  # CI not required for classifier
            per_segment=m.per_segment,
            perturbation_total_us_mean=0.0,  # not consumed by classifier
        )
    return per_cohort


def _ci_half_width_95(samples: list[float]) -> float:
    """95% normal-approximation CI half-width (1.96 × stderr).

    Mirrors :func:`m6_1_1_sweep._ci_half_width` — kept here so the sweep
    aggregator doesn't need to import from M6.1.1's module. Returns 0.0
    when the sample is too small to estimate stddev (n < 2).
    """
    if len(samples) < 2:
        return 0.0
    stddev = float(statistics.stdev(samples))
    n = float(len(samples))
    return float(1.96 * stddev / (n**0.5))


__all__ = [
    "M6_1_3CellMeasurement",
    "M6_1_3RunMeta",
    "M6_1_3SweepArtifact",
    "_cell_id",
    "_ci_half_width_95",
    "aggregate_per_cohort_for_cell",
    "render_json",
    "render_markdown",
    "write_m6_1_3_report",
]
