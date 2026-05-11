"""M5 supersedes-M4 table builder (FR-015 / FR-017).

Reads M4's published ``m4-time-axis-tuning.json`` plus an in-memory ``Run``
and emits a ``SupersedesM4Entry`` for every M4 cell where either:

* ``loopback_caveat == True`` on the M4 side (these are the cells M5 exists
  to resolve), or
* the M5 verdict differs from the M4 verdict on either the time metric or
  the bytes metric.

``expected_class`` classifies each row per a five-value taxonomy that
extends the original four values from ``data-model.md``:

* ``verdict_confirmed`` — verdicts match on both metrics (still recorded so
  loopback-caveat resolution is traceable).
* ``loopback_resolution`` — M4 had ``loopback_caveat == True`` AND verdict
  changed. The headline M5 case.
* ``transport_resolution`` — axis is ``keepalive`` / ``http2_framing`` AND
  M4 had no loopback caveat AND verdict changed (real-RTT effect M4 missed
  for reasons other than the loopback caveat).
* ``bound_classifier_transition`` — verdict change is explained by the
  boundedness classifier moving (M4 ``client_bound`` / ``noise_bounded`` →
  M5 unbound, or M5 ``server_bound`` firing on a cell M4 couldn't classify).
  These are methodology-driven transitions, not real disagreements; M5's
  verdict is the more defensible one. See ``_classify_expected`` for the
  precise detection criterion.
* ``unexpected_supersession`` — axis is ``max_message_size`` /
  ``compression`` AND verdict changed AND the change is *not* a
  bound-classifier transition. Genuine surprise; reader should investigate
  before adopting.

For verdict-changed entries on the time metric, ``citations`` is populated
with structured cross-references into the cloned vLLM / grpcio source
trees (FR-017). Citation discovery is driven by a small per-axis hint
table — see ``_axis_citations`` below.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m3_types import (
    Citation,
    ExpectedClass,
    Path_,
    Run,
    SupersedesM4Entry,
    Verdict,
)


def _axis_citations(axis: str) -> tuple[Citation, ...]:
    """Per-axis ground-truth citations for time-metric verdict changes (FR-017).

    Static table sourced via the M2 ground-truth workflow (CLAUDE.md
    navigation rules). Time-metric supersessions on each axis are most often
    explained by the cited source location, so the same citations apply to
    every row on the same axis. Future enhancements can substitute
    cohort-specific citations sourced via ``cross-repo.json`` queries.
    """
    if axis == "keepalive":
        return (
            Citation(
                repo="grpc/grpc",
                file_path="src/core/ext/transport/chttp2/transport/chttp2_transport.cc",
                identifier="keepalive_watchdog_fired_locked",
                justification=(
                    "HTTP/2 keepalive ping/timeout state machine — only "
                    "exercised under non-loopback RTT"
                ),
            ),
        )
    if axis == "http2_framing":
        return (
            Citation(
                repo="grpc/grpc",
                file_path="src/core/ext/transport/chttp2/transport/flow_control.cc",
                identifier=None,
                justification=(
                    "HTTP/2 flow-control state machine; BDP probing depends on "
                    "real-RTT round-trip observations"
                ),
            ),
            Citation(
                repo="grpc/grpc",
                file_path="src/core/lib/transport/bdp_estimator.cc",
                identifier=None,
                justification="BDP estimator drives window-update cadence under real RTT",
            ),
        )
    if axis == "compression":
        return (
            Citation(
                repo="grpc/grpc",
                file_path="src/python/grpcio/grpc/_channel.py",
                identifier=None,
                justification=(
                    "Python-side compression argument plumbing; compression's "
                    "CPU/wire trade-off changes shape under real-RTT framing"
                ),
            ),
            Citation(
                repo="grpc/grpc",
                file_path="src/core/ext/transport/chttp2/transport/frame_data.cc",
                identifier=None,
                justification="frame-level data compression handling",
            ),
        )
    if axis == "max_message_size":
        return (
            Citation(
                repo="grpc/grpc",
                file_path="src/python/grpcio/grpc/_channel.py",
                identifier=None,
                justification=(
                    "channel-args max_message_size plumbing; fragmentation "
                    "behavior changes under non-loopback transports"
                ),
            ),
        )
    return ()


_BOUND_VERDICTS: frozenset[str] = frozenset({"client_bound", "noise_bounded", "server_bound"})


def _classify_expected(
    axis: str,
    m4_loopback_caveat: bool,
    verdict_changed: bool,
    m4_verdict_time: str = "no_winner",
    m5_verdict_time: str = "no_winner",
) -> ExpectedClass:
    """Five-value classifier (extends the original spec Edge Cases taxonomy).

    The fifth value, ``bound_classifier_transition``, captures verdict changes
    that are explained by the *boundedness classifier* moving rather than by a
    real transport-layer effect or a measurement-noise artifact. Two
    structural patterns hit this class on the M5/M4 join:

    * ``client_bound → recommend/no_winner`` — M4 emitted ``client_bound``
      when the candidate delta sat below the baseline's own per-RPC jitter
      floor (a loopback measurement artifact). On real-wire transport that
      jitter floor is no longer the limit (RTT dominates by ~3 orders of
      magnitude), so M5 sees the CI honestly. The verdict literally changed
      but the *information* is the same — M5's verdict is the more defensible
      one.
    * ``no_winner → server_bound`` — M5's R-4 classifier detects cells where
      remote-server overhead dominates transport. M4 structurally cannot fire
      this classifier (loopback's "server" is the same process as the
      client), so this transition is methodology-driven, not data-driven.

    Without the new class, both patterns end up in ``unexpected_supersession``
    where they incorrectly prime the reader to "investigate before adopting."
    The bound-classifier transitions don't need investigation — they're
    explainable and M5's verdict is the right one.

    Detection criterion (precise): the M4 time-metric verdict is in
    ``{client_bound, noise_bounded}`` and the M5 verdict is not, OR the M5
    verdict is ``server_bound`` and the M4 verdict is not. This is checked
    before the ``transport_resolution`` / ``unexpected_supersession``
    branches so the new class wins on the cells it applies to.
    """
    if not verdict_changed:
        return "verdict_confirmed"
    if m4_loopback_caveat:
        return "loopback_resolution"
    m4_was_client_or_noise_bound = m4_verdict_time in {"client_bound", "noise_bounded"}
    m5_no_longer_bound = m5_verdict_time not in _BOUND_VERDICTS
    m5_fired_server_bound = m5_verdict_time == "server_bound" and m4_verdict_time != "server_bound"
    if (m4_was_client_or_noise_bound and m5_no_longer_bound) or m5_fired_server_bound:
        return "bound_classifier_transition"
    if axis in ("keepalive", "http2_framing"):
        return "transport_resolution"
    return "unexpected_supersession"


def _verdicts_match(a: str, b: str) -> bool:
    return a == b


def _build_rationale(
    *,
    axis: str,
    m4_path: Path_,
    width: int,
    m4_v_time: str,
    m5_v_time: str,
    m4_v_bytes: str,
    m5_v_bytes: str,
    m5_ci_low: float,
    m5_ci_high: float,
    m4_loopback: bool,
    verdict_changed: bool,
    expected_class: ExpectedClass = "verdict_confirmed",
) -> str:
    if not verdict_changed and m4_loopback:
        return (
            f"M5 confirms M4's {m4_v_time}/{m4_v_bytes} verdict for "
            f"{axis} at hidden_size {width} on {m4_path}, resolving the "
            f"M4 loopback caveat with cross-host transport"
        )
    if not verdict_changed:
        return (
            f"M5 confirms M4's {m4_v_time}/{m4_v_bytes} verdict for "
            f"{axis} at hidden_size {width} on {m4_path}"
        )
    parts: list[str] = []
    if not _verdicts_match(m4_v_time, m5_v_time):
        parts.append(f"time-metric verdict changed from {m4_v_time!r} to {m5_v_time!r}")
    if not _verdicts_match(m4_v_bytes, m5_v_bytes):
        parts.append(f"bytes-metric verdict changed from {m4_v_bytes!r} to {m5_v_bytes!r}")
    delta_descr = f" (M5 CI=[{m5_ci_low:.4g}, {m5_ci_high:.4g}])"
    # Tailor the explanation by classifier-class so the reader gets the
    # right framing: loopback caveat resolved, classifier-transition
    # explained, or genuine real-wire disagreement worth investigating.
    if expected_class == "loopback_resolution":
        reason = "real RTT exposed an effect M4 could not measure on loopback"
    elif expected_class == "bound_classifier_transition":
        if m4_v_time in {"client_bound", "noise_bounded"} and m5_v_time not in _BOUND_VERDICTS:
            reason = (
                "M4's client-side classifier was a loopback jitter-floor "
                "artifact; on real wire the jitter floor is dominated by RTT, "
                "so M5 sees the CI honestly — M5's verdict is the more "
                "defensible one"
            )
        elif m5_v_time == "server_bound":
            reason = (
                "M5's R-4 classifier detected remote-server overhead "
                "dominating transport — a classification M4 structurally "
                "cannot fire on loopback (same-process server)"
            )
        else:
            reason = "boundedness classifier moved between M4 and M5"
    elif expected_class == "transport_resolution":
        reason = (
            "RTT-bounded axis effect surfaced on real wire that M4's "
            "loopback measurement could not exercise"
        )
    else:  # unexpected_supersession
        reason = "M5 disagrees with M4 under real-wire transport"
    return f"{'; '.join(parts)}{delta_descr}: {reason}"


def build_supersedes_m4_table(run: Run, m4_report_path: Path) -> list[SupersedesM4Entry]:
    """Build the ``Run.supersedes_m4`` list by joining M4's published cells
    against the M5 ``Run``'s recommendations.
    """
    if not m4_report_path.exists():
        return []
    try:
        payload = json.loads(m4_report_path.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    # Index M4 cells by (axis, path, width).
    m4_cells: dict[tuple[str, str, int], dict[str, Any]] = {}
    m4_recs = payload.get("recommendations", [])
    for rec in m4_recs:
        axis = str(rec.get("axis", ""))
        path = str(rec.get("applies_to_path", ""))
        widths_list = rec.get("applies_to_widths", []) or []
        for w in widths_list:
            try:
                width = int(w)
            except (TypeError, ValueError):
                continue
            m4_cells[(axis, path, width)] = {
                "verdict": str(rec.get("verdict", "no_winner")),
                "config_name": rec.get("winning_config"),
            }

    # M4 loopback-caveat axes from the report.
    loopback_axes = set(payload.get("loopback_caveat_axes", []) or [])

    # Index M5 recommendations by the same key.
    m5_recs: dict[tuple[str, str, int], dict[str, Any]] = {}
    for rec in run.recommendations:
        for w in rec.applies_to_widths:
            key = (rec.axis, rec.applies_to_path, int(w))
            m5_recs[key] = {
                "verdict_time": rec.verdict,
                "ci_lower": rec.candidate_ci_lower if rec.candidate_ci_lower is not None else 0.0,
                "ci_upper": rec.baseline_ci_upper,
            }

    # For bytes verdicts on the M5 side we don't currently emit a separate
    # rec per metric (the M5 recommendation builder is time/TTFT-first);
    # populate with "no_winner" so verdict_changed is computed conservatively
    # on the bytes axis. Future revisions can split bytes verdicts out.
    entries: list[SupersedesM4Entry] = []
    for (axis, path, width), m4_cell in m4_cells.items():
        if path not in ("embed", "chat_stream"):
            continue
        m5_cell = m5_recs.get((axis, path, width))
        m4_loopback = axis in loopback_axes
        m4_v_time: str = m4_cell["verdict"]
        # We don't have separate M4 bytes verdicts in the published shape; the
        # M4 recommendation builder is the same for time-axis cells, so we
        # treat the recorded verdict as the time-metric verdict and use
        # "no_winner" as the bytes placeholder. The supersession-changed
        # logic still triggers on time-metric changes (the headline M5 case).
        m4_v_bytes = "no_winner"
        if m5_cell is None:
            # M5 didn't measure this M4 cell. Skip — supersession requires
            # both sides to exist (per task T056 note).
            if m4_loopback:
                # Loopback-caveat cell with no M5 counterpart: record an
                # entry so the reader can see the unresolved caveat.
                entry = SupersedesM4Entry(
                    m4_axis=axis,
                    m4_hidden_size=width,
                    m4_path=path,  # type: ignore[arg-type]
                    m4_verdict_time=_safe_verdict(m4_v_time),
                    m4_verdict_bytes=_safe_verdict(m4_v_bytes),
                    m4_loopback_caveat=True,
                    m5_verdict_time=_safe_verdict(m4_v_time),
                    m5_verdict_bytes=_safe_verdict(m4_v_bytes),
                    m5_supporting_ci_lower=0.0,
                    m5_supporting_ci_upper=0.0,
                    rationale=(
                        f"M5 did not measure {axis}/h{width}/{path} — M4 "
                        "loopback caveat remains unresolved on this cell"
                    ),
                    expected_class="loopback_resolution",
                )
                entries.append(entry)
            continue

        m5_v_time: str = m5_cell["verdict_time"]
        m5_v_bytes = "no_winner"
        time_changed = m4_v_time != m5_v_time
        bytes_changed = m4_v_bytes != m5_v_bytes
        verdict_changed = time_changed or bytes_changed
        expected = _classify_expected(
            axis,
            m4_loopback,
            verdict_changed,
            m4_verdict_time=m4_v_time,
            m5_verdict_time=m5_v_time,
        )
        ci_lower = float(m5_cell.get("ci_lower") or 0.0)
        ci_upper = float(m5_cell.get("ci_upper") or 0.0)
        if ci_lower > ci_upper:
            # The Recommendation stores negated CIs for minimizing metrics;
            # swap so the entry's invariant holds.
            ci_lower, ci_upper = ci_upper, ci_lower
        citations: tuple[Citation, ...] = ()
        if time_changed:
            citations = _axis_citations(axis)
        rationale = _build_rationale(
            axis=axis,
            m4_path=path,  # type: ignore[arg-type]
            width=width,
            m4_v_time=m4_v_time,
            m5_v_time=m5_v_time,
            m4_v_bytes=m4_v_bytes,
            m5_v_bytes=m5_v_bytes,
            m5_ci_low=ci_lower,
            m5_ci_high=ci_upper,
            m4_loopback=m4_loopback,
            verdict_changed=verdict_changed,
            expected_class=expected,
        )
        # Emit a supersession row when:
        #   (a) M4 had loopback_caveat=True (mandatory per FR-015), OR
        #   (b) verdict changed on either metric.
        if not (m4_loopback or verdict_changed):
            continue
        entries.append(
            SupersedesM4Entry(
                m4_axis=axis,
                m4_hidden_size=width,
                m4_path=path,  # type: ignore[arg-type]
                m4_verdict_time=_safe_verdict(m4_v_time),
                m4_verdict_bytes=_safe_verdict(m4_v_bytes),
                m4_loopback_caveat=m4_loopback,
                m5_verdict_time=_safe_verdict(m5_v_time),
                m5_verdict_bytes=_safe_verdict(m5_v_bytes),
                m5_supporting_ci_lower=ci_lower,
                m5_supporting_ci_upper=ci_upper,
                rationale=rationale,
                expected_class=expected,
                citations=citations,
            )
        )
    return entries


def _safe_verdict(v: str) -> Verdict:
    """Coerce a string verdict into the typed literal; default to ``no_winner``
    when the string doesn't match a known literal. Keeps the dataclass
    construction permissive against unknown M4-report variants.
    """
    if v in (
        "recommend",
        "no_winner",
        "not_measurable",
        "noise_bounded",
        "client_bound",
        "server_bound",
    ):
        return v  # type: ignore[return-value]
    return "no_winner"
