"""US3 / T037 / FR-013 — schema-candidate cascade rule.

At hidden_size 4096:
- A ``recommend`` candidate triggers re-measurement at 2048 + 8192.
- An overlapping-CI ``no_winner`` candidate does **not** cascade.
The cascade decision is recorded in the per-candidate result.
"""

from __future__ import annotations

from vllm_grpc_bench.m4_sweep import schema_widths_to_measure


class TestSchemaCascade:
    def test_recommend_cascades(self) -> None:
        widths = schema_widths_to_measure(
            primary_verdict_at_canonical="recommend",
            canonical_width=4096,
            full_widths=(2048, 4096, 8192),
        )
        assert sorted(widths) == [2048, 4096, 8192]

    def test_borderline_cascades(self) -> None:
        widths = schema_widths_to_measure(
            primary_verdict_at_canonical="borderline",
            canonical_width=4096,
            full_widths=(2048, 4096, 8192),
        )
        assert sorted(widths) == [2048, 4096, 8192]

    def test_no_winner_does_not_cascade(self) -> None:
        widths = schema_widths_to_measure(
            primary_verdict_at_canonical="no_winner",
            canonical_width=4096,
            full_widths=(2048, 4096, 8192),
        )
        assert widths == [4096]

    def test_not_measurable_does_not_cascade(self) -> None:
        widths = schema_widths_to_measure(
            primary_verdict_at_canonical="not_measurable",
            canonical_width=4096,
            full_widths=(2048, 4096, 8192),
        )
        assert widths == [4096]
