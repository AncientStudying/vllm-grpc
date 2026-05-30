"""Timing extraction/segmentation helpers (v0.0.1 generic home).

De-prefixed surface of the former ``m6_1_1_timing`` module. During the v0.0.1
refactor this re-exports the live timing API from the legacy modules that still
define it; the definitions move here when those modules are deleted (Phase 4).
"""

from __future__ import annotations

from vllm_grpc_bench.m6_1_1_timing import (
    compute_per_segment_delta,
    extract_grpc_timings,
    extract_rest_timings,
    timing_checkpoint_to_payload,
)
from vllm_grpc_bench.m6_1_1_types import PerSegmentDelta, TimingCheckpoint

__all__ = [
    "PerSegmentDelta",
    "TimingCheckpoint",
    "compute_per_segment_delta",
    "extract_grpc_timings",
    "extract_rest_timings",
    "timing_checkpoint_to_payload",
]
