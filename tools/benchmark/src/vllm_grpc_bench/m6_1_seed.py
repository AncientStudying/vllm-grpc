"""M6.1 per-RPC deterministic seed mapping + ``torch.Generator`` factory.

Per spec FR-019 / FR-028 and research R-3: every measurement RPC's
``SamplingParams.seed`` is computed as ``base_seed + rpc_index`` (warmup RPCs
have no seed and do not advance the counter), and the prompt-embeds tensor's
*values* are drawn deterministically from a per-RPC ``torch.Generator``
seeded with the same scalar so the wire bytes are bit-reproducible across
re-runs (SC-006).

Cell shape (``[seq_len, hidden_size=4096] fp16``) is pinned at sweep start
by :mod:`vllm_grpc_bench.m6_1_seq_len`; only the values vary per RPC.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import torch

DEFAULT_M6_1_BASE_SEED: int = 42


def compute_rpc_seed(rpc_index: int, base_seed: int = DEFAULT_M6_1_BASE_SEED) -> int:
    """Return the per-RPC seed scalar for measurement RPC ``rpc_index``.

    ``rpc_index`` MUST be a non-negative integer (warmup RPCs do not advance
    the counter per FR-019 / FR-015).
    """
    if rpc_index < 0:
        raise ValueError(f"rpc_index must be >= 0, got {rpc_index}")
    return base_seed + rpc_index


def build_torch_generator_for_rpc(
    rpc_index: int,
    base_seed: int = DEFAULT_M6_1_BASE_SEED,
    device: str = "cpu",
) -> torch.Generator:
    """Build a ``torch.Generator`` seeded for the given measurement RPC.

    Two generators built for the same ``rpc_index`` produce bit-identical
    output sequences under ``torch.randn(...)`` (FR-028 / SC-006).
    """
    import torch  # local import — keeps non-M6.1 callers torch-free

    if rpc_index < 0:
        raise ValueError(f"rpc_index must be >= 0, got {rpc_index}")
    g = torch.Generator(device=device)
    g.manual_seed(base_seed + rpc_index)
    return g


__all__ = [
    "DEFAULT_M6_1_BASE_SEED",
    "build_torch_generator_for_rpc",
    "compute_rpc_seed",
]
