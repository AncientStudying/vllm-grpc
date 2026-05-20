# Contract: M6.2 CLI Surface

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Top-level mode flags (FR-020)

Two mutually-exclusive top-level mode flags added to `tools/benchmark/src/vllm_grpc_bench/__main__.py`'s argparse wiring.

| Flag | Action | Description |
|------|--------|-------------|
| `--m6_2` | `store_true` | Run the M6.2 publish sweep — full 6-point `max_tokens` axis × 4-cohort × 6-cell matrix at the round-3-pinned `n`. Produces `docs/benchmarks/m6_2-token-budget.{md,json}`. **Refuses to start if `--m6_2-n` is unset** (FR-004 round-3 deferral). |
| `--m6_2-validate` | `store_true` | Run the validate sweep — 3-point axis subset `{10, 50, 2048}` × 4-cohort × 6-cell matrix at `n=20` (hard-pinned). Produces `docs/benchmarks/m6_2-token-budget-validate.{md,json}`. Variance-gate input for the round-3 clarify cycle. |

**Mutual exclusion** (FR-020): both flags mutually exclusive with each other AND with every prior mode flag:

```python
m6_2_modes = ["--m6_2", "--m6_2-validate"]
prior_modes = [
    "--m6_1_3-validate", "--m6_1_3",
    "--m6_1_2-validate", "--m6_1_2",
    "--m6_1_1-diagnose", "--m6_1_1",
    "--m6_1", "--m6_1-smoke",
    "--m6", "--m6-smoke",
    "--m5_2", "--m5_2-smoke",
    "--m5_1", "--m5_1-smoke",
    "--m5", "--m4", "--m3",
]
```

Both `--m6_2` and `--m6_2-validate` route to `run_m6_2(args, *, sweep_mode: Literal["publish", "validate"])` in `m6_2_validate.py`. Sweep mode recorded in `run_meta.sweep_mode`.

## Modifier flag

| Flag | Type | Default under `--m6_2` | Default under `--m6_2-validate` | Notes |
|------|------|------------------------|----------------------------------|-------|
| `--m6_2-n` | `int \| None` | **`None` (REQUIRED — round-3 deferral)** | `20` (hard-pinned) | FR-004. Publish-mode value pinned in a future clarify cycle; orchestrator refuses to start if unset. Validate-mode value is hard-pinned at 20; `--m6_2-n=<X != 20>` under `--m6_2-validate` raises argparse error. |

**No `--m6_2-asymmetric-prompts` flag** (FR-008 + spec round-3 Q1). The flag MUST NOT be added to argparse. Symmetric prompts are operative-by-default via `symmetric_prompts.assign_symmetric_prompt(...)` per FR-008 round-5 amendment.

**No corpus-path CLI flags** (FR-034 + FR-035 round-5). Corpus paths are spec-pinned to:
- `tools/benchmark/corpus/chat_sharegpt_1000.json` (chat per FR-034)
- `tools/benchmark/corpus/completions_embeds_qwen3_8b/` (embed per FR-035; Phase 1 prerequisite)

The orchestrator validates the on-disk corpus SHA against the provenance file at sweep start per SC-018 (`CorpusDriftError` on mismatch).

**No `--m6_2-diagnose-repeat` / `--m6_2-diagnose-n` modifier flags** (no multi-run loop in M6.2).

**No `--m6_2-ignore-eos` flag** (the `ignore_eos=True` regime is exclusive to the FR-036 KV-pressure sub-probe; the sub-probe is auto-invoked by `--m6_2` and `--m6_2-validate` per SC-019, no CLI knob).

## Namespaced sub-flags (FR-020)

| Flag | Type | Default | Notes |
|------|------|---------|-------|
| `--m6_2-modal-region` | `str` | `"eu-west-1"` | Verbatim from M6.1.3. CI regression test asserts this. |
| `--m6_2-modal-token-env` | `str` | `"MODAL_BENCH_TOKEN"` | Verbatim from M6.1.3. |
| `--m6_2-modal-endpoint` | `str \| None` | `None` | |
| `--m6_2-skip-deploy` | `store_true` | `False` | For dev cycles + CLI integration tests without Modal compute. |
| `--m6_2-base-seed` | `int` | `42` | Verbatim from M6.1.3. Smoke/warmup `seed=0` convention depends on this. CI regression test asserts this. |
| `--m6_2-model` | `str` | `"Qwen/Qwen3-8B"` | Verbatim from M6.1.3. CI regression test asserts this. |
| `--m6_2-m6-1-3-baseline` | `str` | `"docs/benchmarks/m6_1_3-attribution-closure.json"` | Path to M6.1.3 published JSON; null-anchor reference (FR-013) + FR-031 trajectory threshold source + FR-016 crossover base-verdict source. |
| `--m6_2-report-out` | `str` | Inferred per FR-015 | Operator override of markdown output path. |
| `--m6_2-report-json-out` | `str` | Inferred per FR-015 | Operator override of JSON output path. |
| `--m6_2-events-sidecar-out` | `str` | `"docs/benchmarks/m6_2-events.jsonl"` | Sidecar JSONL with per-block UTC timestamps + retry markers + prompt_source. |
| `--m6_2-allow-engine-mismatch` | `store_true` | `False` | Bypasses engine-version-pin check; dev-only. |

## Default-inheritance regression test

```python
def test_m6_2_inheritable_defaults_match_m6_1_3() -> None:
    """FR-020: --m6_2 defaults for modal-region, base-seed, model MUST match M6.1.3's verbatim."""
    parser = build_parser()
    args = parser.parse_args(["--m6_2", "--m6_2-n=50"])
    assert args.m6_2_modal_region == "eu-west-1"
    assert args.m6_2_base_seed == 42
    assert args.m6_2_model == "Qwen/Qwen3-8B"
```

## Round-3 deferral gate (FR-004) + round-5 corpus validation gate (SC-018)

```python
def run_m6_2(args, *, sweep_mode):
    # Round-3 deferral gate
    if sweep_mode == "publish":
        if args.m6_2_n is None:
            raise SystemExit(
                "M6.2 publish BLOCKED: --m6_2-n unset. Per FR-004, publish n is gated on the round-3 "
                "clarify cycle that fires after validate-sweep variance data. Run --m6_2-validate first; "
                "then /speckit-clarify to pin n; then --m6_2 --m6_2-n=<pinned>."
            )
    elif sweep_mode == "validate":
        if args.m6_2_n is not None and args.m6_2_n != 20:
            raise SystemExit(f"M6.2 validate pins n=20. --m6_2-n={args.m6_2_n} rejected.")
        args.m6_2_n = 20

    # Round-5 corpus validation gate (SC-018)
    from vllm_grpc_bench.m6_2_prompt_source import (
        load_chat_corpus, load_embed_corpus, validate_corpus_sha_at_publish_time,
    )
    chat_corpus = load_chat_corpus()  # raises CorpusDriftError on SHA mismatch
    embed_corpus = load_embed_corpus()  # raises CorpusDriftError on SHA mismatch or missing corpus

    # Proceed to sweep orchestration ...
```

**Test enforcement**: `test_m6_2_cli.py::test_publish_blocked_without_n`, `test_m6_2_cli.py::test_validate_n_hardpinned_to_20`, `test_m6_2_cli.py::test_asymmetric_prompts_flag_not_shipped`, `test_m6_2_prompt_source.py::test_chat_corpus_sha_mismatch_raises`, `test_m6_2_prompt_source.py::test_embed_corpus_missing_raises`.

## CLI invocation examples

**Phase 1 prerequisite (one-time)**: generate the embed corpus:
```bash
python scripts/python/gen_embed_corpus_qwen3_8b.py \
    --source-corpus=tools/benchmark/corpus/chat_sharegpt_1000.json \
    --output-dir=tools/benchmark/corpus/completions_embeds_qwen3_8b/ \
    --model=Qwen/Qwen3-8B \
    --hidden-size=4096 \
    --dtype=float16
# ~10-30 min on Modal A10G or local GPU.
# Commit the resulting corpus directory.
```

**Validate sweep** (run first per FR-004 deferral):
```bash
python -m vllm_grpc_bench --m6_2-validate --m6_2-modal-region=eu-west-1
# ~2.3-2.5 h wall-clock, ~$4 Modal spend.
# Includes the KV-pressure sub-probe automatically per SC-019.
```

**Publish sweep** (after `/speckit-clarify` pins n):
```bash
python -m vllm_grpc_bench --m6_2 --m6_2-n=<ROUND_3_PINNED_N> --m6_2-modal-region=eu-west-1
# 20-48 h wall-clock, $20-$40 Modal spend (depending on n).
```

**Local dev / integration test** (no Modal compute):
```bash
python -m vllm_grpc_bench --m6_2-validate --m6_2-skip-deploy
python -m vllm_grpc_bench --m6_2 --m6_2-n=50 --m6_2-skip-deploy
```

## Mutual-exclusion enforcement test

```python
@pytest.mark.parametrize("mode_a, mode_b", itertools.combinations(ALL_MODE_FLAGS, 2))
def test_mode_flags_mutually_exclusive(mode_a, mode_b):
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([mode_a, mode_b])

ALL_MODE_FLAGS = m6_2_modes + prior_modes  # 19 flags total
```
