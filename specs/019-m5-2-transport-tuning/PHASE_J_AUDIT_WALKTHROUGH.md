# Phase J — Payload-Parity Audit Walkthrough (quickstart Step 4)

A practical step-by-step walkthrough for completing the M5.2 payload-parity audit (`quickstart.md` Step 4, formalized in [`contracts/m5_2-payload-parity-audit.md`](contracts/m5_2-payload-parity-audit.md)).

This is the one **manual code-review step** in the whole M5.2 workflow. It exists because the past regression — REST and gRPC silently sending different-sized embed payloads — is invisible to within-harness symmetry checks (both protocols would compute the wrong bytes self-consistently). It's a code-reading + empirical-measurement pass with the findings recorded into the just-emitted `{run_id}.run_config.json`.

Total wall-clock: ~20-30 min if you're reading carefully, ~10 min if you've done it before.

---

## Step 4a — Side-by-side read: chat-path

Open two panes:

- **Pane L**: `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py:155-210` (`_single_chat_stream_request`)
- **Pane R**: `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py:95-150` (`_send_chat_rpc`)

Walk through the 7 checklist items in `contracts/m5_2-payload-parity-audit.md` §Step 1. The fields you're comparing across panes:

| Field | REST (pane L) | gRPC (pane R) |
|-------|---------------|---------------|
| Prompt content | `body["messages"] = sample.messages` (line 171) | `messages=[ChatMessage(role=m["role"], content=m["content"]) for m in sample.messages]` (line 108-110) |
| `max_tokens` | `body["max_tokens"] = sample.max_tokens` (line 173) | `max_tokens=sample.max_tokens` (line 112) |
| `temperature` | `body["temperature"] = sample.temperature` (line 174) | `temperature=sample.temperature` (line 113) |
| `seed` | omitted (FastAPI shim's pydantic model rejects it) | `seed=sample.seed` (line 114) |
| Stream | `stream=True` (line 172) → SSE | `CompleteStream` RPC (bidi-stream) |

The omitted-`seed` divergence is **intentional and noted in the code** (`rest_cohort.py:168` — "the shim's pydantic request model doesn't accept it"). The MockEngine doesn't use seed in token generation, so it's a wrapper difference, not a payload-content difference. **Note this in your audit's `notes` field.**

Also confirm the corpus is the source of truth:

```bash
# Sanity-check corpus identity (should match what the sweep loaded)
shasum -a 256 tools/benchmark/corpus/chat_sharegpt_1000.json
jq -r '.source_revision_sha, .source_file_sha256, .filter_criteria' \
   tools/benchmark/corpus/chat_sharegpt_1000.provenance.json

# Confirm corpus-parity tests still pass
uv run pytest tools/benchmark/tests/test_chat_corpus_parity.py -v
```

If `test_chat_corpus_parity.py` passes, the corpus-driven path is locked in and the legacy synthetic-prompt phrases ("Hello world", "M5.1 chat probe") are forbidden by the test suite.

---

## Step 4b — Side-by-side read + empirical measurement: embed-path **(THE PRIMARY REGRESSION GUARD)**

Open three panes:

- **Pane L**: `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py:213-254` (`_single_embed_request`)
- **Pane R**: `tools/benchmark/src/vllm_grpc_bench/m3_sweep.py:293-302` (`_build_embed_request` — the gRPC side)
- **Pane M**: `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py:153-170` (`_send_embed_rpc` — confirms it calls `_build_embed_request`)

The regression-relevant invariants to confirm:

| Property | REST | gRPC |
|---|---|---|
| `seq_len` | `16` (`rest_cohort.py:226`) | `seq_len=16` (`m3_sweep.py:294`, default) |
| `hidden_size` | param passed through | param passed through |
| Tensor shape | `(_SEQ_LEN, hidden_size)` (line 228) | `(seq_len, hidden_size)` (line 297) |
| Dtype | `np.float32` (line 228) | `np.float32` (line 297) |
| Raw bytes | `tensor.tobytes()` then base64 (line 229) | `arr.tobytes()` (line 301), no base64 — protobuf carries `bytes` field directly |
| Seed | `seed=hidden_size` (line 227) | `seed=seed ^ hidden_size ^ seq_len` (line 296) |

The seeds **differ** (REST uses `hidden_size` directly; gRPC uses `seed ^ hidden_size ^ seq_len`). That means the **values** in the tensor differ between protocols, but the **shape and byte count** are identical. The MockEngine doesn't care about content, only sizes — so this is a wrapper-level seed difference, not a content-bias regression. **Note in your audit's `notes` field.**

Now the empirical-bytes measurement. Run this from the repo root:

```bash
uv run python -c '
import base64, json
import numpy as np
from vllm_grpc_bench.corpus import load_corpus, DEFAULT_CHAT_CORPUS_PATH

# ---- Embed payload: REST vs gRPC byte sizes per hidden_size ----
SEQ_LEN = 16
print("# Embed payload sizes (bytes)")
print(f"{"hidden_size":<13}{"rest_body":<12}{"rest_engine_input":<20}{"grpc_proto":<12}{"grpc_engine_input":<20}")
for h in (2048, 4096, 8192):
    # REST side (rest_cohort.py:_single_embed_request)
    tensor = np.random.default_rng(seed=h).standard_normal((SEQ_LEN, h), dtype=np.float32)
    rest_raw = tensor.tobytes()
    rest_b64 = base64.b64encode(rest_raw).decode("ascii")
    rest_body = json.dumps({"model": "mock", "input_kind": "prompt_embedding_b64",
                            "input": rest_b64, "hidden_size": h}).encode()

    # gRPC side (m3_sweep.py:_build_embed_request)
    from vllm_grpc_bench import completions_pb2  # type: ignore
    arr = np.random.default_rng(seed=0 ^ h ^ SEQ_LEN).standard_normal((SEQ_LEN, h), dtype=np.float32)
    req = completions_pb2.CompletionRequest(model="mock-engine", max_tokens=10, prompt_embeds=arr.tobytes())
    grpc_wire = req.SerializeToString()

    # "Engine input" = the raw tensor bytes the engine actually consumes
    # (REST decodes base64 server-side; gRPC carries protobuf bytes field directly).
    print(f"{h:<13}{len(rest_body):<12}{len(rest_raw):<20}{len(grpc_wire):<12}{len(arr.tobytes()):<20}")

# ---- Chat payload: REST vs gRPC representative byte sizes (corpus medians) ----
print()
print("# Chat payload sizes (bytes, representative median over first 100 corpus samples)")
corpus = load_corpus(DEFAULT_CHAT_CORPUS_PATH)
from vllm_grpc_bench import chat_pb2  # type: ignore
rest_sizes, grpc_sizes = [], []
for sample in corpus[:100]:
    rest_body = json.dumps({"model": "mock", "messages": sample.messages, "stream": True,
                            "max_tokens": sample.max_tokens, "temperature": sample.temperature}).encode()
    rest_sizes.append(len(rest_body))
    req = chat_pb2.ChatCompleteRequest(
        messages=[chat_pb2.ChatMessage(role=m["role"], content=m["content"]) for m in sample.messages],
        model="mock-engine", max_tokens=sample.max_tokens,
        temperature=sample.temperature, seed=sample.seed,
    )
    grpc_sizes.append(len(req.SerializeToString()))
rest_sizes.sort(); grpc_sizes.sort()
print(f"chat REST  body median = {rest_sizes[50]} bytes")
print(f"chat gRPC proto median = {grpc_sizes[50]} bytes")
'
```

**Expected numbers**:

- **`rest_engine_input == grpc_engine_input`** for each hidden_size: `16 × 4 × hidden_size` = **131072 / 262144 / 524288 bytes** for h=2048/4096/8192 respectively. **This is the regression-guard equality** — if these diverge, STOP and fix the harness.
- **`rest_body`** ≈ `(4/3) × rest_engine_input + ~80 bytes` (base64 inflation + JSON wrapper).
- **`grpc_proto`** ≈ `grpc_engine_input + ~30 bytes` (protobuf tag/length prefixes + `model` + `max_tokens` fields).
- **`chat_rest_body`** and **`chat_grpc_proto`** are NOT equal by design — JSON vs protobuf wrappers differ. Just record both as representative medians.

---

## Step 4c — Confirm no protocol-specific normalization

Skim both cohort files for any per-protocol input transform that could change effective payload semantics. The current state:

- REST does base64-encode for JSON transit (decoded server-side before the engine sees it).
- gRPC carries protobuf bytes directly.
- Both reach the engine with the same `(seq_len, hidden_size)` float32 tensor.
- No resizing, no dtype conversion, no value scaling.

**Note this in your `notes` field.**

---

## Step 4d — Record findings into the run config

Find the run_id from the full-sweep output line (`run_id=m5_2-...`), then:

```bash
RUN_CONFIG=bench-results/m5_2-full/m5_2-XXXXXXXXXXXX.run_config.json   # fill in the run_id
PR_HEAD_SHA=$(git rev-parse HEAD)   # current M5.2 branch HEAD
AUDIT_DATE=$(date -u +%F)

# Patch the payload_parity_audit block in-place
uv run python -c "
import json, sys
path = '$RUN_CONFIG'
cfg = json.load(open(path))
cfg['payload_parity_audit'] = {
    'no_regression_confirmed_against_pr': '$PR_HEAD_SHA',
    'auditor': 'bsansom',
    'audit_date_iso': '$AUDIT_DATE',
    'measured_payload_bytes': {
        # Fill these in from the python -c snippet output above
        'chat_rest_https_edge': <chat_rest_body_median>,
        'chat_rest_plain_tcp':  <chat_rest_body_median>,
        'chat_grpc':            <chat_grpc_proto_median>,
        'embed_rest_https_edge_h2048': 131072,
        'embed_rest_https_edge_h4096': 262144,
        'embed_rest_https_edge_h8192': 524288,
        'embed_rest_plain_tcp_h2048':  131072,
        'embed_rest_plain_tcp_h4096':  262144,
        'embed_rest_plain_tcp_h8192':  524288,
        'embed_grpc_h2048': 131072,
        'embed_grpc_h4096': 262144,
        'embed_grpc_h8192': 524288,
    },
    'regression_named': 'REST harness embed-payload-size divergence vs gRPC (M3-era, regression-protected here)',
    'notes': 'REST drops sample.seed (FastAPI shim pydantic model rejects it); gRPC embed seed = seed ^ hidden_size ^ seq_len while REST embed seed = hidden_size, so tensor values differ but shape/dtype/byte-count are byte-identical at the engine input. No protocol-specific normalization applied — REST base64-encodes for JSON transit (decoded server-side), gRPC carries protobuf bytes directly.',
}
json.dump(cfg, open(path, 'w'), indent=2)
print(f'Patched {path}')
"
```

The contract documents `measured_payload_bytes` as a base schema with chat/embed entries, but explicitly **allows per-width breakouts as a superset** (`contracts/m5_2-payload-parity-audit.md:85`). The above uses the superset form because embed bytes depend on hidden_size.

---

## Step 4e — Nothing more to do here

Step 5 of `contracts/m5_2-payload-parity-audit.md` ("surface the audit in the executive metadata") is automatic: the regenerator in Step 5 of `quickstart.md` reads `payload_parity_audit` from the run config and renders the line:

```markdown
**Payload-parity audit (FR-005c)**: no embed-payload-size regression confirmed against PR <SHA> (auditor: ..., date: ...). Measured payload bytes (per request, by path and cohort): chat_rest=N1, chat_grpc=N2, embed_rest=N3, embed_grpc=N4.
```

into the markdown report's executive section. You don't write that line by hand.

After Step 4d, **jump straight to `quickstart.md` Step 5** (the regenerator).

---

## Re-audit triggers

The audit MUST be re-performed if any commit between this audit and K1 touches:

- `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py`
- `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py`
- `tools/benchmark/src/vllm_grpc_bench/corpus.py`
- `tools/benchmark/src/vllm_grpc_bench/m3_sweep.py` (`_build_embed_request`)
- The FastAPI shim's request-body parsing path
- `scripts/python/modal_bench_rest_grpc_server.py` (request-body handling)

In those cases: update `no_regression_confirmed_against_pr` to the new HEAD, refresh `audit_date_iso`, and re-run the regenerator.
