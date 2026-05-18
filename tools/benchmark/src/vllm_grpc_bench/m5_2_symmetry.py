"""M5.2 3-tier symmetry helper — re-export shim.

The implementation now lives in :mod:`vllm_grpc_bench.symmetric_prompts`
(relocated as a cross-milestone shared module per M6.1.3 FR-019 + R-6).
This shim preserves the M5.2-era import path so the historical
``--m5_2`` / ``--m5_2-smoke`` re-runnability per M6.1.3 FR-037 holds
without any caller-side change.
"""

from __future__ import annotations

from vllm_grpc_bench.symmetric_prompts import *  # noqa: F401, F403
