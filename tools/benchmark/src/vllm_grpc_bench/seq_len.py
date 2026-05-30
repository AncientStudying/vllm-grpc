"""M6.1 ``seq_len`` pinning helper.

Per spec FR-028 and research R-3: the prompt-embeds tensor shape is
``[seq_len, hidden_size=4096]`` where ``seq_len`` is fixed across all RPCs,
cells, and cohorts. The pin is computed once at sweep start by tokenising
M6's canonical text-digest format ``"embeds:" + "0"*16`` against the loaded
model's tokenizer (Qwen3-8B) and recording the resulting integer in
``M6_1RunMeta.seq_len``.

Holding seq_len constant across M6 and M6.1 keeps the "Engine path
differential" a clean read of the engine code-path cost.
"""

from __future__ import annotations

from typing import Any

# M6's per-RPC text-digest format was "embeds:" + 16 hex chars (8-byte
# blake2b digest); see ``packages/frontend/src/vllm_grpc_frontend/completions.py``
# ``_prompt_embeds_to_text_digest``. The digest *content* varies per RPC but
# the token count of the fixed-length form is constant; we use a literal of
# the same shape so the pin is deterministic.
_M6_TEXT_DIGEST_SAMPLE: str = "embeds:" + "0" * 16

# Precomputed pins for (model_identifier, sample) → seq_len.
# Populated once via the live HuggingFace tokenizer and recorded here so
# the fast path doesn't need a ``transformers`` import. Lets CI (which
# installs only the default dep groups, not ``investigation``) and any
# other sandboxed runtime exercise sweep code paths that hit
# :func:`pin_seq_len_at_sweep_start`.
#
# To add a new (model, sample) entry, run the tokenizer once with the
# investigation group installed:
#
#     uv run python -c "from transformers import AutoTokenizer; \
#         t = AutoTokenizer.from_pretrained('<model>'); \
#         print(len(t.encode('<sample>', add_special_tokens=False)))"
#
# and append the result here. Determinism is the contract: the same
# tokenizer + add_special_tokens=False always yields the same count.
_PRECOMPUTED_SEQ_LEN: dict[tuple[str, str], int] = {
    # Qwen/Qwen3-8B encodes "embeds:" + "0"*16 as 19 tokens
    # (verified 2026-05-17 against HuggingFace ``Qwen/Qwen3-8B``).
    ("Qwen/Qwen3-8B", _M6_TEXT_DIGEST_SAMPLE): 19,
}

_tokenizer_cache: dict[str, Any] = {}


def _load_tokenizer(model_identifier: str) -> Any:
    cached = _tokenizer_cache.get(model_identifier)
    if cached is not None:
        return cached
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_identifier)
    _tokenizer_cache[model_identifier] = tok
    return tok


def pin_seq_len_at_sweep_start(model_identifier: str = "Qwen/Qwen3-8B") -> int:
    """Return the pinned prompt-embeds ``seq_len`` for the given model.

    Fast path: look up the (model, canonical sample) pair in
    :data:`_PRECOMPUTED_SEQ_LEN`. Avoids a ``transformers`` import in
    environments where the tokenizer isn't installed (CI without the
    ``investigation`` dependency group; sandboxed test runners).

    Slow path: tokenize the canonical sample against the live model
    tokenizer with ``add_special_tokens=False`` and return the token
    count. Required when a caller passes a model that isn't in the
    precomputed table. The tokenizer is cached so repeated calls within
    a process don't re-fetch from HuggingFace.
    """
    cached = _PRECOMPUTED_SEQ_LEN.get((model_identifier, _M6_TEXT_DIGEST_SAMPLE))
    if cached is not None:
        return cached

    tok = _load_tokenizer(model_identifier)
    tokens = tok.encode(_M6_TEXT_DIGEST_SAMPLE, add_special_tokens=False)
    seq_len = len(tokens)
    if seq_len < 1:
        raise RuntimeError(
            f"pin_seq_len_at_sweep_start: tokenizer returned 0 tokens for "
            f"model {model_identifier!r}; cannot proceed (FR-028)"
        )
    return seq_len


__all__ = ["pin_seq_len_at_sweep_start"]
