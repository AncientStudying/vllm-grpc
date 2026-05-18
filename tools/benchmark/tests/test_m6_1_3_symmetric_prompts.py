"""M6.1.3 — symmetric-prompts shared helper tests (T027).

Exercises :mod:`vllm_grpc_bench.symmetric_prompts` per FR-019 + round-2 Q4
+ R-6:

* ``assign_symmetric_prompt`` returns the same prompt for the same
  iteration index across cohorts (cohort-invariant deterministic mapping).
* The M5.2 back-compat shim (``m5_2_symmetry``) re-exports the helper so
  legacy imports resolve to the relocated module without behaviour change.
* ``validate_symmetric_invariant`` raises on per-cohort distribution
  divergence and accepts byte-identical distributions silently.
* Symmetric-mode invariant per FR-020: when the sweep dispatches via
  ``assign_symmetric_prompt``, per-cohort token-count + token-hash
  distributions are byte-identical for the same iteration index.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.symmetric_prompts import (
    SymmetryAssertionFailed,
    assign_symmetric_prompt,
    validate_symmetric_invariant,
)

# --- Test fixture builder ---------------------------------------------------


_CORPUS: list[str] = [
    "What is the capital of France?",
    "Explain transformers in one sentence.",
    "Translate 'hello' to Spanish.",
    "Summarise quantum entanglement.",
    "List three mammals.",
]


# --- assign_symmetric_prompt: cohort-invariant assignment ------------------


def test_shared_helper_roundtrip_same_iter_same_prompt_across_cohorts() -> None:
    """FR-019 + round-2 Q4: ``assign_symmetric_prompt(iter_idx, cohort,
    corpus)`` returns the same prompt for the same ``iter_idx`` regardless
    of ``cohort``."""
    for iter_idx in range(20):
        prompts = {
            cohort: assign_symmetric_prompt(iter_idx, cohort, _CORPUS)
            for cohort in (
                "rest_https_edge",
                "rest_plain_tcp",
                "default_grpc",
                "tuned_grpc_multiplexed",
            )
        }
        # All four cohorts saw the same prompt at this iteration.
        unique_prompts = set(prompts.values())
        assert len(unique_prompts) == 1, (
            f"iter_idx={iter_idx}: cohorts saw different prompts {prompts}"
        )


def test_shared_helper_corpus_modulo_wrap() -> None:
    """When ``iter_idx >= len(corpus)`` the assignment wraps deterministically:
    ``corpus[iter_idx % len(corpus)]``."""
    n = len(_CORPUS)
    for iter_idx in range(n, n * 3):
        prompt = assign_symmetric_prompt(iter_idx, "rest_https_edge", _CORPUS)
        assert prompt == _CORPUS[iter_idx % n]


def test_shared_helper_empty_corpus_raises() -> None:
    """Empty corpus is a misuse (no prompts to assign); the helper raises
    ``ValueError`` rather than returning a sentinel."""
    with pytest.raises(ValueError, match="corpus must be non-empty"):
        assign_symmetric_prompt(0, "rest_https_edge", [])


# --- M5.2 back-compat via re-export shim (R-6 + FR-037) --------------------


def test_m5_2_back_compat_via_shim() -> None:
    """R-6: the M5.2 import path (``vllm_grpc_bench.m5_2_symmetry``) is a
    re-export shim that resolves to the relocated module. M5.2's
    historical re-runnability per FR-037 holds because the import name
    + symbol surface didn't change.
    """
    from vllm_grpc_bench import m5_2_symmetry, symmetric_prompts

    # The shim re-exports the same callable, not a wrapper.
    assert m5_2_symmetry.assign_symmetric_prompt is symmetric_prompts.assign_symmetric_prompt
    assert (
        m5_2_symmetry.validate_symmetric_invariant is symmetric_prompts.validate_symmetric_invariant
    )
    # And the M5.2-era tier dataclasses also import cleanly through the shim.
    assert m5_2_symmetry.SymmetryAssertionFailed is symmetric_prompts.SymmetryAssertionFailed


def test_m5_2_legacy_import_behavior_preserved() -> None:
    """Calling ``assign_symmetric_prompt`` via the M5.2 shim produces the
    same output as calling it via the relocated module."""
    from vllm_grpc_bench.m5_2_symmetry import (
        assign_symmetric_prompt as legacy_assign,
    )

    for iter_idx in range(10):
        via_shim = legacy_assign(iter_idx, "rest_https_edge", _CORPUS)
        via_direct = assign_symmetric_prompt(iter_idx, "rest_https_edge", _CORPUS)
        assert via_shim == via_direct


# --- validate_symmetric_invariant: byte-identical distributions ------------


def test_validate_symmetric_invariant_accepts_identical_distributions() -> None:
    """When every cohort's distribution dict is byte-identical, the
    validator returns ``None`` without raising."""
    distribution = {"prompt_a": 10, "prompt_b": 5, "prompt_c": 3}
    per_cohort = {
        "rest_https_edge": dict(distribution),
        "rest_plain_tcp": dict(distribution),
        "default_grpc": dict(distribution),
        "tuned_grpc_multiplexed": dict(distribution),
    }
    validate_symmetric_invariant(per_cohort)  # No raise.


def test_validate_symmetric_invariant_raises_on_divergent_counts() -> None:
    """Different counts for the same prompt set → tier-b symmetry
    assertion fires."""
    per_cohort = {
        "rest_https_edge": {"prompt_a": 10, "prompt_b": 5},
        "default_grpc": {"prompt_a": 9, "prompt_b": 6},  # counts differ
    }
    with pytest.raises(SymmetryAssertionFailed) as exc_info:
        validate_symmetric_invariant(per_cohort)
    assert exc_info.value.tier == "b"
    assert exc_info.value.field == "symmetric_prompt_distribution"


def test_validate_symmetric_invariant_raises_on_divergent_keys() -> None:
    """Different prompt set across cohorts → tier-b symmetry assertion
    fires (the hash sets diverge)."""
    per_cohort = {
        "rest_https_edge": {"prompt_a": 10},
        "default_grpc": {"prompt_b": 10},  # different prompt key
    }
    with pytest.raises(SymmetryAssertionFailed):
        validate_symmetric_invariant(per_cohort)


def test_validate_symmetric_invariant_accepts_single_cohort() -> None:
    """A single-cohort input has nothing to compare against; the validator
    returns ``None`` (degenerate-but-not-invalid)."""
    validate_symmetric_invariant({"rest_https_edge": {"prompt_a": 10}})


# --- FR-020 symmetric-mode invariant ----------------------------------------


def test_symmetric_mode_invariant_per_iter_byte_identical() -> None:
    """FR-020: when the sweep dispatches via ``assign_symmetric_prompt``,
    per-cohort token-count + token-hash distributions are byte-identical
    for the same iteration index.

    This simulates the M6.1.3 sweep's symmetric-prompts path: each cohort
    iterates iter_idx 0..N-1, assigns the prompt via
    ``assign_symmetric_prompt``, and accumulates a per-cohort distribution
    (mapping ``prompt_text`` → count). The accumulated distributions MUST
    be identical across cohorts.
    """
    cohorts = ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed")
    per_cohort_distributions: dict[str, dict[str, int]] = {c: {} for c in cohorts}
    n_iter = 50  # matches the per-cohort sample count of a validate sweep
    for cohort in cohorts:
        for iter_idx in range(n_iter):
            prompt = assign_symmetric_prompt(iter_idx, cohort, _CORPUS)
            per_cohort_distributions[cohort][prompt] = (
                per_cohort_distributions[cohort].get(prompt, 0) + 1
            )
    # Invariant: every cohort's distribution is identical.
    validate_symmetric_invariant(per_cohort_distributions)  # No raise.
