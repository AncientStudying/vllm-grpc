# M4: Time-Axis Channel & Schema Tuning

## Methodology

- Pacing mode: `no_pacing`
- Shared baseline cohort ids: `{'embed': 'embed|h4096|m1-baseline|m1_embed', 'chat_stream': 'chat_stream|h4096|m1-baseline|m1_chat'}`
- Sample policy: {'default_n': 100, 'expand_n': 250, 'expand_rule': 'ci_overlap'}
- Loopback caveat axes: ['http2_framing', 'keepalive']
- Seed: 0
- Run date: 2026-05-10
- Host: Apple M2 Pro (12 cores), arm64, macOS 26.4.1 (Darwin 25.4.0, kernel xnu-12377.101.15)
- Python: 3.12.12 (Clang 21.1.4)
- Reproducer: `uv run python -m vllm_grpc_bench --m4` on a quiet host. Defaults: `--no-pacing --shared-baseline --baseline-n=100 --candidate-n=100 --expand-n=250 --warmup-n=10 --baseline-cv-warn=0.05`. See `specs/016-m4-time-axis-tuning/quickstart.md` for the full runbook and `specs/016-m4-time-axis-tuning/research.md` R-11 for FR-005 (per-cohort CV is recorded; the run never aborts on noisy baselines — the "Baseline within-cohort CV" table below names cohorts whose CV exceeded the warn threshold).

## Verdicts

| axis | path | hidden_size | verdict | winning_config | Δ% | citation |
|------|------|-------------|---------|----------------|----|----------|
| max_message_size | embed | 2048 | recommend | max-msg-16mib | -30.00% | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 2048 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | embed | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | embed | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 8192 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | embed | 2048 | recommend | max-msg-unlimited | -20.47% | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 2048 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | embed | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | embed | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| max_message_size | chat_stream | 8192 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (channel-args plumbing); ~/.graphify/repos/grpc/grpc/src/core/lib/channel/channel_args.cc (defaults) |
| keepalive | embed | 2048 | recommend | keepalive-aggressive | -28.24% | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 2048 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | embed | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | embed | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 8192 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | embed | 2048 | recommend | keepalive-relaxed | -25.04% | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 2048 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | embed | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | embed | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| keepalive | chat_stream | 8192 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/chttp2_transport.cc (keepalive timer logic) |
| compression | embed | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | chat_stream | 2048 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | embed | 4096 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | chat_stream | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | embed | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| compression | chat_stream | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py (compression argument); ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/frame_data.cc (frame-level compression handling) |
| http2_framing | embed | 2048 | recommend | http2-bdp-probe | -22.62% | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | chat_stream | 2048 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | embed | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | chat_stream | 4096 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | embed | 8192 | no_winner | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |
| http2_framing | chat_stream | 8192 | client_bound | - | - | ~/.graphify/repos/grpc/grpc/src/core/ext/transport/chttp2/transport/flow_control.cc (chttp2 stream/transport flow-control state); ~/.graphify/repos/grpc/grpc/src/core/lib/transport/bdp_estimator.cc (BDP probe state machine) |

## Baseline within-cohort CV (FR-005)

Per-cohort coefficient of variation (stddev/mean) on the verdict metric. The harness records this for every baseline cohort; cohorts marked `noisy` exceeded the run's `--baseline-cv-warn` threshold and verdicts derived from them carry extra uncertainty (see research.md R-11).

| baseline cohort | role | metric | CV | noisy? |
|-----------------|------|--------|----|--------|
| `embed|h4096|m1-baseline|m1_embed` | m1_shared | time | 0.0959 | yes |
| `chat_stream|h4096|m1-baseline|m1_chat` | m1_shared | ttft | 0.1084 | yes |
| `embed|h4096|frozen-embed-h4096|m1_embed` | frozen_channel | time | 0.0630 | yes |
| `chat_stream|h4096|frozen-chat-stream-h4096|m1_chat` | frozen_channel | ttft | 0.0856 | yes |

## Per-path frozen-channel baselines

- **embed** → cohort `embed|h4096|frozen-embed-h4096|m1_embed` @ hidden_size=4096; per-axis winners: {'max_message_size': 'm1-default', 'keepalive': 'm1-default', 'compression': 'm1-default', 'http2_framing': 'm1-default'}
- **chat_stream** → cohort `chat_stream|h4096|frozen-chat-stream-h4096|m1_chat` @ hidden_size=4096; per-axis winners: {'max_message_size': 'm1-default', 'keepalive': 'm1-default', 'compression': 'm1-default', 'http2_framing': 'm1-default'}

## Supersedes M3

| M3 cell | M3 verdict | M4 cell | M4 verdict | rationale |
|---------|------------|---------|------------|-----------|
| embed|h2048|keepalive|m1-baseline | noise_bounded | embed|h2048|keepalive-aggressive|m1_embed | recommend | M4 re-measurement under shared baseline + no-pacing produced recommend for (embed, h2048, keepalive). |
| chat_stream|h4096|http2_framing|m1-baseline | noise_bounded | chat_stream|h4096|http2-bdp-probe|m1_chat | client_bound | M4 re-measurement under shared baseline + no-pacing produced client_bound for (chat_stream, h4096, http2_framing). |

## Loopback caveat

These axes' verdicts apply to single-host loopback runs only — RTT-bounded behaviour cannot manifest on `127.0.0.1` (R-6):

- `http2_framing`
- `keepalive`

## Schema candidates

### `packed_token_ids` (measured)

### `oneof_flattened_input` (measured)

### `chunk_granularity` (measured)

