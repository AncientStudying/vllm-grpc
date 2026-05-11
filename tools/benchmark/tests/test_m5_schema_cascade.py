"""T036 — schema-candidate canonical-first cascade (FR-012).

The cascade widens the measurement set from {canonical_width} to
{2048, 4096, 8192} only when the canonical-width verdict is ``recommend``
or borderline. ``no_winner`` cleanly inside the baseline CI skips the
cascade.
"""

from __future__ import annotations

from vllm_grpc_bench.m5_sweep import schema_widths_to_measure


class TestSchemaCascade:
    """``schema_widths_to_measure`` decides cascade firing."""

    def test_recommend_triggers_cascade(self) -> None:
        widths = schema_widths_to_measure(
            primary_verdict_at_canonical="recommend",
            canonical_width=4096,
            full_widths=(2048, 4096, 8192),
        )
        assert widths == [2048, 4096, 8192]

    def test_borderline_triggers_cascade(self) -> None:
        widths = schema_widths_to_measure(
            primary_verdict_at_canonical="borderline",
            canonical_width=4096,
            full_widths=(2048, 4096, 8192),
        )
        assert widths == [2048, 4096, 8192]

    def test_no_winner_skips_cascade(self) -> None:
        widths = schema_widths_to_measure(
            primary_verdict_at_canonical="no_winner",
            canonical_width=4096,
            full_widths=(2048, 4096, 8192),
        )
        assert widths == [4096]

    def test_not_measurable_skips_cascade(self) -> None:
        widths = schema_widths_to_measure(
            primary_verdict_at_canonical="not_measurable",
            canonical_width=4096,
            full_widths=(2048, 4096, 8192),
        )
        assert widths == [4096]
