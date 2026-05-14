# Contract: M5.2 JSON Report Schema (Strict Superset of M5.1)

The M5.2 aggregate JSON at `docs/benchmarks/m5_2-transport-vs-tuning.json` is a strict superset of M5.1's schema (`docs/benchmarks/m5_1-rest-vs-grpc.json`). Every key M5.1 emitted is still present and carries M5.1-compatible semantics; M5.2-specific keys live in new namespaces or are appended to existing arrays. M5.1-aware tooling continues to read the JSON without modification (per FR-013).

This contract pins the **JSON wire shape**; the Python dataclasses backing each shape are documented in `data-model.md`.

## Top-level keys (additive to M5.1)

| Key | Type | Source | Notes |
|-----|------|--------|-------|
| `m5_2_run` | object | `M5_2Run` dataclass (data-model.md) | Top-level container for M5.2's run. M5.1-aware consumers ignore this key. |
| `symmetry` | object | `SymmetryBlock` dataclass | 3-tier symmetry block per FR-005b. Top-level for grep convenience. |
| `events_sidecar_path` | string | string | Repo-relative path to the gzipped sidecar. |
| `events_sidecar_sha256` | string (hex) | string | SHA-256 hex digest of the gzipped sidecar. The regenerator verifies this before computing aggregates per FR-012b. |
| `protocol_comparison_verdicts` | array of object | `list[ProtocolComparisonRow]` | One row per (cell × gRPC cohort) per FR-009. |
| `transport_only_verdicts` | array of object | `list[TransportOnlyRow]` | One row per cell per FR-009. |
| `supersedes_m5_1` | array of object | `list[SupersedesM5_1Entry]` | Supersedes-M5.1 table per FR-016. |
| `payload_parity_audit` | object | — | `{no_regression_confirmed_against_pr: string, measured_payload_bytes: {chat_rest_https_edge: int, chat_rest_plain_tcp: int, chat_grpc: int, embed_rest_https_edge: int, embed_rest_plain_tcp: int, embed_grpc: int}}` per FR-005c. |
| `smoke_run_outcome` | object | — | `{iso: string, asserted_clauses_count: int, per_cohort_rtt_probe_medians_ms: {cohort: float}}` per FR-005a / SC-012. |
| `https_edge_vs_plain_tcp_rtt_delta_median_ms` | float | float | Computed at report-build time; surfaces in executive section per FR-014. |
| `https_edge_vs_plain_tcp_rtt_delta_p95_ms` | float | float | Computed at report-build time. |
| `modal_region` | string | string | e.g., `"eu-west-1"`. |
| `modal_instance_class` | string | string | e.g., `"cpu-only"` or specific Modal class. |
| `https_edge_endpoint` | string | string | The HTTPS-edge URL the rest_https_edge cohort used. |
| `client_external_geolocation` | object \| null | — | `{country: string, region: string}` or `null` if the lookup was skipped or failed. |
| `failed_cells` | array of object, OPTIONAL | `M5_2Run.failed_cells` (post-impl R-13) | Per-cell crash log persisted to the RUN CONFIG JSON (`{run_id}.run_config.json`), NOT to the aggregate report JSON. Each entry: `{path, hidden_size, concurrency, exception_type, exception_repr, traceback}`. Empty on clean runs; non-empty when the sweep's per-cell try/except caught a failure. The aggregate report JSON MAY include this key (currently the regenerator does not emit it), or readers can consult the run config directly. The negative-results appendix in the markdown SHOULD eventually surface failed cells explicitly; today they appear as missing rows. |

## `symmetry` block detail

```json
{
  "symmetry": {
    "tier_a": {
      "prompt_corpus_hash": "<sha256 hex>",
      "modal_deploy_handle": "vllm-grpc-bench-rest-grpc-mock-<run_id>",
      "mock_engine_config_digest": "<sha256 hex>",
      "warmup_batch_policy": "discard_first_5_measurement_n_5"
    },
    "tier_b": {
      "rest_client_config_digest_url_excepted": "<sha256 hex>",
      "tuned_grpc_channel_config_digest_topology_excepted": "<sha256 hex>"
    },
    "tier_c": [
      {
        "cohort": "rest_https_edge",
        "client_config_digest_full": "<sha256 hex>",
        "modal_app_handle": "<...>",
        "modal_region": "eu-west-1",
        "warmup_batch_size": 20,
        "tier_b_skipped_c1_tuned_grpc_pair": false
      },
      "..."
    ],
    "client_external_geolocation_country": "US",
    "client_external_geolocation_region": "US-CA"
  }
}
```

The `tier_b.tuned_grpc_channel_config_digest_topology_excepted` field is set to `null` when the run is exclusively at c=1 (degenerate tuned_grpc pair); the asserter records `tier_b_skipped_c1_tuned_grpc_pair: true` in each tier_c entry for the c=1 cohort.

## `protocol_comparison_verdicts` row detail

```json
{
  "path": "chat_stream",
  "hidden_size": 4096,
  "concurrency": 4,
  "grpc_cohort": "tuned_grpc_multiplexed",
  "rest_cohort": "rest_https_edge",
  "verdict": "tuned_grpc_multiplexed_recommend",
  "comparison_unavailable_reason": null,
  "delta_median_ms": -6.8,
  "ci_lower_ms": -8.2,
  "ci_upper_ms": -5.4,
  "grpc_cohort_network_path": "plain_tcp",
  "rest_cohort_network_path": "https_edge"
}
```

`verdict` literals: see `data-model.md::ProtocolComparisonVerdict`. `delta_median_ms` is signed: negative means the gRPC cohort wins on the time metric; positive means the REST cohort wins.

## `transport_only_verdicts` row detail

```json
{
  "path": "embed",
  "hidden_size": 8192,
  "concurrency": 8,
  "verdict": "rest_plain_tcp_recommend",
  "comparison_unavailable_reason": null,
  "delta_median_ms": 12.3,
  "ci_lower_ms": 10.1,
  "ci_upper_ms": 14.7
}
```

`verdict` literals: see `data-model.md::TransportOnlyVerdict`. `delta_median_ms` is signed: positive means `rest_https_edge` is slower than `rest_plain_tcp` (i.e., the HTTPS-edge has a measurable transport cost on this cell).

## `supersedes_m5_1` row detail

```json
{
  "path": "chat_stream",
  "hidden_size": 2048,
  "concurrency": 4,
  "grpc_cohort": "default_grpc",
  "m5_1_verdict": "no_winner",
  "m5_2_verdict": "default_grpc_recommend",
  "m5_2_delta_median_ms": -6.2,
  "m5_2_ci_lower_ms": -8.3,
  "m5_2_ci_upper_ms": -4.1,
  "category": "noise_resolved",
  "rationale": "M5.2 resolves M5.1's no_winner with default_grpc winning by 6.2 ms (CI [4.1, 8.3]) at n=250."
}
```

`category` literals: see `data-model.md::SupersedesM5_1Category`. The `rationale` field is a one-line free-text summary the report renders verbatim in the Supersedes-M5.1 table.

## Forward-compatibility rules

1. **Additive only.** M5.2 MUST NOT rename or remove any M5.1 key. The M5.1 keys (`m5_1_matrix`, `supersedes_m1_time`, M5-era `m5_matrix`, etc.) are present in the M5.2 JSON, emitted with empty arrays when the M5.2 mode is active (matches M5.1's "keep M5 keys with empty arrays" convention from M5.1 R-6).
2. **No semantic redefinition.** Existing keys carry the same meaning. M5.2 introduces new literals (e.g., `rest_https_edge_recommend`) by adding them to the Literal union; M5.1 verdicts (e.g., `rest_recommend`) continue to be valid in the M5.1 portion of the schema.
3. **No timestamp coupling.** Every timestamp the JSON emits is derived from the events sidecar or from the run config's `run_started_at_iso`. The regenerator produces byte-identical JSON on equivalent sidecar + config inputs (per R-5).
4. **Deterministic encoding.** The regenerator uses `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` so the file is byte-stable across regenerator invocations on the same inputs.

## Regenerator validation rule

The regenerator (per `contracts/m5_2-regenerator.md`) verifies the produced JSON against this schema by:
1. Parsing the JSON.
2. Asserting all top-level keys listed above are present (additive keys are required when in M5.2 mode).
3. Asserting `events_sidecar_sha256` equals the SHA-256 hex of the gzipped sidecar at `events_sidecar_path`.
4. Asserting `symmetry.tier_a` field set is exactly `{prompt_corpus_hash, modal_deploy_handle, mock_engine_config_digest, warmup_batch_policy}`.
5. Asserting every `protocol_comparison_verdicts` row's `verdict` is one of the `ProtocolComparisonVerdict` literals; similarly for `transport_only_verdicts` and `supersedes_m5_1`.

Validation failures raise `M5_2SchemaValidationFailed` with the offending key + observed value; the regenerator refuses to write the markdown alongside.
