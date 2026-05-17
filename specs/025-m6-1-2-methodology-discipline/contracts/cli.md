# Contract: M6.1.2 CLI Surface

**Branch**: `025-m6-1-2-methodology-discipline` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Top-level mode flags (FR-026)

M6.1.2 adds two mutually-exclusive top-level mode flags. Both are added to `tools/benchmark/src/vllm_grpc_bench/__main__.py`'s argparse wiring in the same block style as M6.1.1's `--m6_1_1-diagnose` / `--m6_1_1` flags (sourced from `__main__.py:526-540`).

| Flag | Action | Description |
|------|--------|-------------|
| `--m6_1_2` | `store_true` | Run the full M6.1.2 sweep — produces the published per-cell artifact at the canonical path. Identical sweep shape to `--m6_1_2-validate` (FR-024 declares the smoke-equivalent validation sweep to be the same n=50 × full M6.1.1 6-cell matrix × 4-cohort shape); the distinction is operator-intent: `--m6_1_2` is for the PR-merge publishable artifact, `--m6_1_2-validate` is the harness-wiring confidence-builder. |
| `--m6_1_2-validate` | `store_true` | Run the smoke-equivalent validation sweep (per FR-024 + round-1 Q4 + round-1 Q5 terminology). Same n=50, same 6-cell matrix, same 4-cohort set as `--m6_1_2`. The validation sweep IS the M6.1.2 PR-merge gate (SC-002 / SC-003); the operator may run it during development cycles or in CI for incremental confidence-building. |

**Mutual exclusion** (FR-026): both `--m6_1_2` and `--m6_1_2-validate` are mutually exclusive with each other AND with every existing mode flag the project supports:

```python
m6_1_2_modes = ["--m6_1_2", "--m6_1_2-validate"]
prior_modes = [
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
# argparse mutual-exclusion: at most one of (m6_1_2_modes + prior_modes) may be set per invocation.
```

## Namespaced sub-flags (FR-027)

The 12 `--m6_1_2-*` sub-flags mirror M6.1.1's set at `__main__.py:541-596`. Defaults for the three methodology-significant inheritable parameters (`modal-region`, `base-seed`, `model`) MUST match M6.1.1's verbatim per FR-027 + round-3 Q2.

| Flag | Type | Default | Notes |
|------|------|---------|-------|
| `--m6_1_2-modal-region` | `str` | `"eu-west-1"` | **Verbatim from `__main__.py:541-543` M6.1.1 default**. Silent drift breaks FR-024's "directly comparable cell-by-cell" property. CI regression test (`test_m6_1_2_cli.py`) asserts this exact default. |
| `--m6_1_2-modal-token-env` | `str` | `"MODAL_BENCH_TOKEN"` | Mirrors `__main__.py:546-549` M6.1.1 default. Env-var name whose value is the Modal API token. |
| `--m6_1_2-modal-endpoint` | `str \| None` | `None` | Mirrors `__main__.py:551-554` M6.1.1 default. Override Modal app endpoint; `None` uses the deploy default. |
| `--m6_1_2-skip-deploy` | `store_true` | `False` | Mirrors `__main__.py:556-559` M6.1.1 default. Reuse an existing Modal deploy + handshake-dict; speeds dev cycles. |
| `--m6_1_2-base-seed` | `int` | `42` | **Verbatim from `__main__.py:561-565` M6.1.1 default**. RPC seed determinism baseline. Silent drift breaks FR-024 comparability + the smoke/warmup `seed=0` convention (see [`feedback_smoke_warmup_seed_zero`](../../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_smoke_warmup_seed_zero.md) memory — the `max(0, seed - base_seed)` clamp depends on base_seed staying at 42). CI regression test asserts this exact default. |
| `--m6_1_2-model` | `str` | `"Qwen/Qwen3-8B"` | **Verbatim from `__main__.py:567-570` M6.1.1 default**. HuggingFace model identifier. Silent drift breaks FR-024 comparability. CI regression test asserts this exact default. |
| `--m6_1_2-m6-1-1-baseline` | `str` | `"docs/benchmarks/m6_1_1-engine-cost-instrumentation.json"` | Path to M6.1.1's published JSON, consumed as a per-cell comparison reference. Differs from M6.1.1's `--m6_1_1-m6-1-baseline` (which pointed at M6.1's JSON); M6.1.2 points one milestone forward. |
| `--m6_1_2-report-out` | `str` | `"docs/benchmarks/m6_1_2-methodology-discipline.md"` | Per FR-029. Canonical published-artifact path; operator may override for dev runs. |
| `--m6_1_2-report-json-out` | `str` | `"docs/benchmarks/m6_1_2-methodology-discipline.json"` | Per FR-029. Canonical JSON companion. |
| `--m6_1_2-events-sidecar-out` | `str` | `"docs/benchmarks/m6_1_2-events.jsonl"` | Mirrors M6.1.1's events sidecar convention (`__main__.py:590-594`). |
| `--m6_1_2-allow-engine-mismatch` | `store_true` | `False` | Mirrors `__main__.py:596-600` M6.1.1 default. Bypasses the engine-version-pin check; intended for development only. |

## Default-inheritance regression test

Per FR-027 + round-3 Q2, the spec-level guard against silent drift is a CI test in `tools/benchmark/tests/test_m6_1_2_cli.py`:

```python
def test_m6_1_2_inheritable_defaults_match_m6_1_1() -> None:
    """FR-027 + round-3 Q2: --m6_1_2 defaults for modal-region, base-seed,
    model MUST match M6.1.1's verbatim. This test fails loudly if a future
    refactor accidentally drifts any of the three."""
    parser = build_parser()
    args = parser.parse_args(["--m6_1_2-validate"])
    assert args.m6_1_2_modal_region == "eu-west-1"
    assert args.m6_1_2_base_seed == 42
    assert args.m6_1_2_model == "Qwen/Qwen3-8B"
```

## Exit codes

M6.1.2 inherits M6.1.1's exit-code convention from `__main__.py`:

| Code | Meaning |
|------|---------|
| `0` | Sweep completed successfully; artifact written |
| `1` | Argparse error (mutual exclusion, unknown flag, etc.) |
| `2` | Modal deploy / handshake failure |
| `3` | Engine version mismatch and `--m6_1_2-allow-engine-mismatch` not set |
| `4` | Sweep aborted by user (Ctrl-C) |
| `5` | Sweep failed mid-run; partial artifact may exist; check stderr |

**Note**: per FR-005 + FR-005a, probe failures (single-cohort OR all-cohort) do NOT trigger a non-zero exit — the probe is methodology-supporting, not measurement-critical. The artifact is written with error blocks in `network_paths`; exit code 0.

## Dispatch wiring

M6.1.2 adds two new dispatch functions to `__main__.py` (parallel to M6.1.1's `run_m6_1_1_diagnose(...)` / `run_m6_1_1_phase_2(...)`):

```python
# In __main__.py, after argparse parsing:
if args.m6_1_2:
    return run_m6_1_2_sweep(args)  # imports from m6_1_2_sweep
if args.m6_1_2_validate:
    return run_m6_1_2_validate(args)  # imports from m6_1_2_validate
```

Both functions take the parsed `argparse.Namespace`; both return `int` (the exit code).

## Cross-references

- Plan: [`../plan.md`](../plan.md) — Technical Context.
- Data model: [`../data-model.md`](../data-model.md) — Python entity shapes.
- Spec: [`../spec.md`](../spec.md) — FR-026 / FR-027 / FR-028 + round-3 Q2 source-of-truth.
- M6.1.1 CLI precedent: `specs/023-m6-1-1-engine-cost-instrumentation/contracts/cli.md` and `tools/benchmark/src/vllm_grpc_bench/__main__.py:525-600`.
