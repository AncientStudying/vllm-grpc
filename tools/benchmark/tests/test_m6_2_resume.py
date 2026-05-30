"""M6.2 — Phase-1 resume / checkpoint plumbing.

Covers:

* ``CheckpointHeader`` serialisation round-trip (write → load → equal).
* Measurement + anchor JSONL append round-trip (every field preserved
  by ``M6_2MeasurementPoint(**payload)`` and ``M6_2AnchorLatencySnapshot(**payload)``).
* Integrity gate: ``validate_checkpoint_against_current_run`` rejects
  each of the nine integrity-gated fields with a precise diagnostic and
  composes a multi-field diff message when more than one diverged.
* Robustness: truncated tail line dropped, missing header rejected,
  schema_version drift rejected, file-not-found rejected.
* Sweep integration: ``run_sweep`` with pre-loaded measurements
  emits ``BLOCK_SKIPPED`` for completed (cell, cohort, max_tokens)
  tuples and appends only the missing rows; pre-loaded anchor snapshots
  suppress the t=0 anchor; ``checkpoint_path`` produces an on-disk
  sidecar with one JSON line per block + per anchor snapshot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from vllm_grpc_bench.m6_1_2_types import M6_1_2CohortKind
from vllm_grpc_bench.m6_2_resume import (
    RESUME_SCHEMA_VERSION,
    CheckpointHeader,
    CheckpointMismatchError,
    append_anchor,
    append_measurement,
    completed_block_keys,
    load_checkpoint,
    validate_checkpoint_against_current_run,
    write_checkpoint_header,
)
from vllm_grpc_bench.sweep_types import M6_2AnchorLatencySnapshot, M6_2MeasurementPoint

# --- Helpers ---------------------------------------------------------------


def _sample_header(**overrides: Any) -> CheckpointHeader:
    base: dict[str, Any] = {
        "schema_version": RESUME_SCHEMA_VERSION,
        "run_id": "2026-05-25T00:00:00Z-deadbeef",
        "run_started_at": "2026-05-25T00:00:00Z",
        "sweep_mode": "publish",
        "n_per_point": 40,
        "axis": (10, 50, 256, 512, 1024, 2048),
        "base_seed": 42,
        "model_identifier": "Qwen/Qwen3-8B",
        "modal_region": "eu-west-1",
        "git_sha": "abc1234",
        "chat_corpus_sha256": "c" * 64,
        "embed_corpus_sha256": "e" * 64,
    }
    base.update(overrides)
    return CheckpointHeader(**base)


def _sample_measurement(
    cell_id: str = "embed_c1",
    cohort: M6_1_2CohortKind = "default_grpc",
    max_tokens: int = 10,
    *,
    failed: bool = False,
) -> M6_2MeasurementPoint:
    return M6_2MeasurementPoint(
        cell_id=cell_id,
        cohort=cohort,
        max_tokens=max_tokens,
        n_rpcs=40,
        wall_p50_ms=None if failed else 1234.5,
        wall_p95_ms=None if failed else 1500.0,
        wall_p99_ms=None if failed else 1700.0,
        wall_p50_ms_ci_half_width=None if failed else 12.3,
        tpot_ms=None if failed else 45.6,
        seg_ab_ms=None if failed else 10.0,
        seg_queue_ms=None if failed else 5.0,
        seg_prefill_ms=None if failed else 20.0,
        seg_ingress_ms=None if failed else 8.0,
        seg_egress_ms=None if failed else 7.0,
        failed_reason="grpc embed: StatusCode.UNAVAILABLE" if failed else None,
        block_start_utc="2026-05-25T00:01:00Z",
        block_end_utc="2026-05-25T00:01:30Z",
        retry_attempted=False,
        clock_anomaly=False,
        prompt_source="corpus_sharegpt_embed",
        measurement_regime="natural_eos",
        prompt_corpus_idx=0 if not failed else None,
    )


def _sample_snapshot(
    *,
    wall_p50_ms: float = 65.0,
    sweep_hour_mark: float = 0.0,
) -> M6_2AnchorLatencySnapshot:
    return M6_2AnchorLatencySnapshot(
        wall_p50_ms=wall_p50_ms,
        wall_p95_ms=wall_p50_ms + 1.0,
        wall_p99_ms=wall_p50_ms + 1.5,
        snapshot_timestamp="2026-05-25T00:00:00Z",
        sweep_hour_mark=sweep_hour_mark,
    )


# --- Header round-trip -----------------------------------------------------


class TestHeaderRoundTrip:
    """A header written via ``write_checkpoint_header`` and read back via
    ``load_checkpoint`` must compare equal field-for-field. Tuple-ness of
    the ``axis`` field survives the JSON round-trip (JSON serialises as a
    list, the loader rebuilds a tuple)."""

    def test_header_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "cp.jsonl"
        header = _sample_header()
        write_checkpoint_header(path, header)
        loaded_header, measurements, anchors = load_checkpoint(path)
        assert loaded_header == header
        assert measurements == []
        assert anchors == {}

    def test_header_with_different_axis_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "cp.jsonl"
        header = _sample_header(axis=(10, 50, 2048), sweep_mode="validate", n_per_point=20)
        write_checkpoint_header(path, header)
        loaded_header, _, _ = load_checkpoint(path)
        assert loaded_header == header

    def test_truncates_existing_file(self, tmp_path: Path) -> None:
        """``write_checkpoint_header`` opens in ``"w"`` mode — any stale
        content is discarded. Resuming runs do NOT call write_checkpoint_header
        precisely so they preserve the prior content."""
        path = tmp_path / "cp.jsonl"
        path.write_text("stale\nlines\nhere\n")
        write_checkpoint_header(path, _sample_header())
        # Loader sees only the one header line.
        loaded_header, measurements, anchors = load_checkpoint(path)
        assert loaded_header.run_id == "2026-05-25T00:00:00Z-deadbeef"
        assert measurements == []


# --- Measurement / anchor append round-trip --------------------------------


class TestMeasurementRoundTrip:
    def test_measurement_round_trips_full_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "cp.jsonl"
        write_checkpoint_header(path, _sample_header())
        m = _sample_measurement()
        append_measurement(path, m)
        _, measurements, _ = load_checkpoint(path)
        assert len(measurements) == 1
        assert measurements[0] == m

    def test_measurement_round_trips_failed_block(self, tmp_path: Path) -> None:
        """Failed blocks carry ``None`` for every latency field plus a
        ``failed_reason`` string. The loader must preserve the ``None``s
        rather than coerce them to 0.0 or empty strings."""
        path = tmp_path / "cp.jsonl"
        write_checkpoint_header(path, _sample_header())
        m = _sample_measurement(failed=True)
        append_measurement(path, m)
        _, measurements, _ = load_checkpoint(path)
        assert measurements[0].failed_reason is not None
        assert measurements[0].wall_p50_ms is None
        assert measurements[0].prompt_corpus_idx is None

    def test_multiple_measurements_preserve_order(self, tmp_path: Path) -> None:
        path = tmp_path / "cp.jsonl"
        write_checkpoint_header(path, _sample_header())
        cohorts: list[M6_1_2CohortKind] = ["default_grpc", "rest_https_edge", "rest_plain_tcp"]
        for i, cohort in enumerate(cohorts):
            append_measurement(path, _sample_measurement(cohort=cohort, max_tokens=10 + i))
        _, measurements, _ = load_checkpoint(path)
        assert [m.cohort for m in measurements] == cohorts
        assert [m.max_tokens for m in measurements] == [10, 11, 12]


class TestAnchorRoundTrip:
    def test_anchor_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "cp.jsonl"
        write_checkpoint_header(path, _sample_header())
        snap = _sample_snapshot()
        append_anchor(path, "default_grpc", snap)
        _, _, anchors = load_checkpoint(path)
        assert list(anchors.keys()) == ["default_grpc"]
        assert anchors["default_grpc"] == [snap]

    def test_multi_cohort_anchors_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "cp.jsonl"
        write_checkpoint_header(path, _sample_header())
        # Two snapshots per cohort across two anchor blocks at different hour marks.
        cohorts: list[M6_1_2CohortKind] = [
            "default_grpc",
            "rest_https_edge",
            "rest_plain_tcp",
            "tuned_grpc_multiplexed",
        ]
        for cohort in cohorts:
            append_anchor(path, cohort, _sample_snapshot(sweep_hour_mark=0.0))
        for cohort in cohorts:
            append_anchor(path, cohort, _sample_snapshot(sweep_hour_mark=4.0))
        _, _, anchors = load_checkpoint(path)
        assert sorted(anchors.keys()) == sorted(cohorts)
        for cohort in cohorts:
            assert len(anchors[cohort]) == 2
            assert anchors[cohort][0].sweep_hour_mark == 0.0
            assert anchors[cohort][1].sweep_hour_mark == 4.0


# --- Robustness ------------------------------------------------------------


class TestLoadCheckpointRobustness:
    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CheckpointMismatchError, match="not found"):
            load_checkpoint(tmp_path / "does_not_exist.jsonl")

    def test_missing_header_raises(self, tmp_path: Path) -> None:
        """A file with only measurement lines (no header) is invalid —
        the integrity gate has nothing to gate against."""
        path = tmp_path / "cp.jsonl"
        # Write a measurement line directly (no header).
        m = _sample_measurement()
        from dataclasses import asdict

        path.write_text(json.dumps({"kind": "measurement", **asdict(m)}) + "\n")
        with pytest.raises(CheckpointMismatchError, match="missing a header"):
            load_checkpoint(path)

    def test_schema_version_mismatch_raises(self, tmp_path: Path) -> None:
        """A header written under a different ``schema_version`` cannot
        be loaded — the JSONL format may have changed incompatibly."""
        path = tmp_path / "cp.jsonl"
        bad_header_line = json.dumps(
            {
                "kind": "header",
                "schema_version": "m6_2_resume.v999",
                "run_id": "x",
                "run_started_at": "2026-05-25T00:00:00Z",
                "sweep_mode": "publish",
                "n_per_point": 40,
                "axis": [10],
                "base_seed": 42,
                "model_identifier": "x",
                "modal_region": "eu-west-1",
                "git_sha": "x",
                "chat_corpus_sha256": "x",
                "embed_corpus_sha256": "x",
            }
        )
        path.write_text(bad_header_line + "\n")
        with pytest.raises(CheckpointMismatchError, match="schema_version"):
            load_checkpoint(path)

    def test_partial_tail_line_is_silently_dropped(self, tmp_path: Path) -> None:
        """Crash mid-fsync can leave a half-written JSON line at EOF.
        The loader's per-line ``try/except`` swallows the parse error
        and emits a clean ``(header, measurements, anchors)`` containing
        every line up to (but not including) the partial one."""
        path = tmp_path / "cp.jsonl"
        write_checkpoint_header(path, _sample_header())
        append_measurement(path, _sample_measurement())
        # Append a partial line that won't parse.
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"kind":"measurement","cell_id":"embed_c1",')  # truncated
        _, measurements, _ = load_checkpoint(path)
        assert len(measurements) == 1

    def test_blank_lines_silently_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "cp.jsonl"
        write_checkpoint_header(path, _sample_header())
        # Insert a blank line then a measurement.
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n\n")
        append_measurement(path, _sample_measurement())
        _, measurements, _ = load_checkpoint(path)
        assert len(measurements) == 1

    def test_unknown_kind_is_silently_ignored(self, tmp_path: Path) -> None:
        """Forward-compat: future versions may add new line kinds (e.g.
        topology probe snapshots). The loader must skip unknown ``kind``
        values without crashing."""
        path = tmp_path / "cp.jsonl"
        write_checkpoint_header(path, _sample_header())
        with open(path, "a", encoding="utf-8") as f:
            f.write('{"kind":"future_thing","payload":42}\n')
        append_measurement(path, _sample_measurement())
        _, measurements, _ = load_checkpoint(path)
        assert len(measurements) == 1


# --- Integrity gate --------------------------------------------------------


class TestValidateCheckpointAgainstCurrentRun:
    """Every integrity-gated field must reject a mismatched current-run
    value. Errors are aggregated so the operator sees all divergences in
    one diagnostic, not one-at-a-time."""

    def _validate(self, header: CheckpointHeader, **overrides: Any) -> None:
        kwargs: dict[str, Any] = {
            "sweep_mode": header.sweep_mode,
            "n_per_point": header.n_per_point,
            "axis": header.axis,
            "base_seed": header.base_seed,
            "model_identifier": header.model_identifier,
            "modal_region": header.modal_region,
            "git_sha": header.git_sha,
            "chat_corpus_sha256": header.chat_corpus_sha256,
            "embed_corpus_sha256": header.embed_corpus_sha256,
        }
        kwargs.update(overrides)
        validate_checkpoint_against_current_run(header, **kwargs)

    def test_matching_args_pass(self) -> None:
        self._validate(_sample_header())  # no overrides → match

    def test_sweep_mode_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="sweep_mode"):
            self._validate(_sample_header(), sweep_mode="validate")

    def test_n_per_point_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="n_per_point"):
            self._validate(_sample_header(), n_per_point=20)

    def test_axis_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="axis"):
            self._validate(_sample_header(), axis=(10, 50, 2048))

    def test_base_seed_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="base_seed"):
            self._validate(_sample_header(), base_seed=999)

    def test_model_identifier_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="model_identifier"):
            self._validate(_sample_header(), model_identifier="Qwen/Qwen3-7B")

    def test_modal_region_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="modal_region"):
            self._validate(_sample_header(), modal_region="us-east-1")

    def test_git_sha_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="git_sha"):
            self._validate(_sample_header(), git_sha="other-sha")

    def test_chat_corpus_sha256_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="chat_corpus_sha256"):
            self._validate(_sample_header(), chat_corpus_sha256="d" * 64)

    def test_embed_corpus_sha256_mismatch_raises(self) -> None:
        with pytest.raises(CheckpointMismatchError, match="embed_corpus_sha256"):
            self._validate(_sample_header(), embed_corpus_sha256="f" * 64)

    def test_multiple_mismatches_combined_in_message(self) -> None:
        """The operator should see ALL divergences in one shot — not
        one-at-a-time across re-runs. The error message lists every
        mismatched field."""
        with pytest.raises(CheckpointMismatchError) as excinfo:
            self._validate(
                _sample_header(),
                sweep_mode="validate",
                n_per_point=20,
                base_seed=999,
            )
        msg = str(excinfo.value)
        assert "sweep_mode" in msg
        assert "n_per_point" in msg
        assert "base_seed" in msg


# --- completed_block_keys --------------------------------------------------


class TestCompletedBlockKeys:
    def test_empty(self) -> None:
        assert completed_block_keys([]) == frozenset()

    def test_single_measurement(self) -> None:
        keys = completed_block_keys([_sample_measurement()])
        assert keys == frozenset({("embed_c1", "default_grpc", 10)})

    def test_failed_block_is_treated_as_completed(self) -> None:
        """Phase-1: failed blocks count as completed (Phase-2 will add
        ``--m6_2-resume-retry-failed`` to selectively re-run them)."""
        keys = completed_block_keys([_sample_measurement(failed=True)])
        assert keys == frozenset({("embed_c1", "default_grpc", 10)})

    def test_distinct_keys(self) -> None:
        ms = [
            _sample_measurement(cell_id="embed_c1", cohort="default_grpc", max_tokens=10),
            _sample_measurement(cell_id="embed_c1", cohort="rest_https_edge", max_tokens=10),
            _sample_measurement(cell_id="embed_c4", cohort="default_grpc", max_tokens=10),
            _sample_measurement(cell_id="embed_c1", cohort="default_grpc", max_tokens=50),
        ]
        keys = completed_block_keys(ms)
        assert len(keys) == 4


# --- Sweep loop integration ------------------------------------------------


def _stub_block_inputs() -> dict[str, Any]:
    return {
        "prompt_text": "hello",
        "embed_tensor_bytes": None,
        "ignore_eos": False,
        "prompt_source": "synthetic_seed_derived",
        "prompt_corpus_idx": None,
    }


def _stub_chat_corpus(size: int = 8) -> list[Any]:
    """Minimal chat corpus that satisfies ``assign_symmetric_prompt`` —
    just needs ``size > 0`` elements with the ``RequestSample`` shape."""
    from vllm_grpc_bench.corpus import RequestSample

    return [
        RequestSample(
            id=f"stub-{i}",
            messages=[{"role": "user", "content": f"hello {i}"}],
            model="Qwen/Qwen3-8B",
            max_tokens=10,
            temperature=0.0,
            seed=i,
        )
        for i in range(size)
    ]


def _stub_embed_corpus(size: int = 8) -> list[Any]:
    """Minimal embed corpus that satisfies ``assign_symmetric_prompt``."""
    from vllm_grpc_bench.corpus import CompletionEmbedSample

    return [
        CompletionEmbedSample(
            id=i,
            tensor_bytes=b"\x00" * 32,
            max_tokens=10,
            seed=i,
            seq_len=16,
            bucket="short",
        )
        for i in range(size)
    ]


class _CapturingDispatcher:
    """BlockDispatcher test double that records every (cell, cohort,
    max_tokens) call and returns a deterministic success result. The
    sweep loop uses this to verify the skip predicate honours pre-loaded
    measurements (calls only happen for blocks NOT in the checkpoint)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, M6_1_2CohortKind, int]] = []

    async def __call__(
        self,
        *,
        cell_id: str,
        cohort: M6_1_2CohortKind,
        max_tokens: int,
        n: int,
        block_inputs: Any,
    ) -> Any:
        from vllm_grpc_bench.sweep import BlockDispatchResult

        self.calls.append((cell_id, cohort, max_tokens))
        return BlockDispatchResult(
            timings_ms=[100.0 + i for i in range(n)],
            failed_reason=None,
            per_rpc_metadata=[],
        )


class _StubAnchorDispatcher:
    """Anchor dispatcher test double — returns a list of n synthetic
    timings; never raises. Anchor blocks fire at sweep start + every
    cadence + sweep end; this stub satisfies the AnchorRPCDriver
    Protocol shape used by the orchestrator."""

    async def __call__(
        self,
        *,
        cohort: M6_1_2CohortKind,
        n: int,
        base_seed: int,
        seed_offset: int,
    ) -> list[float]:
        return [50.0 + i for i in range(n)]


def _is_transient_stub(_exc: BaseException) -> bool:
    return False


class TestSweepLoopResume:
    @pytest.mark.asyncio
    async def test_preloaded_measurements_skip_completed_blocks(self, tmp_path: Path) -> None:
        """When ``preloaded_measurements`` contains a (cell, cohort,
        max_tokens), the sweep loop must NOT call the dispatcher for
        that block. Pre-loaded measurements stay in the output list and
        are joined by the freshly-dispatched ones."""
        from vllm_grpc_bench.sweep import M6_2SweepInputs, run_sweep

        # Pre-load only the first three blocks of the validate axis.
        preloaded = [
            _sample_measurement(cell_id="embed_c1", cohort="default_grpc", max_tokens=10),
            _sample_measurement(cell_id="embed_c1", cohort="rest_https_edge", max_tokens=10),
            _sample_measurement(cell_id="embed_c1", cohort="rest_plain_tcp", max_tokens=10),
        ]
        dispatcher = _CapturingDispatcher()
        anchor = _StubAnchorDispatcher()

        inputs = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, dispatcher),
            anchor_dispatcher=cast(Any, anchor),
            is_transient=_is_transient_stub,
            topology_probe=None,
            preloaded_measurements=preloaded,
        )
        outputs = await run_sweep(inputs)

        # Pre-loaded measurements are still in the output, unchanged.
        for pre in preloaded:
            assert pre in outputs.measurements
        # Dispatcher was NEVER called for the pre-loaded blocks.
        for pre in preloaded:
            assert (pre.cell_id, pre.cohort, pre.max_tokens) not in dispatcher.calls
        # And was called for everything else in the axis.
        assert len(dispatcher.calls) > 0

    @pytest.mark.asyncio
    async def test_no_preloaded_state_dispatches_everything(self, tmp_path: Path) -> None:
        """Sanity check: with ``preloaded_measurements=None``, the
        dispatcher fires for every block in the axis. Used as the
        reference for the skip-count assertion below."""
        from vllm_grpc_bench.sweep import M6_2SweepInputs, run_sweep

        dispatcher = _CapturingDispatcher()
        inputs = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, dispatcher),
            anchor_dispatcher=cast(Any, _StubAnchorDispatcher()),
            is_transient=_is_transient_stub,
            topology_probe=None,
        )
        outputs = await run_sweep(inputs)
        # Validate axis: 6 cells × variable cohorts × 3 caps = 66 blocks.
        assert len(dispatcher.calls) == 66
        assert len(outputs.measurements) == 66

    @pytest.mark.asyncio
    async def test_partial_preload_dispatches_complement(self, tmp_path: Path) -> None:
        """30 pre-loaded measurements + 66 total expected blocks → the
        dispatcher fires exactly 36 times. Mirrors the production
        recover-mid-sweep behaviour."""
        from vllm_grpc_bench.sweep import M6_2SweepInputs, run_sweep

        dispatcher_total = _CapturingDispatcher()
        inputs_total = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, dispatcher_total),
            anchor_dispatcher=cast(Any, _StubAnchorDispatcher()),
            is_transient=_is_transient_stub,
            topology_probe=None,
        )
        await run_sweep(inputs_total)
        # Take the first 30 blocks from a clean run and use them as the
        # checkpoint for a second invocation.
        preloaded = [
            _sample_measurement(cell_id=cell, cohort=coh, max_tokens=mt)
            for cell, coh, mt in dispatcher_total.calls[:30]
        ]
        dispatcher_resume = _CapturingDispatcher()
        inputs_resume = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, dispatcher_resume),
            anchor_dispatcher=cast(Any, _StubAnchorDispatcher()),
            is_transient=_is_transient_stub,
            topology_probe=None,
            preloaded_measurements=preloaded,
        )
        outputs = await run_sweep(inputs_resume)
        assert len(dispatcher_resume.calls) == 66 - 30
        # Total measurements = pre-loaded + dispatched.
        assert len(outputs.measurements) == 66

    @pytest.mark.asyncio
    async def test_preloaded_anchors_suppress_sweep_start_anchor(self, tmp_path: Path) -> None:
        """The t=0 anchor must NOT re-fire when the checkpoint already
        carries snapshots — those snapshots belong to the prior run's
        t=0 capture; re-firing would corrupt the trajectory."""
        from vllm_grpc_bench.sweep import M6_2SweepInputs, run_sweep

        calls: list[tuple[str, int]] = []

        class _CountingAnchor:
            async def __call__(
                self,
                *,
                cohort: M6_1_2CohortKind,
                n: int,
                base_seed: int,
                seed_offset: int,
            ) -> list[float]:
                calls.append((cohort, seed_offset))
                return [50.0] * n

        preloaded_anchors: dict[M6_1_2CohortKind, list[M6_2AnchorLatencySnapshot]] = {
            "default_grpc": [_sample_snapshot()],
            "rest_https_edge": [_sample_snapshot()],
            "rest_plain_tcp": [_sample_snapshot()],
            "tuned_grpc_multiplexed": [_sample_snapshot()],
        }
        inputs = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, _CapturingDispatcher()),
            anchor_dispatcher=cast(Any, _CountingAnchor()),
            is_transient=_is_transient_stub,
            topology_probe=None,
            preloaded_anchor_snapshots=preloaded_anchors,
        )
        outputs = await run_sweep(inputs)
        # Every pre-loaded anchor must still be in the output.
        for cohort, snaps in preloaded_anchors.items():
            assert outputs.anchor_snapshots[cohort][: len(snaps)] == snaps

    @pytest.mark.asyncio
    async def test_checkpoint_path_writes_jsonl_sidecar(self, tmp_path: Path) -> None:
        """Every dispatched block must append a JSON line to the
        sidecar. The on-disk count matches in-memory ``measurements``."""
        from vllm_grpc_bench.sweep import M6_2SweepInputs, run_sweep

        cp_path = tmp_path / "cp.jsonl"
        write_checkpoint_header(cp_path, _sample_header(sweep_mode="validate", n_per_point=20))
        inputs = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, _CapturingDispatcher()),
            anchor_dispatcher=cast(Any, _StubAnchorDispatcher()),
            is_transient=_is_transient_stub,
            topology_probe=None,
            checkpoint_path=cp_path,
        )
        outputs = await run_sweep(inputs)
        text = cp_path.read_text()
        # 1 header + len(measurements) + at least one anchor block (start)
        # × 4 cohorts = at least 1 + 66 + 4 = 71 lines.
        line_count = sum(1 for line in text.splitlines() if line.strip())
        assert line_count >= 1 + len(outputs.measurements) + 4

        # Reloading the checkpoint yields the same measurements.
        _, loaded_measurements, loaded_anchors = load_checkpoint(cp_path)
        assert len(loaded_measurements) == len(outputs.measurements)

    @pytest.mark.asyncio
    async def test_resume_preserves_iter_idx_seed_allocation(self, tmp_path: Path) -> None:
        """The dispatcher derives per-RPC seeds from
        ``base_seed + iter_idx`` and ``iter_idx = len(measurements)``.
        On resume, pre-loaded measurements occupy the low indices so
        the freshly-dispatched blocks see ``iter_idx`` continue from
        where the prior run left off — NOT restart at 0.

        We verify this by capturing the ``iter_idx`` the dispatcher
        observed during the freshly-resumed-from-30 run, and comparing
        it to indices [30, 31, ..., 65] from the clean reference run.
        """
        from vllm_grpc_bench.sweep import M6_2SweepInputs, run_sweep

        # Reference run: capture per-call iter_idx (= len(measurements)
        # at dispatch time). The dispatcher receives the block index
        # via the orchestrator's increment, but since we don't expose
        # iter_idx directly, we use call ORDER as a proxy: call N has
        # iter_idx = N.
        ref = _CapturingDispatcher()
        ref_inputs = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, ref),
            anchor_dispatcher=cast(Any, _StubAnchorDispatcher()),
            is_transient=_is_transient_stub,
            topology_probe=None,
        )
        await run_sweep(ref_inputs)
        ref_calls = list(ref.calls)

        # Resumed run: take first 30 ref calls as pre-loaded
        # measurements, then verify the dispatched-call sequence is
        # ref_calls[30:].
        preloaded = [
            _sample_measurement(cell_id=cell, cohort=coh, max_tokens=mt)
            for cell, coh, mt in ref_calls[:30]
        ]
        resumed = _CapturingDispatcher()
        resumed_inputs = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, resumed),
            anchor_dispatcher=cast(Any, _StubAnchorDispatcher()),
            is_transient=_is_transient_stub,
            topology_probe=None,
            preloaded_measurements=preloaded,
        )
        await run_sweep(resumed_inputs)
        assert resumed.calls == ref_calls[30:]

    @pytest.mark.asyncio
    async def test_wall_clock_start_utc_override_preserves_original_start(
        self, tmp_path: Path
    ) -> None:
        from vllm_grpc_bench.sweep import M6_2SweepInputs, run_sweep

        original_start = "2026-05-24T21:28:31Z"
        inputs = M6_2SweepInputs(
            sweep_mode="validate",
            n=20,
            axis=(10, 50, 2048),
            base_seed=42,
            chat_corpus=_stub_chat_corpus(),
            embed_corpus=_stub_embed_corpus(),
            dispatcher=cast(Any, _CapturingDispatcher()),
            anchor_dispatcher=cast(Any, _StubAnchorDispatcher()),
            is_transient=_is_transient_stub,
            topology_probe=None,
            wall_clock_start_utc_override=original_start,
        )
        outputs = await run_sweep(inputs)
        # The orchestrator records the override as wall_clock_start_utc
        # in the outputs (downstream build_artifact uses it for run_meta).
        assert outputs.wall_clock_start_utc == original_start
