#!/usr/bin/env bash
# Phase 2 environment setup: Modal A10G + vLLM 0.20.0
#
# Chosen environment per ADR 0001: cloud GPU (Modal A10G, vllm 0.20.0).
# This script validates prerequisites and runs the prompt_embeds verification
# on a Modal-provisioned A10G. No local vLLM installation is required — Modal
# builds and runs the container in the cloud.
#
# Prerequisites:
#   1. uv installed (https://docs.astral.sh/uv/getting-started/installation/)
#   2. Modal account + token: uv run --with modal modal token new
#
# Usage:
#   bash scripts/setup/phase2-env.sh

set -euo pipefail

log() { echo "[phase2-env] $*"; }
fail() { echo "[phase2-env] ERROR: $*" >&2; exit 1; }

log "=== Phase 2 environment setup: Modal A10G ==="

# --- Prerequisite: uv ---
log "Checking uv..."
if ! command -v uv &>/dev/null; then
    fail "uv not found. Install from https://docs.astral.sh/uv/getting-started/installation/"
fi
log "uv found: $(uv --version)"

# --- Prerequisite: Modal token ---
log "Checking Modal authentication..."
MODAL_TOKEN_FILE="${MODAL_TOKEN_PATH:-${HOME}/.modal.toml}"
if [[ ! -f "${MODAL_TOKEN_FILE}" ]]; then
    fail "Modal token not found at ${MODAL_TOKEN_FILE}. Run: uv run --with modal modal token new"
fi
log "Modal token found: ${MODAL_TOKEN_FILE}"

# --- Locate verification script ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VERIFY_SCRIPT="${REPO_ROOT}/scripts/python/verify_prompt_embeds_modal.py"

if [[ ! -f "${VERIFY_SCRIPT}" ]]; then
    fail "Verification script not found: ${VERIFY_SCRIPT}"
fi
log "Verification script: ${VERIFY_SCRIPT}"

# --- Run verification on Modal A10G ---
log "Launching Modal A10G experiment (vllm 0.20.0, Qwen3-0.6B)..."
log "Expected runtime: 7–12 minutes (image build + model download + inference)"
log ""

cd "${REPO_ROOT}"
uv run --with modal modal run scripts/python/verify_prompt_embeds_modal.py

log ""
log "=== Setup complete ==="
