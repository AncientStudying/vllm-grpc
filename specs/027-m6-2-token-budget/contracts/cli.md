# Contract: M6.2 CLI Surface

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Top-level mode flags (FR-020)

M6.2 adds two mutually-exclusive top-level mode flags. Both are added to `tools/benchmark/src/vllm_grpc_bench/__main__.py`'s argparse wiring in the same block style as M6.1.3's `--m6_1_3` / `--m6_1_3-validate` flags.

| Flag | Action | Description |
|------|--------|-------------|
| `--m6_2` | `store_true` | Run the M6.2 milestone-publish sweep — drives the full 6-point `max_tokens` axis × 4-cohort × 6-cell matrix at the round-3-pinned `n` per FR-004. Produces the canonical M6.2 artifact at `docs/benchmarks/m6_2-token-budget.{md,json}` per FR-015. **Refuses to start if `--m6_2-n` is unset** (round-3 deferral gate per FR-004). |
| `--m6_2-validate` | `store_true` | Run the smoke-equivalent validate sweep — drives the 3-point axis subset `{10, 50, 2048}` × 4-cohort × 6-cell matrix at `n=20` (hard-pinned). Produces the validate-sibling artifact at `docs/benchmarks/m6_2-token-budget-validate.{md,json}` per FR-015 + FR-001. Used as the harness-wiring confidence-builder before committing the 20-48h publish run AND as the variance-gate input for clarify round 3's publish-`n` pinning. |

**Mutual exclusion** (FR-020): both `--m6_2` and `--m6_2-validate` are mutually exclusive with each other AND with every existing mode flag the project supports:

```python
m6_2_modes = ["--m6_2", "--m6_2-validate"]
prior_modes = [
    "--m6_1_3-validate",
    "--m6_1_3",
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
# argparse mutual-exclusion: at most one of (m6_2_modes + prior_modes) may be set per invocation.
```

**Single dispatch function** (mirrors M6.1.3 + M6.1.2 pattern): both `--m6_2` and `--m6_2-validate` route to `run_m6_2(args, *, sweep_mode: Literal["publish", "validate"])` in `m6_2_validate.py`. Sweep mode is recorded in `run_meta.sweep_mode` (`"m6_2_publish"` or `"m6_2_validate"`).

## Modifier flags

| Flag | Type | Default under `--m6_2` | Default under `--m6_2-validate` | Notes |
|------|------|------------------------|----------------------------------|-------|
| `--m6_2-n` | `int \| None` | **`None` (REQUIRED — round-3 deferral)** | `20` (hard-pinned, override REJECTED) | FR-004. Per-(cell, cohort, max_tokens) sample size. Under `--m6_2`, the orchestrator REFUSES to start if `args.m6_2_n` is `None` — a future clarify round 3 closes against validate-sweep variance data and pins the value (`50` uniform, `100` uniform, or adaptive split). Under `--m6_2-validate`, the value is hard-pinned at `20`; passing `--m6_2-n=<X>` for any X != 20 under `--m6_2-validate` raises an argparse error. |

**No `--m6_2-asymmetric-prompts` flag** (FR-008 + spec round-3 Q1): the flag MUST NOT be added to the argparse parser. Symmetric prompts are on by default and the only mode shipped via CLI in M6.2. Operators wishing to run an asymmetric diagnostic must do so via a one-off script importing the `symmetric_prompts.py` shared helper directly (the helper API supports disabling symmetric mode; the gap is purely in whether M6.2 exposes a CLI entry point for it). The `run_meta.symmetric_prompts_enabled` field stays at `true` in every M6.2 artifact (forward-compatible if a future milestone introduces the flag).

**Test enforcement**: `test_m6_2_cli.py::test_asymmetric_prompts_flag_not_shipped` asserts:
```python
parser = build_parser()
with pytest.raises(SystemExit):
    parser.parse_args(["--m6_2", "--m6_2-asymmetric-prompts"])
```

**No `--m6_2-diagnose-repeat` / `--m6_2-diagnose-n` modifier flags** (M6.2 has no multi-run loop): the M6.1.3 modifier flags were for the multi-run variance characterization in M6.1.3's Story 3; M6.2's variance characterization is fold into the round-3-deferred publish `n` selection per FR-004, not into a multi-run loop. The flags MUST NOT appear in the M6.2 parser.

## Namespaced sub-flags (FR-020)

The `--m6_2-*` sub-flags mirror M6.1.3's set at `__main__.py` (and M6.1.2's before that). Defaults for the three methodology-significant inheritable parameters (`modal-region`, `base-seed`, `model`) MUST match M6.1.3's verbatim. CI regression test asserts these defaults.

| Flag | Type | Default | Notes |
|------|------|---------|-------|
| `--m6_2-modal-region` | `str` | `"eu-west-1"` | **Verbatim from M6.1.3** (which inherits M6.1.2 → M6.1.1). Silent drift breaks the cell-by-cell comparability against the M6.1.3 baseline. CI regression test (`test_m6_2_cli.py`) asserts this exact default. |
| `--m6_2-modal-token-env` | `str` | `"MODAL_BENCH_TOKEN"` | Mirrors M6.1.3 default. Env-var name whose value is the Modal API token. |
| `--m6_2-modal-endpoint` | `str \| None` | `None` | Mirrors M6.1.3 default. Override Modal app endpoint; `None` uses the deploy default. |
| `--m6_2-skip-deploy` | `store_true` | `False` | Mirrors M6.1.3 default. Reuse an existing Modal deploy + handshake-dict; speeds dev cycles + enables the CLI integration tests without Modal compute. |
| `--m6_2-base-seed` | `int` | `42` | **Verbatim from M6.1.3**. RPC seed determinism baseline. CI regression test asserts this exact default. Smoke/warmup `seed=0` convention (per [`feedback_smoke_warmup_seed_zero`](../../../.claude/projects/-Users-bsansom-projects-vllm-grpc/memory/feedback_smoke_warmup_seed_zero.md) memory) depends on `base_seed` staying at 42. |
| `--m6_2-model` | `str` | `"Qwen/Qwen3-8B"` | **Verbatim from M6.1.3**. HuggingFace model identifier. CI regression test asserts this exact default. |
| `--m6_2-m6-1-3-baseline` | `str` | `"docs/benchmarks/m6_1_3-attribution-closure.json"` | Path to M6.1.3's published JSON, consumed as the null-anchor reference at `max_tokens=10/50` per FR-013 AND as the M6.1.3-baseline-CI-half-width source for FR-031's `latency_drift_warning` threshold AND as the M6.1.3 base-verdict source for FR-016's crossover analysis. |
| `--m6_2-report-out` | `str` | Inferred per FR-015 | Operator override of the inferred markdown output path. |
| `--m6_2-report-json-out` | `str` | Inferred per FR-015 | Operator override of the inferred JSON output path. |
| `--m6_2-events-sidecar-out` | `str` | `"docs/benchmarks/m6_2-events.jsonl"` | Mirrors M6.1.3 events sidecar convention. Extended with per-block UTC timestamps + retry-attempted markers. |
| `--m6_2-allow-engine-mismatch` | `store_true` | `False` | Mirrors M6.1.3 default. Bypasses the engine-version-pin check; intended for development only. |

## Output-path inference (FR-015)

The validate/publish entry function infers the output path from the mode:

- `--m6_2-validate` → `docs/benchmarks/m6_2-token-budget-validate.{md,json}`.
- `--m6_2` → `docs/benchmarks/m6_2-token-budget.{md,json}` (canonical publish).
- Operator explicitly passing `--m6_2-report-out` or `--m6_2-report-json-out` overrides the inferred path regardless of mode.

## Default-inheritance regression test

Per FR-020 (verbatim inheritance from M6.1.3 → M6.1.2 → M6.1.1), the spec-level guard against silent drift is a CI test in `tools/benchmark/tests/test_m6_2_cli.py`:

```python
def test_m6_2_inheritable_defaults_match_m6_1_3() -> None:
    """FR-020: --m6_2 defaults for modal-region, base-seed, model MUST match
    M6.1.3's verbatim. Silent drift breaks the per-cell comparability against
    the M6.1.3 baseline."""
    parser = build_parser()
    args = parser.parse_args(["--m6_2", "--m6_2-n=50"])
    assert args.m6_2_modal_region == "eu-west-1"
    assert args.m6_2_base_seed == 42
    assert args.m6_2_model == "Qwen/Qwen3-8B"
```

## Round-3 deferral gate (FR-004)

The most operationally significant new CLI behavior. The publish-mode orchestrator MUST refuse `--m6_2` invocation if `--m6_2-n` is unset:

```python
def run_m6_2(args, *, sweep_mode):
    if sweep_mode == "publish":
        if args.m6_2_n is None:
            raise SystemExit(
                "M6.2 publish mode is BLOCKED: --m6_2-n is unset.\n"
                "Per FR-004 + spec round-2 Q1, publish-mode `n` is deferred to clarify round 3,\n"
                "which fires after the validate sweep produces measured within-cohort stddev\n"
                "at chat_stream c=1 × max_tokens=2048. Run `--m6_2-validate` first; then run\n"
                "/speckit-clarify round 3 to pin n; then re-invoke `--m6_2 --m6_2-n=<pinned>`."
            )
    elif sweep_mode == "validate":
        if args.m6_2_n is not None and args.m6_2_n != 20:
            raise SystemExit(
                f"M6.2 validate mode pins n=20 (FR-004). --m6_2-n={args.m6_2_n} is rejected."
            )
        args.m6_2_n = 20
```

**Test enforcement**: `test_m6_2_cli.py::test_publish_blocked_without_n` and `test_m6_2_cli.py::test_validate_n_hardpinned_to_20`.

## CLI invocation examples

**Validate sweep** (run this first):
```bash
python -m vllm_grpc_bench --m6_2-validate --m6_2-modal-region=eu-west-1
```
Produces `docs/benchmarks/m6_2-token-budget-validate.{md,json}` in ~2.3-2.5 h, ~$4 Modal spend.

**Publish sweep** (after clarify round 3 pins n):
```bash
python -m vllm_grpc_bench --m6_2 --m6_2-n=50 --m6_2-modal-region=eu-west-1
# OR (depending on round-3 outcome)
python -m vllm_grpc_bench --m6_2 --m6_2-n=100 --m6_2-modal-region=eu-west-1
```
Produces `docs/benchmarks/m6_2-token-budget.{md,json}` in 20-48 h, $20-40 Modal spend (depending on `n`).

**Local dev / integration test** (no Modal compute):
```bash
python -m vllm_grpc_bench --m6_2-validate --m6_2-skip-deploy
python -m vllm_grpc_bench --m6_2 --m6_2-n=50 --m6_2-skip-deploy
```
Uses a stub RPC driver that returns canned latency + retry timing; exercises the full orchestrator + reporter without Modal.

## Mutual-exclusion enforcement test

```python
@pytest.mark.parametrize("mode_a, mode_b", itertools.combinations(ALL_MODE_FLAGS, 2))
def test_mode_flags_mutually_exclusive(mode_a: str, mode_b: str) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([mode_a, mode_b])
```

where `ALL_MODE_FLAGS = m6_2_modes + prior_modes` (the full 19-flag set).
