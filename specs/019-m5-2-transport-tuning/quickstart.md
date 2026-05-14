# M5.2 Quickstart

End-to-end reproduction guide for the M5.2 REST transport path × gRPC tuning surface sweep on Modal CPU-only. Wall-clock target: ≤40 minutes total (≤30 min full sweep + ≤10 min smoke + Phase J + K1/K2/K3 narrative commits).

## Prerequisites

- Local clone of this repo at `~/projects/vllm-grpc` (or wherever).
- `uv` toolchain installed and `uv sync --all-packages` run at the repo root.
- Modal credentials: `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` in the env, or `~/.modal.toml` configured (run `modal token new` if neither).
- A network path with realistic plain-TCP RTT to Modal's chosen region. From a US-east client, `eu-west-1` produces ~52 ms median plain-TCP RTT (M5.1's measured value); other region picks are documented in `--m5_2-modal-region`.
- The HTTPS-edge RTT will differ — Modal's HTTPS edge is anycast-routed, so the measured median depends on the client's geographic proximity to the nearest Modal edge POP. Record your client geolocation per FR-008 / R-3 tier (c).
- The M5.1 published JSON at `docs/benchmarks/m5_1-rest-vs-grpc.json` MUST be present on disk — the Supersedes-M5.1 table builder reads it directly.

## Step 1 — Generate a bearer token

```bash
export MODAL_BENCH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

The token is a one-time secret. It is **never** written to the report or to any committed file. Both the harness and the Modal container read it from the env / Modal Secret of the same name.

Optional: pin a known token if you intend to re-run the sweep against the same deployed app:

```bash
export MODAL_BENCH_TOKEN="my-stable-test-token-for-rerun-only"
```

## Step 1.5 — (Optional) Regenerate the chat corpus

> Added 2026-05-12 per research [R-12](research.md). The chat corpus is committed at `tools/benchmark/corpus/chat_sharegpt_1000.json` (the ShareGPT V3 1k-sample subset). Skip this step unless you intend to change the corpus size, filter, or pin to a different ShareGPT revision.

The committed corpus is byte-stable. Re-generating it with the default parameters produces a byte-identical JSON (modulo timestamp comments) because the script pins the source revision SHA, the source-file SHA-256, the filter criteria, and the random seed:

```bash
uv run python scripts/python/gen_chat_corpus.py \
    --count 1000 --min-chars 4 --max-chars 2048 --max-tokens 128 --seed 42
```

The first invocation downloads ShareGPT V3 (~673 MB) into the gitignored `bench-results/sharegpt-raw/` cache; subsequent invocations skip the download on SHA match. Output: `tools/benchmark/corpus/chat_sharegpt_1000.json` + `.provenance.json`.

The harness reads `chat_sharegpt_1000.json` by default. Override via `M5_2SweepConfig.chat_corpus_path` (currently config-only; no CLI flag).

## Step 2 — Run the pre-flight smoke gate (FR-005a + SC-012)

```bash
uv run python -m vllm_grpc_bench --m5_2 --m5_2-smoke
```

The smoke harness:
1. Deploys the dual-protocol Modal app (`vllm-grpc-bench-rest-grpc-mock`) to `eu-west-1`.
2. Probes RTT against all three endpoints (gRPC plain-TCP + REST HTTPS-edge + REST plain-TCP).
3. Runs the four M5.2-specific assertions per FR-005a:
    - Both REST transports reach the same Modal deploy (identical `/healthz` body + `modal_deploy_handle`).
    - M5.2-additive JSON schema fields round-trip (write → read → assert equivalence).
    - Per-cohort RTT probe within thresholds for all five cohorts.
    - Tier (a) + tier (b) symmetry assertion passes (per FR-005b).
4. Runs the 4-cell smoke (`chat_stream c=1`, `chat_stream c=4`, `embed c=4`, `embed c=1`) with `n=5` measurement + `n=2` warmup per cohort.
5. Emits the smoke's events sidecar (gzipped) + aggregate JSON + markdown.
6. Tears down the Modal app.
7. Prints a structured `M5_2 smoke gate: PASS — <timestamp>, <asserted_clauses_count>, per-cohort RTT medians (ms): rest_https_edge=<...>, rest_plain_tcp=<...>, default_grpc=<...>, tuned_grpc_*=<...>` line.

**Copy this PASS line. The PR description MUST cite it explicitly per SC-012.**

If the smoke fails (exit code 5 for symmetry, 6 for RTT/assertion, etc.), **STOP**: fix the cause before running the full sweep. The smoke is the gate.

## Step 3 — Run the full M5.2 sweep

```bash
uv run python -m vllm_grpc_bench --m5_2 --m5_2-modal-region=eu-west-1
```

The harness:
1. Deploys the dual-protocol Modal app to `eu-west-1`.
2. Looks up the client's external geolocation via `https://ipinfo.io/json` (skip with `--m5_2-skip-geolocation-lookup` in air-gapped environments).
3. Builds and asserts the 3-tier symmetry block per FR-005b. Aborts on tier (a) or tier (b) divergence with exit code 5 and the diverging field named in stderr.
4. Probes RTT against all three endpoints. Aborts on RTT validity failure with exit code 6.
5. Loads the chat corpus (`tools/benchmark/corpus/chat_sharegpt_1000.json` by default; logged as `[m5_2] chat corpus: 1000 samples from ...`). Both REST and gRPC chat cohorts cycle through this corpus by iteration index (per research [R-12](research.md)).
6. Runs warmup cohorts per protocol-side per path. Warmup records ARE written to the sidecar (`phase: "warmup"`) but excluded from aggregates.
7. Enumerates the 18 matrix cells (2 paths × 3 widths × 3 concurrencies). For each cell, dispatches (in series): `rest_https_edge` → `rest_plain_tcp` → `default_grpc` → `tuned_grpc_multiplexed` (c≥2) → `tuned_grpc_channels` (c≥2) OR `tuned_grpc` (c=1). Per-request events stream to the un-gzipped sidecar.
8. On full-sweep completion: closes the sidecar, gzips it (`gzip -9`), computes the SHA-256 hex.
9. Emits `bench-results/m5_2-full/{run_id}.run_config.json` with the symmetry block, sidecar path, sidecar SHA-256, modal region/instance class, run timestamps, etc.
10. Does NOT emit the markdown or aggregate JSON directly (per FR-012b — the regenerator builds those from the sidecar + run config).
11. Tears down the Modal app.

**Expected wall-clock: 25–66 minutes** (per SC-007 / Edge Case "n=250 doubles per-cohort runtime"). Monitor with `modal app list | grep vllm-grpc-bench-rest-grpc-mock` (should be empty after a clean teardown).

**Preemption recovery (R-13)**: Modal occasionally preempts long-running Functions and restarts them on a new worker (https://modal.com/docs/guide/preemption). The new worker writes fresh tunnel URLs to the same Modal Dict; the harness detects the resulting `ConnectError`, polls the Dict for fresh URLs, and retries the affected cell once. Expect stderr lines like:

```
[m5_2] cell N/18 <cell_key>: connect error (ConnectError); polling Modal Dict for fresh URLs (preemption check) …
[m5_2] cell N/18 <cell_key>: preemption detected — updating URLs and retrying. new grpc=<host>:50051, new rest_edge=https://<id>.modal.run
```

A successful refresh + retry costs ~90 s (Dict poll timeout) and resumes the sweep transparently. If refresh returns `None` (no fresh URLs detected within the timeout), the cell falls through to the `failed_cells` log and the sweep proceeds to the next cell.

**Per-cell isolation**: If a cohort fails irrecoverably mid-sweep (e.g., `rest_https_edge` 502 storms after a failed preemption refresh), the harness logs the cell to `failed_cells` (in the run config JSON) with the exception type + repr + traceback, and continues to the next cell. The sidecar + run config are closed cleanly so the regenerator can still build a partial report from whatever cells succeeded.

## Step 4 — Phase J: Payload-parity code-review audit (FR-005c)

**STOP and read** `specs/019-m5-2-transport-tuning/contracts/m5_2-payload-parity-audit.md` end-to-end. Then:

1. Open `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py` and `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py` side-by-side.
2. Walk through each checklist item in the audit contract (chat-path parity → embed-path parity → no protocol-specific normalization).
3. Empirically measure the embed-payload byte sizes (the regression-relevant ones) via the one-off `python -c` snippet in the contract.
4. Record findings in `bench-results/m5_2-full/{run_id}.run_config.json` under the `payload_parity_audit` top-level key (the contract documents the exact JSON shape).

If any check fails: **STOP**, fix the harness, re-run Step 3 (the full sweep), then re-audit.

The audit's `no_regression_confirmed_against_pr` SHA value should be the **current HEAD of the M5.2 PR branch** at audit time. If subsequent commits land before K1, re-audit and update the SHA.

## Step 5 — Run the regenerator to produce the markdown + aggregate JSON

```bash
uv run python scripts/python/regen_bench_reports.py \
    --m5_2-sidecar bench-results/m5_2-full/{run_id}.events.jsonl.gz \
    --m5_2-run-config bench-results/m5_2-full/{run_id}.run_config.json
```

This:
1. Verifies the sidecar's SHA-256 against the run config's recorded value. Aborts on mismatch (exit code 8).
2. Streams the JSONL, computes per-cohort aggregates (warmup excluded).
3. Re-asserts the 3-tier symmetry block at report-build time. Aborts on tier (a) or tier (b) divergence (exit code 5).
4. Builds the two verdict families per cell + the Supersedes-M5.1 table.
5. Writes deterministic markdown + aggregate JSON to `docs/benchmarks/m5_2-transport-vs-tuning.{md,json}`.
6. Copies the gzipped sidecar to `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz`.

**Verify the round-trip is byte-identical** (per FR-012b):

```bash
uv run python scripts/python/regen_bench_reports.py \
    --m5_2-sidecar docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz \
    --m5_2-run-config bench-results/m5_2-full/{run_id}.run_config.json \
    --m5_2-report-out /tmp/m5_2-roundtrip
diff /tmp/m5_2-roundtrip.md docs/benchmarks/m5_2-transport-vs-tuning.md
diff /tmp/m5_2-roundtrip.json docs/benchmarks/m5_2-transport-vs-tuning.json
# Both diffs MUST be empty.
```

## Step 6 — Inspect the report

```bash
less docs/benchmarks/m5_2-transport-vs-tuning.md
```

The report's structure (per FR-014 / FR-015):

1. **Executive section** — headline finding(s) per verdict family; MockEngine read-instruction caveat; HTTPS-edge vs plain-TCP RTT delta; payload-parity audit metadata (per Phase J); smoke-gate outcome (per Step 2); client external geolocation; events sidecar SHA-256 + path.
2. **Per-cell comparison matrix** — 18 cells, both verdict families per cell, network path named on every row.
3. **Supersedes M5.1 table** — categories: `verdict_changed` / `verdict_confirmed` / `noise_resolved` / `transport_dependent` / `confirmed_unavailable`.
4. **M1 bytes-axis + M5 transport-axis preservation notes** — explicit statement that those facts are NOT superseded (per FR-014 (d)).
5. **Negative results appendix** — every `no_winner` / `comparison_unavailable` cell with supporting CIs per FR-014 (e).
6. **Field provenance** — sidecar filter / aggregate-JSON key blockquotes at each section header per FR-012b.

## Step 7 — Phase K1: "Summarize M5.2 milestone findings" commit (first narrative commit)

```bash
git add docs/benchmarks/m5_2-transport-vs-tuning.md \
        docs/benchmarks/m5_2-transport-vs-tuning.json \
        docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz
git commit -m "$(cat <<'EOF'
[Spec Kit] Summarize M5.2 milestone findings

Five-cohort head-to-head with rest_https_edge production-equivalent REST
baseline at n=250 (eu-west-1, ~52 ms plain-TCP RTT median). 18-cell
matrix across (chat_stream, embed) × (h2048, h4096, h8192) × (c=1, c=4,
c=8). Per-cell verdicts split into protocol comparison (each gRPC cohort
vs rest_https_edge) and transport-only comparison (rest_https_edge vs
rest_plain_tcp) families. Supersedes-M5.1 table records category per row.
Events JSONL sidecar SHA-256: <...>. Payload-parity audit: no regression
confirmed against PR <SHA>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Step 8 — Phase K2: "Compose ANALYSIS.md § M5.2 narrative" commit (second narrative commit)

This commit creates `ANALYSIS.md` at the repo root and folds the legacy `docs/benchmarks/summary.md` content into it (M3 § byte-for-byte equivalent), then re-points cross-references.

### 8a. Create `ANALYSIS.md`

Open a new file `ANALYSIS.md` at the repo root. Use the schema from `data-model.md::ANALYSIS.md milestone section schema`. One H2 section per milestone (M1, M2, M3, M4, M5, M5.1, M5.2) in chronological order. Each section names:
- Title.
- Status (delivered date or "(upcoming)" — M2 is a process milestone with no formal report).
- Report path(s) — `(none — process milestone)` for M2.
- Headline finding(s) in factual prose with CI-bounded numbers where applicable.
- Cross-milestone notes (e.g., "M5.2 resolves M5.1's open question on tuned-vs-default benefit on this path: see § M5.2.").

### 8b. Fold `docs/benchmarks/summary.md` into `ANALYSIS.md § M3`

Read the existing `docs/benchmarks/summary.md`. The M3-era §4 channel-tuning tables MUST be preserved in `ANALYSIS.md § M3` byte-for-byte equivalent (per FR-018). Then replace `summary.md` with a one-line redirect:

```markdown
> This summary's content has moved to [`ANALYSIS.md`](../../ANALYSIS.md) as of M5.2 (PR <SHA-or-#>, <YYYY-MM-DD>). The full milestone-by-milestone findings live there.
>
> All benchmarks ran on … (preserved methodology preamble, for external link back-compatibility).
```

### 8c. Update `docs/PLAN.md`

For each milestone's `### Status (delivered ...)` paragraph in PLAN.md, replace the embedded findings with `Findings: see [\`ANALYSIS.md\`](../ANALYSIS.md) § M<N>.`. Preserve PLAN.md's milestone goals, phase descriptions, exit criteria, and risk register intact (per FR-019).

### 8d. Audit `docs/benchmarks/m*.md` cross-references

For each per-milestone benchmark report:
```bash
grep -l "summary.md" docs/benchmarks/m*.md
```

Update every match: `[summary.md](summary.md)` → `[ANALYSIS.md § M<N>](../../ANALYSIS.md#m<n>--<title-slug>)`. Cross-references between sibling `m*.md` files remain in place per FR-020.

### 8e. Commit

```bash
git add ANALYSIS.md docs/benchmarks/summary.md docs/PLAN.md docs/benchmarks/m*.md
git commit -m "$(cat <<'EOF'
[Spec Kit] Compose ANALYSIS.md § M5.2 narrative

Cross-phase summary consolidation per FR-017. New top-level
ANALYSIS.md covers M1–M5.2 in chronological order. Folds
docs/benchmarks/summary.md content into ANALYSIS.md § M3 byte-for-byte
equivalent and replaces summary.md with a redirect (per FR-018).
Replaces docs/PLAN.md embedded milestone findings with ANALYSIS.md
pointers (per FR-019). Updates docs/benchmarks/m*.md cross-references
to point at ANALYSIS.md (per FR-020). Cites M5.2 milestone report
from commit <K1 SHA>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Step 9 — Phase K3: "Refresh README narrative for M5.2 delivery" commit (third narrative commit, last on branch)

This commit simplifies `README.md` to ≤180 lines per FR-021 and runs the FR-022 tooling-validation pass. **MUST be the last commit on the branch at `gh pr create` time.**

### 9a. Simplify README

Apply the per-section edits documented in `research.md` R-11:
- Benchmark Headlines → one paragraph (≤80 words), structural numbers only.
- Roadmap → ≤25 lines, one line per milestone + ANALYSIS.md pointer.
- Three Access Paths → preserved, trimmed redundant bullets.
- Prerequisites → validated; trim duplicates.
- Quick Start → validated end-to-end against the Makefile.
- Development Commands → validated; trim obsolete targets.
- Environment Variables → validated; remove unused vars.
- Repository Structure → re-checked; update `summary.md` references to ANALYSIS.md.
- CI → preserved; update to reference current CI gates.

Target: 285 lines → ≤180 lines. Verify with `wc -l README.md`.

### 9b. Run the FR-022 tooling-validation pass

For each Make target referenced in the README:
```bash
grep -oE 'make [a-z-]+' README.md | sort -u | while read tgt; do
    grep -q "^${tgt#make }:" Makefile || echo "MISSING: $tgt"
done
```

For each demo script referenced:
```bash
grep -oE 'demo/[a-z0-9.-]+\.(sh|py)' README.md | sort -u | while read script; do
    test -f "$script" || echo "MISSING: $script"
done
```

For each env var referenced (`PROXY_PORT`, `FRONTEND_PORT`, `FRONTEND_ADDR`, `MODEL_NAME`, `PROXY_BASE_URL`):
```bash
grep -rn "$ENV_VAR" packages/ tools/ scripts/ || echo "UNUSED: $ENV_VAR"
```

For each external dependency reference (`uv`, `make`, Modal, `xcode-select --install`): manually verify the install command is current as of the M5.2 PR date.

**Any drift discovered MUST be fixed in K3** — in the README if the README is wrong, in the consuming code / Makefile / demo script if the code is wrong. The PR description names each drift fix per FR-022.

### 9c. Commit

```bash
git add README.md [any-drift-fix-files]
git commit -m "$(cat <<'EOF'
[Spec Kit] Refresh README narrative for M5.2 delivery

Simplify README to <=180 lines per FR-021. Roadmap collapsed to
high-level phase summary linking to ANALYSIS.md. Benchmark Headlines
collapsed to a single paragraph (structural numbers only; M1
bytes-axis). FR-022 tooling-validation pass against every Make target,
demo script, env var, and external dependency reference; drift fixes:
<list>.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### 9d. Verify K3 is HEAD

```bash
git log -1 --oneline
# Expect: <K3 SHA> [Spec Kit] Refresh README narrative for M5.2 delivery
```

If any later commit lands (e.g., from an `after_implement` auto-commit hook), squash or reorder so K3 is HEAD at PR-open time per FR-024.

## Step 10 — Open the PR

```bash
gh pr create --title "M5.2 — REST transport path x gRPC tuning surface" --body "$(cat <<'EOF'
## Summary

M5.2 closes M5.1's two open questions: (a) production-equivalent REST
transport (Modal HTTPS edge alongside plain-TCP) so the operator sees
how the network path moves the verdict; (b) resolution increase from
n=100 to n=250 so default_grpc vs tuned_grpc_* deltas can be resolved
as either genuinely neutral or real-but-small.

Headline finding: <one sentence per verdict family from K1's executive
section>.

Smoke gate (FR-005a + SC-012): PASS — <timestamp from Step 2>, asserted
clauses count: <N>, per-cohort RTT medians: <copy from Step 2>.

Payload-parity audit (FR-005c + SC-013): no embed-payload-size
regression confirmed against PR <SHA-or-#> (Step 4 metadata).

Discrete narrative commits (FR-024a + SC-015):
- K1 `<SHA>`: Summarize M5.2 milestone findings.
- K2 `<SHA>`: Compose ANALYSIS.md § M5.2 narrative.
- K3 `<SHA>` (HEAD): Refresh README narrative for M5.2 delivery.

FR-022 tooling-validation drift fixes (if any): <list from Step 9b>.

## Test plan

- [ ] Smoke gate passes (`uv run python -m vllm_grpc_bench --m5_2 --m5_2-smoke`).
- [ ] Full sweep completes in <=40 min wall-clock with all 18 cells.
- [ ] Round-trip regenerator diff is empty.
- [ ] Sidecar SHA-256 in executive metadata matches `shasum -a 256` output.
- [ ] M5.1 published file unchanged (supersession is forward-only).
- [ ] All three narrative commits present in the log; K3 is HEAD.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

## Troubleshooting

### Smoke fails with tier (a) divergence

The corpus hash, MockEngine config, or Modal deploy handle is not byte-equal across cohorts. Re-check:
- The corpus loader returns deterministic content (no `random` calls without `--seed`).
- All five cohorts read from the same MockEngineConfig instance (it lives module-level in the container — single instance).
- The Modal deploy handle is captured ONCE per run, not per cohort.

### Smoke fails with tier (b) divergence

The two REST cohorts differ on something other than URL, or the two `tuned_grpc_*` cohorts differ on something other than topology. Diff the client-config digests:
```bash
python -c "
from vllm_grpc_bench.m5_2_symmetry import build_symmetry_block
block = build_symmetry_block(...)  # Reconstruct from smoke output
print(block.tier_b)
"
```

### Full sweep exceeds 40-minute budget

Per SC-007 / Edge Case: M5.2's runtime budget is operator-triggered, not part of CI. If the realised runtime exceeds 40 min, document the realised runtime in the PR description and consider:
- Are cohorts inadvertently running in parallel (they should be serial — check `m5_2_sweep.py` dispatch logic)?
- Is `--m5_2-n` accidentally larger than 250 (the cascade does NOT expand beyond 250)?

### Regenerator refuses to publish (SidecarChecksumMismatch)

The committed sidecar's SHA-256 does not match the run config's recorded value. Possible causes:
- Sidecar truncated during commit (git-LFS partial pull).
- Manual edit of the gzipped file.
- Re-running the sweep with a different seed and replacing the sidecar without updating the run config.

Investigate; either restore the original sidecar (from `bench-results/`) or re-run the full sweep + regenerator.

### The smoke gate passed but the full sweep failed with `comparison_unavailable` on >50% of cells

`server_bound` classifier is firing on most cohorts. This usually means the Modal container is CPU-saturated. Re-check the Modal instance class (should be CPU-only with sufficient vCPU); consider running at lower concurrency (c=4 max) for a diagnostic run.

### K3 isn't HEAD at `gh pr create` time

An auto-commit hook (e.g., `after_implement`) committed something after K3. Reorder:
```bash
git rebase -i HEAD~N    # N = number of commits since K3
# Move K3 to the end; mark interlopers as fixup or drop them.
```

Re-verify `git log -1 --oneline` before `gh pr create`.

### Full sweep finished but `failed_cells` lists 1+ entries

Per R-13's preemption-aware resilience, the sweep persists each cell crash to `bench-results/m5_2-full/{run_id}.run_config.json` under the `failed_cells` key. Each entry carries `path`, `hidden_size`, `concurrency`, `exception_type`, `exception_repr`, and `traceback`. Three common patterns:

1. **`ConnectError` after a preemption + a failed refresh retry**: Modal preempted mid-cell, the refresh poll found no fresh URLs within 90 s, the cell gave up. Inspect the Modal Dashboard for worker health; consider re-running the affected cells in a follow-up sweep (or re-running the full sweep — the regenerator is robust to partial data).
2. **`ConnectError` with no preemption diagnostic line**: the harness's connect-error detection didn't trigger a refresh (e.g., the refresh callable was `None` because `--m5_2-skip-deploy` mode). This is real network failure — the Modal deploy is unreachable. Re-deploy or check operator credentials.
3. **Non-connect exception**: a real code bug. The `exception_type` + `traceback` in the run config name the failure site. File a bug.

In all cases the sweep's `events_sidecar_sha256` matches the gzipped sidecar (verifiable via `shasum -a 256`), and the regenerator can build a partial M5.2 report from whatever cells succeeded. The report's negative-results appendix will surface the failed cells (currently as missing rows; future enhancement could explicitly mark them).

To recover ONLY the failed cells (instead of re-running all 18):
```bash
# Read the failed_cells list from the run config:
jq '.failed_cells[] | {path, hidden_size, concurrency}' \
    bench-results/m5_2-full/{run_id}.run_config.json

# Re-run with the surviving cells excluded (requires manual cells_override
# construction or a future --m5_2-resume-from flag).
```

### Sweep aborts BEFORE the first cell with `ConnectError`

The initial Modal handshake succeeded but the first cohort's first request can't reach Modal. Causes: Modal app already torn down; firewall/proxy on the local machine; tunnel URLs stale from a previous run. The `[m5_2] CELL FAILED 1/18 ...` line will show the full exception type + repr (verbose-error-reporting fix). Re-deploy by re-running `--m5_2` (drop `--m5_2-skip-deploy` if set).
