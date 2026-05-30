# Contract: Verification Commands (FR/SC → runnable check)

Every requirement in this feature is provable by a local or CI command. These are the acceptance
gates the /tasks phase turns into tasks. **None uploads to any index.**

## Build (FR-007 / SC-001)

```bash
for p in gen proxy frontend client; do uv build --package vllm-grpc-$p; done
# Expect: dist/*.whl + dist/*.tar.gz for each → 8 artifacts, zero errors.
```

## Metadata / long-description (FR-008a / SC-005 / SC-006)

```bash
uvx twine check packages/*/dist/*          # zero errors AND zero warnings
```

## Clean-environment install (FR-008 / SC-002)

```bash
uv venv /tmp/clean && uv pip install --python /tmp/clean/bin/python --no-project \
  --find-links packages/gen/dist packages/<pkg>/dist/<pkg>-0.1.0-py3-none-any.whl
# Expect: install succeeds resolving vllm-grpc-gen from the local index (not a workspace path).
```

## gen standalone import (FR-007a / SC-013)

```bash
uv pip install --python /tmp/gen/bin/python --no-project packages/gen/dist/*.whl
/tmp/gen/bin/python -c "import vllm_grpc.v1.chat_pb2, vllm_grpc.v1.chat_pb2_grpc; print('ok')"
# Also assert the wheel CONTAINS the stubs:
python -m zipfile -l packages/gen/dist/*.whl | grep -E "v1/.*_pb2(_grpc)?\.py"
```

## Client leanness (FR-009 / SC-003)

```bash
uv pip install --python /tmp/client/bin/python --no-project \
  --find-links packages/gen/dist packages/client/dist/*.whl
/tmp/client/bin/python -m pip freeze | grep -Ei "fastapi|uvicorn" && echo "FAIL: web deps leaked" || echo "ok"
```

## Console-script smoke (FR-010 / SC-004)

```bash
# proxy: launch, hit /healthz, expect a served response (fake/empty backend ok)
/tmp/proxy/bin/vllm-grpc-proxy &   # then curl http://127.0.0.1:<port>/healthz
# frontend: launch against the existing fake-engine fixture, assert gRPC server starts
/tmp/frontend/bin/vllm-grpc-frontend &   # with fake engine env; no GPU/model
```

## Floors stay green (FR-006b / SC-009)

```bash
make proto && uv run pytest packages/proxy/tests packages/frontend/tests packages/client/tests -q
# Run with deps resolved at the new floors; expect the existing suite green.
```

## Deprecation-free own code (FR-023 / SC-010)

```bash
uv run python -W error::DeprecationWarning -c "import vllm_grpc_frontend.main"
# And: exercise the frontend smoke path; assert no DeprecationWarning from vllm_grpc_frontend.*
grep -rn "AsyncLLMEngine\|AsyncEngineArgs" packages/frontend/src && echo "FAIL: V0 path remains" || echo "ok"
```

## Release workflow static validation (FR-011–FR-015 / SC-005 / SC-008)

```bash
uvx actionlint .github/workflows/release.yml        # or actionlint binary
grep -nE "password:|PYPI_API_TOKEN" .github/workflows/release.yml && echo "FAIL: token auth" || echo "ok"
grep -n "id-token: write" .github/workflows/release.yml          # OIDC present
# Manual review: test step before real step; real step gated by environment; gen built first.
# Assert NO run occurred: no v0.1.0 tag pushed during this feature.
```

## Docs (FR-016–FR-018a / FR-024–FR-026 / SC-007 / SC-011 / SC-012)

```bash
test -f CHANGELOG.md && grep -q "0.1.0" CHANGELOG.md
test -f docs/RELEASES.md && grep -Eq "v0.0.0|v0.0.1|v0.1.0" docs/RELEASES.md
for p in gen proxy frontend client; do test -f packages/$p/README.md; done   # per-package READMEs
grep -q "pip install vllm-grpc-client" README.md                              # install matrix
# Manual: consistency of package names/commands/terminology across README, ANALYSIS, CONTRIBUTING.

# vLLM peer-prerequisite floor is documented, NOT in metadata (FR-005a / SC-007a):
grep -Eiq "vllm.*v1|AsyncLLM" packages/frontend/README.md && grep -Eq ">=\s*0\.20|0\.20" packages/frontend/README.md
grep -Eiq "vllm" README.md            # root install matrix names the vLLM prerequisite
# And assert vLLM appears in NO built frontend metadata (hard dep or extra):
python -m zipfile -l packages/frontend/dist/*.whl >/dev/null
unzip -p packages/frontend/dist/*.whl "*/METADATA" | grep -i "vllm" \
  && echo "FAIL: vLLM leaked into frontend metadata" || echo "ok: vLLM is pure peer"
```

## No-upload invariant (FR-014a / FR-020 / SC-008)

The whole feature performs **zero** `twine upload` / `uv publish` / `gh-action-pypi-publish` runs.
Grep history/CI logs to confirm no upload step executed; confirm no distribution name was claimed on
any index.
