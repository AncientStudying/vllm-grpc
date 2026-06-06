# Contract: Release Pipeline (`.github/workflows/release.yml`)

Structural contract for the tag-triggered release workflow. Within this feature the workflow is
**authored and statically validated only** — no job runs, no upload occurs.

## Required shape

```yaml
name: Release
on:
  push:
    tags: ["v*"]                       # FR-011 — tag-triggered

jobs:
  build:                               # FR-011 — builds all 4 distributions
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv build --package vllm-grpc-gen        # gen first — FR-015
      - run: uv build --package vllm-grpc-proxy
      - run: uv build --package vllm-grpc-frontend
      - run: uv build --package vllm-grpc-client
      - uses: actions/upload-artifact@v4             # hand dists to publish jobs

  publish-testpypi:                    # FR-013 — authored, NOT executed in-feature
    needs: build
    runs-on: ubuntu-latest
    permissions:
      id-token: write                  # FR-012 — OIDC, no stored token
    steps:
      - uses: actions/download-artifact@v4
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/   # gen first via ordering — FR-015

  publish-pypi:                        # FR-014 — present but gated
    needs: publish-testpypi
    runs-on: ubuntu-latest
    environment: pypi-release          # required-reviewers gate = manual approval
    permissions:
      id-token: write                  # FR-012 — OIDC
    steps:
      - uses: actions/download-artifact@v4
      - uses: pypa/gh-action-pypi-publish@release/v1     # default = real PyPI
```

## Contract assertions (statically verifiable — no run)

- C-W1: triggers only on `v*` tags. (FR-011)
- C-W2: a build job produces wheel + sdist for all four packages. (FR-011/SC-001)
- C-W3: every publish job sets `permissions: id-token: write` and references **no** API-token
  secret (`password:` / `PYPI_API_TOKEN` absent). (FR-012/VR-7)
- C-W4: a TestPyPI publish step exists (`repository-url: …test.pypi.org/legacy/`). (FR-013)
- C-W5: a real-PyPI publish step exists and is gated behind a protected `environment:` with required
  reviewers. (FR-014)
- C-W6: `gen` is published before/satisfying the leaf packages (job `needs:` or step ordering).
  (FR-015)
- C-W7: workflow passes `actionlint` (or equivalent static lint). (SC-005)
- C-W8: no job executes during this feature — verified by the absence of a `v0.1.0`-triggering
  upload and the gated environment. (FR-014a/FR-020/SC-008)
- C-W9: the "version already on index" edge case has a documented re-run strategy (e.g. a
  pre-release/dev suffix for TestPyPI, or documented deletion) in the workflow comments or
  CONTRIBUTING. (edge case)

## Out of scope for this contract
- Actually running any job (test or real upload) — operator action, post-merge.
- Configuring the PyPI/TestPyPI Trusted-Publisher relationship — operator prerequisite.
