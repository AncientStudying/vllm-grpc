# Contract: `cohort_set` + `cohort_omissions` artifact fields

**Branch**: `025-m6-1-2-methodology-discipline` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Purpose

Two new top-level fields on the M6.1.2 sweep artifact JSON make the cohort-set choice for a given sweep machine-readable, so downstream milestones (M6.1.3 / M6.2 / M7 / M8) and human readers can distinguish "this cohort was intentionally omitted by the milestone's design" from "this cohort failed at runtime." The split is the entire point — runtime cohort failures live in per-cell error rows, not in `cohort_omissions`. Per round-2 Q2 + FR-016.

## Wire shape

### M6.1.2's default 4-cohort sweep (no intentional omissions)

```jsonc
{
  "cohort_set": ["default_grpc", "rest_https_edge", "rest_plain_tcp", "tuned_grpc_multiplexed"]
  // `cohort_omissions` is absent (or null); readers MUST interpret absence as "no intentional omissions"
}
```

### A hypothetical downstream milestone that omits one cohort intentionally

```jsonc
{
  "cohort_set": ["default_grpc", "rest_https_edge", "tuned_grpc_multiplexed"],
  "cohort_omissions": {
    "rest_plain_tcp": "M6.2 budget reduction; cohort isolates protocol cost which is not under variation in this milestone"
  }
}
```

### A sweep at `c=1` only (tuned-pair collapse rule, FR-011)

When the entire sweep is at `c=1`, `tuned_grpc_multiplexed` collapses into `default_grpc` per FR-011. This is a STRUCTURAL collapse from the spec, not an intentional omission, so `cohort_omissions` is NOT used; the collapse is described in the sweep's `run_meta` (M6.1.1-inherited):

```jsonc
{
  "cohort_set": ["default_grpc", "rest_https_edge", "rest_plain_tcp"]
  // tuned_grpc_multiplexed is structurally collapsed via the c=1 rule, not omitted;
  // cohort_omissions stays absent
}
```

Note that the M6.1.2 smoke-equivalent validation sweep (FR-024) covers the FULL M6.1.1 6-cell matrix which includes both `c=1` cells AND `c>=2` cells, so `tuned_grpc_multiplexed` IS present in `cohort_set` for the canonical M6.1.2 validation artifact (it appears in the `c=4` and `c=8` cells even though it's collapsed at `c=1`).

## Field reference

### `cohort_set`

| Property | Value |
|----------|-------|
| Type | JSON array of strings |
| Required | Yes (every M6.1.2-or-later sweep) |
| Element type | `M6_1_2CohortKind` literal (`"rest_https_edge"`, `"rest_plain_tcp"`, `"default_grpc"`, `"tuned_grpc_multiplexed"`) |
| Ordering | Sorted alphabetically (plan-level decision per [`data-model.md`](../data-model.md) — reader-script stability across runs) |
| Empty allowed? | No — a successful sweep always runs at least one cohort |
| Cardinality | 1 to 4 elements |

**Semantics**: every cohort name that the sweep ACTUALLY RAN appears in `cohort_set`. If a cohort was supposed to run but every RPC errored (a runtime failure), it STILL appears in `cohort_set` — its failure is recorded in per-cell error rows, not in `cohort_omissions`. The whole point of the split.

### `cohort_omissions`

| Property | Value |
|----------|-------|
| Type | JSON object (or absent) |
| Required | No — absence = "no intentional omissions" (round-2 Q2 explicit) |
| Key type | `M6_1_2CohortKind` literal |
| Value type | String (one-line human-readable reason) |
| Cardinality | 0 to 3 (every key MUST NOT appear in `cohort_set`; the universe is 4 cohorts; at most 3 may be omitted while at least 1 still runs) |
| Empty object semantics | An EMPTY `{}` object vs an ABSENT field — both mean "no intentional omissions"; readers MUST tolerate both shapes |

**Invariant** (FR-016): `set(cohort_set) ∪ set(cohort_omissions.keys()) == {"rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed"}` AND `set(cohort_set) ∩ set(cohort_omissions.keys()) == {}` (every cohort appears in EXACTLY ONE of the two collections). The reporter's pre-write validation in `m6_1_2_reporter.py` enforces this. Violation raises `ValueError` BEFORE the artifact is written — failing loudly is preferable to writing a malformed artifact that downstream readers misinterpret.

**What does NOT belong in `cohort_omissions`**:
- A cohort that ran but every RPC errored (runtime failure) — record this in per-cell error rows; the cohort still appears in `cohort_set`.
- A cohort that wasn't in the milestone's iteration list because of the `c=1` tuned-pair collapse rule (FR-011) — this is a structural property described in `run_meta`, not an intentional omission.

## Strict-superset schema evolution (FR-016)

Both fields are net new on the M6.1.2 artifact. M6.1.1-vintage readers ignore unknown top-level keys without parse error. No `schema_version` bump. Same precedent as `network_paths` (FR-004), `dispatch_mode` (M6.0a FR-007).

## Use cases driving the contract

### UC-1: M6.1.3 inherits the cohort set and adds proxy-edge probes

M6.1.3's spec consumes the M6.1.2 `cohort_set`, asserts it matches the expected 4-cohort universe, and proceeds to its own probes per cohort. If M6.1.3 finds `cohort_set: ["rest_https_edge", "default_grpc"]` (someone ran a `--m6_1_2-validate --m6_1_2-skip-cohort=rest_plain_tcp --m6_1_2-skip-cohort=tuned_grpc_multiplexed` for a dev cycle), the M6.1.3 driver sees this and errors out with a clear "expected 4 cohorts, got 2" message — methodology drift is loud.

### UC-2: M6.2 elects to omit `rest_plain_tcp` for budget reasons

M6.2's `max_tokens` axis sweep is N×6 cells (where N is the axis cardinality); covering all 4 cohorts would multiply cost. Per FR-016, M6.2 may set `cohort_omissions: {"rest_plain_tcp": "M6.2 budget reduction; cohort isolates protocol cost which is not under variation in this milestone"}`. A reader of the M6.2 artifact sees the explicit reason and knows this is design, not failure.

### UC-3: A reader compares two M6.1.2 sweeps from different operators

Operator A runs `--m6_1_2-validate` from macOS (all 4 cohorts succeed, `network_paths` populated). Operator B runs `--m6_1_2-validate` from a corp-firewalled Linux box (all 4 cohorts succeed for measurement; `network_paths` records 4 `probe_timeout` errors). Both sweeps have `cohort_set: ["default_grpc", "rest_https_edge", "rest_plain_tcp", "tuned_grpc_multiplexed"]`. The reader correctly concludes: same cohort set, same measurement validity; operator B's environment lacks probe-quality topology evidence but the per-cell numbers are comparable. The `cohort_set` field's presence + sameness is the signal; the difference in `network_paths` is independent.

## Validation tests

The integration test `tools/benchmark/tests/test_m6_1_2_artifact_schema.py` exercises the invariants:

```python
def test_cohort_set_omissions_invariant() -> None:
    """FR-016: set(cohort_set) ∪ set(cohort_omissions.keys()) = canonical 4-cohort universe;
    set(cohort_set) ∩ set(cohort_omissions.keys()) = {}."""
    artifact = build_m6_1_2_artifact(cohort_omissions={"rest_plain_tcp": "test"})
    canonical = {"rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc_multiplexed"}
    assert set(artifact["cohort_set"]) | set(artifact["cohort_omissions"].keys()) == canonical
    assert set(artifact["cohort_set"]) & set(artifact["cohort_omissions"].keys()) == set()


def test_invariant_violation_raises_before_write() -> None:
    """Reporter pre-write validation: malformed (cohort_set, cohort_omissions) raises ValueError."""
    with pytest.raises(ValueError, match="cohort_set ∪ cohort_omissions"):
        build_m6_1_2_artifact(
            cohort_set=["rest_https_edge"],  # Missing 3
            cohort_omissions=None,           # Doesn't account for the missing 3
        )


def test_absent_and_empty_cohort_omissions_equivalent() -> None:
    """Round-2 Q2: absent cohort_omissions key vs empty {} — both mean no intentional omissions."""
    a = build_m6_1_2_artifact(cohort_set=ALL_4, cohort_omissions=None)
    b = build_m6_1_2_artifact(cohort_set=ALL_4, cohort_omissions={})
    assert parse_omissions(a) == parse_omissions(b) == {}
```

## Cross-references

- Plan: [`../plan.md`](../plan.md) — Technical Context.
- Data model: [`../data-model.md`](../data-model.md) — `M6_1_2CohortOmissions`, `M6_1_2SweepArtifact`.
- Spec: [`../spec.md`](../spec.md) — FR-016 + Story 2 AS#6 + round-2 Q2.
- Network paths contract: [`./network-paths.md`](./network-paths.md) — sibling top-level field with the same strict-superset evolution.
- M6.0a precedent: [`specs/024-m6-0a-concurrent-dispatch/contracts/output.md`](../../024-m6-0a-concurrent-dispatch/contracts/output.md) — the `dispatch_mode` top-level key that established the strict-superset pattern.
