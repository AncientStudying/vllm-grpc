"""Cohort-independent prompt-assignment + symmetry-invariant helpers.

A cross-milestone shared module: ``assign_symmetric_prompt`` is the canonical
import target for any sweep that needs cohort-symmetric prompt selection.

The M5.2-era 3-tier symmetry-block machinery (``build_symmetry_block`` /
``assert_symmetry`` + their dataclasses) was removed at Phase 4 (T020a) when
the M5.2 sweep/regen sources were deleted; the forward survivors below carry
no milestone-prefixed dependency.
"""

from __future__ import annotations

import json


class SymmetryAssertionFailed(RuntimeError):
    """Raised by :func:`validate_symmetric_invariant` on divergence.

    The exception message names the diverging tier, field, and cohort pair so
    the operator can `grep` the symmetry block in the published JSON to
    locate the divergent state.
    """

    def __init__(
        self,
        *,
        tier: str,
        field: str,
        cohort_a: str = "",
        cohort_b: str = "",
        observed_a: str = "",
        observed_b: str = "",
    ) -> None:
        self.tier = tier
        self.field = field
        self.cohort_a = cohort_a
        self.cohort_b = cohort_b
        self.observed_a = observed_a
        self.observed_b = observed_b
        msg = (
            f"tier_{tier}_divergence: field={field}"
            + (f", cohort_a={cohort_a}" if cohort_a else "")
            + (f", cohort_b={cohort_b}" if cohort_b else "")
            + (f", observed_a={observed_a[:16]}…" if observed_a else "")
            + (f", observed_b={observed_b[:16]}…" if observed_b else "")
        )
        super().__init__(msg)


def assign_symmetric_prompt[T](
    iter_idx: int,
    cohort: str,
    corpus: list[T],
) -> T:
    """Return ``corpus[iter_idx % len(corpus)]`` regardless of ``cohort``.

    When symmetric-prompts mode is set, every cohort sees the SAME prompt at
    the SAME iteration index. The deterministic assignment is
    ``corpus[iter_idx % len(corpus)]``; ``cohort`` is accepted but
    intentionally ignored so the function signature documents the symmetry
    guarantee at the call site. Generic over the corpus element type so the
    embed regime can pass ``list[CompletionEmbedSample]`` alongside chat's
    ``list[RequestSample]`` or ``list[str]``.
    """
    del cohort  # Symmetric-prompts mode: prompt is cohort-invariant by design.
    if not corpus:
        raise ValueError("assign_symmetric_prompt: corpus must be non-empty")
    return corpus[iter_idx % len(corpus)]


def validate_symmetric_invariant(
    per_cohort_distributions: dict[str, dict[str, int]],
) -> None:
    """Assert per-cohort distributions are byte-identical (FR-020).

    Input shape: ``{cohort_name: {prompt_or_hash: count}}``. Raises
    :class:`SymmetryAssertionFailed` (tier ``b``, field
    ``symmetric_prompt_distribution``) when any two cohorts have divergent
    distributions. Returns ``None`` on success.
    """
    if len(per_cohort_distributions) < 2:
        # Single cohort (or empty): nothing to compare against.
        return
    cohorts = sorted(per_cohort_distributions.keys())
    head_cohort = cohorts[0]
    head_dist = per_cohort_distributions[head_cohort]
    for cohort in cohorts[1:]:
        observed = per_cohort_distributions[cohort]
        if observed != head_dist:
            head_summary = json.dumps(head_dist, sort_keys=True, separators=(",", ":"))
            observed_summary = json.dumps(observed, sort_keys=True, separators=(",", ":"))
            raise SymmetryAssertionFailed(
                tier="b",
                field="symmetric_prompt_distribution",
                cohort_a=head_cohort,
                cohort_b=cohort,
                observed_a=head_summary,
                observed_b=observed_summary,
            )
