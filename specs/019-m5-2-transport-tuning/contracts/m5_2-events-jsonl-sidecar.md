# Contract: M5.2 Per-Request Events JSONL Sidecar

The M5.2 harness emits one per-request labelled-events JSONL sidecar per full sweep at `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz` (gzipped per FR-012a). The sidecar is committed to the repo in gzipped form. Readers query the file with `zgrep` or `gunzip -c <file> | grep`; the regenerator (per `contracts/m5_2-regenerator.md`) decompresses it on read.

This contract pins the JSONL line format, the gzip discipline, the SHA-256 checksum protocol, and the regenerator's read contract.

## File location and form

- **Working file (during sweep)**: `bench-results/m5_2-full/{run_id}.events.jsonl` (un-gzipped, append-only). Lives in the gitignored `bench-results/` dir.
- **Committed file**: `docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz` (gzipped). The Phase-K1 narrative-summary commit copies the gzipped file from `bench-results/m5_2-full/{run_id}.events.jsonl.gz` to the docs path.
- **SHA-256 digest**: hex-encoded; recorded in the M5.2 JSON aggregate's executive metadata (`events_sidecar_sha256` top-level key) and in the M5.2 markdown's executive section.

## Line format

Each line of the (un-gzipped) JSONL is a single JSON object with exactly these keys (no additional keys allowed in M5.2; future milestones MAY extend the schema additively):

```json
{
  "cohort": "rest_https_edge",
  "path": "chat_stream",
  "hidden_size": 4096,
  "concurrency": 4,
  "network_path": "https_edge",
  "request_uuid": "550e8400-e29b-41d4-a716-446655440000",
  "issue_ts_ms": 12345.678,
  "first_byte_ts_ms": 12378.901,
  "done_ts_ms": 12456.234,
  "rtt_at_issue_ms": 52.4,
  "phase": "measurement",
  "server_bound": false,
  "request_body_bytes": 1247,
  "response_body_bytes": 8930,
  "status": "success"
}
```

### Field semantics

| Field | Type | Notes |
|-------|------|-------|
| `cohort` | string | One of: `rest_https_edge`, `rest_plain_tcp`, `default_grpc`, `tuned_grpc_multiplexed`, `tuned_grpc_channels`, `tuned_grpc` (at c=1). |
| `path` | string | `chat_stream` or `embed`. |
| `hidden_size` | int | 2048 \| 4096 \| 8192. |
| `concurrency` | int | 1 \| 4 \| 8. |
| `network_path` | string | `https_edge` or `plain_tcp`. Replicated from cohort for grep convenience. |
| `request_uuid` | string | uuid4-formatted hex. Unique within the run. |
| `issue_ts_ms` | float | Monotonic wall-clock at request issue, in milliseconds. |
| `first_byte_ts_ms` | float or null | First-byte timestamp for `chat_stream` (SSE first event); always `null` for `embed`. |
| `done_ts_ms` | float | Monotonic wall-clock at response completion, in milliseconds. |
| `rtt_at_issue_ms` | float | Cohort's measured RTT median at the moment the request was issued (snapshot — same value for all requests within a cohort, replicated per record for grep convenience). |
| `phase` | string | `warmup` or `measurement`. Warmup records are persisted (for audit) but excluded from aggregates per FR-011. The cohort runners (`rest_cohort.run_rest_cohort` + `m5_1_grpc_cohort.run_grpc_cohort`) snapshot warmup samples into a `warmup_samples` field on their result dataclasses; the M5.2 sweep's `write_cell_events_to_sidecar` emits the warmup records FIRST per cohort with `phase="warmup"` and `rtt_at_issue_ms=0.0` (the RTT probe hadn't run yet at warmup-issue time per FR-012a (f)), then the measurement records follow with the cohort's measured RTT. This persistence path was added post-implementation 2026-05-12 (Fix B) — earlier M5.1-inherited code discarded warmup samples internally, which violated FR-012a (g)'s persistence requirement. |
| `server_bound` | bool | Cohort-level flag, replicated per record. |
| `request_body_bytes` | int | Number of bytes in the request body (HTTP body bytes for REST; protobuf wire bytes for gRPC). |
| `response_body_bytes` | int | Number of bytes in the response body (sum across SSE frames for `chat_stream`; full body for `embed`). For `chat_stream` REST cohorts the implementation sums `len(line.encode()) + 1` (for the trailing `\n` that `httpx.aiter_lines` strips) across every yielded SSE line including the trailing `data: [DONE]` line. For gRPC chat_stream cohorts the implementation sums `len(chunk.SerializeToString())` across every received `ChatStreamChunk`. The two protocols' `response_body_bytes` are therefore comparable as "total response wire bytes" — earlier M5.1-era REST code captured only the first SSE line, which made the column incommensurable across protocols and was corrected 2026-05-12 per Fix A. |
| `status` | string | `success` \| `timeout` \| `error:<reason>` (e.g., `error:connection_reset`, `error:502_bad_gateway`). |

## Serialization rules

1. **Deterministic encoding**: `json.dumps(record_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. The `EventsSidecarWriter` applies this encoding to every record.
2. **One record per line**: each `json.dumps(...)` is followed by `"\n"`. No trailing newline at end-of-file is required (the reader handles both).
3. **No partial writes**: the writer flushes the buffer every N=1000 records to reduce loss on SIGKILL; the file's last line MAY be a partial record if the process was killed mid-flush. The reader skips partial trailing records silently (warns via stderr).
4. **No mid-stream gzip**: the writer appends to the un-gzipped file during the sweep and gzips-on-close (per R-4). This avoids the operational hazard of trying to gzip-append.

## Gzip protocol

On `EventsSidecarWriter.__exit__`:
1. `flush()` and `close()` the un-gzipped file.
2. `gzip` the file with `gzip --best` (Python `gzip.open(..., "wb", compresslevel=9)`).
3. Remove the un-gzipped intermediate.
4. Compute `hashlib.sha256(gzipped_file_bytes).hexdigest()`.
5. Expose the gzipped path + the SHA-256 hex via `EventsSidecarWriter.result`.

The gzip's deterministic-name rule: the gzipped file MUST be named `{un_gzipped_path}.gz` (i.e., the gzip footer preserves the un-gzipped filename for `gunzip` round-trip compatibility). The `mtime` field in the gzip header is set to 0 so the gzipped bytes are reproducible across runs of the regenerator on equivalent in-memory state.

## Reader contract

The regenerator reads the gzipped sidecar via `m5_2_events.read_sidecar_iter(path)`:

```python
def read_sidecar_iter(path: Path) -> Iterator[PerRequestEventRecord]:
    """Stream records from a gzipped JSONL sidecar.

    - Opens with gzip.open(path, "rt", encoding="utf-8").
    - Strips trailing whitespace from each line; skips empty lines.
    - On a JSON decode error or a missing required field: warns via
      stderr and skips the record (does NOT raise — partial trailing
      records from SIGKILL'd runs are recoverable).
    - On an unknown additional field: warns via stderr (forward-compat
      with future milestone extensions).
    - Yields PerRequestEventRecord instances.
    """
```

## Section-header filter syntax (for FR-012b field provenance)

The M5.2 markdown writer documents each aggregate's provenance using a "sidecar filter" expression. The expression is a `key=value AND key=value AND ...` form parsed by `m5_2_events.apply_filter(records, filter_str)`:

| Filter expression | Matches |
|-------------------|---------|
| `cohort=rest_https_edge` | all records where `cohort == "rest_https_edge"`. |
| `phase=measurement` | excludes warmup records. |
| `status=success` | excludes timeout / error records. |
| `path=chat_stream AND hidden_size=4096 AND concurrency=4` | one cell. |
| `cohort=tuned_grpc_multiplexed AND phase=measurement AND status=success` | typical aggregate-row filter. |

A markdown section header reads, e.g.:

```markdown
### Per-cell verdicts: chat_stream × h2048 × c=4

> Computed from events sidecar filter: `cohort IN {rest_https_edge,default_grpc} AND path=chat_stream AND hidden_size=2048 AND concurrency=4 AND phase=measurement AND status=success`.
```

so a reader can `zgrep` the sidecar with a matching pattern and verify the aggregate row by counting + median-ing the matching records. The filter expression is the M5.2 markdown's contract with the reader.

## `zgrep` quickstart

```bash
# All rest_https_edge chat_stream measurement records at c=4:
zgrep '"cohort":"rest_https_edge"' docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz | \
    grep '"path":"chat_stream"' | \
    grep '"concurrency":4' | \
    grep '"phase":"measurement"' | \
    head

# Count records per cohort:
gunzip -c docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz | \
    jq -r '.cohort' | sort | uniq -c

# Verify the file's SHA-256 against the report's executive metadata:
shasum -a 256 docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz
```

## Storage estimate

Per FR-012a:
- Full sweep: ≈84 cohorts × 250 measurement records + ~5 warmup × 84 cohorts ≈ 21,420 records.
- Per-record JSON ≈50–100 bytes (compact encoding).
- Raw: ≈14 MB. Gzipped at `--best`: ≈1.5–3 MB.

Smoke (`--m5_2-smoke`): ≈30 cohorts × 5 measurement + ~2 warmup × 30 ≈ 210 records. Gzipped: ~10–20 KB. Not committed (lives only in `bench-results/`).
