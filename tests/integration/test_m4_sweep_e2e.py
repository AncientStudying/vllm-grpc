"""US2 / T035 — end-to-end small-fixture M4 sweep.

Drives a tiny ``--m4 --skip-schema`` sweep against the in-process gRPC
mock engine. Confirms:

- The run completes without raising.
- ``validate_run`` accepts the result (no FR-007 / FR-002 violations).
- The report JSON is parseable by an M3-shape reader (the strict-superset
  guarantee from FR-015 / R-7).
- A SupersessionEntry is produced for an M3 noise_bounded fixture.
- No cohort carries the ``noise_bounded`` literal.

The sweep uses a single axis (``compression``), one width (4096), and the
``baseline_n=100/candidate_n=100`` default. Even at small ``hidden_size``
this takes a few seconds to run, which is acceptable for an integration
test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vllm_grpc_bench.m3_types import M4SweepConfig
from vllm_grpc_bench.m4_supersede import build_supersession_entries
from vllm_grpc_bench.m4_sweep import run_m4_sweep, validate_run
from vllm_grpc_bench.reporter import write_m4_json


@pytest.mark.asyncio
async def test_m4_skip_schema_end_to_end(tmp_path: Path) -> None:
    # baseline_cv_max is loosened for the in-process integration test:
    # cold-start gRPC channel/server bring-up dominates wall-clock variance
    # on the first batch of RPCs. The CV cap is the operator's defense for
    # full-sweep runs on a quiet host (R-11) — exercised in production by
    # the operator-driven sweep, not by CI fixtures.
    config = M4SweepConfig(
        pacing_mode="no_pacing",
        baseline_n=100,
        candidate_n=100,
        expand_n=200,
        baseline_cv_max=10.0,
        widths=(4096,),
        paths=("embed",),
        axes=("compression",),
        skip_schema=True,
        schema_canonical_width=4096,
    )
    run = await run_m4_sweep(config, progress=False)

    # Invariants from data-model.md hold.
    validate_run(run)

    # No noise_bounded literal anywhere in the recommendations.
    assert all(r.verdict != "noise_bounded" for r in run.recommendations)

    # Cohorts include the shared baseline plus at least one candidate.
    assert any(c.is_baseline and c.baseline_role == "m1_shared" for c in run.cohorts)
    assert any(not c.is_baseline for c in run.cohorts)

    # Strict-superset JSON: M3-shape readers can still consume the file.
    out = tmp_path / "m4-time-axis-tuning.json"
    write_m4_json(run, out)
    payload = json.loads(out.read_text())
    for required in (
        "mode",
        "axes",
        "widths",
        "paths",
        "iterations_per_cell",
        "seed",
        "cohorts",
    ):
        assert required in payload, f"M3-shape reader missing field: {required}"
    for cohort in payload["cohorts"]:
        for required in (
            "cell_id",
            "path",
            "hidden_size",
            "config_name",
            "config_axis",
            "iterations",
            "n_successful",
            "measurable",
            "bytes",
            "time_seconds",
        ):
            assert required in cohort

    # Supersession entries against a synthetic M3 noise_bounded fixture.
    m3_fixture = tmp_path / "m3-channel-tuning-time.json"
    m3_fixture.write_text(
        json.dumps(
            {
                "mode": "p1-time-reanalysis",
                "recommendations": [
                    {
                        "axis": "compression",
                        "applies_to_path": "embed",
                        "applies_to_widths": [4096],
                        "verdict": "noise_bounded",
                        "winning_config": "compression-gzip",
                        "notes": "fixture",
                        "citation": "x",
                    }
                ],
                "cohorts": [],
            }
        )
    )
    m4_cells = [
        {
            "cell_id": cohort["cell_id"],
            "path": cohort["path"],
            "hidden_size": cohort["hidden_size"],
            "config_axis": cohort["config_axis"],
            "config_name": cohort["config_name"],
            "verdict": "no_winner",
        }
        for cohort in payload["cohorts"]
    ]
    entries = build_supersession_entries(m3_fixture, m4_cells)
    assert any(e.m3_verdict == "noise_bounded" for e in entries)
