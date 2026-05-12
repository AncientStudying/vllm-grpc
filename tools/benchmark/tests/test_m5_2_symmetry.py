"""Tests for the M5.2 3-tier symmetry block builder + asserter (T017).

Covers research R-3:
- tier (a) cross-cohort invariants are detected on prompt-corpus mismatch.
- tier (b) intra-protocol pair digests match modulo the operative field.
- c=1 degeneracy skip for the tuned-gRPC pair (single tuned_grpc cohort,
  never asserts).
- tier (c) metadata replicates the c=1 skip flag onto every cohort entry.
"""

from __future__ import annotations

import pytest
from vllm_grpc_bench.m5_2_symmetry import (
    CohortConfigInput,
    SymmetryAssertionFailed,
    assert_symmetry,
    build_symmetry_block,
    canonical_digest,
)

_CORPUS = "a" * 64
_DEPLOY = "vllm-grpc-bench-rest-grpc-mock-r1"
_APP = "vllm-grpc-bench-rest-grpc-mock"
_ENGINE = "b" * 64
_WARMUP = "discard_first_5_measurement_n_5"


def _rest_cfg(cohort: str, base_url: str) -> CohortConfigInput:
    return CohortConfigInput(
        cohort=cohort,  # type: ignore[arg-type]
        prompt_corpus_hash=_CORPUS,
        modal_deploy_handle=_DEPLOY,
        modal_app_handle=_APP,
        modal_region="eu-west-1",
        mock_engine_config_digest=_ENGINE,
        warmup_batch_policy=_WARMUP,
        warmup_batch_size=20,
        client_config_full={
            "base_url": base_url,
            "http2": False,
            "max_keepalive_connections": 4,
            "max_connections": 4,
        },
        rest_url_excepted_field="base_url",
    )


def _tuned_cfg(cohort: str, topology: str) -> CohortConfigInput:
    return CohortConfigInput(
        cohort=cohort,  # type: ignore[arg-type]
        prompt_corpus_hash=_CORPUS,
        modal_deploy_handle=_DEPLOY,
        modal_app_handle=_APP,
        modal_region="eu-west-1",
        mock_engine_config_digest=_ENGINE,
        warmup_batch_policy=_WARMUP,
        warmup_batch_size=20,
        client_config_full={
            "channel_topology": topology,
            "max_message_size": 64 * 1024 * 1024,
            "compression": "gzip",
            "keepalive_time_ms": 10000,
        },
        grpc_topology_excepted_field="channel_topology",
    )


def _default_grpc_cfg() -> CohortConfigInput:
    return CohortConfigInput(
        cohort="default_grpc",
        prompt_corpus_hash=_CORPUS,
        modal_deploy_handle=_DEPLOY,
        modal_app_handle=_APP,
        modal_region="eu-west-1",
        mock_engine_config_digest=_ENGINE,
        warmup_batch_policy=_WARMUP,
        warmup_batch_size=20,
        client_config_full={"channel_topology": "default", "max_message_size": 4 * 1024 * 1024},
    )


def test_canonical_digest_is_byte_stable() -> None:
    payload_a = {"b": 2, "a": 1, "c": [1, 2]}
    payload_b = {"a": 1, "c": [1, 2], "b": 2}
    assert canonical_digest(payload_a) == canonical_digest(payload_b)


def test_build_symmetry_block_matches_for_five_cohorts() -> None:
    cfgs = [
        _rest_cfg("rest_https_edge", "https://edge.example/"),
        _rest_cfg("rest_plain_tcp", "http://tcp.example:8000/"),
        _default_grpc_cfg(),
        _tuned_cfg("tuned_grpc_multiplexed", "multiplexed"),
        _tuned_cfg("tuned_grpc_channels", "channels"),
    ]
    block = build_symmetry_block(cfgs)
    assert block.tier_a.prompt_corpus_hash == _CORPUS
    assert block.tier_b.rest_client_config_digest_url_excepted != ""
    assert block.tier_b.tuned_grpc_channel_config_digest_topology_excepted is not None
    # tier (c) replicates every cohort once.
    assert len(block.tier_c) == 5
    assert {m.cohort for m in block.tier_c} == {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
        "tuned_grpc_multiplexed",
        "tuned_grpc_channels",
    }
    # None of the c≥2 cohorts get tier_b_skipped flag.
    assert all(not m.tier_b_skipped_c1_tuned_grpc_pair for m in block.tier_c)
    # Asserter passes on the same configs.
    assert_symmetry(block, cfgs, concurrency_levels=[1, 4, 8])


def test_assert_symmetry_raises_on_tier_a_prompt_corpus_mismatch() -> None:
    cfgs = [
        _rest_cfg("rest_https_edge", "https://edge.example/"),
        _rest_cfg("rest_plain_tcp", "http://tcp.example:8000/"),
    ]
    block = build_symmetry_block(cfgs)
    bad = list(cfgs)
    bad[1] = CohortConfigInput(
        **{**bad[1].__dict__, "prompt_corpus_hash": "9" * 64},
    )
    with pytest.raises(SymmetryAssertionFailed) as excinfo:
        assert_symmetry(block, bad, concurrency_levels=[4])
    assert excinfo.value.tier == "a"
    assert excinfo.value.field == "prompt_corpus_hash"


def test_assert_symmetry_raises_on_tier_b_rest_client_config_divergence() -> None:
    cfgs = [
        _rest_cfg("rest_https_edge", "https://edge.example/"),
        _rest_cfg("rest_plain_tcp", "http://tcp.example:8000/"),
    ]
    block = build_symmetry_block(cfgs)
    bad = list(cfgs)
    # Mutate one REST cohort's NON-URL client config field. URL is excepted;
    # this divergence MUST fire tier (b).
    diverged = dict(bad[1].client_config_full)
    diverged["max_keepalive_connections"] = 99
    bad[1] = CohortConfigInput(
        **{**bad[1].__dict__, "client_config_full": diverged},
    )
    with pytest.raises(SymmetryAssertionFailed) as excinfo:
        assert_symmetry(block, bad, concurrency_levels=[4])
    assert excinfo.value.tier == "b"
    assert excinfo.value.field == "rest_client_config_digest_url_excepted"


def test_url_only_divergence_does_not_raise_tier_b() -> None:
    """URL is the OPERATIVE variable between the two REST transports — it
    differs by design and MUST NOT trip tier (b)."""
    cfgs = [
        _rest_cfg("rest_https_edge", "https://edge.example/"),
        _rest_cfg("rest_plain_tcp", "http://tcp.example:8000/"),
    ]
    block = build_symmetry_block(cfgs)
    assert_symmetry(block, cfgs, concurrency_levels=[4])  # no raise


def test_c1_only_run_skips_tuned_pair_assertion() -> None:
    """At c=1 the two tuned cohorts collapse to tuned_grpc per FR-006. The
    tier (b) tuned-pair assertion is skipped and tier_b's digest is None.
    """
    tuned_c1 = CohortConfigInput(
        cohort="tuned_grpc",
        prompt_corpus_hash=_CORPUS,
        modal_deploy_handle=_DEPLOY,
        modal_app_handle=_APP,
        modal_region="eu-west-1",
        mock_engine_config_digest=_ENGINE,
        warmup_batch_policy=_WARMUP,
        warmup_batch_size=20,
        client_config_full={"channel_topology": "single"},
    )
    cfgs = [
        _rest_cfg("rest_https_edge", "https://edge.example/"),
        _rest_cfg("rest_plain_tcp", "http://tcp.example:8000/"),
        _default_grpc_cfg(),
        tuned_c1,
    ]
    block = build_symmetry_block(cfgs)
    assert block.tier_b.tuned_grpc_channel_config_digest_topology_excepted is None
    # tier (c) records the skip flag on the tuned_grpc cohort.
    skip_flags = {m.cohort: m.tier_b_skipped_c1_tuned_grpc_pair for m in block.tier_c}
    assert skip_flags["tuned_grpc"] is True
    assert skip_flags["rest_https_edge"] is False
    assert_symmetry(block, cfgs, concurrency_levels=[1])  # no raise


def test_c4_run_with_topology_mismatch_raises_tier_b() -> None:
    """At c=4 the two tuned cohorts MUST share their non-topology digest."""
    cfgs = [
        _rest_cfg("rest_https_edge", "https://edge.example/"),
        _rest_cfg("rest_plain_tcp", "http://tcp.example:8000/"),
        _tuned_cfg("tuned_grpc_multiplexed", "multiplexed"),
        _tuned_cfg("tuned_grpc_channels", "channels"),
    ]
    block = build_symmetry_block(cfgs)
    bad = list(cfgs)
    bad[3] = CohortConfigInput(
        **{
            **bad[3].__dict__,
            "client_config_full": {
                "channel_topology": "channels",
                "max_message_size": 999,
                "compression": "gzip",
                "keepalive_time_ms": 10000,
            },
        }
    )
    with pytest.raises(SymmetryAssertionFailed) as excinfo:
        assert_symmetry(block, bad, concurrency_levels=[4])
    assert excinfo.value.tier == "b"
    assert "tuned_grpc" in excinfo.value.field
