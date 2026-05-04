#!/usr/bin/env python
"""Demo: OpenAI REST chat completion via the gRPC proxy using the openai SDK.

Access path: openai SDK → proxy (HTTP/REST) → gRPC frontend → vLLM
The proxy exposes a standard OpenAI-compatible /v1 endpoint, so any
OpenAI client library works without modification.

Usage:
    uv run python demo/openai-sdk.py

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
    response = client.chat.completions.create(
        model="Qwen/Qwen3-0.6B",
        messages=[{"role": "user", "content": "What is 2+2?"}],
        max_tokens=64,
        seed=42,
    )
    print(response.choices[0].message.content)
except openai.APIError as exc:
    print(f"ERROR: {exc}", file=sys.stderr)
    sys.exit(1)
