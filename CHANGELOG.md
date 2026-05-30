# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This project publishes four packages in lockstep from one repository:
`vllm-grpc-gen`, `vllm-grpc-proxy`, `vllm-grpc-frontend`, and `vllm-grpc-client`.

## [Unreleased]

## [0.1.0] - 2026-05-30

First PyPI release. Brings the four workspace packages to a publish-ready,
installable state (no functional/runtime behaviour change beyond the engine-API
migration noted below).

### Added

- Complete distribution metadata for all four packages (description, keywords,
  classifiers, authors, MIT license, and Homepage/Repository/Issues/Changelog
  project URLs) plus a per-package `README.md` long-description.
- Console scripts: `vllm-grpc-proxy` (launches the REST proxy via uvicorn) and
  `vllm-grpc-frontend` (launches the gRPC server).
- `vllm-grpc-gen` build-time stub generation: a hatchling build hook runs
  `protoc` so the gitignored protobuf/gRPC stubs are produced into the wheel and
  sdist. `proto/` remains the single source of truth.
- `vllm-grpc-frontend` optional `engine` extra: `pip install
  "vllm-grpc-frontend[engine]"` pulls `vllm>=0.20`. The base install stays
  vLLM-free so it installs on any platform.
- `.github/workflows/release.yml`: a tag-triggered (`v*`) publish pipeline using
  Trusted Publishing (OIDC), publishing to TestPyPI then — behind a manual
  approval gate — to PyPI, with `vllm-grpc-gen` built first.

### Changed

- Frontend engine path migrated from the deprecated V0 `AsyncLLMEngine` /
  `AsyncEngineArgs.from_engine_args` to vLLM's V1 `AsyncLLM`, eliminating the
  recurring deprecation warning.
- Dependency floors bumped to the lock-resolved versions (floor-only, no upper
  caps): `grpcio>=1.80`, `fastapi>=0.136`, `uvicorn[standard]>=0.46`; `gen`
  declares `protobuf>=6.33` + `grpcio>=1.80`. Leaf packages depend on the
  published `vllm-grpc-gen~=0.1.0` instead of a workspace path.

[Unreleased]: https://github.com/AncientStudying/vllm-grpc/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AncientStudying/vllm-grpc/releases/tag/v0.1.0
