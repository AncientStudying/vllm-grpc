# Contract: Package Metadata (`pyproject.toml` per package)

The published-interface contract for each of the four distributions. A package satisfies this
contract when its built `METADATA` contains every required field below and passes `twine check`.

## Shared `[project]` contract (all four)

```toml
[project]
name = "<vllm-grpc-{gen|proxy|frontend|client}>"
version = "0.1.0"                       # static literal — FR-003 / FR-003b
requires-python = ">=3.12"              # no upper cap — FR-003a
description = "<non-empty, plain-language>"   # FR-001 / FR-024
readme = "README.md"                    # per-package long-description — FR-002
license = "MIT"                         # SPDX, matches root LICENSE — FR-001
keywords = ["vllm", "grpc", "llm", "inference", ...]   # FR-001
authors = [{ name = "<author>", email = "<email>" }]   # FR-001
classifiers = [
  "Development Status :: 4 - Beta",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3.12",
  "Topic :: Scientific/Engineering :: Artificial Intelligence",
]                                       # FR-001 / FR-003a

[project.urls]
Homepage   = "https://github.com/<org>/vllm-grpc"
Repository = "https://github.com/<org>/vllm-grpc"
Issues     = "https://github.com/<org>/vllm-grpc/issues"
Changelog  = "https://github.com/<org>/vllm-grpc/blob/main/CHANGELOG.md"   # resolves — FR-018a
```

**Contract assertions** (verifiable):
- C-M1: built `METADATA` has `Requires-Python: >=3.12` and **no** `<` upper bound. (FR-003a)
- C-M2: `Version: 0.1.0` literal; pyproject has no `dynamic = ["version"]`. (FR-003b)
- C-M3: all four `Project-URL` entries present. (FR-001/SC-006)
- C-M4: `Description-Content-Type` set and long-description renders (twine check clean). (FR-008a)
- C-M5: classifiers include the AI topic + Python 3.12 + MIT. (FR-001)

## Per-package dependency contract

```toml
# gen — owns generated code's runtime imports (FR-006c)
dependencies = ["protobuf>=6.33", "grpcio>=1.80"]
[build-system]
requires = ["hatchling", "grpcio-tools>=1.80", "protobuf>=6.33"]   # FR-007a
build-backend = "hatchling.build"
[tool.hatch.build.hooks.custom]                                    # runs protoc — FR-007a

# proxy
dependencies = ["fastapi>=0.136", "uvicorn[standard]>=0.46", "grpcio>=1.80", "vllm-grpc-gen~=0.1.0"]
[project.scripts]
vllm-grpc-proxy = "vllm_grpc_proxy.main:main"                      # FR-004

# frontend  (vLLM intentionally absent — FR-005)
dependencies = ["grpcio>=1.80", "vllm-grpc-gen~=0.1.0"]
[project.scripts]
vllm-grpc-frontend = "vllm_grpc_frontend.main:main"               # FR-004

# client — lean, no web-server deps (FR-009)
dependencies = ["grpcio>=1.80", "vllm-grpc-gen~=0.1.0"]
```

**Contract assertions**:
- C-D1: no third-party constraint carries an upper cap (`<` / `!=` ceiling). (FR-006a)
- C-D2: floors are exactly the lock-resolved values or higher: grpcio≥1.80, fastapi≥0.136,
  uvicorn≥0.46, protobuf≥6.33. (FR-006b/FR-006c)
- C-D3: internal dep is `vllm-grpc-gen~=0.1.0` in every leaf package. (FR-006)
- C-D4: frontend `METADATA` has **no** `Requires-Dist: vllm` and **no** vLLM optional extra
  (`Provides-Extra` / `Requires-Dist: vllm; extra == …`) — vLLM is a pure peer; the V1-API floor
  (`vllm>=0.20`) lives only in the frontend README + root install matrix. (FR-005/FR-005a)
- C-D5: `[tool.uv.sources]` does not appear in built `METADATA`. (edge case — no workspace leak)
