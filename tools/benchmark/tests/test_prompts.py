"""New-home coverage for the de-prefixed ``prompts`` module (T023).

Asserts the unified :func:`build_chat_prompt` is deterministic (same seed →
same prompt; different seeds → different prompts), per-RPC-varying, and that
the hoisted ``DEFAULT_CHAT_MAX_TOKENS`` default survived the Phase-4 move.
"""

from __future__ import annotations

from vllm_grpc_bench.prompts import DEFAULT_CHAT_MAX_TOKENS, build_chat_prompt


def test_build_chat_prompt_is_deterministic() -> None:
    """Same seed always yields the identical prompt (byte-stable digest)."""
    assert build_chat_prompt(42) == build_chat_prompt(42)


def test_build_chat_prompt_varies_per_seed() -> None:
    """Distinct seeds produce distinct prompts so engine output varies per RPC."""
    prompts = {build_chat_prompt(seed) for seed in range(50)}
    assert len(prompts) == 50


def test_build_chat_prompt_embeds_seed() -> None:
    """The seed is echoed into the prompt text (per-RPC traceability)."""
    assert "seed=7" in build_chat_prompt(7)
    assert build_chat_prompt(7).endswith("Please respond.")


def test_default_chat_max_tokens() -> None:
    """The hoisted default cap is preserved from the legacy ``m3_sweep`` home."""
    assert DEFAULT_CHAT_MAX_TOKENS == 64
