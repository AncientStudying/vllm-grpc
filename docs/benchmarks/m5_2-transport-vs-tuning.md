# M5.2: REST Transport Path × gRPC Tuning Surface

## Executive summary

> Computed from aggregate JSON key: `https_edge_vs_plain_tcp_rtt_delta_median_ms`.

- 18-cell five-cohort sweep at n=250. 48 protocol-comparison rows; 18 transport-only rows; 0 `comparison_unavailable`; 0 `low_rtt_caveat`.
- HTTPS-edge vs plain-TCP RTT delta: median -47.46 ms, p95 -48.13 ms.
- Supersedes-M5.1: 3 `noise_resolved` (n=250 resolution increase paid off); 0 `transport_dependent` (HTTPS-edge moved the verdict).
- Payload-parity audit (FR-005c): no regression confirmed against PR `29947752dbdda912e961ba8f44083d7370144e4d`.
- Smoke-gate outcome (FR-005a + SC-012): `2026-05-14T01:00:43Z`, asserted clauses: 0.
- Events sidecar SHA-256: `ba8d7d134adc536e8f3a3d87a08bdb7bdadbfc6ecf065a3036d810453f3c7e24` at `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz`.
- **Read instruction**: M5.2 measures MockEngine (engine cost held constant across protocols) so the verdict reflects transport + framing only. Real-engine re-validation is deferred to M7.

## Per-cell comparison matrix

> Computed from events sidecar filter: `phase=measurement AND status=success`.

### chat_stream × h2048 × c=1

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `tuned_grpc_recommend` | -1.1 | [-1.6, -0.8] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `no_winner` | -0.3 | [-0.7, +0.2] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -4.9 | [-5.4, -4.4] |

### chat_stream × h2048 × c=4

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +16.0 | [+12.2, +22.2] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +17.8 | [+13.7, +21.9] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +25.9 | [+22.4, +28.4] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -1.4 | [-2.1, -0.9] |

### chat_stream × h2048 × c=8

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +13.0 | [+11.0, +16.1] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +21.7 | [+17.4, +27.7] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +21.3 | [+14.3, +23.8] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -2.9 | [-3.5, -2.2] |

### chat_stream × h4096 × c=1

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `tuned_grpc_recommend` | -1.0 | [-1.5, -0.4] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `default_grpc_recommend` | -0.5 | [-0.9, -0.0] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -5.0 | [-5.4, -4.5] |

### chat_stream × h4096 × c=4

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +17.6 | [+13.7, +23.2] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +14.7 | [+11.3, +20.3] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +14.7 | [+10.1, +19.3] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -1.1 | [-1.8, -0.4] |

### chat_stream × h4096 × c=8

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +21.1 | [+19.2, +22.1] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +18.1 | [+15.3, +22.9] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +22.7 | [+18.4, +25.2] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -2.2 | [-3.1, -1.3] |

### chat_stream × h8192 × c=1

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `no_winner` | +0.1 | [-0.4, +0.6] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +0.5 | [+0.1, +1.1] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -4.6 | [-5.2, -4.3] |

### chat_stream × h8192 × c=4

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +14.0 | [+9.6, +17.6] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +17.8 | [+13.2, +24.6] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +26.1 | [+24.5, +28.2] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -2.4 | [-2.9, -1.6] |

### chat_stream × h8192 × c=8

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +28.5 | [+24.6, +33.4] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +18.4 | [+13.5, +23.7] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +13.4 | [+6.6, +18.6] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -2.8 | [-3.3, -2.0] |

### embed × h2048 × c=1

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `tuned_grpc_recommend` | -7.2 | [-7.5, -6.7] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `default_grpc_recommend` | -6.6 | [-7.0, -6.1] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -46.3 | [-47.0, -46.0] |

### embed × h2048 × c=4

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +125.6 | [+95.8, +154.5] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +129.2 | [+100.5, +160.4] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +91.6 | [+65.7, +121.4] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -36.5 | [-73.9, -11.4] |

### embed × h2048 × c=8

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +179.5 | [+135.3, +219.2] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +147.7 | [+109.0, +184.9] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +182.8 | [+138.9, +220.9] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -67.1 | [-125.2, -18.6] |

### embed × h4096 × c=1

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `tuned_grpc_recommend` | -51.0 | [-56.6, -47.3] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `default_grpc_recommend` | -51.2 | [-56.4, -47.8] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -24.4 | [-32.5, -13.2] |

### embed × h4096 × c=4

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +74.4 | [+34.6, +119.6] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +101.3 | [+65.5, +149.0] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +74.1 | [+45.5, +122.8] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -81.0 | [-129.6, -36.3] |

### embed × h4096 × c=8

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +98.7 | [+2.2, +194.2] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `no_winner` | -21.0 | [-132.7, +79.4] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +427.2 | [+300.2, +514.6] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -237.1 | [-326.5, -145.9] |

### embed × h8192 × c=1

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `tuned_grpc_recommend` | -103.3 | [-132.0, -81.4] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `default_grpc_recommend` | -114.3 | [-138.7, -102.0] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `no_winner` | -17.1 | [-29.3, +10.1] |

### embed × h8192 × c=4

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +317.9 | [+208.4, +389.6] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +250.9 | [+162.6, +336.2] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +372.6 | [+290.4, +427.6] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `no_winner` | -18.9 | [-109.1, +48.6] |

### embed × h8192 × c=8

| family | gRPC cohort | gRPC net | REST cohort | REST net | verdict | Δ median (ms) | 95% CI (ms) |
|--------|-------------|----------|-------------|----------|---------|---------------|-------------|
| protocol | `tuned_grpc_multiplexed` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +863.5 | [+696.9, +1180.5] |
| protocol | `tuned_grpc_channels` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +674.0 | [+489.8, +915.4] |
| protocol | `default_grpc` | `plain_tcp` | `rest_https_edge` | `https_edge` | `rest_https_edge_recommend` | +1481.5 | [+1316.3, +1705.4] |
| transport | — | — | `rest_https_edge` vs `rest_plain_tcp` | https_edge / plain_tcp | `rest_https_edge_recommend` | -439.5 | [-662.6, -265.0] |

## Supersedes M5.1

> Computed from aggregate JSON key: `supersedes_m5_1`.

| cell | gRPC cohort | M5.1 verdict | M5.2 verdict | Δ median (ms) | 95% CI | category | rationale |
|------|-------------|--------------|--------------|---------------|--------|----------|-----------|
| chat_stream:h2048:c1 | `default_grpc` | `default_grpc_recommend` | `no_winner` | -0.3 | [-0.7, +0.2] | `verdict_changed` | M5.1='default_grpc_recommend'; M5.2='no_winner'; delta=-0.3 ms (CI [-0.7, +0.2]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| chat_stream:h2048:c1 | `tuned_grpc` | `tuned_grpc_recommend` | `tuned_grpc_recommend` | -1.1 | [-1.6, -0.8] | `verdict_confirmed` | M5.1='tuned_grpc_recommend'; M5.2='tuned_grpc_recommend'; delta=-1.1 ms (CI [-1.6, -0.8]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h2048:c4 | `default_grpc` | `rest_recommend` | `rest_https_edge_recommend` | +25.9 | [+22.4, +28.4] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+25.9 ms (CI [+22.4, +28.4]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h2048:c4 | `tuned_grpc_channels` | `rest_recommend` | `rest_https_edge_recommend` | +17.8 | [+13.7, +21.9] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+17.8 ms (CI [+13.7, +21.9]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h2048:c4 | `tuned_grpc_multiplexed` | `rest_recommend` | `rest_https_edge_recommend` | +16.0 | [+12.2, +22.2] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+16.0 ms (CI [+12.2, +22.2]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h2048:c8 | `default_grpc` | `rest_recommend` | `rest_https_edge_recommend` | +21.3 | [+14.3, +23.8] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+21.3 ms (CI [+14.3, +23.8]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h2048:c8 | `tuned_grpc_channels` | `rest_recommend` | `rest_https_edge_recommend` | +21.7 | [+17.4, +27.7] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+21.7 ms (CI [+17.4, +27.7]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h2048:c8 | `tuned_grpc_multiplexed` | `rest_recommend` | `rest_https_edge_recommend` | +13.0 | [+11.0, +16.1] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+13.0 ms (CI [+11.0, +16.1]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h4096:c1 | `default_grpc` | `default_grpc_recommend` | `default_grpc_recommend` | -0.5 | [-0.9, -0.0] | `verdict_confirmed` | M5.1='default_grpc_recommend'; M5.2='default_grpc_recommend'; delta=-0.5 ms (CI [-0.9, -0.0]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h4096:c1 | `tuned_grpc` | `tuned_grpc_recommend` | `tuned_grpc_recommend` | -1.0 | [-1.5, -0.4] | `verdict_confirmed` | M5.1='tuned_grpc_recommend'; M5.2='tuned_grpc_recommend'; delta=-1.0 ms (CI [-1.5, -0.4]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h4096:c4 | `default_grpc` | `rest_recommend` | `rest_https_edge_recommend` | +14.7 | [+10.1, +19.3] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+14.7 ms (CI [+10.1, +19.3]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h4096:c4 | `tuned_grpc_channels` | `rest_recommend` | `rest_https_edge_recommend` | +14.7 | [+11.3, +20.3] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+14.7 ms (CI [+11.3, +20.3]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h4096:c4 | `tuned_grpc_multiplexed` | `rest_recommend` | `rest_https_edge_recommend` | +17.6 | [+13.7, +23.2] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+17.6 ms (CI [+13.7, +23.2]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h4096:c8 | `default_grpc` | `default_grpc_recommend` | `rest_https_edge_recommend` | +22.7 | [+18.4, +25.2] | `verdict_changed` | M5.1='default_grpc_recommend'; M5.2='rest_https_edge_recommend'; delta=+22.7 ms (CI [+18.4, +25.2]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| chat_stream:h4096:c8 | `tuned_grpc_channels` | `no_winner` | `rest_https_edge_recommend` | +18.1 | [+15.3, +22.9] | `noise_resolved` | M5.1='no_winner'; M5.2='rest_https_edge_recommend'; delta=+18.1 ms (CI [+15.3, +22.9]). M5.1's no_winner resolved by M5.2's n=250 resolution increase under the HTTPS-edge topology. |
| chat_stream:h4096:c8 | `tuned_grpc_multiplexed` | `no_winner` | `rest_https_edge_recommend` | +21.1 | [+19.2, +22.1] | `noise_resolved` | M5.1='no_winner'; M5.2='rest_https_edge_recommend'; delta=+21.1 ms (CI [+19.2, +22.1]). M5.1's no_winner resolved by M5.2's n=250 resolution increase under the HTTPS-edge topology. |
| chat_stream:h8192:c1 | `default_grpc` | `default_grpc_recommend` | `rest_https_edge_recommend` | +0.5 | [+0.1, +1.1] | `verdict_changed` | M5.1='default_grpc_recommend'; M5.2='rest_https_edge_recommend'; delta=+0.5 ms (CI [+0.1, +1.1]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| chat_stream:h8192:c1 | `tuned_grpc` | `tuned_grpc_recommend` | `no_winner` | +0.1 | [-0.4, +0.6] | `verdict_changed` | M5.1='tuned_grpc_recommend'; M5.2='no_winner'; delta=+0.1 ms (CI [-0.4, +0.6]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| chat_stream:h8192:c4 | `default_grpc` | `rest_recommend` | `rest_https_edge_recommend` | +26.1 | [+24.5, +28.2] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+26.1 ms (CI [+24.5, +28.2]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h8192:c4 | `tuned_grpc_channels` | `rest_recommend` | `rest_https_edge_recommend` | +17.8 | [+13.2, +24.6] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+17.8 ms (CI [+13.2, +24.6]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h8192:c4 | `tuned_grpc_multiplexed` | `rest_recommend` | `rest_https_edge_recommend` | +14.0 | [+9.6, +17.6] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+14.0 ms (CI [+9.6, +17.6]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h8192:c8 | `default_grpc` | `rest_recommend` | `rest_https_edge_recommend` | +13.4 | [+6.6, +18.6] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+13.4 ms (CI [+6.6, +18.6]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h8192:c8 | `tuned_grpc_channels` | `rest_recommend` | `rest_https_edge_recommend` | +18.4 | [+13.5, +23.7] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+18.4 ms (CI [+13.5, +23.7]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| chat_stream:h8192:c8 | `tuned_grpc_multiplexed` | `rest_recommend` | `rest_https_edge_recommend` | +28.5 | [+24.6, +33.4] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+28.5 ms (CI [+24.6, +33.4]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h2048:c1 | `default_grpc` | `default_grpc_recommend` | `default_grpc_recommend` | -6.6 | [-7.0, -6.1] | `verdict_confirmed` | M5.1='default_grpc_recommend'; M5.2='default_grpc_recommend'; delta=-6.6 ms (CI [-7.0, -6.1]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h2048:c1 | `tuned_grpc` | `tuned_grpc_recommend` | `tuned_grpc_recommend` | -7.2 | [-7.5, -6.7] | `verdict_confirmed` | M5.1='tuned_grpc_recommend'; M5.2='tuned_grpc_recommend'; delta=-7.2 ms (CI [-7.5, -6.7]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h2048:c4 | `default_grpc` | `default_grpc_recommend` | `rest_https_edge_recommend` | +91.6 | [+65.7, +121.4] | `verdict_changed` | M5.1='default_grpc_recommend'; M5.2='rest_https_edge_recommend'; delta=+91.6 ms (CI [+65.7, +121.4]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h2048:c4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | `rest_https_edge_recommend` | +129.2 | [+100.5, +160.4] | `verdict_changed` | M5.1='tuned_grpc_channels_recommend'; M5.2='rest_https_edge_recommend'; delta=+129.2 ms (CI [+100.5, +160.4]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h2048:c4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | `rest_https_edge_recommend` | +125.6 | [+95.8, +154.5] | `verdict_changed` | M5.1='tuned_grpc_multiplexed_recommend'; M5.2='rest_https_edge_recommend'; delta=+125.6 ms (CI [+95.8, +154.5]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h2048:c8 | `default_grpc` | `no_winner` | `rest_https_edge_recommend` | +182.8 | [+138.9, +220.9] | `noise_resolved` | M5.1='no_winner'; M5.2='rest_https_edge_recommend'; delta=+182.8 ms (CI [+138.9, +220.9]). M5.1's no_winner resolved by M5.2's n=250 resolution increase under the HTTPS-edge topology. |
| embed:h2048:c8 | `tuned_grpc_channels` | `rest_recommend` | `rest_https_edge_recommend` | +147.7 | [+109.0, +184.9] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+147.7 ms (CI [+109.0, +184.9]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h2048:c8 | `tuned_grpc_multiplexed` | `rest_recommend` | `rest_https_edge_recommend` | +179.5 | [+135.3, +219.2] | `verdict_confirmed` | M5.1='rest_recommend'; M5.2='rest_https_edge_recommend'; delta=+179.5 ms (CI [+135.3, +219.2]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h4096:c1 | `default_grpc` | `default_grpc_recommend` | `default_grpc_recommend` | -51.2 | [-56.4, -47.8] | `verdict_confirmed` | M5.1='default_grpc_recommend'; M5.2='default_grpc_recommend'; delta=-51.2 ms (CI [-56.4, -47.8]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h4096:c1 | `tuned_grpc` | `tuned_grpc_recommend` | `tuned_grpc_recommend` | -51.0 | [-56.6, -47.3] | `verdict_confirmed` | M5.1='tuned_grpc_recommend'; M5.2='tuned_grpc_recommend'; delta=-51.0 ms (CI [-56.6, -47.3]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h4096:c4 | `default_grpc` | `default_grpc_recommend` | `rest_https_edge_recommend` | +74.1 | [+45.5, +122.8] | `verdict_changed` | M5.1='default_grpc_recommend'; M5.2='rest_https_edge_recommend'; delta=+74.1 ms (CI [+45.5, +122.8]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h4096:c4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | `rest_https_edge_recommend` | +101.3 | [+65.5, +149.0] | `verdict_changed` | M5.1='tuned_grpc_channels_recommend'; M5.2='rest_https_edge_recommend'; delta=+101.3 ms (CI [+65.5, +149.0]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h4096:c4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | `rest_https_edge_recommend` | +74.4 | [+34.6, +119.6] | `verdict_changed` | M5.1='tuned_grpc_multiplexed_recommend'; M5.2='rest_https_edge_recommend'; delta=+74.4 ms (CI [+34.6, +119.6]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h4096:c8 | `default_grpc` | `default_grpc_recommend` | `rest_https_edge_recommend` | +427.2 | [+300.2, +514.6] | `verdict_changed` | M5.1='default_grpc_recommend'; M5.2='rest_https_edge_recommend'; delta=+427.2 ms (CI [+300.2, +514.6]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h4096:c8 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | `no_winner` | -21.0 | [-132.7, +79.4] | `verdict_changed` | M5.1='tuned_grpc_channels_recommend'; M5.2='no_winner'; delta=-21.0 ms (CI [-132.7, +79.4]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h4096:c8 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | `rest_https_edge_recommend` | +98.7 | [+2.2, +194.2] | `verdict_changed` | M5.1='tuned_grpc_multiplexed_recommend'; M5.2='rest_https_edge_recommend'; delta=+98.7 ms (CI [+2.2, +194.2]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h8192:c1 | `default_grpc` | `default_grpc_recommend` | `default_grpc_recommend` | -114.3 | [-138.7, -102.0] | `verdict_confirmed` | M5.1='default_grpc_recommend'; M5.2='default_grpc_recommend'; delta=-114.3 ms (CI [-138.7, -102.0]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h8192:c1 | `tuned_grpc` | `tuned_grpc_recommend` | `tuned_grpc_recommend` | -103.3 | [-132.0, -81.4] | `verdict_confirmed` | M5.1='tuned_grpc_recommend'; M5.2='tuned_grpc_recommend'; delta=-103.3 ms (CI [-132.0, -81.4]). M5.1's verdict holds under M5.2's n=250 + HTTPS-edge topology — finding generalizes across both deployment shapes. |
| embed:h8192:c4 | `default_grpc` | `default_grpc_recommend` | `rest_https_edge_recommend` | +372.6 | [+290.4, +427.6] | `verdict_changed` | M5.1='default_grpc_recommend'; M5.2='rest_https_edge_recommend'; delta=+372.6 ms (CI [+290.4, +427.6]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h8192:c4 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | `rest_https_edge_recommend` | +250.9 | [+162.6, +336.2] | `verdict_changed` | M5.1='tuned_grpc_channels_recommend'; M5.2='rest_https_edge_recommend'; delta=+250.9 ms (CI [+162.6, +336.2]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h8192:c4 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | `rest_https_edge_recommend` | +317.9 | [+208.4, +389.6] | `verdict_changed` | M5.1='tuned_grpc_multiplexed_recommend'; M5.2='rest_https_edge_recommend'; delta=+317.9 ms (CI [+208.4, +389.6]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h8192:c8 | `default_grpc` | `default_grpc_recommend` | `rest_https_edge_recommend` | +1481.5 | [+1316.3, +1705.4] | `verdict_changed` | M5.1='default_grpc_recommend'; M5.2='rest_https_edge_recommend'; delta=+1481.5 ms (CI [+1316.3, +1705.4]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h8192:c8 | `tuned_grpc_channels` | `tuned_grpc_channels_recommend` | `rest_https_edge_recommend` | +674.0 | [+489.8, +915.4] | `verdict_changed` | M5.1='tuned_grpc_channels_recommend'; M5.2='rest_https_edge_recommend'; delta=+674.0 ms (CI [+489.8, +915.4]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |
| embed:h8192:c8 | `tuned_grpc_multiplexed` | `tuned_grpc_multiplexed_recommend` | `rest_https_edge_recommend` | +863.5 | [+696.9, +1180.5] | `verdict_changed` | M5.1='tuned_grpc_multiplexed_recommend'; M5.2='rest_https_edge_recommend'; delta=+863.5 ms (CI [+696.9, +1180.5]). Topology-dependent: M5.1's same-network-path topology and M5.2's HTTPS-edge topology favor different cohorts; pick by deployment shape (M5.1 applies when REST and gRPC share a network fabric; M5.2 applies when REST fronts a managed anycast edge). |

## Negative results — do not re-run speculatively

> Computed from aggregate JSON key: `protocol_comparison_verdicts` filtered by verdict ∈ {no_winner, comparison_unavailable}.

- (protocol) chat_stream:h2048:c1 / `default_grpc` vs `rest_https_edge`: `no_winner` (Δ -0.3 ms, CI [-0.7, +0.2])
- (protocol) chat_stream:h8192:c1 / `tuned_grpc` vs `rest_https_edge`: `no_winner` (Δ +0.1 ms, CI [-0.4, +0.6])
- (protocol) embed:h4096:c8 / `tuned_grpc_channels` vs `rest_https_edge`: `no_winner` (Δ -21.0 ms, CI [-132.7, +79.4])
- (transport) embed:h8192:c1 / `rest_https_edge` vs `rest_plain_tcp`: `no_winner` (Δ -17.1 ms, CI [-29.3, +10.1])
- (transport) embed:h8192:c4 / `rest_https_edge` vs `rest_plain_tcp`: `no_winner` (Δ -18.9 ms, CI [-109.1, +48.6])

## Preserved findings (NOT superseded by M5.2)

- M1 bytes-axis (encoding-driven, transport-immune): the ~89% chat response byte reduction and ~25% embed request byte reduction stand unchanged. M5.2 measures time only.
- M5 transport-axis (channel-tuning component): the per-axis tuned-channel recommendations from `docs/benchmarks/m5-cross-host-validation.md` remain in force; M5.2 reuses M5's frozen-tuned channel composition without re-tuning (FR-007).

