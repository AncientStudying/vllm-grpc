"""US2 / T027 / FR-007 / FR-009 — Supersession table generation.

``m4_supersede`` reads ``docs/benchmarks/m3-channel-tuning-time.json`` and
produces a ``SupersessionEntry`` for every M3 cell with verdict
``noise_bounded``, mapping to the matching M4 cell on
``(path, hidden_size, axis, config_name)``.
"""

from __future__ import annotations

import json
from pathlib import Path


def _make_m3_time_json(tmp_path: Path) -> Path:
    payload = {
        "mode": "p1-time-reanalysis",
        "axes": ["compression"],
        "widths": [4096],
        "paths": ["chat_stream"],
        "iterations_per_cell": 100,
        "seed": 0,
        "cohorts": [
            {
                "cell_id": "chat_stream|h4096|compression-gzip|m4_chat",
                "path": "chat_stream",
                "hidden_size": 4096,
                "config_name": "compression-gzip",
                "config_axis": "compression",
            }
        ],
        "recommendations": [
            {
                "axis": "compression",
                "applies_to_path": "chat_stream",
                "applies_to_widths": [4096],
                "verdict": "noise_bounded",
                "winning_config": None,
                "notes": "M3 noise_bounded under per-axis baseline",
                "citation": "x",
            }
        ],
    }
    out = tmp_path / "m3-channel-tuning-time.json"
    out.write_text(json.dumps(payload))
    return out


class TestSupersede:
    def test_emits_entry_for_each_noise_bounded_recommendation(self, tmp_path: Path) -> None:
        from vllm_grpc_bench.m4_supersede import build_supersession_entries

        m3_path = _make_m3_time_json(tmp_path)
        # Stand in for the M4 cohort. The supersede builder matches on
        # (path, hidden_size, axis, config_name) — when given a matching
        # M4-side cell description, it should produce one entry per
        # noise_bounded M3 cell.
        m4_cells = [
            {
                "cell_id": "chat_stream|h4096|compression|m4_chat",
                "path": "chat_stream",
                "hidden_size": 4096,
                "config_name": "compression-gzip",
                "config_axis": "compression",
                "verdict": "recommend",
            }
        ]
        entries = build_supersession_entries(m3_path, m4_cells)
        assert len(entries) == 1
        entry = entries[0]
        assert entry.m3_verdict == "noise_bounded"
        assert entry.m4_verdict == "recommend"
        assert entry.rationale  # non-empty

    def test_no_noise_bounded_no_entries(self, tmp_path: Path) -> None:
        from vllm_grpc_bench.m4_supersede import build_supersession_entries

        m3_path = tmp_path / "m3-channel-tuning-time.json"
        m3_path.write_text(
            json.dumps(
                {
                    "mode": "p1-time-reanalysis",
                    "recommendations": [
                        {
                            "axis": "compression",
                            "applies_to_path": "chat_stream",
                            "applies_to_widths": [4096],
                            "verdict": "recommend",
                            "winning_config": "compression-gzip",
                            "notes": "x",
                            "citation": "x",
                        }
                    ],
                    "cohorts": [],
                }
            )
        )
        entries = build_supersession_entries(m3_path, [])
        assert entries == []
