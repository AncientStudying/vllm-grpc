"""Harness-wide exceptions (v0.0.1 generic home).

During the v0.0.1 refactor this re-exports the schema-validation error from the
legacy module that still defines it; the definition moves here when that module
is deleted (Phase 4). See ``specs/029-post-m6.2-cleanup-v0.0.1/``.
"""

from __future__ import annotations

from vllm_grpc_bench.m5_2_regen import M5_2SchemaValidationFailed as SchemaValidationFailed

__all__ = ["SchemaValidationFailed"]
