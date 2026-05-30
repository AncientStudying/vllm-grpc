# Contract: post-refactor package layout & generic-home API (FR-001/004/005/009/010)

The harness is internal (not published to PyPI — that is `v0.1.0`), so the "contract" is the import surface that intra-package code and tests rely on. After v0.0.1:

## Invariants (the gates)

- **I1**: No module under `tools/benchmark/src/vllm_grpc_bench/` has a name matching `^m[0-9]` (SC-001).
- **I2**: No test under `tools/benchmark/tests/` has a name matching `^test_m[0-9]` (SC-001).
- **I3**: No module (src or test) contains `import …mN…` / `from …mN… import` for a milestone-prefixed module (SC-004).
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
# I3/I4: no milestone-prefixed imports / aliases anywhere
grep -rnE '(import|from).*\bm[0-9][a-z0-9_]*\b' tools/benchmark/src tools/benchmark/tests \
  | grep -vE 'm6_2-token-budget|m6_1_3-attribution|docs/benchmarks' | wc -l  # → 0
# I5: one reporter, 4-member CohortKind
ls tools/benchmark/src/vllm_grpc_bench/*reporter*.py | wc -l                # → 1
# gates
make lint typecheck test                                                   # → green
python -m vllm_grpc_bench --validate --skip-deploy                         # → completes
```
