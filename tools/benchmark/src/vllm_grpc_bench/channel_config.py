"""Named bundles of grpcio channel options for the M3 sweep.

A ``ChannelConfig`` is applied symmetrically to ``grpc.aio.server(options=...)``
on the frontend and ``grpc.aio.insecure_channel(target, options=...)`` on the
proxy + direct client. The seven module-level presets cover the four P1 axes
plus the M1 baseline.

The ``_ALLOWED_ARGS`` allowlist rejects typo'd grpcio arg names — grpcio
silently ignores unknown args, which would mask configuration bugs in the
report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import grpc

ChannelOption = tuple[str, int | str]
ChannelOptions = tuple[ChannelOption, ...]

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]+[a-z0-9]$")

_ALLOWED_ARGS: frozenset[str] = frozenset(
    {
        # Message size limits
        "grpc.max_send_message_length",
        "grpc.max_receive_message_length",
        # Keepalive
        "grpc.keepalive_time_ms",
        "grpc.keepalive_timeout_ms",
        "grpc.keepalive_permit_without_calls",
        "grpc.http2.max_pings_without_data",
        "grpc.http2.min_time_between_pings_ms",
        "grpc.http2.min_ping_interval_without_data_ms",
        # HTTP/2 framing / flow control
        "grpc.http2.bdp_probe",
        "grpc.http2.lookahead_bytes",
        "grpc.http2.max_frame_size",
        # Compression (channel-default; per-call also possible)
        "grpc.default_compression_algorithm",
        "grpc.default_compression_level",
    }
)

Axis = Literal[
    "max_message_size",
    "keepalive",
    "compression",
    "http2_framing",
    "baseline",
    "schema",
]


def _validate_options(options: ChannelOptions) -> None:
    for k, _ in options:
        if k not in _ALLOWED_ARGS:
            raise ValueError(
                f"unknown grpcio channel arg {k!r}; add it to _ALLOWED_ARGS if intentional"
            )


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    axis: Axis
    server_options: ChannelOptions = field(default_factory=tuple)
    client_options: ChannelOptions = field(default_factory=tuple)
    compression: grpc.Compression = grpc.Compression.NoCompression
    description: str = ""

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(f"ChannelConfig.name {self.name!r} must be kebab-case")
        _validate_options(self.server_options)
        _validate_options(self.client_options)


M1_BASELINE = ChannelConfig(
    name="m1-baseline",
    axis="baseline",
    description="No explicit channel options; matches M1 wire shape exactly.",
)

MAX_MSG_16MIB = ChannelConfig(
    name="max-msg-16mib",
    axis="max_message_size",
    server_options=(
        ("grpc.max_send_message_length", 16 * 1024 * 1024),
        ("grpc.max_receive_message_length", 16 * 1024 * 1024),
    ),
    client_options=(
        ("grpc.max_send_message_length", 16 * 1024 * 1024),
        ("grpc.max_receive_message_length", 16 * 1024 * 1024),
    ),
    description="16 MiB on each side; clears hidden_size=8192 float32 embeds with margin.",
)

MAX_MSG_UNLIMITED = ChannelConfig(
    name="max-msg-unlimited",
    axis="max_message_size",
    server_options=(
        ("grpc.max_send_message_length", -1),
        ("grpc.max_receive_message_length", -1),
    ),
    client_options=(
        ("grpc.max_send_message_length", -1),
        ("grpc.max_receive_message_length", -1),
    ),
    description="Both sides unlimited (-1); used to confirm bind/no-bind boundary cleanly.",
)

KEEPALIVE_AGGRESSIVE = ChannelConfig(
    name="keepalive-aggressive",
    axis="keepalive",
    server_options=(
        ("grpc.keepalive_time_ms", 10000),
        ("grpc.keepalive_timeout_ms", 5000),
        ("grpc.keepalive_permit_without_calls", 1),
        # Server must accept the ping rate or it sends GOAWAY.
        ("grpc.http2.min_time_between_pings_ms", 5000),
        ("grpc.http2.min_ping_interval_without_data_ms", 5000),
    ),
    client_options=(
        ("grpc.keepalive_time_ms", 10000),
        ("grpc.keepalive_timeout_ms", 5000),
        ("grpc.keepalive_permit_without_calls", 1),
    ),
    description="10s keepalive ping interval; surfaces GOAWAY storms on unconfigured servers.",
)

KEEPALIVE_RELAXED = ChannelConfig(
    name="keepalive-relaxed",
    axis="keepalive",
    server_options=(
        ("grpc.keepalive_time_ms", 60000),
        ("grpc.keepalive_timeout_ms", 20000),
    ),
    client_options=(
        ("grpc.keepalive_time_ms", 60000),
        ("grpc.keepalive_timeout_ms", 20000),
    ),
    description="60s keepalive ping interval; closer to typical production tuning.",
)

COMPRESSION_GZIP = ChannelConfig(
    name="compression-gzip",
    axis="compression",
    compression=grpc.Compression.Gzip,
    description="Gzip channel-level compression; expected to enlarge dense float embeds.",
)

HTTP2_BDP_PROBE = ChannelConfig(
    name="http2-bdp-probe",
    axis="http2_framing",
    server_options=(
        ("grpc.http2.bdp_probe", 1),
        ("grpc.http2.lookahead_bytes", 16384),
    ),
    client_options=(
        ("grpc.http2.bdp_probe", 1),
        ("grpc.http2.lookahead_bytes", 16384),
    ),
    description="Adaptive HTTP/2 flow-control window via BDP probing.",
)


ALL_PRESETS: tuple[ChannelConfig, ...] = (
    M1_BASELINE,
    MAX_MSG_16MIB,
    MAX_MSG_UNLIMITED,
    KEEPALIVE_AGGRESSIVE,
    KEEPALIVE_RELAXED,
    COMPRESSION_GZIP,
    HTTP2_BDP_PROBE,
)


def preset_by_name(name: str) -> ChannelConfig:
    for cfg in ALL_PRESETS:
        if cfg.name == name:
            return cfg
    raise KeyError(f"no ChannelConfig preset named {name!r}")


def presets_for_axis(axis: Axis) -> tuple[ChannelConfig, ...]:
    """Return baseline + every candidate preset on the given axis."""
    return (M1_BASELINE,) + tuple(c for c in ALL_PRESETS if c.axis == axis)
