"""M6.1.1 strict-superset JSON validation test (T035 / FR-022).

Loads M6.1's published JSON to derive its top-level key set, then
constructs a representative M6.1.1 JSON payload and asserts every M6.1
key is reachable (directly, or via the sentinel-object alias documented
in contracts/output.md § "Strict-superset rules"). M6.1.1's NEW keys
MUST NOT collide with any M6.1 key.

The test fires whether or not M6.1.1 has closed: it constructs the M6.1.1
payload from the in-memory reporter so the assertion holds on the M6.1.1
branch before the JSON is committed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m6_1_1_reporter import (
    _M6_1_KEY_ALIASES,
    assert_strict_superset,
    build_sentinel,
    render_json,
)
from vllm_grpc_bench.m6_1_1_types import (
    M6_1_1Run,
    M6_1_1RunMeta,
    PerturbationAudit,
    Phase1RunRecord,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_M6_1_BASELINE = _REPO_ROOT / "docs" / "benchmarks" / "m6_1-real-prompt-embeds.json"


def _representative_m6_1_1_run() -> M6_1_1Run:
    meta = M6_1_1RunMeta(
        git_sha="deadbeef",
        hostname="modal",
        modal_function_id=None,
        gpu_type="A10G",
        modal_region="eu-west-1",
        model_identifier="Qwen/Qwen3-8B",
        hidden_size=4096,
        cold_start_s=12.0,
        max_model_len=2048,
        gpu_memory_utilization=0.92,
        engine_version="0.20.1",
        m6_1_baseline_engine_version="0.20.1",
        torch_version="2.11.0",
        M6_1_1_BASE_SEED=42,
        seq_len=512,
        phase_1_n=50,
        phase_2_path="phase_2_pending",
        run_started_at="2026-05-17T09:00:00Z",
        run_completed_at="2026-05-17T09:30:00Z",
    )
    return M6_1_1Run(
        schema_version="m6_1_1.v1",
        run_id="r",
        run_started_at="t",
        run_completed_at="t",
        run_meta=meta,
        phase_1_classifications={},
        phase_1_runs=[
            Phase1RunRecord(
                run_id="run-1",
                run_started_at="t",
                run_completed_at="t",
                wall_clock_s=0.0,
                multi_point_timings=[],
                phase_1_classifications={},
                perturbation_audit=PerturbationAudit(per_cohort_per_cell={}, exceeded=False),
                n_per_cohort=50,
            )
        ],
        multi_point_timings=[],
        phase_2_outcome=None,
        phase_2_choice=None,
        chat_stream_baseline_post_symmetrisation=build_sentinel("phase_2_pending"),
        embed_baseline_post_symmetrisation=build_sentinel("phase_2_pending"),
        embed_regression_check=None,
        m6_1_baseline_pointer="docs/benchmarks/m6_1-real-prompt-embeds.json",
        methodology_supersedence="",
    )


# FR-022 strict-superset scope: the M6.1 keys M6.1.1 explicitly claims to
# preserve are the engine_cost data, the verdict-table verdicts, and the
# run-level metadata. M6.1's lineage keys (M3/M4/M5.x rtt_distribution,
# cohorts, modal_metadata, etc.) are M6.1's domain, not M6.1.1's — M6.1.1
# annotates M6.1's JSON additively (FR-023) but doesn't mirror its full
# top-level shape.
_M6_1_KEYS_M6_1_1_PRESERVES: tuple[str, ...] = (
    "schema_version",
    "run_id",
    "run_started_at",
    "run_completed_at",
    "run_meta",
    "engine_cost_baseline",  # aliased to chat_stream_baseline_post_symmetrisation
    "supersedes_m6_under_enable_prompt_embeds",  # aliased to methodology_supersedence
)


def test_m6_1_1_json_is_strict_superset_of_m6_1_engine_cost_schema() -> None:
    """Every M6.1 M6.1.1-relevant top-level key is reachable in M6.1.1's
    JSON, either directly or via the sentinel-object alias (round-2 Q1).

    The "M6.1.1-relevant" subset is the engine_cost data (aliased to
    chat_stream_baseline_post_symmetrisation), the M6.1 verdict table
    (aliased to methodology_supersedence), and the run-level metadata.
    """
    if not _M6_1_BASELINE.is_file():
        pytest.skip(f"M6.1 baseline at {_M6_1_BASELINE} not present")
    m6_1_data = json.loads(_M6_1_BASELINE.read_text(encoding="utf-8"))
    # Verify the M6.1.1-relevant subset is actually present in M6.1's JSON.
    missing_in_m6_1 = [k for k in _M6_1_KEYS_M6_1_1_PRESERVES if k not in m6_1_data]
    assert missing_in_m6_1 == [], (
        f"M6.1 baseline missing keys M6.1.1 expects to find: {missing_in_m6_1}"
    )
    m6_1_1_payload = render_json(_representative_m6_1_1_run())
    assert_strict_superset(m6_1_1_payload, m6_1_keys=list(_M6_1_KEYS_M6_1_1_PRESERVES))


def test_m6_1_1_new_keys_do_not_collide_with_m6_1_keys() -> None:
    """M6.1.1's additive keys are namespaced so M6.1 readers can ignore
    unknown keys without false matches."""
    if not _M6_1_BASELINE.is_file():
        pytest.skip(f"M6.1 baseline at {_M6_1_BASELINE} not present")
    m6_1_data = json.loads(_M6_1_BASELINE.read_text(encoding="utf-8"))
    m6_1_keys = set(m6_1_data.keys())
    m6_1_1_payload = render_json(_representative_m6_1_1_run())
    # M6.1.1's new keys are: phase_1_classifications, phase_1_runs,
    # multi_point_timings, phase_2_outcome, phase_2_choice,
    # chat_stream_baseline_post_symmetrisation, embed_baseline_post_symmetrisation,
    # embed_regression_check, m6_1_baseline_pointer, methodology_supersedence.
    m6_1_1_new_keys = set(m6_1_1_payload.keys()) - m6_1_keys
    # Any key shared with M6.1 must be either schema_version, run_id,
    # run_started_at, run_completed_at, or run_meta (M6.1.1 strict-superset
    # for top-level metadata).
    shared_keys = set(m6_1_1_payload.keys()) & m6_1_keys
    expected_shared = {
        "schema_version",
        "run_id",
        "run_started_at",
        "run_completed_at",
        "run_meta",
    }
    # Subset relationship: every shared key is a known metadata key.
    unexpected_shared = shared_keys - expected_shared
    assert unexpected_shared == set(), (
        f"Unexpected M6.1.1 key collisions with M6.1: {unexpected_shared}. "
        "Namespace these or remove them from M6.1.1's top level."
    )
    # NEW keys exist (i.e., M6.1.1 isn't an empty copy of M6.1).
    assert m6_1_1_new_keys, "M6.1.1 contributes no new top-level keys"


def test_baseline_sentinel_aliases_satisfy_m6_1_engine_cost_baseline() -> None:
    """The sentinel-object alias for ``engine_cost_baseline`` is
    ``chat_stream_baseline_post_symmetrisation`` (round-2 Q1 dispatch)."""
    assert _M6_1_KEY_ALIASES["engine_cost_baseline"] == "chat_stream_baseline_post_symmetrisation"


def test_baseline_sentinel_aliases_satisfy_supersedes_m6() -> None:
    """The sentinel-object alias for ``supersedes_m6_under_enable_prompt_embeds``
    is ``methodology_supersedence`` (FR-023 additive annotation)."""
    assert (
        _M6_1_KEY_ALIASES["supersedes_m6_under_enable_prompt_embeds"] == "methodology_supersedence"
    )
