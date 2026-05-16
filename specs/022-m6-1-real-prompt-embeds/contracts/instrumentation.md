# Contract: M6.1 Prompt-Embeds Wire Format + Engine-Cost Instrumentation

**Plan**: [../plan.md](../plan.md)
**Spec FRs**: FR-002 (gRPC embed wire format), FR-003 (REST embed wire format), FR-004 (REST input_kind dual coexistence), FR-006 (torch pin + validation), FR-018 (engine_cost emission — reused from M6), FR-028 (tensor shape + values)
**Research**: [R-1](../research.md#r-1-frontend-dispatch-already-routes-torchsave-bytes-to-real-prompt-embeds), [R-2](../research.md#r-2-torch-client-side-version-pin-policy), [R-3](../research.md#r-3-seq_len-pinning-to-m6s-tokenised-text-digest-length)

This document fixes the wire-format contracts for two surfaces:
1. The prompt-embeds tensor payload (gRPC `prompt_embeds` field +
   REST `input_kind="prompt_embedding_torch_b64"`).
2. The engine-cost instrumentation (gRPC trailing metadata + REST JSON
   `engine_cost` field) — **reused unchanged from M6**.

The change vector versus M6 is the prompt-embeds payload encoding. The
engine-cost contract is reused verbatim because the engine wraps its
forward pass identically regardless of whether the input is text or a
tensor.

---

## 1. gRPC embed cohort wire format (FR-002 / FR-028)

### Where the payload is built

`tools/benchmark/src/vllm_grpc_bench/m6_1_rpc_driver.py` — the M6.1
embed request builder for gRPC cohorts (`default_grpc`,
`tuned_grpc_multiplexed`).

### Payload encoding

```python
# Pseudocode for the gRPC embed request builder
import io
import torch
from vllm_grpc.v1 import completions_pb2

def _build_embed_grpc_request(seq_len: int, hidden_size: int, seed: int) -> completions_pb2.CompletionRequest:
    """M6.1 — ship torch.save(tensor) bytes in prompt_embeds.

    The frontend's _resolve_prompt_embeds_input dispatch in
    packages/frontend/src/vllm_grpc_frontend/completions.py:49 sees
    the ZIP magic prefix (PK\\x03\\x04) and routes to decode_embeds
    instead of the text-digest hash, driving the
    enable_prompt_embeds=True engine path.
    """
    g = torch.Generator(device="cpu").manual_seed(M6_1_BASE_SEED + seed)
    tensor = torch.randn((seq_len, hidden_size), dtype=torch.float16, generator=g)
    buf = io.BytesIO()
    torch.save(tensor, buf)
    return completions_pb2.CompletionRequest(
        prompt_embeds=buf.getvalue(),  # ZIP-magic-prefixed torch.save bytes
        max_tokens=10,                  # FR-028 — embed unary, max_tokens=10 reused from M6
        seed=seed,                      # FR-019 — per-RPC seed forwarded to SamplingParams
    )
```

### Wire shape requirements

| Property | Value | Spec | Source |
|---|---|---|---|
| proto field | `CompletionRequest.prompt_embeds` (`bytes`) | (unchanged from M5.x / M6) | `proto/vllm_grpc/v1/completions.proto` |
| byte prefix | `PK\x03\x04` (ZIP magic) | FR-002 / R-1 | `torch.save` invariant |
| tensor shape | `[seq_len, hidden_size=4096]` | FR-028 | `m6_1_seq_len.py` pins seq_len at sweep start |
| tensor dtype | `torch.float16` | FR-028 | matches loaded model weights |
| seed → values | `torch.Generator(device='cpu').manual_seed(M6_1_BASE_SEED + rpc_index)` then `torch.randn(...)` | FR-028 / FR-019 | per-RPC determinism |

### Frontend behaviour (reused unchanged)

The frontend's existing `_resolve_prompt_embeds_input` helper (at
`packages/frontend/src/vllm_grpc_frontend/completions.py:49`) handles the
dispatch:
1. Checks first 4 bytes against `b"PK\x03\x04"`.
2. Matches → call `decode_embeds(raw_bytes)` → return
   `{"prompt_embeds": tensor}`.
3. No match → fall back to `_prompt_embeds_to_text_digest(raw_bytes)` (the
   M5.x / M6 path).

`decode_embeds` requires `ndim == 2` and dtype in `{float32, bfloat16,
float16}`; M6.1's `[seq_len, 4096] fp16` tensors satisfy both. No frontend
change is required.

---

## 2. REST embed cohort wire format (FR-003 / FR-004 / FR-028)

### Where the payload is built

`tools/benchmark/src/vllm_grpc_bench/rest_cohort.py` — modified to emit
`input_kind="prompt_embedding_torch_b64"` under the `--m6_1` dispatch path.

### Where the payload is consumed

`tools/benchmark/src/vllm_grpc_bench/rest_shim.py` — modified to recognise
the new `input_kind` value alongside the existing
`prompt_embedding_b64` and `text` values.

### Payload encoding

```python
# Client side (rest_cohort.py) — pseudocode
import base64
import io
import torch

def _build_embed_rest_payload_m6_1(seq_len: int, hidden_size: int, seed: int) -> dict[str, Any]:
    g = torch.Generator(device="cpu").manual_seed(M6_1_BASE_SEED + seed)
    tensor = torch.randn((seq_len, hidden_size), dtype=torch.float16, generator=g)
    buf = io.BytesIO()
    torch.save(tensor, buf)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return {
        "model": "mock",
        "input_kind": "prompt_embedding_torch_b64",   # NEW per FR-003
        "input": encoded,
        "hidden_size": hidden_size,
        "max_tokens": 10,
        "seed": seed,
    }
```

### REST shim handler shape

```python
# rest_shim.py — pseudocode for the modified embed handler
@shim.post("/v1/embeddings")
async def embeddings(req: _EmbedRequest) -> Any:
    if req.input_kind not in ("prompt_embedding_b64", "prompt_embedding_torch_b64", "text"):
        return JSONResponse({"error": "unsupported input_kind"}, status_code=422)

    if req.input_kind == "prompt_embedding_torch_b64":
        # FR-003 — new M6.1 path: real prompt-embeds tensor.
        try:
            raw_bytes = base64.b64decode(req.input, validate=True)
        except (ValueError, base64.binascii.Error):
            return JSONResponse({"error": "input not valid base64"}, status_code=400)
        # Reuse the frontend's decode_embeds (imported from
        # vllm_grpc_frontend.completions_translate) so the REST and gRPC
        # paths use the same deserialisation primitive.
        try:
            tensor = decode_embeds(raw_bytes)
        except ValueError as exc:
            return JSONResponse({"error": f"decode_embeds failed: {exc}"}, status_code=422)
        prompt: Any = {"prompt_embeds": tensor}  # drives enable_prompt_embeds=True

    elif req.input_kind == "prompt_embedding_b64":
        # FR-004 — preserved M5.x / M6 path: raw float32 bytes hashed to a text digest.
        try:
            raw_bytes = base64.b64decode(req.input, validate=True)
        except (ValueError, base64.binascii.Error):
            return JSONResponse({"error": "input not valid base64"}, status_code=400)
        digest = hashlib.blake2b(raw_bytes, digest_size=8).hexdigest()
        prompt = f"embeds:{digest}"

    else:  # text
        prompt = req.input

    # ... rest of handler unchanged (engine.generate, engine_cost emission, etc.)
```

### Wire shape requirements (FR-003 sub-clauses)

| Property | Value | Spec |
|---|---|---|
| `input_kind` | `"prompt_embedding_torch_b64"` | FR-003 |
| `input` field | base64-encoded `torch.save(tensor)` bytes | FR-003 |
| Separate `dtype` field | NOT present in the request body | FR-003 (round-2 Q2) |
| Separate `shape` field | NOT present in the request body | FR-003 (round-2 Q2) |
| Tensor shape + dtype recovery | Done server-side by `decode_embeds` | FR-003 / R-1 |
| `hidden_size` field | Present (used for cell-routing only); MUST match tensor's `shape[1]` | FR-003 |
| `max_tokens` | `10` (matches M6 embed convention) | FR-005 / M6 reuse |
| `seed` | per-RPC `M6_1_BASE_SEED + rpc_index` | FR-019 / FR-028 |

### Coexistence with `prompt_embedding_b64` (FR-004)

Both `input_kind` values MUST be accepted by the REST shim indefinitely:
- `prompt_embedding_b64` — raw float32 bytes (no torch dependency on
  client); server hashes to a text digest before engine call. Engine work
  is text-prompt unary completion. Used by M5.x / M6 reproductions.
- `prompt_embedding_torch_b64` — base64-encoded `torch.save` bytes; server
  calls `decode_embeds` and ships `{"prompt_embeds": tensor}` to the engine.
  Engine work is real prompt-embeds inference via `enable_prompt_embeds=True`.
  Used by M6.1+ sweeps.

The REST contract documentation (in the FastAPI shim or a dedicated
markdown file under `tools/benchmark/`) MUST name both values, describe
their engine-side behaviour, and point readers at M6.1's published
"Engine path differential" section as the decision aid for choosing
between them.

---

## 3. Client-side torch pin + driver-start validation (FR-006)

### Where it lives

`tools/benchmark/src/vllm_grpc_bench/m6_1_torch_pin.py` — module that
holds the pinned version constant and the validation function.

### Pin

`torch==2.11.0` — the exact version vLLM 0.20.1 requires transitively (per
[Research R-2](../research.md#r-2-torch-client-side-version-pin-policy)).
The pin lives in two places that MUST stay in sync:
1. `tools/benchmark/pyproject.toml` `[project.dependencies]` —
   `torch==2.11.0`.
2. `tools/benchmark/src/vllm_grpc_bench/m6_1_torch_pin.py`:
   `_EXPECTED_TORCH_VERSION: Final[str] = "2.11.0"`.

A unit test in `tests/m6_1/test_torch_pin.py` MUST assert these two values
match (failing closed if a future bump only updates one of them).

### Validation function

```python
# m6_1_torch_pin.py — pseudocode
import sys
from typing import Final

_EXPECTED_TORCH_VERSION: Final[str] = "2.11.0"

def validate_torch_version() -> str:
    """Validate torch.__version__ matches the M6.1 pinned version.

    Raises SystemExit(2) with a clear actionable message if mismatched.
    Returns the detected version on success.

    Called once at the start of M6.1 smoke + full sweep, BEFORE the first
    measurement RPC of the first embed cohort (FR-006). Failing here saves
    the operator from a downstream silent decode_embeds failure that would
    surface as cell_incomplete (FR-017 floor).
    """
    try:
        import torch
    except ImportError:
        print(
            "M6.1 ERROR: torch is required on the client to ship prompt-embeds tensors.\n"
            f"  Install: pip install torch=={_EXPECTED_TORCH_VERSION}\n"
            "  See: specs/022-m6-1-real-prompt-embeds/quickstart.md § Prerequisites.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    detected = torch.__version__
    if detected != _EXPECTED_TORCH_VERSION:
        print(
            f"M6.1 ERROR: client torch version mismatch.\n"
            f"  Expected: {_EXPECTED_TORCH_VERSION} (matches vllm==0.20.1 transitive pin)\n"
            f"  Detected: {detected}\n"
            f"  Reason: torch.save / torch.load wire format may differ across versions\n"
            f"          (FR-006). Fix: pip install torch=={_EXPECTED_TORCH_VERSION}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return detected
```

### Where it's called

- `m6_1_sweep.run_sweep()` — first call, before deploying Modal app.
- `m6_1_smoke.run_smoke()` — first call, before any RPC.

Calling it before Modal deploy means the operator pays no Modal compute
cost when their local torch is misversioned.

---

## 4. Engine-cost instrumentation (REUSED FROM M6 — FR-018)

The engine-cost wire contract is unchanged from M6. This section is
intentionally brief — see [M6's contracts/instrumentation.md](../../020-m6-real-engine-mini-validation/contracts/instrumentation.md)
for the canonical specification.

### Summary (cross-reference)

| Path | Cohort | Wire channel | Field / key |
|---|---|---|---|
| embed | gRPC | trailing metadata | `engine-forward-ms` (string-encoded float) |
| embed | REST | JSON top-level | `engine_cost.engine_forward_ms` (float) |
| chat_stream | gRPC | trailing metadata (on stream completion) | `engine-ttft-ms`, `engine-tpot-ms` |
| chat_stream | REST | JSON top-level on final SSE event | `engine_cost.engine_ttft_ms`, `engine_cost.engine_tpot_ms` |

### Harness-side parser

`tools/benchmark/src/vllm_grpc_bench/m6_engine_cost.py` — REUSED verbatim
from M6. M6.1's sweep orchestrator calls
`parse_grpc_trailing_metadata(...)` and `parse_rest_response(...)`
unchanged.

### Drift warning (engine_cost_drift_warning — FR-022)

Same algorithm M6 used: pairwise comparison of per-cohort engine_cost
means; flag if any pair disagrees by >10% (threshold relative to the
smaller value). Effect on classification: diagnostic only — verdicts still
computed, per-cohort values surfaced in the JSON and markdown.

---

## 5. Chat_stream control-drift instrumentation (NEW — FR-029)

The chat_stream control-drift check is post-sweep (not at smoke per
FR-012), so there's no per-RPC wire format involved. The check operates
on aggregated per-cohort CIs from M6.1 versus M6's published per-cohort
CIs. See [Research R-6](../research.md#r-6-chat_stream-control-drift-check-algorithm)
for the algorithm and [`output.md`](./output.md) for how the
`chat_stream_control_drift_warning` flag is surfaced in the report.

The check is implemented in
`tools/benchmark/src/vllm_grpc_bench/m6_1_drift_check.py` and is invoked
exactly once at the end of full sweep, after all 6 cells have been
classified. The smoke gate MUST NOT call this module.

---

## 6. Failure modes and observability

| Failure mode | Symptom in M6.1 | Action |
|---|---|---|
| `torch` not importable on client | Exit code 2 from `--m6_1` or `--m6_1-smoke` at startup, with a clear stderr message naming `torch` (FR-006) | Operator installs `torch==2.11.0` |
| `torch.__version__` mismatch | Exit code 2 from `--m6_1` or `--m6_1-smoke` at startup, with a clear stderr message naming both detected and expected versions (FR-006) | Operator runs `pip install torch==2.11.0` |
| `decode_embeds` raises on the server (malformed `torch.save` bytes) | RPC counted as failure, retried up to 3 attempts; contributes to `cell_incomplete` floor (FR-017) | Per-RPC events sidecar `failure_reason` field carries the underlying ValueError |
| Tensor dtype/shape mismatch with engine | Same — engine-side error → RPC failure → retry → `cell_incomplete` if cohort drops below 80 | Per-RPC events sidecar carries the failure cause |
| REST shim returns 422 on `prompt_embedding_torch_b64` (shim version too old) | RPC failure → retry → `cell_incomplete` | Operator checks Modal app deploy is the M6.1 branch's rest_shim.py |
| GPU OOM under real prompt-embeds activations | RPC failure → retry → `cell_incomplete` (FR-017) — preferred over harness abort so other cells still complete | Operator investigates via events sidecar; if pervasive, check Modal app's engine config |
| Engine path mistakenly routed to text-digest (e.g., raw bytes shipped under `--m6_1`) | Engine cost looks identical to M6 baseline (because the engine path IS the M6 baseline); verdict differential would be near-zero | Suspect a regression in the gRPC payload builder; check that `torch.save` bytes are shipped, not `tensor.tobytes()` |
| `engine_cost_drift_warning` fires on every cell | Likely REST shim instrumentation regression OR cohort engine paths diverged | File issue; inspect per-cohort engine_cost values in JSON |
| `chat_stream_control_drift_warning` fires on every chat_stream cell | Infrastructure drift between M6 sweep and M6.1 sweep (Modal flake, region drift) | Operator weights embed-cell verdicts cautiously; consider re-running M6 baseline + M6.1 same-period |
