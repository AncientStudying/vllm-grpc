#!/usr/bin/env bash
# Demo: OpenAI REST chat completion via the gRPC proxy
#
# Access path: curl → proxy (HTTP/REST) → gRPC frontend → vLLM
# The proxy translates the OpenAI JSON body into a gRPC ChatRequest.
#
# Requires: proxy on $PROXY_BASE_URL (default http://localhost:8000)
#           make run-proxy  (which requires make run-frontend first)

PROXY_URL="${PROXY_BASE_URL:-http://localhost:8000}/v1/chat/completions"

curl -sf "$PROXY_URL" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3-0.6B",
    "messages": [{"role": "user", "content": "What is 2+2?"}],
    "max_tokens": 64,
    "seed": 42
  }' || { echo "ERROR: proxy not reachable at $PROXY_URL"; exit 1; }
