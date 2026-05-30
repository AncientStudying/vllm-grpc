"""Chat-prompt construction (v0.0.1 generic home).

Single unified chat-prompt builder for the forward harness. ``build_chat_prompt``
is the seed+digest form (deterministic, per-RPC-varying); the divergent M5.2
``iteration``/``cell_id`` builder is dropped when ``rest_cohort`` is repointed
(Phase 3, FR-003). During the transition this re-exports from the legacy
modules that still define the symbols; the definitions move here when those
modules are deleted (Phase 4).
"""

from __future__ import annotations

from vllm_grpc_bench.m3_sweep import DEFAULT_CHAT_MAX_TOKENS
from vllm_grpc_bench.m6_rpc_driver import _build_chat_prompt as build_chat_prompt

__all__ = ["DEFAULT_CHAT_MAX_TOKENS", "build_chat_prompt"]
