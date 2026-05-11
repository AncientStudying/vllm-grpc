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
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -7.9% | [-9.0, -6.6] |
| 1 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -6.9% | [-8.1, -5.6] |
| 4 | `tuned_grpc_multiplexed` | `rest_recommend` | +53.7% | [+49.1, +59.2] |
| 4 | `tuned_grpc_channels` | `rest_recommend` | +53.4% | [+47.5, +59.6] |
| 4 | `default_grpc` | `rest_recommend` | +52.1% | [+46.1, +58.1] |
| 8 | `tuned_grpc_multiplexed` | `rest_recommend` | +16.8% | [+11.0, +20.7] |
| 8 | `tuned_grpc_channels` | `rest_recommend` | +12.4% | [+7.0, +17.6] |
| 8 | `default_grpc` | `rest_recommend` | +35.9% | [+24.6, +45.3] |

#### h=4096

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -7.6% | [-8.5, -6.8] |
| 1 | `default_grpc` | `no_winner` | -3.7% | [-6.3, +2.2] |
| 4 | `tuned_grpc_multiplexed` | `rest_recommend` | +36.5% | [+30.2, +43.0] |
| 4 | `tuned_grpc_channels` | `rest_recommend` | +35.2% | [+30.1, +40.6] |
| 4 | `default_grpc` | `rest_recommend` | +34.7% | [+26.5, +38.6] |
| 8 | `tuned_grpc_multiplexed` | `no_winner` | -25.6% | [-35.3, +16.6] |
| 8 | `tuned_grpc_channels` | `no_winner` | -24.7% | [-33.6, +19.0] |
| 8 | `default_grpc` | `no_winner` | -22.4% | [-31.4, +22.6] |

#### h=8192

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -11.2% | [-18.7, -7.0] |
| 1 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -9.4% | [-17.5, -6.0] |
| 4 | `tuned_grpc_multiplexed` | `rest_recommend` | +52.9% | [+46.2, +56.6] |
| 4 | `tuned_grpc_channels` | `rest_recommend` | +48.5% | [+42.8, +54.6] |
| 4 | `default_grpc` | `rest_recommend` | +52.7% | [+46.6, +58.0] |
| 8 | `tuned_grpc_multiplexed` | `rest_recommend` | +23.1% | [+8.1, +33.6] |
| 8 | `tuned_grpc_channels` | `rest_recommend` | +15.2% | [+10.3, +31.4] |
| 8 | `default_grpc` | `rest_recommend` | +18.9% | [+7.0, +38.3] |

### embed

#### h=2048

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -39.8% | [-40.6, -39.4] |
| 1 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -40.9% | [-41.5, -40.1] |
| 4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -20.2% | [-21.5, -19.6] |
| 4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -19.4% | [-20.7, -18.2] |
| 4 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -20.3% | [-21.5, -19.6] |
| 8 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -21.1% | [-32.2, -4.0] |
| 8 | `tuned_grpc_channels` | `no_winner` | -17.2% | [-27.3, +0.6] |
| 8 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -31.9% | [-39.2, -16.1] |

#### h=4096

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -37.1% | [-37.6, -36.7] |
| 1 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -37.0% | [-37.5, -36.6] |
| 4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -19.2% | [-31.2, -10.5] |
| 4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -18.9% | [-36.0, -1.2] |
| 4 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -17.7% | [-30.1, -8.2] |
| 8 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -26.2% | [-34.9, -21.4] |
| 8 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -24.7% | [-33.5, -20.1] |
| 8 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -19.5% | [-29.1, -15.0] |

#### h=8192

| concurrency | sub-cohort | verdict | delta % | 95% CI |
|-------------|------------|---------|---------|--------|
| 1 | `tuned_grpc` | `tuned_grpc_recommend` | -34.5% | [-35.0, -34.0] |
| 1 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -35.0% | [-35.4, -34.4] |
| 4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -26.6% | [-31.9, -20.5] |
| 4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -26.4% | [-31.7, -20.3] |
| 4 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -25.3% | [-30.7, -18.9] |
| 8 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | -24.5% | [-30.5, -16.1] |
| 8 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | -37.0% | [-41.2, -30.4] |
| 8 | `default_grpc` | `tuned_grpc_multiplexed_recommend` | -17.2% | [-27.1, -11.0] |

## REST shim overhead appendix

- Median across run: 0.481 ms
- p95 across run: 2.549 ms
- Max across run: 2.549 ms

## Supersedes M1 (time-axis)

| M1 path | c | M1 verdict | M5.1 verdicts by width | classification |
|---------|---|------------|-----------------------|----------------|
| **chat_completion** | 1 | REST faster (c=1 small-body chat) | h2048=tuned_grpc_recommend, h4096=tuned_grpc_recommend, h8192=tuned_grpc_recommend | **verdict_changed** |
| **chat_completion** | 4 | no_winner | h2048=rest_recommend, h4096=rest_recommend, h8192=rest_recommend | **verdict_changed** |
| **chat_completion** | 8 | gRPC faster (c=8 high-fanout chat) | h2048=rest_recommend, h4096=no_winner, h8192=rest_recommend | **verdict_changed** |
| **embed_completion** | 1 | no_winner | h2048=tuned_grpc_recommend, h4096=tuned_grpc_recommend, h8192=tuned_grpc_recommend | **verdict_changed** |
| embed_completion | 4 | gRPC faster (c=4 embed) | h2048=tuned_grpc_multiplexed_recommend, h4096=tuned_grpc_multiplexed_recommend, h8192=tuned_grpc_multiplexed_recommend | verdict_confirmed |
| embed_completion | 8 | gRPC faster (c=8 embed) | h2048=tuned_grpc_multiplexed_recommend, h4096=tuned_grpc_multiplexed_recommend, h8192=tuned_grpc_channels_recommend | verdict_confirmed |

## Negative results — do not re-run speculatively

Cells with at least one `no_winner` verdict (Constitution V — these are honestly reported negative results, not measurement bugs):

- chat_stream:h4096:c1 / `default_grpc`: delta -3.7% (CI [-6.3, +2.2])
- chat_stream:h4096:c8 / `tuned_grpc_multiplexed`: delta -25.6% (CI [-35.3, +16.6])
- chat_stream:h4096:c8 / `tuned_grpc_channels`: delta -24.7% (CI [-33.6, +19.0])
- chat_stream:h4096:c8 / `default_grpc`: delta -22.4% (CI [-31.4, +22.6])
- embed:h2048:c8 / `tuned_grpc_channels`: delta -17.2% (CI [-27.3, +0.6])

