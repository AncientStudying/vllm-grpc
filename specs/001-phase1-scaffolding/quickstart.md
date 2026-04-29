# Quickstart: Phase 1 — Scaffolding

**Goal**: Clone → bootstrap → running ping demo in under five minutes.

---

## Prerequisites

- macOS (M2) or Linux with Python 3.12 available
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `make` installed (macOS: `xcode-select --install`; Linux: pre-installed)

---

## 1. Clone and Bootstrap

```bash
git clone <repo-url> vllm-grpc
cd vllm-grpc

# Install all workspace dependencies and generate protobuf stubs
make bootstrap
```

`make bootstrap` runs:
1. `uv sync --frozen` — installs all workspace packages and their dependencies
2. `make proto` — generates Python stubs from `proto/` into `packages/gen/src/`

---

## 2. Start the Frontend (gRPC Server)

Open a terminal tab:

```bash
make run-frontend
# → Frontend gRPC server listening on 0.0.0.0:50051
```

---

## 3. Start the Proxy (REST Server)

Open another terminal tab:

```bash
make run-proxy
# → Proxy HTTP server listening on 0.0.0.0:8000
```

---

## 4. Verify the End-to-End Ping

```bash
curl -s http://localhost:8000/healthz
# → {"status":"ok"}
```

Or use the provided script:

```bash
bash scripts/curl/healthz.sh
```

---

## 5. Run Checks

```bash
make check          # lint + typecheck + tests
make lint           # ruff check + format check only
make typecheck      # mypy --strict only
make test           # pytest only
make proto          # regenerate stubs (idempotent)
```

---

## Environment Variables

| Variable | Default | Override example |
|----------|---------|-----------------|
| `PROXY_PORT` | `8000` | `PROXY_PORT=9000 make run-proxy` |
| `FRONTEND_PORT` | `50051` | `FRONTEND_PORT=50052 make run-frontend` |
| `FRONTEND_ADDR` | `localhost:50051` | `FRONTEND_ADDR=localhost:50052 make run-proxy` |

---

## Troubleshooting

**`make bootstrap` fails with "proto tools not found"**
Install `grpcio-tools`: `uv pip install grpcio-tools` (it's a dev dependency — should be present after `uv sync`).

**`curl /healthz` returns 503**
The frontend is not running. Start it first with `make run-frontend`.

**`mypy` reports errors in generated stubs**
Ensure `grpc-stubs` was installed: `uv sync --frozen` should handle this. If not, run `uv add grpc-stubs --dev`.
