# Contract: `m4-time-axis-tuning.json` schema

This contract defines the M4 report schema as a **strict superset** of M3's `m3-channel-tuning-time.json` schema (per /speckit-clarify Q1 → spec FR-015 → research.md R-7).

> **Compatibility rule**: any reader that successfully parses an `m3-channel-tuning-time.json` file MUST successfully parse an `m4-time-axis-tuning.json` file when M4 fields are ignored. New fields are additive only. No M3 field is renamed, removed, or has its semantics redefined.

## Top-level shape

```jsonc
{
  // ----- M3-shape fields (preserved unchanged) -----
  "mode": "m4-time-axis-tuning",        // M3 used "p1-time-reanalysis"
  "axes": ["max_message_size", "keepalive", "compression", "http2_framing"],
  "widths": [2048, 4096, 8192],
  "paths": ["embed", "chat_stream"],
  "iterations_per_cell": 100,           // the candidate_n default; per-cohort actuals live in cohorts[i].iterations
  "seed": 0,
  "p2_revision": null,                  // M3 left null when no schema sweep ran; M4 keeps null and uses schema_candidate_results below
  "frozen_channel": null,               // M3's pre-existing field; M4 leaves null and populates frozen_channel_baselines instead
  "cohorts": [ /* see per-cohort shape below */ ],

  // ----- M4-only top-level additions (FR-007, FR-009, FR-015, R-7) -----
  "pacing_mode": "no_pacing",                          // "paced" | "no_pacing"
  "shared_baseline_cohort_ids": {
    "embed": "embed|h4096|m1-baseline|m1_embed",      // points into cohorts[]
    "chat_stream": "chat_stream|h4096|m1-baseline|m1_chat"
  },
  "frozen_channel_baselines": {
    "chat_stream": {
      "path": "chat_stream",
      "cohort_id": "chat_stream|h4096|frozen|m4_frozen",
      "channel_config_name": "frozen-chat_stream-h4096",
      "per_axis_winners": {
        "max_message_size": "m1-default",
        "keepalive": "m1-default",
        "compression": "gzip",
        "http2_framing": "m1-default"
      },
      "measured_at_hidden_size": 4096
    },
    "embed": { /* same shape */ }
  },
  "supersedes": [ /* see SupersessionEntry below */ ],
  "candidate_sizing_policy": {
    "default_n": 100,
    "expand_n": 250,
    "expand_rule": "ci_overlap"
  },
  "loopback_caveat_axes": ["keepalive", "http2_framing"],
  "schema_candidate_results": [ /* per-candidate verdict; see below */ ]
}
```

## Per-cohort shape

```jsonc
{
  // ----- M3-shape fields (preserved unchanged) -----
  "cell_id": "chat_stream|h4096|compression|m4_chat",
  "path": "chat_stream",
  "hidden_size": 4096,
  "config_name": "compression=gzip",
  "config_axis": "compression",
  "corpus_subset": "m4_chat",
  "iterations": 100,                     // post-expansion final n if the borderline rule fired
  "n_successful": 100,
  "measurable": true,
  "off_canonical": false,
  "bytes": { "mean": 330.8, "ci_low": 328.5, "ci_high": 333.1 },
  "time_seconds": { "mean": 0.0184, "ci_low": 0.0179, "ci_high": 0.0190 },

  // ----- M4-only per-cohort additions -----
  "is_baseline": false,
  "baseline_role": null,                 // "m1_shared" | "frozen_channel" | null
  "expansion_record": {
    "initial_n": 100,
    "initial_ci_overlapped": false,
    "expanded": false,
    "final_n": 100,
    "expansion_reason": null
  },
  "client_bound": false,
  "time_to_first_token_seconds": {       // null for embed cohorts; first-class for chat_stream (FR-003)
    "mean": 0.00432,
    "ci_low": 0.00418,
    "ci_high": 0.00446
  }
}
```

## SupersessionEntry shape

```jsonc
{
  "m3_cell_id": "chat_stream|h4096|compression|m4_chat",
  "m3_verdict": "noise_bounded",
  "m4_cell_id": "chat_stream|h4096|compression|m4_chat",
  "m4_verdict": "recommend",
  "rationale": "no-pacing exposed 4.2% TTFT reduction under compression at hidden_size 4096"
}
```

## Schema-candidate result shape

```jsonc
{
  "candidate_name": "packed_token_ids",
  "proto_file": "proto/vllm_grpc/v1/m4-candidates/packed_token_ids.proto",
  "measured_widths": [4096],              // 4096-first cascade; widths 2048 and 8192 only if 4096 result is recommend or borderline
  "per_width": [
    {
      "hidden_size": 4096,
      "frozen_baseline_cohort_id": "chat_stream|h4096|frozen|m4_frozen",
      "candidate_cohort_id": "chat_stream|h4096|schema:packed_token_ids|m4_chat",
      "bytes_verdict": "no_winner",
      "time_verdict": "recommend",
      "primary_metric": "time",
      "delta_bytes_pct": 0.1,            // candidate vs. frozen baseline; null if metric unavailable
      "delta_time_pct": -3.8,
      "ci_overlap_initial": false,
      "expanded": false
    }
  ],
  "is_negative_result": false,           // true iff bytes_verdict and time_verdict are both "no_winner" at every measured width
  "notes": null
}
```

## Verdict literal compatibility

The `Verdict` literal set in M4's JSON is `{recommend, no_winner, not_measurable, client_bound}`. Any cohort or candidate where M4 cannot emit a definitive verdict is `not_measurable` (with diagnostic notes), never `noise_bounded`. Readers that handle M3's `noise_bounded` are unaffected — M4 does not produce that value.

## Validation

The harness's `m4_sweep.validate_run(run)` runs all seven invariants from `data-model.md` § "Validation invariants" before writing the JSON. Validation failure is an exit-code-4 condition.
