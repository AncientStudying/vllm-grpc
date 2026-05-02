# Research: Phase 5 — Modal gRPC Frontend Deployment

**Branch**: `005-modal-grpc-frontend` | **Date**: 2026-05-01

---

## R-001: Modal TCP Tunnel for gRPC (modal.forward)

**Decision**: Use `modal.forward(port, unencrypted=True)` as the mechanism to expose the gRPC port from inside a Modal container. The returned `Tunnel` object exposes `tcp_socket: tuple[str, int]` — formatted as `f"{host}:{port}"` it is a valid value for `FRONTEND_ADDR` / `grpc.aio.insecure_channel()`.

**Rationale**: The proxy uses `grpc.aio.insecure_channel(addr)`, which is plain-text HTTP/2 over TCP. The `unencrypted=True` flag skips Modal's TLS wrapper and produces a raw TCP tunnel compatible with the proxy's insecure channel.

**Important constraint — generator functions**: Research indicates that using `modal.forward()` inside a generator `@app.function` that `yield`s is underdocumented and may close the tunnel when the function is suspended. This approach is not used in any known Modal examples. **Avoid the generator+forward pattern.**

**Alternative considered**: Run the proxy subprocess *inside* the Modal container alongside the gRPC frontend. This avoids the need for an external tunnel altogether. The smoke test runs proxy→gRPC→vLLM entirely within the container; `FRONTEND_ADDR` is set to `localhost:50051` (intra-container). This approach is simpler, well-supported, and exercises the full proxy→gRPC code path.

**Chosen approach for smoke test**: Proxy runs inside the Modal container as a `subprocess.Popen`. No external tunnel required. The `FRONTEND_ADDR` env var is validated (set to `localhost:50051` inside the container). FR-004 / SC-005 are satisfied because the proxy's code requires no changes — any `host:port` value works.

**Note on `modal.forward` for Phase 4.1**: Phase 4.1's `bench_modal.py` may need external access for the REST endpoint; this is deferred. For Phase 3.1, intra-container testing is sufficient.

---

## R-002: Modal Volume for Pre-Staged Model Weights

**Decision**: Use `modal.Volume.from_name("vllm-grpc-model-weights", create_if_missing=True)` to persist model weights across invocations. Mount at `/mnt/weights` inside the container.

**Rationale**: Without pre-staged weights, every cold start downloads `Qwen/Qwen3-0.6B` (~1.5 GB) from HuggingFace, adding 3–5 minutes of variable latency. A persistent volume reduces cold start to container provisioning + server init only (~60–120 s), making SC-004's ±10 s reproducibility achievable.

**API details**:
- Create / look up: `modal.Volume.from_name("name", create_if_missing=True)` — idempotent
- Mount in function: `@app.function(volumes={"/mnt/weights": _MODEL_VOLUME})`
- After writing (download step): `_MODEL_VOLUME.commit()` is required to persist changes; without `.commit()`, writes are not durable

**Download script**: A separate one-time `modal_download_weights.py` script uses `huggingface_hub.snapshot_download()` inside a Modal CPU function (no GPU needed for download). The script checks if weights already exist before downloading (idempotency via filesystem check at `/mnt/weights/config.json`).

**Alternatives considered**: Using Modal's built-in HuggingFace cache (`modal.Image` with `.pip_install("huggingface_hub")` + `run_commands` to pre-download) — rejected because image layers are immutable and can't be updated without rebuilding the image. The volume approach is more flexible and doesn't bloat the image.

---

## R-003: Packaging vllm-grpc-frontend and vllm-grpc-proxy into Modal Image

**Decision**: Build the Modal container image with:
1. `pip_install("vllm==0.20.0", "grpcio>=1.65", "fastapi>=0.115", "uvicorn[standard]>=0.30")`
2. `.copy_local_dir("proto", "/build/proto")`
3. `.copy_local_dir("packages/gen", "/build/packages/gen")`
4. `.copy_local_dir("packages/frontend", "/build/packages/frontend")`
5. `.copy_local_dir("packages/proxy", "/build/packages/proxy")`
6. `.run_commands(...)` — run `grpc_tools.protoc` to generate stubs, then `pip install` each package

**Rationale**: The workspace packages (`vllm-grpc-gen`, `vllm-grpc-frontend`, `vllm-grpc-proxy`) are not published to PyPI; they must be installed from source. Modal's `.copy_local_dir()` + `.run_commands("pip install <path>")` is the standard pattern for local packages. Running `protoc` inside the image build ensures the image is reproducible from a fresh clone (no local stub generation required on the developer's machine first).

**Proto stubs are gitignored**: `packages/gen/src/vllm_grpc/v1/*_pb2.py` are gitignored. The image build regenerates them via `grpcio-tools` — not from local disk — so the image is always consistent with the proto source.

**Alternatives considered**: 
- Building wheels locally and `pip_install_local_packages()` — rejected because it requires a local build step and the wheel paths must be specified exactly
- Installing `vllm-grpc-frontend` only (not proxy) — rejected because the smoke test needs the proxy inside the container (see R-001)

---

## R-004: vLLM Local Model Path Support

**Decision**: Pass the volume mount path to `AsyncEngineArgs(model="/mnt/weights")` and `AutoTokenizer.from_pretrained("/mnt/weights")`. vLLM resolves local paths directly from the filesystem, bypassing HuggingFace hub.

**Rationale**: vLLM's `AsyncEngineArgs.model` accepts any path that the `transformers` library can load — HuggingFace model ID, local directory, or local file. A local path that contains `config.json` and weight shards is loaded directly.

**Caveat**: One community report (vLLM issue #39039) notes that vLLM may attempt a HuggingFace metadata fetch even for local paths in some versions. The download script will pre-stage weights in the exact directory format `snapshot_download()` produces (`/mnt/weights` as the root), which matches what `transformers` expects. If the HF fetch is attempted but the local path is already complete, the fetch will fail gracefully and fall back to local loading.

**Frontend env var**: `MODEL_NAME` env var in `packages/frontend/src/vllm_grpc_frontend/main.py` is already used to set the model path. Override with `MODEL_NAME=/mnt/weights` in the Modal function to load from the volume.

---

## R-005: Proxy Subprocess Startup Inside Modal

**Decision**: Start the proxy as a subprocess inside the Modal container using `subprocess.Popen` with the `uvicorn` command. Poll `http://localhost:8000/healthz` to confirm the proxy is up before sending the smoke-test request.

**Rationale**: The proxy is a FastAPI/uvicorn app. Running it as a subprocess inside the container is straightforward, avoids network complexity, and exercises the full proxy→gRPC→vLLM code path. The proxy's `/healthz` endpoint calls `Health.Ping` on the gRPC frontend; a 200 response confirms both proxy startup AND gRPC frontend health.

**Startup sequence**:
1. Start gRPC frontend server (`subprocess.Popen` of `vllm_grpc_frontend.main`)
2. Poll `grpc.aio.insecure_channel("localhost:50051")` → `HealthStub.Ping()` (or poll HTTP `/healthz` once proxy is up)
3. Start proxy subprocess with `FRONTEND_ADDR=localhost:50051`
4. Poll `http://localhost:8000/healthz` until 200
5. Send `POST /v1/chat/completions` with `seed=42`, `max_tokens=20`
6. Assert non-empty `choices[0].message.content`
7. Kill proxy and frontend processes; function returns result dict

**Timing**: Cold-start window = time from function invocation to step 4 complete. Per-request latency = time for step 5. Both are reported in the result dict and documented in the ADR.
