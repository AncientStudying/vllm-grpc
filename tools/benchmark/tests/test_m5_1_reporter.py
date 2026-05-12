"""T030 — M5.1 reporter tests covering JSON shape, additive-only superset
rule, cohort/matrix consistency, and absence of token-shaped strings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from vllm_grpc_bench.channel_config import M1_BASELINE
from vllm_grpc_bench.m3_types import (
    BenchmarkCell,
    CellVerdict,
    M5_1Cell,
    M5_1RunMetadata,
    RESTCohortRecord,
    RTTRecord,
    RunCohort,
    Sample,
    ShimOverheadRecord,
    SupersedesM1Entry,
)
from vllm_grpc_bench.reporter import write_m5_1_json, write_m5_1_markdown


def _make_minimal_run() -> tuple[M5_1RunMetadata, list[RunCohort]]:
    """Build a minimal M5.1 run with two cells (c=1 + c=4) for one path/width."""
    rtt = RTTRecord(n=8, median_ms=52.0, p95_ms=58.0, samples_ms=(52.0,) * 8)

    # Cell c=1 — two verdicts.
    cell_c1 = M5_1Cell(
        path="chat_stream",
        hidden_size=2048,
        concurrency=1,
        rest_cohort_key="rest:chat_stream:h2048:c1",
        default_grpc_cohort_key="grpc-default:chat_stream:h2048:c1",
        tuned_grpc_multiplexed_cohort_key="grpc-tuned:chat_stream:h2048:c1",
        tuned_grpc_channels_cohort_key=None,
        verdicts=[
            CellVerdict(
                grpc_sub_cohort="tuned_grpc",
                verdict="tuned_grpc_recommend",
                delta_pct=-15.0,
                ci_pct=(-20.0, -10.0),
                metric="ttft",
            ),
            CellVerdict(
                grpc_sub_cohort="default_grpc",
                verdict="no_winner",
                delta_pct=-1.0,
                ci_pct=(-5.0, 3.0),
                metric="ttft",
            ),
        ],
        comparison_unavailable=False,
        comparison_unavailable_reason=None,
        rtt_ms_median=52.0,
        rtt_ms_p95=58.0,
        low_rtt_caveat=False,
    )
    # Cell c=4 — three verdicts.
    cell_c4 = M5_1Cell(
        path="chat_stream",
        hidden_size=2048,
        concurrency=4,
        rest_cohort_key="rest:chat_stream:h2048:c4",
        default_grpc_cohort_key="grpc-default:chat_stream:h2048:c4",
        tuned_grpc_multiplexed_cohort_key="grpc-tuned-mux:chat_stream:h2048:c4",
        tuned_grpc_channels_cohort_key="grpc-tuned-ch:chat_stream:h2048:c4",
        verdicts=[
            CellVerdict(
                grpc_sub_cohort="tuned_grpc_multiplexed",
                verdict="tuned_grpc_multiplexed_recommend",
                delta_pct=-18.0,
                ci_pct=(-22.0, -14.0),
                metric="ttft",
            ),
            CellVerdict(
                grpc_sub_cohort="tuned_grpc_channels",
                verdict="no_winner",
                delta_pct=-2.0,
                ci_pct=(-5.0, 1.0),
                metric="ttft",
            ),
            CellVerdict(
                grpc_sub_cohort="default_grpc",
                verdict="rest_recommend",
                delta_pct=8.0,
                ci_pct=(4.0, 13.0),
                metric="ttft",
            ),
        ],
        comparison_unavailable=False,
        comparison_unavailable_reason=None,
        rtt_ms_median=52.0,
        rtt_ms_p95=58.0,
        low_rtt_caveat=False,
    )

    metadata = M5_1RunMetadata(
        modal_app_handle="vllm-grpc-bench-rest-grpc-mock",
        modal_region="eu-west-1",
        modal_instance_class="cpu",
        rest_shim_version_sha="testsha",
        rest_shim_uvicorn_workers=1,
        auth_token_env_var="MODAL_BENCH_TOKEN",
        shim_overhead=ShimOverheadRecord(
            shim_overhead_ms_median_across_run=0.4,
            shim_overhead_ms_p95_across_run=0.9,
            shim_overhead_ms_max_across_run=2.1,
            shim_overhead_material_in_any_cohort=False,
        ),
        supersedes_m1_time=[
            SupersedesM1Entry(
                m1_path="chat_completion",
                m1_concurrency=1,
                m1_verdict_literal="REST faster (c=1 small-body chat)",
                m1_source_report="docs/benchmarks/phase-3-modal-comparison.md#chat-c1",
                m5_1_verdict_per_width={2048: "tuned_grpc_recommend"},
                m5_1_supporting_delta_pct={2048: -15.0},
                m5_1_supporting_ci_pct={2048: (-20.0, -10.0)},
                classification="verdict_changed",
                rationale="On real wire, tuned-gRPC HTTP/2 multiplexing reverses M1's "
                "loopback-era REST-wins finding. Note: MockEngine, not real vLLM.",
            )
        ],
        m5_1_matrix=[cell_c1, cell_c4],
    )

    # Cohort entries: REST + tuned-grpc (c=1) for c=1 cell; REST + 2× gRPC for c=4.
    bench_cell = BenchmarkCell(
        path="chat_stream",
        hidden_size=2048,
        channel_config=M1_BASELINE,
        corpus_subset="m1_chat",
        iterations=100,
    )
    sample = Sample(
        cell_id="chat_stream:h2048:c1",
        iteration=0,
        request_wire_bytes=300,
        response_wire_bytes=1800,
        wall_clock_seconds=0.08,
    )
    rest_record = RESTCohortRecord(
        shim_overhead_ms_median=0.4,
        shim_overhead_ms_p95=0.9,
        connections_opened=1,
        connections_keepalive_reused=99,
        request_bytes_median=300,
        request_bytes_p95=300,
        response_bytes_median=1800,
        response_bytes_p95=1900,
    )
    cohort_rest_c1 = RunCohort(
        cell=bench_cell,
        samples=(sample,),
        n_successful=1,
        bytes_mean=300.0,
        bytes_ci_low=300.0,
        bytes_ci_high=300.0,
        time_mean=0.08,
        time_ci_low=0.07,
        time_ci_high=0.09,
        rtt_record=rtt,
        protocol="rest",
        grpc_channel_model=None,
        connection_count=1,
        shim_overhead_ms=0.4,
        comparison_cell_key="chat_stream:h2048:c1",
        rest_cohort_record=rest_record,
    )
    cohort_grpc_c1 = RunCohort(
        cell=bench_cell,
        samples=(sample,),
        n_successful=1,
        bytes_mean=300.0,
        bytes_ci_low=300.0,
        bytes_ci_high=300.0,
        time_mean=0.07,
        time_ci_low=0.06,
        time_ci_high=0.08,
        rtt_record=rtt,
        protocol="grpc",
        grpc_channel_model="tuned_grpc",
        connection_count=1,
        shim_overhead_ms=None,
        comparison_cell_key="chat_stream:h2048:c1",
        rest_cohort_record=None,
    )
    cohort_grpc_default_c1 = RunCohort(
        cell=bench_cell,
        samples=(sample,),
        n_successful=1,
        bytes_mean=300.0,
        bytes_ci_low=300.0,
        bytes_ci_high=300.0,
        time_mean=0.079,
        time_ci_low=0.075,
        time_ci_high=0.082,
        rtt_record=rtt,
        protocol="grpc",
        grpc_channel_model="default_grpc",
        connection_count=1,
        shim_overhead_ms=None,
        comparison_cell_key="chat_stream:h2048:c1",
        rest_cohort_record=None,
    )
    cohorts = [cohort_rest_c1, cohort_grpc_c1, cohort_grpc_default_c1]
    return metadata, cohorts


def test_m5_1_json_carries_all_m5_keys(tmp_path: Path) -> None:
    """T030 (a): every M5 top-level key is present, plus M5.1-specific keys."""
    metadata, cohorts = _make_minimal_run()
    out = tmp_path / "m5_1.json"
    write_m5_1_json(metadata, cohorts, sample_size=100, path=out)
    payload = json.loads(out.read_text())
    # M5 keys present (additive-only).
    for key in (
        "run_id",
        "shared_baseline_cohorts",
        "channel_axis_recommendations",
        "schema_candidate_recommendations",
        "supersedes_m4",
        "supersedes_m3",
        "rtt_distribution",
        "modal_metadata",
        "cohorts",
    ):
        assert key in payload, f"missing M5 key: {key}"
    # M5.1 additive keys.
    for key in (
        "m5_1_matrix",
        "supersedes_m1_time",
        "rest_shim_meta",
        "auth_token_env_var",
    ):
        assert key in payload, f"missing M5.1 key: {key}"


def test_m5_1_json_cohort_comparison_cell_key_resolves(tmp_path: Path) -> None:
    """T030 (b): every cohort's comparison_cell_key resolves to a matrix entry."""
    metadata, cohorts = _make_minimal_run()
    out = tmp_path / "m5_1.json"
    write_m5_1_json(metadata, cohorts, sample_size=100, path=out)
    payload = json.loads(out.read_text())
    matrix_keys = {c["comparison_cell_key"] for c in payload["m5_1_matrix"]}
    for cohort in payload["cohorts"]:
        assert cohort["comparison_cell_key"] in matrix_keys


def test_m5_1_verdict_count_matches_concurrency(tmp_path: Path) -> None:
    """T030 (c): len(verdicts) == 3 at c >= 2; len(verdicts) == 2 at c=1."""
    metadata, cohorts = _make_minimal_run()
    out = tmp_path / "m5_1.json"
    write_m5_1_json(metadata, cohorts, sample_size=100, path=out)
    payload = json.loads(out.read_text())
    for cell in payload["m5_1_matrix"]:
        if cell["concurrency"] >= 2:
            assert len(cell["verdicts"]) == 3
        else:
            assert len(cell["verdicts"]) == 2


def test_m5_1_json_no_bearer_token_in_payload(tmp_path: Path) -> None:
    """T030 (d): no token-shaped string is emitted in the JSON."""
    metadata, cohorts = _make_minimal_run()
    out = tmp_path / "m5_1.json"
    write_m5_1_json(metadata, cohorts, sample_size=100, path=out)
    text = out.read_text()
    # No "Bearer " prefix.
    assert "Bearer " not in text
    # No `secrets.token_urlsafe(32)`-shaped value: 30+ chars URL-safe with
    # both upper- and lower-case letters (snake_case identifiers like
    # `schema_candidate_recommendations` are lowercase-only and so don't trip).
    for match in re.finditer(r"\b[A-Za-z0-9_-]{30,}\b", text):
        s = match.group(0)
        has_upper = any(c.isupper() for c in s)
        has_lower = any(c.islower() for c in s)
        has_digit = any(c.isdigit() for c in s)
        if has_upper and has_lower and has_digit:
            pytest.fail(f"token-shaped string leaked into report: {s!r}")


def test_m5_1_markdown_executive_section_names_headline(tmp_path: Path) -> None:
    """T030 (e): executive Markdown section names headline finding shape."""
    metadata, _ = _make_minimal_run()
    out = tmp_path / "m5_1.md"
    write_m5_1_markdown(metadata, out)
    text = out.read_text()
    assert "## Executive summary" in text
    assert "MockEngine" in text  # read-instruction caveat per FR-015
    assert "Bytes-axis" in text or "bytes-axis" in text  # FR-021 preservation
    assert "Supersedes M1" in text  # supersession table heading
    assert "Negative results" in text


def test_m5_1_markdown_highlights_verdict_changed_rows(tmp_path: Path) -> None:
    """T030 (e): verdict_changed rows are visually distinguishable (bold)."""
    metadata, _ = _make_minimal_run()
    out = tmp_path / "m5_1.md"
    write_m5_1_markdown(metadata, out)
    text = out.read_text()
    # Verdict-changed row gets ** bold ** markers per FR-020.
    assert "**verdict_changed**" in text


def test_m5_1_json_token_guard_rejects_bearer_strings(tmp_path: Path) -> None:
    """Defensive: a stray bearer-token-shaped string raises rather than ships."""
    metadata, cohorts = _make_minimal_run()
    # Mutate a string field to include a Bearer-token shape; the writer
    # MUST refuse to emit it.
    poisoned = M5_1RunMetadata(
        modal_app_handle=metadata.modal_app_handle,
        modal_region=metadata.modal_region,
        modal_instance_class=metadata.modal_instance_class,
        rest_shim_version_sha="Bearer abc123",  # malicious value
        rest_shim_uvicorn_workers=metadata.rest_shim_uvicorn_workers,
        auth_token_env_var=metadata.auth_token_env_var,
        shim_overhead=metadata.shim_overhead,
        supersedes_m1_time=metadata.supersedes_m1_time,
        m5_1_matrix=metadata.m5_1_matrix,
    )
    with pytest.raises(RuntimeError, match=r"bearer-token-shaped"):
        write_m5_1_json(poisoned, cohorts, sample_size=100, path=tmp_path / "should_fail.json")
