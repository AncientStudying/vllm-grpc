# Quickstart: M6.1 — Real-Prompt-Embeds Engine Path

**Plan**: [plan.md](./plan.md)

Operator playbook for running the M6.1 sweep on Modal A10G in `eu-west-1`.
Assumes the M6.1 implementation has landed (post-`/speckit-tasks` execution).

---

## Prerequisites

```bash
# 1. Repo cloned + dependencies installed (one-time)
git clone <repo>
cd vllm-grpc
uv sync           # installs harness + frontend + proxy + torch==2.11.0 (FR-006)

# 2. Modal token configured (one-time)
modal token new   # interactive — sign in to Modal in browser

# 3. Verify M6 baseline JSON exists locally (required by FR-008 / FR-009)
test -f docs/benchmarks/m6-real-engine-mini-validation.json && echo "OK" || echo "MISSING — fetch from main branch"

# 4. Verify client torch version matches the M6.1 pin (FR-006)
python -c "import torch; print(torch.__version__)"   # expected: 2.11.0
# If mismatched, the harness will refuse to launch with a clear error message.
# Fix: `uv sync` after `git pull` (the pin lives in tools/benchmark/pyproject.toml).

# 5. On the M6.1 branch
git checkout 022-m6-1-real-prompt-embeds
git pull
```

**Why the new `torch` prerequisite**: M6.1's gRPC embed driver calls
`torch.save(tensor)` on the client to produce wire bytes that the
frontend's `decode_embeds` deserialises into a real `torch.Tensor` for
the `enable_prompt_embeds=True` engine path. Client `torch` is pinned to
**2.11.0** — the exact version vLLM 0.20.1 pulls transitively — so
client-serialised bytes are wire-compatible with server-side deserialisation
(no silent ZIP-format mismatches). See [research R-2](./research.md#r-2-torch-client-side-version-pin-policy).

---

## Step 1 — Smoke gate (~5 min)

The smoke gate validates the harness wires the real-prompt-embeds engine
path correctly, that the client's `torch` is installed and pinned, and that
the M6 baseline JSON is loadable. Cheap to re-run.

```bash
python -m vllm_grpc_bench --m6_1-smoke --m6_1-modal-region=eu-west-1
```

**What you should see on stderr**:

```
cell=embed×c=1 cohort=rest_https_edge status=ok reason=10/10 succ
cell=embed×c=1 cohort=default_grpc status=ok reason=10/10 succ
cell=embed×c=1 cohort=tuned_grpc_multiplexed status=ok reason=10/10 succ
cell=chat_stream×c=1 cohort=rest_https_edge status=ok reason=10/10 succ
cell=chat_stream×c=1 cohort=default_grpc status=ok reason=10/10 succ
cell=chat_stream×c=1 cohort=tuned_grpc_multiplexed status=ok reason=10/10 succ
note: chat_stream control-drift check is full-sweep-only (FR-012/FR-029) — will run after the n=100 sweep completes
```

**Exit code**: `0` on full success; `1` if any (cell × cohort) pair failed
(with per-pair stderr summary identifying the failing pair); `2` if a
pre-check failed (M6 baseline JSON missing/malformed/incomplete OR
torch version mismatch — distinguishes "didn't reach RPCs" from "RPCs
failed").

**Common smoke failures**:
- `M6.1 ERROR: torch is required on the client to ship prompt-embeds tensors.` — `torch` not installed in the active environment. Fix: `uv sync`.
- `M6.1 ERROR: client torch version mismatch. Expected: 2.11.0. Detected: 2.12.x.` — local environment has a newer/older torch. Fix: `uv sync` (or `pip install torch==2.11.0` if you're managing the env manually).
- `M6.1 ERROR: M6 baseline JSON missing cell entry: chat_stream c=4` — the M6 JSON file under `docs/benchmarks/` is missing or stale. Pull from `main` and re-run.
- `M6.1 ERROR: M6 baseline JSON failed to parse` — corrupted file; pull a fresh copy.
- `decode_embeds failed: prompt_embeds must have dtype float32, bfloat16, or float16; got ...` — the embed driver shipped a tensor with the wrong dtype. Should not happen with the M6.1 driver pinning dtype=fp16; if you see this, the driver code drifted from FR-028 — open an issue.
- `Modal deploy timed out` — transient Modal infrastructure issue; re-run after 1–2 min.

If smoke fails, **do not run the full sweep** until the failure is
resolved (FR-013). The full sweep is metered Modal A10G compute (~80 min);
a wiring bug that surfaces 80 min into the run is a ~$10 mistake.

---

## Step 2 — Full sweep (~75–90 min)

```bash
python -m vllm_grpc_bench --m6_1 --m6_1-modal-region=eu-west-1
```

**What you should see on stderr** (sample first few lines):

```
M6.1 sweep: 6 cells × 3 cohorts × n=100, runtime ETA ≤90 min, model=Qwen/Qwen3-8B, region=eu-west-1, torch=2.11.0, vllm=0.20.1
[1/18] embed × c=1 / rest_https_edge — 100/100 succ — 8420 ms — ETA 88m
[2/18] embed × c=1 / default_grpc — 100/100 succ — 7890 ms — ETA 85m
[3/18] embed × c=1 / tuned_grpc_multiplexed — 100/100 succ — 7400 ms — ETA 82m
[4/18] embed × c=4 / rest_https_edge — 100/100 succ — 12950 ms — ETA 77m
...
[18/18] chat_stream × c=8 / tuned_grpc_multiplexed — 99/100 succ — 24800 ms — ETA 0m
M6.1 sweep complete: verdict table at docs/benchmarks/m6_1-real-prompt-embeds.md (4 verdict_survives / 1 verdict_changed / 1 cell_incomplete)
```

**Stdout** (final line, pipeable):

```
docs/benchmarks/m6_1-real-prompt-embeds.md
```

**Exit code**: `0` on success; non-zero per [`contracts/cli.md`](./contracts/cli.md).

---

## Step 3 — Read the published reports

Two artifacts are written:

- `docs/benchmarks/m6_1-real-prompt-embeds.md` — operator-facing markdown with the verdict table.
- `docs/benchmarks/m6_1-real-prompt-embeds.json` — JSON companion (M6-superset).

**Operator's first read**:

1. Open the markdown report.
2. Read the **Executive Summary** (engine + model + region + GPU + torch version + pinned seq_len; takes one screen).
3. Read the **Supersedes M6 Under enable_prompt_embeds** verdict table — one row per cell; classification column is the headline.
4. Read the **Engine Path Differential** section — per-cell M6.1 − M6 deltas (the methodology gift for consumers picking between the two engine paths — US2).
5. Scan for `cell_incomplete` rows — those signal harness/Modal issues worth investigating.
6. Scan for `⚠ engine drift` markers in the verdict table's Drift flags column — those signal cohort engine_cost disagreement worth investigating.
7. Scan for `⚠ chat_stream drift` markers in the verdict table's Drift flags column (only appears on chat_stream cells) — those signal that infrastructure or engine drift between M6 and M6.1 may have contaminated the same-sweep embed-cell verdicts (FR-029); weight embed-cell verdicts cautiously when this flag is set.
8. Scan for `verdict_changed` rows — those are the most important findings (M6 winner direction flipped under the real prompt-embeds engine path).
9. Read the Methodology Notes' engine_version comparison line — if M6's baseline recorded `engine_version=unknown` (legacy baseline) OR the M6 baseline's version differs from M6.1's pinned version, the differential read is informational (FR-030).

---

## Step 4 — Commit and push (when ready)

Per the project's `feedback_local_lint_chain` memory, run all four CI gates
locally before pushing:

```bash
ruff check .
ruff format --check .
mypy --strict packages tools
pytest
```

If all four pass, commit:

```bash
git add docs/benchmarks/m6_1-real-prompt-embeds.md \
        docs/benchmarks/m6_1-real-prompt-embeds.json \
        docs/benchmarks/m6_1-events-*.jsonl.gz   # if events sidecar was emitted under docs/benchmarks/
git commit -m "M6.1: publish real-prompt-embeds sweep results (<date>)"
git push
```

(The harness implementation work and the published-report commits are
typically separate commits per the project convention.)

---

## Common operator scenarios

### Re-run M6.1 against a different Modal region

```bash
python -m vllm_grpc_bench --m6_1 --m6_1-modal-region=us-east-1
```

The verdict table will name the region in the executive section. RTT
distribution will reflect the operator → us-east-1 path. Cross-region
comparison is not part of M6.1's deliverable but the operator can run
multiple sweeps and diff the published reports manually.

### Re-run M6.1 with a different base seed (for variance characterisation)

```bash
python -m vllm_grpc_bench --m6_1 --m6_1-base-seed=99
```

Engine outputs (and therefore engine_cost) change; cohort comparisons and
verdicts may differ. Two seeds' verdicts agreeing strengthens confidence
that the verdict isn't seed-sensitive. Standard scientific practice — not
part of the milestone exit criterion.

### Investigate a `cell_incomplete` cell

1. Check the per-cohort `n_successes` in the markdown's Per-Cohort Detail table for the failing cell.
2. Open the events JSONL sidecar (`docs/benchmarks/m6_1-events-*.jsonl.gz`); filter for the failing cell + cohort:
   ```bash
   zcat docs/benchmarks/m6_1-events-2026-05-16.jsonl.gz | jq 'select(.cell_path=="chat_stream" and .cell_concurrency==4 and .cohort=="tuned_grpc_multiplexed" and .success==false)' | head
   ```
3. The `failure_reason` field on each failed event names the underlying cause (timeout, OOM, gRPC channel reset, `decode_embeds` failure, etc.).
4. If the failure is transient (Modal flake), re-run the sweep. If structural (model OOM, wiring bug, dtype mismatch), open an issue. Note that the differential section's row for this cell is still populated (SC-007) with whatever `n_successes` was achieved.

### Investigate a `⚠ engine drift` warning

1. Read the markdown footnote under the flagged verdict row — it surfaces per-cohort `engine_cost_mean_ms` values.
2. If REST cohort's engine_cost is materially higher than gRPC cohorts', suspect a REST-shim instrumentation bug in `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` (e.g., timing wrapper around the wrong call, or the new `input_kind="prompt_embedding_torch_b64"` path missing the engine_cost emission).
3. If gRPC cohorts disagree among themselves, suspect a cohort-specific engine code path (rare).

### Investigate a `⚠ chat_stream drift` warning (FR-029)

1. The flag indicates that at least one chat_stream cohort's M6.1 95% CI on TTFT does not overlap M6's published CI for the same (cell, cohort).
2. Possible causes: Modal regional infrastructure drift between sweep days; vLLM engine version drift between M6 baseline (possibly `engine_version=unknown`) and M6.1's pinned 0.20.1; GPU contention from another tenant on the A10G pool.
3. Treat all embed-cell verdicts on the same sweep with extra scepticism — the chat_stream cells are the same-period control; if they drift, the embed-cell verdict signal may be partially confounded by the same drift source.
4. Mitigation: re-run M6.1; if the drift persists, consider re-running M6 baseline same-period before drawing conclusions.

### Reproduce a historical M6.1 run bit-exactly

The published JSON's `run_meta` block records `git_sha`, `engine_version`,
`torch_version`, `M6_1_BASE_SEED`, `modal_region`, `seq_len`, and the
`m6_winner_deltas` snapshot. To reproduce:

```bash
git checkout <run_meta.git_sha>
# Verify torch + vllm versions match via uv.lock
uv sync
python -m vllm_grpc_bench --m6_1 \
  --m6_1-modal-region=<run_meta.modal_region> \
  --m6_1-base-seed=<run_meta.M6_1_BASE_SEED>
```

The verdict table should match bit-exactly given the same M6 baseline JSON
(snapshot in `m6_winner_deltas`) and the same engine + torch versions
(SC-006).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Smoke exits with `M6.1 ERROR: torch is required` | `torch` not installed in active env | `uv sync` |
| Smoke exits with `M6.1 ERROR: client torch version mismatch` | local env has wrong torch version | `uv sync`; if persistent, `pip install torch==2.11.0` |
| Smoke exits with `M6.1 ERROR: M6 baseline JSON ...` | M6 JSON file out of date or missing | `git pull` on main; verify `docs/benchmarks/m6-real-engine-mini-validation.json` exists; re-run smoke |
| Sweep aborts at launch with `cold_start_s: 240` | Model load slow on first cold container | Re-run; second invocation hits warm container |
| Engine init aborts with `... KV cache is needed, which is larger than the available KV cache memory` | `max_model_len` cap removed or model identifier changed to one with hidden_size > 4096 | Verify the Modal app's `AsyncEngineArgs` carries `max_model_len=2048` and `gpu_memory_utilization=0.92`; see M6 research.md R-11 (config UNCHANGED from M6 per FR-007) |
| Multiple `cell_incomplete` cells with `decode_embeds failed:` in events sidecar | gRPC embed driver shipping non-torch.save bytes (regression) | Check `m6_1_rpc_driver._build_embed_grpc_request` is using `torch.save(buf)` not `tensor.tobytes()` |
| Multiple `cell_incomplete` cells with OOM in events sidecar | Real prompt-embeds activations pushing past A10G headroom | Investigate per-cohort failure pattern; if transient, retry; if pervasive, escalate (engine config UNCHANGED from M6 per FR-007 — symptom suggests Modal A10G batch behaviour change) |
| `engine_cost_drift_warning` on every cell | Likely REST shim instrumentation regression for the new `input_kind` path | Check `rest_shim.py` emits `engine_cost.engine_forward_ms` on the `prompt_embedding_torch_b64` branch the same way it does on the `prompt_embedding_b64` branch |
| `chat_stream_control_drift_warning` on every chat_stream cell | Significant infrastructure drift between M6 sweep day and M6.1 sweep day | Re-run; if persistent, consider re-running M6 baseline same-period before publishing M6.1 conclusions |
| Verdict table all `no_winner_at_n100` and M6 was mostly `verdict_buried_by_engine` | Expected — FR-010 sub-clause: buried-by-engine M6 cells produce M6.1 `no_winner_at_n100` regardless of CI overlap | Read the differential section instead; engine_cost_mean deltas are still informative |
| Sweep wall-clock > 90 min | Per-cell budget breached | Check per-(cell × cohort) stderr lines for slow cohorts; investigate Modal region performance; the prompt-embeds engine path SHOULD be comparable in cost to M6's text-prompt path on identical hardware |
