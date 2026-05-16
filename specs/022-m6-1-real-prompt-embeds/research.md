# Phase 0 Research: M6.1 — Real-Prompt-Embeds Engine Path

**Branch**: `022-m6-1-real-prompt-embeds` | **Date**: 2026-05-16
**Plan**: [plan.md](./plan.md)

This document consolidates the research items that informed the plan. The
2-round clarification process (see [`spec.md`](./spec.md) `## Clarifications`)
settled all NEEDS CLARIFICATION items at spec time, so this file's purpose is
to record the codebase-state findings and design decisions that shape
implementation but are not spec-level contracts.

Each item: **Decision** → **Rationale** → **Alternatives considered**.

---

## R-1: Frontend dispatch already routes torch.save bytes to real prompt-embeds

**Decision**: The gRPC embed cohort's switch from "raw float32 bytes that hash
to a text digest" (M5.x / M6 wire format) to "real prompt-embedding tensors
through `enable_prompt_embeds=True`" requires **no frontend code change**. The
existing `_resolve_prompt_embeds_input` helper in
`packages/frontend/src/vllm_grpc_frontend/completions.py:49` already
distinguishes the two encodings by the `PK\x03\x04` ZIP magic prefix:

```python
_TORCH_SAVE_MAGIC: bytes = b"PK\x03\x04"

def _resolve_prompt_embeds_input(raw_bytes: bytes) -> Any:
    if raw_bytes[:4] != _TORCH_SAVE_MAGIC:
        return _prompt_embeds_to_text_digest(raw_bytes)
    try:
        tensor = decode_embeds(raw_bytes)
    except ValueError:
        return _prompt_embeds_to_text_digest(raw_bytes)
    return {"prompt_embeds": tensor}
```

When M6.1's gRPC embed driver ships `torch.save(tensor)` bytes (which always
start with the ZIP magic), the dispatch routes to `decode_embeds(raw_bytes)`,
returns a real `torch.Tensor`, and hands `{"prompt_embeds": tensor}` to
`engine.generate(...)` — driving the `enable_prompt_embeds=True` engine path.
When M5.x / M6 ship raw float32 bytes (no ZIP magic), the dispatch falls back
to `_prompt_embeds_to_text_digest` and the engine sees a short text prompt.
Both paths coexist indefinitely — symmetric with the REST `input_kind` policy
established in FR-004.

**Rationale**:
- Confirmed by direct source inspection at
  `packages/frontend/src/vllm_grpc_frontend/completions.py:38-64`. The comment
  at lines 38-46 documents the prefix-pre-filter as a `torch.load` warning
  suppression + cost optimisation, but the dispatch logic also serves the
  M6.1 routing requirement without modification.
- `decode_embeds` (in
  `packages/frontend/src/vllm_grpc_frontend/completions_translate.py:7`)
  already accepts `float32`, `bfloat16`, and `float16` dtypes (line 15) and
  requires `ndim == 2` (line 19) — matching M6.1's `[seq_len, hidden_size]`
  fp16 tensor shape (FR-028).
- Constitution Principle I ("Proto-First") requires `.proto` edits before any
  wire-format change. Reusing the existing field encoding distinction
  (prefix-based, no schema change) keeps the existing
  `proto/vllm_grpc/v1/completions.proto` untouched.

**Alternatives considered**:
- Add a separate `prompt_embeds_real` proto field — requires `.proto` edits +
  stub regeneration + downstream proxy/client awareness. Rejected for
  Proto-First + Phase Discipline reasons.
- Pass an explicit `engine_path` discriminator field on the request —
  redundant with the existing prefix-based dispatch and would force every
  M5.x / M6 reproduction to update the wire format. Rejected.
- Strip the prefix-based dispatch and rely on a flag — same redundancy
  problem; also breaks M5.x / M6 reproducibility.

---

## R-2: torch client-side version pin policy

**Decision**: The bench client's package (`tools/benchmark/pyproject.toml`)
adds `torch==2.11.0` to its dependencies — the exact version vLLM 0.20.1
pulls transitively per `uv.lock`. The embed driver validates
`torch.__version__` against the expected pinned version at driver-start
(before the first measurement RPC of the first embed cohort) and exits with a
clear actionable error message if mismatched (FR-006).

**Rationale**:
- Confirmed via direct inspection of `uv.lock`: `vllm==0.20.1` requires
  `torch==2.11.0` (lock entries at lines 2727-2754).
- Pinning to the same version vLLM uses transitively eliminates the only
  realistic source of `torch.save` / `torch.load` wire incompatibility — the
  pickle ZIP format and the tensor metadata embedded by torch evolve across
  major versions, and a client running 2.12.0 against a server running 2.11.0
  could produce silent `decode_embeds` failures that surface as
  undebuggable `cell_incomplete` floors via FR-017.
- Validating `torch.__version__` at driver-start (before any RPC) turns a
  silent runtime failure into an actionable startup error — operationally
  cheap to recover from.
- The validation lives in `m6_1_torch_pin.py` and is called once at the
  beginning of `m6_1_sweep.run_sweep()` and `m6_1_smoke.run_smoke()` so both
  modes share the same precondition.

**Alternatives considered**:
- Pin the bench client to a broader range (`torch>=2.11,<3.0`) — allows the
  operator's environment to drift; defeats the determinism goal. Rejected.
- Don't pin at all, leave it to the operator to install torch — the silent
  failure mode is exactly what FR-006 was added to prevent. Rejected.
- Add a `decode_embeds` wire-format version check on the server side — would
  require a frontend change (violates the "no frontend change required"
  premise of R-1). Rejected.
- Use a build-from-source torch matching vLLM's vendored CUDA version —
  fragile and slow for the operator's laptop. The pinned PyPI wheel is
  sufficient for the client-side `torch.save` call (the client doesn't need
  CUDA at all).

---

## R-3: seq_len pinning to M6's tokenised text-digest length

**Decision**: M6.1's prompt-embeds tensor shape is
`[seq_len, hidden_size=4096]` where `seq_len` is **fixed across all RPCs,
cells, and cohorts**, pinned at sweep start by tokenising M6's per-RPC
text-digest format `embed_<8-byte-hex>` against the loaded model's tokenizer
(Qwen3-8B) and using the resulting token count. The pinned `seq_len` value is
recorded in `M6_1RunMeta.seq_len` (FR-027).

Implementation pattern in `m6_1_seq_len.py`:

```python
def pin_seq_len_at_sweep_start(model_identifier: str) -> int:
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_identifier)
    # M6 hashed prompt_embeds bytes to "embeds:<8-byte-hex>" and shipped
    # that as the text prompt. We tokenise the same canonical form using
    # a fixed-content sample (the digest content varies per RPC, but the
    # token count is determined by the format + the hex length, which is
    # constant).
    sample = "embeds:" + "0" * 16  # 16 hex chars = 8 bytes
    tokens = tok.encode(sample, add_special_tokens=False)
    return len(tokens)
```

The pinning happens **once** per sweep (after model load completes, before
the first measurement RPC). All subsequent tensors share the same
`[seq_len, 4096] fp16` shape with varying values.

**Rationale**:
- Confirmed by direct inspection of
  `packages/frontend/src/vllm_grpc_frontend/completions.py:34` —
  `_prompt_embeds_to_text_digest` returns `f"embeds:{digest}"` where `digest`
  is the 8-byte (16-hex-char) blake2b hash of the raw payload. This is the
  exact text M6's embed cohort fed into `engine.generate(...)` per RPC.
- Pinning `seq_len` to that tokenised length is the cleanest way to hold
  workload size constant across M6 and M6.1 so the "Engine path differential"
  is a clean read of the engine code-path cost rather than a confound with
  prompt-length variance — the Q answered in spec.md Clarifications session
  2026-05-15.
- Tokenising at sweep start (vs hardcoding a value) ensures the pin tracks
  the actual tokenizer behaviour for the loaded model. For Qwen3-8B this is
  expected to be ~8 tokens; the harness records the actual integer in
  RunMeta so the published methodology note is concrete.
- `transformers.AutoTokenizer.from_pretrained` is already part of vLLM's
  transitive dependency tree (vLLM uses it internally for prompt handling),
  so no new dependency is introduced.

**Alternatives considered**:
- Hardcode `seq_len=8` — risks drift if the Qwen3-8B tokenizer changes or
  the model is swapped. The dynamic pin is robust.
- Use a different fixed seq_len (e.g., 16 — matches M3 / M5.x's raw-bytes
  tensor shape) — would change workload size relative to M6 and confound
  the differential. Rejected at spec time (FR-028).
- Vary seq_len per RPC by tokenising the actual per-RPC digest — same
  problem (the digest content varies, so token count could too). Holding
  shape constant per RPC is the spec's design choice.
- Skip the tokenizer call and pin to a constant via a CLI flag — adds
  operator-error surface and breaks the "exact M6 workload size" invariant.

---

## R-4: M6 published JSON schema for m6_winner_deltas lookup

**Decision**: The M6.1 verdict classifier reads M6 winner deltas from
`docs/benchmarks/m6-real-engine-mini-validation.json`. The relevant fields
are `supersedes_m5_2_under_real_engine[]` (one entry per cell — the M6
verdict table) and `m6_meta.m5_2_winner_deltas` (the M5.2 deltas M6 itself
consumed). For M6.1 the **M6 winner delta** for each cell is computed from
M6's `supersedes_m5_2_under_real_engine[i].per_cohort_classifier_metric` —
specifically, the signed difference between the cohort M6 classified as
winning and the comparison cohort, using the same algorithm M6 used to
extract M5.2 deltas (Research item R-5 / R-6 in M6's research.md).

```python
# Pseudocode for m6_1_supersede.py
def extract_m6_winner_delta(m6_cell_record: dict) -> tuple[float | None, str | None]:
    """Return (|delta_median_ms|, winner_direction) from an M6 cell.

    Returns (None, None) if the M6 cell's classification is one of the
    "no usable winner delta" categories per FR-010:
        - no_winner_at_n100
        - cell_incomplete
        - verdict_buried_by_engine
    """
    classification = m6_cell_record["classification"]
    if classification in {"no_winner_at_n100", "cell_incomplete",
                          "verdict_buried_by_engine"}:
        return None, None
    # For verdict_survives / verdict_changed, M6 published a non-overlapping
    # CI verdict; extract delta from the M6 cohort means.
    pcm = m6_cell_record["per_cohort_classifier_metric"]
    rest = pcm["rest_https_edge"]["mean_ms"]
    grpc = pcm["tuned_grpc_multiplexed"]["mean_ms"]
    delta = rest - grpc  # positive → grpc wins; negative → rest wins
    direction = "grpc_wins" if delta > 0 else "rest_wins"
    return abs(delta), direction
```

The harness snapshots the resulting `m6_winner_deltas` dict into
`M6_1RunMeta.m6_winner_deltas` at sweep launch (FR-008) — equivalent
treatment to M6's `m5_2_winner_deltas` snapshot.

**Rationale**:
- Confirmed by direct inspection of
  `docs/benchmarks/m6-real-engine-mini-validation.json` top-level keys —
  `supersedes_m5_2_under_real_engine`, `m6_meta`, and the cell-level
  `per_cohort_classifier_metric` shape are present.
- FR-009's "must validate all 6 cells present" precondition requires the
  classifier to load the file early and check structural completeness before
  any RPC is sent — that abort-fast behaviour mirrors M6's M5.2-baseline
  precondition treatment.
- The FR-010 sub-clause (cells whose M6 verdict was `no_winner_at_n100`,
  `cell_incomplete`, OR `verdict_buried_by_engine` classify as
  `no_winner_at_n100` regardless of M6.1 CI overlap) is implemented by the
  early-return None tuple in the extract function above — the classifier
  then short-circuits to `no_winner_at_n100` per the algorithm in R-8.

**Alternatives considered**:
- Read the M6 baseline from `protocol_comparison_verdicts[]` (M5.2-shape
  strict-superset section) — same data, but `supersedes_m5_2_under_real_engine`
  carries the canonical M6 classification while `protocol_comparison_verdicts`
  preserves M5.2's shape. The M6-canonical field is cleaner.
- Recompute the M6 winner delta from M6's per-RPC events sidecar — wasteful
  and adds a dependency on the sidecar file being colocated with the JSON
  companion. Rejected.
- Treat `verdict_buried_by_engine` cells as having a usable winner delta
  (extract a cohort-mean delta even though M6 ruled the cell unverifiable) —
  rejected at spec time (Clarifications session 2026-05-15 Q2). Re-extracting
  a "winner delta" from buried-by-engine cells would smuggle a verdict claim
  into M6.1 that M6 itself refused to make.

---

## R-5: M6 engine_version baseline value handling

**Decision**: M6.1's RunMeta records two `engine_version` fields:
1. `engine_version` — M6.1's own pinned `vllm` version, read from
   `pyproject.toml` (the project's source of truth for the vLLM dependency
   pin). Expected value: `0.20.1`.
2. `m6_baseline_engine_version` — the value of `run_meta.engine_version`
   read from the M6 baseline JSON (`docs/benchmarks/m6-real-engine-mini-validation.json`'s
   `m6_meta.engine_version` field). Expected value for the existing legacy
   baseline: `"unknown"` (M6's version-reader helper landed post-sweep —
   confirmed by direct inspection of the baseline file's `m6_meta` block).

The published markdown report includes a one-line note in the Methodology
section naming both values; if they differ (or if `m6_baseline_engine_version
== "unknown"`), the note flags the comparison as informational and reminds
the operator that the "Engine path differential" read is cleanest when both
versions match. The harness does NOT block or abort on mismatch — non-blocking
by design so M6.1 can run against the existing legacy M6 baseline (FR-030).

**Rationale**:
- Confirmed by direct inspection of M6's published JSON: the `m6_meta`
  object exists with an `engine_version: "unknown"` value, per the bash
  output during plan research:
  ```
  run_meta keys: ['cold_start_s', 'engine_version', 'git_sha', 'gpu_type',
                  'hostname', 'm5_2_winner_deltas', 'm6_base_seed',
                  'model_identifier']
  engine_version: unknown
  ```
- Surfacing as informational + non-blocking means M6.1 can run against the
  legacy baseline today (avoiding a blocker on a milestone-republish loop),
  while future re-published M6 baselines (with a recorded version) feed
  cleanly through the same plumbing.
- Reading M6.1's own version from `pyproject.toml` (rather than at runtime
  from `vllm.__version__`) keeps the version statement consistent with the
  declared dependency pin, even if the operator's local environment has
  drifted. This matches the M6 pattern (`engine_version` is the configured
  pin, not the at-runtime import).

**Alternatives considered**:
- Block the run if `engine_version` doesn't match — would make M6.1
  unrunnable against the existing legacy M6 baseline (rejected at spec time,
  Clarifications session 2026-05-15 Q4).
- Skip the comparison entirely — loses the methodology disclosure that lets
  operators judge differential trust.
- Read `vllm.__version__` at runtime instead of from `pyproject.toml` — would
  surface the operator's environment version (possibly different from the
  declared pin if the operator has a dirty venv); confusing.

---

## R-6: chat_stream control-drift check algorithm

**Decision**: After full-sweep completion (and ONLY at full sweep, not at
smoke — FR-012/FR-029), the harness runs a per-cell-per-cohort CI-overlap
check on the classifier metric (TTFT for chat_stream cells) against M6's
published CIs. Algorithm in `m6_1_drift_check.py`:

```python
def check_chat_stream_control_drift(
    m6_1_chat_stream_cells: list[M6_1CellRecord],
    m6_baseline_chat_stream_cells: list[dict],
) -> dict[tuple[str, int], bool]:
    """Return per-(cell_path, concurrency) → drift flag.

    A cell's drift flag is True iff at least one (cohort) pair has
    non-overlapping CIs between M6 and M6.1.
    """
    flags: dict[tuple[str, int], bool] = {}
    for cell in m6_1_chat_stream_cells:
        m6_match = _find_m6_cell(m6_baseline_chat_stream_cells, cell)
        any_non_overlap = False
        for cohort in ("rest_https_edge", "default_grpc", "tuned_grpc_multiplexed"):
            m6_1_ci = cell.per_cohort[cohort].classifier_metric_ci
            m6_ci = m6_match["per_cohort_classifier_metric"][cohort]
            if not _cis_overlap(m6_1_ci, (m6_ci["ci_lower_ms"], m6_ci["ci_upper_ms"])):
                any_non_overlap = True
                break
        flags[(cell.path, cell.concurrency)] = any_non_overlap
    return flags
```

Flagged cells get a `chat_stream_control_drift_warning: True` field in both
the JSON companion (under each chat_stream cell record) and the markdown
report (annotation next to the cell row in the verdict table). The flag is
diagnostic — verdicts are still computed and published. UX mirrors
`engine_cost_drift_warning` (FR-022).

**Rationale**:
- FR-029 mandates the check fires only on full sweep, not smoke; smoke's
  n=10 CIs are too wide for the overlap test to produce meaningful signal
  (a wide n=10 CI versus M6's tight n=100 CI would nearly always overlap,
  falsely reassuring the operator — confirmed at spec time, Clarifications
  session 2026-05-15 Q3 / round 2 Q5).
- Per-(cell × cohort) CI-overlap on the same classifier metric (TTFT) is the
  same primitive M6's classifier uses for embed cells — a known-tested
  algorithm, no new statistical machinery introduced.
- Trigger condition is "at least one cohort non-overlaps" rather than "all
  cohorts non-overlap" because *any* contaminating drift is worth surfacing
  (the operator decides whether to trust the verdicts).

**Alternatives considered**:
- Run the check at smoke too — n=10 CIs are too wide; produces false
  negatives (Clarifications round 2 Q5).
- Use a different statistical test (e.g., t-test against M6's published
  mean) — heavier; CI-overlap is the project's established framing across
  M5.2 / M6 / M6.1.
- Use a tighter threshold (e.g., require ≥2 cohorts non-overlap) — would
  miss single-cohort regressions (e.g., a REST shim change that affects only
  the REST cohort).
- Block on drift — would make M6.1 unrunnable whenever Modal infrastructure
  has any drift relative to M6's sweep day. Diagnostic-only is the design.

---

## R-7: GPU memory pressure under real prompt-embeds engine path

**Decision**: The engine config (`max_model_len=2048`, `gpu_memory_utilization=0.92`)
is reused unchanged from M6. The real prompt-embeds engine path uses extra
activation memory for the forward pass on the materialised tensor (vs M6's
text-digest path, which tokenises a short string and uses standard
attention-mask-zeroed activation memory). The harness does NOT introduce its
own OOM guard; instead, any OOM that surfaces during sweep flows through the
existing FR-017 retry / `cell_incomplete` pathway.

Memory budget back-of-envelope at h=4096, `seq_len ≈ 8`, c=8:

```
Qwen3-8B fp16 weights:        ~16 GB
KV cache (max_model_len=2048): ~1.1 GB (from M6 R-11 calc — UNCHANGED)
Prompt-embeds activations:    [seq_len × hidden_size × layers × fp16]
                            = 8 × 4096 × 36 × 2 bytes ≈ 2.3 MB per request
                              (negligible at c=8 → ~18 MB aggregate)
Standard activation memory:   ~hundreds of MB across the forward pass
Total:                        ~17 GB + headroom — well within 24 GB
```

The headroom is comparable to M6's, so OOM is unlikely to surface during
typical operation. If it does (e.g., transient pressure during concurrent
chat_stream + embed), the cell falls to `cell_incomplete` per FR-017 and the
operator investigates from the events sidecar.

**Rationale**:
- Memory budget calculation shows the additional cost of the real
  prompt-embeds forward pass is negligible relative to KV cache + weights;
  no config tuning needed.
- Reusing the M6 engine config preserves the "exactly one variable change"
  invariant (FR-007 — same engine config, only the engine code path
  differs).
- Routing any OOM through `cell_incomplete` (rather than aborting the sweep)
  preserves operator-quality-of-life: a single (cell × cohort) OOM doesn't
  lose 80 minutes of Modal time on the other 5 cells.

**Alternatives considered**:
- Lower `gpu_memory_utilization=0.85` to leave more headroom — would
  artificially constrain KV cache and could degrade chat_stream performance.
  Rejected: a measurement-influencing config change.
- Add an explicit pre-sweep OOM probe — adds complexity; FR-017's retry
  pathway already handles transient memory pressure gracefully.
- Lower `max_model_len=1024` — would help KV cache headroom further but
  M6.1's actual per-RPC token count is well under 100 (R-3); no benefit.

---

## R-8: Verdict classifier algorithm (M6.1)

**Decision**: The classifier in `m6_1_supersede.py` implements FR-010's
deterministic discrimination rule as a pure function of (M6.1 measurement
data, M6 baseline JSON). The algorithm is structurally identical to M6's
classifier (Research R-7 in M6's research.md), retargeted at M6 winner deltas
and extended with the FR-010 sub-clause for buried-by-engine M6 cells:

```text
For each of the 6 M6.1 cells (path, c=1|4|8 at h=4096):
  1. If any cohort has n_successes < 80 (FR-017):
       → terminal classification = cell_incomplete
       → SKIP further verdict computation.

  2. Compute classifier_metric per cohort:
       - For embed: client-observed total per-RPC wall-clock mean and 95% CI (FR-011).
       - For chat_stream: client-observed TTFT mean and 95% CI (FR-011).

  3. Compute engine_cost_mean per cell as the simple unweighted average of
     the three per-cohort means (FR-022). Path-discriminated:
       - embed: average of per-cohort engine_forward_ms means.
       - chat_stream: average of per-cohort engine_ttft_ms means.

  4. Compute engine_cost_drift_warning flag:
       - If any pair of cohorts' engine_cost_mean disagree by >10%, set flag.
       - Flag does NOT promote cell to cell_incomplete (FR-022).

  5. Lookup M6_winner_delta (see R-4):
       - Read M6's supersedes_m5_2_under_real_engine[] for (path, h=4096, c).
       - If M6 classification ∈ {no_winner_at_n100, cell_incomplete,
                                  verdict_buried_by_engine}:
            M6_winner_delta = None.  (FR-010 sub-clause — no usable baseline)
       - Else (M6 was verdict_survives or verdict_changed):
            Extract |delta| and direction from per_cohort_classifier_metric.
            M6_winner_delta = |delta|, M6_winner_direction = sign.

  6. Compute M6.1 cohort-pair CI overlap. The relevant pair is
     (rest_https_edge, tuned_grpc_multiplexed) — the same pair M6 used.

  7. Apply FR-010 discrimination rule:
       - If M6_winner_delta is None:
            → no_winner_at_n100 (regardless of M6.1 CI overlap — FR-010 sub-clause).
       - Else if M6.1 pair CIs are non-overlapping:
            If sign(M6.1_delta) == M6_winner_direction → verdict_survives
            Else → verdict_changed
       - Else (M6.1 pair CIs overlap):
            If engine_cost_mean ≥ 5 × M6_winner_delta → verdict_buried_by_engine
            Else → no_winner_at_n100

  8. Write per-cell verdict + classifier_metric values + engine_cost_mean +
     engine_cost_drift_warning + chat_stream_control_drift_warning (R-6) +
     n_successes + failure_count to M6.1 report and JSON companion.

  9. Compute Engine Path Differential (US2 / FR-020):
       - For each cohort: classifier_metric_delta_ms = M6.1 mean − M6 mean,
         with combined 95% CI half-width (square root of sum of squared
         CI half-widths — standard CI of difference for independent samples).
       - For the cell: engine_cost_mean_delta_ms = M6.1 cell engine_cost_mean
         − M6 cell engine_cost_mean, with combined 95% CI half-width.
       - Differential is published even when verdict == no_winner_at_n100 or
         cell_incomplete (SC-007). Operator inspects raw deltas there.
```

**Rationale**:
- Direct implementation of FR-010's discrimination rules + FR-017's
  `cell_incomplete` precondition + FR-022's drift flag + FR-029's
  chat_stream control-drift check + FR-020's differential.
- Pure function of inputs ⇒ deterministic ⇒ unit-testable on synthetic
  inputs without Modal access (per Constitution Principle IV).
- Step 1 ordering (`cell_incomplete` first) prevents wasted classifier work
  on cells that won't get a verdict.
- Step 5's expanded "no usable baseline" set (vs M6's set, which excluded
  only `no_winner_at_n100` and `cell_incomplete`) implements the FR-010
  sub-clause that buried-by-engine M6 cells produce `no_winner_at_n100`
  regardless of M6.1 CI overlap. Rationale per spec Clarifications session
  2026-05-15 Q2: re-extracting a winner delta from buried-by-engine cells
  would smuggle a verdict claim M6 itself refused to make.
- Step 9 (Engine Path Differential computation) runs for every cell
  regardless of verdict — SC-007 guarantees the section's row is populated
  even for `cell_incomplete` cells, annotated with actual `n_successes`.

**Alternatives considered**:
- Compute all metrics first, then check `cell_incomplete` — wastes computation;
  same outcome.
- Allow operator post-hoc reclassification — explicitly forbidden by FR-010
  (matches M6's explicit prohibition).
- Use `delta_median_ms` directly instead of `|delta|` for the 5× rule —
  would conflate sign + magnitude. The rule cares about magnitude only.
- Extract winner deltas from buried-by-engine M6 cells — rejected at spec
  time (Clarifications Q2).
- Use a more permissive non-overlap test (e.g., delta sign without CI check)
  — would inflate `verdict_survives` / `verdict_changed` counts spuriously.

---

## R-9: Round-robin per c-batch + warmup interaction reused from M6

**Decision**: M6.1 reuses M6's round-robin per c-batch sequencer wholesale.
The implementation lives in `m6_sweep.py` (or its helpers); `m6_1_sweep.py`
composes the existing per-cohort cohort-execution helpers without
re-implementing the sequencer. The per-cohort warmup phase (10 RPCs/cohort)
follows the same round-robin rotation; the at-c=8 rounding rule (12 full
rounds + 1 partial round with last cohort's tail dropped) is identical to
M6 R-9.

**Rationale**:
- The sequencer is correctness-critical and unit-tested under M6; reusing it
  unchanged minimises risk and code surface.
- FR-015 (warmup convention) and FR-016 (round-robin per c-batch convention)
  are spec'd identically to M6's FR-021/FR-022 — no algorithmic divergence
  needed.
- `m6_1_sweep` composes `m6_sweep`'s helpers; if a regression in the
  sequencer would surface in M6's tests too, the project's CI gate catches
  it before merge.

**Alternatives considered**:
- Re-implement the sequencer in `m6_1_sweep` — duplication; harder to
  maintain.
- Refactor the sequencer to a shared module — fine eventually, but per
  Phase Discipline (don't introduce abstractions beyond what the task
  requires), keep the M6 module as the canonical source and let M6.1
  compose from it. A future M-milestone with three+ sweep variants might
  motivate a refactor.

---

## Coverage Summary

All NEEDS CLARIFICATION items in the Technical Context were resolved during
the 2-round spec clarification process; this Phase 0 file documented
codebase-state findings + design decisions only. No items remain unresolved.
