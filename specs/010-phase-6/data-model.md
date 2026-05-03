# Data Model: Phase 6 — Completions API with Prompt Embeddings

**Branch**: `010-phase-6`
**Date**: 2026-05-03

---

## Proto Messages (`proto/vllm_grpc/v1/completions.proto`)

### CompletionRequest

| Field | Proto type | Field # | Notes |
|---|---|---|---|
| model | string | 1 | Model name, e.g. `"Qwen/Qwen3-0.6B"` |
| max_tokens | int32 | 2 | Required; max output tokens |
| temperature | optional float | 3 | Absent → engine default |
| top_p | optional float | 4 | Absent → engine default |
| seed | optional int64 | 5 | Absent → non-deterministic |
| prompt *(oneof input)* | string | 6 | Plain text; mutually exclusive with prompt_embeds |
| prompt_embeds *(oneof input)* | bytes | 7 | Raw `torch.save()` bytes; mutually exclusive with prompt |

**Invariant**: exactly one of `prompt` or `prompt_embeds` MUST be set. Proto3 `oneof` enforces this at the schema level; application code must not allow neither.

### CompletionResponse

| Field | Proto type | Field # | Notes |
|---|---|---|---|
| generated_text | string | 1 | Full generated text (non-streaming only) |
| finish_reason | string | 2 | `"stop"` or `"length"` |
| prompt_tokens | int32 | 3 | Tokens consumed by the input |
| completion_tokens | int32 | 4 | Tokens generated |

### CompletionStreamChunk

| Field | Proto type | Field # | Notes |
|---|---|---|---|
| delta_text | string | 1 | Token text delta for this chunk |
| finish_reason | string | 2 | `""` on non-final chunks; `"stop"`/`"length"` on final |
| token_index | int32 | 3 | Zero-based position of this token in the output |

---

## Proxy Pydantic Model (`packages/proxy/src/vllm_grpc_proxy/completions_translate.py`)

### OpenAICompletionRequest

| Field | Python type | Notes |
|---|---|---|
| model | str | Passed through to proto |
| max_tokens | int | Default: 16 |
| temperature | float \| None | None → not set in proto |
| top_p | float \| None | None → not set in proto |
| seed | int \| None | None → not set in proto |
| stream | bool | Default: False |
| prompt | str \| None | Mutually exclusive with prompt_embeds |
| prompt_embeds | str \| None | Base64-encoded `torch.save()` bytes |

Validation: exactly one of `prompt` / `prompt_embeds` must be non-None; raise HTTP 422 if violated.

---

## Client Library Dataclasses (`packages/client/src/vllm_grpc_client/completions.py`)

### CompletionResult

| Field | Python type | Notes |
|---|---|---|
| generated_text | str | Full generated text |
| finish_reason | str | `"stop"` or `"length"` |
| prompt_tokens | int | |
| completion_tokens | int | |

### CompletionStreamChunk

| Field | Python type | Notes |
|---|---|---|
| delta_text | str | Token text delta |
| finish_reason | str \| None | None on non-final chunks |
| token_index | int | |

---

## Benchmark Entities (`tools/benchmark/src/vllm_grpc_bench/`)

### RequestResult (additions)

| Field | Python type | Notes |
|---|---|---|
| request_type | Literal["chat", "completion-text", "completion-embeds"] | Distinguishes corpus type |

### RunSummary (additions)

| Field | Python type | Notes |
|---|---|---|
| request_type | Literal["chat", "completion-text", "completion-embeds"] | |

Existing `request_bytes_mean` and `response_bytes_mean` fields carry wire-size data for all request types; no new fields required.

---

## Embedding Corpus Manifest (`tools/benchmark/corpus/completions_embeds/manifest.json`)

Each entry is a JSON object describing one corpus sample. The manifest is the link between the committed source text and the committed `.pt` file, making the corpus independently verifiable.

| Field | Type | Notes |
|---|---|---|
| id | int | Zero-based sample index |
| source_prompt | str | The plain-text prompt the tensor was derived from |
| seq_len | int | Number of tokens (= tensor shape[0]) |
| shape | [int, int] | `[seq_len, 1024]` — hidden_size is fixed for Qwen3-0.6B |
| dtype | str | `"float32"` |
| embed_file | str | Relative path to the `.pt` file, e.g. `"corpus/completions_embeds/00.pt"` |
| max_tokens | int | Generation limit used for all paths in this sample |
| seed | int | Fixed seed for deterministic output comparison |
| bucket | str | `"short"` / `"medium"` / `"long"` / `"full"` — seq_len range bucket |
| source | str | `"chat_corpus"` (direct extraction from `chat_nonstreaming.json`) or `"concatenated"` (adjacent chat entries joined to reach target token count) |

**Source prompts** are also committed in full to `tools/benchmark/corpus/completions_embeds/prompts.txt` (one prompt per line, in id order). This redundancy allows `gen_embed_corpus.py` to be re-run from `prompts.txt` alone and its output verified against the committed `.pt` files.

---

## Tensor Wire Format Reference

| Path | Encoding | seq_len=8 | seq_len=64 | seq_len=256 |
|---|---|---|---|---|
| REST (JSON body) | base64(`torch.save()` bytes) | ≈ 43 KB | ≈ 349 KB | ≈ 1.4 MB |
| gRPC proto `bytes` field | raw `torch.save()` bytes | 32 KB | 262 KB | 1.0 MB |
| On-disk corpus (`.pt` file) | `torch.save()` bytes | 32 KB | 262 KB | 1.0 MB |

The ~33% gap between REST and gRPC paths holds linearly across all sequence lengths — this is the primary measurement target of the Phase 6 benchmark. The four-bucket corpus design (seq_len 8–256) demonstrates that the advantage is consistent rather than an artefact of a single payload size.
