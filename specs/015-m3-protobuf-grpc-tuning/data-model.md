# Phase 1 Data Model: M3 — Protobuf & gRPC Tuning

**Feature**: 015-m3-protobuf-grpc-tuning
**Date**: 2026-05-09

This document specifies the in-process data structures the M3 bench harness uses, with field types and validation rules. These are dataclasses (or `TypedDict` where appropriate) under `tools/benchmark/src/vllm_grpc_bench/`. They are **not** wire types — for wire types, see `proto/vllm_grpc/v1/*.proto`.

## Entities

### `MockEngineConfig` (new — `tools/benchmark/src/vllm_grpc_bench/mock_engine.py`)

Configures a `MockEngine` instance.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `hidden_size` | `int` | > 0; canonical = {2048, 4096, 8192} | Determines embedding tensor shape and (for streaming) per-chunk hidden-vector size |
| `seed` | `int` | ≥ 0 | RNG seed; combined with prompt hash to make output deterministic |
| `tokens_per_second` | `float` | > 0; default 20.0 | Streaming pacing; mirrors typical Llama-class TPS so framing/keepalive cross thresholds at realistic intervals |
| `max_tokens_per_stream` | `int` | > 0; default 64 | Cap per stream; `m3_long_stream.json` overrides via `min_tokens` request hint to force ≥1024 tokens |

**Validation**: `hidden_size > 0`; `tokens_per_second > 0`; `max_tokens_per_stream ≥ 1`. Raises `ValueError` on construction with the offending field name.

### `ChannelConfig` (new — `tools/benchmark/src/vllm_grpc_bench/channel_config.py`)

A named bundle of grpcio channel options applied symmetrically to `grpc.aio.server(options=...)` and `grpc.aio.insecure_channel(target, options=...)`.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `name` | `str` | non-empty, kebab-case | Identifier in the report (e.g. `m1-baseline`, `max-msg-16mib`, `keepalive-aggressive`) |
| `axis` | `Literal["max_message_size","keepalive","compression","http2_framing","baseline"]` | one of the listed | Which P1 axis this configuration exercises (baseline = default for all axes) |
| `server_options` | `tuple[tuple[str, int|str], ...]` | Each tuple is `(grpcio_arg_name, value)` | Becomes the `options=` arg to `grpc.aio.server` |
| `client_options` | `tuple[tuple[str, int|str], ...]` | Each tuple is `(grpcio_arg_name, value)` | Becomes the `options=` arg to `grpc.aio.insecure_channel` |
| `compression` | `grpc.Compression` | `NoCompression \| Gzip \| Deflate` | Passed via `compression=` to channel/call (compression axis only; otherwise `NoCompression`) |
| `description` | `str` | free text | Human-readable rationale, surfaced in the report |

**Validation**: `name` matches `^[a-z0-9][a-z0-9-]+[a-z0-9]$` (kebab-case enforcement); `axis` is one of the literals; `server_options` and `client_options` keys must come from a known-grpcio-args allowlist (see `channel_config.py:_ALLOWED_ARGS`) so typos don't silently produce default behaviour.

**Named presets** (defined as module-level constants):

- `M1_BASELINE` — empty options on both sides, `NoCompression`. The baseline that every other config compares against.
- `MAX_MSG_16MIB` — `grpc.max_send_message_length=16*1024*1024`, `grpc.max_receive_message_length=16*1024*1024`.
- `MAX_MSG_UNLIMITED` — both = -1.
- `KEEPALIVE_AGGRESSIVE` — `grpc.keepalive_time_ms=10000`, `grpc.keepalive_timeout_ms=5000`, `grpc.keepalive_permit_without_calls=1`.
- `KEEPALIVE_RELAXED` — `grpc.keepalive_time_ms=60000`, `grpc.keepalive_timeout_ms=20000`.
- `COMPRESSION_GZIP` — `compression=grpc.Compression.Gzip`.
- `HTTP2_BDP_PROBE` — `grpc.http2.bdp_probe=1`, `grpc.http2.lookahead_bytes=16384`.

### `BenchmarkCell`

Identifies a single combination of dimensions that produces a `RunCohort`.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `path` | `Literal["embed", "chat_stream"]` | one of two | Which RPC path is exercised |
| `hidden_size` | `int` | one of {2048, 4096, 8192} for canonical cells; any > 0 for exploratory | Mock engine's embedding width |
| `channel_config` | `ChannelConfig` | — | Which channel-axis/config is being tested |
| `corpus_subset` | `Literal["m1_chat", "m1_embed", "m3_long_stream"]` | one of three | Drives prompt selection |
| `iterations` | `int` | default 30; CLI override allowed | Repetitions for CI math (R-1) |

**Validation**: `path == "embed"` requires `corpus_subset == "m1_embed"`; `path == "chat_stream"` requires `corpus_subset in {"m1_chat", "m3_long_stream"}`. Mismatches raise `ValueError("path/corpus_subset mismatch: ...")`.

### `Sample`

A single iteration's measurement.

| Field | Type | Notes |
|---|---|---|
| `cell_id` | `str` | Foreign key to the parent `BenchmarkCell`'s deterministic id (path + width + config.name + corpus_subset) |
| `iteration` | `int` | 0-indexed within the cell |
| `request_wire_bytes` | `int` | Serialized request body bytes (sender side) |
| `response_wire_bytes` | `int` | For unary: serialized response. For streaming: sum of all chunk sizes |
| `wall_clock_seconds` | `float` | End-to-end RPC time |
| `tokens_emitted` | `int \| None` | None for embed; present for streaming |
| `time_to_first_token_seconds` | `float \| None` | streaming only |
| `error` | `str \| None` | If the RPC failed; non-None samples are excluded from CI math but recorded |

### `RunCohort`

Aggregated samples for one cell. Computed lazily from `list[Sample]`.

| Field | Type | Notes |
|---|---|---|
| `cell` | `BenchmarkCell` | — |
| `samples` | `list[Sample]` | All iterations, including errors |
| `n_successful` | `int` | Number of samples with `error is None` |
| `bytes_mean` | `float` | Mean of `response_wire_bytes` over successful samples |
| `bytes_ci_low` / `bytes_ci_high` | `float` | 95% CI bounds (R-1 methodology) |
| `time_mean` | `float` | Mean of `wall_clock_seconds` |
| `time_ci_low` / `time_ci_high` | `float` | 95% CI bounds |

**Validation invariant**: `n_successful >= max(10, iterations - error_budget)` where `error_budget = 5`. If too many errors, the cohort is marked `not_measurable` in the report (one of the recordable outcomes per FR-008).

### `Recommendation`

The output unit per axis. Multiple `Recommendation`s per axis are allowed if width-specific.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `axis` | same as `ChannelConfig.axis` | — | Which knob this recommendation governs |
| `applies_to_path` | `Literal["embed", "chat_stream", "both"]` | — | — |
| `applies_to_widths` | `frozenset[int]` | non-empty | Subset of `{2048, 4096, 8192}` |
| `verdict` | `Literal["recommend", "no_winner", "not_measurable"]` | one of three | Maps to the FR-008 recordable outcomes |
| `winning_config` | `ChannelConfig \| None` | required if `verdict == "recommend"` | — |
| `winning_delta_pct` | `float \| None` | required if `verdict == "recommend"`; signed (negative = reduction) | Wire-byte or decode-time % delta vs. baseline |
| `winning_metric` | `Literal["bytes", "time"] \| None` | required if `verdict == "recommend"` | Which metric the win is on |
| `baseline_ci_upper` | `float` | — | The CI threshold the candidate had to clear |
| `candidate_ci_lower` | `float \| None` | — | The lower CI of the candidate's metric (must exceed `baseline_ci_upper`) |
| `citation` | `str` | non-empty | Path into cloned grpcio/vLLM source per FR-007 / FR-009 |
| `notes` | `str` | free text | Caveats, edge cases, deferred follow-ups |

**Validation**: when `verdict == "recommend"`, all `winning_*` fields are non-None and `candidate_ci_lower > baseline_ci_upper` (the SC-003 statistical bar).

### `ProtoRevision` (P2-only)

Identifies a P2 candidate proto change.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `name` | `str` | kebab-case | e.g. `chat-token-ids-packed`, `chat-oneof-flatten` |
| `description` | `str` | non-empty | What changed in the `.proto` file |
| `target_files` | `tuple[str, ...]` | each must exist | Paths under `proto/vllm_grpc/v1/` |
| `frozen_channel_config` | `ChannelConfig` | — | The P1-recommended config under which P2 measures (FR-008) |
| `client_compat_break` | `bool` | — | True if the change forces existing M1 clients to regenerate stubs |

P2 measurements reuse `BenchmarkCell` / `RunCohort` / `Recommendation` with `axis="schema"` (a P2-only sentinel value added to the literal at P2 time).

## Relationships

```text
MockEngineConfig ─┐
                  ├─→ frontend.main → grpc.aio.server(options=ChannelConfig.server_options)
ChannelConfig ────┘                 ↑
                                    │ (test driver wires both into one BenchmarkCell)
                                    ↓
                  ┌─→ proxy/client → grpc.aio.insecure_channel(options=ChannelConfig.client_options)
                  │
                  └─→ Sample (one per iteration) → RunCohort (one per cell) → Recommendation (one per axis × scope)
```

`ProtoRevision` ties into the P2 layer by selecting its `frozen_channel_config` from a P1 `Recommendation` whose `verdict == "recommend"` (or, if all P1 axes resolved to `no_winner` / `not_measurable`, from the explicit `M1_BASELINE` preset).

## State transitions

`Recommendation.verdict` evolves through (at most) these states during a sweep:

```text
(missing) → "not_measurable"   if RunCohort.n_successful < threshold
          → "no_winner"        if all candidates' candidate_ci_lower ≤ baseline_ci_upper
          → "recommend"        if at least one candidate clears the SC-003 bar
```

Once written to `m3-channel-tuning.json`, a `Recommendation` is immutable for that report; rerunning the sweep produces a new dated report rather than overwriting.

## Out of scope for the data model

- *Live monitoring / streaming dashboards*: M3 is offline analysis. No `now()`-based fields beyond the per-`Sample` `wall_clock_seconds`.
- *Cross-machine federation*: every cell runs on one host; no `host_id` field.
- *Persistence beyond the JSON report*: no database, no schema migration concerns.
