"""US2 / T028 / FR-015 / R-7 — strict-superset JSON schema.

Every M3 top-level field and every M3 per-cohort field is preserved with
identical semantics; M4-only fields are additive.
"""

from __future__ import annotations

import json
from pathlib import Path

from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    Run,
    RunCohort,
)
from vllm_grpc_bench.reporter import write_m4_json


def _baseline(path: str) -> RunCohort:
    cell = BenchmarkCell(
        path=path,  # type: ignore[arg-type]
        hidden_size=4096,
        channel_config=M1_BASELINE,
        corpus_subset="m1_embed" if path == "embed" else "m1_chat",  # type: ignore[arg-type]
        iterations=100,
    )
    return RunCohort(
        cell=cell,
        samples=tuple(),
        n_successful=100,
        bytes_mean=200.0,
        bytes_ci_low=199.0,
        bytes_ci_high=201.0,
        time_mean=0.01,
        time_ci_low=0.0095,
        time_ci_high=0.0105,
        is_baseline=True,
        baseline_role="m1_shared",
        time_to_first_token_seconds=(0.005, 0.0048, 0.0052) if path == "chat_stream" else None,
    )


def _build_run() -> Run:
    embed = _baseline("embed")
    chat = _baseline("chat_stream")
    return Run(
        mode="m4-time-axis-tuning",
        axes=["compression"],
        widths=[4096],
        paths=["embed", "chat_stream"],
        iterations_per_cell=100,
        seed=0,
        cohorts=[embed, chat],
        pacing_mode="no_pacing",
        shared_baseline_cohort_ids={
            "embed": embed.cell.cell_id,
            "chat_stream": chat.cell.cell_id,
        },
        loopback_caveat_axes=[],
    )


M3_TOP_LEVEL_FIELDS = {
    "mode",
    "axes",
    "widths",
    "paths",
    "iterations_per_cell",
    "seed",
    "p2_revision",
    "frozen_channel",
    "cohorts",
}

M3_COHORT_FIELDS = {
    "cell_id",
    "path",
    "hidden_size",
    "config_name",
    "config_axis",
    "corpus_subset",
    "iterations",
    "n_successful",
    "measurable",
    "off_canonical",
    "bytes",
    "time_seconds",
}

M4_NEW_TOP_LEVEL_FIELDS = {
    "pacing_mode",
    "shared_baseline_cohort_ids",
    "frozen_channel_baselines",
    "supersedes",
    "candidate_sizing_policy",
    "loopback_caveat_axes",
    "schema_candidate_results",
}

M4_NEW_COHORT_FIELDS = {
    "is_baseline",
    "baseline_role",
    "expansion_record",
    "client_bound",
    "time_to_first_token_seconds",
}


def test_top_level_strict_superset(tmp_path: Path) -> None:
    out = tmp_path / "m4.json"
    write_m4_json(_build_run(), out)
    payload = json.loads(out.read_text())
    keys = set(payload.keys())
    assert M3_TOP_LEVEL_FIELDS.issubset(keys), f"M3 fields missing: {M3_TOP_LEVEL_FIELDS - keys}"
    assert M4_NEW_TOP_LEVEL_FIELDS.issubset(keys), (
        f"M4 fields missing: {M4_NEW_TOP_LEVEL_FIELDS - keys}"
    )
    assert payload["mode"] == "m4-time-axis-tuning"


def test_per_cohort_strict_superset(tmp_path: Path) -> None:
    out = tmp_path / "m4.json"
    write_m4_json(_build_run(), out)
    payload = json.loads(out.read_text())
    for cohort in payload["cohorts"]:
        keys = set(cohort.keys())
        assert M3_COHORT_FIELDS.issubset(keys), (
            f"M3 cohort fields missing: {M3_COHORT_FIELDS - keys}"
        )
        assert M4_NEW_COHORT_FIELDS.issubset(keys), (
            f"M4 cohort fields missing: {M4_NEW_COHORT_FIELDS - keys}"
        )
