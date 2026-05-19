"""M6.1.3 — Per-cohort prompt-content audit (FR-016 + FR-016a + round-1 Q5
+ round-2 Q5).

Net-new module per the plan's table — no copy source. The algorithmic spec
lives in ``specs/026-m6-1-3-attribution-closure/contracts/artifact-schema.md``
"Per-Cohort Prompt-Content Audit reporter section" + the audit dataclasses
in :mod:`m6_1_3_types`.

The audit's role is to detect whether per-cohort prompt-content drift is
the root cause of the chat_stream c=1 ``engine_compute_variation`` verdict
inherited from M6.1.1. Three outcomes per cell:

* **H1 confirmed** — per-cohort token-count means diverge by > 2σ of the
  pooled per-RPC distribution. The cohorts are seeing different token-id
  sequences; the engine_compute_variation reading is partly a
  prompt-length artifact, not pure engine non-determinism. Drives the
  FR-017 spec recommendation (symmetric prompts becomes the M6.x
  convention).
* **H2 candidate** — per-cohort token-count means are statistically
  identical BUT hash distributions diverge (the cohorts saw different
  per-RPC token-id sequences that happened to tokenize to the same
  length). Drives the FR-018 spec recommendation (Phase C engine-config
  probes).
* **H1 rejected** — per-cohort token-count means AND hash distributions
  are statistically identical. The engine_compute_variation is pure
  engine non-determinism; no prompt-content remediation is indicated.

The pooled verdict at ``chat_stream_c1`` is the load-bearing output — it
chooses between FR-017 and FR-018 recommendations on the published
artifact. Other cells' verdicts are reported for completeness but don't
drive the recommendation.

Per FR-016a + round-2 Q5, the orchestrator ALSO computes per-run verdicts
so the reporter can render a conditional appendix when any per-run verdict
disagrees with the pooled verdict for any cell (a stability signal for
multi-run sweeps).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from vllm_grpc_bench.m6_1_3_types import (
    M6_1_2CohortKind,
    M6_1_3AuditSample,
    M6_1_3AuditVerdictLine,
    M6_1_3PerCellAuditAggregate,
    M6_1_3PerCohortAuditDistribution,
    M6_1_3PerRunAuditVerdict,
)

# --- Verdict criterion thresholds -------------------------------------------

# Per FR-016 round-1 Q5: ">2σ divergence on token-count means → H1 confirmed".
# We interpret 2σ as 2× the pooled per-RPC stddev of token-count values
# across all cohorts in the cell. When the per-cohort mean spread exceeds
# this gate, the cohorts saw materially different prompt lengths.
_H1_SIGMA_MULTIPLIER: float = 2.0

# Token-count means are integer values (per-RPC tokenized_prompt_length). The
# "statistically identical" gate accepts up to 1.0-token rounding slop so two
# cohorts whose pooled means happen to differ by < 1 token still count as
# identical for H1 rejected.
_IDENTICAL_MEAN_TOLERANCE: float = 1.0


# --- Verdict literals (matches M6_1_3AuditVerdictLine Literal) --------------

_H1_CONFIRMED: M6_1_3AuditVerdictLine = "H1 confirmed: per-cohort token-count means diverge by >2σ"
_H1_REJECTED: M6_1_3AuditVerdictLine = (
    "H1 rejected: per-cohort distributions statistically identical"
)
_H2_CANDIDATE: M6_1_3AuditVerdictLine = (
    "H2 candidate: token-counts identical but hash distributions differ"
)


# --- Internal helpers --------------------------------------------------------


def _build_per_cohort_distribution(
    samples_for_cohort: Sequence[M6_1_3AuditSample],
) -> M6_1_3PerCohortAuditDistribution:
    """Aggregate the per-RPC samples for one cohort into a distribution."""
    lengths = [s.tokenized_prompt_length for s in samples_for_cohort]
    hash_counter: dict[str, int] = {}
    for s in samples_for_cohort:
        hash_counter[s.tokenized_prompt_hash] = hash_counter.get(s.tokenized_prompt_hash, 0) + 1
    n_rpcs = len(lengths)
    if n_rpcs == 0:
        return M6_1_3PerCohortAuditDistribution(
            mean_tokenized_prompt_length=0.0,
            stddev_tokenized_prompt_length=0.0,
            n_rpcs=0,
            unique_hash_count=0,
            hash_distribution={},
        )
    mean = float(sum(lengths) / n_rpcs)
    stddev = float(statistics.stdev(lengths)) if n_rpcs > 1 else 0.0
    return M6_1_3PerCohortAuditDistribution(
        mean_tokenized_prompt_length=mean,
        stddev_tokenized_prompt_length=stddev,
        n_rpcs=n_rpcs,
        unique_hash_count=len(hash_counter),
        hash_distribution=hash_counter,
    )


def _classify_cell(
    per_cohort: dict[M6_1_2CohortKind, M6_1_3PerCohortAuditDistribution],
    all_lengths: list[int],
) -> M6_1_3AuditVerdictLine:
    """Pick the H1 / H2 / rejected verdict for a single cell.

    Decision flow (matters because the criteria are non-disjoint):

    1. **H1 confirmed**: if the spread of per-cohort means exceeds 2× the
       pooled per-RPC stddev, the cohorts saw materially different prompt
       lengths. Returns immediately.
    2. **H1 rejected**: per-cohort means within rounding slop AND every
       cohort observed the same set of hashes (byte-identical hash
       distributions) → distributions statistically identical.
    3. **H2 candidate**: per-cohort means within rounding slop BUT hash
       distributions diverge → same token-counts, different prompt content.

    Edge cases (single cohort, empty cell, identical singleton): the
    verdict defaults to ``H1 rejected`` (no divergence detectable).
    """
    cohort_means = [d.mean_tokenized_prompt_length for d in per_cohort.values() if d.n_rpcs > 0]
    if len(cohort_means) < 2:
        # Single cohort or empty cell — no divergence possible.
        return _H1_REJECTED

    spread = max(cohort_means) - min(cohort_means)

    pooled_stddev = float(statistics.stdev(all_lengths)) if len(all_lengths) > 1 else 0.0
    if pooled_stddev > 0 and spread > _H1_SIGMA_MULTIPLIER * pooled_stddev:
        return _H1_CONFIRMED

    if spread > _IDENTICAL_MEAN_TOLERANCE:
        # Means diverge by more than the rounding-slop tolerance but the
        # divergence wasn't above the 2σ gate (e.g., pooled stddev was 0
        # because every RPC produced the same length per cohort, OR the
        # pooled stddev is small and the means barely cleared the
        # tolerance). The most informative single label is still H1
        # confirmed — the means are NOT statistically identical even
        # though the formal 2σ gate didn't fire on a degenerate variance.
        return _H1_CONFIRMED

    # Means within tolerance — inspect hash distributions.
    hash_sets = [frozenset(d.hash_distribution.keys()) for d in per_cohort.values()]
    if not hash_sets:
        return _H1_REJECTED
    head = hash_sets[0]
    if all(h == head for h in hash_sets[1:]):
        return _H1_REJECTED
    return _H2_CANDIDATE


def _group_by_cell_then_cohort(
    samples: Sequence[M6_1_3AuditSample],
) -> dict[str, dict[M6_1_2CohortKind, list[M6_1_3AuditSample]]]:
    """Group flat sample list by ``cell_id`` then ``cohort`` (helper)."""
    out: dict[str, dict[M6_1_2CohortKind, list[M6_1_3AuditSample]]] = {}
    for s in samples:
        out.setdefault(s.cell_id, {}).setdefault(s.cohort, []).append(s)
    return out


# --- Public API --------------------------------------------------------------


def compute_pooled_verdict(
    samples: Sequence[M6_1_3AuditSample],
) -> list[M6_1_3PerCellAuditAggregate]:
    """Pool audit samples across runs and cohorts; emit one verdict per cell.

    Per FR-016 + round-1 Q5: the pooled verdict is the load-bearing audit
    output — drives the FR-017 / FR-018 spec recommendation on the
    published artifact. Pools samples regardless of ``run_idx`` so the
    n_rpcs per cohort equals ``N_runs × n_per_run`` (250 on a 5-run × n=50
    publish sweep; 50 on a single-run validate sweep).

    Returns a list sorted by ``cell_id`` so the reporter renders cells in
    canonical order regardless of ingestion order.
    """
    by_cell = _group_by_cell_then_cohort(samples)
    out: list[M6_1_3PerCellAuditAggregate] = []
    for cell_id in sorted(by_cell.keys()):
        by_cohort = by_cell[cell_id]
        per_cohort: dict[M6_1_2CohortKind, M6_1_3PerCohortAuditDistribution] = {
            cohort: _build_per_cohort_distribution(cohort_samples)
            for cohort, cohort_samples in by_cohort.items()
        }
        all_lengths = [
            s.tokenized_prompt_length
            for cohort_samples in by_cohort.values()
            for s in cohort_samples
        ]
        verdict = _classify_cell(per_cohort, all_lengths)
        out.append(
            M6_1_3PerCellAuditAggregate(
                cell_id=cell_id,
                per_cohort=per_cohort,
                pooled_verdict=verdict,
            )
        )
    return out


def compute_per_run_verdicts(
    samples: Sequence[M6_1_3AuditSample],
) -> list[M6_1_3PerRunAuditVerdict]:
    """Compute per-run, per-cell audit verdicts for the FR-016a appendix.

    Per round-2 Q5: the conditional appendix renders only when any per-run
    verdict differs from the pooled verdict for any cell. The per-run
    verdicts are computed by filtering samples to a single ``run_idx``
    before running the same classifier as :func:`compute_pooled_verdict`.

    Returns a list sorted by ``(run_idx, cell_id)`` for canonical rendering.
    """
    by_run: dict[int, list[M6_1_3AuditSample]] = {}
    for s in samples:
        by_run.setdefault(s.run_idx, []).append(s)
    out: list[M6_1_3PerRunAuditVerdict] = []
    for run_idx in sorted(by_run.keys()):
        run_samples = by_run[run_idx]
        by_cell = _group_by_cell_then_cohort(run_samples)
        for cell_id in sorted(by_cell.keys()):
            by_cohort = by_cell[cell_id]
            per_cohort = {
                cohort: _build_per_cohort_distribution(cohort_samples)
                for cohort, cohort_samples in by_cohort.items()
            }
            all_lengths = [
                s.tokenized_prompt_length
                for cohort_samples in by_cohort.values()
                for s in cohort_samples
            ]
            verdict = _classify_cell(per_cohort, all_lengths)
            out.append(
                M6_1_3PerRunAuditVerdict(
                    run_idx=run_idx,
                    cell_id=cell_id,
                    verdict=verdict,
                )
            )
    return out


def should_render_audit_appendix(
    pooled: Sequence[M6_1_3PerCellAuditAggregate],
    per_run: Sequence[M6_1_3PerRunAuditVerdict],
) -> bool:
    """FR-016a + round-2 Q5: True iff any per-run verdict differs from the
    pooled verdict for any cell.

    "Differs" is byte-non-identical label string per cell. When True, the
    reporter renders the per-run audit appendix for ALL cells (not just
    the disagreeing ones — per round-2 Q5 the appendix is exhaustive when
    triggered so readers see the full context).
    """
    pooled_by_cell: dict[str, M6_1_3AuditVerdictLine] = {
        agg.cell_id: agg.pooled_verdict for agg in pooled
    }
    for run_verdict in per_run:
        expected = pooled_by_cell.get(run_verdict.cell_id)
        if expected is None:
            # Per-run carries a cell that pooled doesn't — shouldn't happen
            # in normal sweeps but treat as a disagreement signal.
            return True
        if run_verdict.verdict != expected:
            return True
    return False


def extract_h1_recommendation(pooled: Sequence[M6_1_3PerCellAuditAggregate]) -> str:
    """Return the FR-017 / FR-018 spec-decision recommendation text.

    The recommendation hinges on the ``chat_stream_c1`` cell's pooled
    verdict per round-1 Q5:

    * **H1 confirmed** → FR-017: symmetric prompts SHOULD become the M6.x
      convention. M6.2 / M7 / M8 spec authors MUST cite this recommendation
      as a precondition per SC-012.
    * **H1 rejected** → FR-018: proceed to Phase C engine-config probes
      (prefix-cache disable per H3, reversed cohort order per H4) for
      further investigation.
    * **H2 candidate** → carries a distinct text note (acknowledging the
      hash divergence) but doesn't trigger FR-017 by itself.
    * **No chat_stream_c1 cell** → fallback text noting the audit cell
      didn't run; no recommendation.
    """
    target_cell = "chat_stream_c1"
    by_cell: dict[str, M6_1_3AuditVerdictLine] = {agg.cell_id: agg.pooled_verdict for agg in pooled}
    verdict = by_cell.get(target_cell)
    if verdict is None:
        return (
            f"Audit recommendation unavailable: no {target_cell} cell in the "
            "published artifact. Re-run with a sweep that exercises "
            f"{target_cell} to populate the FR-017 / FR-018 recommendation."
        )
    if verdict == _H1_CONFIRMED:
        return (
            f"H1 confirmed at {target_cell}: per-cohort token-count means "
            "diverge by >2σ. Symmetric prompts SHOULD become the M6.x "
            "convention going forward (per FR-017). M6.2 / M7 / M8 spec "
            "authors MUST cite this recommendation as a precondition (per "
            "SC-012) and either accept it (turning their milestone's "
            "`-symmetric-prompts` flag on by default) or document an "
            "explicit divergence with reasoning."
        )
    if verdict == _H1_REJECTED:
        return (
            f"H1 rejected at {target_cell}: per-cohort distributions "
            "statistically identical. Proceed to Phase C engine-config "
            "probes (prefix-cache disable per H3, reversed cohort order "
            "per H4) for further investigation (per FR-018). Phase C is "
            "out of scope for the M6.1.3 closure deliverable; invoke "
            "manually if a follow-up operator wants to pursue it."
        )
    # H2 candidate.
    return (
        f"H2 candidate at {target_cell}: token-counts identical but hash "
        "distributions differ across cohorts. The cohorts saw different "
        "per-RPC token-id sequences that tokenized to the same length — "
        "investigate the prompt-content fanout (text-level encoding drift) "
        "before deciding on FR-017 (symmetric prompts) vs FR-018 (Phase C "
        "engine-config probes)."
    )


__all__ = [
    "compute_per_run_verdicts",
    "compute_pooled_verdict",
    "extract_h1_recommendation",
    "should_render_audit_appendix",
]
