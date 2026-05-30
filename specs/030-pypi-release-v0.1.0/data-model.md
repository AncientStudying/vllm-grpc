# Phase 1 Data Model: First PyPI Release (v0.1.0)

This feature ships no runtime datastore. The "entities" are **packaging artifacts and their
metadata** — the structured objects the build, install, and release steps operate on. Modeling them
explicitly gives the /tasks phase concrete fields, relationships, and validation rules to verify.

---

## Entity 1 — Distributable Package

One of the four workspace members. Each produces a wheel + sdist.

| Field | Type | Rule / Source |
|-------|------|---------------|
| `name` | string | One of `vllm-grpc-gen`, `vllm-grpc-proxy`, `vllm-grpc-frontend`, `vllm-grpc-client` (FR-001) |
| `version` | string literal | Exactly `"0.1.0"`, static, no `dynamic`/VCS (FR-003, FR-003b) |
| `requires_python` | string | `">=3.12"`, no upper cap (FR-003a) |
| `description` | string | Non-empty, plain-language (FR-001, FR-024) |
| `keywords` | list[string] | Non-empty (FR-001) |
| `classifiers` | list[string] | MUST include an AI/scientific topic, `Programming Language :: Python :: 3.12`, `License :: OSI Approved :: MIT License`, a `Development Status` (FR-001, FR-003a) |
| `authors` | list[{name,email}] | Non-empty (FR-001) |
| `license` | string | `"MIT"`, consistent with root `LICENSE` (FR-001) |
| `readme` | path | `README.md` inside the package dir; rendered as long-description (FR-002) |
| `urls` | map | MUST contain Homepage, Repository, Issues, Changelog — all 4 (FR-001); Changelog resolves to a valid target (FR-018a/SC-011) |
| `dependencies` | list[constraint] | Floor-only `>=`, no caps for third-party (FR-006a/FR-006b); internal `vllm-grpc-gen~=0.1.0` (FR-006) |
| `console_script` | optional map | proxy + frontend only (FR-004) |
| `build_backend` | string | `hatchling.build` |

**Per-package specialization**

| Package | console_script | extra deps | build specifics |
|---------|----------------|------------|-----------------|
| `vllm-grpc-gen` | — | `protobuf>=6.33`, `grpcio>=1.80` (FR-006c) | build hook runs `protoc`; `grpcio-tools` in `[build-system].requires`; stubs gitignored, generated into wheel+sdist (FR-007a/SC-013) |
| `vllm-grpc-proxy` | `vllm-grpc-proxy = vllm_grpc_proxy.main:main` | `fastapi>=0.136`, `uvicorn[standard]>=0.46`, `grpcio>=1.80`, `vllm-grpc-gen~=0.1.0` | new `main()` calling `uvicorn.run` |
| `vllm-grpc-frontend` | `vllm-grpc-frontend = vllm_grpc_frontend.main:main` | default: `grpcio>=1.80`, `vllm-grpc-gen~=0.1.0` (**no vLLM**); optional extra `engine = ["vllm>=0.20"]` (FR-005/FR-005a) | V0→V1 engine remediation (FR-022) |
| `vllm-grpc-client` | — | `grpcio>=1.80`, `vllm-grpc-gen~=0.1.0` | lean — no web-server deps (FR-009/SC-003) |

**State transitions (per package)**

```
authored(pyproject+README) → builds(wheel+sdist) → metadata-valid(twine check)
  → installs(clean venv) → smoke-passes(console script / import)
```
Each arrow is a verification gate (FR-007/008/008a/010, SC-001/002/004). DoD = all four reach
`smoke-passes` with **no upload**.

**Validation rules**
- VR-1: `twine check` emits zero errors/warnings for every artifact (FR-008a/SC-005).
- VR-2: No `[tool.uv.sources]`/workspace path leaks into published `METADATA` (edge case).
- VR-3: Client install pulls zero proxy/frontend-only deps (no `fastapi`/`uvicorn`) (FR-009/SC-003).
- VR-4: `gen` wheel/sdist contains `vllm_grpc/v1/*_pb2*.py`; `import vllm_grpc.v1` works after a
  standalone `gen` install (SC-013).
- VR-5: No third-party constraint has an upper cap (FR-006a).

---

## Entity 2 — Release Pipeline (`.github/workflows/release.yml`)

| Field | Type | Rule / Source |
|-------|------|---------------|
| `trigger` | event | `push` on tags matching `v*` (FR-011) |
| `auth_mode` | enum | Trusted Publishing / OIDC — `permissions: id-token: write`, no stored token (FR-012) |
| `build_job` | job | Builds all 4 distributions (wheel+sdist) (FR-011) |
| `testpypi_step` | job/step | Uploads 4 packages to test index; authored + statically validated, **not executed in-feature** (FR-013) |
| `pypi_step` | job/step | Real-index upload, present but gated behind manual approval; **not executed in-feature** (FR-014) |
| `ordering` | constraint | `gen` published before/satisfying leaf deps (FR-015) |
| `gating` | constraint | No step uploads within this feature (FR-014a/FR-020/SC-008) |

**Validation rules**
- VR-6: Workflow passes static lint (actionlint-style) (SC-005).
- VR-7: No `password:`/`PYPI_TOKEN` secret referenced — OIDC only (FR-012).
- VR-8: Both test + real publish steps present, both tag-gated, real step approval-gated (US3).
- VR-9: Re-runnable strategy for "version already exists" documented (edge case).

---

## Entity 3 — Install Matrix (documentation object)

| Persona | Install command | Notes |
|---------|-----------------|-------|
| SDK consumer | `pip install vllm-grpc-client` | gen installs transitively (FR-016) |
| Proxy operator | `pip install vllm-grpc-proxy` | console script `vllm-grpc-proxy` |
| Frontend operator | `pip install vllm-grpc-frontend` (base, no vLLM) or `pip install "vllm-grpc-frontend[engine]"` (pulls `vllm>=0.20`) | vLLM is a non-forced peer (FR-005); requires the V1 `AsyncLLM` API → expressed as the optional `engine` extra + documented (FR-005a/FR-016) |

**Validation rules**:
- VR-10 — a reader determines the correct command per persona in one read (SC-007); package names
  + commands consistent across all docs (SC-012).
- VR-12 — the frontend declares vLLM **only** as the optional `engine` extra (`vllm>=0.20`), never
  as a default dependency: `pip install vllm-grpc-frontend` pulls zero vLLM; `…[engine]` pulls
  `vllm>=0.20`. The frontend README + root install matrix state the V1-API prerequisite, the
  `[engine]` extra, and the `>=0.20` floor (FR-005a/SC-007a).

---

## Entity 4 — Release-History Documents

| Artifact | Format | Rule / Source |
|----------|--------|---------------|
| `CHANGELOG.md` | Keep-a-Changelog | Has a `v0.1.0` entry; is the `changelog` URL target (FR-018a/SC-011) |
| `docs/RELEASES.md` | human-readable notes | Lists `v0.0.0`, `v0.0.1`, `v0.1.0` (FR-018/SC-011) |

**Validation rule**: VR-11 — both files exist with a `v0.1.0` entry; every package's `changelog`
URL resolves to a valid target (SC-011).

---

## Cross-entity relationships

```
Distributable(gen) ──published-before──> Distributable(proxy|frontend|client)   [FR-015]
Distributable(proxy|frontend|client) ──Requires-Dist vllm-grpc-gen~=0.1.0──> Distributable(gen)
Release Pipeline ──builds+(later)publishes──> all 4 Distributables
Distributable.urls.Changelog ──resolves-to──> CHANGELOG.md
Install Matrix ──documents──> {client, proxy, frontend}
```

**Global invariant (DoD)**: every Distributable reaches `smoke-passes`, the Release Pipeline passes
static validation, and the count of external uploads performed in this feature is **exactly 0**
(SC-008 / FR-014a / FR-020).
