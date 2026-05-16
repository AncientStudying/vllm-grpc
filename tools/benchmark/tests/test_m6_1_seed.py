"""Tests for ``m6_1_seed`` — per-RPC seed mapping + ``torch.Generator`` factory."""

from __future__ import annotations

import pytest
import torch
from vllm_grpc_bench import m6_1_seed


def test_compute_rpc_seed_default_base() -> None:
    assert m6_1_seed.compute_rpc_seed(0) == 42
    assert m6_1_seed.compute_rpc_seed(0, base_seed=42) == 42
    assert m6_1_seed.compute_rpc_seed(99, base_seed=42) == 141


def test_compute_rpc_seed_rejects_negative() -> None:
    with pytest.raises(ValueError):
        m6_1_seed.compute_rpc_seed(-1)


def test_torch_generator_bit_reproducible_same_rpc() -> None:
    g1 = m6_1_seed.build_torch_generator_for_rpc(7, base_seed=42)
    g2 = m6_1_seed.build_torch_generator_for_rpc(7, base_seed=42)
    shape = (8, 4096)
    t1 = torch.randn(shape, dtype=torch.float16, generator=g1)
    t2 = torch.randn(shape, dtype=torch.float16, generator=g2)
    assert torch.equal(t1, t2)


def test_torch_generator_differs_across_rpcs() -> None:
    g1 = m6_1_seed.build_torch_generator_for_rpc(0)
    g2 = m6_1_seed.build_torch_generator_for_rpc(1)
    shape = (8, 4096)
    t1 = torch.randn(shape, dtype=torch.float16, generator=g1)
    t2 = torch.randn(shape, dtype=torch.float16, generator=g2)
    assert not torch.equal(t1, t2)


def test_torch_generator_rejects_negative() -> None:
    with pytest.raises(ValueError):
        m6_1_seed.build_torch_generator_for_rpc(-1)
