#!/usr/bin/env python3
"""Verify prompt_embeds support via vLLM's native OpenAI completions endpoint.

Usage:
    uv run --with vllm --with httpx scripts/python/verify_prompt_embeds.py \\
        --base-url http://localhost:9000 \\
        --model Qwen/Qwen3-0.6B \\
        --seq-len 8 \\
        --max-tokens 50

Exit codes:
    0  Server accepted prompt_embeds and returned a completion.
    1  Server unreachable, returned an error, or response was malformed.
"""

from __future__ import annotations

import argparse
import base64
import io
import sys
import time

import httpx
import torch

HIDDEN_SIZE: int = 1024  # Qwen3-0.6B hidden dimension


def build_prompt_embeds(seq_len: int) -> str:
    """Return a base64-encoded torch.save() of a float32 zeros tensor [seq_len, HIDDEN_SIZE]."""
    tensor = torch.zeros(seq_len, HIDDEN_SIZE, dtype=torch.float32)
    buf = io.BytesIO()
    torch.save(tensor, buf)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def run_verification(
    base_url: str,
    model: str,
    seq_len: int,
    max_tokens: int,
) -> int:
    """Send a prompt_embeds completion request. Returns 0 on success, 1 on failure."""
    print(f"[INFO] target: {base_url}")
    print(f"[INFO] model={model}  seq_len={seq_len}  max_tokens={max_tokens}")

    payload: dict[str, object] = {
        "model": model,
        "prompt_embeds": build_prompt_embeds(seq_len),
        "max_tokens": max_tokens,
    }

    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(f"{base_url}/v1/completions", json=payload)
    except httpx.ConnectError as exc:
        print(f"[FAIL] Cannot connect to server: {exc}")
        return 1
    except httpx.TimeoutException as exc:
        print(f"[FAIL] Request timed out: {exc}")
        return 1

    elapsed = time.monotonic() - t0

    if response.status_code != 200:
        print(f"[FAIL] HTTP {response.status_code}")
        print(f"       {response.text[:500]}")
        return 1

    data: dict[str, object] = response.json()
    choices = data.get("choices")
    if not choices:
        print(f"[FAIL] No choices in response: {data}")
        return 1

    usage = data.get("usage") or {}
    tokens_generated = usage.get("completion_tokens", "?") if isinstance(usage, dict) else "?"
    print(f"[OK] Server responded in {elapsed:.2f}s")
    print(f"[OK] Tokens generated: {tokens_generated}")
    print("[OK] prompt_embeds accepted — environment is viable")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify prompt_embeds support via vLLM's native OpenAI server."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="vLLM server base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--model",
        default="Qwen/Qwen3-0.6B",
        help="Model name as served by vLLM (default: Qwen/Qwen3-0.6B)",
    )
    parser.add_argument(
        "--seq-len",
        type=int,
        default=8,
        help="Sequence length for the prompt_embeds tensor (default: 8)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=50,
        help="Number of tokens to generate (default: 50)",
    )
    args = parser.parse_args()
    sys.exit(
        run_verification(
            base_url=args.base_url,
            model=args.model,
            seq_len=args.seq_len,
            max_tokens=args.max_tokens,
        )
    )


if __name__ == "__main__":
    main()
