#!/usr/bin/env bash
set -euo pipefail

PROXY_PORT="${PROXY_PORT:-8000}"
curl -s "http://localhost:${PROXY_PORT}/healthz"
echo
