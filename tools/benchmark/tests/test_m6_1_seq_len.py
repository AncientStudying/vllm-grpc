"""Tests for ``m6_1_seq_len`` — seq_len pinning helper (FR-028)."""

from __future__ import annotations

from typing import Any

import pytest
from vllm_grpc_bench import m6_1_seq_len


class _StubTokenizer:
    """Stub that returns a fixed-length token list regardless of input."""

    def __init__(self, token_count: int) -> None:
        self._token_count = token_count

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        del text, add_special_tokens
        return list(range(self._token_count))


def test_pin_seq_len_returns_token_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """Slow path: tokenizer is consulted when (model, sample) isn't precomputed.
    Use a synthetic model identifier that bypasses the precomputed lookup."""
    monkeypatch.setattr(m6_1_seq_len, "_tokenizer_cache", {})

    def fake_load(model_identifier: str) -> Any:
        return _StubTokenizer(token_count=8)

    monkeypatch.setattr(m6_1_seq_len, "_load_tokenizer", fake_load)
    assert m6_1_seq_len.pin_seq_len_at_sweep_start("stub-model-not-precomputed") == 8


def test_pin_seq_len_rejects_zero_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m6_1_seq_len, "_tokenizer_cache", {})

    def fake_load(model_identifier: str) -> Any:
        return _StubTokenizer(token_count=0)

    monkeypatch.setattr(m6_1_seq_len, "_load_tokenizer", fake_load)
    with pytest.raises(RuntimeError):
        m6_1_seq_len.pin_seq_len_at_sweep_start("stub-model-not-precomputed")


def test_pin_seq_len_returns_positive_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m6_1_seq_len, "_tokenizer_cache", {})

    def fake_load(model_identifier: str) -> Any:
        return _StubTokenizer(token_count=5)

    monkeypatch.setattr(m6_1_seq_len, "_load_tokenizer", fake_load)
    # Use the slow path so the stub takes effect.
    result = m6_1_seq_len.pin_seq_len_at_sweep_start("stub-model-not-precomputed")
    assert isinstance(result, int)
    assert result >= 1


def test_pin_seq_len_fast_path_skips_tokenizer_for_precomputed_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fast path: precomputed (model, sample) pair returns without ever
    calling ``_load_tokenizer`` (so ``transformers`` doesn't need to be
    importable). Critical for CI runs that skip the ``investigation``
    dependency group."""
    monkeypatch.setattr(m6_1_seq_len, "_tokenizer_cache", {})

    def fake_load_should_not_be_called(model_identifier: str) -> Any:
        raise AssertionError(
            f"_load_tokenizer was called for {model_identifier!r}; "
            "fast path should have short-circuited"
        )

    monkeypatch.setattr(m6_1_seq_len, "_load_tokenizer", fake_load_should_not_be_called)
    assert m6_1_seq_len.pin_seq_len_at_sweep_start("Qwen/Qwen3-8B") == 19
    # Default arg also hits the fast path.
    assert m6_1_seq_len.pin_seq_len_at_sweep_start() == 19


def test_pin_seq_len_precomputed_table_has_canonical_default_pair() -> None:
    """Schema check: the canonical default ``(Qwen/Qwen3-8B, _M6_TEXT_DIGEST_SAMPLE)``
    is precomputed. Guards against accidental table edits that would push
    the default sweep config back onto the slow tokenizer path."""
    assert (
        "Qwen/Qwen3-8B",
        m6_1_seq_len._M6_TEXT_DIGEST_SAMPLE,
    ) in m6_1_seq_len._PRECOMPUTED_SEQ_LEN
