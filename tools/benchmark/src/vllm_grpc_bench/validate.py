"""M6.2 — single CLI entry function for both ``--m6_2`` and ``--m6_2-validate``.

Mirrors :mod:`m6_1_3_validate`'s R-7 + round-2 Q2 dispatch shape: both
top-level mode flags ship the same sweep shape; one entry function handles
both. The operator-intent distinction lives in the ``sweep_mode:
Literal["publish", "validate"]`` argument and is recorded in
``run_meta.sweep_mode`` on the published artifact.

Output paths per FR-015 (R-7 inheritance):

* ``--m6_2-validate`` (any modifier shape) →
  ``docs/benchmarks/m6_2-token-budget-validate.{md,json}``.
* ``--m6_2`` (publish) →
  ``docs/benchmarks/m6_2-token-budget.{md,json}``.
* Explicit ``--m6_2-report-out`` / ``--m6_2-report-json-out`` overrides
  take precedence regardless of mode.

Per ``contracts/cli.md`` exit codes:

* ``0`` — sweep completed; artifact written.
* ``2`` — Modal deploy / handshake failure.
* ``3`` — engine version mismatch and ``--m6_2-allow-engine-mismatch``
  not set (reserved; not exercised in the Foundational/US1 scope).
* ``4`` — sweep aborted by user (Ctrl-C; reserved).
* ``5`` — sweep failed mid-run; partial artifact may exist.
* ``6`` — corpus SHA drift detected at sweep start (SC-018).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import grpc
import httpx

from vllm_grpc_bench.corpus import (
    CompletionEmbedSample,
    RequestSample,
)
from vllm_grpc_bench.m6_2_crossover import M6_1_3CohortBaseline
from vllm_grpc_bench.sweep_types import (
    M6_2_NULL_ANCHOR_MAX_TOKENS,
    M6_2_VALIDATE_MAX_TOKENS_AXIS,
    M6_2NullAnchor,
    M6_2RunMeta,
    M6_2SweepArtifact,
    M6_2SweepMode,
)
from vllm_grpc_bench.types import CELLS, COHORTS, Cell, CohortKind

__all__ = [
    "M6_2_ENDPOINT_DEATH_CONSECUTIVE_THRESHOLD",
    "M6_2_PREEMPTION_RECURRENCE_THRESHOLD",
    "PreemptionBudgetExhausted",
    "PreemptionRecoveryFailed",
    "block_failed_with_endpoint_death",
    "block_has_endpoint_death",
    "build_artifact",
    "build_modal_anchor_dispatcher",
    "build_modal_block_dispatcher",
    "build_modal_make_driver_callable",
    "build_stub_anchor_dispatcher",
    "build_stub_dispatcher",
    "derive_anchor_baseline_p50_ms",
    "derive_anchor_drift_threshold",
    "infer_output_path",
    "is_modal_endpoint_death",
    "is_modal_endpoint_death_reason",
    "is_transient_modal_error",
    "load_m6_1_3_baseline",
    "make_null_anchor_validation",
    "run_m6_2",
]


# --- Output-path inference (FR-015 + R-7 inheritance) ----------------------

_VALIDATE_MD = "docs/benchmarks/m6_2-token-budget-validate.md"
_VALIDATE_JSON = "docs/benchmarks/m6_2-token-budget-validate.json"
_CANONICAL_MD = "docs/benchmarks/m6_2-token-budget.md"
_CANONICAL_JSON = "docs/benchmarks/m6_2-token-budget.json"


def infer_output_path(
    args: argparse.Namespace,
    *,
    kind: Literal["md", "json"],
) -> str:
    """Resolve the M6.2 artifact output path per FR-015.

    Explicit ``--m6_2-report-out`` (md) or ``--m6_2-report-json-out`` (json)
    overrides take precedence; otherwise the path defaults to the
    canonical (publish) or validate sibling.
    """
    explicit_md = getattr(args, "m6_2_report_out", None)
    explicit_json = getattr(args, "m6_2_report_json_out", None)
    if kind == "md" and explicit_md is not None:
        return str(explicit_md)
    if kind == "json" and explicit_json is not None:
        return str(explicit_json)

    sweep_mode: M6_2SweepMode = "validate" if getattr(args, "m6_2_validate", False) else "publish"
    if sweep_mode == "validate":
        return _VALIDATE_MD if kind == "md" else _VALIDATE_JSON
    return _CANONICAL_MD if kind == "md" else _CANONICAL_JSON


def _resolve_axis(sweep_mode: M6_2SweepMode) -> tuple[int, ...]:
    """Validate mode uses the 3-point subset per FR-001 round-1 Q2; publish
    uses the full 6-point axis."""
    from vllm_grpc_bench.sweep_types import M6_2_MAX_TOKENS_AXIS

    return M6_2_VALIDATE_MAX_TOKENS_AXIS if sweep_mode == "validate" else M6_2_MAX_TOKENS_AXIS


# --- Stub dispatcher for --m6_2-skip-deploy / tests ------------------------


def _stub_seed(cell_id: str, cohort: str, max_tokens: int) -> int:
    """Stable hash → int for deterministic per-block stub latency synthesis."""
    return abs(hash((cell_id, cohort, max_tokens))) % (2**31)


def build_stub_dispatcher() -> object:
    """Return a deterministic stub :class:`BlockDispatcher` for tests and
    ``--m6_2-skip-deploy`` invocations.

    Emits a list of ``n`` per-block timings shaped by the cell concurrency,
    cohort, and max_tokens — enough variance for the artifact assembler to
    compute non-degenerate percentiles. Returns an object whose
    ``__call__`` matches the :class:`BlockDispatcher` Protocol.
    """
    from vllm_grpc_bench.sweep import BlockDispatchResult

    class _StubDispatcher:
        async def __call__(
            self,
            *,
            cell_id: str,
            cohort: str,
            max_tokens: int,
            n: int,
            block_inputs: object,
        ) -> BlockDispatchResult:
            del block_inputs  # not used in the stub
            seed = _stub_seed(cell_id, cohort, max_tokens)
            base = 50.0 + (max_tokens / 50.0) * 8.0  # rough cap scaling
            cohort_bias = (abs(hash(cohort)) % 17) * 1.3
            concurrency_bias = 1.4 if "c8" in cell_id else (1.2 if "c4" in cell_id else 1.0)
            timings = [
                (base + cohort_bias) * concurrency_bias + ((seed + i * 9973) % 1000) / 100.0
                for i in range(n)
            ]
            return BlockDispatchResult(
                timings_ms=timings,
                failed_reason=None,
                per_rpc_metadata=[],
            )

    return _StubDispatcher()


def build_stub_anchor_dispatcher() -> object:
    """Return a deterministic stub :class:`AnchorRPCDriver` (async)."""

    async def _stub_anchor(*, cohort: str, n: int, base_seed: int, seed_offset: int) -> list[float]:
        del seed_offset
        base = 60.0 + (base_seed % 17) * 0.5
        cohort_bias = (abs(hash(cohort)) % 13) * 1.1
        return [base + cohort_bias + (i % 7) * 0.3 for i in range(n)]

    return _stub_anchor


def _stub_is_transient(exc: BaseException) -> bool:  # noqa: ARG001 - kept for protocol shape
    """Stub retry classifier: never retries (errors fail the block immediately).

    Tests can override this with a more interesting predicate; the default
    matches the validate-mode behavior where transient retry is a publish-time
    concern."""
    return False


# --- Real (Modal-backed) classifier + dispatchers --------------------------


_GRPC_TRANSIENT_CODES = frozenset(
    {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.ABORTED,
        grpc.StatusCode.INTERNAL,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
    }
)
"""gRPC status codes treated as transient by :func:`is_transient_modal_error`.

* ``UNAVAILABLE`` — connection reset, Modal frontend restart.
* ``DEADLINE_EXCEEDED`` — RPC slow but not necessarily wedged.
* ``ABORTED`` — tunnel-level transient.
* ``INTERNAL`` — most often a Modal-side transient at high concurrency.
* ``RESOURCE_EXHAUSTED`` — KV / scheduler back-pressure that may pass with
  a retry once the in-flight RPC drains.

``UNAUTHENTICATED`` / ``PERMISSION_DENIED`` / ``INVALID_ARGUMENT`` are
explicitly NOT transient (configuration or input bugs)."""


def is_transient_modal_error(exc: BaseException) -> bool:
    """FR-033 in-window retry classifier for the real Modal dispatch path.

    Returns ``True`` on transient network-shaped errors (gRPC code in
    :data:`_GRPC_TRANSIENT_CODES`, httpx transport errors / timeouts),
    ``False`` otherwise. ``False`` is the safe default — non-transient
    exceptions fail the block once, preserving FR-033's "retry exactly once,
    in-window" contract.
    """
    if isinstance(exc, grpc.RpcError):
        try:
            code = exc.code()
        except AttributeError:
            return False
        return code in _GRPC_TRANSIENT_CODES
    return isinstance(
        exc,
        httpx.TransportError | httpx.TimeoutException | httpx.RemoteProtocolError,
    )


# T074a — Modal-preemption mid-sweep detection ------------------------------
#
# These signatures were observed in the 2026-05-24 13:44 UTC validate run
# during the post-14:58 cascade after Modal preempted the worker container:
#
#   gRPC : "StatusCode.UNAVAILABLE failed to connect to all addresses;
#           last error: UNKNOWN: ipv4:<old_modal_ip>:<port>: F[ailed to ...]"
#   REST : httpx.ConnectError("All connection attempts failed")
#   REST : httpx.ReadError(...)               # streaming read died mid-RPC
#   REST : httpx.ConnectError(
#               "[Errno 8] nodename nor servname provided, or not known")
#                                             # DNS lookup of dead endpoint
#
# The block dispatcher uses :func:`is_modal_endpoint_death` together with
# the "all N RPCs in this block failed" predicate to decide whether to
# trigger T074b's mid-sweep recovery path. A single endpoint-death exception
# in isolation could just be a transient connection blip; preemption is
# diagnosed only when the WHOLE block fails with this shape (a real Modal
# preemption kills every in-flight RPC against the dead container).

_ENDPOINT_DEATH_GRPC_CODES: frozenset[grpc.StatusCode] = frozenset(
    {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.CANCELLED}
)
"""gRPC status codes consistent with the underlying Modal container having
disappeared. ``UNAVAILABLE`` is the dominant signal (the four-tuple
"failed to connect to all addresses" pattern); ``CANCELLED`` shows up when
the gRPC channel itself gives up mid-call after the connection dies."""


_ENDPOINT_DEATH_MESSAGE_FRAGMENTS: tuple[str, ...] = (
    "failed to connect to all addresses",
    "all connection attempts failed",
    "nodename nor servname provided",
    "name or service not known",
    "connection refused",
    "connection reset by peer",
    "no route to host",
    "broken pipe",
)
"""Lower-cased substrings of error messages that indicate the remote
endpoint is unreachable at the transport layer (TCP / DNS), as distinct
from a slow-but-alive endpoint (DEADLINE_EXCEEDED / TimeoutException)."""


def is_modal_endpoint_death(exc: BaseException) -> bool:
    """Return ``True`` iff ``exc`` is shaped like a dead Modal endpoint
    (worker preempted, container restarted on a different IP, DNS stale).

    Distinct from :func:`is_transient_modal_error` — the latter classifies
    *retry-eligible single-RPC errors*; this one classifies *whole-block
    failure patterns that imply the endpoint URL needs to be refreshed*.

    Recognises:

    * ``grpc.RpcError`` with ``code() in {UNAVAILABLE, CANCELLED}`` AND
      a message containing one of the transport-layer fragments listed in
      :data:`_ENDPOINT_DEATH_MESSAGE_FRAGMENTS`. The plain UNAVAILABLE
      check is intentionally LESS permissive than
      :func:`is_transient_modal_error` — DEADLINE_EXCEEDED and the other
      transient gRPC codes are alive-but-slow, not endpoint-dead.
    * ``httpx.ConnectError`` — REST connection refused / DNS failure /
      no route to host. All of these mean the cached endpoint URL no
      longer points at a live container.
    * ``httpx.ReadError`` whose payload contains an endpoint-death
      fragment — streaming response was terminated mid-stream by the
      container vanishing. (Plain ReadError without that fragment is
      classified as transient, not endpoint-dead.)

    Always returns ``False`` for non-network exceptions so that genuine
    bugs (TypeError, KeyError, etc.) don't get masked as preemption.
    """
    if isinstance(exc, grpc.RpcError):
        try:
            code = exc.code()
            details = (exc.details() or "").lower()
        except AttributeError:
            return False
        if code not in _ENDPOINT_DEATH_GRPC_CODES:
            return False
        return any(frag in details for frag in _ENDPOINT_DEATH_MESSAGE_FRAGMENTS)
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.ReadError):
        details = str(exc).lower()
        return any(frag in details for frag in _ENDPOINT_DEATH_MESSAGE_FRAGMENTS)
    return False


def is_modal_endpoint_death_reason(reason: str | None) -> bool:
    """Return ``True`` iff a recorded ``RPCResult.failure_reason`` string
    carries one of the endpoint-death message fragments.

    Some cohorts (notably ``tuned_grpc_multiplexed`` over a shared HTTP/2
    channel) catch transport-layer errors inside the RPC driver and surface
    them as ``RPCResult(success=False, failure_reason=...)`` — a non-exception
    result — instead of letting the exception escape ``asyncio.gather``.
    The 2026-05-24 publish sweep's post-mortem showed this hides the
    preemption from the original :func:`is_modal_endpoint_death` predicate,
    which only inspects raised exceptions. Matching against
    :data:`_ENDPOINT_DEATH_MESSAGE_FRAGMENTS` recovers the signal.
    """
    if not isinstance(reason, str) or not reason:
        return False
    lower = reason.lower()
    return any(frag in lower for frag in _ENDPOINT_DEATH_MESSAGE_FRAGMENTS)


def _is_endpoint_death_result(r: Any) -> bool:
    """Classify a single per-RPC result (exception OR ``RPCResult``-shaped
    record) as endpoint-death. Used by :func:`block_failed_with_endpoint_death`
    and :func:`block_has_endpoint_death`."""
    if isinstance(r, BaseException):
        return is_modal_endpoint_death(r)
    if getattr(r, "success", None) is False:
        return is_modal_endpoint_death_reason(getattr(r, "failure_reason", None))
    return False


def block_failed_with_endpoint_death(results: list[Any], n: int) -> bool:
    """Return ``True`` iff a whole block dispatched ``n`` RPCs and EVERY
    one came back as an endpoint-death failure — either a raised
    :func:`is_modal_endpoint_death` exception OR a non-exception
    ``RPCResult(success=False, failure_reason=...)`` whose ``failure_reason``
    matches :func:`is_modal_endpoint_death_reason`.

    The block dispatcher uses this predicate to decide whether to trigger
    T074's recovery path: a single endpoint-death in isolation could just
    be a transient blip absorbed by the FR-033 retry-once policy, but
    EVERY RPC in the block failing the same way indicates the underlying
    Modal container has actually disappeared and the dispatcher needs to
    swap to a refreshed endpoint before continuing.

    ``results`` is the raw ``asyncio.gather(..., return_exceptions=True)``
    output — exceptions and ``RPCResult`` objects intermixed. Returns
    ``False`` when ``len(results) != n`` (partial/over-collected batch —
    handled as a normal block failure, not a preemption) and when
    ``n <= 0`` (vacuous-truth guard — no RPCs means no signal).
    """
    if n <= 0 or len(results) != n:
        return False
    return all(_is_endpoint_death_result(r) for r in results)


def block_has_endpoint_death(results: list[Any]) -> bool:
    """Return ``True`` iff ``results`` contains at least one endpoint-death
    failure (either exception or :func:`RPCResult`-shaped failure-reason).

    Distinct from :func:`block_failed_with_endpoint_death`: this is the
    *any* predicate that feeds the secondary "two-consecutive-blocks"
    trigger in :func:`build_modal_block_dispatcher`. Partial-failure blocks
    are not by themselves a preemption signal — a single transport blip
    can land on one RPC mid-block — but two consecutive blocks with at
    least one endpoint-death apiece is a strong enough signal that the
    cached endpoint URL is stale.
    """
    return any(_is_endpoint_death_result(r) for r in results)


def _cell_from_cell_id(cell_id: str) -> Cell:
    """Resolve a cell id (e.g. ``"chat_stream_c4"``) into an :class:`Cell`."""
    for path, hidden_size, concurrency in CELLS:
        if cell_id == f"{path}_c{concurrency}":
            return Cell(path=path, hidden_size=hidden_size, concurrency=concurrency)
    raise ValueError(f"unknown M6.2 cell id {cell_id!r}; not in CELLS")


# T074c — Modal-preemption budget enforcement -------------------------------


M6_2_ENDPOINT_DEATH_CONSECUTIVE_THRESHOLD: int = 2
"""Secondary preemption trigger: when this many *consecutive* blocks each
report at least one endpoint-death failure, the dispatcher forces a
``make_driver()`` refresh even if no individual block tripped the
strict whole-block ``block_failed_with_endpoint_death`` predicate.

The 2026-05-24 publish sweep died because the ``tuned_grpc_multiplexed``
cohort's shared HTTP/2 channel surfaced connection failures as
``RPCResult(success=False, failure_reason=...)`` records mixed with
late-arriving exceptions, leaving the whole-block predicate just-barely
unsatisfied while every downstream block still failed. Two consecutive
partial-death blocks is a strong enough signal that the cached endpoint
URL is stale; one is not (could be a single transport blip).
"""


M6_2_PREEMPTION_RECURRENCE_THRESHOLD: int = 2
"""FR-026 inherits the M6.1.3 FR-028 Modal-preemption-recurrence threshold:
the sweep tolerates up to ``M6_2_PREEMPTION_RECURRENCE_THRESHOLD`` Modal-
preemption-recovery cycles before aborting. The 3rd detected preemption
raises :class:`PreemptionBudgetExhausted` so the sweep exits cleanly
rather than spinning on a Modal app that keeps getting preempted.

A "preemption-recovery cycle" is a (PREEMPTION_DETECTED, PREEMPTION_RECOVERED)
event pair against a single dead endpoint. The counter accumulates across
the whole sweep, not per-cohort or per-cell."""


class PreemptionBudgetExhausted(RuntimeError):
    """Raised by the block dispatcher when Modal preemption recovery has
    been attempted more than ``M6_2_PREEMPTION_RECURRENCE_THRESHOLD`` times
    in a single sweep. The orchestrator catches this in
    :func:`_run_modal_backed` and exits with a non-zero return code so the
    operator (or cron-monitor) sees that the sweep abandoned cleanly."""


class PreemptionRecoveryFailed(RuntimeError):
    """Raised when ``make_driver`` itself fails to produce a fresh driver
    (Modal endpoint never came back online inside the recovery timeout).
    The orchestrator treats this the same as ``PreemptionBudgetExhausted``
    — clean abort, no further block attempts."""


# T074d — Modal-side endpoint refresh factory --------------------------------


async def build_modal_make_driver_callable(
    *,
    initial_endpoints: Any,  # modal_endpoint.RESTGRPCEndpoints
    seq_len: int,
    base_seed: int,
    outer_stack: Any,  # contextlib.AsyncExitStack
    refresh_timeout_s: float = 600.0,
) -> tuple[Any, Any, Any]:
    """Build the initial M6.2 driver + a ``make_driver`` callable wired
    against ``modal_endpoint.refresh_rest_grpc_urls`` for T074b's recovery
    loop.

    Returns ``(initial_driver, make_driver, get_current_endpoints)``:

    * ``initial_driver`` — the live M6.2 driver bound to ``initial_endpoints``.
      Pass this as the first positional argument to
      :func:`build_modal_block_dispatcher`.
    * ``make_driver`` — async callable. When the block dispatcher detects
      whole-block endpoint-death, it awaits this callable. The callable
      polls the Modal handshake Dict via ``refresh_rest_grpc_urls`` for
      fresh URLs (up to ``refresh_timeout_s`` — default 600 s, covers the
      ~2–3 min Modal preemption-restart window plus headroom for the
      vLLM EngineCore + weight-load), closes the dead driver context,
      opens a new context against the refreshed URLs, and returns the
      new driver. Raises :class:`PreemptionRecoveryFailed` upstream if
      no fresh URLs appear within the timeout.
    * ``get_current_endpoints`` — sync callable returning the most-recent
      ``RESTGRPCEndpoints``. Useful for the topology probe whose
      ``handshake_dict`` would otherwise capture the stale pre-preemption
      URLs in its closure.

    The factory tracks the driver-lifecycle stack on ``outer_stack`` so
    every opened driver context is guaranteed to close cleanly at sweep
    end, even after multiple preemption recoveries.
    """
    import contextlib

    from vllm_grpc_bench.modal_endpoint import refresh_rest_grpc_urls
    from vllm_grpc_bench.rpc_driver import provide_m6_2_rpc_driver

    # Open the initial driver context. The inner stack is tracked on
    # ``outer_stack`` so any leftover driver contexts (from earlier
    # recoveries) close cleanly when the sweep exits.
    initial_inner_stack: Any = contextlib.AsyncExitStack()
    await outer_stack.enter_async_context(initial_inner_stack)
    initial_driver, _ = await initial_inner_stack.enter_async_context(
        provide_m6_2_rpc_driver(initial_endpoints, seq_len=seq_len, base_seed=base_seed)
    )

    state: dict[str, Any] = {
        "endpoints": initial_endpoints,
        "driver_stack": initial_inner_stack,
    }

    async def make_driver() -> Any:
        new_endpoints = await refresh_rest_grpc_urls(
            state["endpoints"], poll_timeout_s=refresh_timeout_s
        )
        if new_endpoints is None:
            raise RuntimeError(
                f"Modal endpoint refresh: no fresh URLs published to the "
                f"handshake Dict within {refresh_timeout_s:.0f} s. The "
                f"preempted Modal worker may have failed to restart, or "
                f"the new container's vLLM EngineCore is still initializing. "
                f"The block dispatcher will surface this as "
                f"PreemptionRecoveryFailed and the orchestrator will abort."
            )
        # Close the old driver context (best-effort — gRPC channel + httpx
        # client may already be dead, but we want their cleanup hooks to
        # run regardless).
        with contextlib.suppress(Exception):
            await state["driver_stack"].aclose()
        # Open a new driver context against the refreshed URLs and register
        # it on the outer stack so the sweep-end cleanup hits it too.
        new_inner_stack: Any = contextlib.AsyncExitStack()
        await outer_stack.enter_async_context(new_inner_stack)
        new_driver, _ = await new_inner_stack.enter_async_context(
            provide_m6_2_rpc_driver(new_endpoints, seq_len=seq_len, base_seed=base_seed)
        )
        state["driver_stack"] = new_inner_stack
        state["endpoints"] = new_endpoints
        return new_driver

    def get_current_endpoints() -> Any:
        return state["endpoints"]

    return initial_driver, make_driver, get_current_endpoints


def build_modal_block_dispatcher(
    driver: Any,  # M6_2RPCDriver — `Any` to avoid an import cycle at the type level
    *,
    base_seed: int,
    make_driver: Any = None,  # Callable[[], Awaitable[M6_2RPCDriver]] | None
    preemption_budget: int = M6_2_PREEMPTION_RECURRENCE_THRESHOLD,
    consecutive_death_threshold: int = M6_2_ENDPOINT_DEATH_CONSECUTIVE_THRESHOLD,
) -> Any:
    """Build a :class:`BlockDispatcher` that fires N concurrent RPCs via
    :func:`provide_m6_2_rpc_driver`'s driver callable.

    The dispatcher:

    * Resolves ``cell_id`` → :class:`Cell` via :func:`_cell_from_cell_id`.
    * Allocates per-RPC seeds from ``base_seed`` + the block's iteration
      index (the orchestrator already advances ``iter_idx`` by block, so we
      stripe per-RPC seeds within the block).
    * Reads ``prompt`` (chat) / ``prompt_embeds_override`` (embed) +
      ``ignore_eos`` from the :class:`ResolvedBlockInputs` produced by
      :mod:`prompts`.
    * Awaits all ``n`` RPCs in parallel via :func:`asyncio.gather`.
    * Aggregates results into :class:`BlockDispatchResult`: per-RPC wall
      times for successful RPCs, the first non-None ``failure_reason`` for
      the block (with ``no_successful_rpcs`` sentinel when every RPC failed),
      and per-RPC ``m6_1_1_timing_payload`` dicts for the segment
      decomposition.

    **T074b Modal-preemption recovery (2026-05-24)**: when ALL ``n`` RPCs
    in the block fail with :func:`is_modal_endpoint_death` shapes AND a
    ``make_driver`` callable is provided, the dispatcher emits a
    ``PREEMPTION_DETECTED`` progress event, awaits ``make_driver()`` to
    receive a fresh driver bound to the post-restart Modal endpoint,
    emits ``PREEMPTION_RECOVERED``, and retries the block once against
    the refreshed driver. After ``preemption_budget`` recovery cycles the
    dispatcher raises :class:`PreemptionBudgetExhausted` so the
    orchestrator aborts cleanly. ``make_driver=None`` (the default for
    backward compatibility) disables recovery entirely — the dispatcher
    behaves identically to the pre-T074 implementation.

    **Secondary trigger (2026-05-25 publish-sweep autopsy fix)**: when
    the whole-block predicate is *just barely* unsatisfied — e.g. the
    ``tuned_grpc_multiplexed`` cohort's shared-channel driver surfaces
    transport errors as non-exception ``RPCResult`` records mixed with
    late-arriving exceptions — but every block keeps reporting at least
    one endpoint-death failure, the dispatcher counts consecutive
    partial-death blocks. Once that count reaches
    ``consecutive_death_threshold`` (default
    :data:`M6_2_ENDPOINT_DEATH_CONSECUTIVE_THRESHOLD` = 2), the
    dispatcher forces a recovery + retry of the current block. The
    counter resets to zero on any block that finishes without an
    endpoint-death failure or whose primary trigger fires.

    The dispatcher function carries the live counters as attributes so
    the orchestrator can persist them to ``run_meta.preemption_events``::

        dispatcher.preemption_events  # int — total successful recoveries
        dispatcher.preemption_budget  # int — configured cap
    """
    from vllm_grpc_bench.prompts import ResolvedBlockInputs
    from vllm_grpc_bench.sweep import BlockDispatchResult, _progress

    # Mutable holder so the recovery loop can swap in a refreshed driver
    # without disturbing the closure semantics of the inner ``_one_rpc``.
    # ``consecutive_death_blocks`` survives across dispatcher calls so the
    # secondary "two consecutive partial-death blocks" trigger can fire.
    state = SimpleNamespace(
        driver=driver,
        preemption_events=0,
        consecutive_death_blocks=0,
    )

    async def _gather_block(
        cell: Cell,
        cohort: CohortKind,
        max_tokens: int,
        n: int,
        prompt: Any,
        prompt_embeds_override: Any,
        ignore_eos: bool,
    ) -> list[Any]:
        # In-flight RPCs MUST be bounded by cell.concurrency so the measured
        # cell reflects the load it claims to characterize. Without this
        # semaphore, all n RPCs fire simultaneously regardless of cell.c,
        # which (a) under-measures c=1/c=4 cells by accidentally batching them
        # at n-way concurrency, (b) saturates the single-worker REST shim's
        # event loop with concurrent SSE streams, inflating client-side TPOT
        # by ~44 ms/token on REST cohorts at n=20. Mirrors the M6.1.3
        # m6_1_3_sweep.py:468 pattern.
        sem = asyncio.Semaphore(cell.concurrency)

        async def _one_rpc(i: int) -> Any:
            seed = base_seed + i
            async with sem:
                return await state.driver(
                    cohort,
                    cell,
                    seed,
                    max_tokens=max_tokens,
                    ignore_eos=ignore_eos,
                    prompt=prompt,
                    prompt_embeds_override=prompt_embeds_override,
                )

        return await asyncio.gather(*[_one_rpc(i) for i in range(n)], return_exceptions=True)

    async def _dispatcher(
        *,
        cell_id: str,
        cohort: CohortKind,
        max_tokens: int,
        n: int,
        block_inputs: ResolvedBlockInputs,
    ) -> BlockDispatchResult:
        cell = _cell_from_cell_id(cell_id)
        prompt = block_inputs.get("prompt_text")
        prompt_embeds_override = block_inputs.get("embed_tensor_bytes")
        ignore_eos = bool(block_inputs.get("ignore_eos", False))

        results = await _gather_block(
            cell, cohort, max_tokens, n, prompt, prompt_embeds_override, ignore_eos
        )

        # T074b primary trigger: every RPC in the block came back as
        # endpoint-death — the Modal container is gone, refresh and
        # retry. Secondary trigger (2026-05-25 publish-sweep fix):
        # ``consecutive_death_threshold`` partial-death blocks in a row
        # ALSO trigger a refresh, even when the whole-block predicate
        # never tripped. The two triggers share one recovery branch.
        while make_driver is not None:
            primary = block_failed_with_endpoint_death(results, n)
            secondary = False
            trigger_reason: str
            if primary:
                # A clean preemption signal — reset the consecutive
                # counter so the next block starts from zero.
                state.consecutive_death_blocks = 0
                trigger_reason = "whole_block_endpoint_death"
            elif block_has_endpoint_death(results):
                state.consecutive_death_blocks += 1
                if state.consecutive_death_blocks >= consecutive_death_threshold:
                    secondary = True
                    trigger_reason = "consecutive_endpoint_death"
                    # Reset the counter on trigger so we don't refire
                    # immediately on the next partial-death block.
                    state.consecutive_death_blocks = 0
                else:
                    # Partial-death block but below threshold — return it
                    # to the caller as a normal failure-aggregation case.
                    break
            else:
                # No endpoint-death this block; reset the streak.
                state.consecutive_death_blocks = 0
                break

            if not (primary or secondary):  # pragma: no cover — defensive
                break

            if state.preemption_events >= preemption_budget:
                _progress(
                    "PREEMPTION_BUDGET_EXHAUSTED",
                    cell=cell_id,
                    cohort=cohort,
                    max_tokens=max_tokens,
                    preemption_events=state.preemption_events,
                    budget=preemption_budget,
                    trigger=trigger_reason,
                )
                raise PreemptionBudgetExhausted(
                    f"Modal preemption recurrence threshold "
                    f"({preemption_budget}) exhausted at cell={cell_id} "
                    f"cohort={cohort} max_tokens={max_tokens}; aborting sweep "
                    f"per FR-026."
                )
            attempt = state.preemption_events + 1
            _progress(
                "PREEMPTION_DETECTED",
                cell=cell_id,
                cohort=cohort,
                max_tokens=max_tokens,
                attempt=f"{attempt}/{preemption_budget}",
                trigger=trigger_reason,
            )
            t0 = asyncio.get_event_loop().time()
            try:
                state.driver = await make_driver()
            except Exception as exc:  # noqa: BLE001
                _progress(
                    "PREEMPTION_RECOVERY_FAILED",
                    cell=cell_id,
                    cohort=cohort,
                    max_tokens=max_tokens,
                    attempt=f"{attempt}/{preemption_budget}",
                    trigger=trigger_reason,
                    error=type(exc).__name__,
                )
                raise PreemptionRecoveryFailed(
                    f"make_driver() failed during preemption recovery "
                    f"at cell={cell_id} cohort={cohort} max_tokens={max_tokens}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            state.preemption_events = attempt
            _progress(
                "PREEMPTION_RECOVERED",
                cell=cell_id,
                cohort=cohort,
                max_tokens=max_tokens,
                attempt=f"{attempt}/{preemption_budget}",
                trigger=trigger_reason,
                recovery_s=f"{asyncio.get_event_loop().time() - t0:.1f}",
            )
            results = await _gather_block(
                cell,
                cohort,
                max_tokens,
                n,
                prompt,
                prompt_embeds_override,
                ignore_eos,
            )

        timings_ms: list[float] = []
        per_rpc_metadata: list[dict[str, str]] = []
        first_failure: str | None = None
        for r in results:
            if isinstance(r, BaseException):
                if first_failure is None:
                    first_failure = _classify_dispatcher_exc(r)
                continue
            # r is RPCResult-shaped (m6_sweep.RPCResult). Avoid an isinstance
            # check on RPCResult to keep this dispatcher framework-agnostic for
            # the integration test's fake driver.
            if getattr(r, "success", False) and getattr(r, "wall_clock_ms", None) is not None:
                timings_ms.append(float(r.wall_clock_ms))
                md: dict[str, str] = {}
                payload = getattr(r, "m6_1_1_timing_payload", None)
                if isinstance(payload, dict):
                    # Skip None values: timing_checkpoint_to_payload emits None
                    # for pre-M6.1.3 wire vintage on `pre_engine_wall_ns` /
                    # `first_chunk_mono_ns` / audit fields. Carrying the literal
                    # string "None" through would break downstream int parsing.
                    for k, v in payload.items():
                        if v is None:
                            continue
                        md[k] = str(v)
                engine_cost = getattr(r, "engine_cost", None)
                if engine_cost is not None:
                    # Thread engine_cost fields into per_rpc_metadata so the
                    # aggregator can compute tpot_ms / engine_ttft_ms / engine_forward_ms
                    # alongside the M6.1.1 segment checkpoints. Keys mirror
                    # `EngineCostSpan` attribute names verbatim.
                    for attr in ("engine_tpot_ms", "engine_ttft_ms", "engine_forward_ms"):
                        v = getattr(engine_cost, attr, None)
                        if v is not None:
                            md[attr] = str(v)
                if md:
                    per_rpc_metadata.append(md)
            else:
                if first_failure is None:
                    reason = getattr(r, "failure_reason", None)
                    first_failure = str(reason) if reason else "unknown_failure"

        if not timings_ms:
            return BlockDispatchResult(
                timings_ms=[],
                failed_reason=first_failure or "no_successful_rpcs",
                per_rpc_metadata=[],
            )
        return BlockDispatchResult(
            timings_ms=timings_ms,
            failed_reason=None,
            per_rpc_metadata=per_rpc_metadata,
        )

    # Expose the live preemption-events counter so the orchestrator can
    # persist it to ``run_meta.preemption_events`` after the sweep
    # completes. Functions are first-class and can carry attributes; the
    # ``state`` namespace itself is the source of truth (the closure
    # references it), so the read is always current.
    def _get_preemption_events() -> int:
        return int(state.preemption_events)

    _dispatcher.preemption_events = _get_preemption_events  # type: ignore[attr-defined]
    _dispatcher.preemption_budget = preemption_budget  # type: ignore[attr-defined]

    return _dispatcher


def _classify_dispatcher_exc(exc: BaseException) -> str:
    """Map a raised exception to a short ``failed_reason`` string that the
    classifier downstream can pattern-match (e.g. ``"grpc_unavailable"`` vs
    ``"httpx_timeout"``)."""
    if isinstance(exc, grpc.RpcError):
        try:
            code = exc.code().name.lower()
        except (AttributeError, ValueError):
            code = "unknown"
        return f"grpc_{code}"
    if isinstance(exc, httpx.TimeoutException):
        return "httpx_timeout"
    if isinstance(exc, httpx.HTTPError):
        return f"httpx_{type(exc).__name__.lower()}"
    return f"{type(exc).__name__.lower()}"


def build_modal_anchor_dispatcher(
    driver: Any,  # M6_2RPCDriver
    *,
    anchor_cell: Cell | None = None,
    anchor_max_tokens: int = 10,
    make_driver: Any = None,  # Callable[[], Awaitable[M6_2RPCDriver]] | None
    preemption_budget: int = M6_2_PREEMPTION_RECURRENCE_THRESHOLD,
    consecutive_death_threshold: int = M6_2_ENDPOINT_DEATH_CONSECUTIVE_THRESHOLD,
) -> Any:
    """Build an :class:`AnchorRPCDriver` that fires the FR-031 anchor block
    against the real driver.

    The anchor block uses SYNTHETIC prompts (``prompt=None`` → builder falls
    back to ``_build_chat_prompt(seed)``), preserving byte-comparability with
    M6.1.3's published anchors per R-3 of research.md. Always at
    ``chat_stream_c1 × max_tokens=10`` unless the caller overrides.

    **T074e Modal-preemption recovery (2026-05-24)**: parallel to
    :func:`build_modal_block_dispatcher`'s recovery loop. When ALL ``n``
    anchor RPCs fail with :func:`is_modal_endpoint_death` shapes AND
    ``make_driver`` is supplied, the dispatcher emits a
    ``PREEMPTION_DETECTED phase=anchor`` event, awaits the refreshed
    driver, emits ``PREEMPTION_RECOVERED phase=anchor``, and retries the
    anchor block once. After ``preemption_budget`` recoveries the
    dispatcher raises :class:`PreemptionBudgetExhausted` (same exception
    type as the block dispatcher; the orchestrator's outer ``except``
    clause catches both).

    The anchor dispatcher tracks its own ``preemption_events`` counter
    separately from the block dispatcher's. Per-dispatcher budgets are
    technically more permissive than FR-026's strict sweep-wide threshold,
    but anchor preemption is rare enough (anchors fire at most ~10 times
    per publish sweep vs ~132 block dispatches) that the per-dispatcher
    counter is a practical simplification. Unifying the budgets via the
    make_driver factory is a future enhancement.

    Counters exposed for orchestrator readback (mirrors the block
    dispatcher API)::

        anchor_dispatcher.preemption_events  # callable returning int
        anchor_dispatcher.preemption_budget  # int constant
    """
    from vllm_grpc_bench.sweep import _progress
    from vllm_grpc_bench.types import Cell as _M6_1Cell

    cell = anchor_cell or _M6_1Cell(path="chat_stream", hidden_size=4096, concurrency=1)
    state = SimpleNamespace(driver=driver, preemption_events=0, consecutive_death_blocks=0)

    async def _gather_anchor(
        cohort: CohortKind, n: int, base_seed: int, seed_offset: int
    ) -> list[Any]:
        """Fire the anchor block once and return raw per-RPC results
        (success records OR exceptions). The caller distinguishes the
        all-endpoint-death pattern from a normal partial-failure path."""
        # Same in-flight bound as build_modal_block_dispatcher: the anchor is
        # always chat_stream_c1 (concurrency=1), so this enforces strictly
        # serial dispatch and matches M6.1.3's anchor measurement regime.
        sem = asyncio.Semaphore(cell.concurrency)

        async def _one(i: int) -> Any:
            seed = base_seed + seed_offset + i
            async with sem:
                try:
                    return await state.driver(
                        cohort,
                        cell,
                        seed,
                        max_tokens=anchor_max_tokens,
                        ignore_eos=False,
                        prompt=None,
                        prompt_embeds_override=None,
                    )
                except (grpc.RpcError, httpx.HTTPError) as exc:
                    # Capture the exception itself so the recovery predicate
                    # can run is_modal_endpoint_death on it. The legacy
                    # behavior of returning None on RPC failure is preserved
                    # in the aggregation step below.
                    return exc

        return await asyncio.gather(*[_one(i) for i in range(n)])

    async def _anchor(
        *, cohort: CohortKind, n: int, base_seed: int, seed_offset: int
    ) -> list[float]:
        results = await _gather_anchor(cohort, n, base_seed, seed_offset)

        # T074e recovery loop: primary trigger fires when every anchor
        # RPC failed with an endpoint-death signature; secondary trigger
        # fires after ``consecutive_death_threshold`` consecutive anchor
        # blocks each had at least one endpoint-death failure (mirrors
        # build_modal_block_dispatcher's logic).
        while make_driver is not None:
            primary = block_failed_with_endpoint_death(results, n)
            secondary = False
            trigger_reason: str
            if primary:
                state.consecutive_death_blocks = 0
                trigger_reason = "whole_block_endpoint_death"
            elif block_has_endpoint_death(results):
                state.consecutive_death_blocks += 1
                if state.consecutive_death_blocks >= consecutive_death_threshold:
                    secondary = True
                    trigger_reason = "consecutive_endpoint_death"
                    state.consecutive_death_blocks = 0
                else:
                    break
            else:
                state.consecutive_death_blocks = 0
                break

            if not (primary or secondary):  # pragma: no cover — defensive
                break

            if state.preemption_events >= preemption_budget:
                _progress(
                    "PREEMPTION_BUDGET_EXHAUSTED",
                    phase="anchor",
                    cohort=cohort,
                    preemption_events=state.preemption_events,
                    budget=preemption_budget,
                    trigger=trigger_reason,
                )
                raise PreemptionBudgetExhausted(
                    f"Modal preemption recurrence threshold "
                    f"({preemption_budget}) exhausted during anchor block "
                    f"cohort={cohort}; aborting sweep per FR-026."
                )
            attempt = state.preemption_events + 1
            _progress(
                "PREEMPTION_DETECTED",
                phase="anchor",
                cohort=cohort,
                attempt=f"{attempt}/{preemption_budget}",
                trigger=trigger_reason,
            )
            t0 = asyncio.get_event_loop().time()
            try:
                state.driver = await make_driver()
            except Exception as exc:  # noqa: BLE001
                _progress(
                    "PREEMPTION_RECOVERY_FAILED",
                    phase="anchor",
                    cohort=cohort,
                    attempt=f"{attempt}/{preemption_budget}",
                    trigger=trigger_reason,
                    error=type(exc).__name__,
                )
                raise PreemptionRecoveryFailed(
                    f"make_driver() failed during anchor-block preemption "
                    f"recovery cohort={cohort}: {type(exc).__name__}: {exc}"
                ) from exc
            state.preemption_events = attempt
            _progress(
                "PREEMPTION_RECOVERED",
                phase="anchor",
                cohort=cohort,
                attempt=f"{attempt}/{preemption_budget}",
                trigger=trigger_reason,
                recovery_s=f"{asyncio.get_event_loop().time() - t0:.1f}",
            )
            results = await _gather_anchor(cohort, n, base_seed, seed_offset)

        # Convert raw results into the legacy "list of successful timings"
        # shape the caller (compute_anchor_block) expects. Exceptions and
        # non-success records are dropped (preserves pre-T074e behavior).
        timings: list[float] = []
        for r in results:
            if isinstance(r, BaseException):
                continue
            if getattr(r, "success", False) and getattr(r, "wall_clock_ms", None) is not None:
                timings.append(float(r.wall_clock_ms))
        return timings

    def _get_preemption_events() -> int:
        return int(state.preemption_events)

    _anchor.preemption_events = _get_preemption_events  # type: ignore[attr-defined]
    _anchor.preemption_budget = preemption_budget  # type: ignore[attr-defined]

    return _anchor


# --- M6.1.3 baseline loader (US2 crossover input) --------------------------


def load_m6_1_3_baseline(
    baseline_path: str | Path,
) -> tuple[
    dict[str, dict[CohortKind, M6_1_3CohortBaseline]],
    dict[str, str],
]:
    """Read the M6.1.3 artifact and return ``(per_cell_baseline, base_verdicts)``.

    ``per_cell_baseline[cell_id][cohort]`` is a
    :class:`m6_2_crossover.M6_1_3CohortBaseline` (wall_p50_ms + CI half-width).
    ``base_verdicts[cell_id]`` is the M6.1.3 classifier label.

    Source mapping:

    - ``wall_p50_ms`` ← M6.1.3's ``measurements[].wall_clock_ms_mean`` (mean
      is the closest available per-cohort proxy; M6.1.3 doesn't publish a
      per-cohort p50).
    - ``wall_p50_ms_ci_half_width`` ← per-(cell, cohort)
      ``between_run_variance.stddev_of_means_ms`` × 1.96 / sqrt(n_runs) when
      available, else 0.0 (the crossover compute falls back to the symmetric
      mean-in-CI rule's failure path when the CI is degenerate).
    - ``base_verdicts`` ← ``classifications`` dict from the artifact.

    Returns ``({}, {})`` if the baseline file is missing or malformed; the
    crossover compute then emits the canonical "did not publish" evidence
    for every cell.
    """
    path = Path(baseline_path)
    if not path.exists():
        return {}, {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}, {}

    baseline_per_cell: dict[str, dict[CohortKind, M6_1_3CohortBaseline]] = {}
    for measurement in data.get("measurements", []):
        cell_id = measurement.get("cell_id")
        cohort = measurement.get("cohort")
        wall_mean = measurement.get("wall_clock_ms_mean")
        if cell_id is None or cohort is None or wall_mean is None:
            continue
        baseline_per_cell.setdefault(cell_id, {})[cohort] = M6_1_3CohortBaseline(
            wall_p50_ms=float(wall_mean),
            wall_p50_ms_ci_half_width=0.0,  # see between_run_variance section
        )

    # Enrich with between_run_variance-derived CI half-widths when present.
    variance = data.get("between_run_variance") or {}
    for cell_id, per_cohort in variance.items():
        for cohort, var in (per_cohort or {}).items():
            stddev = var.get("stddev_of_means_ms")
            n_runs = var.get("n_runs", 1)
            if stddev is None or n_runs is None or n_runs < 2:
                continue
            try:
                ci_half = 1.96 * float(stddev) / (float(n_runs) ** 0.5)
            except (TypeError, ValueError):
                continue
            entry = baseline_per_cell.get(cell_id, {}).get(cohort)
            if entry is None:
                continue
            baseline_per_cell[cell_id][cohort] = M6_1_3CohortBaseline(
                wall_p50_ms=entry.wall_p50_ms,
                wall_p50_ms_ci_half_width=ci_half,
            )

    base_verdicts: dict[str, str] = {}
    for cell_id, label in (data.get("classifications") or {}).items():
        if isinstance(label, str):
            base_verdicts[cell_id] = label
    return baseline_per_cell, base_verdicts


# --- Real anchor CI half-width derivation (T054) ---------------------------


def derive_anchor_drift_threshold(baseline_path: str | Path) -> float:
    """Read M6.1.3's ``between_run_variance`` at ``chat_stream_c1`` (the
    cell the anchor block exercises) and return the MAX CI half-width across
    the cohorts that M6.1.3 published.

    The drift-warning rule in :func:`m6_2_anchor_trajectory.compute_anchor_latency_trajectory`
    fires when the per-cohort ``max - min`` spread across anchor snapshots
    exceeds this threshold. Using the per-cohort MAX (rather than the per-cohort
    mean / min) is the most conservative choice: a tight cohort's threshold
    would fire on benign network jitter the looser cohorts already absorb.

    Falls back to ``5.0`` ms if the baseline file is unreadable or carries no
    ``between_run_variance.chat_stream_c1`` block — preserves the previous
    sentinel behavior so the call site never throws.
    """
    path = Path(baseline_path)
    if not path.exists():
        return 5.0
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return 5.0
    brv = (data.get("between_run_variance") or {}).get("chat_stream_c1") or {}
    cis: list[float] = []
    for cohort_data in brv.values():
        if not isinstance(cohort_data, dict):
            continue
        stddev = cohort_data.get("stddev_of_means_ms")
        n_runs = cohort_data.get("n_runs")
        if stddev is None or n_runs is None or n_runs < 2:
            continue
        try:
            cis.append(1.96 * float(stddev) / (float(n_runs) ** 0.5))
        except (TypeError, ValueError):
            continue
    return max(cis) if cis else 5.0


def derive_anchor_baseline_p50_ms(baseline_path: str | Path) -> float:
    """Read M6.1.3's ``chat_stream_c1`` × ``max_tokens=10`` published
    ``wall_p50_ms`` and return the MAX across the cohorts M6.1.3 published.

    Feeds B4's ``floor_fraction × baseline_p50_ms`` co-floor in
    :func:`m6_2_anchor_trajectory.compute_anchor_latency_trajectory`. Using
    the per-cohort MAX matches :func:`derive_anchor_drift_threshold`'s
    conservative choice: B4's co-floor scales with the slowest cohort's
    baseline so a tight gRPC cohort's threshold doesn't fire on operationally-
    insignificant drift that the slower REST cohorts naturally absorb.

    Falls back to ``0.0`` ms when the baseline file is unreadable or has no
    ``chat_stream_c1`` × max_tokens=10 row — B4 reduces to a no-op floor
    (the pre-B4 B2 behavior) so the call site never throws and the
    threshold formula remains well-defined.
    """
    path = Path(baseline_path)
    if not path.exists():
        return 0.0
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0.0
    per_cell = (data.get("per_cell") or {}).get("chat_stream_c1") or {}
    p50s: list[float] = []
    for cohort_data in per_cell.values():
        if not isinstance(cohort_data, dict):
            continue
        # M6.1.3 baselines are at single max_tokens; tolerate either flat or
        # max_tokens-keyed shape.
        row = cohort_data.get("10") or cohort_data
        if not isinstance(row, dict):
            continue
        wall_p50 = row.get("wall_p50_ms")
        if wall_p50 is None:
            continue
        try:
            p50s.append(float(wall_p50))
        except (TypeError, ValueError):
            continue
    return max(p50s) if p50s else 0.0


# --- Null-anchor assembly (T053) --------------------------------------------


def _cross_checkable_max_tokens(path: str) -> int:
    """The single ``max_tokens`` axis value at which an M6.1.x baseline exists
    for this cell type.

    M6.1.x used ``max_tokens=50`` for ``chat_stream`` cells and ``max_tokens=10``
    for ``embed`` cells (the M6.x synthetic caps). The other axis point in
    ``M6_2_NULL_ANCHOR_MAX_TOKENS`` is a NEW baseline (no M6.1.x reference).
    """
    return 50 if path == "chat_stream" else 10


def make_null_anchor_validation(
    measurements: list[Any],  # list[M6_2MeasurementPoint]
    baseline_per_cell: dict[str, dict[CohortKind, M6_1_3CohortBaseline]],
) -> list[M6_2NullAnchor]:
    """FR-012 / FR-013 null-anchor assembly across the 48 anchor cells.

    Iterates ``CELLS × COHORTS × {10, 50}`` (= 48 cells), pairing
    each with the M6.2 measurement at that (cell_id, cohort, max_tokens).
    For each, decides cross-checkable vs new-baseline by whether M6.1.3
    published a baseline at the ``max_tokens`` value matched to the cell
    type (``chat_stream`` → ``max_tokens=50``; ``embed`` → ``max_tokens=10``).

    Cross-checkable cells call :func:`m6_2_null_anchor.make_null_anchor` with
    the M6.1.3 wall_p50 + CI half-width. New-baseline cells call
    :func:`m6_2_null_anchor.make_new_baseline_anchor` carrying only the M6.2
    wall_p50 (or ``None`` if the anchor block failed).
    """
    from vllm_grpc_bench.m6_2_null_anchor import (
        make_new_baseline_anchor,
        make_null_anchor,
    )

    by_key: dict[tuple[str, CohortKind, int], Any] = {}
    for point in measurements:
        if point.max_tokens not in M6_2_NULL_ANCHOR_MAX_TOKENS:
            continue
        by_key[(point.cell_id, point.cohort, point.max_tokens)] = point

    anchors: list[M6_2NullAnchor] = []
    for path, _hidden_size, concurrency in CELLS:
        cell_id = f"{path}_c{concurrency}"
        baseline_max_tokens = _cross_checkable_max_tokens(path)
        cohorts_for_cell = baseline_per_cell.get(cell_id, {})
        for cohort in COHORTS:
            for max_tokens in M6_2_NULL_ANCHOR_MAX_TOKENS:
                point = by_key.get((cell_id, cohort, max_tokens))
                m6_2_p50: float | None = None
                if point is not None and point.wall_p50_ms is not None:
                    m6_2_p50 = point.wall_p50_ms
                baseline_entry = (
                    cohorts_for_cell.get(cohort) if max_tokens == baseline_max_tokens else None
                )
                if baseline_entry is not None and baseline_entry.wall_p50_ms_ci_half_width > 0.0:
                    m6_2_ci_hw = 0.0
                    if point is not None:
                        # M6.2's per-block CI half-width is computed by the
                        # per-segment aggregator (see ``_aggregate_block_metrics``
                        # in sweep). Thread it into the pooled-CI rule so
                        # cells whose own variance is larger than the M6.1.3
                        # baseline CI don't trip on noise. ``None`` for cells
                        # whose CI couldn't be computed (n<2) → 0.0 → floor.
                        ci_attr = getattr(point, "wall_p50_ms_ci_half_width", None)
                        if isinstance(ci_attr, int | float):
                            m6_2_ci_hw = float(ci_attr)
                    anchors.append(
                        make_null_anchor(
                            cell_id=cell_id,
                            cohort=cohort,
                            max_tokens=max_tokens,
                            m6_2_wall_p50_ms=m6_2_p50,
                            m6_1_3_wall_p50_ms=baseline_entry.wall_p50_ms,
                            m6_1_3_ci_half_width=baseline_entry.wall_p50_ms_ci_half_width,
                            m6_2_ci_half_width=m6_2_ci_hw,
                        )
                    )
                else:
                    anchors.append(
                        make_new_baseline_anchor(
                            cell_id=cell_id,
                            cohort=cohort,
                            max_tokens=max_tokens,
                            m6_2_wall_p50_ms=m6_2_p50,
                        )
                    )
    return anchors


# --- Artifact assembly -----------------------------------------------------


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        return out.stdout.strip() or "unknown"
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def build_artifact(
    *,
    sweep_mode: M6_2SweepMode,
    sweep_outputs: object,  # M6_2SweepOutputs (avoid import cycle)
    chat_corpus_sha256: str,
    chat_corpus_path: str,
    embed_corpus_sha256: str,
    embed_corpus_path: str,
    n_per_point: int,
    base_seed: int,
    modal_region: str,
    model_identifier: str,
    sub_probe_rows: object = None,  # list[SubProbeBlockResult] | None
    sub_probe_ran: bool = False,
    run_id: str | None = None,
    m6_1_3_baseline_path: str = "docs/benchmarks/m6_1_3-attribution-closure.json",
    network_paths: dict[CohortKind, list[Any]] | None = None,
    preemption_events: int = 0,
) -> M6_2SweepArtifact:
    """Assemble :class:`M6_2SweepArtifact` from the sweep outputs + ancillary
    inputs collected by :func:`run_m6_2`.

    Sections populated:

    * Production-budget rows: from the sweep's ``MeasurementPoint`` list.
    * ``not_validated`` placeholders for validate-mode interior caps: via
      :func:`m6_2_reporter.fill_validate_mode_placeholders`.
    * Anchor-latency trajectory: from per-cohort anchor snapshots. The
      drift threshold is derived from M6.1.3's
      ``between_run_variance.chat_stream_c1`` per :func:`derive_anchor_drift_threshold`
      (T054) — the previous hardcoded 5.0 ms sentinel only fires now when the
      baseline file is unreadable or absent.
    * Null-anchor validation: 48-cell list assembled by
      :func:`make_null_anchor_validation` (T053) — 22 cross-checkable cells
      verdict against M6.1.3's published CI; 26 new-baseline cells carry
      ``new_baseline_marker=True``.
    * Crossover (US2): symmetric mean-in-CI rule against M6.1.3 base verdicts.
    * KV-pressure (US3): wall-clock-ratio inference consuming sub-probe rows.
    * ``network_paths``: threaded from the sweep's topology probe (T055).
    * ``integrity_warnings``: composed via
      :func:`m6_2_reporter.build_integrity_warnings`.
    """
    from vllm_grpc_bench.m6_2_anchor_trajectory import (
        compute_anchor_latency_trajectory,
    )
    from vllm_grpc_bench.m6_2_crossover import (
        SubProbeBlockResult,
        compute_kv_pressure_inference,
        compute_per_cell_crossover,
    )
    from vllm_grpc_bench.m6_2_reporter import (
        build_integrity_warnings,
        fill_validate_mode_placeholders,
    )
    from vllm_grpc_bench.sweep import M6_2SweepOutputs
    from vllm_grpc_bench.sweep_types import M6_2_MAX_TOKENS_AXIS
    from vllm_grpc_bench.types import COHORTS

    if not isinstance(sweep_outputs, M6_2SweepOutputs):
        raise TypeError(
            f"build_artifact() expected M6_2SweepOutputs, got {type(sweep_outputs).__name__}"
        )

    # Pivot the measurements list into the per_cell shape per artifact-schema.md.
    per_cell: dict[str, dict[str, dict[int, object]]] = {}
    for point in sweep_outputs.measurements:
        per_cell.setdefault(point.cell_id, {}).setdefault(point.cohort, {})[point.max_tokens] = (
            point
        )

    # Validate-mode placeholders for the unmeasured interior caps.
    per_cell_filled = fill_validate_mode_placeholders(
        per_cell,  # type: ignore[arg-type]
        sweep_mode=sweep_mode,
        block_start_utc=sweep_outputs.wall_clock_start_utc,
        block_end_utc=sweep_outputs.wall_clock_end_utc,
    )

    # M6.1.3 baseline load (used for both anchor CI threshold + crossover input
    # + null-anchor cross-checkable verdicts).
    baseline_per_cell, base_verdicts = load_m6_1_3_baseline(m6_1_3_baseline_path)

    # Anchor-latency trajectory (FR-031 / SC-016). T054 wires the CI threshold
    # from M6.1.3's between_run_variance.chat_stream_c1 — the cell the anchor
    # block exercises. T060/T061 round-8 amendment additionally threads the
    # baseline p50 (for B4's 2.5% relative co-floor) and the C1 warmup
    # suppression cutoff. Sentinel fallbacks if the baseline JSON is unavailable.
    anchor_trajectory = compute_anchor_latency_trajectory(
        sweep_outputs.anchor_snapshots,
        m6_1_3_baseline_ci_half_width=derive_anchor_drift_threshold(m6_1_3_baseline_path),
        baseline_p50_ms=derive_anchor_baseline_p50_ms(m6_1_3_baseline_path),
    )

    # US2 crossover compute. Reads M6.1.3 baseline (cohort means + classifier
    # labels) and runs the symmetric mean-in-CI rule against M6.2's per-cohort
    # axis rows. Cells without a baseline entry emit canonical "did not
    # publish" evidence.
    protocol_crossover = compute_per_cell_crossover(
        per_cell_filled,
        baseline_per_cell,
        base_verdicts,
        sweep_mode=sweep_mode,
    )

    # US3 KV-pressure inference. Consumes the sub-probe rows (NOT the
    # main-sweep budget-table c=8 rows) per FR-036 / FR-017a amendment.
    # 8 records emitted: 4 cohorts × 2 cell-types.
    typed_sub_probe_rows: list[SubProbeBlockResult] = []
    if sub_probe_rows is not None:
        if not isinstance(sub_probe_rows, list):
            raise TypeError(f"sub_probe_rows must be a list, got {type(sub_probe_rows).__name__}")
        for row in sub_probe_rows:
            if not isinstance(row, SubProbeBlockResult):
                raise TypeError(
                    f"sub_probe_rows entries must be SubProbeBlockResult, got {type(row).__name__}"
                )
            typed_sub_probe_rows.append(row)
    kv_pressure_observation = compute_kv_pressure_inference(typed_sub_probe_rows)

    started = sweep_outputs.wall_clock_start_utc
    ended = sweep_outputs.wall_clock_end_utc
    total_hours = _hours_between(started, ended)

    run_meta = M6_2RunMeta(
        git_sha=_git_sha(),
        modal_region=modal_region,
        base_seed=base_seed,
        model_identifier=model_identifier,
        dispatch_mode="concurrent",
        symmetric_prompts_enabled=True,
        schema_version="m6_1_1.v1",
        sweep_mode=sweep_mode,
        m6_1_3_baseline_artifact_path=m6_1_3_baseline_path,
        iteration_order="cohort_innermost_block",
        iteration_discipline_verified=sweep_outputs.iteration_discipline_verified,
        n_per_point=n_per_point,
        validate_axis_subset=(
            list(M6_2_VALIDATE_MAX_TOKENS_AXIS) if sweep_mode == "validate" else None
        ),
        wall_clock_start_utc=started,
        wall_clock_end_utc=ended,
        total_sweep_hours=total_hours,
        modal_spend_usd_estimate=None,
        chat_corpus_sha256=chat_corpus_sha256,
        chat_corpus_path=chat_corpus_path,
        embed_corpus_sha256=embed_corpus_sha256,
        embed_corpus_path=embed_corpus_path,
        sub_probe_ran=sub_probe_ran,
        preemption_events=preemption_events,
    )

    null_anchor_validation = make_null_anchor_validation(
        sweep_outputs.measurements, baseline_per_cell
    )
    resolved_network_paths: dict[CohortKind, list[Any]] = (
        {c: list(network_paths.get(c, [])) for c in COHORTS}
        if network_paths is not None
        else {c: [] for c in COHORTS}
    )

    artifact = M6_2SweepArtifact(
        schema_version="m6_1_1.v1",
        dispatch_mode="concurrent",
        run_id=run_id or f"{started}-{uuid.uuid4().hex[:8]}",
        run_started_at=started,
        run_completed_at=ended,
        run_meta=run_meta,
        per_cell=per_cell_filled,
        network_paths=resolved_network_paths,
        cohort_set=list(COHORTS),
        cohort_omissions=None,
        null_anchor_validation=null_anchor_validation,
        max_tokens_axis=list(
            M6_2_VALIDATE_MAX_TOKENS_AXIS if sweep_mode == "validate" else M6_2_MAX_TOKENS_AXIS
        ),
        protocol_crossover=protocol_crossover,
        kv_pressure_observation=kv_pressure_observation,
        anchor_latency_trajectory=anchor_trajectory,
        failure_summary={},
        integrity_warnings=[],
    )
    # Compute failure_summary tally + integrity_warnings from the assembled
    # artifact so the rendering matches the JSON serialization byte-for-byte.
    artifact.failure_summary = _tally_failure_summary(artifact)
    artifact.integrity_warnings = build_integrity_warnings(artifact)
    return artifact


def _tally_failure_summary(artifact: M6_2SweepArtifact) -> dict[str, int]:
    """Count ``failed_<reason>`` markers across the table, excluding the
    validate-mode ``not_validated`` placeholders."""
    from vllm_grpc_bench.m6_2_reporter import NOT_VALIDATED_MARKER

    counts: dict[str, int] = {}
    for per_cohort in artifact.per_cell.values():
        for per_cap in per_cohort.values():
            for point in per_cap.values():
                if point.failed_reason is None or point.failed_reason == NOT_VALIDATED_MARKER:
                    continue
                counts[point.failed_reason] = counts.get(point.failed_reason, 0) + 1
    return counts


def _hours_between(start_utc: str, end_utc: str) -> float:
    try:
        start = _dt.datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
        end = _dt.datetime.fromisoformat(end_utc.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (end - start).total_seconds() / 3600.0


# --- Main-sweep + sub-probe driver -----------------------------------------


async def _drive_main_sweep_and_sub_probe(
    *,
    inputs: object,  # M6_2SweepInputs
    dispatcher: object,
    anchor_dispatcher: object,
    chat_corpus: list[RequestSample],
    embed_corpus: list[CompletionEmbedSample],
    base_seed: int,
    is_transient: Any = None,
) -> tuple[Any, list[Any]]:
    """Drive the main sweep + sub-probe sequentially in a single asyncio
    runtime. Sub-probe always runs after the main sweep completes per SC-019;
    both publish and validate modes invoke it.

    ``is_transient`` is the FR-033 retry classifier for the sub-probe blocks.
    Defaults to :func:`_stub_is_transient` (never retries) when omitted, so
    test paths preserve their existing behavior.
    """
    from vllm_grpc_bench.m6_2_sub_probe import run_kv_pressure_sub_probe
    from vllm_grpc_bench.sweep import (
        M6_2SweepInputs,
    )
    from vllm_grpc_bench.sweep import (
        run_sweep as _run_sweep,
    )

    if not isinstance(inputs, M6_2SweepInputs):
        raise TypeError(
            f"_drive_main_sweep_and_sub_probe inputs must be M6_2SweepInputs, "
            f"got {type(inputs).__name__}"
        )

    import time as _time

    from vllm_grpc_bench.sweep import _progress as _sweep_progress

    sweep_outputs = await _run_sweep(inputs)
    _sweep_progress(
        "SUBPROBE_START",
        blocks=16,
        n=20,
        ignore_eos=True,
        caps="1024,2048",
    )
    sub_probe_perf_start = _time.monotonic()
    sub_probe_results_list = list(
        await run_kv_pressure_sub_probe(
            dispatcher=dispatcher,  # type: ignore[arg-type]
            is_transient=is_transient if is_transient is not None else _stub_is_transient,
            base_seed=base_seed,
            chat_corpus=chat_corpus,
            embed_corpus=embed_corpus,
        )
    )
    _sweep_progress(
        "SUBPROBE_END",
        blocks_done=len(sub_probe_results_list),
        duration_s=f"{_time.monotonic() - sub_probe_perf_start:.1f}",
    )
    del anchor_dispatcher  # not needed by the sub-probe (it dispatches via the main dispatcher)
    return sweep_outputs, sub_probe_results_list


# --- Real Modal-backed dispatch path ---------------------------------------


async def _run_modal_backed(
    args: argparse.Namespace,
    *,
    sweep_mode: M6_2SweepMode,
    n_per_point: int,
    chat_corpus: list[RequestSample],
    embed_corpus: list[CompletionEmbedSample],
    chat_corpus_sha256: str,
    chat_corpus_path: str,
    embed_corpus_sha256: str,
    embed_corpus_path: str,
    md_path: Path,
    json_path: Path,
    base_seed: int,
    modal_region: str,
    model_identifier: str,
    checkpoint_path: Path | None = None,
    preloaded_measurements: list[Any] | None = None,
    preloaded_anchor_snapshots: dict[CohortKind, list[Any]] | None = None,
    resumed_run_id: str | None = None,
    resumed_run_started_at: str | None = None,
) -> int:
    """Open Modal deploy + M6.2 RPC driver, run the sweep with real adapters,
    write the artifact. Returns the exit code per ``contracts/cli.md``.

    Mirrors :func:`m6_1_3_validate._run_modal_backed` (T013 / FR-028) but:

    * Uses :func:`rpc_driver.provide_m6_2_rpc_driver` so the driver
      callable threads the M6.2 kwargs (max_tokens / ignore_eos / prompt /
      prompt_embeds_override) per block.
    * Wraps the driver in :func:`build_modal_block_dispatcher` +
      :func:`build_modal_anchor_dispatcher` to match the sweep's
      ``BlockDispatcher`` + ``AnchorRPCDriver`` Protocols.
    * Wires the FR-009 topology probe (``network_probe.run_topology_probe``)
      against the handshake dict at sweep start + end.
    """
    from dataclasses import replace

    from vllm_grpc_bench.m6_2_reporter import write_m6_2_report
    from vllm_grpc_bench.modal_endpoint import ModalDeployError, provide_m6_endpoint
    from vllm_grpc_bench.network_probe import run_topology_probe
    from vllm_grpc_bench.seq_len import pin_seq_len_at_sweep_start
    from vllm_grpc_bench.sweep import M6_2SweepInputs

    token_env = str(getattr(args, "m6_2_modal_token_env", "MODAL_BENCH_TOKEN"))

    pinned_seq_len = pin_seq_len_at_sweep_start(model_identifier)
    print(
        f"[validate] pinned seq_len={pinned_seq_len} for model={model_identifier}",
        file=sys.stderr,
        flush=True,
    )
    axis = _resolve_axis(sweep_mode)

    try:
        import contextlib

        async with contextlib.AsyncExitStack() as outer_stack:
            endpoints = await outer_stack.enter_async_context(
                provide_m6_endpoint(
                    region=modal_region,
                    token_env=token_env,
                    model_id=model_identifier,
                )
            )
            # T074d — build the initial driver + make_driver factory in one
            # call. The outer_stack tracks every driver context (including
            # post-preemption refreshed ones) so sweep-end cleanup hits all
            # of them.
            (
                driver,
                make_driver,
                get_current_endpoints,
            ) = await build_modal_make_driver_callable(
                initial_endpoints=endpoints,
                seq_len=pinned_seq_len,
                base_seed=base_seed,
                outer_stack=outer_stack,
            )

            del replace  # imported above for parity with M6.1.3; unused here
            block_dispatcher = build_modal_block_dispatcher(
                driver,
                base_seed=base_seed,
                make_driver=make_driver,
            )
            anchor_dispatcher = build_modal_anchor_dispatcher(
                driver,
                make_driver=make_driver,
            )

            async def _topology_probe() -> dict[CohortKind, Any]:
                # T074d: re-read endpoints each call so a topology probe
                # that runs AFTER a preemption recovery sees the refreshed
                # URLs instead of the stale closure-captured ones.
                current = get_current_endpoints()
                handshake_dict: dict[str, object] = {
                    "rest_https_edge_url": current.rest_https_edge_url or "",
                    "rest_plain_tcp_url": current.rest_plain_tcp_url or "",
                    "grpc": current.grpc_url,
                }
                return await run_topology_probe(handshake_dict)

            inputs = M6_2SweepInputs(
                sweep_mode=sweep_mode,
                n=n_per_point,
                axis=axis,
                base_seed=base_seed,
                chat_corpus=chat_corpus,
                embed_corpus=embed_corpus,
                dispatcher=block_dispatcher,
                anchor_dispatcher=anchor_dispatcher,
                is_transient=is_transient_modal_error,
                topology_probe=_topology_probe,
                checkpoint_path=checkpoint_path,
                preloaded_measurements=preloaded_measurements,
                preloaded_anchor_snapshots=preloaded_anchor_snapshots,
                wall_clock_start_utc_override=resumed_run_started_at,
            )
            sweep_outputs, sub_probe_results = await _drive_main_sweep_and_sub_probe(
                inputs=inputs,
                dispatcher=block_dispatcher,
                anchor_dispatcher=anchor_dispatcher,
                chat_corpus=chat_corpus,
                embed_corpus=embed_corpus,
                base_seed=base_seed,
                is_transient=is_transient_modal_error,
            )
            # T074f — capture the per-dispatcher preemption counters BEFORE
            # the async-with block exits and the dispatcher closures fall
            # out of scope. Total is sum across both paths; persisted to
            # run_meta.preemption_events for post-hoc audit. Both
            # accessors are callable; the .preemption_events attribute is
            # the function, not the value.
            preemption_events_total = int(block_dispatcher.preemption_events()) + int(
                anchor_dispatcher.preemption_events()
            )
    except ModalDeployError as exc:
        print(
            f"[validate] Modal deploy/handshake failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 2
    except PreemptionBudgetExhausted as exc:
        # T074c: the FR-026 preemption-recurrence threshold was exhausted
        # by sustained Modal-side instability. The sweep aborts cleanly
        # rather than spinning forever. Return a distinct non-zero RC so
        # the operator (and the monitor script) can tell this apart from
        # a generic sweep failure.
        print(
            f"[validate] sweep aborted: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 6
    except PreemptionRecoveryFailed as exc:
        # T074c: make_driver() exhausted its refresh_timeout_s without
        # finding fresh URLs in the Modal Dict. Likely Modal-side outage.
        print(
            f"[validate] sweep aborted: preemption recovery failed: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 7
    except Exception as exc:  # noqa: BLE001
        print(
            f"[validate] sweep failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return 5

    network_paths = getattr(sweep_outputs, "network_paths", None)
    artifact = build_artifact(
        sweep_mode=sweep_mode,
        sweep_outputs=sweep_outputs,
        chat_corpus_sha256=chat_corpus_sha256,
        chat_corpus_path=chat_corpus_path,
        embed_corpus_sha256=embed_corpus_sha256,
        embed_corpus_path=embed_corpus_path,
        n_per_point=n_per_point,
        base_seed=base_seed,
        modal_region=modal_region,
        model_identifier=model_identifier,
        sub_probe_rows=sub_probe_results,
        sub_probe_ran=True,
        network_paths=network_paths,
        preemption_events=preemption_events_total,
        run_id=resumed_run_id,
    )
    write_m6_2_report(artifact, md_path, json_path, sweep_mode=sweep_mode)
    extra = (f" resumed_run_id={resumed_run_id}" if resumed_run_id else "") + (
        f" checkpoint={checkpoint_path}" if checkpoint_path else ""
    )
    print(
        f"[validate] sweep_mode={sweep_mode} n_per_point={n_per_point} "
        f"axis={list(axis)} md_out={md_path} json_out={json_path}{extra}",
        flush=True,
    )
    return 0


# --- Entry function --------------------------------------------------------


class _CheckpointMismatchAdapter(RuntimeError):
    """Local alias used by :func:`_resolve_resume_state` so the validate
    layer doesn't leak ``m6_2_resume.CheckpointMismatchError`` into its
    public surface. The orchestrator catches the local class and renders
    its ``str(exc)`` to stderr; the exit code is rc=8 (distinct from the
    rc=5 / rc=6 / rc=7 used by gates / deploy / preemption budget)."""


def _resolve_resume_state(
    args: argparse.Namespace,
    *,
    json_path: Path,
    sweep_mode: M6_2SweepMode,
    n_per_point: int,
    axis: tuple[int, ...],
    base_seed: int,
    model_identifier: str,
    modal_region: str,
    chat_corpus_sha256: str,
    embed_corpus_sha256: str,
) -> tuple[
    Path | None,  # checkpoint_path
    list[Any] | None,  # preloaded_measurements (M6_2MeasurementPoint)
    dict[CohortKind, list[Any]] | None,  # preloaded_anchor_snapshots
    str | None,  # resumed_run_id (Phase-1: propagate from checkpoint header on resume)
    str | None,  # resumed_run_started_at
]:
    """Read ``--m6_2-resume`` + ``--m6_2-checkpoint-out`` from ``args``,
    load + validate the checkpoint (if any), and return the tuple the
    sweep entrypoints thread into :class:`M6_2SweepInputs`.

    Three cases:

    1. ``--m6_2-resume PATH`` set → load the checkpoint, validate every
       integrity-gated field against the current invocation, return the
       pre-populated measurements + anchor snapshots and the original
       run_id / run_started_at carried over from the checkpoint header.
       Subsequent writes continue appending to the same path.
    2. No resume; ``--m6_2-checkpoint-out`` defaulted (``None``) → use
       ``<json_path>.checkpoint.jsonl``, write a fresh header, return
       empty pre-loaded state.
    3. No resume; ``--m6_2-checkpoint-out`` explicitly empty (``Path("")``)
       → disable checkpointing entirely, return ``checkpoint_path=None``
       and empty pre-loaded state.

    Raises :class:`_CheckpointMismatchAdapter` on integrity-gate failure;
    the orchestrator surfaces it and exits rc=8."""
    from vllm_grpc_bench.m6_2_resume import (
        RESUME_SCHEMA_VERSION,
        CheckpointHeader,
        CheckpointMismatchError,
        load_checkpoint,
        validate_checkpoint_against_current_run,
        write_checkpoint_header,
    )

    resume_path = getattr(args, "m6_2_resume", None)
    checkpoint_out = getattr(args, "m6_2_checkpoint_out", None)

    if resume_path is not None:
        try:
            header, measurements, anchor_snapshots = load_checkpoint(Path(resume_path))
            validate_checkpoint_against_current_run(
                header,
                sweep_mode=sweep_mode,
                n_per_point=n_per_point,
                axis=axis,
                base_seed=base_seed,
                model_identifier=model_identifier,
                modal_region=modal_region,
                git_sha=_git_sha(),
                chat_corpus_sha256=chat_corpus_sha256,
                embed_corpus_sha256=embed_corpus_sha256,
            )
        except CheckpointMismatchError as exc:
            raise _CheckpointMismatchAdapter(str(exc)) from exc
        print(
            f"[validate] resumed from checkpoint {resume_path} "
            f"({len(measurements)} measurements + "
            f"{sum(len(v) for v in anchor_snapshots.values())} anchor snapshots carried over)",
            file=sys.stderr,
            flush=True,
        )
        return (
            Path(resume_path),
            list(measurements),
            dict(anchor_snapshots) if anchor_snapshots else None,
            header.run_id,
            header.run_started_at,
        )

    # No resume — fresh sweep. Decide checkpoint output path.
    if checkpoint_out is not None and str(checkpoint_out) == "":
        # Explicit opt-out via empty path.
        return (None, None, None, None, None)

    checkpoint_path: Path
    if checkpoint_out is None:
        checkpoint_path = Path(str(json_path) + ".checkpoint.jsonl")
    else:
        checkpoint_path = Path(checkpoint_out)

    from vllm_grpc_bench.sweep import _now_iso_utc

    run_started_at = _now_iso_utc()
    run_id = f"{run_started_at}-{uuid.uuid4().hex[:8]}"
    header = CheckpointHeader(
        schema_version=RESUME_SCHEMA_VERSION,
        run_id=run_id,
        run_started_at=run_started_at,
        sweep_mode=sweep_mode,
        n_per_point=n_per_point,
        axis=tuple(axis),
        base_seed=base_seed,
        model_identifier=model_identifier,
        modal_region=modal_region,
        git_sha=_git_sha(),
        chat_corpus_sha256=chat_corpus_sha256,
        embed_corpus_sha256=embed_corpus_sha256,
    )
    write_checkpoint_header(checkpoint_path, header)
    print(
        f"[validate] checkpoint sidecar opened at {checkpoint_path} (run_id={run_id})",
        file=sys.stderr,
        flush=True,
    )
    # Phase-1 contract: the header's run_id + run_started_at are pinned at
    # this moment and threaded through build_artifact even on a fresh run
    # so the artifact's run_id matches the checkpoint's run_id (so the
    # operator can correlate the two in post-mortem audits).
    return (checkpoint_path, None, None, run_id, run_started_at)


def run_m6_2(args: argparse.Namespace, *, sweep_mode: M6_2SweepMode) -> int:
    """Single entry function for both ``--m6_2`` and ``--m6_2-validate``.

    Returns the process exit code per ``contracts/cli.md``. Orchestrates:

    * FR-004 round-3 ``--m6_2-n`` deferral gate.
    * SC-018 corpus SHA validation gate at sweep start.
    * Dispatcher selection (stub vs Modal-backed) based on
      ``--m6_2-skip-deploy``.
    * Sweep execution via :func:`sweep.run_sweep`.
    * Artifact assembly via :func:`build_artifact`.
    * Reporter write via :func:`m6_2_reporter.write_m6_2_report`.
    """
    from vllm_grpc_bench.corpus import CorpusDriftError
    from vllm_grpc_bench.m6_2_reporter import write_m6_2_report
    from vllm_grpc_bench.prompts import load_chat_corpus, load_embed_corpus
    from vllm_grpc_bench.sweep import (
        M6_2SweepInputs,
        gate_corpus_shas,
        gate_publish_mode_n,
    )

    args_m6_2_n: int | None = getattr(args, "m6_2_n", None)
    try:
        n_per_point = gate_publish_mode_n(args_m6_2_n, sweep_mode)
    except ValueError as exc:
        print(f"ERROR: {exc}", flush=True)
        return 5

    try:
        (
            chat_corpus_sha256,
            chat_corpus_path,
            embed_corpus_sha256,
            embed_corpus_path,
        ) = gate_corpus_shas()
    except CorpusDriftError as exc:
        print(f"ERROR: SC-018 corpus drift detected:\n{exc}", flush=True)
        return 6
    except FileNotFoundError as exc:
        print(f"ERROR: corpus missing (FR-035 Phase 1 prerequisite):\n{exc}", flush=True)
        return 6

    chat_corpus = load_chat_corpus()
    embed_corpus = load_embed_corpus()

    axis = _resolve_axis(sweep_mode)
    md_path = Path(infer_output_path(args, kind="md"))
    json_path = Path(infer_output_path(args, kind="json"))
    base_seed = int(getattr(args, "m6_2_base_seed", 42))
    modal_region = str(getattr(args, "m6_2_modal_region", "eu-west-1"))
    model_identifier = str(getattr(args, "m6_2_model", "Qwen/Qwen3-8B"))
    skip_deploy = bool(getattr(args, "m6_2_skip_deploy", False))

    # Phase-1 resume / checkpoint resolution. Three cases:
    #
    # 1. ``--m6_2-resume PATH`` set → load + validate header against the
    #    current run identity, pre-populate measurements + anchor snapshots,
    #    continue appending to the same checkpoint path.
    # 2. No resume; ``--m6_2-checkpoint-out`` defaulted (None) → checkpoint
    #    at ``<json_path>.checkpoint.jsonl``, write a fresh header.
    # 3. No resume; ``--m6_2-checkpoint-out`` explicitly empty (Path("")) →
    #    disable checkpointing entirely (back-compat with pre-Phase-1
    #    invocations that don't want a sidecar).
    try:
        (
            checkpoint_path,
            preloaded_measurements,
            preloaded_anchor_snapshots,
            resumed_run_id,
            resumed_run_started_at,
        ) = _resolve_resume_state(
            args,
            json_path=json_path,
            sweep_mode=sweep_mode,
            n_per_point=n_per_point,
            axis=axis,
            base_seed=base_seed,
            model_identifier=model_identifier,
            modal_region=modal_region,
            chat_corpus_sha256=chat_corpus_sha256,
            embed_corpus_sha256=embed_corpus_sha256,
        )
    except _CheckpointMismatchAdapter as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 8

    if not skip_deploy:
        return asyncio.run(
            _run_modal_backed(
                args,
                sweep_mode=sweep_mode,
                n_per_point=n_per_point,
                chat_corpus=chat_corpus,
                embed_corpus=embed_corpus,
                chat_corpus_sha256=chat_corpus_sha256,
                chat_corpus_path=chat_corpus_path,
                embed_corpus_sha256=embed_corpus_sha256,
                embed_corpus_path=embed_corpus_path,
                md_path=md_path,
                json_path=json_path,
                base_seed=base_seed,
                modal_region=modal_region,
                model_identifier=model_identifier,
                checkpoint_path=checkpoint_path,
                preloaded_measurements=preloaded_measurements,
                preloaded_anchor_snapshots=preloaded_anchor_snapshots,
                resumed_run_id=resumed_run_id,
                resumed_run_started_at=resumed_run_started_at,
            )
        )

    # --m6_2-skip-deploy path: stub dispatcher for tests + local artifact
    # smoke-runs. Modal is never contacted.
    dispatcher = build_stub_dispatcher()
    anchor_dispatcher = build_stub_anchor_dispatcher()

    inputs = M6_2SweepInputs(
        sweep_mode=sweep_mode,
        n=n_per_point,
        axis=axis,
        base_seed=base_seed,
        chat_corpus=chat_corpus,
        embed_corpus=embed_corpus,
        dispatcher=dispatcher,  # type: ignore[arg-type]
        anchor_dispatcher=anchor_dispatcher,  # type: ignore[arg-type]
        is_transient=_stub_is_transient,
        topology_probe=None,
        checkpoint_path=checkpoint_path,
        preloaded_measurements=preloaded_measurements,
        preloaded_anchor_snapshots=preloaded_anchor_snapshots,
        wall_clock_start_utc_override=resumed_run_started_at,
    )
    sub_probe_rows = asyncio.run(
        _drive_main_sweep_and_sub_probe(
            inputs=inputs,
            dispatcher=dispatcher,
            anchor_dispatcher=anchor_dispatcher,
            chat_corpus=chat_corpus,
            embed_corpus=embed_corpus,
            base_seed=base_seed,
        )
    )
    sweep_outputs, sub_probe_results = sub_probe_rows

    artifact = build_artifact(
        sweep_mode=sweep_mode,
        sweep_outputs=sweep_outputs,
        chat_corpus_sha256=chat_corpus_sha256,
        chat_corpus_path=chat_corpus_path,
        embed_corpus_sha256=embed_corpus_sha256,
        embed_corpus_path=embed_corpus_path,
        n_per_point=n_per_point,
        base_seed=base_seed,
        modal_region=modal_region,
        model_identifier=model_identifier,
        sub_probe_rows=sub_probe_results,
        sub_probe_ran=True,
        network_paths=getattr(sweep_outputs, "network_paths", None),
        run_id=resumed_run_id,
    )
    write_m6_2_report(artifact, md_path, json_path, sweep_mode=sweep_mode)
    extra = (f" resumed_run_id={resumed_run_id}" if resumed_run_id else "") + (
        f" checkpoint={checkpoint_path}" if checkpoint_path else ""
    )
    print(
        f"[validate] sweep_mode={sweep_mode} n_per_point={n_per_point} "
        f"axis={list(axis)} md_out={md_path} json_out={json_path}{extra}",
        flush=True,
    )
    return 0
