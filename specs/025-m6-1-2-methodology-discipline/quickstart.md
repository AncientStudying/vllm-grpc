# Quickstart: M6.1.2 — Methodology Discipline

**Branch**: `025-m6-1-2-methodology-discipline` | **Phase 1 output** | **Plan**: [plan.md](./plan.md)

This is the operator playbook for landing M6.1.2 and producing its published artifact at `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`. Follow the phases in order. Each phase has its own merge gate.

## Phase 0 — One-time setup (operator workstation)

### Install `tcptraceroute`

The M6.1.2 topology probe (Story 1) requires the `tcptraceroute` binary (Michael Toren's tool) per FR-002 + round-2 Q3. Single canonical tool; no cross-platform fallbacks.

```sh
# macOS:
brew install tcptraceroute

# Debian / Ubuntu:
sudo apt install tcptraceroute

# RHEL / Fedora:
sudo dnf install tcptraceroute

# Verify:
tcptraceroute --version
```

#### macOS: one-time setuid fixup (Homebrew install only)

`tcptraceroute` needs raw socket access to send SYNs, which on macOS requires
root. The system `/usr/sbin/traceroute` ships setuid-root and "just works"
without `sudo`, but Homebrew installs as the user so it can't apply the
setuid bit — you'll see `Got root?` when you run `tcptraceroute <host> <port>`
unprivileged.

Mirror the system `traceroute` model with a one-time post-install fixup so
the M6.1.2 sweep can invoke the probe without escalating the entire Python
process:

```sh
sudo chown root:wheel $(brew --prefix)/bin/tcptraceroute
sudo chmod u+s        $(brew --prefix)/bin/tcptraceroute

# Sanity check — should now print hops as your normal user, no sudo:
tcptraceroute -n -w 2 -q 1 -m 8 1.1.1.1 443 | head -5
```

(Linux package installs from `apt` / `dnf` typically handle this for you
via the package's post-install hooks — only macOS Homebrew needs this
manual step.)

If `tcptraceroute` is absent — or installed but not setuid-root and the
sweep wasn't launched with `sudo` — the M6.1.2 sweep still completes
(FR-005's error-block-and-continue behavior fires per cohort) but the
`network_paths` block records error entries for every cohort and FR-005a's
loud stderr warning surfaces — topology evidence is unavailable for that
sweep. SC-002 / SC-004 / SC-010 are not satisfied. The PR-validation sweep
MUST be run from an environment where the probe binary can dispatch raw
SYNs unprivileged (or the operator must `sudo` the sweep, which runs the
entire Python process as root — not recommended).

### Switch to the M6.1.2 branch

```sh
git checkout 025-m6-1-2-methodology-discipline
git log -1 --oneline  # Should show the latest clarify commit (b237b6f or later)
```

### Cherry-pick the spike's timestamped-progress-line commit

Per FR-021 + R-7, commit `3763687` on `spike/m6-1-roadmap-additions` carries forward verbatim. Cherry-pick it to the M6.1.2 branch:

```sh
git cherry-pick 3763687
# If cherry-pick fails because the spike branch was rebased: re-create the
# 5-file change set manually (m6_sweep.py, m6_1_sweep.py, m6_1_1_sweep.py,
# tools/benchmark/tests/test_m6_quickstart_format.py, traceroute_probe.py)
# per data-model.md's "Modified Files" table.
```

### Local environment

```sh
uv sync --frozen   # Inherits M6.1.1's pinned vllm + torch + grpcio versions
```

## Phase 1 — Implement the new modules (no Modal compute)

Implementation order matches the data-model dependency graph (each module depends on earlier ones):

1. `tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py` — dataclasses + literals (per [`data-model.md`](./data-model.md)).
2. `tools/benchmark/src/vllm_grpc_bench/m6_1_2_network_probe.py` — `tcptraceroute` subprocess + CSP attribution (per R-5, R-6; spec FR-001 through FR-007).
3. `tools/benchmark/src/vllm_grpc_bench/m6_1_2_reporter.py` — JSON / markdown serialization (mirroring `m6_1_1_reporter.py`).
4. `tools/benchmark/src/vllm_grpc_bench/m6_1_2_sweep.py` — orchestrator (calls the probe, iterates the 4 cohorts, dispatches to `m6_1_rpc_driver.py`).
5. `tools/benchmark/src/vllm_grpc_bench/m6_1_2_validate.py` — `--m6_1_2-validate` entry point.

Then the modifications:

6. `tools/benchmark/src/vllm_grpc_bench/m6_1_rpc_driver.py:305-345` — add the `rest_plain_tcp` 4th cohort dispatch case (per R-4).
7. `tools/benchmark/src/vllm_grpc_bench/__main__.py:525-600 area` — add `--m6_1_2` + `--m6_1_2-validate` + 12 namespaced sub-flags (per [`contracts/cli.md`](./contracts/cli.md)).

### Local lint chain (mandatory pre-push gate)

Per [`feedback_local_lint_chain`](../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_local_lint_chain.md) memory + Constitution Principle IV: CI runs four separate gates. Run all four locally before pushing:

```sh
uv run ruff check tools/benchmark/
uv run ruff format --check tools/benchmark/
uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_2_types.py \
                     tools/benchmark/src/vllm_grpc_bench/m6_1_2_network_probe.py \
                     tools/benchmark/src/vllm_grpc_bench/m6_1_2_reporter.py \
                     tools/benchmark/src/vllm_grpc_bench/m6_1_2_sweep.py \
                     tools/benchmark/src/vllm_grpc_bench/m6_1_2_validate.py
uv run pytest tools/benchmark/tests/test_m6_1_2_*.py
```

All four MUST pass before push. The Constitution Principle IV prohibition on `--no-verify` applies.

### Unit-test the new modules

Each new test file under `tools/benchmark/tests/` (per [`plan.md`](./plan.md) Testing section):

```sh
uv run pytest tools/benchmark/tests/test_m6_1_2_network_probe.py     # R-5 + R-6 coverage
uv run pytest tools/benchmark/tests/test_m6_1_2_artifact_schema.py   # FR-016 + SC-006 coverage
uv run pytest tools/benchmark/tests/test_m6_1_2_cli.py               # FR-026 / FR-027 + verbatim-inheritance regression
uv run pytest tools/benchmark/tests/test_m6_1_2_progress_format.py   # SC-005 + FR-020 coverage
uv run pytest tools/benchmark/tests/test_m6_1_2_smoke_validate_cli.py  # End-to-end CLI integration (no Modal)
```

## Phase 2 — Run the smoke-equivalent validation sweep

Per FR-024 + round-1 Q4 + SC-001 + SC-008. This is the M6.1.2 PR-merge gate: the sweep produces the published artifact at `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`.

### Pre-flight checks

```sh
# Confirm tcptraceroute reachable:
tcptraceroute --version

# Confirm M6.1.1 baseline exists (--m6_1_2-m6-1-1-baseline default points here):
ls -la docs/benchmarks/m6_1_1-engine-cost-instrumentation.json

# Confirm Modal token env var:
echo "${MODAL_BENCH_TOKEN:-<unset>}"

# Confirm the M6.1.2 CLI surface parses:
uv run python -m vllm_grpc_bench --m6_1_2-validate --help | head -20
```

### Run the validation sweep

```sh
uv run python -m vllm_grpc_bench --m6_1_2-validate \
    --m6_1_2-modal-region=eu-west-1 \
    --m6_1_2-base-seed=42 \
    --m6_1_2-model="Qwen/Qwen3-8B"
```

Note: the three explicit `--m6_1_2-*` arguments above match the defaults verbatim (per FR-027 + round-3 Q2) — they're shown explicitly here so the operator can spot-check the verbatim-inheritance contract is being respected. Omitting them is equivalent.

Expected sweep behavior (per SC-001):
- ~33 min wall-clock on Modal A10G `eu-west-1` (M6.1.1's ~27 min + ~120s probe overhead + cohort 3→4 expansion).
- Probe completes in ~5-30s at sweep start (parallel-across-cohorts, 30s per-cohort timeout).
- Loud stderr warning if any cohort's CSP differs from the spike-confirmed pattern (FR-006) or every probe fails (FR-005a).
- Total Modal compute: ~$0.40 (cap $0.50 per SC-008).

### Inspect the artifact

```sh
# Verify the new top-level keys are present:
jq 'keys' docs/benchmarks/m6_1_2-methodology-discipline.json

# Should include (at minimum): cohort_set, cohort_omissions (or absent), network_paths,
# plus M6.1.1-inherited keys (dispatch_mode, run_id, run_meta, ...)

# Verify the 4-cohort split:
jq '.cohort_set' docs/benchmarks/m6_1_2-methodology-discipline.json
# Expected: ["default_grpc", "rest_https_edge", "rest_plain_tcp", "tuned_grpc_multiplexed"]

# Verify network_paths topology (per SC-002):
jq '.network_paths | to_entries | map({cohort: .key, cloud_provider: .value.cloud_provider, region: .value.region})' \
    docs/benchmarks/m6_1_2-methodology-discipline.json
# Expected (deploys conforming to spike-confirmed pattern):
#   rest_https_edge        -> ("Microsoft Azure", null)
#   rest_plain_tcp         -> ("AWS",             "us-west-1")
#   default_grpc           -> ("AWS",             "us-west-1")
#   tuned_grpc_multiplexed -> ("AWS",             "us-west-1")

# Verify the protocol-only differential is computable (per SC-004):
jq '.phase_1_runs[0].cells | map({cell: .key,
  rest_plain_tcp_ttft_ms: .value.rest_plain_tcp.engine_ttft_ms.mean,
  default_grpc_ttft_ms:   .value.default_grpc.engine_ttft_ms.mean,
  delta_ms: (.value.rest_plain_tcp.engine_ttft_ms.mean - .value.default_grpc.engine_ttft_ms.mean)
})' docs/benchmarks/m6_1_2-methodology-discipline.json
```

### Update ANALYSIS.md and instrumentation contract

Per FR-008 + FR-009 + SC-007. Both updates land in the same PR as the code change:

```sh
# ANALYSIS.md: replace the loose "different network path" phrasing with the
# multi-CSP framing from spike #1 (FR-008). Search for "different network path"
# and update with: "cohorts enter Modal via entirely different cloud providers
# (Microsoft Azure for *.modal.run; AWS us-west-1 for *.modal.host); see
# docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md for
# the live traceroute proof and docs/benchmarks/m6_1_2-methodology-discipline.json
# for per-sweep evidence in the network_paths block."

# contracts/instrumentation.md (or equivalent): add a section documenting
# network_paths, cohort_set, cohort_omissions per FR-009 + FR-016 +
# specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md +
# specs/025-m6-1-2-methodology-discipline/contracts/artifact-schema.md.
```

## Phase 3 — Land the PR

### Pre-PR checks

```sh
# Final lint chain:
uv run ruff check tools/benchmark/
uv run ruff format --check tools/benchmark/
uv run mypy --strict tools/benchmark/src/vllm_grpc_bench/m6_1_2_*.py
uv run pytest tools/benchmark/tests/

# Verify artifact exists and parses:
jq -e '.cohort_set | length' docs/benchmarks/m6_1_2-methodology-discipline.json

# Verify ANALYSIS.md updated:
grep -n "cohorts enter Modal via entirely different cloud providers" ANALYSIS.md
```

### Open the PR

Per [`feedback_pr_creation_deferred`](../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_pr_creation_deferred.md) memory: PR creation is a separate gate from push. Confirm with the user before `gh pr create`.

PR description should reference:
- Spec: `specs/025-m6-1-2-methodology-discipline/spec.md` (13 Q/A clarifications across 3 rounds)
- Plan: `specs/025-m6-1-2-methodology-discipline/plan.md`
- Published artifact: `docs/benchmarks/m6_1_2-methodology-discipline.{md,json}`
- PLAN.md M6.1.2 section: `docs/PLAN.md` §234-258

## Troubleshooting

### Probe fails with `tcptraceroute_unavailable` for every cohort

The binary isn't on PATH. Install it (Phase 0). Re-run the sweep. The previous artifact's `network_paths` error blocks are overwritten.

### Probe fails with `subprocess_error` / "Got root?" for every cohort (macOS Homebrew)

`tcptraceroute` is on PATH but isn't setuid-root, so it can't open the raw socket as an unprivileged user. Apply the one-time setuid fixup from Phase 0:

```sh
sudo chown root:wheel $(brew --prefix)/bin/tcptraceroute
sudo chmod u+s        $(brew --prefix)/bin/tcptraceroute
```

Re-run the sweep. (Running the whole sweep with `sudo` also works but escalates the entire Python process — Modal client, httpx, etc. — to root, which is not recommended.)

### Probe times out for one or more cohorts

Likely cause: the operator's network blocks scan-like TCP-SYN traffic but allows established connections (the measurement RPCs still complete fine). Re-run from an unrestricted host if topology evidence matters for the PR-merge gate.

### Cohort-CSP-mismatch warning fires (FR-006)

Modal's tunnel architecture has changed since the spike's 2026-05-17 measurement. The artifact records the new reality faithfully. Cross-check the new `cloud_provider` values in `network_paths` against the spike's findings; if Modal moved a cohort to a new CSP, this is a methodology-significant event and should be flagged in the PR description (the topology assertion ANALYSIS.md will cite is now wrong; FR-008's update needs to reflect the new reality, not the spike's).

### `--m6_1_2-modal-region` default doesn't match `--m6_1_1-diagnose`'s default

A drift regression — fail the CI test in `test_m6_1_2_cli.py::test_m6_1_2_inheritable_defaults_match_m6_1_1`. Fix `__main__.py:541` (or wherever the default landed) to set the M6.1.2 default to the same string as M6.1.1's. Round-3 Q2 + FR-027 explicitly guard against this.

### M6.1.1's `--m6_1_1-diagnose` historical re-run produces different output after M6.1.2 lands

This is a serious regression — per FR-028, M6.1.1's flag semantics MUST stay frozen. Investigate: did any of the modifications to `m6_sweep.py` / `m6_1_sweep.py` / `m6_1_1_sweep.py` (the spike's timestamp helper cherry-pick) accidentally change classifier or measurement logic? The timestamp helper should ONLY affect stderr emission, not data flow.

## Cross-references

- Plan: [`plan.md`](./plan.md)
- Data model: [`data-model.md`](./data-model.md)
- CLI contract: [`contracts/cli.md`](./contracts/cli.md)
- Network-paths contract: [`contracts/network-paths.md`](./contracts/network-paths.md)
- Artifact-schema contract: [`contracts/artifact-schema.md`](./contracts/artifact-schema.md)
- Spec: [`spec.md`](./spec.md)
- Research: [`research.md`](./research.md)
- PLAN.md M6.1.2 section: `docs/PLAN.md` §234-258
- M6.1.1 quickstart precedent: `specs/023-m6-1-1-engine-cost-instrumentation/quickstart.md`
- M6.0a quickstart precedent: `specs/024-m6-0a-concurrent-dispatch/quickstart.md`
