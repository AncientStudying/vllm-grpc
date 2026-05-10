"""US3 / T038 / FR-011 — schema candidates pair with the per-path frozen
baseline (NOT the shared M1_BASELINE, NOT M3's bytes baseline).
"""

from __future__ import annotations

from vllm_grpc_bench.m4_sweep import resolve_schema_baseline


class TestSchemaBaselineSelection:
    def test_chat_stream_pairs_with_chat_frozen(self) -> None:
        frozens = {"chat_stream": "frozen_chat_id", "embed": "frozen_embed_id"}
        shared = {"chat_stream": "shared_chat_id", "embed": "shared_embed_id"}
        baseline_id = resolve_schema_baseline(
            path="chat_stream",
            frozen_baselines=frozens,
            shared_baselines=shared,
        )
        assert baseline_id == "frozen_chat_id"

    def test_embed_pairs_with_embed_frozen(self) -> None:
        frozens = {"chat_stream": "frozen_chat_id", "embed": "frozen_embed_id"}
        shared = {"chat_stream": "shared_chat_id", "embed": "shared_embed_id"}
        baseline_id = resolve_schema_baseline(
            path="embed",
            frozen_baselines=frozens,
            shared_baselines=shared,
        )
        assert baseline_id == "frozen_embed_id"

    def test_missing_frozen_falls_back_to_shared_with_note(self) -> None:
        # Per FR-011, if the frozen baseline is unavailable for some reason,
        # the function returns the shared baseline (allowing the harness
        # to keep producing verdicts) — the note is recorded in
        # ``SchemaCandidateResult.notes`` upstream.
        baseline_id = resolve_schema_baseline(
            path="chat_stream",
            frozen_baselines={},
            shared_baselines={"chat_stream": "shared_chat_id"},
        )
        assert baseline_id == "shared_chat_id"
