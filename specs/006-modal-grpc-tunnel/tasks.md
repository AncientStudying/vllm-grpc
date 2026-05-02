# Tasks: Phase 3.2 — Local Proxy → Modal gRPC Tunnel

**Input**: Design documents from `specs/006-modal-grpc-tunnel/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Not requested. The manual validation tasks (T005, T006) are the integration tests for this phase; `ruff` + `mypy --strict` are the CI gates.

**Organization**: Tasks grouped by user story for independent implementation and validation.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no unresolved dependencies)
- **[Story]**: Which user story this task belongs to (US1–US3)
- Exact file paths in all descriptions

---

## Phase 1: User Story 1 — Serve Script Implementation (Priority: P1) 🎯 MVP

**Goal**: `make modal-serve-frontend` starts the gRPC frontend on Modal A10G, opens a TCP tunnel, and prints `export FRONTEND_ADDR=<host>:<port>` to the developer's terminal.

**Independent Test**: Run `make modal-serve-frontend`; observe a `FRONTEND_ADDR=...` line printed within the cold-start window (≤ 5 min). Export it, start `make run-proxy`, confirm `GET /healthz` returns 200.

- [X] T001 [US1] Define Modal app, constants, and image in `scripts/python/modal_frontend_serve.py`: constants `_VLLM_VERSION="0.20.0"`, `_MODEL_PATH="/mnt/weights"`, `_GRPC_PORT=50051`, `_GRPC_STARTUP_POLLS=120`, `_GRPC_POLL_INTERVAL_S=5`, `_FUNCTION_TIMEOUT_S=3600`, `_STOP_CHECK_INTERVAL_S=5`, `_ADDR_POLL_TIMEOUT_S=600`, `_DICT_NAME="vllm-grpc-serve"`, `_DICT_KEY_ADDR="frontend_addr"`, `_DICT_KEY_COLD_START="cold_start_s"`, `_DICT_KEY_STOP="stop_signal"`; `app = modal.App("vllm-grpc-frontend-serve")`; `_MODEL_VOLUME = modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=False)`; image chain: `debian_slim(python_version="3.12")` → `pip_install("vllm==0.20.0", "grpcio>=1.65", "grpcio-tools>=1.65")` → `add_local_dir("proto", "/build/proto", copy=True)` → `add_local_dir("packages/gen", "/build/packages/gen", copy=True)` → `add_local_dir("packages/frontend", "/build/packages/frontend", copy=True)` → `run_commands(...)` (run `grpcio_tools.protoc` for `health.proto` and `chat.proto`, then `pip install /build/packages/gen /build/packages/frontend`). Note: proxy package NOT included — proxy runs locally.
- [X] T002 [US1] Implement `serve_frontend()` in `scripts/python/modal_frontend_serve.py`: decorated with `@app.function(gpu="A10G", image=_image, volumes={_MODEL_PATH: _MODEL_VOLUME}, timeout=_FUNCTION_TIMEOUT_S)`; starts `subprocess.Popen(["python", "-m", "vllm_grpc_frontend.main"], env={**os.environ, "MODEL_NAME": _MODEL_PATH, "FRONTEND_HOST": "0.0.0.0", "FRONTEND_PORT": str(_GRPC_PORT)}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)`; polls `grpc.insecure_channel(f"localhost:{_GRPC_PORT}")` → `HealthStub.Ping()` every `_GRPC_POLL_INTERVAL_S` up to `_GRPC_STARTUP_POLLS`; on process exit during poll, reads stderr and returns `{"ok": False, "error": ..., "cold_start_s": ..., }` (matching `ServeResult` schema in `specs/006-modal-grpc-tunnel/contracts/serve-result.md`); on timeout returns failure result; records `cold_start_s = time.monotonic() - t_start`; opens `modal.forward(_GRPC_PORT, unencrypted=True)` context manager; writes `d[_DICT_KEY_ADDR] = f"{host}:{port}"` and `d[_DICT_KEY_COLD_START] = cold_start_s` to `modal.Dict.from_name(_DICT_NAME, create_if_missing=True)`; enters sleep loop checking `d.get(_DICT_KEY_STOP)` every `_STOP_CHECK_INTERVAL_S` and time budget; on exit: closes `modal.forward()` context (tunnel closes automatically), kills frontend subprocess, deletes all three dict keys; returns `ServeResult(ok=True, cold_start_s=cold_start_s, error=None)`
- [X] T003 [US1] Implement `@app.local_entrypoint()` `main()` in `scripts/python/modal_frontend_serve.py`: `d = modal.Dict.from_name(_DICT_NAME, create_if_missing=True)`; delete stale keys (`_DICT_KEY_ADDR`, `_DICT_KEY_COLD_START`, `_DICT_KEY_STOP`) via try/except KeyError; print `"[INFO] Deploying gRPC frontend to Modal A10G..."`; call `serve_frontend.spawn()`; poll `d.get(_DICT_KEY_ADDR)` every 2 s up to `_ADDR_POLL_TIMEOUT_S`; on timeout print error to stderr and `sys.exit(1)`; on address received: print `f"[INFO] cold_start_s = {cold_start:.1f}"`, print `f"[OK]   export FRONTEND_ADDR={addr}"`, print `"[INFO] Set FRONTEND_ADDR and run: make run-proxy"`, print `"[INFO] Press Ctrl+C to tear down."`; block with `while True: time.sleep(1)`; on `KeyboardInterrupt`: print `"\n[INFO] Sending teardown signal..."`, set `d[_DICT_KEY_STOP] = True`, print `"[INFO] Container will stop within 30s. Exiting."`, exit 0
- [X] T004 [P] [US1] Add `modal-serve-frontend` Makefile target in `Makefile`: `uv run --with modal modal run scripts/python/modal_frontend_serve.py`; add `modal-serve-frontend` to the `.PHONY` list on line 9

**Checkpoint**: US1 implementation complete — script and Makefile target exist, `ruff` and `mypy --strict` run clean (T008 may be done before or after T005).

---

## Phase 2: User Story 1 — Manual Validation (Priority: P1)

**Goal**: Confirm `make modal-serve-frontend` produces a valid `FRONTEND_ADDR` within the cold-start window and that the proxy health-check confirms tunnel connectivity.

**Independent Test**: `FRONTEND_ADDR=<addr> make run-proxy` starts the proxy; `curl localhost:8000/healthz` returns 200.

- [ ] T005 [US1] Run `make modal-serve-frontend` manually on a clean terminal; wait for `[OK]   export FRONTEND_ADDR=...` line; export the address; open a second terminal and run `FRONTEND_ADDR=<addr> make run-proxy`; confirm `GET http://localhost:8000/healthz` returns `{"status":"ok"}` (proxy reached cloud gRPC frontend via tunnel); note `cold_start_s` for use in T007 (ADR)

**Checkpoint**: US1 complete — gRPC frontend on Modal A10G is reachable from the developer's local proxy via `modal.forward` TCP tunnel.

---

## Phase 3: User Story 2 — Request Over the Real Network Path (Priority: P1)

**Goal**: A real protobuf/gRPC request travels from the local proxy over the `modal.forward` tunnel to vLLM on A10G and returns a valid chat completion.

**Independent Test**: With proxy running and `FRONTEND_ADDR` pointing at the tunnel, `bash scripts/curl/chat-nonstreaming-modal.sh` returns valid JSON with non-empty `choices[0].message.content`.

- [ ] T006 [US2] With the tunnel and proxy still running from T005: run `bash scripts/curl/chat-nonstreaming-modal.sh` and confirm non-empty `content` in the response; run it a second time and confirm same `completion_text` (SC-002 determinism); note any connection errors or latency anomalies for use in T007; press Ctrl+C in the `make modal-serve-frontend` terminal and confirm teardown message prints

**Checkpoint**: US2 complete — first real protobuf/gRPC bytes traversed the network. SC-001 through SC-005 validated end-to-end.

---

## Phase 4: User Story 3 — Reproducibility + Type Safety (Priority: P2)

**Goal**: ADR documents the validated topology; new Python file passes `ruff` and `mypy --strict`.

**Independent Test**: Following `docs/decisions/0002-modal-deployment.md` Phase 3.2 section on a machine with only Modal auth and pre-staged weights produces a working tunnel.

- [ ] T007 [US3] Update `docs/decisions/0002-modal-deployment.md` with a new "## Phase 3.2: Local Proxy → Modal gRPC Tunnel" section covering: topology diagram (local proxy → modal.forward tunnel → gRPC frontend → vLLM), `modal.Dict` address-communication pattern and key schema, `spawn()` + stop-signal teardown mechanism, observed `cold_start_s` from T005, HTTP/2 tunnel stability observations from T006 (whether PING frames passed, any connection drops), runaway-cost guard (1-hour function timeout), and prerequisites (Modal token + `make download-weights` from Phase 3.1)
- [X] T008 [P] [US3] Run `uv run ruff check scripts/python/modal_frontend_serve.py && uv run ruff format --check scripts/python/modal_frontend_serve.py && uv run mypy --strict scripts/python/modal_frontend_serve.py`; fix all errors; note any `# type: ignore` suppressions added for `modal.Dict` dynamic API and confirm each has a justifying comment

**Checkpoint**: US3 complete — ADR updated with real tunnel observations; new script is ruff-clean and mypy --strict clean.

---

## Phase 5: Polish

**Purpose**: End-to-end validation that the quickstart matches actual behavior.

- [ ] T009 Run `specs/006-modal-grpc-tunnel/quickstart.md` Steps 1–4 in order on a clean terminal session; confirm each step's expected output matches actual output; fix any discrepancies between the quickstart and real behavior

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (US1 implementation)**: No dependencies — start immediately
- **Phase 2 (US1 validation)**: Depends on Phase 1 complete (T001–T004 done)
- **Phase 3 (US2 validation)**: Depends on Phase 2 complete (T005 done — tunnel must be running)
- **Phase 4 (US3 — ADR + type)**: T007 depends on T005 + T006 (needs real timing and tunnel observations); T008 [P] depends only on Phase 1 (can be run as soon as script is written)
- **Phase 5 (Polish)**: Depends on all phases complete

### User Story Dependencies

- **US1 (P1)**: No dependencies. Blocks US2.
- **US2 (P1)**: Requires US1 complete (tunnel must be reachable before sending a request).
- **US3 (P2)**: T008 (type safety) requires Phase 1 (script must exist). T007 (ADR) requires T005 + T006 (real observed values).

### Within Phase 1 (US1 Implementation)

- T001 before T002 (image must be defined before implementing the function body)
- T001 before T003 (modal.Dict constants must be defined before entrypoint uses them)
- T004 [P] can be done alongside T001–T003 (different file)

---

## Parallel Execution Examples

```bash
# Phase 1: T004 in parallel with T001-T003
Task: "Add modal-serve-frontend Makefile target"    # T004 [P] — Makefile only
Task: "Define app constants and image in modal_frontend_serve.py"  # T001

# Phase 4: T008 in parallel once script is written
Task: "ruff + mypy --strict on modal_frontend_serve.py"  # T008 [P]
Task: "Update ADR 0002 with Phase 3.2 section"           # T007 — needs T005+T006 data
```

---

## Implementation Strategy

### MVP (User Stories 1 + 2)

1. Complete Phase 1: US1 implementation (T001–T004)
2. Complete Phase 2: US1 manual validation (T005)
3. Complete Phase 3: US2 manual validation (T006)
4. **STOP and VALIDATE**: Full local-proxy → Modal-gRPC path confirmed

### Incremental Delivery

1. Phase 1 + Phase 2 → Tunnel address reachable from local proxy (US1 gate)
2. Phase 3 → Real request over the wire confirmed (US2 gate — first real wire-efficiency test possible)
3. Phase 4 + Phase 5 → ADR + type safety + quickstart polish (US3)

---

## Notes

- T005 and T006 are **manual execution tasks** — they require running Modal commands on the developer's machine with a live internet connection and cannot be automated in CI.
- `cold_start_s` from T005 and tunnel stability observations from T006 are real observed values that must be entered into T007 (ADR). Do not write the ADR until both live runs have completed.
- If `modal.forward()` fails to pass gRPC HTTP/2 frames (observed as connection drops or `UNAVAILABLE` errors on the proxy side), document this in T007 per FR-006 and open a follow-on task to investigate alternatives (gRPC keepalive options, TLS tunnel, or `modal serve` mode).
- No pytest tests are added in this phase; T005 and T006 are the integration tests.
- `mypy --strict` on `modal_frontend_serve.py` will require `# type: ignore` for `modal.Dict` dynamic-typing accesses; each suppression must have a comment explaining why the type is safe at that point.
