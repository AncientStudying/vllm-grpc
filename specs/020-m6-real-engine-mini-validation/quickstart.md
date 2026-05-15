# Quickstart: M6 — Real-Engine Mini-Validation

**Plan**: [plan.md](./plan.md)

Operator playbook for running the M6 sweep on Modal A10G in `eu-west-1`. Assumes the M6 implementation has landed (post-`/speckit-tasks` execution).

---

## Prerequisites

```bash
# 1. Repo cloned + dependencies installed (one-time)
git clone <repo>
cd vllm-grpc
uv sync           # installs harness + frontend + proxy

# 2. Modal token configured (one-time)
modal token new   # interactive — sign in to Modal in browser

# 3. Verify M5.2 baseline JSON exists locally (required by FR-014)
test -f docs/benchmarks/m5_2-transport-vs-tuning.json && echo "OK" || echo "MISSING — fetch from main branch"

# 4. On the M6 branch
git checkout 020-m6-real-engine-mini-validation
git pull
```

---

## Step 1 — Smoke gate (~5 min)

Smoke gate validates the harness wires real Qwen3-8B correctly under the real-engine path AND the M5.2 baseline file is loadable. Cheap to re-run.

```bash
python -m vllm_grpc_bench --m6-smoke --m6-modal-region=eu-west-1
```

**What you should see on stderr**:

```
cell=embed×c=1 cohort=rest_https_edge status=ok reason=10/10 succ
cell=embed×c=1 cohort=default_grpc status=ok reason=10/10 succ
cell=embed×c=1 cohort=tuned_grpc_multiplexed status=ok reason=10/10 succ
cell=chat_stream×c=1 cohort=rest_https_edge status=ok reason=10/10 succ
cell=chat_stream×c=1 cohort=default_grpc status=ok reason=10/10 succ
cell=chat_stream×c=1 cohort=tuned_grpc_multiplexed status=ok reason=10/10 succ
```

**Exit code**: `0` on full success; `1` if any (cell × cohort) pair failed (with per-pair stderr summary identifying the failing pair).

**Common smoke failures**:
- `M5.2 baseline missing cell entry: chat_stream c=4` — the M5.2 JSON file under `docs/benchmarks/` is missing or stale. Pull from `main` and re-run.
- `Engine load failed: CUDA out of memory` — Qwen3-8B fp16 didn't fit in A10G VRAM. Check the model identifier hasn't drifted (default: `Qwen/Qwen3-8B`).
- `Modal deploy timed out` — transient Modal infrastructure issue; re-run after 1–2 min.

If smoke fails, **do not run the full sweep** until the failure is resolved (FR-012). The full sweep is metered Modal A10G compute (~80 min); a wiring bug that surfaces 80 min into the run is a ~$10 mistake.

---

## Step 2 — Full sweep (~75–90 min)

```bash
python -m vllm_grpc_bench --m6 --m6-modal-region=eu-west-1
```

**What you should see on stderr** (sample first few lines):

```
M6 sweep: 6 cells × 3 cohorts × n=100, runtime ETA ≤90 min, model=Qwen/Qwen3-8B, region=eu-west-1
[1/18] embed × c=1 / rest_https_edge — 100/100 succ — 8230 ms — ETA 87m
[2/18] embed × c=1 / default_grpc — 100/100 succ — 7710 ms — ETA 84m
[3/18] embed × c=1 / tuned_grpc_multiplexed — 100/100 succ — 7240 ms — ETA 81m
[4/18] embed × c=4 / rest_https_edge — 100/100 succ — 12600 ms — ETA 76m
...
[18/18] chat_stream × c=8 / tuned_grpc_multiplexed — 99/100 succ — 24800 ms — ETA 0m
M6 sweep complete: verdict table at docs/benchmarks/m6-real-engine-mini-validation.md (4 verdict_survives / 1 verdict_changed / 1 cell_incomplete)
```

**Stdout** (final line, pipeable):

```
docs/benchmarks/m6-real-engine-mini-validation.md
```

**Exit code**: `0` on success; non-zero per [`contracts/cli.md`](./contracts/cli.md).

---

## Step 3 — Read the published reports

Two artifacts are written:

- `docs/benchmarks/m6-real-engine-mini-validation.md` — operator-facing markdown with the verdict table.
- `docs/benchmarks/m6-real-engine-mini-validation.json` — JSON companion (M5.2-superset).

**Operator's first read**:

1. Open the markdown report.
2. Read the **Executive Summary** (engine + model + region + GPU; takes one screen).
3. Read the **Supersedes M5.2 Under Real Engine** verdict table — one row per cell; classification column is the headline.
4. Scan for `cell_incomplete` rows — those signal harness/Modal issues worth investigating.
5. Scan for `⚠ engine drift` markers — those signal cohort engine_cost disagreement worth investigating.
6. Scan for `verdict_changed` rows — those are the most important findings (M5.2 winner direction flipped under real engine).

For M7 designers — the **Engine Cost Per RPC** table is the M6 → M7 hand-off. Per-cell engine cost (forward / TTFT / TPOT) is the cost floor against which M7 measures prompt-length scaling.

---

## Step 4 — Commit and push (when ready)

Per the project's `feedback_local_lint_chain` memory, run all four CI gates locally before pushing:

```bash
ruff check .
ruff format --check .
mypy --strict packages tools
pytest
```

If all four pass, commit:

```bash
git add docs/benchmarks/m6-real-engine-mini-validation.md \
        docs/benchmarks/m6-real-engine-mini-validation.json \
        docs/benchmarks/m6-events-*.jsonl.gz   # if events sidecar was emitted under docs/benchmarks/
git commit -m "M6: publish real-engine mini-validation results (sweep <date>)"
git push
```

(The harness implementation work and the published-report commits are typically separate commits per the project convention.)

---

## Common operator scenarios

### Re-run M6 against a different Modal region

```bash
python -m vllm_grpc_bench --m6 --m6-modal-region=us-east-1
```

The verdict table will name the region in the executive section. RTT distribution will reflect the operator → us-east-1 path. Cross-region comparison is not part of M6's deliverable but the operator can run multiple sweeps and diff the published reports manually.

### Re-run M6 with a different base seed (for variance characterisation)

```bash
python -m vllm_grpc_bench --m6 --m6-base-seed=99
```

Engine outputs (and therefore engine_cost) change; cohort comparisons and verdicts may differ. Two seeds' verdicts agreeing strengthens confidence that the verdict isn't seed-sensitive. Standard scientific practice — not part of the milestone exit criterion.

### Investigate a `cell_incomplete` cell

1. Check the per-cohort `n_successes` in the markdown's Per-Cohort Detail table for the failing cell.
2. Open the events JSONL sidecar (`docs/benchmarks/m6-events-*.jsonl.gz`); filter for the failing cell + cohort:
   ```bash
   zcat docs/benchmarks/m6-events-2026-05-14.jsonl.gz | jq 'select(.cell_path=="chat_stream" and .cell_concurrency==4 and .cohort=="tuned_grpc_multiplexed" and .success==false)' | head
   ```
3. The `failure_reason` field on each failed event names the underlying cause (timeout, OOM, gRPC channel reset, etc.).
4. If the failure is transient (Modal flake), re-run the sweep. If structural (model OOM, wiring bug), open an issue.

### Investigate a `⚠ engine drift` warning

1. Read the markdown footnote under the flagged verdict row — it surfaces per-cohort `engine_cost_mean_ms` values.
2. If REST cohort's engine_cost is materially higher than gRPC cohorts', suspect a REST-shim instrumentation bug in `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` (e.g., timing wrapper around the wrong call).
3. If gRPC cohorts disagree among themselves, suspect a cohort-specific engine code path (rare).

### Reproduce a historical M6 run bit-exactly

The published JSON's `m6_meta` block records `git_sha`, `engine_version`, `m6_base_seed`, `modal_region`, and the `m5_2_winner_deltas` snapshot. To reproduce:

```bash
git checkout <m6_meta.git_sha>
# Verify engine_version matches via uv.lock
uv sync
python -m vllm_grpc_bench --m6 \
  --m6-modal-region=<m6_meta.modal_region> \
  --m6-base-seed=<m6_meta.m6_base_seed>
```

The verdict table should match bit-exactly given the same M5.2 baseline JSON (snapshot in m5_2_winner_deltas) and the same engine version.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Smoke exits with `M5.2 baseline missing cell entry: ...` | M5.2 JSON file out of date | `git pull` on main; re-run smoke |
| Sweep aborts at launch with `cold_start_s: 240` | Model load slow on first cold container | Re-run; second invocation hits warm container |
| `engine_cost_drift_warning` on every cell | Likely REST shim instrumentation regression | File issue; check `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` for engine_cost field placement |
| Verdict table all `no_winner_at_n100` | Maybe legitimate; or maybe seed/sampling produced unusually high variance | Re-run with `--m6-base-seed=99`; if pattern repeats, the M5.2 effect is genuinely lost under real engine |
| Sweep wall-clock > 90 min | Per-cell budget breached | Check per-(cell × cohort) stderr lines for slow cohorts; investigate Modal region performance |
