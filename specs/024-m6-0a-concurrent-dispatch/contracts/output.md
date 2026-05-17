# Contract: `dispatch_mode` Manifest Field

**Plan**: [../plan.md](../plan.md) | **Spec**: [../spec.md](../spec.md)

## Purpose

Define the single new field that M6.0a adds to M6.1.1's published JSON manifest, its strict-superset semantics, and the read-side rules for downstream consumers (M6.1.1 reviewers, the M6.2 milestone, future M6.x sub-milestones, and ad-hoc operator tooling).

## Field Definition

**Key**: `dispatch_mode`
**Path**: top-level (sibling of M6.1.1's existing top-level keys like `run_id`, `started_at`, `phase_1_runs`, `phase_2_outcome`, `m6_1_baseline_pointer`, `methodology_supersedence`).
**Type**: `Literal["sequential", "concurrent"]` — a single string with exactly two valid values.
**Value emitted by M6.0a's corrected harness**: `"concurrent"` (unconditional after PR-1 lands).

## Schema-Evolution Semantics

Per FR-007 (Session 1 Q2 of the spec): `dispatch_mode` is a **strict-superset addition** to M6.1.1's manifest. This means:

1. **No schema-version bump**. M6.1.1's `schema_version` field (e.g., `"m6_1_1.v1"`) stays at its current value; the new field is purely additive.
2. **Pre-existing readers ignore the unknown field**. Any M6.1.1-aware reader written before M6.0a (including a hypothetical M6.2 consumer drafted against M6.1.1's pre-M6.0a schema) MUST continue to parse the manifest correctly, treating `dispatch_mode` as if it were absent.
3. **Absent-key default = `"sequential"`**. The 2026-05-16 audit baseline (`docs/benchmarks/m6_1_1-audit-2026-05-16-seq-dispatch.md`, committed at `b63947a`) did not emit the field — the harness at that time did not yet know about M6.0a. The audit baseline's JSON companion does not even exist (the run crashed during JSON serialisation due to the tuple-key bug fixed at `14a9a0c`); only its markdown survives. But the **rule for readers** is: if `dispatch_mode` is absent in any M6.1.1 manifest, interpret it as `"sequential"`.

## Reader Logic

The canonical read-side check is:

```python
def get_dispatch_mode(manifest: dict[str, Any]) -> Literal["sequential", "concurrent"]:
    """Read the dispatch_mode field with the M6.0a backward-compat rule.

    Absent key → "sequential" (pre-M6.0a manifests).
    Present key → the literal value ("concurrent" for post-M6.0a-corrected runs;
    "sequential" is reserved for the absent-key case and SHOULD NOT be emitted by
    any post-M6.0a manifest).
    """
    value = manifest.get("dispatch_mode")
    if value is None:
        return "sequential"
    if value not in ("sequential", "concurrent"):
        raise ValueError(f"unrecognised dispatch_mode: {value!r}")
    return value
```

## Emission Rules

The M6.0a-corrected harness MUST:

1. **Emit `dispatch_mode: "concurrent"`** on every manifest written by `m6_1_1_reporter._sanitize_for_json`'s downstream consumers (i.e., every JSON file written by `--m6_1_1-diagnose` or `--m6_1_1` after PR-1 lands).
2. **NOT emit `dispatch_mode: "sequential"`** under any condition. The string `"sequential"` is reserved exclusively for the read-side default interpretation of absent-key (pre-M6.0a) manifests. Emitting it from a post-M6.0a harness would imply the corrected harness can produce sequential dispatch — it cannot (FR-005, no parallel-fork code path).
3. **Place the field at the top level** of the manifest, sibling to existing top-level keys. The field MUST NOT be nested inside `run_meta`, `phase_1_runs`, or any other sub-object — its strict-superset semantics depend on it being at a stable, easily-discoverable position.
4. **Preserve all existing top-level keys** verbatim — no renaming, no reordering, no removal. M6.1.1's existing keys (`run_id`, `started_at`, `phase_1_classifications`, `phase_2_outcome`, `phase_2_path`, `chat_stream_baseline_post_symmetrisation`, `embed_baseline_post_symmetrisation`, `embed_regression_check`, `multi_point_timings`, `phase_1_runs`, `m6_1_baseline_pointer`, `methodology_supersedence`, `schema_version`, etc.) are unchanged.

## Markdown Surface

The markdown companion of the corrected-dispatch artifact (`docs/benchmarks/m6_1_1-engine-cost-instrumentation.md`) MUST surface the dispatch mode in the methodology section header:

```markdown
## Methodology

- **Model**: `Qwen/Qwen3-8B`, hidden_size=4096
- **Engine**: vllm==0.20.1 (M6.1 baseline recorded: 0.20.1)
- **Dispatch mode**: concurrent (peak in-flight = c, per M6.0a)
- **Hardware**: A10G on Modal `eu-west-1`
- **Torch pin**: 2.11.0 (FR-003)
...
```

The audit baseline markdown (preserved verbatim per FR-011) does NOT receive a retroactive "Dispatch mode: sequential" line. Readers wishing to compare audit vs corrected dispatch should read the dispatch-correction note (`docs/benchmarks/m6_0a-dispatch-correction.md`) which explicitly states both modes side by side.

## JSON Schema Sketch

```json
{
  "schema_version": "m6_1_1.v1",
  "run_id": "2026-05-NN-<hash>",
  "started_at": "2026-05-NN...",
  "dispatch_mode": "concurrent",
  "phase_1_classifications": { ... },
  "phase_2_outcome": "...",
  "phase_2_path": "phase_2_pending",
  "phase_1_runs": [ ... ],
  "chat_stream_baseline_post_symmetrisation": { ... },
  "embed_baseline_post_symmetrisation": { ... },
  "embed_regression_check": { ... },
  "multi_point_timings": { ... },
  "m6_1_baseline_pointer": "docs/benchmarks/m6_1-real-prompt-embeds.json",
  "methodology_supersedence": { ... }
}
```

## Negative Invariants (what the contract prohibits)

- **No third value**: `dispatch_mode ∈ {"sequential", "concurrent"}` is closed. `"automatic"`, `"mixed"`, `"unknown"`, `"hybrid"`, etc., are not permitted (FR-005 + Phase Discipline).
- **No nested location**: `dispatch_mode` is a top-level key. It does not appear inside `run_meta.dispatch_mode`, `phase_1_runs[i].dispatch_mode`, or any other sub-object.
- **No per-cell or per-cohort variant**: every cell × cohort in a single run shares the same dispatch mode. There is no `phase_1_classifications[cell_key].dispatch_mode`.
- **No version bump**: `schema_version` is unchanged. Future readers MUST NOT use the presence of `dispatch_mode` as a version-detection signal — they MUST use `manifest.get("dispatch_mode", "sequential")` as the canonical retroactive-default pattern.
- **No retroactive emission**: the audit baseline run is not re-emitted with a `dispatch_mode: "sequential"` annotation. The audit baseline JSON does not exist; the audit baseline markdown is preserved verbatim per FR-011.

## Cross-Reference for Downstream Milestones

M6.2 (the next downstream consumer) reads M6.1.1 manifests as its baseline reference. After M6.0a lands:

- M6.2's `baseline_pointer` continues to point at M6.1.1's canonical JSON (`docs/benchmarks/m6_1_1-engine-cost-instrumentation.json`).
- M6.2 MAY surface `dispatch_mode` in its own published JSON to document which baseline was used.
- M6.2 inherits the corrected dispatch automatically (FR-005 — no parallel-fork; the M6.1 measurement loop M6.2 reuses is the fixed version after PR-1).

This contract is forward-compatible: any future M6.x sub-milestone that introduces a new dispatch axis (e.g., a fictional `M6.0b — Cross-Cohort Concurrent Dispatch`) MUST add its own discriminator field (e.g., `cross_cohort_dispatch_mode`) rather than expanding the `dispatch_mode` enum.
