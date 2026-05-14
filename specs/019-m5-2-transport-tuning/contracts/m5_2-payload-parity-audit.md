# Contract: M5.2 Payload-Parity Code-Review Audit (FR-005c)

This is the operator-driven, code-review-only audit step the maintainer performs during Phase J of the M5.2 implementation plan. It protects against the **past regression where the REST harness was sending a different-sized embedding payload than the gRPC harness** — a regression no within-harness symmetry assertion can catch because both protocols would compute the wrong payload self-consistently.

The audit is a structured code reading. It is NOT a harness-automated assertion (those are covered by FR-005b's 3-tier symmetry block). The audit's findings are recorded in the M5.2 report's executive metadata so a future operator confirms the audit was performed.

**Per FR-005c, the audit MUST be performed against the M5.2 PR's harness HEAD before the K1 narrative-summary commit lands.**

---

## Step 1 — Read the chat-path payload construction side-by-side

Open these files in side-by-side panes:

- `tools/benchmark/src/vllm_grpc_bench/rest_cohort.py` — the function that builds the chat request body (look for `messages`, `max_tokens`, `temperature`, `stream`). The REST cohort now consumes a `RequestSample` from the chat corpus.
- `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py` — the function that builds the gRPC chat request (look for `_send_chat_rpc`, `ChatCompleteRequest`, `ChatMessage`). The gRPC cohort consumes the same `RequestSample` when the harness threads one through.
- `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` — confirm `dispatch_cell` threads `chat_corpus` into BOTH REST cohort calls AND all gRPC cohort calls.
- `tools/benchmark/src/vllm_grpc_bench/corpus.py` — the `RequestSample` schema + `load_corpus(path)` + `DEFAULT_CHAT_CORPUS_PATH` constant.
- `tools/benchmark/corpus/chat_sharegpt_1000.json` (and `.provenance.json`) — the committed ShareGPT V3 subset.

**Confirm** (post-implementation 2026-05-12 — chat-corpus-driven parity is now MANDATORY per spec [FR-005c Step 1 strict-reading addition](../spec.md)):
- [ ] Both protocols read the **same `RequestSample` from `chat_corpus` by `iteration % len(corpus)`** for a given iteration. The corpus is loaded once in `run_m5_2_sweep` and threaded through `dispatch_cell` to all cohort runners.
- [ ] Both protocols set **`max_tokens` from `sample.max_tokens`** (NOT a hardcoded default; NOT a `DEFAULT_CHAT_MAX_TOKENS` override). REST writes it into the JSON body; gRPC writes it into the protobuf `ChatCompleteRequest.max_tokens` field.
- [ ] Both protocols set **`temperature` from `sample.temperature`**. REST writes it into the JSON body; gRPC writes it into the protobuf `optional temperature` field.
- [ ] Both protocols pass `sample.messages` verbatim — same prompt content, same role labelling, same `messages` array.
- [ ] REST uses `stream=true` (SSE over HTTP/1.1); gRPC uses `CompleteStream` (bidi-stream). Both stream by design.
- [ ] No protocol-specific transform reshapes the prompt content (e.g., a REST-only sanitization or gRPC-only protobuf field reordering).
- [ ] The corpus's source identity is verifiable: `tools/benchmark/corpus/chat_sharegpt_1000.provenance.json` records the ShareGPT V3 revision SHA, source-file SHA-256, filter criteria, and random seed. Re-running `scripts/python/gen_chat_corpus.py` with the default parameters produces a byte-identical corpus JSON.
- [ ] `test_chat_corpus_parity.py` passes — the test suite locks in the corpus-driven path and forbids the legacy synthetic-prompt phrases ("Hello world", "M5.1 chat probe").

If any check fails, **STOP** and fix the harness; the audit cannot be completed until parity is restored. The fix lands in the M5.2 PR (NOT in a follow-up).

> **Historical note (2026-05-12, pre-corpus integration)**: An earlier version of the M5.2 harness used synthetic per-iteration prompts (`build_chat_prompt(iteration, cell_id)` with a hardcoded `DEFAULT_CHAT_MAX_TOKENS=64`) on both sides. The strict-reading audit Step 1 flagged this as a parity gap (different prompts, different max_tokens at the M5.1-inherited stage). The corpus integration above resolves the gap. See [research.md R-12](../research.md) for the methodology rationale.

## Step 2 — Read the embed-path payload construction side-by-side (THE PRIMARY REGRESSION GUARD)

Open the same two cohort files and the corpus loader plus the embed-payload constructor:

- `rest_cohort.py` — find the function that builds the embed request body (look for `input`, `prompt_embeds`, base64 encoding).
- `m5_1_grpc_cohort.py` — find the function that builds the gRPC embed request (look for `EmbeddingRequest`, `prompt_embeds`, `tensor` field).
- The embedding shape derivation code (likely `tools/benchmark/src/vllm_grpc_bench/corpus.py::derive_prompt_embeds_for_hidden_size`).

**Confirm — these are the regression-relevant checks**:
- [ ] Both protocols derive their embedding-input tensor from the **same hidden_size value**.
- [ ] Both protocols produce a tensor of the **same shape** (e.g., `(seq_len, hidden_size)`).
- [ ] Both protocols use the **same dtype** (e.g., `float32` or `bfloat16` — whichever the corpus loader produces).
- [ ] The resulting **byte size** of the embedding payload is **byte-identical** between protocols for a given `(embed, hidden_size)` cell, modulo protocol-wrapper overhead (HTTP JSON body's base64 wrapper bytes vs gRPC protobuf field-tag bytes — these wrapper bytes differ by a small constant, but the **engine-input content** must match exactly).
- [ ] **The past regression check**: read git log / `git blame` on the embed-payload constructor; confirm no commit since 2026-05-11 (M5.1 merge date) has changed the REST-side embed-payload construction in a way that diverged from gRPC. Cite the past regression by name in the audit notes: *"the REST harness was sending a different-sized embedding payload than gRPC"*.
- [ ] **Measure both payload sizes empirically**: run a one-off `python -c` snippet that imports the harness payload constructors and prints `len(rest_embed_body_bytes)` and `len(grpc_embed_request.SerializeToString())` for each of the three hidden_size values. Record the numbers; they MUST satisfy the byte-identity rule above.

If any check fails, **STOP** and fix the harness.

## Step 3 — Confirm no protocol-specific normalization changes effective payload

**Confirm**:
- [ ] Neither protocol applies a per-protocol input normalization (resizing, padding, dtype conversion, value scaling) that changes the **in-flight bytes** between protocols.
- [ ] Any normalization that exists is **applied symmetrically** in both protocols (or is a protocol-wrapper concern only, e.g., base64-encoding for REST's JSON body, which is decoded server-side before the engine sees it).

## Step 4 — Record the audit's findings

Append to `bench-results/m5_2-full/{run_id}.run_config.json` under the `payload_parity_audit` top-level key:

```json
{
  "payload_parity_audit": {
    "no_regression_confirmed_against_pr": "<SHA-or-PR#>",
    "auditor": "<your name or handle>",
    "audit_date_iso": "<YYYY-MM-DD>",
    "measured_payload_bytes": {
      "chat_rest_https_edge": <N1>,
      "chat_rest_plain_tcp": <N1>,
      "chat_grpc": <N2>,
      "embed_rest_https_edge": <N3>,
      "embed_rest_plain_tcp": <N3>,
      "embed_grpc": <N4>
    },
    "regression_named": "REST harness embed-payload-size divergence vs gRPC (M3-era, regression-protected here)",
    "notes": "<one paragraph free text noting any sub-finding worth surfacing>"
  }
}
```

The chat REST and gRPC byte sizes (`N1` vs `N2`) are not byte-equal because of the JSON-vs-protobuf wrapper difference; the regression-relevant constraint is that **`chat_rest_https_edge` == `chat_rest_plain_tcp`** (both REST cohorts are byte-identical) AND **`embed_rest_https_edge` == `embed_rest_plain_tcp` == `embed_grpc`** (embedding-input byte size is identical across protocols — the regression failure mode).

> **Note on `measured_payload_bytes` representativeness**: Since the chat corpus is ShareGPT V3 with variable-length prompts (short / medium / long buckets per R-12), the recorded chat byte values are **representative medians** across the corpus, NOT fixed per-request values. A reader audits chat-path parity by re-running the harness and confirming the median byte sizes match across the two REST cohorts (which iterate the same corpus). The audit's `measured_payload_bytes` field MAY include per-width breakouts (e.g., `embed_rest_https_edge_h2048`, `embed_rest_https_edge_h4096`, `embed_rest_https_edge_h8192`) as a superset of the contract's documented shape; the regenerator passes the dict through unchanged.

## Step 5 — Surface the audit in the report's executive metadata

The regenerator picks up the `payload_parity_audit` block from the run config and renders it into the M5.2 markdown's executive section as:

```markdown
**Payload-parity audit (FR-005c)**: no embed-payload-size regression confirmed against PR <SHA-or-#> (auditor: <name>, date: <YYYY-MM-DD>). Measured payload bytes (per request, by path and cohort): chat_rest=N1, chat_grpc=N2, embed_rest=N3, embed_grpc=N4.
```

Per SC-013, the PR description MUST cite the no-regression confirmation line + the SHA-or-# explicitly so a reviewer can verify the audit was performed without re-running the harness.

## Re-audit conditions

The audit MUST be re-performed if any of the following are true:

- The maintainer pushes a new commit to the M5.2 PR branch that **touches** any of: `rest_cohort.py`, `m5_1_grpc_cohort.py`, `corpus.py`, `rest_shim.py`, the embed-payload construction path in any of the above, or the FastAPI shim's request-body parsing.
- The Modal-deploy script (`modal_bench_rest_grpc_server.py`) changes in a way that affects request-body handling.

In those cases: update the `no_regression_confirmed_against_pr` field to the new commit SHA, re-record the audit_date_iso, and re-run the regenerator to refresh the executive metadata. The K1 narrative-summary commit MAY be rewritten (since it has not yet been pushed to a PR; the audit runs in Phase J, before K1).

If the re-audit happens after the M5.2 PR is already opened, the K1 commit's text is amended with the updated audit metadata and the PR description's audit citation is updated accordingly.
