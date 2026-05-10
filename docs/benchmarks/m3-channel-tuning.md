# M3 — gRPC Channel-Level Tuning

**Source JSON:** [`m3-channel-tuning.json`](./m3-channel-tuning.json)
**Spec:** `specs/015-m3-protobuf-grpc-tuning/spec.md`
**Sweep run:** `bench-results/m3-full/m3-channel-tuning.json` (n=30 iters/cell, seed=0, mock vLLM engine)
**Hardware:** macOS Apple Silicon, CPU-only (mock engine — no real vLLM execution)

---

## Executive summary

The four-axis P1 sweep (`max_message_size`, `keepalive`, `compression`, `http2_framing`) at three canonical embedding widths (2048, 4096, 8192) × two paths (`embed`, `chat_stream`) ran 24 axis × width × path cells. **Every cell returned `no_winner`** under SC-003: no candidate channel configuration's wire-byte 95% CI fell strictly below the M1-baseline's 95% CI in the same batch.

**SC-001 — recommended channel config per canonical width:**

| `hidden_size` | Path | Recommendation |
|---|---|---|
| 2048 | embed + chat_stream | **`M1_BASELINE`** (no candidate cleared SC-003) |
| 4096 | embed + chat_stream | **`M1_BASELINE`** (no candidate cleared SC-003) |
| 8192 | embed + chat_stream | **`M1_BASELINE`** (no candidate cleared SC-003) |

**SC-002 — `max_message_size` binding width:** the gRPC default 4 MiB ceiling is **never binding** at any canonical width up to and including 8192. Embed payloads sit at ~131 KB (h=2048), ~262 KB (h=4096), and ~524 KB (h=8192) — roughly 8× under the default ceiling at the largest canonical width. Streaming chat payloads are ~330 B per RPC. A binding width on the embed path would land somewhere above hidden_size ≈ 32k (extrapolating linearly: ~2.1 MB at h=32768), well outside the canonical M3 range.

**P1 frozen channel config (FR-008):** `M1_BASELINE` (no axis won → all four axes default to baseline). See [`p1_frozen_config`](#p1-frozen-channel-config-fr-008) below; this is the configuration US2 measures against.

---

## Methodology

- **Win criterion (SC-003):** a candidate is a winner only when its wire-byte 95% CI is strictly below the same-batch M1-baseline's 95% CI. The orchestrator's `build_recommendations` evaluates this on `bytes` (per-RPC `request_wire_bytes + response_wire_bytes`, application-level / pre-compression).
- **Per-cell repetition:** n=30 iterations/cell with deterministic seeding (seed=0). The 95% CI is computed via a hard-coded t-table (no `scipy` dependency) — see `tools/benchmark/src/vllm_grpc_bench/ci.py`.
- **Reference baseline:** `M1_BASELINE` (empty server/client options, no compression). All deltas are vs. M1-baseline measured on the same M3 hardware in the same sweep batch — per `research.md` R-8 / spec FR-005, comparisons against M1's pre-recorded GPU numbers are explicitly **not** valid since M3 runs on CPU with the mock engine.
- **Mock engine:** `MockEngine` provides a vLLM `engine`-shaped surface; `generate(...)` paces tokens at `tokens_per_second` and `encode(...)` returns deterministic embedding tensors of the requested `hidden_size`. The mock satisfies the slice consumed by both `ChatServicer` and `CompletionsServicer`.
- **Long-stream cohort (FR-011):** `m3_long_stream.json` is included for the keepalive and `http2_framing` axes on the `chat_stream` path at `hidden_size=4096` only (per the recent sweep restriction in commit `723f57d`). The cohort emits ≥1024 tokens at ~50 ms/token so wall-clock crosses `KEEPALIVE_AGGRESSIVE` ping intervals multiple times per RPC.
- **Wire-byte caveat for the compression axis:** the `bytes` metric measures the application-level message size as seen by the servicer/client, **not** the post-compression on-wire byte count. Compression's on-wire effect is therefore not directly observable from this metric; its CPU-time tax is.
- **Time-axis observations (advisory, not SC-003):** per-cell mean wall-clock and CIs are recorded but `build_recommendations` does not evaluate SC-003 on time. Several cells show time CIs that look like wins against the within-batch baseline, but baseline time itself varies notably across axis batches (e.g., 184 ms → 205 ms for chat_stream h=2048 m1_chat between the `max_message_size` and `compression` batches), suggesting cross-batch system-load variability rather than axis-attributable time wins. Time deltas are presented in each axis section as advisory observations.

---

## Axis 1 — `max_message_size`

**Citation:** `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` (channel-args plumbing); `~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc` (defaults).

**Verdict (all cells):** `no_winner` — bumping `grpc.max_send_message_length` / `grpc.max_receive_message_length` to 16 MiB or `unlimited` does not reduce wire bytes (deltas are within ±0.7% of baseline at chat_stream and within ±0.001% at embed) at any canonical width.

| Path | Width | Candidate | Δbytes (abs) | Δbytes (%) | Candidate bytes 95% CI | Verdict |
|---|---|---|---:|---:|---|---|
| embed | 2048 | `MAX_MSG_16MIB` | +0.63 | +0.0005% | [131141.60, 131144.67] | no_winner |
| embed | 2048 | `MAX_MSG_UNLIMITED` | -0.30 | -0.0002% | [131140.20, 131144.20] | no_winner |
| embed | 4096 | `MAX_MSG_16MIB` | +0.50 | +0.0002% | [262212.79, 262215.94] | no_winner |
| embed | 4096 | `MAX_MSG_UNLIMITED` | -0.27 | -0.0001% | [262212.65, 262214.55] | no_winner |
| embed | 8192 | `MAX_MSG_16MIB` | +0.93 | +0.0002% | [524356.65, 524360.28] | no_winner |
| embed | 8192 | `MAX_MSG_UNLIMITED` | +1.30 | +0.0002% | [524356.93, 524360.73] | no_winner |
| chat_stream | 2048 | `MAX_MSG_16MIB` | +2.10 | +0.6344% | [330.35, 335.85] | no_winner |
| chat_stream | 2048 | `MAX_MSG_UNLIMITED` | -0.37 | -0.1108% | [327.68, 333.59] | no_winner |
| chat_stream | 4096 | `MAX_MSG_16MIB` | -2.50 | -0.7522% | [327.10, 332.64] | no_winner |
| chat_stream | 4096 | `MAX_MSG_UNLIMITED` | -1.43 | -0.4313% | [328.15, 333.71] | no_winner |
| chat_stream | 8192 | `MAX_MSG_16MIB` | -1.33 | -0.4023% | [327.37, 332.76] | no_winner |
| chat_stream | 8192 | `MAX_MSG_UNLIMITED` | +2.20 | +0.6639% | [331.50, 335.70] | no_winner |

**Interpretation.** The default `max_message_size` is not a constraint at any canonical width on either path. Embed payloads are dominated by the dense float32 tensor (4 × `hidden_size` × prompt-batch-size bytes); even at h=8192 the response sits well under 1 MiB, far below the 4 MiB default. Bumping the limit changes nothing because the pre-existing default is already permissive enough.

---

## Axis 2 — `keepalive`

**Citation:** `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc` (keepalive timer logic).

**Verdict (all cells):** `no_winner` on bytes. Long-stream resilience observation: `KEEPALIVE_AGGRESSIVE` (10 s ping interval / 10 s timeout) successfully completes the ~52 s synthetic long-stream RPC at h=4096 with no connection drops — rebutting the spec edge-case concern that aggressive keepalive could tear down long-streaming connections.

| Path | Width | Candidate | Δbytes (abs) | Δbytes (%) | Candidate bytes 95% CI | Verdict |
|---|---|---|---:|---:|---|---|
| embed | 2048 | `KEEPALIVE_AGGRESSIVE` | -0.03 | -0.0000% | [131141.08, 131143.86] | no_winner |
| embed | 2048 | `KEEPALIVE_RELAXED` | -0.03 | -0.0000% | [131140.73, 131144.20] | no_winner |
| embed | 4096 | `KEEPALIVE_AGGRESSIVE` | +0.07 | +0.0000% | [262212.57, 262215.30] | no_winner |
| embed | 4096 | `KEEPALIVE_RELAXED` | -0.10 | -0.0000% | [262212.56, 262214.97] | no_winner |
| embed | 8192 | `KEEPALIVE_AGGRESSIVE` | +0.47 | +0.0001% | [524356.55, 524359.45] | no_winner |
| embed | 8192 | `KEEPALIVE_RELAXED` | +2.53 | +0.0005% | [524358.36, 524361.77] | no_winner |
| chat_stream | 2048 | `KEEPALIVE_AGGRESSIVE` | +2.50 | +0.7553% | [330.66, 336.34] | no_winner |
| chat_stream | 2048 | `KEEPALIVE_RELAXED` | +0.37 | +0.1108% | [328.50, 334.24] | no_winner |
| chat_stream | 4096 | `KEEPALIVE_AGGRESSIVE` | -1.30 | -0.3911% | [328.76, 333.37] | no_winner |
| chat_stream | 4096 | `KEEPALIVE_RELAXED` | -1.03 | -0.3109% | [328.97, 333.70] | no_winner |
| chat_stream | 8192 | `KEEPALIVE_AGGRESSIVE` | -0.90 | -0.2716% | [328.22, 332.78] | no_winner |
| chat_stream | 8192 | `KEEPALIVE_RELAXED` | +2.40 | +0.7242% | [331.90, 335.70] | no_winner |

**Long-stream cohort (chat_stream, h=4096, FR-011):**

| Candidate | Mean wall-clock (s) | Mean wire bytes | Outcome |
|---|---:|---:|---|
| `M1_BASELINE` | 52.72 | 9127 | n=30 successful, no drops |
| `KEEPALIVE_AGGRESSIVE` | 52.73 | 9130 | n=30 successful, no drops |
| `KEEPALIVE_RELAXED` | 52.84 | 9132 | n=30 successful, no drops |

**Interpretation.** Keepalive options have no measurable effect on wire bytes for short RPCs (the ping frames don't accrue against application-level message bytes). For long streams the more interesting question — does aggressive keepalive cause the upstream servicer to drop the connection? — is answered: at the M1 servicer's defaults (no `GRPC_ARG_KEEPALIVE_PERMIT_WITHOUT_CALLS=0`), aggressive 10 s pings are tolerated.

---

## Axis 3 — `compression`

**Citation:** `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` (compression argument); `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc` (frame-level compression handling).

**Verdict (all cells):** `no_winner` on bytes. **Time tax recorded:** gzip on dense-float embed payloads adds **+18% to +39%** per-RPC wall-clock with no measurable wire-byte savings in the application-level metric — an honest negative result per Constitution V.

| Path | Width | Candidate | Δbytes (abs) | Δbytes (%) | Δtime (%) | Candidate bytes 95% CI | Verdict |
|---|---|---|---:|---:|---:|---|---|
| embed | 2048 | `COMPRESSION_GZIP` | -1.20 | -0.0009% | +18.39% | [131139.79, 131142.81] | no_winner |
| embed | 4096 | `COMPRESSION_GZIP` | +1.53 | +0.0006% | +38.99% | [262213.72, 262217.08] | no_winner |
| embed | 8192 | `COMPRESSION_GZIP` | +0.77 | +0.0001% | +39.40% | [524356.84, 524359.76] | no_winner |
| chat_stream | 2048 | `COMPRESSION_GZIP` | +0.90 | +0.2719% | -0.14% | [328.88, 334.92] | no_winner |
| chat_stream | 4096 | `COMPRESSION_GZIP` | +0.27 | +0.0802% | +1.38% | [330.31, 334.96] | no_winner |
| chat_stream | 8192 | `COMPRESSION_GZIP` | -0.23 | -0.0704% | +2.43% | [329.23, 333.10] | no_winner |

**Interpretation.** This matches the prediction in `research.md` R-7: dense float32 embedding tensors have near-uniform high-entropy bytes, so gzip's dictionary compression does not shrink them while still incurring full encode/decode CPU cost on both ends. The 39% time tax at h=4096 and h=8192 is the dominant signal. **Recommendation: do not enable transport-level compression for the embed path under any canonical width.** For chat_stream the time tax is small (~1–2%), but no wire-byte win materializes either.

---

## Axis 4 — HTTP/2 framing (`HTTP2_BDP_PROBE`)

**Citation:** `~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc` (chttp2 stream/transport flow-control state); `~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc` (BDP probe state machine).

**Verdict (all cells):** `no_winner` on bytes. Long-stream cohort included at h=4096 (FR-011) — see below.

| Path | Width | Candidate | Δbytes (abs) | Δbytes (%) | Candidate bytes 95% CI | Verdict |
|---|---|---|---:|---:|---|---|
| embed | 2048 | `HTTP2_BDP_PROBE` | -0.63 | -0.0005% | [131139.82, 131143.92] | no_winner |
| embed | 4096 | `HTTP2_BDP_PROBE` | -0.50 | -0.0002% | [262211.59, 262215.14] | no_winner |
| embed | 8192 | `HTTP2_BDP_PROBE` | +0.93 | +0.0002% | [524356.82, 524360.12] | no_winner |
| chat_stream | 2048 | `HTTP2_BDP_PROBE` | +1.90 | +0.5740% | [330.62, 335.18] | no_winner |
| chat_stream | 4096 | `HTTP2_BDP_PROBE` | +0.63 | +0.1906% | [329.92, 336.08] | no_winner |
| chat_stream | 8192 | `HTTP2_BDP_PROBE` | -1.20 | -0.3621% | [327.47, 332.93] | no_winner |

**Long-stream cohort (chat_stream, h=4096, FR-011):**

| Candidate | Mean wall-clock (s) | Mean wire bytes | Outcome |
|---|---:|---:|---|
| `M1_BASELINE` | 53.44 | 9124 | n=30 successful |
| `HTTP2_BDP_PROBE` | 53.42 | 9143 | n=30 successful |

**Interpretation.** BDP-probe-driven flow-control window expansion does not change application-level wire bytes (it tunes when WINDOW_UPDATE frames are sent, not what application bytes get serialized). On the loopback CPU-only mock used here there is no measurable BDP latency to absorb, so the candidate has no opportunity to manifest a bytes win. A re-test on a higher-latency cross-host path (real Modal A10G ↔ local) would be a more discriminating workload — out of scope for M3's CPU-only mock.

---

## Off-canonical / exploratory cells

The current sweep ran no off-canonical widths. If a future re-run includes them (per the relaxed `--width` contract that accepts arbitrary positive integers), they will appear here in a separate sub-table marked exploratory and will be excluded from primary recommendations per the spec's canonical-widths constraint.

---

## P1 frozen channel config (FR-008)

All four P1 axes have a recorded outcome in `{recommend, no_winner, not_measurable}` — specifically, all 24 axis × width × path verdicts are `no_winner`. The frozen P1 channel config (used as the P2 baseline) is therefore:

```text
p1_frozen_config = M1_BASELINE
  - max_message_size:  default (gRPC built-in, ~4 MiB)
  - keepalive:         default
  - compression:       default (NoCompression)
  - http2_framing:     default
```

US2 measures schema-level candidates against this baseline; the JSON companion publishes this under `p1_frozen_config` for `--frozen-channel m1-baseline` invocation.

---

## Reproducing this report

```bash
# Full sweep (≈ ran in this run, see bench-results/m3-full/sweep.log)
python -m vllm_grpc_bench --m3 --out-dir bench-results/m3-full

# Smoke check (≈ 30 s, no measurement)
python -m vllm_grpc_bench --m3 --smoke \
    --axis max_message_size --width 2048 --path embed
```

See `specs/015-m3-protobuf-grpc-tuning/quickstart.md` for the full reproducer.
