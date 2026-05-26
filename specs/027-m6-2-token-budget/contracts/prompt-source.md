# Contract: M6.2 Three-Regime Prompt Source

**Branch**: `027-m6-2-token-budget` | **Phase 1 output (new round-5)** | **Plan**: [../plan.md](../plan.md)

## Why this contract exists

Round-5 of `/speckit-clarify` surfaced a code-surface fact the prior plan didn't account for: the M6.x family currently uses synthetic seed-derived prompts (chat: `_build_chat_prompt(seed)` ≈ `"M6 chat probe seed={N} digest={X}. Please respond."`; embed: random `torch.randn` tensors), NOT corpus-sourced prompts. `ignore_eos` is not set anywhere in the codebase. On the synthetic chat probe, Qwen3-8B reliably emits EOS within ~50-200 tokens regardless of the `max_tokens` cap.

Two consequences silently break the M6.2 spec:

1. The `max_tokens=2048` row in the budget table doesn't reflect 2048-token generation — engine EOS-samples far below the cap.
2. FR-017a's wall-clock-ratio inference threshold (2.2) is meaningless if both `c=8 × max_tokens=1024` and `c=8 × max_tokens=2048` measurements terminate at natural EOS far below the cap.

Round-5 resolves this with the **Option D three-regime split**:

- **Null-anchor cells** (`max_tokens ∈ {10, 50}`): synthetic seed-derived prompts (M6.1.x byte-identical). Preserves FR-012 / FR-013 baseline comparison.
- **Interior-cap cells** (`max_tokens ∈ {256, 512, 1024, 2048}`): ShareGPT corpus (chat) or ShareGPT-derived embeddings at hidden_size=4096 (embed). Production-realistic; methodologically consistent across cell-types.
- **KV-pressure sub-probe** (`c=8 × {1024, 2048}`): ShareGPT corpus regime + `ignore_eos=True` (forced cap). The ONLY measurement driving FR-017a's wall-clock-ratio inference + threshold 2.2.

This contract pins the regime resolution logic + corpus paths + SHA validation + `ignore_eos` plumbing.

## Regime resolution table

`m6_2_prompt_source.resolve_block_inputs(cell, max_tokens, iter_idx, cohort, base_seed, ignore_eos_override=None)` returns the per-block input dict per this table:

| Cell-type | `max_tokens` | Regime | Builder called | `prompt_source` | `ignore_eos` |
|---|---|---|---|---|---|
| chat_stream | 10 or 50 (null anchor) | **synthetic** | `m6_rpc_driver._build_chat_prompt(seed)` | `synthetic_seed_derived` | `False` |
| chat_stream | 256, 512, 1024, 2048 (interior cap) | **corpus** | `symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, chat_corpus)` | `corpus_sharegpt` | `False` |
| chat_stream | sub-probe at `c=8 × {1024, 2048}` | **corpus + forced cap** | same as interior-cap | `corpus_sharegpt` | `True` (per `ignore_eos_override`) |
| embed | 10 or 50 (null anchor) | **synthetic random tensor** | `m6_1_rpc_driver.build_torch_save_bytes(rpc_index, base_seed)` | `synthetic_random_tensor` | `False` |
| embed | 256, 512, 1024, 2048 (interior cap) | **corpus** | load `.pt` from `completions_embeds_qwen3_8b/{idx:04d}.pt` where `idx = iter_idx % len(corpus)` | `corpus_sharegpt_embed` | `False` |
| embed | sub-probe at `c=8 × {1024, 2048}` | **corpus + forced cap** | same as interior-cap | `corpus_sharegpt_embed` | `True` (per `ignore_eos_override`) |

The `ignore_eos_override` parameter is supplied as `True` by the sub-probe orchestrator (`m6_2_sub_probe.run_kv_pressure_sub_probe(...)`) and as `None` (or `False`) by the main-sweep orchestrator (`m6_2_sweep.py`).

The `cohort` parameter to `assign_symmetric_prompt(...)` is "intentionally ignored — kept for call-site readability" per the symmetric_prompts module docstring; the function returns `corpus[iter_idx % len(corpus)]` cohort-invariantly.

## Function signatures

```python
# tools/benchmark/src/vllm_grpc_bench/m6_2_prompt_source.py

from typing import Literal
from pathlib import Path
from vllm_grpc_bench.corpus import RequestSample, CompletionEmbedSample
from vllm_grpc_bench.m6_2_types import M6_2PromptSource

class CorpusDriftError(RuntimeError):
    """Raised when the on-disk corpus SHA does not match the provenance file's recorded SHA.

    Fail-fast at sweep start per SC-018; the operator cannot silently swap a corpus mid-cycle.
    The error message names the diverging field (chat or embed) + the expected vs observed SHAs
    so the operator can reconcile.
    """

def load_chat_corpus() -> list[RequestSample]:
    """Load tools/benchmark/corpus/chat_sharegpt_1000.json + verify SHA against provenance file.

    Reads chat_sharegpt_1000.provenance.json's `corpus_sha256` field; computes SHA-256 of the
    on-disk chat_sharegpt_1000.json; raises CorpusDriftError on mismatch.
    """

def load_embed_corpus() -> list[CompletionEmbedSample]:
    """Load tools/benchmark/corpus/completions_embeds_qwen3_8b/ + verify SHA against manifest.

    Reads completions_embeds_qwen3_8b/manifest.json's top-level `corpus_sha256` field; computes
    the canonical SHA-256 over the sorted list of per-file SHAs (also from the manifest); raises
    CorpusDriftError on mismatch. Also raises FileNotFoundError if the corpus directory is missing
    (the Phase 1 prerequisite per FR-035).
    """

def resolve_block_inputs(
    cell: str,
    max_tokens: int,
    iter_idx: int,
    cohort: str,
    base_seed: int,
    chat_corpus: list[RequestSample] | None = None,
    embed_corpus: list[CompletionEmbedSample] | None = None,
    *,
    ignore_eos_override: bool | None = None,
) -> dict:
    """Resolve the per-block input parameters per the regime table above.

    Returns a dict with keys:
    - `prompt_text` (chat regimes) OR `embed_tensor_bytes` (embed regimes)
    - `prompt_source` (one of the 4 M6_2PromptSource literals)
    - `prompt_corpus_idx` (iter_idx for corpus regimes; None for synthetic regimes)
    - `ignore_eos` (True if ignore_eos_override is True; False otherwise)
    - `max_tokens` (the cap value, passed through)
    """
```

## Corpus paths + SHA pinning

**Chat corpus** (FR-034, existing — no new engineering):
- Path: `tools/benchmark/corpus/chat_sharegpt_1000.json`
- Provenance: `tools/benchmark/corpus/chat_sharegpt_1000.provenance.json`
- SHA-256: `4442302df439fdc1967e9fb48a88910cee5d0f712592e733d47bdbbc1e0374f1` (pinned in the provenance file)
- Contents: 1000 first-human-turn ShareGPT prompts, 561 short / 324 medium / 115 long buckets.
- Loaded via the existing `vllm_grpc_bench.corpus.load_corpus(DEFAULT_CHAT_CORPUS_PATH)` mechanism.

**Embed corpus** (FR-035, NEW — Phase 1 prerequisite):
- Path: `tools/benchmark/corpus/completions_embeds_qwen3_8b/`
  - 1000 `.pt` files: `0000.pt` ... `0999.pt`, each containing a `seq_len × 4096` fp16 tensor.
  - `manifest.json` with per-entry SHA + `source_prompt_id` + `seq_len` + `bucket` + top-level `corpus_sha256` + `source_chat_corpus_sha256` + `model = "Qwen/Qwen3-8B"` + `hidden_size = 4096` + `generated_at_utc`.
- Generation: offline via `scripts/python/gen_embed_corpus_qwen3_8b.py` (~10-30 min on Modal A10G or local GPU). Generation is a one-time Phase 1 prerequisite per FR-035 — the corpus MUST exist and be committed before `--m6_2-validate` is invoked.
- Loaded via `vllm_grpc_bench.corpus.load_completions_embeds_qwen3_8b(corpus_dir)` (NEW helper added in round-5).

## `ignore_eos` plumbing

Round-5 parameterizes `ignore_eos` through the RPC builders:

**Chat (gRPC + REST)**: `m6_rpc_driver.py`

```python
# BEFORE (round-4 and earlier):
def _build_chat_grpc_request(seed: int) -> chat_pb2.ChatCompleteRequest:
    return chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role="user", content=_build_chat_prompt(seed))],
        model="mock-engine",
        max_tokens=M6_CHAT_MAX_TOKENS,  # hardcoded 50
        seed=seed,
    )

# AFTER (round-5):
def _build_chat_grpc_request(
    seed: int,
    *,
    max_tokens: int,
    ignore_eos: bool = False,
    prompt: str | None = None,
) -> chat_pb2.ChatCompleteRequest:
    content = prompt if prompt is not None else _build_chat_prompt(seed)
    return chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role="user", content=content)],
        model="mock-engine",
        max_tokens=max_tokens,
        seed=seed,
        ignore_eos=ignore_eos,
    )
```

Mirror changes on `_build_chat_rest_payload`. The historical M6.1.x call sites pass `max_tokens=M6_CHAT_MAX_TOKENS` (50) + `ignore_eos=False` + `prompt=None`, preserving binary compatibility.

**Embed (gRPC + REST)**: `m6_1_rpc_driver.py`

```python
# BEFORE:
def _build_embed_grpc_request(seq_len, hidden_size, rpc_index, base_seed, seed=None):
    payload = build_torch_save_bytes(seq_len, hidden_size, rpc_index, base_seed)
    sampling_seed = seed if seed is not None else base_seed + rpc_index
    return completions_pb2.CompletionRequest(
        prompt_embeds=payload,
        max_tokens=10,  # hardcoded
        seed=sampling_seed,
    )

# AFTER (round-5):
def _build_embed_grpc_request(
    seq_len, hidden_size, rpc_index, base_seed,
    *,
    max_tokens: int,
    ignore_eos: bool = False,
    prompt_embeds_override: bytes | None = None,
    seed: int | None = None,
):
    payload = prompt_embeds_override if prompt_embeds_override is not None else build_torch_save_bytes(seq_len, hidden_size, rpc_index, base_seed)
    sampling_seed = seed if seed is not None else base_seed + rpc_index
    return completions_pb2.CompletionRequest(
        prompt_embeds=payload,
        max_tokens=max_tokens,
        seed=sampling_seed,
        ignore_eos=ignore_eos,
    )
```

Mirror on `_build_embed_rest_payload_m6_1`. Historical callers pass `max_tokens=10` + `ignore_eos=False` + `prompt_embeds_override=None`.

**Note on `chat_pb2.ChatCompleteRequest.ignore_eos` and `completions_pb2.CompletionRequest.ignore_eos`**: Both proto messages would need an `ignore_eos: bool = false` field if they don't already have one. **This requires checking the `.proto` files** — if the field doesn't exist, the change would be a `.proto` edit (Constitution Principle I would require it to go through `make proto`). Investigation needed in Phase 2; the contract here documents the intended Python-level signature. If the proto field is missing, the alternative is to pass `ignore_eos` via gRPC metadata or REST request body alongside the existing fields — also additive at the wire level. **`/speckit-tasks` should investigate the proto schemas first thing.**

## Symmetric prompts helper — newly wired

The `symmetric_prompts.assign_symmetric_prompt(iter_idx, cohort, corpus)` function exists in M6.1.3's source (`symmetric_prompts.py:357-376`) but is **not called from any sweep module today** (`grep -rn 'assign_symmetric_prompt' tools/benchmark/src/` returns only its own definition). Round-5 makes it operative for M6.2's interior-cap and sub-probe regimes:

```python
# In m6_2_prompt_source.resolve_block_inputs(...):
from vllm_grpc_bench.symmetric_prompts import assign_symmetric_prompt

# For chat interior-cap or sub-probe:
chat_sample = assign_symmetric_prompt(iter_idx, cohort, [s for s in chat_corpus])
prompt_text = chat_sample.messages[0]["content"]  # adapt to RequestSample shape

# For embed interior-cap or sub-probe:
embed_sample = assign_symmetric_prompt(iter_idx, cohort, [s for s in embed_corpus])
embed_tensor_bytes = open(embed_sample.embed_file_path, "rb").read()  # or similar load mechanic
```

Cohort-invariance test: `test_m6_2_prompt_source.py::test_assign_symmetric_prompt_cohort_invariant` asserts that for any fixed `iter_idx`, calling `resolve_block_inputs(...)` with each of the 4 cohorts returns the same `prompt_text` (chat) or `embed_tensor_bytes` (embed) at the interior-cap or sub-probe regime.

## Per-row field semantics

Every `M6_2MeasurementPoint` row in the latency budget table carries:

- `prompt_source`: one of 4 literals per the regime table.
- `measurement_regime`: always `"natural_eos"` for budget-table rows (the `"forced_cap_ignore_eos_true"` regime is exclusive to `KVPressureObservation` and never appears in MeasurementPoint).
- `prompt_corpus_idx`: the `iter_idx` for corpus regimes; `None` for synthetic regimes.

Every `M6_2KVPressureObservation` record carries:

- `sub_probe_prompt_source`: `"corpus_sharegpt"` (chat) or `"corpus_sharegpt_embed"` (embed).
- `sub_probe_measurement_regime`: always `"forced_cap_ignore_eos_true"`.
- `sub_probe_n_rpcs`: always `20`.

## Corpus SHA validation (SC-018)

The sweep orchestrator validates corpus SHAs at sweep start, BEFORE any RPC dispatch:

```python
def run_m6_2(args, *, sweep_mode):
    # ... round-3 deferral gate ...
    chat_corpus = load_chat_corpus()  # raises CorpusDriftError on SHA mismatch
    embed_corpus = load_embed_corpus()  # raises CorpusDriftError on SHA mismatch
    # ... proceed to sweep ...
```

The artifact records the validated SHAs in `run_meta`:

```python
run_meta.chat_corpus_sha256 = load_chat_corpus_provenance().corpus_sha256
run_meta.chat_corpus_path = str(DEFAULT_CHAT_CORPUS_PATH)
run_meta.embed_corpus_sha256 = load_embed_corpus_manifest().corpus_sha256
run_meta.embed_corpus_path = str(DEFAULT_EMBED_CORPUS_DIR)
```

A post-sweep validator MAY re-check the SHAs at publish time; if the on-disk corpus has been modified between sweep start and publish, the validator fails with a `CorpusDriftError`. This is operator hygiene; the spec-level invariant is sweep-start validation.

## Test enforcement

In `tools/benchmark/tests/test_m6_2_prompt_source.py` (NEW per round-5):

- `test_resolve_chat_null_anchor_uses_synthetic`: assert chat at `max_tokens ∈ {10, 50}` returns `prompt_source = "synthetic_seed_derived"`, `prompt_corpus_idx = None`, `ignore_eos = False`.
- `test_resolve_chat_interior_uses_corpus`: assert chat at `max_tokens ∈ {256, 512, 1024, 2048}` returns `prompt_source = "corpus_sharegpt"`, `prompt_corpus_idx = iter_idx`, `ignore_eos = False`.
- `test_resolve_chat_sub_probe_uses_corpus_plus_ignore_eos`: assert chat sub-probe call with `ignore_eos_override=True` returns `prompt_source = "corpus_sharegpt"`, `ignore_eos = True`.
- Mirror tests for embed regimes.
- `test_assign_symmetric_prompt_cohort_invariant`: assert all 4 cohorts at fixed `iter_idx` get the same prompt.
- `test_chat_corpus_sha_mismatch_raises`: synthesize a corpus file with a different SHA than the provenance; assert `load_chat_corpus()` raises `CorpusDriftError`.
- `test_embed_corpus_missing_raises`: assert `load_embed_corpus()` raises `FileNotFoundError` when the corpus directory is absent (Phase 1 prerequisite enforcement).
- `test_run_meta_carries_corpus_shas`: assert artifact's `run_meta.chat_corpus_sha256` equals the provenance file's `corpus_sha256`; same for embed.
