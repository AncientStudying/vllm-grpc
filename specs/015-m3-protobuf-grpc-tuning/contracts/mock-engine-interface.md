# Contract: `MockEngine` interface

**Feature**: 015-m3-protobuf-grpc-tuning
**Path**: `tools/benchmark/src/vllm_grpc_bench/mock_engine.py`

This contract defines the interface `MockEngine` MUST satisfy so the existing `ChatServicer` and `CompletionsServicer` (in `packages/frontend/src/vllm_grpc_frontend/`) can use it as a drop-in replacement for the real vLLM `engine` parameter, with **no servicer code changes**. The mock's responsibility is to produce realistic *wire payload shapes*, not realistic outputs.

## Surface

```python
class MockEngine:
    def __init__(self, config: MockEngineConfig) -> None: ...

    async def generate(
        self,
        prompt: str,
        sampling_params: SamplingParams,
        request_id: str,
    ) -> AsyncIterator[RequestOutput]:
        """Yields one RequestOutput per generated token (incremental output).

        Streaming pacing is governed by `config.tokens_per_second`; total token
        count is the lesser of `sampling_params.max_tokens`, `config.max_tokens_per_stream`,
        and any prompt-derived hint (see `m3_long_stream.json` corpus convention).
        """

    async def encode(
        self,
        prompt: str,
        request_id: str,
    ) -> AsyncIterator[EmbeddingRequestOutput]:
        """Yields exactly one EmbeddingRequestOutput whose `outputs[0].embedding`
        is a list[float] of length `config.hidden_size`, deterministically seeded
        from hash(prompt) ^ config.seed.
        """
```

`SamplingParams`, `RequestOutput`, and `EmbeddingRequestOutput` are imported from `vllm` so the type signatures match the real engine exactly. Importing those types does **not** import any vLLM execution code (vLLM's typing module is import-clean on macOS via `vllm-metal`).

## Behavioral contract

1. **Determinism**: For a fixed `MockEngineConfig` and a fixed `prompt`, every call to `generate` / `encode` produces an identical sequence of outputs. This is required so iteration-to-iteration variance in the harness comes from the channel/transport, not from the mock.
2. **Wire-shape parity**: Embedding tensors MUST have exactly `config.hidden_size` entries (validated; see `MockEngineConfig` validation in `data-model.md`). Token chunks MUST be valid UTF-8 strings of plausible token-like length (1–8 chars).
3. **Timing parity**: For streaming, the mock SHOULD `asyncio.sleep(1 / config.tokens_per_second)` between yields so HTTP/2 framing, keepalive, and flow-control behaviour cross realistic time thresholds. For embed, no artificial delay — the mock returns synchronously after constructing the tensor (matching the real engine's behaviour for `hidden_size=8192` on CPU within ~1–10 ms). The mock does **not** need to attach explicit timestamps to its yields; per-yield arrival timing is observable to the harness via standard `async for` boundaries timestamped with `time.perf_counter()`. The harness uses these per-token arrival deltas to populate `Sample.mean_inter_token_seconds` and `Sample.inter_token_seconds_stddev` (see `data-model.md`), satisfying spec AS US1-3 without expanding the mock's interface surface.
4. **Failure modes**: If `prompt` is empty, raise `ValueError("MockEngine: empty prompt")` synchronously. If `request_id` collides with an in-flight request, raise `RuntimeError("duplicate request_id")`. The harness validates that no error samples come from the mock itself; all errors must be channel/transport-attributable.
5. **No hidden state across requests**: `generate` and `encode` are pure functions of `(config, prompt, sampling_params)`. No global counters, no caches.

## What the contract does NOT cover

- The real vLLM engine's tokenizer integration. The mock's "tokens" are pseudo-text fragments; the harness does not measure tokenization correctness because that's an engine-internal concern outside M3's scope.
- The real vLLM engine's KV cache, scheduler, batching, or sampling. Not relevant for wire-tuning.
- Multi-turn or chat-template formatting. The mock receives a flat prompt string; chat-template assembly happens in `ChatServicer` upstream of the mock and is unchanged from M1.

## Test obligations

- `tests/test_mock_engine.py` MUST verify: (a) hidden_size shape correctness at all three canonical widths; (b) determinism across two calls with identical inputs; (c) streaming pacing within ±10% of `tokens_per_second`; (d) error modes raise the expected exceptions.
- A smoke integration test under `packages/frontend/tests/` MUST verify that `ChatServicer(engine=MockEngine(...))` and `CompletionsServicer(engine=MockEngine(...))` start, accept one RPC each, and return well-formed responses — proving the drop-in claim.
