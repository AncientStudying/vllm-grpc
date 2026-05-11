# M5: Cross-Host Time-Axis Validation

## Methodology

- Modal app: `vllm-grpc-bench-mock` (region `eu-west-1`)
- Methodology version: `1`
- Runtime wall-clock: 641.6 s
- Measured RTT (run-wide, ms): min=50.47 median=52.18 p95=53.29 max=55.03
- Thresholds: validity=1.0 ms · exercise=20.0 ms · server_bound_overhead_floor=50.0 ms
- Warmup cohort size per path: 32
- Server-bound cohorts excluded from recommendations: 7
- Pacing mode: `no_pacing`
- Shared baseline cohort ids: `{'embed': 'embed|h4096|m1-baseline|m1_embed', 'chat_stream': 'chat_stream|h4096|m1-baseline|m1_chat'}`
- Sample policy: {'default_n': 100, 'expand_n': 250, 'expand_rule': 'ci_overlap'}
- Seed: 0

## Verdicts

| axis | path | hidden_size | verdict | winning_config | Δ% | citation |
|------|------|-------------|---------|----------------|----|----------|
| max_message_size | embed | 2048 | recommend | max-msg-16mib | -23.21% | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | embed | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | embed | 2048 | recommend | max-msg-unlimited | -23.70% | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | embed | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| keepalive | embed | 2048 | recommend | keepalive-aggressive | -24.90% | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | embed | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | embed | 2048 | recommend | keepalive-relaxed | -23.42% | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | embed | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| compression | embed | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | chat_stream | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | chat_stream | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | chat_stream | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| http2_framing | embed | 2048 | recommend | http2-bdp-probe | -25.44% | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | chat_stream | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | embed | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | chat_stream | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | chat_stream | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| baseline | embed | 4096 | no_winner | - | - | n/a (baseline reference) |
| baseline | chat_stream | 4096 | no_winner | - | - | n/a (baseline reference) |
| baseline | embed | 4096 | no_winner | - | - | n/a (baseline reference) |
| baseline | chat_stream | 4096 | no_winner | - | - | n/a (baseline reference) |
| baseline | embed | 4096 | no_winner | - | - | n/a (baseline reference) |
| baseline | chat_stream | 4096 | no_winner | - | - | n/a (baseline reference) |
| max_message_size | embed | 8192 | server_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| keepalive | embed | 8192 | server_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| compression | embed | 4096 | server_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | embed | 8192 | server_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| http2_framing | embed | 8192 | server_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |

## Per-path frozen-channel baselines

- **embed** → cohort `embed|h4096|frozen-embed-h4096-m5|m1_embed` @ hidden_size=4096; per-axis winners: {'max_message_size': 'm1-default', 'keepalive': 'm1-default', 'compression': 'm1-default', 'http2_framing': 'm1-default'}
- **chat_stream** → cohort `chat_stream|h4096|frozen-chat-stream-h4096-m5|m1_chat` @ hidden_size=4096; per-axis winners: {'max_message_size': 'm1-default', 'keepalive': 'm1-default', 'compression': 'm1-default', 'http2_framing': 'm1-default'}

## Schema candidates

### `packed_token_ids` (measured)

### `oneof_flattened_input` (negative result)

### `chunk_granularity` (measured)


## Supersedes M4

| flag | M4 cell | M4 verdict (time/bytes) | M5 verdict (time/bytes) | M5 CI | class | rationale |
|------|---------|-------------------------|-------------------------|-------|-------|-----------|
| **[changed]** | `compression/h4096/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | bound_classifier_transition | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): M4's client-side classifier was a loopback jitter-floor artifact; on real wire the jitter floor is dominated by RTT, so M5 sees the CI honestly — M5's verdict is the more defensible one (citations: grpc/grpc:src/python/grpcio/grpc/_channel.py; grpc/grpc:src/core/ext/transport/chttp2/transport/frame_data.cc) |
| **[changed]** | `http2_framing/h2048/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | loopback_resolution | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/flow_control.cc; grpc/grpc:src/core/lib/transport/bdp_estimator.cc) |
| **[changed]** | `http2_framing/h4096/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | loopback_resolution | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/flow_control.cc; grpc/grpc:src/core/lib/transport/bdp_estimator.cc) |
| **[changed]** | `http2_framing/h8192/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | loopback_resolution | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/flow_control.cc; grpc/grpc:src/core/lib/transport/bdp_estimator.cc) |
| **[changed]** | `keepalive/h2048/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | loopback_resolution | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/chttp2_transport.cc#keepalive_watchdog_fired_locked) |
| **[changed]** | `keepalive/h4096/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | loopback_resolution | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/chttp2_transport.cc#keepalive_watchdog_fired_locked) |
| **[changed]** | `keepalive/h8192/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | loopback_resolution | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/chttp2_transport.cc#keepalive_watchdog_fired_locked) |
| **[changed]** | `max_message_size/h2048/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | bound_classifier_transition | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): M4's client-side classifier was a loopback jitter-floor artifact; on real wire the jitter floor is dominated by RTT, so M5 sees the CI honestly — M5's verdict is the more defensible one (citations: grpc/grpc:src/python/grpcio/grpc/_channel.py) |
| **[changed]** | `max_message_size/h4096/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | bound_classifier_transition | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): M4's client-side classifier was a loopback jitter-floor artifact; on real wire the jitter floor is dominated by RTT, so M5 sees the CI honestly — M5's verdict is the more defensible one (citations: grpc/grpc:src/python/grpcio/grpc/_channel.py) |
| **[changed]** | `max_message_size/h8192/chat_stream` | client_bound/no_winner | no_winner/no_winner | [0, 0.06264] | bound_classifier_transition | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.06264]): M4's client-side classifier was a loopback jitter-floor artifact; on real wire the jitter floor is dominated by RTT, so M5 sees the CI honestly — M5's verdict is the more defensible one (citations: grpc/grpc:src/python/grpcio/grpc/_channel.py) |
| **[changed]** | `compression/h4096/embed` | no_winner/no_winner | server_bound/no_winner | [0, 0] | bound_classifier_transition | time-metric verdict changed from 'no_winner' to 'server_bound' (M5 CI=[0, 0]): M5's R-4 classifier detected remote-server overhead dominating transport — a classification M4 structurally cannot fire on loopback (same-process server) (citations: grpc/grpc:src/python/grpcio/grpc/_channel.py; grpc/grpc:src/core/ext/transport/chttp2/transport/frame_data.cc) |
| **[changed]** | `compression/h8192/embed` | no_winner/no_winner | server_bound/no_winner | [0, 0] | bound_classifier_transition | time-metric verdict changed from 'no_winner' to 'server_bound' (M5 CI=[0, 0]): M5's R-4 classifier detected remote-server overhead dominating transport — a classification M4 structurally cannot fire on loopback (same-process server) (citations: grpc/grpc:src/python/grpcio/grpc/_channel.py; grpc/grpc:src/core/ext/transport/chttp2/transport/frame_data.cc) |
| **[changed]** | `http2_framing/h4096/embed` | client_bound/no_winner | no_winner/no_winner | [0, 0.1215] | loopback_resolution | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.1215]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/flow_control.cc; grpc/grpc:src/core/lib/transport/bdp_estimator.cc) |
| **[changed]** | `http2_framing/h8192/embed` | no_winner/no_winner | server_bound/no_winner | [0, 0] | loopback_resolution | time-metric verdict changed from 'no_winner' to 'server_bound' (M5 CI=[0, 0]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/flow_control.cc; grpc/grpc:src/core/lib/transport/bdp_estimator.cc) |
| **[changed]** | `keepalive/h4096/embed` | client_bound/no_winner | no_winner/no_winner | [0, 0.1215] | loopback_resolution | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.1215]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/chttp2_transport.cc#keepalive_watchdog_fired_locked) |
| **[changed]** | `keepalive/h8192/embed` | no_winner/no_winner | server_bound/no_winner | [0, 0] | loopback_resolution | time-metric verdict changed from 'no_winner' to 'server_bound' (M5 CI=[0, 0]): real RTT exposed an effect M4 could not measure on loopback (citations: grpc/grpc:src/core/ext/transport/chttp2/transport/chttp2_transport.cc#keepalive_watchdog_fired_locked) |
| **[changed]** | `max_message_size/h4096/embed` | client_bound/no_winner | no_winner/no_winner | [0, 0.1215] | bound_classifier_transition | time-metric verdict changed from 'client_bound' to 'no_winner' (M5 CI=[0, 0.1215]): M4's client-side classifier was a loopback jitter-floor artifact; on real wire the jitter floor is dominated by RTT, so M5 sees the CI honestly — M5's verdict is the more defensible one (citations: grpc/grpc:src/python/grpcio/grpc/_channel.py) |
| **[changed]** | `max_message_size/h8192/embed` | no_winner/no_winner | server_bound/no_winner | [0, 0] | bound_classifier_transition | time-metric verdict changed from 'no_winner' to 'server_bound' (M5 CI=[0, 0]): M5's R-4 classifier detected remote-server overhead dominating transport — a classification M4 structurally cannot fire on loopback (same-process server) (citations: grpc/grpc:src/python/grpcio/grpc/_channel.py) |
|  | `http2_framing/h2048/embed` | recommend/no_winner | recommend/no_winner | [-0.1087, -0.09132] | verdict_confirmed | M5 confirms M4's recommend/no_winner verdict for http2_framing at hidden_size 2048 on embed, resolving the M4 loopback caveat with cross-host transport |
|  | `keepalive/h2048/embed` | recommend/no_winner | recommend/no_winner | [-0.1087, -0.0938] | verdict_confirmed | M5 confirms M4's recommend/no_winner verdict for keepalive at hidden_size 2048 on embed, resolving the M4 loopback caveat with cross-host transport |

## Appendix: Negative results — do not re-run speculatively

- `oneof_flattened_input` — bytes and time both `no_winner` at every measured width (FR-013).

## Executive summary

- Runtime wall-clock: 641.6 s · non-discarded cohorts: 46 · region: eu-west-1
- Verdicts: 5 recommend · 30 no_winner · 0 client_bound · 5 server_bound
- RTT median: 52.2 ms · p95: 53.3 ms
- M4 cells superseded: 20 (18 verdict-changed)
