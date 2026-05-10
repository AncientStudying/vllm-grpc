# Contract: M4 schema-candidate proto shapes

US3 measures three protobuf candidates against per-path frozen-channel baselines. Each candidate is defined as an isolated `.proto` file under `proto/vllm_grpc/v1/m4-candidates/` (per Constitution I + research.md R-9). Production proto under `proto/vllm_grpc/v1/{chat,completions}.proto` is **unchanged** by this milestone.

## Build mechanics

`make proto` regenerates Python stubs for both production and candidate `.proto` files. Generated stubs land in:

| Source | Generated stub package |
|--------|------------------------|
| `proto/vllm_grpc/v1/chat.proto` | `packages/gen/vllm_grpc/v1/` (production, untouched) |
| `proto/vllm_grpc/v1/m4-candidates/packed_token_ids.proto` | `packages/gen/vllm_grpc_m4_candidates/packed_token_ids/` |
| `proto/vllm_grpc/v1/m4-candidates/oneof_flattened_input.proto` | `packages/gen/vllm_grpc_m4_candidates/oneof_flattened_input/` |
| `proto/vllm_grpc/v1/m4-candidates/chunk_granularity.proto` | `packages/gen/vllm_grpc_m4_candidates/chunk_granularity/` |

The bench harness imports from `packages.gen.vllm_grpc_m4_candidates.<candidate>` only when measuring the corresponding cohort. No production import path references the candidate stubs.

## Candidate (a) — `packed_token_ids.proto`

**Hypothesis** (from spec FR-012 (a) and `specs/015-m3-protobuf-grpc-tuning/research.md` R-9): The chat completion's token-id field (currently `repeated int32`) benefits from protobuf's packed-encoding for sequences of small integers. Concrete win or loss is measured.

**Variation**: marks the relevant `repeated int32` field with `[packed=true]` (proto2) or relies on proto3's default-on packed encoding for repeated scalars. The exact field is the chat-completion token-id field on `ChatCompletionResponse` (or its streaming chunk equivalent in `ChatCompletionStreamingChunk`) — to be confirmed against the production proto when the candidate is authored.

**Path applicability**: `chat_stream` (and chat-completion non-streaming if measured separately, though M4 keeps the M3 path set: `embed` + `chat_stream`).

**Expected effect direction**: bytes-down (small for already-small token IDs at typical chat lengths; potentially larger for long-stream cohorts). Time effect plausibly small but non-zero via reduced serialization work.

## Candidate (b) — `oneof_flattened_input.proto`

**Hypothesis** (from spec FR-012 (b)): the input union (text prompt vs. tokenized prompt vs. embedding tensor) currently uses a `oneof` with multi-field alternatives; flattening — replacing the `oneof` with a single message that carries an explicit "kind" enum and the per-kind fields as siblings — may reduce wire bytes by removing oneof's discriminator overhead, or may *increase* bytes by serializing always-empty fields. Concrete direction is measured.

**Variation**: replaces the production `oneof` with a flat message shape. The two competing wire formats are measured against the same per-path frozen-channel baseline.

**Path applicability**: both `embed` (the embedding-tensor input is one of the union arms) and `chat_stream` (text prompt is the most common arm).

**Expected effect direction**: ambiguous. Negative result is possible and would be appendixed per FR-014.

## Candidate (c) — `chunk_granularity.proto`

**Hypothesis** (from spec FR-012 (c) and `specs/015-m3-protobuf-grpc-tuning/research.md` R-9): the streaming chunk message currently emits one chunk per token. Coarser granularity (e.g., one chunk per N tokens, or per-content-flush) may reduce per-chunk fixed overhead (HTTP/2 frame headers, gRPC trailer accounting) at the cost of latency-to-first-token.

**Variation**: introduces a candidate streaming chunk message with a flush-policy hint and the harness drives a configurable chunk granularity (e.g., 1, 4, 16 tokens per chunk) within the single candidate file. Each granularity-value is a separate candidate cohort.

**Path applicability**: `chat_stream` only.

**Expected effect direction**: bytes-down (fewer chunks → fewer frame headers); TTFT effect direction depends on chunk size — coarser chunks may *increase* TTFT (must wait for the first N tokens), so the verdict on TTFT may be `no_winner` or `client_bound` for large N. The bytes-time tradeoff is precisely the question this candidate is designed to surface.

## Citations

- M3's deferred-from-P2 framing for these three candidates: `specs/015-m3-protobuf-grpc-tuning/research.md` R-9 ("packed scalars on token-id" was the named first candidate; oneof and chunk granularity were named follow-ups).
- gRPC streaming chunk wire shape: `~/.graphify/repos/grpc/grpc/src/python/grpcio/grpc/_channel.py` per-call streaming reader; HTTP/2 frame overhead per RFC 7540 §4.
- protobuf packed encoding semantics: protobuf language guide for `[packed=true]` and proto3 default-on packed scalars (the project's existing `proto/vllm_grpc/v1/*.proto` files are proto3, so packed is default-on for repeated scalars — the candidate may need to *disable* packed to compare against an unpacked baseline depending on the production wire format observed when the candidate is authored).

## Out of scope for this contract

- Adoption of any winning candidate into production proto. Per spec Assumptions, adoption is a follow-up change tracked separately and only happens for candidates the maintainers accept.
- Combined-candidate measurement (per research.md R-8): if multiple candidates win at hidden_size 4096, a follow-up cohort measures the combination. That cohort uses the same proto-isolation pattern (a fourth `.proto` file under `m4-candidates/` that combines the winning shapes) and is added to the sweep ad-hoc, not pre-declared.
