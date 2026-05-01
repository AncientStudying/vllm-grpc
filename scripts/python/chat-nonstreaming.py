#!/usr/bin/env python
"""Send a non-streaming chat completion to the proxy using the openai SDK.

Usage:
    uv run python scripts/python/chat-nonstreaming.py

Override the proxy base URL:
    PROXY_BASE_URL=http://localhost:8001/v1 uv run python scripts/python/chat-nonstreaming.py
"""

from __future__ import annotations

import os
import sys

import openai

base_url = os.environ.get("PROXY_BASE_URL", "http://localhost:8000/v1")
client = openai.OpenAI(base_url=base_url, api_key="none")

try:
    response = client.chat.completions.create(
        model="Qwen/Qwen3-0.6B",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2 + 2?"},
        ],
        max_tokens=64,
        seed=42,
    )
except openai.APIError as exc:
    print(f"API error: {exc}", file=sys.stderr)
    sys.exit(1)

print(response.choices[0].message.content)
print(response.usage)
