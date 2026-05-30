# Release History

Human-readable notes for each tagged release on the `v*` (codebase-state /
semver) tag namespace. This namespace is independent of the `milestone/*` tags,
which record research deliverables. Machine-readable per-package changes are in
[`CHANGELOG.md`](../CHANGELOG.md).

---

## v0.1.0 — First PyPI release (2026-05-30)

Brings the four workspace packages — `vllm-grpc-gen`, `vllm-grpc-proxy`,
`vllm-grpc-frontend`, `vllm-grpc-client` — to a publish-ready, installable state.

- Full distribution metadata + per-package READMEs; `vllm-grpc-proxy` and
  `vllm-grpc-frontend` console scripts.
- `vllm-grpc-gen` generates its protobuf/gRPC stubs at build time (hatchling
  hook); `proto/` stays the single source of truth.
- Frontend migrated from vLLM's deprecated V0 `AsyncLLMEngine` to the V1
  `AsyncLLM` API; vLLM is an opt-in `engine` extra so the base install is
  platform-agnostic.
- Tag-triggered, OIDC-based release pipeline (`release.yml`): TestPyPI then a
  manually-gated PyPI publish.

See [`CHANGELOG.md`](../CHANGELOG.md#010---2026-05-30) for the detailed entry.

---

## v0.0.1 — Bench-harness refactor (2026-05-30)

Post-M6.2 housekeeping: internal refactor of the benchmark harness
(`tools/benchmark`) for maintainability. No published packages; codebase-state
tag only.

---

## v0.0.0 — Post-M6.2 housekeeping (2026-05-26)

The first codebase-state tag, cut after the M6.2 token-budget characterization
milestone. Documentation and cleanup baseline; no published packages.
