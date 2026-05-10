"""US3 / T039a — schema-candidate CLI flag wiring.

``--schema-candidates=<csv>`` filters which schema candidates run;
``--skip-schema`` skips US3 entirely. Both flags appear in ``--help`` output.
"""

from __future__ import annotations

import io

from vllm_grpc_bench.__main__ import _build_m4_config, _build_parser


class TestSchemaCLIFlags:
    def test_schema_candidates_default(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--m4"])
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        cfg = _build_m4_config(args)
        assert "packed_token_ids" in cfg.schema_candidates
        assert "oneof_flattened_input" in cfg.schema_candidates
        assert "chunk_granularity" in cfg.schema_candidates

    def test_schema_candidates_filtered(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--m4", "--schema-candidates", "packed_token_ids"])
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        cfg = _build_m4_config(args)
        assert cfg.schema_candidates == ("packed_token_ids",)

    def test_skip_schema(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--m4", "--skip-schema"])
        args.m4_pacing = "no_pacing"
        args.m4_shared_baseline = True
        cfg = _build_m4_config(args)
        assert cfg.skip_schema is True

    def test_help_lists_schema_flags(self) -> None:
        parser = _build_parser()
        buffer = io.StringIO()
        parser.print_help(file=buffer)
        text = buffer.getvalue()
        assert "--schema-candidates" in text
        assert "--skip-schema" in text
