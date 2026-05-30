"""Prompt construction + three-regime prompt-source resolution (v0.0.1 home).

Two concerns live here, consolidated into the single prompt home (T015pre):

1. **Builder.** ``build_chat_prompt`` is the unified seed+digest chat-prompt
   form (deterministic, per-RPC-varying); the divergent M5.2 ``iteration``/
   ``cell_id`` builder was dropped when ``rest_cohort`` was repointed (FR-003).
   During the transition this re-exports from the legacy modules that still
   define the symbols; the definitions move here when those modules are deleted
   (Phase 4).

2. **Prompt-source resolver** (formerly ``m6_2_prompt_source``; round-5
   FR-034 / FR-035). The harness defaults are synthetic seed-derived prompts
   (chat) and random tensors (embed), which silently break the
   ``max_tokens=2048`` row + the FR-017a wall-clock-ratio inference. The matrix
   splits into three regimes:

   - Null-anchor cells (``max_tokens ∈ {10, 50}``) — keep the M6.1.x synthetic
     prompts to preserve byte-comparability with the published anchors.
   - Interior-cap cells (``max_tokens ∈ {256, 512, 1024, 2048}``) — switch to
     ShareGPT chat corpus (or the Qwen3-8B prompt-embedding corpus for embed),
     giving production-realistic prompt distributions.
   - KV-pressure sub-probe (``c=8 × {1024, 2048}``) — corpus + ``ignore_eos=True``
     forced cap, the only measurement driving FR-017a's wall-clock-ratio rule.

   See ``contracts/prompt-source.md`` for the full regime table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict

from vllm_grpc_bench.corpus import (
    DEFAULT_CHAT_CORPUS_PATH,
    DEFAULT_EMBED_CORPUS_QWEN3_8B_DIR,
    CompletionEmbedSample,
    CorpusDriftError,
    RequestSample,
    load_completions_embeds_qwen3_8b,
    load_corpus,
    verify_corpus_sha,
)
from vllm_grpc_bench.m3_sweep import DEFAULT_CHAT_MAX_TOKENS
from vllm_grpc_bench.m6_rpc_driver import _build_chat_prompt as build_chat_prompt
from vllm_grpc_bench.sweep_types import (
    M6_2_INTERIOR_CAP_MAX_TOKENS,
    M6_2_NULL_ANCHOR_MAX_TOKENS,
    M6_2_SUB_PROBE_MAX_TOKENS,
    M6_2PromptSource,
)
from vllm_grpc_bench.symmetric_prompts import assign_symmetric_prompt

__all__ = [
    "DEFAULT_CHAT_MAX_TOKENS",
    "CorpusDriftError",
    "ResolvedBlockInputs",
    "build_chat_prompt",
    "load_chat_corpus",
    "load_chat_corpus_provenance",
    "load_embed_corpus",
    "load_embed_corpus_manifest",
    "resolve_block_inputs",
]


DEFAULT_CHAT_PROVENANCE_PATH = (
    DEFAULT_CHAT_CORPUS_PATH.parent / "chat_sharegpt_1000.provenance.json"
)


class ResolvedBlockInputs(TypedDict, total=False):
    """Per-block input parameters returned by :func:`resolve_block_inputs`.

    Exactly one of ``prompt_text`` (chat regimes) or ``embed_tensor_bytes``
    (embed regimes) is set per call.
    """

    prompt_text: str
    embed_tensor_bytes: bytes
    prompt_source: M6_2PromptSource
    prompt_corpus_idx: int | None
    ignore_eos: bool
    max_tokens: int


def load_chat_corpus_provenance(
    provenance_path: Path | None = None,
) -> dict[str, Any]:
    """Return the parsed `chat_sharegpt_1000.provenance.json` contents."""
    p = provenance_path if provenance_path is not None else DEFAULT_CHAT_PROVENANCE_PATH
    if not p.exists():
        raise FileNotFoundError(
            f"Chat corpus provenance file not found: {p}. "
            "The provenance file is checked in alongside the corpus."
        )
    parsed: dict[str, Any] = json.loads(p.read_text())
    return parsed


def load_chat_corpus(
    corpus_path: Path | None = None,
    provenance_path: Path | None = None,
) -> list[RequestSample]:
    """Load the ShareGPT chat corpus and verify its SHA against the provenance.

    SC-018 fail-fast: raises :class:`CorpusDriftError` if the on-disk SHA does
    not match the provenance file's recorded ``corpus_sha256``.
    """
    path = corpus_path if corpus_path is not None else DEFAULT_CHAT_CORPUS_PATH
    if not path.exists():
        raise FileNotFoundError(f"Chat corpus file not found: {path}.")
    provenance = load_chat_corpus_provenance(provenance_path)
    expected_sha = provenance["corpus_sha256"]
    try:
        verify_corpus_sha(path, expected_sha)
    except CorpusDriftError as exc:
        raise CorpusDriftError(f"chat: {exc}") from exc
    return load_corpus(path)


def load_embed_corpus_manifest(
    corpus_dir: Path | None = None,
) -> dict[str, Any]:
    """Return the parsed `completions_embeds_qwen3_8b/manifest.json` contents."""
    d = corpus_dir if corpus_dir is not None else DEFAULT_EMBED_CORPUS_QWEN3_8B_DIR
    manifest_path = d / "manifest.json"
    if not d.exists():
        raise FileNotFoundError(
            f"Embed corpus directory not found: {d}. "
            "Run scripts/python/gen_embed_corpus_qwen3_8b.py first (FR-035)."
        )
    if not manifest_path.exists():
        raise FileNotFoundError(f"Embed corpus manifest not found: {manifest_path}.")
    parsed: dict[str, Any] = json.loads(manifest_path.read_text())
    return parsed


def load_embed_corpus(
    corpus_dir: Path | None = None,
) -> list[CompletionEmbedSample]:
    """Load the Qwen3-8B prompt-embedding corpus and verify its SHA.

    SC-018 fail-fast: raises :class:`CorpusDriftError` on manifest / per-file
    SHA mismatch. Raises :class:`FileNotFoundError` if the corpus directory is
    missing (FR-035 Phase 1 prerequisite enforcement).
    """
    return load_completions_embeds_qwen3_8b(corpus_dir)


def _cell_type_of(cell_id: str) -> str:
    """Map a canonical cell-id (e.g. ``"chat_stream_c4"``, ``"embed_c1"``) to
    the cell-type prefix (``"chat_stream"`` or ``"embed"``)."""
    if cell_id.startswith("chat_stream"):
        return "chat_stream"
    if cell_id.startswith("embed"):
        return "embed"
    raise ValueError(f"Unrecognized cell_id: {cell_id!r}")


def _regime_of(max_tokens: int) -> str:
    """Map ``max_tokens`` to one of the three M6.2 regimes."""
    if max_tokens in M6_2_NULL_ANCHOR_MAX_TOKENS:
        return "null_anchor"
    if max_tokens in M6_2_INTERIOR_CAP_MAX_TOKENS:
        return "interior_cap"
    if max_tokens in M6_2_SUB_PROBE_MAX_TOKENS:
        # Sub-probe regime is dispatched explicitly via ignore_eos_override=True
        # by the sub-probe orchestrator; the main-sweep at the same caps uses
        # the interior-cap (corpus, natural-EOS) regime.
        return "interior_cap"
    raise ValueError(f"max_tokens {max_tokens} not in any M6.2 regime")


def resolve_block_inputs(
    cell: str,
    max_tokens: int,
    iter_idx: int,
    cohort: str,
    base_seed: int,
    chat_corpus: list[RequestSample] | None = None,
    embed_corpus: list[CompletionEmbedSample] | None = None,
    *,
    ignore_eos_override: bool | None = None,
) -> ResolvedBlockInputs:
    """Resolve per-block input parameters per the three-regime table.

    See ``specs/027-m6-2-token-budget/contracts/prompt-source.md`` for the
    full table. ``ignore_eos_override=True`` switches the resolver into the
    sub-probe regime (corpus + forced cap); ``None`` (or False) yields the
    main-sweep regime (synthetic for null-anchor caps; corpus + natural-EOS
    for interior caps).
    """
    cell_type = _cell_type_of(cell)
    regime = _regime_of(max_tokens)
    ignore_eos = bool(ignore_eos_override)

    # Null-anchor cells: synthetic regimes for both chat and embed.
    if regime == "null_anchor" and not ignore_eos:
        if cell_type == "chat_stream":
            seed = base_seed + iter_idx
            return ResolvedBlockInputs(
                prompt_text=build_chat_prompt(seed),
                prompt_source="synthetic_seed_derived",
                prompt_corpus_idx=None,
                ignore_eos=False,
                max_tokens=max_tokens,
            )
        # embed null-anchor: synthetic random tensor (resolved at builder
        # call-time via _build_embed_grpc_request's default path; this
        # resolver records the source label only).
        return ResolvedBlockInputs(
            prompt_source="synthetic_random_tensor",
            prompt_corpus_idx=None,
            ignore_eos=False,
            max_tokens=max_tokens,
        )

    # Interior-cap + sub-probe regimes: corpus-sourced inputs.
    if cell_type == "chat_stream":
        if chat_corpus is None:
            raise ValueError(
                "chat_corpus must be provided for corpus-regime chat blocks "
                "(interior-cap or sub-probe)."
            )
        chat_sample = assign_symmetric_prompt(iter_idx, cohort, chat_corpus)
        # First user message's content. ShareGPT entries are filtered to
        # first-human-turn-only per the provenance schema.
        user_msg = next(m for m in chat_sample.messages if m["role"] == "user")
        return ResolvedBlockInputs(
            prompt_text=user_msg["content"],
            prompt_source="corpus_sharegpt",
            prompt_corpus_idx=iter_idx,
            ignore_eos=ignore_eos,
            max_tokens=max_tokens,
        )

    # embed corpus regime.
    if embed_corpus is None:
        raise ValueError(
            "embed_corpus must be provided for corpus-regime embed blocks "
            "(interior-cap or sub-probe)."
        )
    embed_sample = assign_symmetric_prompt(iter_idx, cohort, embed_corpus)
    return ResolvedBlockInputs(
        embed_tensor_bytes=embed_sample.tensor_bytes,
        prompt_source="corpus_sharegpt_embed",
        prompt_corpus_idx=iter_idx,
        ignore_eos=ignore_eos,
        max_tokens=max_tokens,
    )
