# M5.1 Quickstart

End-to-end reproduction guide for the M5.1 REST-vs-gRPC head-to-head sweep on Modal CPU-only. Wall-clock ~30–60 minutes; one Modal CPU-instance-class hour budget.

## Prerequisites

- Local clone of this repo at `~/projects/vllm-grpc` (or wherever).
- `uv` toolchain installed and `uv sync` run at the repo root.
- Modal credentials: `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` in the env, or `~/.modal.toml` configured (run `modal token new` if neither).
- A network path with realistic RTT to Modal's chosen region. From a US-east client, `eu-west-1` produces ~52 ms median RTT (M5's measured value); other region picks are documented in `--m5_1-modal-region`.

## Step 1 — Generate a bearer token

```bash
export MODAL_BENCH_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

The token is a one-time secret. It is **never** written to the report or to any committed file. Both the harness and the Modal container read it from the env / Modal Secret of the same name.

Optional: pin a known token if you intend to re-run the sweep against the same deployed app:

```bash
export MODAL_BENCH_TOKEN="my-stable-test-token-for-rerun-only"
```

## Step 2 — Run the sweep

Single invocation:

```bash
uv run python -m vllm_grpc_bench --m5_1 --m5_1-modal-region=eu-west-1
```

The harness:
1. Deploys the dual-protocol Modal app (`vllm-grpc-bench-rest-grpc-mock`) to `eu-west-1`.
2. Probes RTT against both endpoints (gRPC plain-TCP, REST HTTPS).
3. Runs warmup cohorts (discarded).
4. Enumerates the 18 matrix cells; for each, dispatches REST → tuned-gRPC sub-cohort(s) → default-gRPC control in series.
5. Builds the comparison-verdict matrix and the supersedes-M1-time table.
6. Writes the report to `docs/benchmarks/m5_1-rest-vs-grpc.{md,json}`.
7. Tears down the Modal app.

Expected wall-clock: 30–60 minutes. Monitor with `modal app list | grep vllm-grpc-bench-rest-grpc-mock` (should be empty after a clean teardown).

## Step 3 — Inspect the report

```bash
less docs/benchmarks/m5_1-rest-vs-grpc.md
```

The report's structure (per FR-015):

1. **Executive section** — headline finding + MockEngine read-instruction caveat.
2. **Per-cell comparison matrix** — 18 cells, 2 or 3 verdict rows per cell.
3. **Supersedes M1 (time-axis) table** — per-(path × concurrency); verdict-changed rows highlighted.
4. **REST shim overhead appendix** — shim-overhead-ms aggregates per cell; warning flag if material in any cohort.
5. **M1 bytes-axis preservation note** — explicit statement that M1's structural byte-reduction claims remain in force.
6. **Negative results appendix** — every `no_winner` / `comparison_unavailable` cell with supporting CIs.

## Step 4 — Commit the report

```bash
git add docs/benchmarks/m5_1-rest-vs-grpc.{md,json}
git commit -m "$(cat <<'EOF'
[Spec Kit] Publish M5.1 report

REST vs tuned-gRPC head-to-head on real wire (eu-west-1 from US-east client,
~52 ms RTT median). 18-cell matrix across (chat_stream, embed) ×
(h2048, h4096, h8192) × (c=1, c=4, c=8). Per-cell verdicts split into
tuned-gRPC multiplexed, tuned-gRPC channels, and default-gRPC reference
rows. Supersedes-M1-time table maps each M1 time-axis cell M5.1 covers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Step 5 — Narrative refresh (FR-017 / FR-018 / FR-019, **last step before PR**)

This step is the user's explicit requirement: just before opening the PR, the maintainer updates `README.md`, `docs/benchmarks/summary.md`, and `docs/PLAN.md` to reflect M5.1's actual published numbers. **This commit MUST be the last commit on the branch at `gh pr create` time** so the PR's first reviewer-facing diff is the current narrative state.

### 5a. Read the report's executive section

Identify:
- The headline finding (whatever shape it takes: tuned-gRPC wins everywhere / REST wins on small-body chat / mixed results / etc.).
- Any `comparison_unavailable` cells (the executive section names them).
- Any cells with `low_rtt_caveat: true` (these should be empty if the eu-west-1 region produced its expected RTT).

### 5b. Update `README.md`

Edit the "Milestone 5.1 — REST vs gRPC Head-to-Head on Real Wire" section:
- Flip the "(upcoming)" suffix to "(delivered)".
- Embed the run date and the published report path.
- Embed the headline finding in the same prose style M5's "(delivered)" section uses (one paragraph, names the specific numbers, names the cells with the strongest signal).
- Update any executive bullets that previously cited M1's loopback-era REST-vs-gRPC time numbers — those bullets now cite M5.1's cross-host numbers as the canonical time-claim evidence.
- Leave M1 bytes-axis claims unchanged (89% chat response reduction, 25% embed request reduction). These are structural and not transport-condition-dependent (FR-021).
- Audit the rest of the README for stale milestone status text (M5 status correctness, milestone numbering, milestone delivery dates).

### 5c. Update `docs/benchmarks/summary.md`

Apply the same narrative refresh to the executive prose in `summary.md`. If a "REST vs gRPC" comparison block currently cites M1's c=1 numbers as the canonical time evidence, replace it with M5.1's per-(path × c) verdict pattern.

### 5d. Update `docs/PLAN.md`

Flip the "Milestone 5.1 — REST vs gRPC Head-to-Head on Real Wire (upcoming)" section to "(delivered)" with the same headline-finding embed.

### 5e. Commit and verify ordering

```bash
git add README.md docs/benchmarks/summary.md docs/PLAN.md
git commit -m "$(cat <<'EOF'
[Spec Kit] Refresh README + executive narrative for M5.1 delivery

Flips M5.1 milestone from upcoming → delivered. Replaces the loopback-era
M1 REST-vs-gRPC time comparison in the executive prose with M5.1's
cross-host numbers as the canonical time-claim evidence. M1 bytes-axis
claims remain in force unchanged (structural, not transport-dependent).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

# Verify this is HEAD:
git log -1 --oneline
# Expected: "<sha> [Spec Kit] Refresh README + executive narrative for M5.1 delivery"
```

### 5f. Handle auto-commit-hook ordering risk

If the Spec Kit `after_implement` auto-commit hook landed any subsequent changes (e.g., generated proto stubs or a tracked log file), the narrative-refresh commit may no longer be `HEAD`. Reorder:

```bash
git log -5 --oneline   # inspect order
# If the narrative commit is not HEAD, soft-reset and re-commit:
git reset --soft <hash-just-before-narrative-commit>
git commit -m "[Spec Kit] Refresh README + executive narrative for M5.1 delivery"
```

(Or use `git rebase -i` to move the narrative commit to the top, but `--soft` reset is simpler.)

## Step 6 — Open the PR

```bash
gh pr create --base main --head 018-m5-1-rest-vs-grpc \
    --title "M5.1: REST vs gRPC head-to-head on real wire" \
    --body "$(cat <<'EOF'
## Summary

Closes the cross-host REST-vs-gRPC measurement gap M5 left open. 18-cell
matrix across (chat_stream, embed) × (h2048, h4096, h8192) × (c=1, c=4,
c=8); per-cell verdicts split into tuned-gRPC multiplexed, tuned-gRPC
channels, and default-gRPC rows; Supersedes-M1-time table maps each M1
time-axis cell M5.1 covers. MockEngine continuity preserves M3-M5
methodology; real-vLLM head-to-head deferred to M7.

Published report: docs/benchmarks/m5_1-rest-vs-grpc.{md,json}.

Headline: <copy from the executive section of the report — unconditional
on outcome shape per the spec's Clarifications 2026-05-11>.

Narrative refresh: the last commit on this branch (<sha>) updates README.md,
docs/benchmarks/summary.md, and docs/PLAN.md to cite M5.1's cross-host
numbers as the canonical time-claim evidence and flips the M5.1 milestone
to "(delivered)" — per FR-017 / FR-019.

## Test plan

- [ ] `make check` passes (lint + typecheck + 274+ harness tests).
- [ ] Modal-secrets-gated smoke test (`tests/integration/test_m5_1_modal_smoke.py`) passes when run with `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET` set.
- [ ] `docs/benchmarks/m5_1-rest-vs-grpc.json` validates against the M5-additive schema (no renames, no removals).
- [ ] No bearer token value appears in any committed file (`git grep -E '[A-Za-z0-9_-]{20,}' docs/benchmarks/m5_1*` is empty of token-like strings).
- [ ] README's M5.1 milestone reads "(delivered)" at `HEAD`; M1 bytes-axis claims unchanged.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

## Common failure modes

| Symptom | Cause | Recovery |
|---------|-------|----------|
| Exit code 4 at start | `MODAL_BENCH_TOKEN`, `MODAL_TOKEN_ID`, or `MODAL_TOKEN_SECRET` missing | Set the missing env var. |
| Exit code 3 mid-deploy | Modal region unavailable, image build failure | Try a different region; check `modal logs` |
| Exit code 6 after RTT probe | Measured median RTT below 1 ms (same-region fast path) or above the validity threshold | Pick a region geographically distant from your client; verify `--m5_1-modal-region` |
| `comparison_unavailable` cells at h8192 + c=8 | Server-side serialization dominates wall-clock (`server_bound` fires) | Expected at large payloads; report's executive section names the affected cells |
| `low_rtt_caveat: true` on every cell | Network conditions changed during the run; ISP route shortened | Re-run; check `traceroute` to the Modal endpoint |
| Modal app lingers after exit code 0 | Rare Modal scheduler bug — should not happen | `modal app stop vllm-grpc-bench-rest-grpc-mock` manually |
| Token value appears in the report | Shouldn't happen — `reporter` does a regex sanity check (exit code 8) | If it does, file a bug; do not commit |
| Hook commits after the narrative-refresh commit | `after_implement` auto-commit landed | Soft-reset and re-commit (step 5f) |

## Cost expectation

Modal CPU-only instance class, ~60 minutes wall-clock = well under one CPU-instance-class-hour budget. M5 was ~10–15 min; M5.1 doubles the cohort count via the REST cohort plus the dual-sub-cohort gRPC matrix plus the per-cell default-gRPC control. The 60-minute budget (SC-007) is the M5.1 target; if a run exceeds 90 minutes, that is a regression worth investigating.
