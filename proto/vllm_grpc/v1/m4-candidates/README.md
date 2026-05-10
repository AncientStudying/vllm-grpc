# M4 Schema Candidates

This namespace holds **isolated** candidate `.proto` files measured by
`tools/benchmark/src/vllm_grpc_bench/m4_sweep.py` against the per-path
frozen-channel baselines built in US2.

These files are **not** wired into production proxy / frontend / client code.
Production proto remains `proto/vllm_grpc/v1/{chat,completions}.proto`.

Adoption of any winning candidate is a separate change tracked in a follow-up
PR — see `docs/PLAN.md` and the M4 spec under
`specs/016-m4-time-axis-tuning/spec.md` § Assumptions.

## Files

- `packed_token_ids.proto` — Candidate (a): packed scalars on chat token-ids.
- `oneof_flattened_input.proto` — Candidate (b): flatten the input union.
- `chunk_granularity.proto` — Candidate (c): coarser streaming chunk granularity.

`make proto` regenerates Python stubs into
`packages/gen/src/vllm_grpc_m4_candidates/<candidate>/`.
