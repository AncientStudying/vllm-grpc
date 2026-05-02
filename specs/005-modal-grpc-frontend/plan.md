# Implementation Plan: Phase 3.1 — Modal gRPC Frontend Deployment

**Branch**: `005-modal-grpc-frontend` | **Date**: 2026-05-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/005-modal-grpc-frontend/spec.md`

## Summary

Add three Modal scripts and one ADR that make the gRPC frontend deployable on Modal A10G so real GPU-backed benchmarks become possible. A one-time weight pre-staging script caches `Qwen/Qwen3-0.6B` in a persistent Modal Volume; a lifecycle-managed gRPC frontend smoke test deploys the full proxy→gRPC→vLLM stack inside a Modal container, validates end-to-end correctness, and tears down automatically; a parallel REST comparison target smoke test does the same for vLLM's native OpenAI server. No proto changes, no new workspace packages, and no proxy code changes.

## Technical Context

**Language/Version**: Python 3.12 (workspace-wide)

**Primary Dependencies**:
- `modal>=0.73` — cloud GPU orchestration; added to dev group in root `pyproject.toml`
- `grpcio>=1.65` — already in proxy and frontend; needed in smoke-test local entrypoint for health polling
- `httpx>=0.27` — already in dev group; used by local entrypoint and REST smoke test
- `huggingface_hub` — installed inside Modal container for weight download; not a local dep
- `vllm==0.20.0` — installed inside Modal containers only; not a local dep (see ADR 0001)
- `grpcio-tools>=1.65` — already in dev group; used inside Modal image build to regenerate proto stubs

**Storage**: `modal.Volume` named `vllm-grpc-model-weights`, mounted at `/mnt/weights` inside containers. Persists across invocations; populated once by the download script.

**Testing**: No new pytest tests — the smoke-test scripts are themselves the integration tests for this phase. `ruff` and `mypy --strict` cover all new Python files. Smoke tests are a manual gate (GPU required; cannot run in CI).

**Target Platform**: Modal A10G (NVIDIA, 24 GB VRAM, vLLM 0.20.0 / CUDA) for cloud functions; macOS ARM64 (M2 Pro) for the local entrypoints.

**Project Type**: Three new standalone scripts under `scripts/python/`, one new curl script under `scripts/curl/`, one new ADR. No new workspace packages.

**Performance Goals**: Cold-start (provisioning + server init, weights pre-staged) ≤ 5 minutes; per-request smoke-test latency ≤ 5 seconds; full lifecycle-managed smoke-test sequence ≤ 15 minutes end-to-end (SC-006).

**Constraints**:
- No proto changes (Constitution I)
- No vLLM fork (Constitution II)
- No Phase 4.1 benchmark orchestration features (Constitution III)
- `ruff` clean + `mypy --strict` on all new `.py` files (Constitution IV)
- Cold-start timing documented in ADR ±10 s (Constitution V)
- The smoke test runs the proxy subprocess **inside** the Modal container (not on the developer's machine); see Research R-001 for rationale. `FRONTEND_ADDR` is set to `localhost:50051` intra-container, which validates the env var mechanism without requiring a TCP tunnel.

**Scale/Scope**: Three new scripts (~150–200 lines each), one curl script, one ADR, two new Makefile targets. No workspace package additions, no proto edits.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Proto-First | ✅ PASS | No `.proto` changes; image build regenerates stubs from existing proto sources |
| II. Library Dependency, Not Fork | ✅ PASS | `vllm==0.20.0` installed in Modal containers via `pip_install`; no source patches |
| III. Phase Discipline | ✅ PASS | Deliverables match `docs/PLAN.md §Phase 3.1` exactly; no benchmark orchestration (Phase 4.1), no streaming (Phase 5), no prompt_embeds (Phase 6) |
| IV. CI is the Merge Gate | ⚠️ PARTIAL | `ruff` + `mypy --strict` on new scripts run in CI; smoke tests require GPU and Modal auth — they are a **manual pre-merge gate**, not a CI gate. This is documented in the ADR and Complexity Tracking. |
| V. Honest Measurement | ✅ PASS | Cold-start and request latency reported in smoke-test output and committed to ADR with ±10 s reproducibility; methodology (corpus, hardware, vLLM version) documented in ADR |

**Post-design re-check**: All principles pass. The decision to run the proxy inside the Modal container (R-001) eliminates TCP tunnel complexity and is the most reliable approach given Modal's experimental tunnel API. The manual smoke-test gate is an acceptable trade-off for GPU-dependent code and is consistent with the project's existing `verify_prompt_embeds_modal.py` pattern.

## Project Structure

### Documentation (this feature)

```text
specs/005-modal-grpc-frontend/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output (complete)
├── quickstart.md        # Phase 1 output (complete)
├── contracts/           # Phase 1 output (complete)
│   ├── modal-weight-volume.md
│   └── smoke-test-result.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
scripts/
├── python/
│   ├── modal_download_weights.py    ← NEW: one-time weight pre-staging (FR-009)
│   ├── modal_frontend_smoke.py      ← NEW: lifecycle-managed gRPC frontend smoke test (FR-001, FR-005)
│   └── modal_vllm_rest.py           ← NEW: lifecycle-managed REST comparison target (FR-002)
└── curl/
    └── chat-nonstreaming-modal.sh   ← NEW: manual curl reference script (FR-005 complement)

docs/decisions/
└── 0002-modal-deployment.md         ← NEW: ADR (FR-007)

pyproject.toml                       ← EXTEND: add `modal>=0.73` to [dependency-groups.dev]
Makefile                             ← EXTEND: add download-weights, smoke-grpc-frontend, smoke-rest targets
```

**No new workspace packages.** All three scripts follow the `scripts/python/` convention established by `verify_prompt_embeds_modal.py`. They are standalone Modal apps, not reusable library code.

**No proxy code changes.** `packages/proxy/src/vllm_grpc_proxy/grpc_client.py` already reads `FRONTEND_ADDR` from the environment and passes it to `grpc.aio.insecure_channel()`. No modification needed to satisfy FR-004 / SC-005.

### modal_download_weights.py — Internal Structure

```text
_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=True)
_download_image = modal.Image.debian_slim(python_version="3.12").pip_install("huggingface_hub")
app = modal.App("vllm-grpc-download-weights")

@app.function(volumes={"/mnt/weights": _MODEL_VOLUME}, image=_download_image, timeout=600)
def download():
    # Check if already downloaded (idempotency)
    # huggingface_hub.snapshot_download(repo_id=_MODEL, local_dir="/mnt/weights")
    # _MODEL_VOLUME.commit()

@app.local_entrypoint()
def main():
    download.remote()
```

### modal_frontend_smoke.py — Internal Structure

```text
_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=True)
_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("vllm==0.20.0", "grpcio>=1.65", "grpcio-tools>=1.65",
                 "fastapi>=0.115", "uvicorn[standard]>=0.30", "httpx>=0.27")
    .copy_local_dir("proto", "/build/proto")
    .copy_local_dir("packages/gen", "/build/packages/gen")
    .copy_local_dir("packages/frontend", "/build/packages/frontend")
    .copy_local_dir("packages/proxy", "/build/packages/proxy")
    .run_commands(
        "python -m grpc_tools.protoc -I /build/proto ..."   # regenerate stubs
        "pip install /build/packages/gen",
        "pip install /build/packages/frontend",
        "pip install /build/packages/proxy",
    )
)
app = modal.App("vllm-grpc-frontend-smoke")

@app.function(gpu="A10G", image=_image, volumes={"/mnt/weights": _MODEL_VOLUME}, timeout=600)
def smoke_test() -> dict:
    # 1. Start gRPC frontend subprocess (MODEL_NAME=/mnt/weights)
    # 2. Poll Health.Ping until ready; record cold_start_s
    # 3. Start proxy subprocess (FRONTEND_ADDR=localhost:50051)
    # 4. Poll /healthz until 200
    # 5. POST /v1/chat/completions (seed=42, max_tokens=20)
    # 6. Assert non-empty choices[0].message.content
    # 7. Kill subprocesses; return SmokeTestResult dict

@app.local_entrypoint()
def main():
    result = smoke_test.remote()
    # Print timing + completion_text; exit 0/1
```

### modal_vllm_rest.py — Internal Structure

```text
_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=True)
_image = modal.Image.debian_slim(python_version="3.12").pip_install("vllm==0.20.0", "httpx")
app = modal.App("vllm-grpc-rest-smoke")

@app.function(gpu="A10G", image=_image, volumes={"/mnt/weights": _MODEL_VOLUME}, timeout=600)
def smoke_test() -> dict:
    # 1. Start vLLM OpenAI API server subprocess (--model /mnt/weights, --port 8000)
    # 2. Poll /health until ready; record cold_start_s
    # 3. POST /v1/chat/completions (seed=42, max_tokens=20)
    # 4. Assert non-empty choices[0].message.content
    # 5. Kill subprocess; return SmokeTestResult dict
    # Pattern: mirrors verify_prompt_embeds_modal.py

@app.local_entrypoint()
def main():
    result = smoke_test.remote()
    # Print timing + completion_text; exit 0/1
```

## Complexity Tracking

| Decision | Why Needed | Simpler Alternative Rejected Because |
|----------|------------|--------------------------------------|
| Proxy runs inside Modal container (not local) | `modal.forward()` generator+tunnel is underdocumented and potentially unreliable for gRPC (see R-001). Intra-container test is simpler and exercises the same code paths. | Keeping proxy local would require `modal.forward(unencrypted=True)` in a generator function, which Modal docs do not explicitly support and which may close the tunnel on `yield`. |
| Smoke tests are a manual CI gate | GPU + Modal auth unavailable in GitHub Actions | Could mock Modal calls in unit tests, but mocking the deployment layer would not validate the actual integration; the existing `verify_prompt_embeds_modal.py` sets this precedent. |
| Both packages (frontend + proxy) installed in same Modal image | Smoke test runs proxy subprocess inside container (see above) | Would require two separate Modal functions and inter-function communication if proxy were external; adds complexity without benefit in this phase. |
