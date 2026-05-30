# ADR 0006 — CLI: keep `bench`/`compare`, add a `sweep` subcommand (v0.0.1, T018)

**Status:** accepted (2026-05-30) · supersedes the literal reading of FR-018a/SC-009 "sweep is the default invocation"

## Context

The v0.0.1 bench-harness refactor (`specs/029-post-m6.2-cleanup-v0.0.1`) de-prefixes
the live `m6_2_*` family and strips the milestone CLI. `contracts/cli-surface.md` +
FR-018a/SC-009 originally specified that, after dropping the `--m3 … --m6_1_3`
milestone selectors, **the de-prefixed sweep becomes the no-arg default invocation**.

During T018 implementation this collided with facts the spec did not reconcile:

1. The repo-root **`Makefile`** (`bench`, `bench-ci`) runs
   `python -m vllm_grpc_bench --proxy-url … --native-url … --output-dir …` with **no
   subcommand** — i.e. it depends on the **M1 `bench` (proxy-vs-native) path being the
   no-arg default**. `bench-compare` uses the `compare` subcommand. These are
   **documented in README.md (lines 130-132) + CONTRIBUTING.md** as primary commands.
2. The spec itself **retains** `runner.py`/`metrics.py`/`compare.py` (Entity 3) and
   `test_runner.py`/`test_compare.py`/`test_reporter.py` (Entity 8) — the bench/compare
   infrastructure and its tests.

So "sweep is the no-arg default" and "`make bench` keeps working (no-arg = bench)" are
mutually exclusive, and the spec asked for both.

## Decision

**Keep `bench` as the no-arg default and `compare`/`compare-cross`/`compare-three-way`
as subcommands; expose the de-prefixed sweep as a new `sweep` subcommand.** The
overwhelming goal is codebase *simplification*, and the simplification is delivered by
removing the milestone scaffolding — **not** by deleting the generic, documented,
spec-retained `bench`/`compare` tooling.

Resulting CLI (`--help` shows **zero** `--m[0-9]` flags — SC-009 satisfied):

```
python -m vllm_grpc_bench                       # bench (proxy-vs-native)  — make bench / bench-ci
python -m vllm_grpc_bench compare A B           # regression compare       — make bench-compare
python -m vllm_grpc_bench sweep --n=40 …        # token-budget sweep (publish)  — make sweep
python -m vllm_grpc_bench sweep --validate …    # token-budget sweep (validate) — make sweep-validate
```

What T018 removed: all `--m3 … --m6_1_3` milestone flag groups + the ~15 `_run_mN` /
`_validate_mN` / `_build_mN` / `_normalize_*` dispatch functions + the milestone `main()`
branches (`__main__.py`: 2906 → ~205 lines). The surviving `--m6_2-*` flags were
de-prefixed and moved under the `sweep` subparser (`--m6_2-modal-region` →
`--modal-region`, `--m6_2-n` → `--n`, `--m6_2-validate` → `--validate`, …); the arg
*dests* were renamed across `validate.py` + the sweep CLI tests.

## Consequences / spec reconciliation

- **FR-018a / SC-009 / cli-surface.md** updated: "the de-prefixed sweep becomes the
  **default invocation**" → "the de-prefixed sweep is a **`sweep` subcommand**; the no-arg
  default remains the `bench` proxy-vs-native benchmark." The testable invariant stays
  "`--help` lists zero `--m[0-9]` flags."
- **Entity 3/8 retention honored** — `runner`/`metrics`/`compare` + `test_runner`/
  `test_compare`/`test_reporter` stay.
- **R4 narrowed** — `reporter.py`'s `write_cross_run_md` / `write_three_way_md` are
  **NOT** deleted in T020 (the `compare-cross` / `compare-three-way` subcommands use
  them). Only the truly-orphaned M1 writers (`write_json`/`write_csv`/`write_summary_md`
  + M4/M5/M5.1/M5.2 writers, once their legacy consumers are gone) are deleted.
- **R2 audit (`compare.py`/`ci.py`) resolved** toward **keep** — a surviving CLI path
  (`compare*` subcommands) uses `compare.py`.
- **FR-018 edit-fence widened** to permit the **`Makefile`** (added `sweep` /
  `sweep-validate` targets, kept `bench`/`bench-ci`/`bench-compare`). T030's scope grep
  is updated accordingly. README.md/CONTRIBUTING.md remain accurate for `bench*`; a
  `make sweep` doc line is a nice-to-have follow-up.
- **Legacy CLI tests pulled forward** — the 15 `test_m{3,4,5,6…}_*cli*` / smoke files
  that imported the removed `__main__` milestone helpers were deleted in T018 (a partial
  T021); the remaining legacy tests (which exercise legacy *modules*, not the CLI) stay
  until T020/T021.

BC: old `python -m vllm_grpc_bench --m6_2 …` invocations are gone; recover via the
`milestone/m6.2-*` tag. `make bench`/`bench-ci`/`bench-compare` are unchanged.
