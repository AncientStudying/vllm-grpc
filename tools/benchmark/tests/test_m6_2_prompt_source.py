"""T016 — M6.2 three-regime prompt-source dispatch + corpus SHA gates.

Per ``specs/027-m6-2-token-budget/contracts/prompt-source.md`` round-5:

- null-anchor cells (max_tokens ∈ {10, 50}) → synthetic regime.
- interior-cap cells (max_tokens ∈ {256, 512, 1024, 2048}) → corpus regime.
- sub-probe (ignore_eos_override=True) → corpus + forced cap.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from vllm_grpc_bench.corpus import (
    CompletionEmbedSample,
    CorpusDriftError,
    RequestSample,
)
from vllm_grpc_bench.m6_2_prompt_source import (
    load_chat_corpus,
    load_embed_corpus,
    resolve_block_inputs,
)
from vllm_grpc_bench.symmetric_prompts import assign_symmetric_prompt


def _make_chat_corpus(n: int = 8) -> list[RequestSample]:
    return [
        RequestSample(
            id=f"sharegpt-{i:04d}",
            messages=[{"role": "user", "content": f"chat prompt {i}"}],
            model="Qwen/Qwen3-8B",
            max_tokens=128,
            temperature=0.0,
            seed=42,
            bucket="short",
        )
        for i in range(n)
    ]


def _make_embed_corpus(n: int = 8) -> list[CompletionEmbedSample]:
    return [
        CompletionEmbedSample(
            id=i,
            tensor_bytes=f"embed{i:04d}".encode(),
            max_tokens=0,
            seed=0,
            seq_len=64,
            bucket="short",
        )
        for i in range(n)
    ]


class TestChatRegimes:
    def test_null_anchor_max_tokens_10_uses_synthetic(self) -> None:
        out = resolve_block_inputs(
            cell="chat_stream_c1",
            max_tokens=10,
            iter_idx=0,
            cohort="default_grpc",
            base_seed=42,
            chat_corpus=_make_chat_corpus(),
            embed_corpus=_make_embed_corpus(),
        )
        assert out["prompt_source"] == "synthetic_seed_derived"
        assert out["prompt_corpus_idx"] is None
        assert out["ignore_eos"] is False
        assert "prompt_text" in out

    def test_null_anchor_max_tokens_50_uses_synthetic(self) -> None:
        out = resolve_block_inputs(
            cell="chat_stream_c1",
            max_tokens=50,
            iter_idx=0,
            cohort="default_grpc",
            base_seed=42,
            chat_corpus=_make_chat_corpus(),
            embed_corpus=_make_embed_corpus(),
        )
        assert out["prompt_source"] == "synthetic_seed_derived"

    def test_interior_cap_uses_corpus(self) -> None:
        corpus = _make_chat_corpus()
        out = resolve_block_inputs(
            cell="chat_stream_c4",
            max_tokens=512,
            iter_idx=3,
            cohort="default_grpc",
            base_seed=42,
            chat_corpus=corpus,
            embed_corpus=_make_embed_corpus(),
        )
        assert out["prompt_source"] == "corpus_sharegpt"
        assert out["prompt_corpus_idx"] == 3
        assert out["ignore_eos"] is False
        assert out["prompt_text"] == corpus[3].messages[0]["content"]

    def test_sub_probe_uses_corpus_plus_ignore_eos(self) -> None:
        out = resolve_block_inputs(
            cell="chat_stream_c8",
            max_tokens=2048,
            iter_idx=5,
            cohort="default_grpc",
            base_seed=42,
            chat_corpus=_make_chat_corpus(),
            embed_corpus=_make_embed_corpus(),
            ignore_eos_override=True,
        )
        assert out["prompt_source"] == "corpus_sharegpt"
        assert out["ignore_eos"] is True


class TestEmbedRegimes:
    def test_null_anchor_uses_synthetic_tensor(self) -> None:
        out = resolve_block_inputs(
            cell="embed_c1",
            max_tokens=10,
            iter_idx=0,
            cohort="default_grpc",
            base_seed=42,
            chat_corpus=_make_chat_corpus(),
            embed_corpus=_make_embed_corpus(),
        )
        assert out["prompt_source"] == "synthetic_random_tensor"
        assert out["prompt_corpus_idx"] is None
        assert out["ignore_eos"] is False
        # Synthetic tensor regime is wired at the builder layer, not in the
        # resolver: embed_tensor_bytes is NOT populated for the synthetic case.
        assert "embed_tensor_bytes" not in out

    def test_interior_cap_uses_corpus(self) -> None:
        corpus = _make_embed_corpus()
        out = resolve_block_inputs(
            cell="embed_c4",
            max_tokens=1024,
            iter_idx=2,
            cohort="default_grpc",
            base_seed=42,
            chat_corpus=_make_chat_corpus(),
            embed_corpus=corpus,
        )
        assert out["prompt_source"] == "corpus_sharegpt_embed"
        assert out["prompt_corpus_idx"] == 2
        assert out["embed_tensor_bytes"] == corpus[2].tensor_bytes

    def test_sub_probe_uses_corpus_plus_ignore_eos(self) -> None:
        out = resolve_block_inputs(
            cell="embed_c8",
            max_tokens=2048,
            iter_idx=1,
            cohort="default_grpc",
            base_seed=42,
            chat_corpus=_make_chat_corpus(),
            embed_corpus=_make_embed_corpus(),
            ignore_eos_override=True,
        )
        assert out["prompt_source"] == "corpus_sharegpt_embed"
        assert out["ignore_eos"] is True


class TestCohortInvariance:
    def test_assign_symmetric_prompt_cohort_invariant(self) -> None:
        corpus = _make_chat_corpus()
        cohorts = ["rest_plain_tcp", "rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"]
        for iter_idx in range(8):
            assigned = {c: assign_symmetric_prompt(iter_idx, c, corpus) for c in cohorts}
            assert len({a.id for a in assigned.values()}) == 1, (
                f"Cohort-invariance broken at iter_idx={iter_idx}"
            )

    def test_resolver_chat_corpus_regime_is_cohort_invariant(self) -> None:
        corpus = _make_chat_corpus()
        cohorts = ["rest_plain_tcp", "rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"]
        for iter_idx in range(8):
            prompts = {
                c: resolve_block_inputs(
                    cell="chat_stream_c4",
                    max_tokens=512,
                    iter_idx=iter_idx,
                    cohort=c,
                    base_seed=42,
                    chat_corpus=corpus,
                    embed_corpus=_make_embed_corpus(),
                )["prompt_text"]
                for c in cohorts
            }
            assert len(set(prompts.values())) == 1


class TestCorpusSHA:
    def test_chat_corpus_sha_mismatch_raises(self, tmp_path: Path) -> None:
        bad_corpus = tmp_path / "chat_sharegpt_1000.json"
        bad_corpus.write_text(
            '[{"id": "sharegpt-0000", "messages": [], "model": "x", '
            '"max_tokens": 1, "temperature": 0.0, "seed": 0}]'
        )
        bad_provenance = tmp_path / "chat_sharegpt_1000.provenance.json"
        bad_provenance.write_text(json.dumps({"corpus_sha256": "0" * 64}))
        with pytest.raises(CorpusDriftError):
            load_chat_corpus(corpus_path=bad_corpus, provenance_path=bad_provenance)

    def test_embed_corpus_missing_dir_raises(self, tmp_path: Path) -> None:
        missing_dir = tmp_path / "completions_embeds_qwen3_8b"
        with pytest.raises(FileNotFoundError):
            load_embed_corpus(corpus_dir=missing_dir)

    def test_embed_corpus_missing_manifest_raises(self, tmp_path: Path) -> None:
        existing_dir = tmp_path / "completions_embeds_qwen3_8b"
        existing_dir.mkdir()
        with pytest.raises(FileNotFoundError):
            load_embed_corpus(corpus_dir=existing_dir)


class TestRaisesOnMissingCorpus:
    def test_chat_corpus_required_for_chat_corpus_regime(self) -> None:
        with pytest.raises(ValueError, match="chat_corpus must be provided"):
            resolve_block_inputs(
                cell="chat_stream_c1",
                max_tokens=1024,
                iter_idx=0,
                cohort="default_grpc",
                base_seed=42,
                chat_corpus=None,
                embed_corpus=_make_embed_corpus(),
            )

    def test_embed_corpus_required_for_embed_corpus_regime(self) -> None:
        with pytest.raises(ValueError, match="embed_corpus must be provided"):
            resolve_block_inputs(
                cell="embed_c4",
                max_tokens=512,
                iter_idx=0,
                cohort="default_grpc",
                base_seed=42,
                chat_corpus=_make_chat_corpus(),
                embed_corpus=None,
            )


# silence unused-import warning for shutil used only by future suites
_ = shutil
