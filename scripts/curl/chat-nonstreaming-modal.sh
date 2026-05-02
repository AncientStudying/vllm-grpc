#!/usr/bin/env bash
# Send a non-streaming chat completion through a local proxy → Modal gRPC frontend.
#
# Usage:
#   PROXY_PORT=8000 bash scripts/curl/chat-nonstreaming-modal.sh
#
# Prerequisites:
#   1. A locally-running vllm-grpc-proxy pointed at a Modal gRPC tunnel:
#        FRONTEND_ADDR=<modal-tunnel-host>:<port> make run-proxy
#   2. An active Modal gRPC tunnel (see docs/decisions/0002-modal-deployment.md
#      for instructions on obtaining a tunnel address via modal.forward()).
#
# For the fully automated lifecycle-managed path (deploy + test + teardown in one
# command), use `make smoke-grpc-frontend` instead.

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
    "max_tokens": 20,
    "seed": 42
  }' | python -m json.tool
