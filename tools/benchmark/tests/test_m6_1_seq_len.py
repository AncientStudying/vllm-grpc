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
    monkeypatch.setattr(m6_1_seq_len, "_tokenizer_cache", {})

    def fake_load(model_identifier: str) -> Any:
        return _StubTokenizer(token_count=8)

    monkeypatch.setattr(m6_1_seq_len, "_load_tokenizer", fake_load)
    assert m6_1_seq_len.pin_seq_len_at_sweep_start("Qwen/Qwen3-8B") == 8


def test_pin_seq_len_rejects_zero_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m6_1_seq_len, "_tokenizer_cache", {})

    def fake_load(model_identifier: str) -> Any:
        return _StubTokenizer(token_count=0)

    monkeypatch.setattr(m6_1_seq_len, "_load_tokenizer", fake_load)
    with pytest.raises(RuntimeError):
        m6_1_seq_len.pin_seq_len_at_sweep_start("Qwen/Qwen3-8B")


def test_pin_seq_len_returns_positive_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m6_1_seq_len, "_tokenizer_cache", {})

    def fake_load(model_identifier: str) -> Any:
        return _StubTokenizer(token_count=5)

    monkeypatch.setattr(m6_1_seq_len, "_load_tokenizer", fake_load)
    result = m6_1_seq_len.pin_seq_len_at_sweep_start()
    assert isinstance(result, int)
    assert result >= 1
