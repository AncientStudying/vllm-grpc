# Quickstart: executing the v0.0.1 bench-harness refactor

Operator runbook for the refactor on `chore/post-m6.2-cleanup-v0.0.1`. Each step ends green under `mypy --strict` + `ruff` so the history is bisectable (FR-008). Run from repo root.

## Pre-flight

```bash
git switch chore/post-m6.2-cleanup-v0.0.1
cd tools/benchmark && make lint typecheck test   # capture the pre-refactor baseline (must be green)
cd ../..
git tag | grep -c '^milestone/'                  # → 16 (recovery net intact, FR-014)
```

## Step 1 — Create generic homes (Entity 1)  →  commit "hoist: generic type/prompt/timing/exception homes"

- Create `types.py`, `prompts.py`, `timing.py`, `exceptions.py`.
- Move live symbols in per data-model Entity 1. `CohortKind` = 4 members. `timing.py` = de-prefixed `m6_1_1_timing`. `SchemaValidationFailed` ← `m5_2_regen`.
- Nothing imports the homes yet (additive). Verify: `mypy --strict . && ruff check .`

## Step 2 — Unify the chat-prompt builder (FR-003)  →  commit "unify chat-prompt builder (BC: rest_cohort prompt bytes change)"

- Put the single seed+digest `build_chat_prompt` in `prompts.py`; repoint `rest_cohort` to it; delete the M5.2 `iteration×cell_id` builder.
- This is the isolated BC break. Verify gates.

## Step 3 — Repoint shared infra at homes  →  commit "repoint shared infra at generic homes"

- `modal_endpoint`, `rest_cohort`, `rtt_probe`, `ttft`, `symmetric_prompts`, `channel_config` (absorb `_client_kwargs`) → import from `types`/`prompts`/`timing`/`exceptions`/`channel_config`.
- Verify gates.

## Step 4 — De-prefix live modules (Entity 2)  →  one commit per module (or small batches)

- Rename `m6_2_sweep`→`sweep`, `m6_2_rpc_driver`→`rpc_driver` (absorb live helpers from `m6_rpc_driver`/`m6_1_rpc_driver`), `m6_2_validate`→`validate` (**keep canonical-path constants verbatim**, FR-019), `resume`, `crossover`, `null_anchor`, `anchor_trajectory`, `sub_probe`; `m6_1_2_network_probe`→`network_probe`; `m6_engine_cost`→`engine_cost`; fold `m6_1_seq_len`→`sweep`.
- Repoint each at the homes as you go. Verify gates after each.

## Step 5 — Consolidate the reporter (Entity 4, FR-005)  →  commit "consolidate report generators into reporter.py"

- Replace `reporter.py` content with de-prefixed `m6_2_reporter`; delete M1-era functions + their M1-era `m3_types` imports; delete the six `m*_reporter.py`.
- Verify: `ls src/vllm_grpc_bench/*reporter*.py | wc -l` → 1; gates green.

## Step 6 — Strip the CLI (Entity 6, FR-018a)  →  commit "flatten CLI: drop legacy --mN, de-prefix --m6_2-*"

- Per `contracts/cli-surface.md`: remove all `--mN` flag groups + dispatch; rename `--m6_2-*`→generic; drop the `--m6_2` selector (default invocation).
- Verify: `python -m vllm_grpc_bench --help | grep -cE '\-\-m[0-9]'` → 0; `python -m vllm_grpc_bench --validate --skip-deploy` completes.

## Step 7 — Delete legacy + rename tests (Entities 7, 8)  →  commit "delete legacy modules + rename retained tests"

- `git rm` every remaining `m[0-9]*`-prefixed src module (zero importers now) and every `test_m[0-9]*` test except `test_m6_2_*`.
- Rename `test_m6_2_*`→generic; add `test_types`/`test_prompts`/`test_timing`/`test_exceptions`.
- Verify the invariants (contracts/module-api.md):
  ```bash
  ls src/vllm_grpc_bench/ | grep -cE '^m[0-9]'        # → 0
  ls tests/ | grep -cE '^test_m[0-9]'                 # → 0
  make lint typecheck test                            # → green
  ```

## Step 8 — Docs + recoverability check (FR-015, SC-007)  →  commit "ANALYSIS.md: harness-refactor recovery note"

- Add the `ANALYSIS.md` subsection: the refactor, the BC breaks (renamed modules, unified prompt, dropped cohort members, flat CLI), and the tag recovery path.
- Sanity-check recovery + preserved pointers:
  ```bash
  git show milestone/m5.2-transport-tuning:tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py | head
  ls docs/benchmarks/m6_2-token-budget.json docs/benchmarks/m6_1_3-attribution-closure.json   # both exist
  ```

## Step 9 — PR + tag (FR-017)

```bash
git push -u origin chore/post-m6.2-cleanup-v0.0.1
gh pr create --base main --title "v0.0.1 — Bench-harness refactor" --body "…(BC-break ledger + recovery path)…"
# POST-MERGE: git switch main && git pull && git tag -a v0.0.1 -m "…" && git push origin v0.0.1
graphify update .   # re-index per constitution Development Workflow
```

## Final acceptance (maps to Success Criteria)

| Check | SC |
|---|---|
| zero `^m[0-9]` modules; homes + consolidated reporter present | SC-001 |
| module count toward ~25, tests ~35 (directional; invariants are the gate) | SC-002 |
| one reporter, one prompt builder, 4-member `CohortKind` | SC-003 |
| zero milestone-prefixed imports / no BC shims | SC-004 |
| `make lint typecheck test` green, no new suppressions | SC-005 |
| `python -m vllm_grpc_bench --validate --skip-deploy` completes | SC-006 |
| `git show milestone/m5.2…` returns legacy harness | SC-007 |
| `v0.0.1` tag + ANALYSIS.md subsection | SC-008 |
| `--help` shows zero milestone flags | SC-009 |
| canonical deliverable + baseline inputs still on disk; ANALYSIS refs resolve | SC-010 |
