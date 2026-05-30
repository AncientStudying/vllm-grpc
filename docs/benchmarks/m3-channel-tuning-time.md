# M3 — gRPC Channel-Level Tuning (Wall-Clock Time)

**Companion to:** [`m3-channel-tuning.md`](./m3-channel-tuning.md) (bytes-axis report from PR #17)
**Source JSON:** [`m3-channel-tuning-time.json`](./m3-channel-tuning-time.json)
**Spec:** `specs/015-m3-protobuf-grpc-tuning/spec.md` (US3 / Phase A; SC-006; FR-014)
**Re-analysis input:** `bench-results/m3-full/m3-channel-tuning.json` (n=30 sweep, seed=0; same data as PR #17)
**Hardware:** macOS Apple Silicon, CPU-only (mock vLLM engine — no real model execution)

---

## Executive summary

Phase A re-analyses the n=30 sweep data already collected in PR #17 against the **wall-clock time metric** (TTFT for chat_stream cells per FR-014; total per-RPC wall-clock for embed cells). PR #17's bytes-only verdict was `no_winner` across all 24 cells; the time-axis re-analysis surfaces **four real wins** that the bytes evaluation missed:

| # | Axis | Path | Width | Metric | Winner | Δ vs predecessor baseline |
|---|---|---|---|---|---|---:|
| 1 | `max_message_size` | chat_stream | 4096 | TTFT | **`max-msg-16mib`** | **−31.39%** |
| 2 | `max_message_size` | chat_stream | 2048 | TTFT | **`max-msg-16mib`** | **−28.66%** |
| 3 | `keepalive` | chat_stream | 2048 | TTFT | **`keepalive-aggressive`** | **−24.20%** |
| 4 | `max_message_size` | embed | 4096 | wall-clock | **`max-msg-16mib`** | −2.43% |

These wins survived the noise-stability check against **all** same-cell M1_BASELINE cohorts (per `research.md` R-12), not just the predecessor-paired one. The default 4 MiB `max_message_size` does NOT bind for any embed payload at canonical widths (per PR #17's SC-002 finding), yet bumping it to 16 MiB reduces TTFT by ~30% on chat_stream — the mechanism is not wire-bytes (the candidate's bytes are within ±0.7% of baseline) and remains to be characterized; M4's cross-host transport mode is the right next test.

**Two cells fell to `noise_bounded`** — the predecessor pairing claimed a win but the win did not survive against alternative same-cell M1_BASELINE cohorts. These cells re-measure under M4's shared-baseline harness (FR-013):

| Axis | Path | Width | Metric | Cross-baseline spread | Action |
|---|---|---|---|---:|---|
| `keepalive` | embed | 2048 | wall-clock | 13.5% | M4 shared-baseline re-measure |
| `http2_framing` | chat_stream | 4096 | TTFT | 35.2% | M4 shared-baseline re-measure |

**P1 frozen channel config (time-axis):** `max-msg-16mib` is the time-axis winner for `max_message_size`. The other three axes default to `M1_BASELINE` — `keepalive` because the chat_stream/h=2048 win is contradicted by a `noise_bounded` cell at embed/h=2048 within the same axis; `compression` and `http2_framing` because no cell produced a defensible win. See `p1_frozen_config_time` in the JSON companion.

---

## Methodology

Phase A is a **code-only re-analysis** of the data already collected in PR #17 — no new sweeps. Inputs: cohort-level `time_seconds` (mean+CI) and per-sample `time_to_first_token_seconds` (already populated for chat_stream cells in the existing JSON). Outputs: per-cell time-axis verdicts using the same SC-003 statistical bar (95% CI separation) as the bytes-axis report.

The time-axis recommendation builder (`m3_sweep.build_recommendations(metric="time")` for embed and `metric="ttft"` for chat_stream) differs from the bytes builder in three ways:

1. **Grouping key** is `(path, hidden_size, corpus_subset)` so the long-stream cohort gets its own verdict separate from the regular `m1_chat` chat_stream cohort. The bytes builder grouped only by `(path, hidden_size)` and the long-stream candidates were folded into the same bucket as `m1_chat` (mostly harmless for bytes, since the m3_long_stream candidate's bytes never beat the m1_chat baseline anyway, but conceptually wrong).
2. **Baseline pairing** is *immediate-predecessor in cohort run-order* rather than "first M1_BASELINE in group". Per `research.md` R-12, same-cell M1_BASELINE measurements drifted by **13% on total wall-clock** across the four axis batches in PR #17's run, but only **<0.01% on bytes**. Pairing each candidate with the baseline measured immediately before it in the same axis batch removes the drift contamination.
3. **`noise_bounded` verdict** (FR-005) is emitted when the predecessor pairing claims a win but the win does **not** survive against at least one alternative same-cell M1_BASELINE — i.e., the conclusion depends on which baseline you happened to pair with. These cells are flagged for M4 re-measurement.

**Why TTFT, not total wall-clock, for chat_stream** (FR-014, R-11, R-13): the mock engine's deterministic per-token pacing (`tokens_per_second≈200`) inserts ~5 ms of `time.sleep` between each yielded token. With ~32 tokens emitted per RPC, ~160 ms of the ~184 ms total wall-clock is artificial pacing. Channel-axis effects on transport+serialization are diluted to <5% of total signal — well below the cross-batch noise floor. TTFT (per-sample `time_to_first_token_seconds`) isolates connection-establishment and first-byte transport time from per-token pacing and is the only diagnostic chat_stream time metric on the M3 harness. M4's `--no-pacing` mode (FR-012) will unblock total chat_stream wall-clock as a defensible verdict metric.

**Why this re-analysis isn't a full M4 substitute**: cells where the noise floor swallowed the signal (the two `noise_bounded` cells in this report) cannot be salvaged by re-analysis alone — they need fresh measurement under M4's harness changes. Per `research.md` R-14, Phase A bounds what the existing data can support; M4 produces the definitive time-axis report.

---

## Axis 1 — `max_message_size`

**Citation:** `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` (channel-args plumbing); `~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc` (defaults).

**Verdicts:**

| Path | Width | Corpus | Metric | Verdict | Winner | Δ% |
|---|---|---|---|---|---|---:|
| embed | 2048 | m1_embed | wall-clock | no_winner | — | — |
| embed | 4096 | m1_embed | wall-clock | **recommend** | **`max-msg-16mib`** | **−2.43%** |
| embed | 8192 | m1_embed | wall-clock | no_winner | — | — |
| chat_stream | 2048 | m1_chat | TTFT | **recommend** | **`max-msg-16mib`** | **−28.66%** |
| chat_stream | 4096 | m1_chat | TTFT | **recommend** | **`max-msg-16mib`** | **−31.39%** |
| chat_stream | 8192 | m1_chat | TTFT | no_winner | — | — |
| chat_stream | 4096 | m3_long_stream | TTFT | no_winner | — | — |

**Interpretation.** The default 4 MiB `max_message_size` does not bind at any canonical width on the bytes axis (per PR #17's SC-002 finding — embed payloads cap at ~524 KB at h=8192). Yet bumping the limit to 16 MiB consistently and substantially **reduces TTFT** on chat_stream at the two smaller widths. This was invisible in the bytes-axis sweep because the wire-byte size doesn't change — the candidate ships the same payload but the first-byte timing improves by ~30%.

The mechanism is not the limit binding (it doesn't, at these payload sizes). Plausible candidates: grpcio's channel-args plumbing pre-allocates differently-sized receive/send buffers when an explicit `max_message_size` is set, which may shorten the path from RPC start to first-yielded chunk on the streaming response. The citation points to `_channel.py` (channel-args plumbing) and `channel_args.cc` (defaults) as the right entry points to characterize the mechanism — that work belongs in M4 alongside the cross-host transport re-test.

The win **survives all 4 alternative same-cell M1_BASELINE cohorts** for both chat_stream cells (per `research.md` R-12 noise-bounded check) — the conclusion is robust across the cross-batch drift PR #17's harness exhibited.

The h=8192 chat_stream cell did not produce a win — the larger payload may dilute first-byte effects. The long-stream cohort at h=4096 also did not produce a win, suggesting the first-byte-window effect saturates beyond a certain stream length.

---

## Axis 2 — `keepalive`

**Citation:** `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc` (keepalive timer logic).

**Verdicts:**

| Path | Width | Corpus | Metric | Verdict | Winner | Δ% |
|---|---|---|---|---|---|---:|
| embed | 2048 | m1_embed | wall-clock | **noise_bounded** | — | — |
| embed | 4096 | m1_embed | wall-clock | no_winner | — | — |
| embed | 8192 | m1_embed | wall-clock | no_winner | — | — |
| chat_stream | 2048 | m1_chat | TTFT | **recommend** | **`keepalive-aggressive`** | **−24.20%** |
| chat_stream | 4096 | m1_chat | TTFT | no_winner | — | — |
| chat_stream | 8192 | m1_chat | TTFT | no_winner | — | — |
| chat_stream | 4096 | m3_long_stream | TTFT | no_winner | — | — |

**Interpretation.** `keepalive-aggressive` (10 s ping interval, 5 s timeout, ping-without-calls enabled) reduces TTFT by 24% on chat_stream at h=2048 against a baseline that sees no candidate win in the bytes axis. The mechanism is plausible — keepalive ping-without-calls keeps the HTTP/2 connection warm and reduces re-handshake or PING-frame interleaving cost on the first response chunk. PR #17's long-stream cohort proved aggressive keepalive does not destabilize 52-second streams; this Phase A finding adds that it actively *helps* TTFT on shorter chat_stream RPCs at the smallest canonical width. The win survives all 4 alternative same-cell baselines.

The embed/h=2048 cell fell to `noise_bounded`: the predecessor pairing claimed `keepalive-aggressive` as a wall-clock winner, but the win did not survive against 1 alternative same-cell M1_BASELINE. Cross-baseline spread at this cell was 13.5% across 4 baselines — large enough to swallow the candidate's apparent signal. Re-measure under M4's shared-baseline harness (FR-013).

---

## Axis 3 — `compression`

**Citation:** `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` (compression argument); `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc` (frame-level compression handling).

**Verdicts:** all `no_winner` on both metrics across all width × path × corpus cells.

**Interpretation.** Mirrors PR #17's bytes finding (gzip incurs +18% to +39% wall-clock on dense-float embed payloads with no compensating wire-byte savings) into the time axis: gzip is honestly worse on time as well as bytes. The TTFT metric for chat_stream picks up no compression win either — text tokens are short enough that gzip's encode/decode setup dominates first-byte timing without producing offsetting wire savings on the first chunk. **Recommendation: do not enable transport-level gzip compression** under any configuration covered by this milestone.

---

## Axis 4 — HTTP/2 framing (`HTTP2_BDP_PROBE`)

**Citation:** `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc` (chttp2 stream/transport flow-control state); `~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc` (BDP probe state machine).

**Verdicts:**

| Path | Width | Corpus | Metric | Verdict |
|---|---|---|---|---|
| embed | 2048/4096/8192 | m1_embed | wall-clock | no_winner (3 cells) |
| chat_stream | 2048 | m1_chat | TTFT | no_winner |
| chat_stream | 4096 | m1_chat | TTFT | **noise_bounded** |
| chat_stream | 8192 | m1_chat | TTFT | no_winner |
| chat_stream | 4096 | m3_long_stream | TTFT | no_winner |

**Interpretation.** No defensible time-axis win. The chat_stream/h=4096/m1_chat cell shows the largest cross-baseline spread of any cell in the report — **35.2% TTFT spread across 4 same-cell M1_BASELINE cohorts** — which swallowed any candidate signal. This matches the original bytes-axis interpretation: BDP-probe-driven flow-control window expansion has nothing to optimize on a CPU-only loopback transport (no measurable RTT). M4's optional cross-host transport mode is the right next test — a real Modal-A10G-↔-local hop would have RTT for the BDP probe to characterize.

---

## Long-stream cohort observations

The long-stream cohort at chat_stream/h=4096 (per FR-011) produced no time-axis winners on either keepalive or http2_framing — consistent with PR #17's finding that aggressive keepalive does not destabilize long streams (n=30 successful, no drops). The TTFT verdict for the long-stream cohort is `no_winner` for both axes; total wall-clock for the long-stream isn't a useful metric (~52 s is dominated by token-emission pacing).

---

## Limitations and M4 hand-off

This report is bounded by the existing harness's measurement properties. Two cells could not be defensibly verdicted on the existing data and re-measure under M4:

1. **`keepalive` × embed × h=2048** (wall-clock): predecessor pairing claimed `keepalive-aggressive` as winner (mean=52.47 ms), but the win does not survive against 1 alternative same-cell M1_BASELINE. Cross-baseline spread 13.5%. M4's shared-baseline mode (FR-013) eliminates this drift by measuring one large up-front baseline (n≥100) and reusing it.
2. **`http2_framing` × chat_stream × h=4096** (TTFT): predecessor claimed `http2-bdp-probe` as winner (mean=1.64 ms), but the win does not survive against 3 alternative same-cell baselines. Cross-baseline spread 35.2%. Same M4 shared-baseline remedy applies. Additionally, the BDP-probe candidate fundamentally cannot manifest a transport-level win on loopback CPU-only — M4's optional cross-host transport mode is needed to give the candidate a chance.

Beyond these specific cells, M4's `--no-pacing` mode (FR-012) is required before chat_stream **total wall-clock** (as opposed to TTFT) can be defensibly verdicted at all — the mock's deterministic token pacing currently dominates ~87% of total streaming wall-clock under R-11.

The 4 wins recorded in this report all survived multi-baseline noise checks, but the underlying mechanisms (especially the surprising 28-31% TTFT improvement from `max-msg-16mib`) are not characterized — only confirmed empirically. M4's harness redesign + cross-host transport will produce the definitive verdict.

---

## P1 frozen channel config (time-axis)

| Axis | Frozen value | Reason |
|---|---|---|
| `max_message_size` | **`max-msg-16mib`** | Wins on time-metric at multiple cells; survives noise-bounded check. |
| `keepalive` | `default` (M1_BASELINE) | One clean recommend (chat_stream/h=2048) but contradicted by a `noise_bounded` cell within the same axis — conservative fallback per FR-008-equivalent rule. M4 resolves. |
| `compression` | `default` (M1_BASELINE) | No recommend anywhere; gzip is honestly worse on dense-float payloads. |
| `http2_framing` | `default` (M1_BASELINE) | No recommend; 1 noise_bounded cell. M4's cross-host mode is the right next test. |

This is `p1_frozen_config_time` in the JSON companion. **It is more conservative than per-cell findings would suggest**: the `keepalive-aggressive` win on chat_stream/h=2048 is real, but the rule defaults the entire axis to M1_BASELINE because of the `noise_bounded` cell at embed/h=2048. M4 will revisit with cleaner methodology.

The bytes-axis `p1_frozen_config` from PR #17 (M1_BASELINE on all four axes) is **superseded for the `max_message_size` axis only** — `max-msg-16mib` wins on time. The other three axes' bytes verdicts and time verdicts agree on M1_BASELINE.

---

## Reproducing this report

```bash
# Phase A re-analysis (code-only; no new sweeps)
python -m vllm_grpc_bench --m3 --reanalyze bench-results/m3-full/m3-channel-tuning.json
# → bench-results/m3-full/m3-channel-tuning-time.json

# To re-run the underlying sweep from scratch (≈ 0.7-4 hours on CPU):
python -m vllm_grpc_bench --m3 --out-dir bench-results/m3-full
```

See `specs/015-m3-protobuf-grpc-tuning/quickstart.md` for the full reproducer and `specs/015-m3-protobuf-grpc-tuning/research.md` R-11..R-14 for the methodology rationale.
