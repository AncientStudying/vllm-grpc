# M5.1: REST vs gRPC Head-to-Head on Real Wire

## Executive summary

- 18-cell head-to-head matrix (2 paths × 3 widths × 3 concurrencies). 0 `comparison_unavailable`, 0 `low_rtt_caveat`.
- Bytes-axis findings from M1 (89% chat response reduction, ~25% embed request reduction) remain in force unchanged (FR-021) — M5.1 measures time only.
- **Read instruction**: M5.1 measures MockEngine, not real vLLM. Engine cost is held constant across protocols so the verdict reflects the transport + framing component only. Real-engine re-validation is deferred to M7.
- **Methodology — Modal tunnel topology**: both protocols use Modal's plain-TCP `modal.forward(..., unencrypted=True)` so the network path is held constant. The original spec assumed REST would use Modal's HTTPS edge (TLS-terminated, anycast-routed near client); the smoke run measured a ~2× RTT gap that would have dominated every verdict. The FR-019 'REST uses Modal-managed TLS' assumption is voided for M5.1, accepted per Constitution V. M1 ran REST over the HTTPS edge — that difference is part of why M5.1 supersedes M1's time-axis findings.

## Per-cell comparison matrix

### chat_stream

#### h=2048

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -4.4% | [-6.7, -3.1] |
| 1 | `default_grpc` | `default_grpc_recommend` | -4.5% | [-6.7, -1.8] |
| 4 | `tuned_grpc_multiplexed` | `rest_recommend` | +20.5% | [+13.9, +40.2] |
| 4 | `tuned_grpc_channels` | `rest_recommend` | +14.7% | [+8.1, +21.6] |
| 4 | `default_grpc` | `rest_recommend` | +19.5% | [+13.8, +41.1] |
| 8 | `tuned_grpc_multiplexed` | `rest_recommend` | +23.4% | [+10.7, +29.5] |
| 8 | `tuned_grpc_channels` | `rest_recommend` | +19.5% | [+4.8, +29.9] |
| 8 | `default_grpc` | `rest_recommend` | +11.9% | [+3.4, +24.9] |

#### h=4096

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -8.5% | [-11.3, -5.8] |
| 1 | `default_grpc` | `default_grpc_recommend` | -8.7% | [-11.6, -6.2] |
| 4 | `tuned_grpc_multiplexed` | `rest_recommend` | +17.9% | [+14.5, +30.6] |
| 4 | `tuned_grpc_channels` | `rest_recommend` | +21.5% | [+15.9, +27.8] |
| 4 | `default_grpc` | `rest_recommend` | +28.9% | [+20.1, +44.6] |
| 8 | `tuned_grpc_multiplexed` | `no_winner` | +1.0% | [-18.8, +9.3] |
| 8 | `tuned_grpc_channels` | `no_winner` | -5.8% | [-14.0, +1.4] |
| 8 | `default_grpc` | `default_grpc_recommend` | -12.4% | [-19.8, -3.1] |

#### h=8192

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -5.3% | [-6.7, -3.5] |
| 1 | `default_grpc` | `default_grpc_recommend` | -6.8% | [-7.9, -4.6] |
| 4 | `tuned_grpc_multiplexed` | `rest_recommend` | +22.8% | [+16.9, +44.0] |
| 4 | `tuned_grpc_channels` | `rest_recommend` | +27.8% | [+16.9, +42.8] |
| 4 | `default_grpc` | `rest_recommend` | +20.2% | [+13.4, +35.4] |
| 8 | `tuned_grpc_multiplexed` | `rest_recommend` | +21.6% | [+16.7, +31.4] |
| 8 | `tuned_grpc_channels` | `rest_recommend` | +27.3% | [+19.3, +41.1] |
| 8 | `default_grpc` | `rest_recommend` | +21.7% | [+10.2, +35.3] |

### embed

#### h=2048

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -34.8% | [-36.9, -33.1] |
| 1 | `default_grpc` | `default_grpc_recommend` | -34.9% | [-36.9, -33.4] |
| 4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -19.9% | [-26.4, -14.9] |
| 4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -18.9% | [-26.5, -12.3] |
| 4 | `default_grpc` | `default_grpc_recommend` | -20.6% | [-26.8, -14.2] |
| 8 | `tuned_grpc_multiplexed` | `rest_recommend` | +48.6% | [+27.8, +73.5] |
| 8 | `tuned_grpc_channels` | `rest_recommend` | +30.4% | [+18.5, +46.3] |
| 8 | `default_grpc` | `no_winner` | -0.8% | [-11.6, +10.3] |

#### h=4096

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -32.3% | [-33.0, -31.8] |
| 1 | `default_grpc` | `default_grpc_recommend` | -33.9% | [-34.4, -33.6] |
| 4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -15.6% | [-26.9, -11.8] |
| 4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -11.3% | [-26.7, -6.0] |
| 4 | `default_grpc` | `default_grpc_recommend` | -15.5% | [-27.3, -11.6] |
| 8 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -25.6% | [-32.3, -20.7] |
| 8 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -25.8% | [-31.7, -21.5] |
| 8 | `default_grpc` | `default_grpc_recommend` | -27.6% | [-32.3, -23.5] |

#### h=8192

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -32.2% | [-32.6, -31.5] |
| 1 | `default_grpc` | `default_grpc_recommend` | -31.4% | [-31.7, -30.7] |
| 4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -19.7% | [-25.5, -12.0] |
| 4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -32.8% | [-38.2, -26.2] |
| 4 | `default_grpc` | `default_grpc_recommend` | -24.1% | [-29.3, -15.4] |
| 8 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -26.7% | [-37.5, -18.2] |
| 8 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -26.5% | [-34.7, -18.9] |
| 8 | `default_grpc` | `default_grpc_recommend` | -31.0% | [-40.5, -21.1] |

## REST shim overhead appendix

- Median across run: 0.551 ms
- p95 across run: 3.039 ms
- Max across run: 3.039 ms

## Supersedes M1 (time-axis)

| M1 path | c | M1 verdict | M5.1 verdicts by width | classification |
|---------|---|------------|-----------------------|----------------|
| **chat_completion** | 1 | REST faster (c=1 small-body chat) | h2048=tuned_grpc_recommend, h4096=tuned_grpc_recommend, h8192=tuned_grpc_recommend | **verdict_changed** |
| **chat_completion** | 4 | no_winner | h2048=rest_recommend, h4096=rest_recommend, h8192=rest_recommend | **verdict_changed** |
| **chat_completion** | 8 | gRPC faster (c=8 high-fanout chat) | h2048=rest_recommend, h4096=no_winner, h8192=rest_recommend | **verdict_changed** |
| **embed_completion** | 1 | no_winner | h2048=tuned_grpc_recommend, h4096=tuned_grpc_recommend, h8192=tuned_grpc_recommend | **verdict_changed** |
| embed_completion | 4 | gRPC faster (c=4 embed) | h2048=tuned_grpc_multiplexed_recommend, h4096=tuned_grpc_multiplexed_recommend, h8192=tuned_grpc_channels_recommend | verdict_confirmed |
| embed_completion | 8 | gRPC faster (c=8 embed) | h2048=rest_recommend, h4096=tuned_grpc_channels_recommend, h8192=tuned_grpc_multiplexed_recommend | mixed |

## Negative results — do not re-run speculatively

Cells with at least one `no_winner` verdict (Constitution V — these are honestly reported negative results, not measurement bugs):

- chat_stream:h4096:c8 / `tuned_grpc_multiplexed`: delta +1.0% (CI [-18.8, +9.3])
- chat_stream:h4096:c8 / `tuned_grpc_channels`: delta -5.8% (CI [-14.0, +1.4])
- embed:h2048:c8 / `default_grpc`: delta -0.8% (CI [-11.6, +10.3])

