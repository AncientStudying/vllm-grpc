# Quickstart: M6.2 — Token-Budget Characterization

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [plan.md](./plan.md)

## Operator playbook

M6.2 is a **two-stage sweep with two methodology gates: a Phase 1 corpus prerequisite and a `/speckit-clarify` gate between validate and publish**.

- **Phase 1 prerequisite (round-5 FR-035)**: a new ShareGPT-derived embed corpus at hidden_size=4096 MUST exist and be committed before `--m6_2-validate` is invoked. One-time offline generation step (~10-30 min on a GPU).
- **`/speckit-clarify` gate (FR-004)**: a future clarify cycle pins the publish-mode `n` (and the wall-clock / Modal-spend caps) based on the validate-sweep's measured within-cohort variance at `chat_stream c=1 × max_tokens=2048`. The publish-mode orchestrator refuses to start if `--m6_2-n` is unset.

The KV-pressure sub-probe (round-5 FR-036) runs automatically in both modes per SC-019 — no separate operator step.

### Stage 0a: ShareGPT-derived embed corpus generation (~10-30 min, one-time, Phase 1 prerequisite per FR-035)

**Skip this stage if the corpus already exists** (check `tools/benchmark/corpus/completions_embeds_qwen3_8b/manifest.json`).

```bash
# 1. Generate the embed corpus at hidden_size=4096 from the ShareGPT chat corpus.
#    Runs on Modal A10G or local GPU; requires ~16 GB VRAM for Qwen3-8B fp16.
python scripts/python/gen_embed_corpus_qwen3_8b.py \
    --source-corpus=tools/benchmark/corpus/chat_sharegpt_1000.json \
    --output-dir=tools/benchmark/corpus/completions_embeds_qwen3_8b/ \
    --model=Qwen/Qwen3-8B \
    --hidden-size=4096 \
    --dtype=float16

# 2. Verify the generated corpus.
ls tools/benchmark/corpus/completions_embeds_qwen3_8b/ | wc -l   # expect 1001 (1000 .pt files + manifest.json)
python -c "import json; m=json.load(open('tools/benchmark/corpus/completions_embeds_qwen3_8b/manifest.json')); print('entries:', len(m['entries']), 'corpus_sha256:', m['corpus_sha256'][:16])"

# 3. Commit the corpus to the repo.
git add tools/benchmark/corpus/completions_embeds_qwen3_8b/
git commit -m "[M6.2 prereq] Generate ShareGPT-derived embed corpus at hidden_size=4096"
```

**The corpus is ~400-800 MB committed**; the manifest pins per-file SHAs + a top-level `corpus_sha256` so SC-018's drift validation can fire on tampering. Generation is reproducible: same ShareGPT input + same model + same RNG seed → same per-file SHAs → same top-level corpus_sha256.

### Stage 0b: Pre-sweep readiness check (~15 min, no Modal)

```bash
# 1. Confirm branch + clean tree
git status                                                    # should be clean on 027-m6-2-token-budget
git log -1                                                    # should show the spec + plan commits

# 2. Confirm M6.1.3 baseline artifact is available
ls -la docs/benchmarks/m6_1_3-attribution-closure.json        # MUST exist (FR-013 + FR-031)

# 3. Confirm Phase 1 corpus prerequisites
ls -la tools/benchmark/corpus/chat_sharegpt_1000.json         # chat corpus (existing, M5.2-vintage)
ls -la tools/benchmark/corpus/chat_sharegpt_1000.provenance.json
ls -la tools/benchmark/corpus/completions_embeds_qwen3_8b/manifest.json  # embed corpus (round-5 prereq from Stage 0a)

# 4. Local lint chain (per feedback_local_lint_chain memory)
ruff check .                                                  # must pass
ruff format --check .                                         # must pass
mypy --strict .                                               # must pass
pytest tools/benchmark/tests/test_m6_2_*.py                   # must pass after implementation lands

# 5. Confirm torch-pin gate would succeed
uv sync --frozen --all-groups                                 # macOS lockfile parity per ANALYSIS.md M6.0a

# 6. Confirm Modal token is set
echo "${MODAL_BENCH_TOKEN:?MODAL_BENCH_TOKEN env var must be set}"

# 7. Dry-run the validate CLI to confirm argparse wiring + corpus SHA validation
python -m vllm_grpc_bench --m6_2-validate --m6_2-skip-deploy  # runs against stub driver; exits within seconds; SC-018 corpus-SHA gate fires here if corpora are missing or drifted
```

If any step fails, fix BEFORE proceeding. The validate sweep is ~2.3-2.5h + ~$4 Modal spend; a CLI typo or missing baseline/corpus is cheaper to catch here.

### Stage 1: Validate sweep (~3.5-4 h wall-clock, ~$5-6 Modal spend post-T066 recalibration)

```bash
# Drive the validate sweep against Modal A10G eu-west-1.
#
# `2>&1 | tee <log>` merges stdout + stderr into the console AND a log file
# so the Phase 9 progress events (`[m6_2 SWEEP_START / TUPLE_START / BLOCK_DONE /
# ANCHOR_START / SUBPROBE_START / SWEEP_END]`) stream live to your terminal
# while a copy persists for the monitor script + post-hoc forensics. The
# monitor (`scripts/python/monitor_m6_2_sweep.py`) reads this same log.
uv run --project tools/benchmark python -m vllm_grpc_bench \
    --m6_2-validate \
    --m6_2-modal-region=eu-west-1 \
    --m6_2-modal-token-env=MODAL_BENCH_TOKEN \
    2>&1 | tee docs/benchmarks/m6_2-validate.sweep.log

# Expected: ~3.5-4 h wall-clock (2026-05-24 measured 3.57 h post-fix);
# ~$5-6 Modal spend (2026-05-24 measured $5.39). Produces:
#   docs/benchmarks/m6_2-token-budget-validate.md   (rendered report)
#   docs/benchmarks/m6_2-token-budget-validate.json (machine-readable)
#   docs/benchmarks/m6_2-events.jsonl                (per-RPC sidecar)
#   docs/benchmarks/m6_2-validate.sweep.log          (tee'd console + monitor input)
```

**Progress events** the orchestrator emits to stderr (Phase 9 / T067):

| Tag | Fires at | Key fields |
|---|---|---|
| `SWEEP_START` | sweep launch | `mode`, `n`, `axis`, `expected_blocks`, `expected_tuples`, `utc` |
| `TOPOLOGY_PROBE_START/END` | start + end | `phase=sweep_start|sweep_end` |
| `ANCHOR_START/END` | start + 4h cadence + end | `sweep_hour_mark`, `duration_s` |
| `TUPLE_START/END` | per `(cell, max_tokens)` tuple | `i=<idx>/<total>`, `cell`, `max_tokens`, `cohorts`, `elapsed_h` |
| `BLOCK_DONE` | per cohort block | `i=<idx>/<total>`, `cell`, `cohort`, `max_tokens`, `duration_s`, `wall_p50_ms`, `failed`, `retry` |
| `SUBPROBE_START/END` | sub-probe phase | `blocks`, `n`, `ignore_eos`, `duration_s` |
| `SWEEP_END` | sweep completion | `blocks_done`, `elapsed_h`, `utc` |

**Validate sweep characteristics**:
- 3-point axis subset `{10, 50, 2048}` × 4 cohorts × 6 cells = **72 measurement points** at `n=20` each = 1,440 total RPCs in the main sweep.
- **Plus the KV-pressure sub-probe (round-5 FR-036)**: 4 cohorts × 2 cell-types × 2 caps × n=20 = 320 sub-probe RPCs. Runs unconditionally per SC-019 — sub-probe is the only path to FR-017a's wall-clock-ratio inference.
- 4-hour budget per FR-024 (main sweep ~2.3-2.5 h + sub-probe ~30 min – 1 h).
- Anchor re-anchor at start + end only (sweep < 8h skips in-flight 4h marks per FR-031).
- Interior axis points (`256 / 512 / 1024`) rendered as `not_validated` in the artifact narrative per FR-001 / SC-002.
- Both null anchors (`max_tokens=10/50`) exercised so the FR-012 / SC-004 cross-milestone comparison fires twice per (cell, cohort).
- High-cap (`max_tokens=2048`) exercised in BOTH regimes: budget-table row (natural EOS, corpus prompt) AND sub-probe (forced cap, `ignore_eos=True`, corpus prompt). The wall-clock-ratio inference uses the sub-probe rows.
- The "Production latency budget" section renders the 72 measured rows + 72 `not_validated` placeholder rows.
- The "KV-cache pressure" subsection shows sub-probe-derived `wall_clock_ratio_c8_2048_over_1024` per cohort × cell-type.

**Validation checklist for the validate artifact**:

```bash
# Open the validate artifact
$EDITOR docs/benchmarks/m6_2-token-budget-validate.md

# Visually confirm:
# 1. Schema version is "m6_1_1.v1" (run_meta block).
# 2. Iteration order is "cohort_innermost_block".
# 3. iteration_discipline_verified = true.
# 4. The "Production latency budget" section renders 72 measured rows + 72 not_validated placeholders.
#    Each row carries prompt_source ∈ {synthetic_seed_derived (null anchors), corpus_sharegpt (chat interior cap),
#    synthetic_random_tensor (embed null anchors), corpus_sharegpt_embed (embed interior cap)} + measurement_regime = "natural_eos".
# 5. The "Protocol crossover threshold" section carries the axis-restricted disclaimer callout.
# 6. The "KV-cache pressure" subsection includes wall_clock_ratio_c8_2048_over_1024 for all 4 cohorts × 2 cell-types,
#    populated from the SUB-PROBE rows (sub_probe_measurement_regime = "forced_cap_ignore_eos_true").
# 7. The "Null anchor validation" subsection lists 22 cross-checkable anchor cells with PASS/WARN/FAIL verdicts
#    + 26 new-baseline anchor cells with `new_baseline_marker = true` (no M6.1.3 CI to compare against) per FR-012.
# 8. The "Anchor latency trajectory" subsection has 2 snapshots per cohort (start + end).
# 9. The "Failure summary" subsection is present (reads "no measurement-cell failures" if clean).
# 10. The "Sweep wall-clock timeline" subsection may be omitted (validate sweep < 8h per FR-032).
# 11. run_meta.chat_corpus_sha256 + chat_corpus_path + embed_corpus_sha256 + embed_corpus_path are populated (round-5 SC-018).
# 12. run_meta.sub_probe_ran = true (round-5 SC-019).

# Check the integrity_warnings list (should be empty in a clean validate sweep):
python -c "import json; print(json.load(open('docs/benchmarks/m6_2-token-budget-validate.json'))['integrity_warnings'])"
```

If the integrity_warnings list is non-empty, investigate before proceeding to Stage 2. Possible issues:
- `null_anchor_drift` → M6.1.3 baseline isn't comparable (rare; investigate engine config drift, or accept the new baseline if drift is monotonically negative post-fix per the 2026-05-24 closure note).
- `cohort_csp_mismatch` → Modal consolidated cohorts mid-sweep; rerun against fresh deploy.
- `intra_sweep_latency_drift` → unlikely in a 3-4h validate sweep but possible; rerun if it fires.
- `trajectory_insufficient_snapshots` → C1 fallback (round-8 amendment): at least one cohort has < 2 post-warmup anchor snapshots. Validate-mode start+end trajectories naturally hit this — informational only, NOT publish-blocking.
- `failure_summary_threshold` → ≥ 3 cells failed; investigate per-reason tally.

### Stage 1b: Monitoring an in-flight sweep

Phase 9 ships a re-runnable monitor at `scripts/python/monitor_m6_2_sweep.py` that combines three signals into a single status line:

1. **Sweep progress** — parses the `[m6_2 *]` events from the tee'd log (Stage 1's `docs/benchmarks/m6_2-validate.sweep.log`).
2. **Process liveness** — optionally `os.kill(pid, 0)` against the orchestrator PID.
3. **Network throughput** — `psutil.net_io_counters` → `/proc/net/dev` → `netstat -ibn` fallback chain so you can confirm Modal traffic is flowing even when no new progress event has landed in the last interval.

**One-shot status (use from cron / launchd):**

```bash
python3 scripts/python/monitor_m6_2_sweep.py \
    --log docs/benchmarks/m6_2-validate.sweep.log \
    --json-out docs/benchmarks/m6_2-token-budget-validate.json \
    --once
```

**Continuous monitor (use from a second terminal — exits when the artifact JSON lands OR the PID dies):**

```bash
# Find the orchestrator PID (look for the python child of the tee pipeline).
SWEEP_PID=$(pgrep -f "vllm_grpc_bench --m6_2-validate" | head -1)

python3 scripts/python/monitor_m6_2_sweep.py \
    --log docs/benchmarks/m6_2-validate.sweep.log \
    --json-out docs/benchmarks/m6_2-token-budget-validate.json \
    --pid "$SWEEP_PID" \
    --interval 60
```

**Sample output line** (one per `--interval`, machine-parseable):

```
[2026-05-24T15:32:00Z] elapsed=2h 17m blocks=45/66 (68%) tuple=12/18 cell=chat_stream_c4×2048 \
    recent_wall_p50=2050ms eta=1h 02m net_rate=1.84MB/s subprobe=pending alive=yes artifact=no
```

Fields:
- `elapsed` — wall-clock since `SWEEP_START`.
- `blocks=A/B (P%)` — measurement blocks done vs `expected_blocks` from the start banner.
- `tuple=C/D` — `(cell, max_tokens)` tuples completed vs `expected_tuples`.
- `cell` — current `(cell × max_tokens)` tuple being measured.
- `recent_wall_p50` — `wall_p50_ms` from the last `BLOCK_DONE` event.
- `eta` — linear extrapolation `elapsed × (expected − done) / done`. Stabilizes after the first 5-10 blocks.
- `net_rate` — sustained MB/s over the last `--interval` seconds across the chosen interface (or all if `--iface` is omitted). `—` if no platform reader is available.
- `subprobe` — `pending` → `running` → `done` as the sub-probe phase advances after the main sweep.
- `alive` — `yes` / `no` / `unknown` (when `--pid` is omitted).
- `artifact` — `yes` once `--json-out` exists AND `SWEEP_END` has been observed.

**Optional flags**:

- `--iface en0` (or `eth0`) — restrict the network-rate sample to one interface. Useful when the workstation has multiple active interfaces.
- `--once` — single status line and exit. Skips the exit-condition checks; designed for scheduling via `cron`, `launchd`, or `ScheduleWakeup`.
- `--interval 30` — increase polling frequency (default 60 s).

### Stage 2: Methodology gate — round-3 closure (CLOSED 2026-05-24)

Round-3 closure landed 2026-05-24 against the post-fix validate sweep. The publish-mode parameters are now pinned in the spec and code:

- **Publish `n=40`** (FR-004; constant `m6_2_types.M6_2_PUBLISH_N`). Validate-sweep CI half-widths at n=20 (median 1.95% @ max_tokens=50, 3.94% @ max_tokens=2048) plus `1/sqrt(2)` ≈ 29% tightening from doubling n placed n=40 below the FR-014 / SC-004 pooled-CI WARN bar at every cell.
- **Wall-clock cap ≤ 16 h** (FR-023). Validate-derived projection at n=40 is ~13.2 h; the cap carries ~20% headroom for FR-026 preemption-retry budget + FR-031 4-hour-mark anchor pulses.
- **Modal-spend cap ≤ $25** (FR-021). Validate-derived projection at n=40 is ~$20 (extrapolated from 2026-05-24 validate at $5.39 / 3.567 h = $1.51/h). Cap carries ~25% headroom.

No further clarify cycle is required before launching publish.

### Stage 3: Publish sweep (~13.2 h wall-clock, ~$20 Modal spend; capped at ≤ 16 h / ≤ $25)

```bash
# Drive the publish sweep against Modal A10G eu-west-1 at the round-3-pinned n=40.
# Same `2>&1 | tee <log>` pattern as Stage 1 so progress events stream live to
# your terminal and persist for the monitor script + post-hoc forensics.
uv run --project tools/benchmark python -m vllm_grpc_bench \
    --m6_2 \
    --m6_2-n=40 \
    --m6_2-modal-region=eu-west-1 \
    --m6_2-modal-token-env=MODAL_BENCH_TOKEN \
    2>&1 | tee docs/benchmarks/m6_2-publish.sweep.log

# Expected: ~13.2 h wall-clock; ~$20 Modal spend; produces
#   docs/benchmarks/m6_2-token-budget.md
#   docs/benchmarks/m6_2-token-budget.json
#   docs/benchmarks/m6_2-events.jsonl   (appended; the validate sweep's events stay)
#   docs/benchmarks/m6_2-publish.sweep.log (tee'd console + monitor input)
# Caps: FR-023 ≤ 16 h, FR-021 ≤ $25.
```

**Monitoring the publish sweep** (same pattern as Stage 1b, against the publish log):

```bash
# Continuous monitor in a second terminal (auto-exits on artifact-present or PID-dead):
SWEEP_PID=$(pgrep -f "vllm_grpc_bench --m6_2 " | head -1)
python3 scripts/python/monitor_m6_2_sweep.py \
    --log docs/benchmarks/m6_2-publish.sweep.log \
    --json-out docs/benchmarks/m6_2-token-budget.json \
    --pid "$SWEEP_PID" \
    --interval 60

# Or one-shot from cron every 10 minutes — append to a status log:
python3 scripts/python/monitor_m6_2_sweep.py \
    --log docs/benchmarks/m6_2-publish.sweep.log \
    --json-out docs/benchmarks/m6_2-token-budget.json \
    --once >> docs/benchmarks/m6_2-publish.monitor.log 2>&1
```

For a 13-hour publish sweep, a 60 s monitor interval gives ~780 status lines — small enough to retain. The publish sweep produces ~132 `BLOCK_DONE` events at the round-3-pinned n=40, plus 8-10 anchor blocks at the 4-h cadence per FR-031.

**Backgrounded launch** (so the terminal that started the sweep can be closed):

```bash
# nohup + & runs the sweep detached. Capture the orchestrator PID for the monitor.
nohup uv run --project tools/benchmark python -m vllm_grpc_bench \
    --m6_2 --m6_2-n=40 --m6_2-modal-region=eu-west-1 \
    > docs/benchmarks/m6_2-publish.sweep.log 2>&1 &
SWEEP_PID=$!
echo "Sweep launched: PID=$SWEEP_PID, log=docs/benchmarks/m6_2-publish.sweep.log"

# Monitor from anywhere:
python3 scripts/python/monitor_m6_2_sweep.py \
    --log docs/benchmarks/m6_2-publish.sweep.log \
    --json-out docs/benchmarks/m6_2-token-budget.json \
    --pid "$SWEEP_PID" --interval 60
```

**Publish sweep characteristics**:
- Full 6-point axis `{10, 50, 256, 512, 1024, 2048}` × 4 cohorts × 6 cells = **144 measurement points** at the round-3-pinned `n=40` each.
- **Plus the KV-pressure sub-probe (round-5 FR-036)**: 320 sub-probe RPCs (4 cohorts × 2 cell-types × 2 caps × n=20). Runs after the main sweep completes; ~30 min – 1 h additional wall-clock (< 2% of the publish budget).
- Anchor re-anchor at start + end + every 4h mark per FR-031 (~8-10 snapshots/cohort).
- `network_paths` topology probe co-fires at the same 4h cadence per FR-009 (~8-10 snapshots/cohort).
- Cohort-innermost block iteration per FR-030 (FR-032 machine-checks discipline). Sub-probe respects FR-030 within its own (cell_type, max_tokens) tuples.
- In-window retry once for transient block failures per FR-033 (applies to sub-probe blocks too).
- Three-regime prompt source per round-5 FR-034 / FR-035: null anchors = synthetic, interior caps = ShareGPT corpus, sub-probe = ShareGPT corpus + ignore_eos=True.
- All four primary sections + 6 auxiliary subsections render.

**Tunnel readiness**:
- The operator's Modal tunnel MUST stay alive across the multi-day runtime. If the tunnel rotates (typical Modal preemption behavior at long wall-clock), the FR-026 preemption-recurrence threshold (pinned at 2 per M6.1.3 FR-028) tolerates one transient recovery cleanly and aborts after a second failure.
- The orchestrator's auto-resume / partial-artifact-merge handler re-establishes the deploy handshake on tunnel rotation; the resumed block re-runs within the same `(cell, max_tokens)` tuple if the resume is prompt.

### Stage 4: Publish artifact validation

Open the publish artifact and check:

```bash
$EDITOR docs/benchmarks/m6_2-token-budget.md

# Visually confirm:
# 1. Schema version is "m6_1_1.v1".
# 2. iteration_order = "cohort_innermost_block".
# 3. iteration_discipline_verified = true (FR-032; soft warning if false).
# 4. Production latency budget renders 144 rows (no `not_validated` placeholders).
# 5. Protocol crossover threshold uses full 6-point vocabulary (no axis-restricted disclaimer).
# 6. KV-cache pressure subsection includes wall_clock_ratio + best-effort engine field.
# 7. Null anchor validation subsection lists 22 cross-checkable + 26 new-baseline anchor cells per FR-012.
# 8. Anchor latency trajectory subsection has 8-10 snapshots per cohort.
# 9. Failure summary subsection tallies any failed cells by reason.
# 10. Sweep wall-clock timeline subsection renders per (cell, max_tokens) tuple.
# 11. Method / Background section references M6.1.3 forward-cross-reference per FR-019.

# Check the integrity_warnings list (publish-blocking-eligible):
python -c "import json; print(json.load(open('docs/benchmarks/m6_2-token-budget.json'))['integrity_warnings'])"
```

If any of the four publish-blocking-eligible channels fired (`null_anchor_drift`, `failure_summary_threshold`, `cohort_csp_mismatch`, `intra_sweep_latency_drift`), the operator decides:
- **Publish anyway**: the artifact still publishes; the integrity header is informational. Recommended when the operator has reason to believe the firing is benign (e.g., the cohort_csp_mismatch fired but the operator confirms via the network_paths trajectory that the topology change is recoverable).
- **Rerun against fresh Modal deploy**: recommended when multiple channels fire OR when the drift is significant per the operator's judgment.

The soft `iteration_discipline_broken` diagnostic warning (FR-032) is informational only — it does NOT block publication but flags that the wall-clock timeline subsection deserves inspection.

### Stage 5: M6.1.3 forward-pointing annotation (FR-019)

Per FR-019, M6.1.3's published markdown receives ONE leading note line pointing forward to M6.2. The line is appended manually after the publish artifact lands:

```bash
# Open M6.1.3's markdown
$EDITOR docs/benchmarks/m6_1_3-attribution-closure.md

# At the top of the body (immediately after the title + frontmatter, before any existing content),
# add EXACTLY this line:
#
# > **Note**: M6.2's published artifact ([m6_2-token-budget.md](m6_2-token-budget.md)) extends this milestone's
# > attribution verdicts to a realistic-response-length axis (`max_tokens ∈ {10, 50, 256, 512, 1024, 2048}`).
# > See that artifact for per-cohort latency budgets at production response lengths and the protocol-crossover
# > threshold per cell.
```

M6.1.3's JSON is untouched. M6.2's markdown already carries the reciprocal "Method / Background" pointer per FR-019.

### Stage 6: Contracts/instrumentation update

Per FR-027, `contracts/instrumentation.md` (project-wide instrumentation contract) gets extended with M6.2's schema additions:

```bash
$EDITOR contracts/instrumentation.md

# Add a new "M6.2 schema additions" section documenting:
# - The four new top-level artifact keys: max_tokens_axis, protocol_crossover, kv_pressure_observation, anchor_latency_trajectory, failure_summary, integrity_warnings.
# - The four new per-row fields: max_tokens, block_start_utc, block_end_utc, retry_attempted.
# - The eight new run_meta fields: iteration_order, iteration_discipline_verified, n_per_point, validate_axis_subset, wall_clock_start_utc, wall_clock_end_utc, total_sweep_hours, modal_spend_usd_estimate.
# - The four publish-blocking-eligible sweep-level integrity-header firing rules.
# - The soft iteration_discipline_verified diagnostic.
# - The symmetric mean-in-CI crossover rule (FR-016).
# - The wall-clock-ratio inference rule (FR-017a).
# - The validate-mode rendering rules.
```

### Stage 7: PR + CI gate

```bash
# Stage the artifacts + the instrumentation contract update + the M6.1.3 forward-pointing annotation
git add docs/benchmarks/m6_2-token-budget.md docs/benchmarks/m6_2-token-budget.json
git add docs/benchmarks/m6_2-token-budget-validate.md docs/benchmarks/m6_2-token-budget-validate.json
git add docs/benchmarks/m6_2-events.jsonl
git add docs/benchmarks/m6_1_3-attribution-closure.md  # FR-019 annotation
git add contracts/instrumentation.md

# Confirm no other files changed unintentionally
git status

# Commit + push
git commit -m "[M6.2] Publish token-budget characterization artifact + M6.1.3 forward annotation"
git push origin 027-m6-2-token-budget

# Open the PR
gh pr create --title "M6.2 — token-budget characterization across max_tokens axis" --body "<see PR template>"
```

The PR's CI gate runs:
- `ruff check` + `ruff format --check` + `mypy --strict` + `pytest` (all four per `feedback_local_lint_chain` memory).
- The M6.2-specific test files: `test_m6_2_iteration_order.py`, `test_m6_2_anchor_trajectory.py`, `test_m6_2_crossover.py`, `test_m6_2_kv_pressure.py`, `test_m6_2_retry_policy.py`, `test_m6_2_null_anchor.py`, `test_m6_2_artifact_schema.py`, `test_m6_2_cli.py`, plus the two integration tests (`test_m6_2_validate_cli.py`, `test_m6_2_publish_cli.py`).
- The M6.1.x test suite (regression: ensure M6.2 hasn't broken historical re-runnability).

If any CI step fails, fix locally before pushing again.

## Common operator tasks

### Re-running the validate sweep against a different time-of-day

If the first validate sweep's integrity_warnings list contains `intra_sweep_latency_drift` (rare in a 2.3h sweep but possible), rerun at a different wall-clock to confirm the firing is exogenous rather than methodological:

```bash
# Wait until a different time-of-day band (e.g., the original ran at 14:00-17:00 UTC; rerun at 02:00-05:00 UTC)
python -m vllm_grpc_bench --m6_2-validate --m6_2-modal-region=eu-west-1
```

If the second validate sweep also fires `intra_sweep_latency_drift`, the issue is methodological (likely the M6.1.3 baseline CI half-width is unrealistically tight); raise to spec-level discussion. If only one fires, the issue is exogenous (transient network congestion in that time-of-day band) and the publish sweep should run with that in mind — start the publish sweep at a time that avoids the known-congested band.

### Re-running an interrupted publish sweep

If the operator's Modal tunnel rotates after the FR-026 preemption-recurrence threshold (>2 preemptions) and the sweep aborts:

```bash
# The orchestrator should have written a partial artifact to docs/benchmarks/m6_2-token-budget.md (incomplete).
# Inspect to see which cells completed; the partial artifact's run_meta.wall_clock_end_utc reflects when the abort fired.

# Rerun the publish sweep from scratch (no partial-resume logic at the multi-day budget per spec):
rm docs/benchmarks/m6_2-token-budget.{md,json} docs/benchmarks/m6_2-events.jsonl  # clean slate
python -m vllm_grpc_bench --m6_2 --m6_2-n=40 --m6_2-modal-region=eu-west-1
```

The single-block-level in-window retry per FR-033 handles transient errors automatically; only the multi-preemption sweep-level abort requires manual rerun.

### Investigating a specific cell's measurements

The JSON artifact's `per_cell` block is keyed by `cell_id` → `cohort` → `max_tokens` → `MeasurementPoint`:

```bash
# Get all rows for chat_stream c=8 (the headline cell for KV-pressure)
python -c "
import json
art = json.load(open('docs/benchmarks/m6_2-token-budget.json'))
import pprint
pprint.pprint(art['per_cell']['chat_stream_c8'])
"
```

Or pivot by cohort:

```bash
# Get all rows for default_grpc across all cells × max_tokens
python -c "
import json
art = json.load(open('docs/benchmarks/m6_2-token-budget.json'))
for cell, by_cohort in art['per_cell'].items():
    if 'default_grpc' in by_cohort:
        for max_tokens, row in by_cohort['default_grpc'].items():
            print(f\"{cell}/{max_tokens}: wall_p50={row.get('wall_p50_ms')}, retry={row.get('retry_attempted')}, failed={row.get('failed_reason')}\")
"
```

## Troubleshooting

### `--m6_2` invocation fails with "publish mode BLOCKED: --m6_2-n is unset"

Per FR-004 (round-3 closure 2026-05-24), the CLI gate `m6_2_sweep.gate_publish_mode_n` requires an explicit `--m6_2-n` flag at launch — no silent default — so an operator cannot start the publish sweep at an unintended n by omission. The canonical pinned value is `m6_2_types.M6_2_PUBLISH_N = 40`. Re-invoke as `--m6_2 --m6_2-n=40`. (Pass a different n only if you intend to override the pinned production value.)

### `--m6_2-asymmetric-prompts` flag not recognized

Per FR-008 + spec round-3 Q1, M6.2 does NOT ship this flag. Symmetric prompts are on by default. An asymmetric diagnostic re-run requires a one-off script importing the `symmetric_prompts.py` shared helper directly with `symmetric_mode=False`.

### `iteration_discipline_verified = false` in the publish artifact

Soft diagnostic per FR-032. Inspect the "Sweep wall-clock timeline" subsection to identify which `(cell, max_tokens)` tuple's cohort blocks were interleaved with another tuple's blocks. Likely causes: Modal preemption mid-tuple with delayed resume; orchestrator bug; manual Ctrl-C and restart. Does NOT block publication; operator decides whether to publish or rerun.

### Wall-clock-ratio inference label is `kv_pressure_not_observable` for all cohorts × cell-types

Per FR-017a, this means `wall_p50_ms(c=8, max_tokens=2048) / wall_p50_ms(c=8, max_tokens=1024) ≤ 2.2` for every cohort × cell-type pair — engine generation cost is scaling ~linearly (the expected baseline), no KV-pressure onset observed at the M6.2 regime. This is a valid finding; M8 spec authors can size KV budgets against this measurement.

If the operator expected KV-pressure onset and the inference reports `not_observable`, possible explanations: (a) the engine config has more KV-cache headroom than projected (~31K tokens estimate may be conservative); (b) the `chat_stream c=8 × max_tokens=2048` regime is below the engine's preemption threshold; (c) the measurement timing didn't catch a transient pressure event. The narrative footnote should cite the measured ratio for operator interpretation.

## Reference

- Spec: [spec.md](./spec.md)
- Plan: [plan.md](./plan.md)
- Research: [research.md](./research.md)
- Data model: [data-model.md](./data-model.md)
- CLI contract: [contracts/cli.md](./contracts/cli.md)
- Artifact schema contract: [contracts/artifact-schema.md](./contracts/artifact-schema.md)
- Iteration order + confound controls: [contracts/iteration-order.md](./contracts/iteration-order.md)
- Wire vocabulary: [contracts/wire-vocabulary.md](./contracts/wire-vocabulary.md)
- Prompt source three-regime split (round-5): [contracts/prompt-source.md](./contracts/prompt-source.md)
- M6.1.3 baseline artifact: `docs/benchmarks/m6_1_3-attribution-closure.{md,json}`
- M6.1.3 plan + contracts (inherited copy-then-refactor methodology): [`specs/026-m6-1-3-attribution-closure/plan.md`](../026-m6-1-3-attribution-closure/plan.md)
- Project-wide instrumentation contract: `contracts/instrumentation.md`
- ShareGPT chat corpus: `tools/benchmark/corpus/chat_sharegpt_1000.json` + `.provenance.json`
- ShareGPT-derived embed corpus (round-5 prereq): `tools/benchmark/corpus/completions_embeds_qwen3_8b/`
- Embed corpus generator script: `scripts/python/gen_embed_corpus_qwen3_8b.py`
