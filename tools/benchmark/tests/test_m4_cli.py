"""US1 / contract m4-bench-cli.md — CLI flag wiring + exit codes.

Covers:
- Default flag values (no-pacing, shared-baseline, baseline_n=100, etc.)
- Mutual exclusion: --no-pacing vs --paced; --shared-baseline vs --per-axis-baseline
- Arithmetic: --candidate-n must be < --expand-n (exit 2)
- Floor: --baseline-n >= 100 (exit 2)
- Build a M4SweepConfig from a parsed Namespace.
"""

from __future__ import annotations

import argparse

import pytest
from vllm_grpc_bench.__main__ import _build_m4_config, _build_parser
from vllm_grpc_bench.m3_types import M4SweepConfig


class TestArgParser:
    def test_defaults_when_only_m4_set(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--m4"])
        assert args.m4 is True
        assert args.m4_pacing is None  # filled in by _run_m4
        assert args.m4_shared_baseline is None
        assert args.baseline_n == 100
        assert args.candidate_n == 100
        assert args.expand_n == 250
        assert args.baseline_cv_max == 0.05
        assert args.widths == "2048,4096,8192"
        assert args.paths == "embed,chat_stream"
        assert args.axes == "max_message_size,keepalive,compression,http2_framing"
        assert args.skip_schema is False

    def test_pacing_mutually_exclusive(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--m4", "--no-pacing", "--paced"])

    def test_baseline_mutually_exclusive(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--m4", "--shared-baseline", "--per-axis-baseline"])

    def test_no_pacing_alias(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--m4", "--no-pacing"])
        assert args.m4_pacing == "no_pacing"

    def test_paced_alias(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--m4", "--paced"])
        assert args.m4_pacing == "paced"


class TestM4ConfigFromArgs:
    def _parse(self, *argv: str) -> argparse.Namespace:
        return _build_parser().parse_args(["--m4", *argv])

    def test_defaults_build_config(self) -> None:
        args = self._parse()
        # Fill the defaults the CLI dispatcher applies.
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        cfg = _build_m4_config(args)
        assert isinstance(cfg, M4SweepConfig)
        assert cfg.pacing_mode == "no_pacing"
        assert cfg.shared_baseline is True
        assert cfg.widths == (2048, 4096, 8192)
        assert cfg.paths == ("embed", "chat_stream")
        assert "compression" in cfg.axes
        assert cfg.schema_canonical_width == 4096

    def test_widths_parsed(self) -> None:
        args = self._parse("--widths", "4096")
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        cfg = _build_m4_config(args)
        assert cfg.widths == (4096,)
        assert cfg.schema_canonical_width == 4096

    def test_skip_schema(self) -> None:
        args = self._parse("--skip-schema")
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        cfg = _build_m4_config(args)
        assert cfg.skip_schema is True

    def test_arithmetic_violation_rejected_at_dataclass(self) -> None:
        args = self._parse("--candidate-n", "300", "--expand-n", "300")
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        with pytest.raises(ValueError, match="expand_n must be > candidate_n"):
            _build_m4_config(args)

    def test_baseline_n_floor_at_dataclass(self) -> None:
        args = self._parse("--baseline-n", "50")
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        with pytest.raises(ValueError, match="baseline_n"):
            _build_m4_config(args)
