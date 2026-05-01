#!/usr/bin/env bash
# Send a non-streaming chat completion to the proxy via curl.
#
# Usage:
#   bash scripts/curl/chat-nonstreaming.sh
#
# Override the proxy port:
#   PROXY_PORT=8001 bash scripts/curl/chat-nonstreaming.sh

set -euo pipefail

PROXY_PORT="${PROXY_PORT:-8000}"

curl -s -X POST "http://localhost:${PROXY_PORT}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-0.6B",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user",   "content": "What is 2 + 2?"}
    ],
    "max_tokens": 64,
    "seed": 42
  }' | python -m json.tool
