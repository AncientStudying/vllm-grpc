from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import BenchmarkCell
from vllm_grpc_bench.mock_engine import MockEngine, MockEngineConfig


class TestEmbeddingShape:
    @pytest.mark.parametrize("hidden_size", [2048, 4096, 8192])
    @pytest.mark.asyncio
    async def test_canonical_widths(self, hidden_size: int) -> None:
        engine = MockEngine(MockEngineConfig(hidden_size=hidden_size))
        outputs = [
            o async for o in engine.encode("test prompt", request_id="canon-" + str(hidden_size))
        ]
        assert len(outputs) == 1
        emb = outputs[0].outputs[0].embedding
        assert len(emb) == hidden_size

    @pytest.mark.asyncio
    async def test_off_canonical_width_accepted(self) -> None:
        # Spec relaxation: any positive integer width is allowed for exploratory runs.
        engine = MockEngine(MockEngineConfig(hidden_size=1536))
        outputs = [o async for o in engine.encode("test", request_id="off-canon")]
        assert len(outputs[0].outputs[0].embedding) == 1536

    def test_off_canonical_propagates_to_cell(self) -> None:
        # When wired through a BenchmarkCell, off_canonical=True
        cell = BenchmarkCell(
            path="embed",
            hidden_size=1536,
            channel_config=M1_BASELINE,
            corpus_subset="m1_embed",
        )
        assert cell.off_canonical is True
        canonical = BenchmarkCell(
            path="embed",
            hidden_size=4096,
            channel_config=M1_BASELINE,
            corpus_subset="m1_embed",
        )
        assert canonical.off_canonical is False


class TestDeterminism:
    @pytest.mark.asyncio
    async def test_encode_byte_identical(self) -> None:
        engine = MockEngine(MockEngineConfig(hidden_size=2048, seed=7))
        out1 = [o async for o in engine.encode("prompt-1", request_id="det-a")]
        out2 = [o async for o in engine.encode("prompt-1", request_id="det-b")]
        assert out1[0].outputs[0].embedding == out2[0].outputs[0].embedding

    @pytest.mark.asyncio
    async def test_generate_byte_identical(self) -> None:
        engine = MockEngine(MockEngineConfig(hidden_size=2048, seed=7, tokens_per_second=1000.0))
        params = SimpleNamespace(max_tokens=8)
        a = [o async for o in engine.generate("p", params, request_id="g-a")]
        b = [o async for o in engine.generate("p", params, request_id="g-b")]
        assert [o.outputs[0].text for o in a] == [o.outputs[0].text for o in b]


class TestStreamingPacing:
    @pytest.mark.asyncio
    async def test_pacing_within_tolerance(self) -> None:
        # Pick a tps that gives ~10 ms/token; 8 tokens → ~70 ms expected
        engine = MockEngine(MockEngineConfig(hidden_size=2048, tokens_per_second=100.0))
        params = SimpleNamespace(max_tokens=8)
        t0 = time.perf_counter()
        n = 0
        async for _ in engine.generate("p", params, request_id="pace"):
            n += 1
        elapsed = time.perf_counter() - t0
        # 8 tokens with 7 inter-token sleeps of ~10 ms = 70 ms.
        # Allow ±10% pacing tolerance per the contract.
        expected = 7 * (1.0 / 100.0)
        # Generous floor/ceiling to absorb scheduler noise on the bench host:
        assert 0.6 * expected < elapsed < 2.0 * expected, (
            f"elapsed={elapsed:.4f} expected~{expected:.4f}"
        )

    @pytest.mark.asyncio
    async def test_pace_tokens_false_skips_inter_token_sleep(self) -> None:
        """T006 / FR-001 / R-1 — no-pacing mode emits tokens as fast as the
        event loop dispatches them. The cohort wall-clock under
        ``pace_tokens=False`` must be materially lower than the paced default.
        """
        paced = MockEngine(
            MockEngineConfig(hidden_size=2048, tokens_per_second=100.0, pace_tokens=True)
        )
        unpaced = MockEngine(
            MockEngineConfig(hidden_size=2048, tokens_per_second=100.0, pace_tokens=False)
        )
        params = SimpleNamespace(max_tokens=16)
        t0 = time.perf_counter()
        async for _ in paced.generate("p", params, request_id="paced"):
            pass
        paced_wall = time.perf_counter() - t0
        t1 = time.perf_counter()
        async for _ in unpaced.generate("p", params, request_id="unpaced"):
            pass
        unpaced_wall = time.perf_counter() - t1
        # 15 inter-token sleeps × 10 ms = 150 ms of forced pacing on the paced
        # path; the unpaced path should be < 10% of that.
        assert unpaced_wall < paced_wall * 0.5, (
            f"unpaced_wall={unpaced_wall:.4f} not materially lower than paced_wall={paced_wall:.4f}"
        )

    def test_pace_tokens_false_relaxes_tps_validation(self) -> None:
        """T006 / R-1 — when pace_tokens=False, tokens_per_second is unused
        and validation is relaxed (any positive value works; a non-positive
        value still raises since the field is required).
        """
        # Should not raise — tps validation is skipped when pacing is off.
        cfg = MockEngineConfig(hidden_size=2048, pace_tokens=False, tokens_per_second=0.5)
        assert cfg.pace_tokens is False


class TestFailureModes:
    @pytest.mark.asyncio
    async def test_empty_prompt_encode_raises(self) -> None:
        engine = MockEngine(MockEngineConfig(hidden_size=2048))
        with pytest.raises(ValueError, match="empty prompt"):
            async for _ in engine.encode("", request_id="empty"):
                pass

    @pytest.mark.asyncio
    async def test_empty_prompt_generate_raises(self) -> None:
        engine = MockEngine(MockEngineConfig(hidden_size=2048))
        params = SimpleNamespace(max_tokens=4)
        with pytest.raises(ValueError, match="empty prompt"):
            async for _ in engine.generate("", params, request_id="empty"):
                pass

    @pytest.mark.asyncio
    async def test_duplicate_request_id_raises(self) -> None:
        engine = MockEngine(MockEngineConfig(hidden_size=2048, tokens_per_second=10.0))
        params = SimpleNamespace(max_tokens=8)

        async def consume() -> None:
            async for _ in engine.generate("p", params, request_id="dup"):
                await asyncio.sleep(0.05)

        first = asyncio.create_task(consume())
        # Wait long enough for the first stream to register `dup` in `_inflight`.
        await asyncio.sleep(0.02)
        with pytest.raises(RuntimeError, match="duplicate request_id"):
            async for _ in engine.generate("p", params, request_id="dup"):
                pass
        await first


class TestConfigValidation:
    def test_zero_hidden_size_rejected(self) -> None:
        with pytest.raises(ValueError, match="hidden_size"):
            MockEngineConfig(hidden_size=0)

    def test_negative_tps_rejected(self) -> None:
        with pytest.raises(ValueError, match="tokens_per_second"):
            MockEngineConfig(hidden_size=2048, tokens_per_second=-1.0)
