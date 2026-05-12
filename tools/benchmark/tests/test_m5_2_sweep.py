"""T023 — M5.2 sweep orchestrator tests.

Covers:
- ``enumerate_cells`` produces 18 cells (the M5.2 matrix is the M5.1 matrix).
- ``dispatch_cell`` schedules cohorts in the documented R-1 order.
- At c=1 the tuned-pair collapses to a single ``tuned_grpc`` cohort.
- At c=4/c=8 both ``tuned_grpc_multiplexed`` and ``tuned_grpc_channels``
  are present.
- Two REST cohorts are present at every cell regardless of concurrency.
- Per-request events are emitted to the sidecar in dispatch order.
- The borderline-expand cascade does NOT exceed ``--m5_2-n=250`` per FR-011
  (we assert that the sweep config exposes the cap).
"""

from __future__ import annotations

from pathlib import Path

from vllm_grpc_bench.m3_types import RTTRecord, Sample
from vllm_grpc_bench.m5_1_grpc_cohort import GRPCCohortResult
from vllm_grpc_bench.m5_2_events import (
    EventsSidecarWriter,
    read_sidecar_iter,
)
from vllm_grpc_bench.m5_2_sweep import (
    CellSpec,
    M5_2CellMeasurement,
    M5_2SweepConfig,
    enumerate_cells,
    write_cell_events_to_sidecar,
)
from vllm_grpc_bench.rest_cohort import (
    RESTCohortRecord,
    RESTCohortResult,
    RESTCohortSample,
)


def _fake_rest(network_path: str, n: int = 3) -> RESTCohortResult:
    samples = tuple(
        RESTCohortSample(
            wall_clock_seconds=0.010 + 0.001 * i,
            shim_overhead_ms=0.3,
            request_bytes=512,
            response_bytes=1024,
        )
        for i in range(n)
    )
    return RESTCohortResult(
        samples=samples,
        record=RESTCohortRecord(
            shim_overhead_ms_median=0.3,
            shim_overhead_ms_p95=0.4,
            connections_opened=4,
            connections_keepalive_reused=n - 4 if n > 4 else 0,
            request_bytes_median=512,
            request_bytes_p95=512,
            response_bytes_median=1024,
            response_bytes_p95=1024,
        ),
        rtt_record=RTTRecord(n=4, median_ms=50.0, p95_ms=55.0, samples_ms=(48.0, 50.0, 52.0, 55.0)),
        network_path=network_path,  # type: ignore[arg-type]
    )


def _fake_grpc(cohort_kind: str, n: int = 3) -> GRPCCohortResult:
    samples = tuple(
        Sample(
            cell_id="test",
            iteration=i,
            request_wire_bytes=256,
            response_wire_bytes=2048,
            wall_clock_seconds=0.012 + 0.001 * i,
            time_to_first_token_seconds=0.005 + 0.0001 * i,
        )
        for i in range(n)
    )
    return GRPCCohortResult(
        samples=samples,
        rtt_record=RTTRecord(n=4, median_ms=48.0, p95_ms=53.0, samples_ms=(46.0, 48.0, 50.0, 53.0)),
        sub_cohort_kind=cohort_kind,  # type: ignore[arg-type]
        channels_opened=1,
    )


def test_enumerate_cells_produces_eighteen_cells() -> None:
    cells = enumerate_cells()
    assert len(cells) == 18
    assert {c.path for c in cells} == {"chat_stream", "embed"}
    assert {c.hidden_size for c in cells} == {2048, 4096, 8192}
    assert {c.concurrency for c in cells} == {1, 4, 8}


def test_smoke_cells_cover_each_cohort_kind_and_c1_degeneracy() -> None:
    """``SMOKE_CELLS`` covers chat_stream/embed × c=1/c=4 so every code path
    is exercised: both REST transports, all four gRPC kinds (tuned_grpc at
    c=1; tuned_multiplexed/tuned_channels at c=4; default_grpc on every),
    and both metric types (TTFT for chat_stream; wallclock for embed)."""
    from vllm_grpc_bench.m5_2_sweep import SMOKE_CELLS

    paths = {c.path for c in SMOKE_CELLS}
    concs = {c.concurrency for c in SMOKE_CELLS}
    assert paths == {"chat_stream", "embed"}
    assert concs == {1, 4}


def test_write_cell_events_to_sidecar_emits_records_in_dispatch_order(
    tmp_path: Path,
) -> None:
    """Per research R-1: dispatch order is rest_https_edge → rest_plain_tcp
    → default_grpc → tuned_grpc_multiplexed → tuned_grpc_channels (c>=2).
    The sidecar writer records in the same order so a `gunzip -c | head`
    immediately surfaces the rest_https_edge cohort first.
    """
    cell = CellSpec(path="chat_stream", hidden_size=2048, concurrency=4)
    measurement = M5_2CellMeasurement(
        cell=cell,
        rest_https_edge=_fake_rest("https_edge"),
        rest_plain_tcp=_fake_rest("plain_tcp"),
        default_grpc=_fake_grpc("default_grpc"),
        tuned_multiplexed=_fake_grpc("tuned_grpc_multiplexed"),
        tuned_channels=_fake_grpc("tuned_grpc_channels"),
        tuned_grpc=None,
    )

    with EventsSidecarWriter(tmp_path, "test-run") as w:
        write_cell_events_to_sidecar(measurement, w)

    gz_path, _sha = w.result
    records = list(read_sidecar_iter(gz_path))
    cohorts_in_order = [r.cohort for r in records]
    # First 3 are rest_https_edge, next 3 rest_plain_tcp, then 3 default,
    # then 3 mux, then 3 channels.
    assert cohorts_in_order[0:3] == ["rest_https_edge"] * 3
    assert cohorts_in_order[3:6] == ["rest_plain_tcp"] * 3
    assert cohorts_in_order[6:9] == ["default_grpc"] * 3
    assert cohorts_in_order[9:12] == ["tuned_grpc_multiplexed"] * 3
    assert cohorts_in_order[12:15] == ["tuned_grpc_channels"] * 3


def test_c1_cell_writes_only_four_cohorts(tmp_path: Path) -> None:
    """At c=1 the tuned-pair collapses to a single ``tuned_grpc`` cohort,
    so only four cohorts (REST×2 + default_grpc + tuned_grpc) emit
    records.
    """
    cell = CellSpec(path="chat_stream", hidden_size=2048, concurrency=1)
    measurement = M5_2CellMeasurement(
        cell=cell,
        rest_https_edge=_fake_rest("https_edge"),
        rest_plain_tcp=_fake_rest("plain_tcp"),
        default_grpc=_fake_grpc("default_grpc"),
        tuned_multiplexed=None,
        tuned_channels=None,
        tuned_grpc=_fake_grpc("tuned_grpc"),
    )
    with EventsSidecarWriter(tmp_path, "c1-run") as w:
        write_cell_events_to_sidecar(measurement, w)
    gz_path, _ = w.result
    cohorts = {r.cohort for r in read_sidecar_iter(gz_path)}
    assert cohorts == {"rest_https_edge", "rest_plain_tcp", "default_grpc", "tuned_grpc"}


def test_c4_cell_writes_five_cohorts(tmp_path: Path) -> None:
    cell = CellSpec(path="embed", hidden_size=4096, concurrency=4)
    measurement = M5_2CellMeasurement(
        cell=cell,
        rest_https_edge=_fake_rest("https_edge"),
        rest_plain_tcp=_fake_rest("plain_tcp"),
        default_grpc=_fake_grpc("default_grpc"),
        tuned_multiplexed=_fake_grpc("tuned_grpc_multiplexed"),
        tuned_channels=_fake_grpc("tuned_grpc_channels"),
        tuned_grpc=None,
    )
    with EventsSidecarWriter(tmp_path, "c4-run") as w:
        write_cell_events_to_sidecar(measurement, w)
    gz_path, _ = w.result
    cohorts = {r.cohort for r in read_sidecar_iter(gz_path)}
    assert cohorts == {
        "rest_https_edge",
        "rest_plain_tcp",
        "default_grpc",
        "tuned_grpc_multiplexed",
        "tuned_grpc_channels",
    }


def test_m5_2_sweep_config_caps_expand_n_at_n_per_cohort() -> None:
    """FR-011: the borderline-expand cascade does NOT expand beyond n=250.
    The sweep config exposes the cap via the ``expand_n`` field; the
    cohort runners read ``n_per_cohort`` for the measurement window.
    """
    cfg = M5_2SweepConfig(
        rest_https_edge_url="https://edge.example",
        rest_plain_tcp_url="http://tcp.example:8000",
        grpc_target="tcp.example:50051",
        run_id="test",
        events_sidecar_out_dir=Path("/tmp/m5_2-test"),
    )
    assert cfg.n_per_cohort == 250
    assert cfg.expand_n == 250
    assert cfg.expand_n == cfg.n_per_cohort


def test_warmup_records_persisted_with_phase_warmup(tmp_path: Path) -> None:
    """FR-012a (g): warmup records are written to the sidecar with
    ``phase: "warmup"`` so the regenerator can audit warmup but excludes
    them from aggregates per FR-011.
    """
    cell = CellSpec(path="embed", hidden_size=2048, concurrency=1)
    measurement = M5_2CellMeasurement(
        cell=cell,
        rest_https_edge=_fake_rest("https_edge"),
        rest_plain_tcp=_fake_rest("plain_tcp"),
        default_grpc=_fake_grpc("default_grpc"),
        tuned_multiplexed=None,
        tuned_channels=None,
        tuned_grpc=_fake_grpc("tuned_grpc"),
    )
    with EventsSidecarWriter(tmp_path, "warm-run") as w:
        write_cell_events_to_sidecar(measurement, w, phase="warmup")
        write_cell_events_to_sidecar(measurement, w, phase="measurement")
    gz_path, _ = w.result
    records = list(read_sidecar_iter(gz_path))
    phases = {r.phase for r in records}
    assert phases == {"warmup", "measurement"}


def test_warmup_samples_emit_with_phase_warmup_when_present(tmp_path: Path) -> None:
    """FR-012a (g) — the sweep layer writes warmup samples to the sidecar
    BEFORE measurement samples (per cohort), labeling them
    ``phase="warmup"`` and zeroing ``rtt_at_issue_ms`` (the RTT probe
    hadn't run yet at warmup-issue time).
    """
    cell = CellSpec(path="chat_stream", hidden_size=2048, concurrency=4)
    rest_edge = _fake_rest("https_edge", n=5)
    rest_edge = RESTCohortResult(
        samples=rest_edge.samples,
        record=rest_edge.record,
        rtt_record=rest_edge.rtt_record,
        network_path=rest_edge.network_path,
        warmup_samples=tuple(
            RESTCohortSample(
                wall_clock_seconds=0.030 + 0.001 * i,
                shim_overhead_ms=0.4,
                request_bytes=512,
                response_bytes=1024,
            )
            for i in range(2)
        ),
    )
    measurement = M5_2CellMeasurement(
        cell=cell,
        rest_https_edge=rest_edge,
        rest_plain_tcp=_fake_rest("plain_tcp"),
        default_grpc=_fake_grpc("default_grpc"),
        tuned_multiplexed=_fake_grpc("tuned_grpc_multiplexed"),
        tuned_channels=_fake_grpc("tuned_grpc_channels"),
        tuned_grpc=None,
    )
    with EventsSidecarWriter(tmp_path, "warm-mixed") as w:
        write_cell_events_to_sidecar(measurement, w)
    gz_path, _ = w.result
    records = list(read_sidecar_iter(gz_path))
    edge_records = [r for r in records if r.cohort == "rest_https_edge"]
    # Warmup records emit FIRST per cohort, then measurement.
    assert edge_records[0].phase == "warmup"
    assert edge_records[1].phase == "warmup"
    assert all(r.phase == "measurement" for r in edge_records[2:])
    # Warmup records carry rtt_at_issue_ms=0 (probe hadn't run yet).
    assert all(r.rtt_at_issue_ms == 0.0 for r in edge_records[:2])
    # Measurement records carry the cohort's measured RTT median.
    assert all(r.rtt_at_issue_ms == 50.0 for r in edge_records[2:])


def test_warmup_records_excluded_when_no_warmup_samples_present(tmp_path: Path) -> None:
    """Back-compat: when result.warmup_samples is empty (M5.1 callers),
    only measurement records reach the sidecar — no spurious empty
    ``phase=warmup`` rows."""
    cell = CellSpec(path="embed", hidden_size=2048, concurrency=4)
    measurement = M5_2CellMeasurement(
        cell=cell,
        rest_https_edge=_fake_rest("https_edge"),
        rest_plain_tcp=_fake_rest("plain_tcp"),
        default_grpc=_fake_grpc("default_grpc"),
        tuned_multiplexed=_fake_grpc("tuned_grpc_multiplexed"),
        tuned_channels=_fake_grpc("tuned_grpc_channels"),
        tuned_grpc=None,
    )
    with EventsSidecarWriter(tmp_path, "no-warm") as w:
        write_cell_events_to_sidecar(measurement, w)
    gz_path, _ = w.result
    records = list(read_sidecar_iter(gz_path))
    assert all(r.phase == "measurement" for r in records)
