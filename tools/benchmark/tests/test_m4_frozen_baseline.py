"""US2 / T026 / FR-011 / R-3 — per-path frozen-channel baseline composition.

For each path the cohort combines that path's per-axis winners at
``schema_canonical_width=4096``. Absent a winner on an axis, the frozen
baseline keeps that axis at the M3 default.
"""

from __future__ import annotations

from vllm_grpc_bench.channel_config import (
    COMPRESSION_GZIP,
    M1_BASELINE,
    MAX_MSG_16MIB,
)
from vllm_grpc_bench.m4_sweep import _compose_channel_config


class TestFrozenComposition:
    def test_no_winners_keeps_m1_default(self) -> None:
        composed = _compose_channel_config(
            name="frozen-embed-h4096",
            per_axis_winners={
                "max_message_size": "m1-default",
                "compression": "m1-default",
                "keepalive": "m1-default",
                "http2_framing": "m1-default",
            },
        )
        assert composed.server_options == ()
        assert composed.client_options == ()
        assert composed.compression == M1_BASELINE.compression

    def test_winners_unioned(self) -> None:
        composed = _compose_channel_config(
            name="frozen-embed-h4096",
            per_axis_winners={
                "max_message_size": MAX_MSG_16MIB.name,
                "compression": COMPRESSION_GZIP.name,
            },
        )
        # Both axes' option keys present on the merged config.
        keys = {opt[0] for opt in composed.server_options}
        assert "grpc.max_send_message_length" in keys
        assert "grpc.max_receive_message_length" in keys
        # Compression flips to gzip via the compression-axis winner.
        assert composed.compression == COMPRESSION_GZIP.compression

    def test_unknown_winner_falls_through(self) -> None:
        composed = _compose_channel_config(
            name="frozen-embed-h4096",
            per_axis_winners={"max_message_size": "no-such-preset"},
        )
        assert composed.server_options == ()
        assert composed.client_options == ()
