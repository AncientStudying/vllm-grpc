# Contract: M5.2 Round-Trippable Regenerator

The M5.2 markdown report and aggregate JSON at `docs/benchmarks/m5_2-transport-vs-tuning.{md,json}` are produced by a regenerator tool that reads only the gzipped events JSONL sidecar (`docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz`) and the per-run configuration captured at run start. The harness MUST NOT emit the markdown or aggregate JSON directly (per FR-012b).

The regenerator extends `scripts/python/regen_bench_reports.py` (which already exists for earlier phases). The extension is invoked via `--m5_2-sidecar PATH` and `--m5_2-run-config PATH`.

## Synopsis

```text
uv run python scripts/python/regen_bench_reports.py \
    --m5_2-sidecar docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz \
    --m5_2-run-config bench-results/m5_2-full/{run_id}.run_config.json \
    [--m5_2-report-out docs/benchmarks/m5_2-transport-vs-tuning]
```

The `--m5_2-report-out` flag is a path prefix (without extension); the regenerator writes `{prefix}.md` and `{prefix}.json`.

## Inputs

1. **Gzipped events JSONL sidecar** (`--m5_2-sidecar`): see `contracts/m5_2-events-jsonl-sidecar.md`.
2. **Per-run config** (`--m5_2-run-config`): a JSON file written by the sweep at run start, containing:
   - `run_id` (string).
   - `run_started_at_iso` (ISO 8601 string).
   - `run_realized_runtime_s` (float; emitted at run end and patched into the file after the sweep completes).
   - `seed` (int).
   - `symmetry` (object — the SymmetryBlock per `data-model.md`).
   - `events_sidecar_sha256` (string — SHA-256 hex of the gzipped sidecar; the regenerator uses this to verify the input).
   - `modal_region` (string).
   - `modal_instance_class` (string).
   - `https_edge_endpoint` (string).
   - `client_external_geolocation` (object \| null).
   - `payload_parity_audit` (object — added by the operator during Phase J before the regenerator runs; see `contracts/m5_2-payload-parity-audit.md`).
   - `smoke_run_outcome` (object — copied from the prior `--m5_2-smoke` invocation's output).

## Algorithm

1. **Load + validate the run config**. Raises `RunConfigInvalid` on missing required keys.
2. **Open the gzipped sidecar**. Compute the file's SHA-256. Compare against `run_config["events_sidecar_sha256"]`. On mismatch, raise `SidecarChecksumMismatch(expected=<hex>, observed=<hex>)` and refuse to produce artifacts. (Per FR-012b.)
3. **Stream the JSONL** via `m5_2_events.read_sidecar_iter`. Build the in-memory `M5_2Aggregates` dataclass:
    - Per-cohort medians, p95s, 95% CIs on the time metric (TTFT for `chat_stream`; total wall-clock for `embed`). Warmup-phase records excluded per FR-011.
    - Per-cohort RTT median + p95 (from `rtt_at_issue_ms` snapshot).
    - Per-cohort byte aggregates (`request_body_bytes`, `response_body_bytes` medians + p95).
    - Per-cohort `connections_opened` (counted via `request_uuid` cardinality + concurrency math — replicated from the cohort metadata in the run config).
4. **Build the two verdict families per cell** (FR-009):
    - Protocol comparison: each gRPC cohort vs `rest_https_edge`. Verdict literal via the same 95% CI-clearing rule M5.1 and M5 use.
    - Transport-only comparison: `rest_https_edge` vs `rest_plain_tcp`. Same statistical rule.
5. **Re-run `m5_2_symmetry.assert_symmetry(run_config["symmetry"], concurrency_levels)`** at report-build time. The regenerator MUST refuse to publish on tier (a) or tier (b) divergence (per FR-005b). Raises `SymmetryAssertionFailed` if the persisted symmetry block has been hand-edited to a divergent state.
6. **Load M5.1's published JSON** at `docs/benchmarks/m5_1-rest-vs-grpc.json`. Build the `supersedes_m5_1` table via `m5_2_supersede.build_supersedes_m5_1(m5_1_cells, m5_2_cells)`.
7. **Compute the HTTPS-edge vs plain-TCP RTT delta** (`rest_https_edge` RTT median − `rest_plain_tcp` RTT median, both signed).
8. **Build the M5_2Run dataclass** with all of the above.
9. **Write the aggregate JSON** using `json.dumps(M5_2Run.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)`. Output is byte-stable across regenerator invocations on equivalent inputs.
10. **Write the markdown report**:
    - Executive section: headline finding(s) per verdict family; HTTPS-edge vs plain-TCP RTT delta; `noise_resolved` count; payload-parity audit confirmation line citing the audit's PR-SHA-or-#; smoke-gate outcome metadata; client external geolocation (if recorded); MockEngine read-instruction caveat.
    - Per-(path × hidden_size × concurrency) comparison matrix: both verdict families per cell; network path named on every row.
    - Supersedes-M5.1 table.
    - Negative-results appendix (cells where verdict is `no_winner` or `comparison_unavailable` with full per-cohort CI bounds).
    - Field-provenance footnotes: each section header names the sidecar filter or aggregate-JSON key the section summarizes (per FR-012b).
    - Sidecar SHA-256 + executive metadata block at the bottom of the report so the reader can copy-paste it into a `shasum -a 256` command for verification.
11. **Return `RegenerationResult(markdown_path, json_path, sidecar_path, observed_sha256, computed_aggregates_count)`**.

## Round-trip contract

The regenerator MUST be **idempotent on a given sidecar + run config**. Specifically:

- Re-running the regenerator with the same `--m5_2-sidecar` and `--m5_2-run-config` MUST produce byte-identical markdown + aggregate JSON on every invocation.
- No `datetime.now()` / no random / no environment-derived value enters the output. All timestamps come from `run_config["run_started_at_iso"]` or from the sidecar's event records.
- Deterministic JSON encoding via `sort_keys=True, separators=(",", ":")`. Deterministic Markdown via stable column ordering, stable row ordering (alphabetical by primary key — cell coordinates ascending, then cohort alphabetical).

This contract is verified by:
- **Unit test** `tools/benchmark/tests/test_m5_2_regenerator.py::test_round_trip_byte_identical`: fixture a 50-record synthetic sidecar + matching run config; run the regenerator twice; `assert open(md, "rb").read() == open(md_rerun, "rb").read()`.
- **Operator pre-PR diff** (per `quickstart.md`): after the sweep + the K1 commit, the maintainer re-runs the regenerator on the committed sidecar + run config and `git diff` the produced artifacts; expectation is no diff.

## SHA-256 verification rule

The regenerator computes SHA-256 of the gzipped sidecar (the entire file's bytes — `hashlib.sha256(open(path, "rb").read()).hexdigest()`) and compares to `run_config["events_sidecar_sha256"]`. Mismatch raises `SidecarChecksumMismatch` and the regenerator refuses to produce artifacts. This catches:
- Sidecar truncation (e.g., git-LFS partial pull, disk full during commit).
- Manual edit of the gzipped file post-commit.
- Tampering between sidecar capture and report regeneration.

The SHA-256 is also surfaced in the report's executive metadata so a reader can `shasum -a 256 docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz` and compare against the report's printed digest.

## Field-provenance documentation rule (FR-012b)

Every aggregate the markdown report renders MUST be preceded by a `> Computed from events sidecar filter: <filter_expression>.` blockquote OR a `> Computed from aggregate JSON key: <json_path>.` blockquote, naming exactly the filter (per `contracts/m5_2-events-jsonl-sidecar.md` filter syntax) or JSON key the regenerator used to compute the value. Examples:

```markdown
### Per-cell verdicts: chat_stream × h2048 × c=4

> Computed from events sidecar filter: `cohort IN {rest_https_edge,default_grpc,tuned_grpc_multiplexed} AND path=chat_stream AND hidden_size=2048 AND concurrency=4 AND phase=measurement AND status=success`.

| Cohort | Network path | n | Median TTFT (ms) | 95% CI | Verdict family / row |
|--------|--------------|---|------------------|--------|----------------------|
| ... |
```

The reader copies the filter expression, runs `zgrep`-equivalent against the gzipped sidecar, counts + medians the matching records, and verifies the row's number. This is what makes the report's numbers auditable without reading the regenerator's source.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Regeneration succeeded; markdown + JSON written. |
| 2 | Flag conflict or missing required input. |
| 4 | Run config invalid (missing required key, malformed JSON). |
| 5 | Symmetry assertion failed at report-build time. |
| 8 | Sidecar SHA-256 mismatch (refused to produce artifacts). |
| 9 | M5.1 published JSON unreadable or schema mismatch (supersedes-M5.1 table cannot be built). |

## Examples

```bash
# Standard regeneration after a sweep:
uv run python scripts/python/regen_bench_reports.py \
    --m5_2-sidecar docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz \
    --m5_2-run-config bench-results/m5_2-full/{run_id}.run_config.json

# Operator pre-PR diff (round-trip verification):
uv run python scripts/python/regen_bench_reports.py \
    --m5_2-sidecar docs/benchmarks/m5_2-transport-vs-tuning.events.jsonl.gz \
    --m5_2-run-config bench-results/m5_2-full/{run_id}.run_config.json \
    --m5_2-report-out /tmp/m5_2-roundtrip
diff /tmp/m5_2-roundtrip.md docs/benchmarks/m5_2-transport-vs-tuning.md
diff /tmp/m5_2-roundtrip.json docs/benchmarks/m5_2-transport-vs-tuning.json
# Both diffs MUST be empty.
```
