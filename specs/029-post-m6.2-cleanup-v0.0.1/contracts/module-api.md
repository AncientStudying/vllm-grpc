# Contract: post-refactor package layout & generic-home API (FR-001/004/005/009/010)

The harness is internal (not published to PyPI — that is `v0.1.0`), so the "contract" is the import surface that intra-package code and tests rely on. After v0.0.1:

## Invariants (the gates)

- **I1**: No module under `tools/benchmark/src/vllm_grpc_bench/` has a name matching `^m[0-9]` (SC-001).
- **I2**: No test under `tools/benchmark/tests/` has a name matching `^test_m[0-9]` (SC-001).
- **I3**: No module (src or test) contains `import …mN…` / `from …mN… import` for a milestone-prefixed module (SC-004). **Enforced strictly at T024 (post-Phase-4).** During US1 (the **T019** checkpoint, before any legacy deletion) there is a **documented transitional carve-out**: the four Entity-1 facade homes — `types.py`, `prompts.py`, `timing.py`, `exceptions.py` — still re-export from the legacy modules that define their symbols, and the definitions only hoist in-place when those legacy sources are `git rm`'d in T020. So I3 reads "zero milestone-prefixed imports in every live module **except** those four facade homes" at T019, and "zero, no exceptions" at T024. (Functional de-prefixed modules — `sweep`, `validate`, `rpc_driver`, `network_probe`, `engine_cost`, `seq_len`, `reporter`, `__main__`, the `m6_2_*` leaves — are clean at T019, **not** carved out.) See tasks.md → Notes → "Facade-home carve-out (T019)".
- **I4**: No backward-compat alias/re-export shim of an old module name exists (SC-004) — e.g. no `m6_2_sweep = sweep` forwarders.
- **I5**: Exactly one report-generation module (`reporter.py`) and exactly one chat-prompt builder; `CohortKind` has 4 members (SC-003).

## Generic-home public symbols (stable intra-package API)

```text
vllm_grpc_bench.types     : CohortKind, COHORTS, cohorts_at_concurrency, CELLS, Cell, Path,
                            RTTRecord, EndpointTuple, RunCohort, RPCResult, NetworkPath,
                            RESTCohortRecord, RestHttpsEdgeCohortRecord, CloudProvider,
                            NetworkPathError, NetworkPathHop, CohortOmissions
vllm_grpc_bench.prompts   : DEFAULT_CHAT_MAX_TOKENS, build_chat_prompt(seed) -> str
vllm_grpc_bench.timing    : extract_grpc_timings, extract_rest_timings,
                            timing_checkpoint_to_payload, TimingCheckpoint
vllm_grpc_bench.exceptions: SchemaValidationFailed
```

(Exact exported names finalized during implementation; the contract is "these symbols resolve from these generic homes, not from any `mN` module.")

## Preserved (NOT part of the BC break — FR-019)

```text
sweep baseline-input default paths        : docs/benchmarks/m6_1_3-attribution-closure.json (+ chain)
validate canonical constants              : docs/benchmarks/m6_2-token-budget.{json,md}
validate output constants                 : docs/benchmarks/m6_2-token-budget-validate.{json,md}
published deliverable on disk             : docs/benchmarks/m6_2-token-budget.{json,md}
```

## Verification commands

```bash
# I1: zero milestone-prefixed source modules
ls tools/benchmark/src/vllm_grpc_bench/ | grep -E '^m[0-9]' | wc -l        # → 0
# I2: zero milestone-prefixed test files
ls tools/benchmark/tests/ | grep -E '^test_m[0-9]' | wc -l                 # → 0
# I3/I4: no milestone-prefixed imports / aliases. Use the ANCHORED grep so prose
# /comments (e.g. channel_config's "Hoisted from `m3_sweep`", a real T008 move;
# rest_cohort's "touching m6_1_1_timing" comment) are not counted as imports.
grep -rnE '^[[:space:]]*(from|import)[[:space:]]+[A-Za-z0-9_. ]*\bm[0-9]' \
  tools/benchmark/src tools/benchmark/tests \
  | grep -vE 'm6_2-token-budget|m6_1_3-attribution|docs/benchmarks'
#   T024 (post-Phase-4, strict): wc -l  → 0
#   T019 (US1 checkpoint): the ONLY allowed residual is the four facade homes
#   types.py / prompts.py / timing.py / exceptions.py (transitional re-exports,
#   hoisted in-place at T020). Every other live module → 0. See tasks.md Notes
#   → "Facade-home carve-out (T019)".
# I5: one reporter, 4-member CohortKind
ls tools/benchmark/src/vllm_grpc_bench/*reporter*.py | wc -l                # → 1
# gates
make lint typecheck test                                                   # → green
python -m vllm_grpc_bench --validate --skip-deploy                         # → completes
```
