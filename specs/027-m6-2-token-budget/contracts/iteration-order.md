# Contract: M6.2 Sweep Iteration Order + Exogenous-Confound Controls

**Branch**: `027-m6-2-token-budget` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Why this contract exists

M6.1.x sweeps ran for ~75 minutes — short enough that exogenous time-varying confounds (day/night cycles, business-hours network traffic, ISP congestion variance) were below the noise floor of the cohort comparison. M6.2 runs for **20-48 hours** (depending on round-3-pinned `n`), and the long wall-clock exposes the sweep to time-of-day variance that can bias the headline cohort-vs-cohort comparison. This contract pins the four implementation-level disciplines that mitigate or expose that variance:

1. **FR-030 cohort-innermost block iteration** — eliminates between-cohort time-of-day bias by ensuring each `(cell, max_tokens)` tuple's 4 cohorts share a tight ~30 min – 4 h time window.
2. **FR-031 intra-sweep anchor re-measurement at 4h cadence** — makes intra-sweep latency drift observable per cohort.
3. **FR-032 per-block UTC timestamps + iteration-discipline machine check** — makes FR-030 independently verifiable post-hoc.
4. **FR-033 in-window retry once, no end-of-sweep retry pass** — preserves FR-030 discipline under transient block-level failures.

The four mechanisms compose: FR-030 mitigates bias; FR-031 detects drift the FR-030 mitigation couldn't absorb; FR-032 verifies FR-030 happened; FR-033 prevents accidental FR-030 violations during failure recovery.

## FR-030 Cohort-innermost block iteration

### Iteration pattern

The orchestrator MUST iterate the 144-point measurement matrix as:

```python
M6_1_CELLS: tuple[str, ...] = ("embed_c1", "embed_c4", "embed_c8", "chat_stream_c1", "chat_stream_c4", "chat_stream_c8")
M6_2_MAX_TOKENS_AXIS: tuple[int, ...] = (10, 50, 256, 512, 1024, 2048)
M6_1_2_COHORTS: tuple[str, ...] = ("rest_plain_tcp", "rest_https_edge", "default_grpc", "tuned_grpc_multiplexed")

for cell_id in M6_1_CELLS:                                       # outer
    for max_tokens in M6_2_MAX_TOKENS_AXIS:                       # middle
        for cohort in cohorts_at_concurrency(cell_id, M6_1_2_COHORTS):  # INNERMOST per FR-030
            run_block(cell_id, cohort, max_tokens, n=args.m6_2_n)
```

where `cohorts_at_concurrency(...)` is the M6.1.2 helper inherited via import (it returns the 4-cohort tuple for c=4 / c=8 cells and the tuned-pair-collapsed 3-cohort tuple for c=1 cells per the M5.2 convention; M6.2 reuses this verbatim per FR-006 + FR-027). For c=1 cells the 4-cohort iteration becomes 3-cohort, but the cohort-innermost discipline is unchanged — all (3 or 4) cohorts at a given `(cell, max_tokens)` tuple still share a contiguous time window.

### Forbidden orderings

The orchestrator MUST NOT iterate cohort-outermost. The following pattern is forbidden:

```python
# FORBIDDEN per FR-030: would map each cohort to a different ~6-12 h band of the 20-40 h sweep
# and confound the cohort comparison with day/night network-load variance.
for cohort in M6_1_2_COHORTS:
    for cell_id in M6_1_CELLS:
        for max_tokens in M6_2_MAX_TOKENS_AXIS:
            ...
```

The orchestrator's runtime check (FR-032 `iteration_discipline_verified`) detects this case post-hoc and flags it via the soft `iteration_discipline_broken` diagnostic warning at the artifact header.

### Outer-loop order rationale

The choice of `(cell × max_tokens)` outer order over `(max_tokens × cell)` outer order is per R-2 of [`../research.md`](../research.md): cells-first means each cell's per-cohort × per-max_tokens block runs in a contiguous ~6-12 h window of the sweep, which aligns with the reporter's per-cell rendering and the wall-clock timeline subsection's per-cell readability. The discipline is on the **innermost** variable; the outer order is pragma.

### Time-window expectations

| Cell | Approximate wall-clock per `(cell, max_tokens)` block (4 cohorts × n RPCs) | Notes |
|---|---|---|
| `embed_c1`, `embed_c4`, `embed_c8` | ~3-30 min (max_tokens has little effect on embed engine cost) | Embed cells at `max_tokens > 10` are a hybrid engine-path + generation signal per FR-002. |
| `chat_stream_c1` × `max_tokens=10` | ~5-15 min | Low-cap chat is ~50 ms/RPC × n × 3-4 cohorts. |
| `chat_stream_c1` × `max_tokens=2048` | ~3-4 h | High-cap chat is ~35-69 s/RPC × n × 3-4 cohorts. THIS IS THE LONGEST BLOCK. |
| `chat_stream_c4` × `max_tokens=2048` | ~1-1.5 h | Concurrent dispatch amortizes per-RPC cost. |
| `chat_stream_c8` × `max_tokens=2048` | ~30-60 min | Further amortization at higher concurrency (load permitting). |

The longest single block (`chat_stream_c1 × max_tokens=2048`) is the worst-case time window for time-of-day variance within the cohort-innermost discipline. At ~4 h, it spans a meaningful fraction of a business-hours band — but it spans the SAME band for all 4 cohorts at that tuple, so the cohort comparison is still time-of-day-controlled (just with a wider within-cohort variance contribution).

## FR-031 Intra-sweep anchor re-measurement

### Cadence

The orchestrator MUST run a lightweight re-anchor block at:

- **Sweep start** (t = 0).
- **Every 4-hour wall-clock mark** in publish mode (t = 4h, 8h, 12h, ...).
- **Sweep end** (t = total_sweep_hours).

In validate mode (sweep wall-clock < 8h), the orchestrator MAY run re-anchors at start + end only and skip in-flight 4h marks. If validate mode exceeds 8h (e.g., due to retries), the orchestrator MUST run the same 4h cadence as publish mode.

The 4h cadence is **aligned with FR-009's `network_paths` probe cadence** — at each 4h mark, both the topology probe AND the anchor re-anchor co-fire as a unified "sweep health check" tick. The total per-tick overhead is ~30-60 s (topology probe per cohort × 4 cohorts + anchor block per cohort × 4 cohorts at n=20).

### Anchor block composition

Each re-anchor block runs **`chat_stream × c=1 × max_tokens=10`, `n=20` RPCs per cohort, cohort-innermost**:

```python
def compute_anchor_block(
    cohorts: tuple[str, ...],
    *,
    cell_id: str = "chat_stream_c1",
    max_tokens: int = 10,
    n: int = 20,
    base_seed: int,
    rpc_driver: RpcDriver,
) -> dict[str, M6_2AnchorLatencySnapshot]:
    out = {}
    for cohort in cohorts:
        per_rpc_timings = run_concurrent_dispatch(
            cell_id=cell_id,
            cohort=cohort,
            max_tokens=max_tokens,
            n=n,
            base_seed=base_seed,
            rpc_driver=rpc_driver,
        )
        out[cohort] = M6_2AnchorLatencySnapshot(
            wall_p50_ms=percentile(per_rpc_timings, 50),
            wall_p95_ms=percentile(per_rpc_timings, 95),
            wall_p99_ms=percentile(per_rpc_timings, 99),
            snapshot_timestamp=datetime.now(UTC).isoformat(),
            sweep_hour_mark=current_sweep_hour_mark(),
        )
    return out
```

The cell choice (`chat_stream c=1 × max_tokens=10`) is per R-3 of [`../research.md`](../research.md): cheap (low max_tokens → ~35 ms per RPC), network-latency-sensitive (c=1 → no concurrent-dispatch masking), symmetric across cohorts (chat_stream is the canonical Story 2 cell-type).

### Drift detection

After all anchor snapshots are collected, the reporter computes:

```python
def fire_latency_drift_warning(
    per_cohort_trajectories: dict[str, M6_2AnchorLatencyTrajectory],
    m6_1_3_baseline_ci_half_width: dict[str, float],
) -> None:
    for cohort, trajectory in per_cohort_trajectories.items():
        spread = trajectory.max_minus_min_wall_p50_ms
        ci_half = m6_1_3_baseline_ci_half_width[cohort]  # from M6.1.3 published JSON
        trajectory.latency_drift_warning = (spread > ci_half)
```

The per-cohort `latency_drift_warning` line is emitted in the "Anchor latency trajectory" subsection of the markdown.

### Sweep-level integrity header firing

When ≥ 2 of 4 cohorts have `latency_drift_warning = true`, the reporter emits the `intra_sweep_latency_drift` sweep-level integrity header at the top of the markdown body. The 2-of-4 threshold gives 1-cohort-of-headroom — a single isolated cohort drift (likely a cohort-specific topology event already covered by FR-009 / SC-010) does NOT trigger the sweep-level header; systematic multi-cohort drift (region-level congestion variance) does.

Publication is NOT blocked; the operator decides whether to publish or rerun against a fresh Modal deploy at a different time-of-day.

## FR-032 Per-block UTC timestamps + iteration-discipline machine check

### Per-block timestamp capture

The orchestrator MUST capture `block_start_utc = datetime.now(UTC).isoformat()` immediately before entering the per-block RPC dispatch loop and `block_end_utc = datetime.now(UTC).isoformat()` immediately after the loop completes (including any in-window retry per FR-033). The timestamps are stored on the per-(cell, cohort, max_tokens) row of the latency budget table:

```python
def run_block(cell_id: str, cohort: str, max_tokens: int, n: int) -> M6_2MeasurementPoint:
    block_start_utc = datetime.now(UTC).isoformat()
    try:
        timings = await dispatch_n_rpcs(cell_id, cohort, max_tokens, n)
        retry_attempted = False
    except TransientError as e:
        # FR-033 in-window retry once
        retry_attempted = True
        try:
            timings = await dispatch_n_rpcs(cell_id, cohort, max_tokens, n)
        except TransientError as e2:
            # Both attempts failed
            block_end_utc = datetime.now(UTC).isoformat()
            return M6_2MeasurementPoint(
                cell_id=cell_id, cohort=cohort, max_tokens=max_tokens, n_rpcs=n,
                failed_reason=classify_error(e2),
                block_start_utc=block_start_utc, block_end_utc=block_end_utc,
                retry_attempted=True,
                # ... all latency fields = None
            )
    block_end_utc = datetime.now(UTC).isoformat()
    return M6_2MeasurementPoint(
        cell_id=cell_id, cohort=cohort, max_tokens=max_tokens, n_rpcs=n,
        block_start_utc=block_start_utc, block_end_utc=block_end_utc,
        retry_attempted=retry_attempted,
        # ... derived latency fields from timings
    )
```

### Iteration-discipline machine check

At the end of the sweep, the orchestrator computes `iteration_discipline_verified: bool` per the algorithm in [`artifact-schema.md`](./artifact-schema.md) under "Iteration discipline machine check". Renders as `run_meta.iteration_discipline_verified` in the JSON; as the soft `iteration_discipline_broken` diagnostic warning at the artifact header when `false`.

This check is purely diagnostic — `false` does NOT block publication, and does NOT count as one of the four publish-blocking-eligible sweep-level integrity warning channels. The operator inspects the wall-clock timeline subsection to identify which `(cell, max_tokens)` tuple's interleaving broke.

### Wall-clock timeline subsection

The "Sweep wall-clock timeline" subsection (at the bottom of the published markdown) renders one row per `(cell, max_tokens)` tuple showing:

| `(cell, max_tokens)` | Cohort 1 start UTC | Cohort 1 duration | Cohort 2 start UTC | Cohort 2 duration | ... | Total tuple duration |
|---|---|---|---|---|---|---|
| `(chat_stream_c1, 2048)` | 2026-05-19T12:00:00Z | 58.3 min | 2026-05-19T12:58:18Z | 61.7 min | ... | 4.2 h |
| ... | ... | ... | ... | ... | ... | ... |

Operators visually verify the 4 cohort blocks at each tuple form a contiguous time band.

In validate mode with total sweep wall-clock < 8h, this subsection MAY be omitted as low-signal (the per-block UTC timestamps still persist in the JSON for operator inspection).

## FR-033 In-window retry once + no end-of-sweep retry pass

### Retry policy

Each `(cell, cohort, max_tokens)` block MAY retry **ONCE** if the first attempt fails with a transient error from the canonical transient-error set:

```python
TRANSIENT_ERROR_TYPES = (
    grpc.RpcError,           # gRPC errors with code IN {UNAVAILABLE, DEADLINE_EXCEEDED, RESOURCE_EXHAUSTED, INTERNAL}
    asyncio.TimeoutError,    # Dispatch timeout
    httpx.RequestError,      # REST transient connection error
    SingleRpcEngineOomError, # Engine returned OOM for one RPC but didn't crash
)

NON_TRANSIENT_ERROR_TYPES = (
    grpc.RpcError,           # gRPC errors with code IN {INVALID_ARGUMENT, NOT_FOUND, ALREADY_EXISTS, PERMISSION_DENIED, UNIMPLEMENTED, FAILED_PRECONDITION, OUT_OF_RANGE, UNAUTHENTICATED}
    EngineCrashedError,      # The engine crashed entirely (Modal-level recovery needed; sweep-level concern)
)
```

The retry MUST happen **WITHIN the current `(cell, max_tokens)` tuple's time window** — i.e., before the orchestrator advances to the next `(cell, max_tokens)` tuple. Concretely: the orchestrator's main iteration loop catches the transient error, retries the block, and then continues. There is NO separate retry phase.

### Forbidden: end-of-sweep retries

The orchestrator MUST NOT implement an end-of-sweep retry pass. A retry that fires AFTER the orchestrator has advanced past a `(cell, max_tokens)` tuple would run in a different time-of-day window than its 3 sibling cohorts at that tuple, silently violating FR-030 and confounding the cohort comparison.

Failed blocks (both attempts failed) are permanently `failed_<reason>` in the latency budget table per FR-029. The failure-summary subsection tallies them by reason; the FR-029 sweep-level integrity header fires per its 3-cells-or-all-4-cohorts-failed rule.

### Retry markers

The `retry_attempted` field on every MeasurementPoint row distinguishes:

| `retry_attempted` | `failed_reason` | Interpretation |
|---|---|---|
| `false` | `None` | First attempt succeeded; clean measurement. |
| `true` | `None` | First attempt failed transiently; retry succeeded; measurement reflects retry. |
| `false` | non-`None` (rare; only for non-transient errors) | First attempt failed non-transiently; no retry attempted; block marked failed. |
| `true` | non-`None` | Both first attempt and retry failed; block marked failed. |

Test enforcement: `test_m6_2_retry_policy.py::test_retry_stays_in_time_window` asserts that for any block with `retry_attempted = true`, `block_start_utc` and `block_end_utc` are within the same `(cell, max_tokens)` tuple's overall time window.

### Interaction with FR-026 Modal-deploy-level preemption recovery

FR-033 (block-level in-window retry) is DISTINCT from FR-026's Modal-deploy-level preemption recovery (inherited from M6.1.3 FR-028, pinned at preemption-recurrence threshold 2):

- **FR-033 in-window retry**: triggers when a single block's RPC dispatch hits a transient error. Retries the block once within the same time window. No Modal-deploy-level action.
- **FR-026 Modal preemption**: triggers when Modal preempts the entire deploy (the operator's tunnel rotates). Re-establishes the deploy handshake and resumes the main iteration at the block where preemption occurred. The resumed block may take the place of an in-window retry OR initiate a fresh first-attempt at the same block — the orchestrator's resume logic handles both cases.

The two mechanisms compose: if a block is in-window-retrying when Modal preemption occurs, the resume re-runs the entire block (counting as a fresh first-attempt) and the in-window retry budget is re-set; the per-row `retry_attempted` field reflects the post-resume state. If the resume drifts into a different time-of-day window (e.g., > 30 min later than the original block start), the resumed block may break FR-030 — in which case `iteration_discipline_verified` fires false and the operator decides whether to publish or rerun. The orchestrator does NOT auto-abort on resume drift; this is a known edge case per R-8 of [`../research.md`](../research.md).

## Test enforcement

The following test files in `tools/benchmark/tests/` enforce this contract:

- `test_m6_2_iteration_order.py` — FR-030 cohort-innermost iteration verification; FR-032 per-block UTC timestamps + iteration-discipline machine check + wall-clock timeline subsection rendering.
- `test_m6_2_anchor_trajectory.py` — FR-031 4h cadence + cell-of-headroom firing rule + start+end-only validate-mode + SC-016 sweep-level integrity header.
- `test_m6_2_retry_policy.py` — FR-033 in-window retry once + retry-failure handling + end-of-sweep retry forbidden + retry-stays-in-time-window assertion.

Each test exercises the contract surface directly with canned data; no Modal compute required. Integration coverage by `test_m6_2_validate_cli.py` and `test_m6_2_publish_cli.py` exercises the same surface against the stub RPC driver end-to-end.
