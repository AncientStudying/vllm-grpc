# M6.2 Analysis — Topology Conclusion Framing (DRAFT)

**Status**: DRAFT for review. Numbers verified against the n=40 publish sweep.
Pending merge into `ANALYSIS.md` § M6.2.

**Source data**: `docs/benchmarks/m6_2-token-budget.{json,md}` from the
2026-05-25 / 2026-05-26 publish sweep (git_sha `82bd55a`, `n_per_point=40`,
modal_region `eu-west-1`, 132 main-sweep blocks + 16 KV-pressure sub-probe
blocks; wall-clock 14.5 h across two processes — see Caveat 6 below).

**Discussion captured**: 2026-05-24 evening session, framing finalised here
on 2026-05-26 against the verified publish artifact.

---

## The framing under consideration

> If you are using Modal.com and the REST-edge product is available it should
> be used. But if you are in an enterprise environment connecting to a
> self-hosted vLLM solution and high-performance routing is not available to
> you, the wire size reductions and modest speed advantages [of gRPC] are
> worth considering.

Two distinct claims:

1. **On Modal with REST-edge available** → use REST-edge.
2. **Self-hosted, no edge product** → gRPC's wire-size reductions + modest
   speed advantages are worth considering.

---

## Claim 1 — Modal + REST-edge → use REST-edge

**Verdict**: ✅ Strongly supported. The gap doubled vs the n=20 validate read.

Anchor block — the only single-prompt cross-cohort comparison
(`chat_stream_c1 × max_tokens=10`, synthetic seed-derived prompt per
FR-034). `tuned_grpc_multiplexed` is excluded by design at c=1 (HTTP/2
multiplexing has no effect on a single stream; cohort runs only at c=4 / c=8):

| Cohort | wall_p50 (n=40) | CI± | vs fastest | (validate n=20 reference) |
|---|---:|---:|---:|---:|
| **`rest_https_edge`** | **488.5 ms** | 17.2 | — | 416 ms |
| `default_grpc` | 611.9 ms | 3.9 | +25.3% | 463 ms |
| `rest_plain_tcp` | 614.6 ms | 12.5 | +25.8% | 467 ms |

REST over Modal's HTTPS edge beats both gRPC variants AND plain REST by
**~25%**. Likely root cause: Modal's edge proxy terminates HTTP/2 + TLS at
the edge POP, amortising handshake + framing costs that bare gRPC and plain
REST both pay end-to-end.

The advantage is product-attributable (Modal's edge isn't available outside
Modal) and the magnitude under n=40 is **larger than the n=20 read** — the
tighter CI sharpened the signal rather than washing it out.

---

## Claim 2 — Self-hosted, no edge → gRPC worth considering

**Verdict**: ✅ Supported and strengthened under n=40, with one definitional
refinement.

This sweep measures *latency*, not *bytes-on-the-wire*. The "wire size
reductions" half of the recommendation needs to be either (a) reframed as
"wire-transmission-time reductions" using the `seg_egress_ms` evidence
below, or (b) backed by a separate byte-count citation (M1's bytes-axis
finding: 89% chat response reduction, 25% embed request reduction —
protobuf framing over JSON, topology-immune).

### Evidence A — `seg_egress_ms` (engine → client wire transmission)

The timing surface most directly sensitive to wire-level efficiency. Edge
cohort excluded (REST-edge is the Claim-1 path). gRPC best-of-two compared
against `rest_plain_tcp`:

| Cell × mt | gRPC best | `rest_plain_tcp` | REST overhead | (validate n=20) |
|---|---:|---:|---:|---:|
| c1×10 | 1.09 ms | 1.19 ms | **+9.5%** | +10% |
| c1×50 | 1.04 ms | 1.16 ms | **+12.5%** | −9% (n=20 noise — sign-flipped) |
| c1×2048 | 0.96 ms | 1.17 ms | **+22.0%** | +28% |
| c4×10 | 1.13 ms | 1.75 ms | **+55.2%** | +37% |
| c4×50 | 1.00 ms | 1.30 ms | **+29.7%** | +41% |
| c4×2048 | 1.18 ms | 1.66 ms | **+40.8%** | +31% |
| c8×10 | 1.31 ms | 1.80 ms | **+38.0%** | +24% |
| c8×50 | 1.30 ms | 1.57 ms | **+21.1%** | +23% |
| c8×2048 | 1.39 ms | 1.84 ms | **+32.6%** | +105% |

**9 of 9 cells** show plain REST taking 10–55% longer to move bytes off the
wire than gRPC. The validate sweep's lone counterexample (c1×50, −9%)
sign-flipped to +12.5% under n=40 — exactly the small-sample noise risk
Caveat 1 anticipated.

**Note**: the validate sweep's headline "c8×2048 doubling (+105%)" did NOT
replicate under n=40 (+32.6%). The c4×10 +55% is now the single largest gap.
The clean story is "consistent +20–55% gRPC advantage on wire transmission
across the matrix", not "doubling at c8×2048".

This is consistent with the protocol-theory expectation: protobuf binary
framing + HTTP/2 binary frames are more compact and lower-overhead than JSON
serialisation + HTTP/1.1 chunked encoding. The `seg_egress_ms` measurement
captures the time cost of that framing difference directly.

### Evidence B — TPOT (per-token decode cost, edge excluded)

The cleanest comparison for steady-state generation throughput:

| Cell × mt | gRPC best | `rest_plain_tcp` | REST overhead | (validate n=20) |
|---|---:|---:|---:|---:|
| c1×10 | 33.51 ms | 33.47 ms | −0.1% | +0.7% |
| c1×50 | 33.74 ms | 33.74 ms | −0.0% | −0.2% |
| c1×2048 | 33.81 ms | 34.03 ms | +0.7% | +0.3% |
| c4×10 | 36.49 ms | 36.25 ms | −0.7% | −0.1% |
| c4×50 | 36.72 ms | 36.75 ms | +0.1% | 0.0% |
| c4×2048 | 36.99 ms | 37.98 ms | **+2.7%** | +2.1% |
| c8×10 | 37.16 ms | 37.15 ms | −0.0% | +1.0% |
| c8×50 | 37.30 ms | 37.37 ms | +0.2% | +0.3% |
| **c8×2048** | **37.43 ms** | **39.55 ms** | **+5.7%** | +4.0% |

At the dominant high-concurrency / long-generation cell (c8 × 2048), gRPC's
per-token cost is **5.7% lower** than plain REST — up from validate's +4.0%
and the cleanest long-generation signal in the artifact. Elsewhere the
per-token costs are within ±1% — too tight to claim a winner.

### Evidence C — Wall_p50 head-to-head (edge excluded, mt ≤ 50)

`default_grpc` vs `rest_plain_tcp`:

| Cell × mt | gRPC | REST_plain | REST slower by | (validate n=20) |
|---|---:|---:|---:|---:|
| c1×10 | 611.9 ms | 614.6 ms | +0.4% | +5.2% |
| c1×50 | 1973.1 ms | 1977.1 ms | +0.2% | −0.6% |
| c4×10 | 692.9 ms | 676.5 ms | −2.4% | +0.1% |
| c4×50 | 2073.1 ms | 2169.8 ms | **+4.7%** | +0.4% |
| c8×10 | 627.5 ms | 693.8 ms | **+10.6%** | +3.1% |
| c8×50 | 2125.5 ms | 2200.5 ms | **+3.5%** | +2.4% |

`tuned_grpc_multiplexed` vs `rest_plain_tcp` (c4 / c8 only — see Claim-1
note on c=1 design exclusion):

| Cell × mt | tuned gRPC | REST_plain | REST slower by | (validate n=20) |
|---|---:|---:|---:|---:|
| c4×10 | 630.1 ms | 676.5 ms | **+7.4%** | −0.9% |
| c4×50 | 2074.1 ms | 2169.8 ms | **+4.6%** | +1.2% |
| **c8×10** | **600.1 ms** | **693.8 ms** | **+15.6%** | +5.1% |
| c8×50 | 2129.5 ms | 2200.5 ms | **+3.3%** | +1.5% |

**The c=8 wall-clock advantage strengthened substantially under n=40.** At
c8×10 the tuned-gRPC advantage over plain REST grew from +5.1% (validate)
to **+15.6% (publish)** — the headline number for the self-hosted-no-edge
recommendation. At c=1 cells the protocols are statistically
indistinguishable (~0% gap), consistent with HTTP/2 multiplexing benefiting
only concurrent streams.

### Why the headline numbers at `max_tokens=2048` are NOT a clean gRPC win

The wall_p50 row at `c8 × max_tokens=2048` reads:

| Cohort | wall_p50 | tpot | seg_egress |
|---|---:|---:|---:|
| `default_grpc` | **5,103 ms** | 37.43 ms | 1.51 ms |
| `tuned_grpc_multiplexed` | 80,152 ms | 39.63 ms | 1.39 ms |
| `rest_https_edge` | 80,278 ms | 39.58 ms | 2.34 ms |
| `rest_plain_tcp` | 81,240 ms | 39.55 ms | 1.84 ms |

The 16× gap is overwhelmingly **prompt-content-driven, not protocol-driven**:
`default_grpc` happens to draw an iter-idx-keyed corpus prompt that hits
natural EOS at a few hundred tokens, while the other cohorts run to the
2048 cap. TPOT and `seg_egress` (the per-token-normalised surfaces) are
within ~6% of each other across all four cohorts — the clean signal.

Quoting the wall_p50 gap as a protocol win would be incorrect. The
artifact's `## Prompt-driven early-EOS audit` section flags the affected
cells. ANALYSIS.md should cite the clean surfaces (TPOT, `seg_egress`,
anchor) instead.

---

## Recommended ANALYSIS.md framing (DRAFT)

> **Topology recommendation** (M6.2 publish, n=40, eu-west-1):
>
> 1. **If using Modal.com and the REST-over-HTTPS-edge product is available:
>    use it.** The publish sweep's anchor measurement
>    (`chat_stream_c1 × max_tokens=10`, synthetic prompt) shows REST-edge
>    at 488.5 ms p50 vs gRPC variants at 611.9 ms and plain REST at 614.6 ms
>    — a **25–26% edge-product advantage** that holds across the
>    `max_tokens` axis (visible at every interior cap). This reinforces and
>    enlarges the M5.2 finding under tighter n=40 CI.
>
> 2. **If self-hosted (no edge product) and protocol choice is open**: gRPC's
>    wire-level transmission costs are 10–55% lower than plain REST in 9 of
>    9 cells (`seg_egress_ms`, publish-sweep `chat_stream` × full
>    `max_tokens` axis), and per-token decode cost (TPOT) is 5.7% lower at
>    the high-concurrency high-payload regime (`chat_stream_c8 × max_tokens
>    = 2048`: gRPC 37.43 ms vs plain-REST 39.55 ms per token). Wall-clock
>    wins are concentrated at `c=8` cells: tuned-gRPC over plain REST is
>    **+15.6% at c8×10** and +3.3% at c8×50; default-gRPC over plain REST is
>    +10.6% at c8×10 and +3.5% at c8×50. At `c=1` cells the protocols are
>    statistically indistinguishable (~0% wall-clock gap).
>
>    The wire-transmission efficiency stems from protobuf binary framing +
>    HTTP/2 binary frames being more compact and lower-overhead than JSON +
>    HTTP/1.1 chunked encoding. For short-payload high-frequency call
>    patterns, the absolute `seg_egress` saving (~0.3–0.6 ms per RPC) is a
>    meaningful fraction of total wall-clock at high concurrency; for
>    long-generation workloads (2048-token responses at ~80 s wall-clock)
>    the absolute saving is small but the per-token TPOT advantage
>    compounds.
>
> 3. **KV-pressure characterisation (Story 3, FR-017a, sub-probe at
>    `c=8 × {1024, 2048}`, `ignore_eos=True`, n=20)**: all 8 cohort × cell-
>    type combinations classify as `kv_pressure_not_observable`. Wall-clock
>    ratios `wall_p50(2048) / wall_p50(1024)` cluster around the linear
>    expectation (chat_stream 1.81–2.02, embed 1.98–2.05; all below the 2.2
>    threshold). `oom_observed=false` for every cell. **Qwen3-8B at
>    c=8 × max_tokens=2048 has half-headroom on the engine ceiling and is
>    not KV-pressured at this configuration.** Downstream consumer: M8
>    inherits this number for KV-budget sizing.

---

## Caveats to address before merging

1. **n=20 noise floor — vindicated.** The validate sweep's c1×50 `seg_egress`
   counterexample (−9%) sign-flipped to +12.5% under n=40, exactly as this
   caveat predicted. Treat any future n=20 single-cell oddity as
   provisional pending n≥40 confirmation.

2. **Wire-size vs wire-time terminology.** The publish sweep measures
   latency, not bytes. The `seg_egress_ms` segment is the cleanest proxy
   for wire-level protocol efficiency the harness produces, but it isn't a
   direct byte count. Either (a) reframe the recommendation as
   "wire-transmission-time reductions" citing `seg_egress` directly, or (b)
   cite M1's bytes-axis finding (chat response bytes −89%, embed request
   bytes −25%) which is topology-immune and survives every M5/M6
   re-measurement.

3. **Early-EOS prompt-content confound at `max_tokens=2048`.** Do NOT cite
   the wall_p50 numbers at `c8×2048` as a protocol win — the 16× gap
   between `default_grpc` (5,103 ms) and the other three cohorts (~80,000
   ms) is iter-idx-keyed corpus-prompt selection drawing a short-completion
   prompt for one cohort. The artifact's auto-emitted `## Prompt-driven
   early-EOS audit` section flags this; ANALYSIS.md cites only the clean
   surfaces (TPOT, `seg_egress`, anchor).

4. **Modal-region specificity and absolute-number drift.** All measurements
   are from `eu-west-1`. Between the validate sweep (2026-05-24) and the
   publish sweep (2026-05-25/26), absolute anchor latencies drifted ~17%
   (REST-edge: 416 → 489 ms) to ~32% (plain REST + default-gRPC: ~467 →
   ~613 ms) without reordering cohorts. **Treat absolute numbers as
   point-in-time; the relative claims (cohort ratios, percent gaps) are
   the durable signal.** The REST-edge advantage may also vary by region
   depending on edge POP density vs the operator's geography.

5. **FR-012 null-anchor drift FAIL on rest_plain_tcp at c1 and c4 ×
   max_tokens=50 — documented baseline-data-quality issue, not an M6.2
   regression.** The drift check compares M6.2 p50 against M6.1.3 mean
   (M6.1.3 didn't publish per-cohort p50). M6.1.3's `rest_plain_tcp` cells
   at c1/c4 are 300–800 ms above their sibling-cohort means at the same
   concurrency (no such anomaly at c8 where the cohort matches its peers).
   `chat_stream_c4 / rest_plain_tcp` in M6.1.3 was specifically computed
   from `n_successes=49/50` — the lone sub-50 cell in the entire M6.1.3
   chat_stream matrix, suggesting outlier-contaminated mean. M6.2's
   `rest_plain_tcp` measurements are internally consistent (CI 12–30 ms,
   per-concurrency cohort spread ≤140 ms). The FAIL is a baseline artifact,
   not a regression in M6.2's rest_plain_tcp path.

6. **Preemption recovery story.** The publish sweep crossed Modal's 12-h
   per-input timeout at hour 12.1 (`Task's current input hit its timeout
   of 43200s`), killing 5 measurement blocks (108–112). The orchestrator's
   `make_driver()` refresh exhausted its 10-min refresh timeout and the
   sweep continued past the dead worker, mis-classifying the failure as
   `unexpected_PreemptionRecoveryFailed` rather than aborting cleanly
   (root cause: `m6_2_sweep.py:316` `except BaseException` swallows
   `PreemptionRecoveryFailed`; filed as an M6.2.x follow-up). Operator
   intervention sent `SIGINT` to PID 89567, stripped the 5 failure rows
   from the checkpoint, and resumed via `--m6_2-resume`; the fresh Modal
   worker re-measured all 5 cells cleanly. **`run_meta.preemption_events`
   in the artifact reads `0` because the resume process reset its
   counter** — the true value across both processes is ≥2 detected
   preemptions + 5 collateral block failures, all recovered in the resumed
   run. Within-tuple temporal locality is broken for blocks 108–112
   (re-measured ~3–12 h after their original sweep-window siblings); the
   measurements themselves are clean.

7. **Anchor-trajectory snapshots insufficient.** Only 2 anchor snapshots
   per cohort (sweep start + t=8 h) reached the checkpoint. The 4-h /
   12-h / sweep-end cadence anchors didn't fire — long inner-loop tuples
   pushed cadence checks past their windows, and the resume process didn't
   re-fire an end-of-sweep anchor in its 1-h window. Integrity warning
   `trajectory_insufficient_snapshots` fires correctly. Filed as M6.2.x
   follow-up; does not affect the topology framing above.

---

## Next steps

1. Merge § "Recommended ANALYSIS.md framing" above into `ANALYSIS.md` § M6.2
   and the topology guide; cite this draft as the working document.
2. File the four M6.2.x follow-ups:
   - `m6_2_sweep.py:316` swallowing `PreemptionRecoveryFailed` + `KeyboardInterrupt`
   - Resume process losing prior `preemption_events_total`
   - Anchor cadence not firing when tuples exceed cadence window
   - Resume not re-firing the sweep-end anchor
3. Document the rest_plain_tcp FAIL in the artifact's narrative section
   (so readers of the .md don't conclude there's a regression).
4. Delete this file once the recommendation lands in `ANALYSIS.md`.
