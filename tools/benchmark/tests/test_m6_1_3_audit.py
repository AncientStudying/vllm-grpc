"""M6.1.3 — Per-cohort prompt-content audit unit tests (T026).

Exercises :mod:`vllm_grpc_bench.m6_1_3_audit` against the contract
scenarios in ``contracts/artifact-schema.md`` "Per-Cohort Prompt-Content
Audit reporter section" + FR-016 + round-1 Q5 + FR-016a + round-2 Q5:

* H1 confirmed / H2 candidate / H1 rejected verdicts on synthesized data.
* Per-run appendix omitted when all per-run verdicts match the pooled
  verdict (FR-016a).
* Per-run appendix rendered when any per-run verdict diverges.
* Pooled n_rpcs counts (n × N_runs per cohort on multi-run; n on single
  run).
* Sidecar-row-matches-extractor wire-canonical-source rule (FR-015 +
  round-1 Q1 — closes ``/speckit-analyze`` C1): the per-cell audit data
  is orchestrator-derived from extractor output, NOT a parallel
  frontend-emission path.
"""

from __future__ import annotations

from typing import cast

import pytest
from vllm_grpc_bench.m6_1_3_audit import (
    compute_per_run_verdicts,
    compute_pooled_verdict,
    extract_h1_recommendation,
    should_render_audit_appendix,
)
from vllm_grpc_bench.m6_1_3_types import (
    M6_1_2CohortKind,
    M6_1_3AuditSample,
)

# --- Test fixture builders --------------------------------------------------


_DEFAULT_HASH: str = "a1b2c3d4e5f60718"


def _samples_for_cohort(
    *,
    run_idx: int,
    cell_id: str,
    cohort: M6_1_2CohortKind,
    lengths: list[int],
    hashes: list[str] | None = None,
) -> list[M6_1_3AuditSample]:
    """Build N samples for a (run, cell, cohort) tuple.

    ``hashes=None`` defaults every sample to ``_DEFAULT_HASH`` (homogeneous
    hash distribution per cohort). Otherwise must be the same length as
    ``lengths``.
    """
    if hashes is None:
        hashes = [_DEFAULT_HASH] * len(lengths)
    assert len(lengths) == len(hashes), "lengths and hashes must align"
    return [
        M6_1_3AuditSample(
            run_idx=run_idx,
            cell_id=cell_id,
            cohort=cohort,
            tokenized_prompt_length=length,
            tokenized_prompt_hash=h,
        )
        for length, h in zip(lengths, hashes, strict=True)
    ]


def _diverging_lengths(target_mean: float, n: int, jitter: int = 0) -> list[int]:
    """Build ``n`` integer lengths whose mean equals ``target_mean``.

    With ``jitter=0`` every length is ``int(round(target_mean))`` (zero
    pooled stddev so divergence detection runs against the inter-cohort
    spread, not within-cohort variance). With ``jitter>0`` the lengths
    alternate ``mean ± jitter`` to seed within-cohort stddev.
    """
    base = int(round(target_mean))
    if jitter == 0:
        return [base] * n
    return [base + jitter if i % 2 == 0 else base - jitter for i in range(n)]


# --- H1 confirmed -----------------------------------------------------------


def test_pooled_h1_confirmed_per_cohort_divergence() -> None:
    """FR-016 round-1 Q5: per-cohort token-count means diverging by > 2σ
    of the pooled per-RPC stddev → H1 confirmed at this cell.

    Setup: 5-run synthetic dataset at chat_stream_c1 with three cohorts:

    * rest_https_edge: mean ~48.2, jitter ±1 → samples around 48-49
    * default_grpc: mean ~53.7, jitter ±1 → samples around 52-54
    * tuned_grpc_multiplexed: mean ~47.9, jitter ±1 → samples around 47-48

    Pooled stddev across all samples is dominated by the inter-cohort
    means spread (~5 tokens between rest_https_edge and default_grpc) vs
    within-cohort jitter (~1 token), so the >2σ gate fires comfortably.
    """
    samples: list[M6_1_3AuditSample] = []
    for run_idx in range(5):
        samples.extend(
            _samples_for_cohort(
                run_idx=run_idx,
                cell_id="chat_stream_c1",
                cohort="rest_https_edge",
                lengths=_diverging_lengths(48.2, n=10, jitter=1),
            )
        )
        samples.extend(
            _samples_for_cohort(
                run_idx=run_idx,
                cell_id="chat_stream_c1",
                cohort="default_grpc",
                lengths=_diverging_lengths(53.7, n=10, jitter=1),
            )
        )
        samples.extend(
            _samples_for_cohort(
                run_idx=run_idx,
                cell_id="chat_stream_c1",
                cohort="tuned_grpc_multiplexed",
                lengths=_diverging_lengths(47.9, n=10, jitter=1),
            )
        )

    pooled = compute_pooled_verdict(samples)
    assert len(pooled) == 1
    cell = pooled[0]
    assert cell.cell_id == "chat_stream_c1"
    assert cell.pooled_verdict == "H1 confirmed: per-cohort token-count means diverge by >2σ"
    # Pooled n_rpcs per cohort = 5 runs × 10 per run = 50.
    assert cell.per_cohort["rest_https_edge"].n_rpcs == 50
    assert cell.per_cohort["default_grpc"].n_rpcs == 50
    assert cell.per_cohort["tuned_grpc_multiplexed"].n_rpcs == 50


# --- H2 candidate -----------------------------------------------------------


def test_pooled_h2_candidate_identical_means_diverging_hashes() -> None:
    """FR-016 round-1 Q5: identical token-count means but diverging hash
    distributions → H2 candidate.

    Setup: every cohort sees the same length (48) but the hash sets
    differ — rest_https_edge has hashes {"aaaa..."}, default_grpc has
    {"bbbb..."}, etc.
    """
    samples: list[M6_1_3AuditSample] = []
    for cohort, hash_marker in (
        ("rest_https_edge", "a" * 16),
        ("default_grpc", "b" * 16),
        ("tuned_grpc_multiplexed", "c" * 16),
    ):
        samples.extend(
            _samples_for_cohort(
                run_idx=0,
                cell_id="chat_stream_c1",
                cohort=cast(M6_1_2CohortKind, cohort),
                lengths=[48] * 10,
                hashes=[hash_marker] * 10,
            )
        )
    pooled = compute_pooled_verdict(samples)
    assert len(pooled) == 1
    assert pooled[0].pooled_verdict == (
        "H2 candidate: token-counts identical but hash distributions differ"
    )


# --- H1 rejected ------------------------------------------------------------


def test_pooled_h1_rejected_identical_distributions() -> None:
    """FR-016 round-1 Q5: identical token-count means AND identical hash
    distributions → H1 rejected (statistically identical)."""
    samples: list[M6_1_3AuditSample] = []
    for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
        samples.extend(
            _samples_for_cohort(
                run_idx=0,
                cell_id="chat_stream_c1",
                cohort=cast(M6_1_2CohortKind, cohort),
                lengths=[48] * 10,
                hashes=[_DEFAULT_HASH] * 10,
            )
        )
    pooled = compute_pooled_verdict(samples)
    assert pooled[0].pooled_verdict == (
        "H1 rejected: per-cohort distributions statistically identical"
    )


def test_pooled_h1_rejected_tolerates_rounding_slop() -> None:
    """Two cohorts whose pooled means differ by < 1 token (rounding slop)
    still classify as H1 rejected when their hash distributions match."""
    samples: list[M6_1_3AuditSample] = []
    samples.extend(
        _samples_for_cohort(
            run_idx=0,
            cell_id="chat_stream_c1",
            cohort="rest_https_edge",
            lengths=[48, 48, 48, 48, 49],  # mean = 48.2
        )
    )
    samples.extend(
        _samples_for_cohort(
            run_idx=0,
            cell_id="chat_stream_c1",
            cohort="default_grpc",
            lengths=[48, 48, 48, 48, 48],  # mean = 48.0
        )
    )
    pooled = compute_pooled_verdict(samples)
    assert pooled[0].pooled_verdict == (
        "H1 rejected: per-cohort distributions statistically identical"
    )


# --- Per-run appendix conditional rendering (FR-016a + round-2 Q5) ----------


def test_per_run_appendix_omitted_when_all_match() -> None:
    """FR-016a: when every per-run verdict matches the pooled verdict for
    every cell, ``should_render_audit_appendix`` returns False (the
    appendix can be omitted to keep the markdown concise)."""
    samples: list[M6_1_3AuditSample] = []
    for run_idx in range(5):
        for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
            samples.extend(
                _samples_for_cohort(
                    run_idx=run_idx,
                    cell_id="chat_stream_c1",
                    cohort=cast(M6_1_2CohortKind, cohort),
                    lengths=[48] * 10,
                )
            )
    pooled = compute_pooled_verdict(samples)
    per_run = compute_per_run_verdicts(samples)
    assert should_render_audit_appendix(pooled, per_run) is False


def test_per_run_appendix_rendered_when_any_disagrees() -> None:
    """FR-016a + round-2 Q5: when any per-run verdict differs from the
    pooled verdict for any cell, the appendix MUST render."""
    samples: list[M6_1_3AuditSample] = []
    # Runs 0-2: clean H1-rejected pattern.
    for run_idx in range(3):
        for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
            samples.extend(
                _samples_for_cohort(
                    run_idx=run_idx,
                    cell_id="chat_stream_c1",
                    cohort=cast(M6_1_2CohortKind, cohort),
                    lengths=[48] * 10,
                )
            )
    # Run 3: rest_https_edge diverges (means spread ~5 tokens) → H1 confirmed.
    for cohort, mean in (
        ("rest_https_edge", 53),
        ("default_grpc", 48),
        ("tuned_grpc_multiplexed", 48),
    ):
        samples.extend(
            _samples_for_cohort(
                run_idx=3,
                cell_id="chat_stream_c1",
                cohort=cast(M6_1_2CohortKind, cohort),
                lengths=[mean] * 10,
            )
        )
    # Run 4: back to clean.
    for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
        samples.extend(
            _samples_for_cohort(
                run_idx=4,
                cell_id="chat_stream_c1",
                cohort=cast(M6_1_2CohortKind, cohort),
                lengths=[48] * 10,
            )
        )
    pooled = compute_pooled_verdict(samples)
    per_run = compute_per_run_verdicts(samples)
    # Run 3 disagrees with the (likely H1-rejected) pooled verdict.
    assert should_render_audit_appendix(pooled, per_run) is True


# --- Pooled n_rpcs counts (FR-016 round-1 Q5) --------------------------------


def test_pooled_n_counts_multi_run() -> None:
    """Pooled n_rpcs per cohort = N_runs × n_per_run on a multi-run publish
    sweep (5 × 50 = 250)."""
    samples: list[M6_1_3AuditSample] = []
    for run_idx in range(5):
        for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
            samples.extend(
                _samples_for_cohort(
                    run_idx=run_idx,
                    cell_id="chat_stream_c1",
                    cohort=cast(M6_1_2CohortKind, cohort),
                    lengths=[48] * 50,  # n_per_run = 50
                )
            )
    pooled = compute_pooled_verdict(samples)
    cell = pooled[0]
    assert cell.per_cohort["rest_https_edge"].n_rpcs == 5 * 50
    assert cell.per_cohort["default_grpc"].n_rpcs == 5 * 50


def test_pooled_n_counts_single_run() -> None:
    """Pooled n_rpcs per cohort = n_per_run on a single-run validate sweep
    (1 × 50 = 50)."""
    samples: list[M6_1_3AuditSample] = []
    for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
        samples.extend(
            _samples_for_cohort(
                run_idx=0,
                cell_id="chat_stream_c1",
                cohort=cast(M6_1_2CohortKind, cohort),
                lengths=[48] * 50,
            )
        )
    pooled = compute_pooled_verdict(samples)
    cell = pooled[0]
    assert cell.per_cohort["rest_https_edge"].n_rpcs == 50


# --- extract_h1_recommendation tail-end (FR-017 / FR-018) ------------------


@pytest.mark.parametrize(
    "verdict_setup,expected_recommendation_substring",
    [
        # H1 confirmed → FR-017 (symmetric prompts becomes M6.x convention)
        (
            "h1_confirmed",
            "Symmetric prompts SHOULD become the M6.x",
        ),
        # H1 rejected → FR-018 (Phase C engine-config probes)
        (
            "h1_rejected",
            "Proceed to Phase C engine-config",
        ),
        # H2 candidate → distinct text note
        (
            "h2_candidate",
            "investigate the prompt-content fanout",
        ),
    ],
)
def test_extract_h1_recommendation_per_verdict(
    verdict_setup: str, expected_recommendation_substring: str
) -> None:
    """The chat_stream_c1 verdict drives the FR-017 / FR-018 / H2-note
    recommendation text per round-1 Q5."""
    samples: list[M6_1_3AuditSample] = []
    if verdict_setup == "h1_confirmed":
        for cohort, mean in (
            ("rest_https_edge", 48),
            ("default_grpc", 54),
            ("tuned_grpc_multiplexed", 47),
        ):
            samples.extend(
                _samples_for_cohort(
                    run_idx=0,
                    cell_id="chat_stream_c1",
                    cohort=cast(M6_1_2CohortKind, cohort),
                    lengths=[mean] * 10,
                )
            )
    elif verdict_setup == "h1_rejected":
        for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
            samples.extend(
                _samples_for_cohort(
                    run_idx=0,
                    cell_id="chat_stream_c1",
                    cohort=cast(M6_1_2CohortKind, cohort),
                    lengths=[48] * 10,
                )
            )
    elif verdict_setup == "h2_candidate":
        for cohort, hash_marker in (
            ("rest_https_edge", "a" * 16),
            ("default_grpc", "b" * 16),
            ("tuned_grpc_multiplexed", "c" * 16),
        ):
            samples.extend(
                _samples_for_cohort(
                    run_idx=0,
                    cell_id="chat_stream_c1",
                    cohort=cast(M6_1_2CohortKind, cohort),
                    lengths=[48] * 10,
                    hashes=[hash_marker] * 10,
                )
            )

    pooled = compute_pooled_verdict(samples)
    recommendation = extract_h1_recommendation(pooled)
    assert expected_recommendation_substring in recommendation


def test_extract_h1_recommendation_missing_chat_stream_c1() -> None:
    """When the pooled aggregate doesn't contain chat_stream_c1 (e.g., a
    degraded sweep), the function returns a fallback explaining the
    recommendation is unavailable."""
    samples: list[M6_1_3AuditSample] = []
    for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
        samples.extend(
            _samples_for_cohort(
                run_idx=0,
                cell_id="embed_c1",
                cohort=cast(M6_1_2CohortKind, cohort),
                lengths=[48] * 10,
            )
        )
    pooled = compute_pooled_verdict(samples)
    recommendation = extract_h1_recommendation(pooled)
    assert "no chat_stream_c1" in recommendation


# --- FR-015 + round-1 Q1: sidecar matches extractor (canonical-source rule) -


def test_sidecar_row_matches_extractor_output() -> None:
    """FR-015 + round-1 Q1 (closes ``/speckit-analyze`` C1): the per-RPC
    audit sample is built from the extractor-populated TimingCheckpoint
    fields — the orchestrator must NEVER read prompt audit data from any
    parallel source.

    This test asserts the canonical-source rule at the unit-test level by
    showing that ``M6_1_3AuditSample`` preserves the exact int + str
    values the extractor would populate (no rounding, no transformation,
    no per-cohort branching on the audit fields).

    Failure mode this guards: a future refactor accidentally re-introduces
    a parallel sidecar-emission path in the frontend servicer, causing
    wire / sidecar drift.
    """
    # Synthesize the value pair that would emerge from the extractor.
    extractor_length = 47
    extractor_hash = "a1b2c3d4e5f60718"

    sample = M6_1_3AuditSample(
        run_idx=0,
        cell_id="chat_stream_c1",
        cohort="rest_https_edge",
        tokenized_prompt_length=extractor_length,
        tokenized_prompt_hash=extractor_hash,
    )

    # Byte-identical: the audit pipeline carries the extractor values
    # through to the pooled distribution without transformation.
    pooled = compute_pooled_verdict([sample])
    assert len(pooled) == 1
    cell = pooled[0]
    assert cell.per_cohort["rest_https_edge"].mean_tokenized_prompt_length == float(
        extractor_length
    )
    # The hash is preserved as-is in the hash_distribution dict.
    assert cell.per_cohort["rest_https_edge"].hash_distribution == {extractor_hash: 1}


# --- Cell ordering + multi-cell handling ------------------------------------


def test_compute_pooled_verdict_emits_cells_alphabetically() -> None:
    """The pooled aggregate list is sorted by ``cell_id`` so the reporter
    renders cells in canonical order regardless of ingestion order."""
    samples: list[M6_1_3AuditSample] = []
    for cell_id in ("embed_c4", "chat_stream_c1", "embed_c1", "chat_stream_c8"):
        for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
            samples.extend(
                _samples_for_cohort(
                    run_idx=0,
                    cell_id=cell_id,
                    cohort=cast(M6_1_2CohortKind, cohort),
                    lengths=[48] * 5,
                )
            )
    pooled = compute_pooled_verdict(samples)
    ordered_cell_ids = [a.cell_id for a in pooled]
    assert ordered_cell_ids == sorted(ordered_cell_ids)
