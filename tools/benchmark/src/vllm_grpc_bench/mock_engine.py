"""CPU-only mock vLLM engine for the M3 channel-tuning sweep.

Drop-in replacement for the ``engine: Any`` parameter the project's existing
``ChatServicer`` and ``CompletionsServicer`` consume. The mock produces
realistically-shaped wire payloads (``hidden_size``-wide float32 embeddings,
plausible per-token text fragments) without invoking real vLLM execution.

Determinism is required: for fixed config + prompt, every call yields
byte-identical outputs. Variance in the harness must come from the
channel/transport, not the mock.

Type-shape parity: instead of importing ``vllm.RequestOutput`` /
``vllm.EmbeddingRequestOutput`` (which would force a vllm install on macOS
where the typing module ships separately as ``vllm-metal``), we publish
duck-typed dataclasses with the same attribute surface the existing servicers
consume. The contract in ``contracts/mock-engine-interface.md`` allows this:
the servicers themselves take ``engine: Any``.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import numpy as np

# Plausible token-like fragments — varied lengths so per-chunk wire byte counts
# resemble a real BPE tokenizer's output distribution.
_TOKEN_FRAGMENTS: tuple[str, ...] = (
    " the",
    " a",
    " of",
    " and",
    " to",
    " in",
    " that",
    " is",
    " for",
    " on",
    " with",
    " as",
    " was",
    " at",
    " by",
    " from",
    "ing",
    "tion",
    "ed",
    "es",
    "Hello",
    "world",
    "model",
    "gRPC",
    "channel",
    "stream",
    "token",
    "embed",
    "M3",
    "bench",
)


@dataclass(frozen=True)
class MockEngineConfig:
    hidden_size: int
    seed: int = 0
    tokens_per_second: float = 20.0
    max_tokens_per_stream: int = 64

    def __post_init__(self) -> None:
        if self.hidden_size <= 0:
            raise ValueError("MockEngineConfig.hidden_size must be > 0")
        if self.tokens_per_second <= 0:
            raise ValueError("MockEngineConfig.tokens_per_second must be > 0")
        if self.max_tokens_per_stream < 1:
            raise ValueError("MockEngineConfig.max_tokens_per_stream must be >= 1")
        if self.seed < 0:
            raise ValueError("MockEngineConfig.seed must be >= 0")


@dataclass
class _MockCompletion:
    text: str
    finish_reason: str
    token_ids: list[int]


@dataclass
class MockRequestOutput:
    """Quacks like vllm.RequestOutput for the surface our servicers consume."""

    prompt_token_ids: list[int]
    outputs: list[_MockCompletion]


@dataclass
class _MockEmbedding:
    embedding: list[float]


@dataclass
class MockEmbeddingRequestOutput:
    """Quacks like vllm.EmbeddingRequestOutput."""

    prompt_token_ids: list[int]
    outputs: list[_MockEmbedding]


def _prompt_hash(prompt: str, seed: int) -> int:
    """Deterministic 64-bit hash combining prompt + seed."""
    h = hashlib.blake2b(prompt.encode("utf-8"), digest_size=8)
    h.update(seed.to_bytes(8, "little", signed=False))
    return int.from_bytes(h.digest(), "little", signed=False)


def _derive_token_count(prompt: str, requested_max: int, cap: int) -> int:
    """If the prompt encodes a long-stream hint (`min_tokens=N`), honour it up to cap.

    Plain prompts without that hint return ``min(requested_max, cap)``.
    """
    needle = "min_tokens="
    idx = prompt.find(needle)
    if idx < 0:
        return min(requested_max, cap)
    rest = prompt[idx + len(needle) :]
    digits: list[str] = []
    for ch in rest:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return min(requested_max, cap)
    requested = int("".join(digits))
    return min(max(requested_max, requested), cap)


class MockEngine:
    def __init__(self, config: MockEngineConfig) -> None:
        self._config = config
        self._inflight: set[str] = set()

    @property
    def config(self) -> MockEngineConfig:
        return self._config

    async def generate(
        self,
        prompt: Any,
        sampling_params: Any,
        *,
        request_id: str,
    ) -> AsyncIterator[MockRequestOutput]:
        # Real engine accepts string or {"prompt_embeds": ...}; we hash repr(dict)
        # for determinism on the embed-input path.
        prompt_str = repr(prompt) if isinstance(prompt, dict) else str(prompt)

        if not prompt_str:
            raise ValueError("MockEngine: empty prompt")
        if request_id in self._inflight:
            raise RuntimeError(f"duplicate request_id: {request_id}")
        self._inflight.add(request_id)
        try:
            requested_max = int(getattr(sampling_params, "max_tokens", 0) or 0)
            if requested_max <= 0:
                requested_max = self._config.max_tokens_per_stream
            n_tokens = _derive_token_count(
                prompt_str, requested_max, self._config.max_tokens_per_stream * 64
            )

            seed = _prompt_hash(prompt_str, self._config.seed)
            rng = np.random.default_rng(seed)
            fragment_indices = rng.integers(0, len(_TOKEN_FRAGMENTS), size=n_tokens).tolist()
            token_ids: list[int] = []
            running_text_parts: list[str] = []
            interval = 1.0 / self._config.tokens_per_second
            prompt_token_ids = [int(seed >> (i * 4) & 0xFFFF) for i in range(8)]

            for i, frag_idx in enumerate(fragment_indices):
                if i > 0:
                    await asyncio.sleep(interval)
                token_ids.append(int(frag_idx))
                running_text_parts.append(_TOKEN_FRAGMENTS[frag_idx])
                running_text = "".join(running_text_parts)
                finish_reason = ""
                if i == n_tokens - 1:
                    finish_reason = (
                        "length" if n_tokens >= self._config.max_tokens_per_stream else "stop"
                    )
                yield MockRequestOutput(
                    prompt_token_ids=list(prompt_token_ids),
                    outputs=[
                        _MockCompletion(
                            text=running_text,
                            finish_reason=finish_reason,
                            token_ids=list(token_ids),
                        )
                    ],
                )
        finally:
            self._inflight.discard(request_id)

    async def encode(
        self,
        prompt: str,
        *,
        request_id: str,
    ) -> AsyncIterator[MockEmbeddingRequestOutput]:
        if not prompt:
            raise ValueError("MockEngine: empty prompt")
        if request_id in self._inflight:
            raise RuntimeError(f"duplicate request_id: {request_id}")
        self._inflight.add(request_id)
        try:
            seed = _prompt_hash(prompt, self._config.seed)
            rng = np.random.default_rng(seed)
            embedding = rng.standard_normal(self._config.hidden_size, dtype=np.float32)
            prompt_token_ids = [int(seed >> (i * 4) & 0xFFFF) for i in range(8)]
            yield MockEmbeddingRequestOutput(
                prompt_token_ids=list(prompt_token_ids),
                outputs=[_MockEmbedding(embedding=embedding.tolist())],
            )
        finally:
            self._inflight.discard(request_id)
