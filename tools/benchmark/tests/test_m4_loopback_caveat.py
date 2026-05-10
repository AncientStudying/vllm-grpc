"""US2 / T025 / FR-010 / R-6 — loopback-caveat tagging is deterministic.

For single-host runs, every run tags ``{keepalive, http2_framing} ∩ axes``
with the loopback caveat regardless of observed deltas. Cross-host runs
(out of scope for M4) would clear the caveat.
"""

from __future__ import annotations

from vllm_grpc_bench.m3_types import M4SweepConfig


def _loopback_caveat_for(axes: tuple[str, ...]) -> list[str]:
    cfg = M4SweepConfig(
        axes=axes,
        widths=(4096,) if 4096 not in M4SweepConfig.__dataclass_fields__ else (2048, 4096, 8192),
        schema_canonical_width=4096,
    )
    return sorted(set(axes) & cfg.loopback_caveat_axes)


class TestLoopbackCaveat:
    def test_keepalive_in_axes_attaches_caveat(self) -> None:
        assert "keepalive" in _loopback_caveat_for(("keepalive", "compression"))

    def test_http2_framing_in_axes_attaches_caveat(self) -> None:
        assert "http2_framing" in _loopback_caveat_for(("http2_framing", "compression"))

    def test_compression_only_no_caveat(self) -> None:
        assert _loopback_caveat_for(("compression",)) == []

    def test_max_message_size_only_no_caveat(self) -> None:
        assert _loopback_caveat_for(("max_message_size",)) == []
