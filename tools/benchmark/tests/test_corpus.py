from __future__ import annotations

import json
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


class TestLoadCompletionsCorpus:
    def test_text_loads_list(self, tmp_path: Path) -> None:
        corpus_dir = tmp_path
        (corpus_dir / "completions_text.json").write_text(
            json.dumps(
                [
                    {
                        "id": 0,
                        "prompt": "hello",
                        "model": "m",
                        "max_tokens": 10,
                        "seed": 42,
                        "bucket": "short",
                    }
                ]
            )
        )
        from vllm_grpc_bench.corpus import CompletionTextSample, load_completions_corpus

        result = load_completions_corpus("text", corpus_dir=corpus_dir)
        assert len(result) == 1
        assert isinstance(result[0], CompletionTextSample)
        assert result[0].prompt == "hello"

    def test_text_missing_file_raises(self, tmp_path: Path) -> None:
        from vllm_grpc_bench.corpus import load_completions_corpus

        with pytest.raises(FileNotFoundError, match="completions_text"):
            load_completions_corpus("text", corpus_dir=tmp_path)

    def test_embeds_missing_manifest_raises(self, tmp_path: Path) -> None:
        from vllm_grpc_bench.corpus import load_completions_corpus

        with pytest.raises(FileNotFoundError, match="manifest"):
            load_completions_corpus("embeds", corpus_dir=tmp_path)
