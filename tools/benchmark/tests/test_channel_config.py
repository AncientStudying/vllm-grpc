from __future__ import annotations

import grpc
import pytest
from vllm_grpc_bench.channel_config import (
    ALL_PRESETS,
    COMPRESSION_GZIP,
    HTTP2_BDP_PROBE,
    KEEPALIVE_AGGRESSIVE,
    KEEPALIVE_RELAXED,
    M1_BASELINE,
    MAX_MSG_16MIB,
    MAX_MSG_UNLIMITED,
    ChannelConfig,
    preset_by_name,
    presets_for_axis,
)


class TestPresets:
    def test_all_seven_presets_construct(self) -> None:
        # __post_init__ runs on every preset import; if any preset is malformed
        # this module would fail to import. Sanity-check the full set:
        names = {c.name for c in ALL_PRESETS}
        assert names == {
            "m1-baseline",
            "max-msg-16mib",
            "max-msg-unlimited",
            "keepalive-aggressive",
            "keepalive-relaxed",
            "compression-gzip",
            "http2-bdp-probe",
        }

    def test_m1_baseline_is_empty(self) -> None:
        assert M1_BASELINE.server_options == ()
        assert M1_BASELINE.client_options == ()
        assert M1_BASELINE.compression is grpc.Compression.NoCompression

    def test_compression_gzip_carries_compression(self) -> None:
        assert COMPRESSION_GZIP.compression is grpc.Compression.Gzip

    def test_max_msg_16mib_values(self) -> None:
        keys = {k for k, _ in MAX_MSG_16MIB.server_options}
        assert "grpc.max_send_message_length" in keys
        assert "grpc.max_receive_message_length" in keys
        for _, v in MAX_MSG_16MIB.server_options:
            assert v == 16 * 1024 * 1024

    def test_max_msg_unlimited_values(self) -> None:
        for _, v in MAX_MSG_UNLIMITED.server_options:
            assert v == -1

    def test_keepalive_presets_distinct(self) -> None:
        agg = dict(KEEPALIVE_AGGRESSIVE.client_options)
        rel = dict(KEEPALIVE_RELAXED.client_options)
        assert agg["grpc.keepalive_time_ms"] == 10000
        assert rel["grpc.keepalive_time_ms"] == 60000

    def test_http2_bdp_probe_options(self) -> None:
        keys = {k for k, _ in HTTP2_BDP_PROBE.server_options}
        assert "grpc.http2.bdp_probe" in keys
        assert "grpc.http2.lookahead_bytes" in keys


class TestNameValidator:
    def test_rejects_underscore(self) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            ChannelConfig(name="Bad_Name", axis="baseline")

    def test_rejects_leading_dash(self) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            ChannelConfig(name="-leading-dash", axis="baseline")

    def test_rejects_trailing_dash(self) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            ChannelConfig(name="trailing-", axis="baseline")

    def test_accepts_simple_kebab(self) -> None:
        c = ChannelConfig(name="ok-name", axis="baseline")
        assert c.name == "ok-name"


class TestAllowedArgs:
    def test_typo_in_arg_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown grpcio channel arg"):
            ChannelConfig(
                name="typo-test",
                axis="max_message_size",
                server_options=(("grpc.max_messag_size", 100),),
            )

    def test_known_arg_accepted(self) -> None:
        c = ChannelConfig(
            name="known-arg",
            axis="max_message_size",
            server_options=(("grpc.max_send_message_length", 100),),
        )
        assert c.server_options[0][0] == "grpc.max_send_message_length"


class TestLookups:
    def test_preset_by_name_known(self) -> None:
        assert preset_by_name("m1-baseline") is M1_BASELINE

    def test_preset_by_name_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            preset_by_name("does-not-exist")

    def test_presets_for_axis_includes_baseline(self) -> None:
        names = [c.name for c in presets_for_axis("keepalive")]
        assert "m1-baseline" in names
        assert "keepalive-aggressive" in names
        assert "keepalive-relaxed" in names
