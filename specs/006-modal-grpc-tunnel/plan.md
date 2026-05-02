# Implementation Plan: Phase 3.2 — Local Proxy → Modal gRPC Tunnel

**Branch**: `006-modal-grpc-tunnel` | **Date**: 2026-05-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/006-modal-grpc-tunnel/spec.md`

## Summary

Add one Modal serve script that starts the gRPC frontend on A10G, opens a raw TCP tunnel via `modal.forward(unencrypted=True)`, publishes the tunnel address to a `modal.Dict`, and blocks until Ctrl+C or timeout. A new `modal-serve-frontend` Makefile target invokes it. The developer exports `FRONTEND_ADDR` from the printed address, runs `make run-proxy` locally, and sends requests through the full local-proxy → network → cloud-gRPC → vLLM path. This is the first time real protobuf/gRPC bytes traverse an actual network in this project.

## Technical Context

**Language/Version**: Python 3.12 (workspace-wide)

**Primary Dependencies**:
- `modal>=0.73` — already in `[dependency-groups.dev]`; used for `modal.forward()`, `modal.Dict`, `@app.function.spawn()`
- `grpcio>=1.65` — already in frontend; used inside container for `Health.Ping` polling
- `grpcio-tools>=1.65` — already in dev group; used inside Modal image build to regenerate proto stubs
- `vllm==0.20.0` — installed inside Modal container only; not a local dep (see ADR 0001)

**Storage**: `modal.Dict` named `"vllm-grpc-serve"` (ephemeral key-value shared state); `modal.Volume` named `"vllm-grpc-model-weights"` (pre-staged weights, created by Phase 3.1)

**Testing**: No new pytest tests. The manual smoke test (Steps 1–4 of quickstart.md) is the integration test for this phase. `ruff` + `mypy --strict` cover the new script. `modal.Dict` API accesses use `# type: ignore` where required by mypy's dynamic typing; each suppression is commented in the code.

**Target Platform**: Modal A10G (NVIDIA, 24 GB VRAM, vLLM 0.20.0 / CUDA) for the container; macOS ARM64 (M2 Pro) for the local entrypoint and proxy.

**Project Type**: One new standalone script under `scripts/python/`, one new Makefile target. No new workspace packages.

**Performance Goals**: Cold-start (provisioning + server init, weights pre-staged) ≤ 5 minutes (SC-001). Tunnel address printed within 10 s of gRPC server healthy. Full sequence (serve start → tunnel address → proxy start → request received) ≤ 15 minutes (SC-005).

**Constraints**:
- No proto changes (Constitution I)
- No vLLM fork (Constitution II)
- No Phase 4.1 benchmark orchestration or multi-request harness integration (Constitution III)
- `ruff` clean + `mypy --strict` on all new `.py` files (Constitution IV); `# type: ignore` suppressions for `modal.Dict` dynamic API are explicitly justified in comments
- Observed tunnel behavior (HTTP/2 stability, any drops) documented in ADR (Constitution V)
- No proxy or frontend package code changes — `FRONTEND_ADDR` is the only configuration point (spec FR-003/FR-004)

**Scale/Scope**: One new script (~150 lines), one Makefile target, one ADR update. No workspace package additions, no proto edits.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Proto-First | ✅ PASS | No `.proto` changes; image build regenerates stubs from existing proto sources (same as Phase 3.1) |
| II. Library Dependency, Not Fork | ✅ PASS | `vllm==0.20.0` installed in Modal container via `pip_install`; no source patches |
| III. Phase Discipline | ✅ PASS | Deliverables match `docs/PLAN.md §Phase 3.2` exactly; no benchmark orchestration (Phase 4.1), no streaming (Phase 5) |
| IV. CI is the Merge Gate | ⚠️ PARTIAL | `ruff` + `mypy --strict` on new script run in CI; the serve function requires GPU + Modal auth and is a **manual pre-merge gate**. Consistent with Phase 3.1 precedent. |
| V. Honest Measurement | ✅ PASS | Tunnel behavior (stability, any HTTP/2 issues) documented in ADR 0002 Phase 3.2 section. If tunnel is unstable, that is reported honestly. |

**Post-design re-check**: All principles pass. The `modal.Dict`-based teardown signal mechanism avoids the generator+yield concern from Phase 3.1 R-001. The manual validation gate is acceptable for GPU-dependent code.

## Project Structure

### Documentation (this feature)

```text
specs/006-modal-grpc-tunnel/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output (complete)
├── quickstart.md        # Phase 1 output (complete)
├── contracts/           # Phase 1 output (complete)
│   ├── tunnel-state.md
│   └── serve-result.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
scripts/
└── python/
    └── modal_frontend_serve.py    ← NEW: long-lived serve script (FR-001, FR-002, FR-005, FR-007)

docs/decisions/
└── 0002-modal-deployment.md       ← EXTEND: add Phase 3.2 section (FR-008)

Makefile                           ← EXTEND: add modal-serve-frontend target; update .PHONY
```

**No new workspace packages.** Follows the `scripts/python/` convention from Phase 3.1.

**No proxy or frontend package changes.** The proxy already reads `FRONTEND_ADDR` from the environment; `make run-proxy FRONTEND_ADDR=<tunnel_addr>` is sufficient.

### modal_frontend_serve.py — Internal Structure

```text
# Constants
_VLLM_VERSION = "0.20.0"
_MODEL_PATH = "/mnt/weights"
_GRPC_PORT = 50051
_GRPC_STARTUP_POLLS = 120          # 5 s × 120 = 600 s max
_GRPC_POLL_INTERVAL_S = 5
_FUNCTION_TIMEOUT_S = 3600         # 1-hour max; cost guard
_STOP_CHECK_INTERVAL_S = 5
_ADDR_POLL_TIMEOUT_S = 600         # local entrypoint gives up after 600 s
_DICT_NAME = "vllm-grpc-serve"
_DICT_KEY_ADDR = "frontend_addr"
_DICT_KEY_COLD_START = "cold_start_s"
_DICT_KEY_STOP = "stop_signal"

app = modal.App("vllm-grpc-frontend-serve")
_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=False)

# Image: same as modal_frontend_smoke.py EXCEPT:
#   - proxy package NOT included (proxy runs locally)
#   - uvicorn NOT included (proxy runs locally)
#   - httpx NOT included
_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("vllm==0.20.0", "grpcio>=1.65", "grpcio-tools>=1.65")
    .add_local_dir("proto",             "/build/proto",             copy=True)
    .add_local_dir("packages/gen",      "/build/packages/gen",      copy=True)
    .add_local_dir("packages/frontend", "/build/packages/frontend", copy=True)
    .run_commands(
        "python -m grpc_tools.protoc -I /build/proto ...",   # regenerate stubs
        "pip install /build/packages/gen",
        "pip install /build/packages/frontend",
    )
)

@app.function(gpu="A10G", image=_image, volumes={_MODEL_PATH: _MODEL_VOLUME}, timeout=_FUNCTION_TIMEOUT_S)
def serve_frontend() -> dict[str, object]:
    # 1. Start gRPC frontend subprocess (MODEL_NAME=_MODEL_PATH, FRONTEND_HOST=0.0.0.0)
    # 2. Poll Health.Ping every 5 s, up to 600 s
    #    → on timeout: return ServeResult(ok=False, error=...)
    # 3. Record cold_start_s
    # 4. Open modal.forward(_GRPC_PORT, unencrypted=True)
    # 5. Write frontend_addr and cold_start_s to modal.Dict
    # 6. Sleep loop (_STOP_CHECK_INTERVAL_S), checking:
    #    - modal.Dict[_DICT_KEY_STOP] → break if True
    #    - time budget (exit before function timeout)
    # 7. Exit modal.forward() context (tunnel closes)
    # 8. Kill frontend subprocess
    # 9. Delete dict keys; return ServeResult(ok=True, cold_start_s=...)

@app.local_entrypoint()
def main() -> None:
    # 1. d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)
    # 2. Delete stale keys (frontend_addr, cold_start_s, stop_signal)
    # 3. serve_frontend.spawn()
    # 4. Poll d[_DICT_KEY_ADDR] every 2 s, up to _ADDR_POLL_TIMEOUT_S
    #    → timeout: sys.exit(1)
    # 5. Print cold_start_s, "export FRONTEND_ADDR=<addr>", instructions
    # 6. Block (time.sleep loop)
    # 7. KeyboardInterrupt → d[_DICT_KEY_STOP] = True → print teardown message → exit 0
```

## Complexity Tracking

No constitution violations. No additional workspace packages. The `modal.Dict` stop-signal mechanism is the only non-obvious pattern, and it is documented in research.md R-002 and R-003.
