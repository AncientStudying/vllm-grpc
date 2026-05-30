# Contract: CLI surface after de-prefix (FR-018a, SC-009)

The harness CLI is the harness's only operator-facing interface. v0.0.1 removes the
milestone CLI and de-prefixes the surviving sweep. **BC break** — recoverable via the
M6.2 tag.

> **Reconciled in T018 (ADR 0006).** The original wording ("the de-prefixed sweep becomes
> the *default* invocation") collided with the retained, README/Makefile-documented `bench`
> (proxy-vs-native) no-arg default + `compare*` subcommands (Entity 3/8). Decision: **keep
> `bench` as the no-arg default + `compare*` subcommands; the de-prefixed sweep is a
> `sweep` subcommand.** The testable invariant — *zero `--m[0-9]` flags* — is unchanged.

## Invocation

Before: `python -m vllm_grpc_bench --m6_2 --m6_2-modal-region=eu-west-1 --m6_2-n=100`
After:  `python -m vllm_grpc_bench sweep --modal-region=eu-west-1 --n=100`

The `--m6_2` selector is **dropped**; the sweep is the **`sweep` subcommand** with
de-prefixed flags. The no-arg default remains the `bench` proxy-vs-native benchmark;
`compare`/`compare-cross`/`compare-three-way` remain subcommands.

## Flag rename table (the surviving M6.2 operator flags)

| Removed flag | New flag |
|---|---|
| `--m6_2` | *(dropped — default invocation)* |
| `--m6_2-modal-region` | `--modal-region` |
| `--m6_2-modal-endpoint` | `--modal-endpoint` |
| `--m6_2-modal-token-env` | `--modal-token-env` |
| `--m6_2-model` | `--model` |
| `--m6_2-n` | `--n` |
| `--m6_2-base-seed` | `--base-seed` |
| `--m6_2-skip-deploy` | `--skip-deploy` |
| `--m6_2-allow-engine-mismatch` | `--allow-engine-mismatch` |
| `--m6_2-validate` | `--validate` |
| `--m6_2-resume` | `--resume` |
| `--m6_2-checkpoint-out` | `--checkpoint-out` |
| `--m6_2-report-out` | `--report-out` |
| `--m6_2-report-json-out` | `--report-json-out` |
| `--m6_2-events-sidecar-out` | `--events-sidecar-out` |
| `--m6_2-m6-1-3-baseline` | `--baseline` |

> Collision check: after dropping the `--mN` selectors, none of the de-prefixed names collide. If two former groups would map to the same generic flag in a future milestone, that is M7's problem, not v0.0.1's (only the M6.2 group survives here).

## Removed flag groups (deleted with their sweeps)

All flags and argparse subparsers / `args.mN` dispatch branches for: `--m3`, `--m4`, `--m5`, `--m5_1` (+ `--m5_1-*`), `--m5_2` (+ `--m5_2-*`), `--m6` (+ `--m6-*`), `--m6_1` (+ `--m6_1-*`), `--m6_1_1` (+ `--m6_1_1-*`, `--m6_1_1-diagnose`), `--m6_1_2` (+ `--m6_1_2-*`, `--m6_1_2-validate`), `--m6_1_3` (+ `--m6_1_3-*`, `--m6_1_3-diagnose-repeat`, `--m6_1_3-validate`). ~30 groups, 72 dispatch references.

## Contract assertions (testable)

1. `python -m vllm_grpc_bench --help` (and `… sweep --help`) list **zero** flags matching `--m[0-9]`.
2. No `args.m3`/`args.m4`/…/`args.m6_1_3` attribute reference remains in `__main__.py`.
3. `python -m vllm_grpc_bench sweep --validate --skip-deploy` runs the fake-backed validate smoke end-to-end (FR-013 / SC-006).
4. The `sweep` subcommand dispatches the de-prefixed sweep (`run_m6_2`); the no-arg default dispatches `bench` (`_run`); `compare*` subcommands are retained.
