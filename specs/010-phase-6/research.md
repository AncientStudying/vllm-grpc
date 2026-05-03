# Research: Phase 6 — Completions API with Prompt Embeddings

**Branch**: `010-phase-6`
**Date**: 2026-05-03
**Purpose**: Resolve all design unknowns before implementation tasks are generated.

---

## R-001: AsyncLLM.generate() Interface for prompt_embeds in vLLM 0.20.0

### Decision

The frontend servicer calls `engine.generate()` using a tensor-aware input dict. Based on vLLM 0.20.0's V1 engine (confirmed viable on A10G in ADR 0001), prompt_embeds are passed via the `PromptType` abstraction as `{"prompt_embeds": tensor}`. The exact keyword must be verified at implementation time against `vllm.AsyncLLMEngine.generate()` in 0.20.0 — the reference is what `vllm/entrypoints/openai/serving_completion.py` does internally when it receives a `prompt_embeds` request.

```python
# Expected pattern (verify against vllm 0.20.0 AsyncLLM.generate signature):
inputs = {"prompt_embeds": tensor}  # tensor: torch.Tensor [seq_len, hidden_size]
async for output in engine.generate(inputs, sampling_params, request_id=request_id):
    ...
```

The frontend receives raw bytes from the proto `CompletionRequest.prompt_embeds` field, reconstructs the tensor via `torch.load(io.BytesIO(raw_bytes))`, then passes it to the engine.

### Rationale

Phase 2's `scripts/python/verify_prompt_embeds_modal.py` demonstrated the full path working on Modal A10G with vLLM 0.20.0. The native vLLM REST server (`--enable-prompt-embeds`) accepts the tensor and passes it to the GPU model runner. Our frontend replicates what vLLM's serving layer does: decode bytes → reconstruct tensor → call engine. The `gpu_model_runner.py` implementation in V1 is the confirmed execution path (ADR 0001).

### Alternatives Considered
- **Pass raw bytes directly to engine**: Engine expects a tensor, not raw bytes; decoding is mandatory.
- **Use vLLM V0 engine (`VLLM_USE_V1=0`)**: Not viable — V0 was removed in vLLM 0.11.0; `VLLM_USE_V1=0` raises `AssertionError` in 0.20.0 (ADR 0001).

---

## R-002: completions.proto Schema

### Decision

New file `proto/vllm_grpc/v1/completions.proto` with a `CompletionsService`. A proto3 `oneof input` block enforces mutual exclusivity of text-prompt and prompt-embedding inputs at the schema level.

```proto
service CompletionsService {
  rpc Complete       (CompletionRequest) returns (CompletionResponse);
  rpc CompleteStream (CompletionRequest) returns (stream CompletionStreamChunk);
}

message CompletionRequest {
  string model      = 1;
  int32  max_tokens = 2;
  optional float  temperature = 3;
  optional float  top_p       = 4;
  optional int64  seed        = 5;
  oneof input {
    string prompt        = 6;
    bytes  prompt_embeds = 7;
  }
}

message CompletionResponse {
  string generated_text     = 1;
  string finish_reason      = 2;
  int32  prompt_tokens      = 3;
  int32  completion_tokens  = 4;
}

// One message per output token in a streaming response.
// finish_reason is "" on non-final chunks; "stop" or "length" on the final chunk.
message CompletionStreamChunk {
  string delta_text    = 1;
  string finish_reason = 2;
  int32  token_index   = 3;
}
```

The `prompt_embeds` bytes field carries the raw `torch.save()` output — no base64 encoding anywhere in the protobuf wire format.

### Rationale

`oneof` prevents ambiguous dual-input requests at the proto level (enforcing FR-008 without any application-layer guard). Using `bytes` for `prompt_embeds` avoids the ~33% base64 overhead of JSON and is protobuf's idiomatic binary carrier. Naming mirrors chat.proto conventions (`*Request`, `*Response`, `*StreamChunk`).

### Alternatives Considered
- **Reuse chat.proto**: Completions and chat have structurally different request/response shapes; a shared proto would bloat both and obscure field semantics.
- **Store embeddings as `repeated float`**: Bulkier on the wire than raw bytes; `bytes` with `torch.save()` is the established convention for this project (ADR 0001).

---

## R-003: Proxy Handling of prompt_embeds (REST → proto)

### Decision

The proxy's `POST /v1/completions` route accepts a Pydantic request model with:
- `prompt: str | None` — plain text (mutually exclusive with `prompt_embeds`)
- `prompt_embeds: str | None` — base64-encoded `torch.save()` bytes (as vLLM's native API delivers them)

Translation to proto:
1. If `prompt` is set: populate `CompletionRequest.prompt`
2. If `prompt_embeds` is set: `base64.b64decode(prompt_embeds)` → populate `CompletionRequest.prompt_embeds` bytes field
3. If both or neither: return HTTP 422 with a descriptive error

Wire size advantage at a glance (Qwen3-0.6B, seq_len=8, hidden_size=1024, float32):
- Raw tensor: 8 × 1024 × 4 = 32,768 bytes
- REST path (base64): ≈ 43,700 bytes (+33%)
- gRPC-direct path (proto bytes): 32,768 bytes (no overhead)

### Rationale

The base64 decode at the proxy boundary is the minimal transformation needed: the REST client sends base64 (vLLM's established convention), and the proto field is raw bytes. This single step eliminates the JSON encoding overhead for the entire gRPC leg. The proxy does not perform `torch.load()` — that is the frontend's responsibility.

### Alternatives Considered
- **Pass base64 string through proto as `string`**: Would require re-encoding at frontend; negates the binary-efficiency advantage and violates FR-006.
- **Have the client send raw bytes directly over REST**: Not compatible with vLLM's native `/v1/completions` wire format (base64 is the established convention).

---

## R-004: SSE Format for Streaming Completions

### Decision

OpenAI's `/v1/completions` streaming format differs from chat completions:

```
data: {"id":"cmpl-{id}","object":"text_completion","created":{ts},"model":"{model}","choices":[{"text":"{token}","index":0,"logprobs":null,"finish_reason":null}]}

data: {"id":"cmpl-{id}","object":"text_completion","created":{ts},"model":"{model}","choices":[{"text":"","index":0,"logprobs":null,"finish_reason":"stop"}]}

data: [DONE]
```

Key differences from chat completions SSE:
- `object` is `"text_completion"` (not `"chat.completion.chunk"`)
- Content delta is in `choices[0].text` (not `choices[0].delta.content`)
- No initial role-delta event (completions have no `role` field)
- Final event has non-empty `finish_reason` with empty `text`

Error event format is identical to chat completions: `data: {"error": {"message": "...", "type": "..."}}\n\n`.

### Rationale

Strict OpenAI format compatibility ensures existing clients (openai SDK, curl one-liners) work unchanged. The Phase 5 SSE helpers in `proxy/chat_translate.py` are reference implementations; completions needs its own parallel set in `proxy/completions_translate.py`.

### Alternatives Considered
- **Reuse chat SSE helpers**: Would require awkward parameter gymnastics; the different field names make separate functions cleaner and mypy-strict-safe.

---

## R-005: CI Benchmark Multi-Phase Comment Aggregation

### Decision

Replace the `benchmark.yml` "Modal baseline summary" step's `cp` command with a shell block that concatenates all available phase markdown files under labelled headers. Each phase file is optional — missing files are silently skipped. The PR comment section heading changes to "Modal GPU Baselines — All Phases".

```bash
{
  found=0
  if [ -f docs/benchmarks/phase-4.2-three-way-comparison.md ]; then
    echo "## Phase 4.2 — Non-Streaming Three-Way Comparison"
    cat docs/benchmarks/phase-4.2-three-way-comparison.md
    echo ""
    found=1
  fi
  if [ -f docs/benchmarks/phase-5-streaming-comparison.md ]; then
    echo "## Phase 5 — Streaming TTFT/TPOT"
    cat docs/benchmarks/phase-5-streaming-comparison.md
    echo ""
    found=1
  fi
  if [ -f docs/benchmarks/phase-6-completions-comparison.md ]; then
    echo "## Phase 6 — Completions with Prompt Embeddings"
    cat docs/benchmarks/phase-6-completions-comparison.md
    echo ""
    found=1
  fi
  if [ "$found" -eq 0 ]; then
    echo "_Modal baselines not yet committed — skipping Modal cross-run summary._"
  fi
} > modal-cross-summary.md
```

### Rationale

The motivation is FR-013: every PR should show the full historical benchmark picture, not just the latest phase's numbers. Concatenation is the simplest aggregation that works in a shell step without introducing new tooling. Phase files are labelled so reviewers can distinguish which numbers belong to which phase.

### Alternatives Considered
- **Single merged JSON + Python reporter**: More structured but requires a new CLI command and a combined schema; concatenation of existing markdown is zero-dependency and sufficient.
- **Link to benchmark files instead of inlining**: Links only work if the PR branch has the files; inline content is always available.

---

## R-006: Benchmark Corpus for Prompt Embeddings

### Decision

The corpus consists of **20 pre-computed embedding tensors** derived from 20 distinct plain-text prompts spanning **4 sequence-length buckets** (5 prompts each). Each tensor is saved as a `.pt` file. A manifest file `completions_embeds/manifest.json` records the source prompt text, token count, and tensor shape for every entry, making the corpus independently verifiable.

**Corpus size distribution:**

| Bucket | Token count (seq_len) | Tensor shape | `.pt` file size (float32) | JSON size (base64) |
|--------|----------------------|--------------|--------------------------|-------------------|
| Short  | 8–16 tokens          | [8–16, 1024] | 32–65 KB                 | 43–87 KB          |
| Medium | 32–48 tokens         | [32–48, 1024] | 131–196 KB               | 175–262 KB        |
| Long   | 96–128 tokens        | [96–128, 1024] | 393–524 KB               | 524–699 KB        |
| Full   | 192–256 tokens       | [192–256, 1024] | 786 KB–1 MB              | 1.0–1.4 MB        |

5 prompts per bucket × 4 buckets = **20 samples total**. This spread demonstrates how the ~33% base64 overhead scales linearly with sequence length and whether gRPC's advantage holds across prompt sizes.

**Source prompts** are derived from the existing `tools/benchmark/corpus/chat_nonstreaming.json` corpus — the same prompts used in the Phase 3 and Phase 4.2 benchmarks. The `content` field from the first user message of each sample is extracted as a plain-text string. This gives methodological continuity: a reviewer can compare wire-size numbers against the same inputs that drove prior latency benchmarks.

For the short and medium buckets (seq_len 8–48) the chat corpus provides ample samples. For the long and full buckets (seq_len 96–256) where the chat corpus may not yield enough tokens, adjacent chat samples are concatenated with a newline separator until the target token count is reached. Any such concatenated entries are flagged with `"source": "concatenated"` in the manifest (versus `"source": "chat_corpus"` for direct extractions), so the provenance of every sample is transparent.

The 20 source texts (post-extraction and any concatenation) are committed to `tools/benchmark/corpus/completions_embeds/prompts.txt` (one per line, in id order), so any reviewer can regenerate the `.pt` files from scratch using `gen_embed_corpus.py` and confirm they match.

**Generation procedure** (performed once; outputs committed):
1. Load Qwen3-0.6B tokenizer and embedding layer (`model.embed_tokens`) locally, no GPU required.
2. Tokenize each source prompt; verify token count falls in the intended bucket.
3. Run `model.embed_tokens(token_ids)` → tensor of shape `[seq_len, 1024]`, dtype float32.
4. `torch.save(tensor, f"corpus/completions_embeds/{i:02d}.pt")`.
5. Record `{"id": i, "source_prompt": text, "seq_len": n, "shape": [n, 1024], "embed_file": "...", "max_tokens": 50, "seed": 42}` in `manifest.json`.

**Harness behaviour**: For each manifest entry, the harness loads the `.pt` file once. For the REST path it base64-encodes the bytes and measures the inflated request size. For gRPC paths it passes raw bytes and measures the proto request size. All three paths receive the identical byte sequence for each sample.

### Rationale

**Why 20 samples?** Enough to compute stable mean wire-size numbers (variance in wire size comes entirely from seq_len, which is fixed per sample) while keeping corpus generation time under 2 minutes on a CPU-only machine. The Phase 3 and Phase 4.2 benchmarks used similar corpus sizes (20–30 entries).

**Why 4 buckets?** The wire-size advantage of protobuf over base64 is proportional to payload size. A single token count would only demonstrate the advantage at one point. Four buckets show that the advantage is constant (~33%) across the full range of realistic prompt lengths, making the claim more credible. A reviewer who sees the advantage holds at 8 tokens *and* 256 tokens is more convinced than one who sees a single data point.

**Why commit the source prompts?** The credibility of the wire-size claim rests on the benchmark being reproducible. Any reviewer must be able to (a) read the 20 source texts, (b) run `gen_embed_corpus.py`, and (c) confirm the `.pt` files match. Committing prompts.txt closes that loop. Zero tensors or randomly-generated tensors would not be independently verifiable.

**Why float32?** It is the widest common dtype and produces the largest wire size, giving the most conservative (hardest-to-beat) REST base64 number. If the gRPC advantage is measurable at float32, it is at least as large at bfloat16 (same shape, half the bytes, same ~33% inflation ratio).

### Alternatives Considered
- **Generate tensors on the fly in the harness**: Requires torch at harness time; adds startup latency; makes results sensitive to harness-environment differences.
- **Use zero tensors (as in verify_prompt_embeds_modal.py)**: Produce non-representative model outputs (the model will output garbage) and are not reproducible from a meaningful prompt; rejected on honesty grounds.
- **Single sequence length**: Would only demonstrate the wire-size advantage at one point; a sceptical reviewer could argue the result is an artefact of that specific size.
- **More than 20 samples or 4 buckets**: Diminishing returns for wire-size measurement (the relationship is linear and deterministic); longer generation time with no credibility gain.
