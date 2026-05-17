# Spike #2 — Cohort reintroduction (`rest_plain_tcp` + cohort discipline)

**Branch**: `spike/m6-1-roadmap-additions`
**Date**: 2026-05-17
**Status**: ✅ Confirmed required. Implementation deferred to **M6.1.2**.

## Why it's confirmed

Item #1's live traceroute proof (see [`01-topology-traceroute-findings.md`](./01-topology-traceroute-findings.md))
showed the M5.x cohorts route through entirely different cloud providers
(`rest_https_edge` → Microsoft Azure; `rest_plain_tcp` + `default_grpc` →
AWS us-west-1 via Telia). That makes the 3-cohort split categorically
load-bearing for cohort comparisons:

| Comparison | Variable isolated |
|---|---|
| `rest_plain_tcp` vs `default_grpc` | **Pure protocol cost** — same CSP, region, path; only HTTP/1.1+REST vs HTTP/2+gRPC changes |
| Either vs `rest_https_edge` | **Multi-cloud routing cost** — same protocol family (more or less), different entry CSP |
| `default_grpc` vs `tuned_grpc_multiplexed` | **Channel-tuning cost** — already validated; preserved |

Without `rest_plain_tcp`, M6.x cells can't separate protocol cost from
CSP-routing cost. M7's corpus expansion and M8's multi-model expansion
will inherit whatever cohort set M6.2 publishes — the user's "continually
supported (or refuted) in data" goal requires the full 3-way split.

## Why not do it now (on this spike)

The implementation is real structural work, not investigation:

- The `rest_plain_tcp` cohort exists in M5.2's code (`m5_2_sweep.py`,
  `m5_2_symmetry.py`, the harness CLI) but was dropped from M6/M6.1/M6.1.1
  during the simplification to a 3-cohort matrix.
- Reintroducing it touches: the sweep cohort iteration, the per-cell
  result schema, the reporter table widths, the cell-key conventions,
  and likely the published-JSON `phase_1_runs[]` shape.
- Whether to keep M5.2's exact cohort definition or evolve it (e.g.,
  symmetry-checked prompts, M6.0a-corrected dispatch semantics applied
  consistently) is a real spec decision — appropriate for the
  ``/speckit-clarify`` cycle, not a spike-time call.

## What M6.1.2 should produce

- 3-cohort split: `rest_https_edge`, `rest_plain_tcp`, `default_grpc`,
  `tuned_grpc_multiplexed` (4 total when c ≥ 2; 3 when c = 1 per the
  existing tuned-pair exclusivity rule). Mirrors M5.2's shape.
- All M6.1.2 / M6.2 / M7 / M8 sweep artifacts carry the full cohort set,
  or document explicitly why a milestone uses a subset.
- ANALYSIS.md updated to reference the multi-CSP finding (correcting the
  "different network path" wording to "different cloud provider for the
  entry edge"). See item #1's findings for the exact phrasing.

## Code-surface hints (read-only enumeration; not a task list)

Sketch from a quick grep — M6.1.2's `/speckit-plan` pass will enumerate
authoritatively:

- `tools/benchmark/src/vllm_grpc_bench/m5_1_grpc_cohort.py` — gRPC cohort
  driver shape (already supports all 3 cohorts via cell `concurrency`).
- `tools/benchmark/src/vllm_grpc_bench/m5_2_sweep.py` — M5.2's 4-5-cohort
  iteration logic, including the tuned-pair / collapsed-tuned exclusivity.
- `tools/benchmark/src/vllm_grpc_bench/m5_2_symmetry.py` — prompt-symmetry
  enforcement so REST + gRPC cohorts see the same logical request.
- `tools/benchmark/src/vllm_grpc_bench/m6_sweep.py`,
  `m6_1_sweep.py`, `m6_1_1_sweep.py` — current 3-cohort iteration that
  needs to grow to 4.
- `scripts/python/modal_bench_rest_grpc_server.py` — already exposes the
  `rest_plain_tcp_url` from `modal.forward(_REST_PORT, unencrypted=True)`
  (line 188-194); the deploy side does not need to change.
- `tools/benchmark/src/vllm_grpc_bench/rest_shim.py` — likely needs the
  plain-TCP REST client path re-exercised; check whether M5.2's wiring
  still compiles or has bit-rotted.

## Disposition

- This spike marks item #2 as decided: **implement in M6.1.2 with the
  3-cohort split + ANALYSIS.md update + per-sweep traceroute probe** (the
  three M6.1.2 deliverables now formally bundle).
- No code change on this spike branch for item #2.
