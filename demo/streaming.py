#!/usr/bin/env python
"""Demo: streaming chat completion via the gRPC proxy (SSE).

Access path: openai SDK (stream=True) → proxy (HTTP/SSE) → gRPC frontend → vLLM
The proxy streams vLLM tokens back to the client as Server-Sent Events.
Tokens are printed as they arrive so you can see the incremental output.

Usage:
    uv run python demo/streaming.py

Requires: proxy on $PROXY_BASE_URL (default http://localhost:8000)
          make run-proxy  (which requires make run-frontend first)
"""

import os
import sys

import openai

client = openai.OpenAI(
    base_url=os.environ.get("PROXY_BASE_URL", "http://localhost:8000/v1"),
    api_key="none",  # proxy does not require authentication
)

try:
    stream = client.chat.completions.create(
        model="Qwen/Qwen3-0.6B",
        messages=[{"role": "user", "content": "Count to five."}],
        max_tokens=64,
        seed=42,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            print(delta, end="", flush=True)
    print()  # newline after streaming completes
except openai.APIError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
