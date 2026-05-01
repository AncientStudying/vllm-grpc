from __future__ import annotations

from pathlib import Path

import pytest
from vllm_grpc_bench.corpus import RequestSample, load_corpus

_FIXTURE_PATH = Path(__file__).parent.parent / "corpus" / "chat_nonstreaming.json"


def test_load_corpus_valid() -> None:
    samples = load_corpus(_FIXTURE_PATH)
    assert len(samples) == 10
    assert all(isinstance(s, RequestSample) for s in samples)


def test_load_corpus_field_values() -> None:
    samples = load_corpus(_FIXTURE_PATH)
    first = samples[0]
    assert first.id == "sample-001"
    assert first.model == "Qwen/Qwen3-0.6B"
    assert first.max_tokens == 10
    assert first.temperature == 0.0
    assert first.seed == 42
    assert isinstance(first.messages, list)
    assert len(first.messages) >= 1
    assert "role" in first.messages[0]
    assert "content" in first.messages[0]


def test_load_corpus_empty_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty.json"
    empty.write_text("[]")
    with pytest.raises(ValueError, match="empty"):
        load_corpus(empty)


def test_load_corpus_malformed_json_raises(tmp_path: Path) -> None:
    import json

    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        load_corpus(bad)


def test_load_corpus_ids_sequential() -> None:
    samples = load_corpus(_FIXTURE_PATH)
    ids = [s.id for s in samples]
    assert ids == [f"sample-{i:03d}" for i in range(1, 11)]
