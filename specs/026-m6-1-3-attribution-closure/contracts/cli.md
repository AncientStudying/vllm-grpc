# Contract: M6.1.3 CLI Surface

**Branch**: `026-m6-1-3-attribution-closure` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Top-level mode flags (FR-034 + round-2 Q2)

M6.1.3 adds two mutually-exclusive top-level mode flags. Both are added to `tools/benchmark/src/vllm_grpc_bench/__main__.py`'s argparse wiring in the same block style as M6.1.2's `--m6_1_2` / `--m6_1_2-validate` flags.

| Flag | Action | Description |
|------|--------|-------------|
| `--m6_1_3` | `store_true` | Run the M6.1.3 milestone-publishing sweep — defaults to `repeat=5` + `n=50` per FR-022 + FR-023 (Phase A multi-run). Produces the canonical M6.1.3 artifact at `docs/benchmarks/m6_1_3-attribution-closure.{md,json}` per FR-038. With `--m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200` modifiers, runs the Phase B n=200 power test (per FR-045) and writes to the Phase B sibling path. |
| `--m6_1_3-validate` | `store_true` | Run the smoke-equivalent validation sweep — defaults to `repeat=1` + `n=50` per FR-022 + FR-023. Produces the validate-sibling artifact at `docs/benchmarks/m6_1_3-attribution-closure-validate.{md,json}` per FR-038 + round-2 Q1. Used as the harness-wiring confidence-builder before committing the ~75 min publish run. |

**Mutual exclusion** (FR-034 + round-2 Q2): both `--m6_1_3` and `--m6_1_3-validate` are mutually exclusive with each other AND with every existing mode flag the project supports:

```python
m6_1_3_modes = ["--m6_1_3", "--m6_1_3-validate"]
prior_modes = [
    "--m6_1_2-validate",
    "--m6_1_2",
    "--m6_1_1-diagnose",
    "--m6_1_1",
    "--m6_1",
    "--m6_1-smoke",
    "--m6",
    "--m6-smoke",
    "--m5_2",
    "--m5_2-smoke",
    "--m5_1",
    "--m5_1-smoke",
    "--m5",
    "--m4",
    "--m3",
]
# argparse mutual-exclusion: at most one of (m6_1_3_modes + prior_modes) may be set per invocation.
```

**`-diagnose` token reservation** (FR-034 + round-2 Q2): the `-diagnose` token is reserved as a MODIFIER PREFIX only. There is **no top-level `--m6_1_3-diagnose` flag** — historical operators familiar with `--m6_1_1-diagnose` should use `--m6_1_3` (publish) or `--m6_1_3-validate` (wiring check) instead. M6.1.1's `--m6_1_1-diagnose` semantics stay frozen per FR-037.

## Modifier flags (FR-022 + FR-023 + FR-019)

Three modifier flags are shared between `--m6_1_3` and `--m6_1_3-validate`:

| Flag | Type | Default under `--m6_1_3` | Default under `--m6_1_3-validate` | Notes |
|------|------|--------------------------|-----------------------------------|-------|
| `--m6_1_3-diagnose-repeat` | `int` | `5` | `1` | FR-022. Multi-run loop count. `N=5` is Phase A; `N=1` with `n=200` is Phase B; `N=1` with `n=50` is validate. |
| `--m6_1_3-diagnose-n` | `int` | `50` | `50` | FR-023. Per-cohort sample size. `n=200` is Phase B; `n=50` is the M6.1.1 baseline. |
| `--m6_1_3-symmetric-prompts` | `store_true` | `False` | `False` | FR-019. Re-wires the sweep cohort-prompt assignment to use the shared `symmetric_prompts.py` helper per round-2 Q4. Operator-invoked Phase B for Story 2 if pooled-distribution H1 verdict (FR-016) confirms prompt-content drift. |

**Output-path inference** (FR-038 + round-2 Q1): the validate-mode entry function infers the output path from the mode + modifier combination per R-7:
- `--m6_1_3-validate` → `docs/benchmarks/m6_1_3-attribution-closure-validate.{md,json}`.
- `--m6_1_3` (default `repeat=5 n=50`) → `docs/benchmarks/m6_1_3-attribution-closure.{md,json}` (canonical publish).
- `--m6_1_3 --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200` → `docs/benchmarks/m6_1_3-attribution-closure-phase-b.{md,json}` (Phase B sibling).
- Operator explicitly passing `--m6_1_3-report-out` or `--m6_1_3-report-json-out` overrides the inferred path regardless of mode.

## Namespaced sub-flags (FR-035)

The 11 `--m6_1_3-*` sub-flags mirror M6.1.2's set at `__main__.py:541-596` (and M6.1.1's before that). Defaults for the three methodology-significant inheritable parameters (`modal-region`, `base-seed`, `model`) MUST match M6.1.2's verbatim per FR-036 + round-2 carry-over from M6.1.2 FR-027 round-3 Q2.

| Flag | Type | Default | Notes |
|------|------|---------|-------|
| `--m6_1_3-modal-region` | `str` | `"eu-west-1"` | **Verbatim from M6.1.2** (which inherits M6.1.1). Silent drift breaks the cell-by-cell comparability against the M6.1.1 / M6.1.2 baselines. CI regression test (`test_m6_1_3_cli.py`) asserts this exact default. |
| `--m6_1_3-modal-token-env` | `str` | `"MODAL_BENCH_TOKEN"` | Mirrors M6.1.2 default. Env-var name whose value is the Modal API token. |
| `--m6_1_3-modal-endpoint` | `str \| None` | `None` | Mirrors M6.1.2 default. Override Modal app endpoint; `None` uses the deploy default. |
| `--m6_1_3-skip-deploy` | `store_true` | `False` | Mirrors M6.1.2 default. Reuse an existing Modal deploy + handshake-dict; speeds dev cycles + enables the CLI integration tests without Modal compute. |
| `--m6_1_3-base-seed` | `int` | `42` | **Verbatim from M6.1.2**. RPC seed determinism baseline. CI regression test asserts this exact default. Smoke/warmup `seed=0` convention (per [`feedback_smoke_warmup_seed_zero`](../../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_smoke_warmup_seed_zero.md) memory) depends on `base_seed` staying at 42. |
| `--m6_1_3-model` | `str` | `"Qwen/Qwen3-8B"` | **Verbatim from M6.1.2**. HuggingFace model identifier. CI regression test asserts this exact default. |
| `--m6_1_3-m6-1-1-baseline` | `str` | `"docs/benchmarks/m6_1_1-engine-cost-instrumentation.json"` | Path to M6.1.1's published JSON, consumed as the per-cell comparison reference (M6.1.3's headline outcome is "M6.1.1's two `inconclusive` cells re-classify"). |
| `--m6_1_3-report-out` | `str` | Inferred per FR-038 + R-7 | Operator override of the inferred output path. |
| `--m6_1_3-report-json-out` | `str` | Inferred per FR-038 + R-7 | Operator override of the inferred JSON output path. |
| `--m6_1_3-events-sidecar-out` | `str` | `"docs/benchmarks/m6_1_3-events.jsonl"` | Mirrors M6.1.1 / M6.1.2 events sidecar convention. Extended with the audit fields per FR-015 + R-9. |
| `--m6_1_3-allow-engine-mismatch` | `store_true` | `False` | Mirrors M6.1.2 default. Bypasses the engine-version-pin check; intended for development only. |

## Default-inheritance regression test

Per FR-036 + round-2 carry-over, the spec-level guard against silent drift is a CI test in `tools/benchmark/tests/test_m6_1_3_cli.py`:

```python
def test_m6_1_3_inheritable_defaults_match_m6_1_2() -> None:
    """FR-036: --m6_1_3 defaults for modal-region, base-seed, model MUST match
    M6.1.2's verbatim (which matches M6.1.1's). This test fails loudly if a
    future refactor accidentally drifts any of the three."""
    parser = build_parser()
    args = parser.parse_args(["--m6_1_3-validate"])
    assert args.m6_1_3_modal_region == "eu-west-1"
    assert args.m6_1_3_base_seed == 42
    assert args.m6_1_3_model == "Qwen/Qwen3-8B"


def test_m6_1_3_modifier_defaults_per_mode() -> None:
    """FR-022 + FR-023: --m6_1_3 defaults repeat=5 / n=50; --m6_1_3-validate
    defaults repeat=1 / n=50."""
    parser = build_parser()
    args_publish = parser.parse_args(["--m6_1_3"])
    assert args_publish.m6_1_3_diagnose_repeat == 5
    assert args_publish.m6_1_3_diagnose_n == 50
    args_validate = parser.parse_args(["--m6_1_3-validate"])
    assert args_validate.m6_1_3_diagnose_repeat == 1
    assert args_validate.m6_1_3_diagnose_n == 50


def test_m6_1_3_output_path_inference_per_mode() -> None:
    """FR-038 + round-2 Q1 + R-7: validate writes to validate sibling;
    --m6_1_3 default writes to canonical; --m6_1_3 with Phase B modifiers
    writes to Phase B sibling."""
    parser = build_parser()
    args_validate = parser.parse_args(["--m6_1_3-validate"])
    assert infer_output_path(args_validate, kind="md") == \
        "docs/benchmarks/m6_1_3-attribution-closure-validate.md"
    args_publish = parser.parse_args(["--m6_1_3"])
    assert infer_output_path(args_publish, kind="md") == \
        "docs/benchmarks/m6_1_3-attribution-closure.md"
    args_phase_b = parser.parse_args([
        "--m6_1_3", "--m6_1_3-diagnose-repeat=1", "--m6_1_3-diagnose-n=200",
    ])
    assert infer_output_path(args_phase_b, kind="md") == \
        "docs/benchmarks/m6_1_3-attribution-closure-phase-b.md"
```

## Exit codes

M6.1.3 inherits M6.1.2's exit-code convention from `__main__.py`:

| Code | Meaning |
|------|---------|
| `0` | Sweep completed successfully; artifact written |
| `1` | Argparse error (mutual exclusion, unknown flag, etc.) |
| `2` | Modal deploy / handshake failure |
| `3` | Engine version mismatch and `--m6_1_3-allow-engine-mismatch` not set |
| `4` | Sweep aborted by user (Ctrl-C) |
| `5` | Sweep failed mid-run; partial artifact may exist; check stderr. Multi-run preemption per FR-028 (more than 2 preemptions in a sequence) returns 5 with a "multi-run incomplete" warning in the rendered markdown. |

**Notes**:
- The negative-value clock-anomaly assertion (FR-006) does NOT trigger a non-zero exit by itself — the sweep continues; the assertion's per-cell rate is checked against SC-013's 0.5% budget at PR-merge time, not at sweep exit.
- SC-013's 0.5% gate fires on BOTH the validate AND canonical-publish artifacts per round-3 Q5 dual-gate; PR-merge holds if either exceeds.

## Dispatch wiring

M6.1.3 adds a single dispatch function to `__main__.py` per round-2 Q2 (matches M6.1.2's pattern):

```python
# In __main__.py, after argparse parsing:
from vllm_grpc_bench.m6_1_3_validate import run_m6_1_3

if args.m6_1_3:
    return run_m6_1_3(args, sweep_mode="full")
if args.m6_1_3_validate:
    return run_m6_1_3(args, sweep_mode="validate")
```

The `run_m6_1_3(...)` function takes the parsed `argparse.Namespace` plus a keyword-only `sweep_mode: Literal["full", "validate"]`; returns `int` (the exit code). The `sweep_mode` value is recorded in `run_meta.sweep_mode` so downstream readers can distinguish PR-merge publishable artifacts from harness-wiring confidence-builder runs.

**Rationale** (matching M6.1.2 round-2 Q2 carry-over): a parallel `m6_1_3_full.py` module for the `--m6_1_3` flag would be a speculative abstraction (Constitution Principle III) since the two flags share the same sweep shape — they differ only by default modifier values and inferred output path. One entry function plus a `sweep_mode` parameter preserves the operator-visible distinction without duplicating code.

## Phase B operator workflow

The canonical workflow is the three-step sequence per FR-039:

1. **Validate** (`--m6_1_3-validate`) — single run, ~15 min, writes to validate sibling. Gates the publish run on wiring health.
2. **Publish** (`--m6_1_3`) — multi-run at `repeat=5`, ~75 min, writes to canonical publish path. Reporter emits the Phase B trigger verdict line per FR-044 (round-2 Q3 unified threshold).
3. **Phase B** (`--m6_1_3 --m6_1_3-diagnose-repeat=1 --m6_1_3-diagnose-n=200`) — single n=200 run, ~60 min, writes to Phase B sibling path. **Conditional** per FR-043 + round-3 Q3 — required only if step 2's Phase A publish run produces at least one cell carrying `inconclusive_high_variance`; otherwise operator-discretionary.

## Cross-references

- Plan: [`../plan.md`](../plan.md) — Technical Context.
- Data model: [`../data-model.md`](../data-model.md) — Python entity shapes.
- Wire vocabulary: [`./wire-vocabulary.md`](./wire-vocabulary.md) — 4 new wire keys; extractor mapping.
- Classifier: [`./classifier.md`](./classifier.md) — 7-bucket decision tree; FR-008a compound labels.
- Artifact schema: [`./artifact-schema.md`](./artifact-schema.md) — three-path publishing scheme; Phase B trigger verdict.
- Spec: [`../spec.md`](../spec.md) — FR-019, FR-022, FR-023, FR-034, FR-035, FR-036, FR-037 + round-2 Q2 + FR-038 round-2 Q1 source-of-truth.
- M6.1.2 CLI precedent: [`../../025-m6-1-2-methodology-discipline/contracts/cli.md`](../../025-m6-1-2-methodology-discipline/contracts/cli.md).
- M6.1.1 CLI precedent: `tools/benchmark/src/vllm_grpc_bench/__main__.py:525-600`.
