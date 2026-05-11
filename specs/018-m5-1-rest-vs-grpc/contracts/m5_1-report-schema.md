# Contract: M5.1 JSON report schema

M5.1's JSON report at `docs/benchmarks/m5_1-rest-vs-grpc.json` is a **strict superset** of M5's `m5-cross-host-validation.json`. Every key M5 emits is present and carries the same semantics; M5.1 adds new keys in new namespaces. M5-aware consumers continue to work unmodified.

## Top-level shape

```jsonc
{
  // === Existing M5 keys (unchanged in M5.1; emitted with empty arrays when
  // the run did not measure channel axes or schema candidates) ===
  "run_id": "<uuid>",
  "run_started_at": "<iso8601>",
  "run_completed_at": "<iso8601>",
  "harness_version_sha": "<git sha>",
  "shared_baseline_cohorts": [ ... ],         // M5 shape; populated in M5.1 with the shared baselines
  "channel_axis_recommendations": [],          // M5 shape; M5.1 emits empty array
  "schema_candidate_recommendations": [],      // M5 shape; M5.1 emits empty array
  "supersedes_m4": [],                         // M5 shape; M5.1 emits empty array
  "supersedes_m3": [],                         // M5 shape; M5.1 emits empty array
  "rtt_distribution": { ... },                 // M5 shape; populated with REST-side AND gRPC-side RTT
  "modal_metadata": { ... },                   // M5 shape; populated with both tunnel URLs (sanitized)

  // === New M5.1-specific top-level keys ===
  "m5_1_matrix": [ ... ],                      // list[M5_1Cell]; the 18-cell head-to-head matrix
  "supersedes_m1_time": [ ... ],               // list[SupersedesM1Entry]; per-(path, c) supersession
  "rest_shim_meta": {                          // ShimOverheadRecord + FastAPI shim provenance
    "shim_version_sha": "<git sha>",
    "uvicorn_workers": 1,
    "shim_overhead_ms_median_across_run": 0.42,
    "shim_overhead_ms_p95_across_run": 1.05,
    "shim_overhead_ms_max_across_run": 4.7,
    "shim_overhead_material_in_any_cohort": false
  },
  "auth_token_env_var": "MODAL_BENCH_TOKEN",   // name only; token value never present

  // === Existing M5 `cohorts[]` array, extended with M5.1 fields on each cohort ===
  "cohorts": [
    {
      // === Existing M5 cohort keys (unchanged) ===
      "key": "rest:chat_stream:h2048:c4",
      "sample_size": 100,
      "median_ms": 248.3,
      "ci_lo_ms": 240.1,
      "ci_hi_ms": 256.5,
      "cv": 0.041,
      "server_bound": false,
      "client_bound": false,
      "low_rtt_caveat": false,
      "rtt_ms_median": 52.3,
      "rtt_ms_p95": 58.1,
      "discarded": false,

      // === New M5.1 cohort fields (additive) ===
      "protocol": "rest",                                // "rest" | "grpc"
      "grpc_channel_model": null,                        // null for REST; one of GRPCSubCohortKind for gRPC
      "connection_count": 4,                             // actually-opened connections
      "shim_overhead_ms": 0.38,                          // REST only; null for gRPC
      "comparison_cell_key": "chat_stream:h2048:c4",     // groups cohorts back to M5_1Cell
      "rest_cohort_record": {                            // null for gRPC; full RESTCohortRecord for REST
        "shim_overhead_ms_median": 0.38,
        "shim_overhead_ms_p95": 0.92,
        "connections_opened": 4,
        "connections_keepalive_reused": 96,              // 100 requests - 4 initial connects
        "request_bytes_median": 312,
        "request_bytes_p95": 312,
        "response_bytes_median": 1842,
        "response_bytes_p95": 1894
      }
    },
    // ... 65 more cohort entries (~70 total: REST + tuned-gRPC sub-cohorts + default-gRPC + warmups)
  ]
}
```

## `M5_1Cell` shape (entries in `m5_1_matrix[*]`)

```jsonc
{
  "path": "chat_stream",                       // "chat_stream" | "embed"
  "hidden_size": 2048,                         // 2048 | 4096 | 8192
  "concurrency": 4,                            // 1 | 4 | 8
  "comparison_cell_key": "chat_stream:h2048:c4",

  // Cohort references (CohortResult.key)
  "rest_cohort_key": "rest:chat_stream:h2048:c4",
  "tuned_grpc_multiplexed_cohort_key": "grpc-tuned-mux:chat_stream:h2048:c4",
  "tuned_grpc_channels_cohort_key": "grpc-tuned-ch:chat_stream:h2048:c4",  // null at c=1
  "default_grpc_cohort_key": "grpc-default:chat_stream:h2048:c4",

  // Verdicts (list of CellVerdict)
  // At c >= 2: 3 entries (tuned-mux × REST, tuned-channels × REST, default-grpc × REST)
  // At c == 1: 2 entries (tuned × REST, default × REST)
  "verdicts": [
    {
      "grpc_sub_cohort": "tuned_grpc_multiplexed",
      "verdict": "tuned_grpc_multiplexed_recommend",
      "delta_pct": -18.4,                      // signed: negative = gRPC faster
      "ci_pct": [-22.1, -14.7],                // 95% CI on delta_pct
      "metric": "ttft"                         // "ttft" | "wallclock"
    },
    {
      "grpc_sub_cohort": "tuned_grpc_channels",
      "verdict": "no_winner",
      "delta_pct": -2.1,
      "ci_pct": [-5.4, 1.2],
      "metric": "ttft"
    },
    {
      "grpc_sub_cohort": "default_grpc",
      // When default_grpc wins, the literal is `default_grpc_recommend`
      // (not the tuned-multiplexed label). One literal per sub-cohort kind.
      "verdict": "default_grpc_recommend",
      "delta_pct": -8.7,
      "ci_pct": [-13.3, -4.1],
      "metric": "ttft"
    }
  ],

  // FR-005 / Edge Case 3
  "comparison_unavailable": false,
  "comparison_unavailable_reason": null,

  // RTT (FR-004, SC-003); computed across all cohorts at this cell
  "rtt_ms_median": 52.3,
  "rtt_ms_p95": 58.1,
  "low_rtt_caveat": false
}
```

## `SupersedesM1Entry` shape (entries in `supersedes_m1_time[*]`)

```jsonc
{
  "m1_path": "chat_completion",
  "m1_concurrency": 1,
  "m1_verdict_literal": "REST faster (c=1 small-body chat)",
  "m1_source_report": "docs/benchmarks/phase-3-modal-comparison.md#chat-c1",

  // M5.1's verdict pattern across widths at this (path, c)
  "m5_1_verdict_per_width": {
    "2048": "tuned_grpc_multiplexed_recommend",
    "4096": "tuned_grpc_multiplexed_recommend",
    "8192": "no_winner"
  },
  "m5_1_supporting_delta_pct": {
    "2048": -23.2,
    "4096": -19.8,
    "8192": -1.1
  },
  "m5_1_supporting_ci_pct": {
    "2048": [-25.1, -21.3],
    "4096": [-22.0, -17.6],
    "8192": [-4.8, 2.6]
  },

  "classification": "verdict_changed",         // "verdict_confirmed" | "verdict_changed" | "mixed"
  "comparison_basis": "m1_real_vllm_vs_m5_1_mock_engine",
  "rationale": "On real wire (52 ms RTT median), tuned-gRPC's HTTP/2 multiplexing reduces chat_stream TTFT 19-23% at h2048-h4096; M1's REST-wins-at-c=1 result was a loopback-era artifact of channel-setup overhead dominating a sub-millisecond payload. The h8192 cell remains no_winner because MockEngine's neutral inference cost limits the wire-component contribution; M7's real-vLLM re-validation will confirm whether the h8192 row holds under real inference cost."
}
```

## Additive-only rule (FR-014)

Every existing M5 key is present unchanged. No M5 key is renamed, removed, or semantically redefined. New keys live in new top-level namespaces (`m5_1_matrix`, `supersedes_m1_time`, `rest_shim_meta`) or on additive cohort fields (`protocol`, `grpc_channel_model`, `connection_count`, `shim_overhead_ms`, `comparison_cell_key`, `rest_cohort_record`).

An M5-only consumer (e.g., an external script that reads `m5-cross-host-validation.json`) MUST be able to read `m5_1-rest-vs-grpc.json` without modification, ignoring keys it does not recognize.

## Validation

`reporter.write_m5_1_report` MUST validate the emitted JSON against:
1. Every M5 key from the M5 schema is present (use `m5-cross-host-validation.json`'s schema as a structural reference).
2. Every M5.1 top-level key (`m5_1_matrix`, `supersedes_m1_time`, `rest_shim_meta`, `auth_token_env_var`) is present.
3. Cohort count = 18 (REST) + tuned-gRPC count + 18 (default-gRPC) + warmups, where tuned-gRPC count = 6 (c=1 cells) + 24 (c≥2 cells, dual sub-cohort) = 30.
4. Every cohort has a `comparison_cell_key` that resolves to an entry in `m5_1_matrix[*]`.
5. Every `m5_1_matrix` entry has `len(verdicts) == (3 if concurrency >= 2 else 2)` unless `comparison_unavailable: true`.
6. No token value is present anywhere in the JSON (regex check for `Bearer ` or anything resembling a 32-character URL-safe token).

Validation failure → exit code 8.
