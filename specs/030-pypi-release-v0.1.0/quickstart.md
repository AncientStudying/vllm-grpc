# Quickstart: First PyPI Release (v0.1.0)

How to take the four packages from source to **proven publish-ready** locally — with **no upload**.
This mirrors the acceptance gates the operator (and CI) will run.

## Prerequisites

- `uv` ≥ 0.9 (verified 0.9.18), Python 3.12.
- `make proto` runs cleanly (generates the gitignored stubs for dev).
- Working tree on `chore/pypi-release-v0.1.0`.

## 1. Build all four (→ 8 artifacts)

```bash
for p in gen proxy frontend client; do uv build --package vllm-grpc-$p; done
ls packages/*/dist/         # expect a .whl and a .tar.gz per package
```
The `gen` build hook runs `protoc`, so its wheel/sdist carry the generated `vllm_grpc/v1/*_pb2*.py`
even though they are gitignored.

## 2. Validate metadata

```bash
uvx twine check packages/*/dist/*       # zero errors, zero warnings
```

## 3. Prove a clean install + standalone gen import

```bash
uv venv /tmp/v && uv pip install --python /tmp/v/bin/python --no-project \
  --find-links packages/gen/dist packages/gen/dist/*.whl
/tmp/v/bin/python -c "import vllm_grpc.v1.chat_pb2_grpc; print('gen ok')"
```

## 4. Prove the client is lean

```bash
uv venv /tmp/c && uv pip install --python /tmp/c/bin/python --no-project \
  --find-links packages/gen/dist packages/client/dist/*.whl
/tmp/c/bin/python -m pip freeze | grep -Ei 'fastapi|uvicorn' \
  && echo 'FAIL: web deps leaked' || echo 'client lean ok'
```

## 5. Smoke the console scripts (no GPU/model)

```bash
# proxy serves its REST surface; frontend starts its gRPC server against the fake engine fixture.
/tmp/.../bin/vllm-grpc-proxy      # curl /healthz
/tmp/.../bin/vllm-grpc-frontend   # with fake-engine env
```

## 6. Confirm the deprecation is gone

```bash
grep -rn 'AsyncLLMEngine\|AsyncEngineArgs' packages/frontend/src \
  && echo 'FAIL: V0 path remains' || echo 'V1 migration ok'
```

## 7. Statically validate the release workflow (it does NOT run)

```bash
uvx actionlint .github/workflows/release.yml
grep -n 'id-token: write' .github/workflows/release.yml        # OIDC present
grep -nE 'password:|PYPI_API_TOKEN' .github/workflows/release.yml \
  && echo 'FAIL: token auth' || echo 'OIDC-only ok'
```

## 8. Docs present

```bash
test -f CHANGELOG.md && test -f docs/RELEASES.md
for p in gen proxy frontend client; do test -f packages/$p/README.md; done
grep -q 'pip install vllm-grpc-client' README.md     # install matrix
```

## Done = publish-ready, zero uploads

When steps 1–8 pass, the Definition of Done is met: four packages build, install cleanly, pass
metadata validation, the console scripts serve, the frontend emits no deprecation warning, the
release workflow is statically valid, and the docs are in place — **without any external upload**.
The TestPyPI upload (operator's first manual trigger of the authored pipeline) and the real PyPI
publish (later, gated) happen after this feature merges.

## What this feature does NOT do
- Upload to TestPyPI or PyPI, or claim any distribution name (FR-020/SC-008).
- Touch `tools/benchmark/`, `proto/`, or package runtime logic beyond packaging + the V0→V1
  remediation (FR-019).
- Add vLLM to the frontend's install requirements (FR-005).
