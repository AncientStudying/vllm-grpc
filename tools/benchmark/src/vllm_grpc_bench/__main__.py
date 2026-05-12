# Live benchmark: ~5 min for 10 samples × [1,4,8] concurrency × 2 targets (measured 2026-05-01)
# CI stub benchmark: <60 s (measured 2026-05-01)
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from vllm_grpc_bench.compare import compare, compare_cross, compare_three_way
from vllm_grpc_bench.corpus import load_corpus
from vllm_grpc_bench.io import load_run
from vllm_grpc_bench.metrics import (
    BenchmarkConfig,
    BenchmarkRun,
    ComparisonReport,
    RequestResult,
    build_run_meta,
    compute_summaries,
)
from vllm_grpc_bench.reporter import (
    write_cross_run_md,
    write_csv,
    write_json,
    write_summary_md,
    write_three_way_md,
)
from vllm_grpc_bench.runner import run_grpc_target_streaming, run_target, run_target_streaming

if TYPE_CHECKING:
    from vllm_grpc_bench.m3_types import M4SweepConfig
    from vllm_grpc_bench.m5_1_sweep import M5_1Run, M5_1SweepConfig

_DEFAULT_CORPUS = Path(__file__).parent.parent.parent / "corpus" / "chat_nonstreaming.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m vllm_grpc_bench",
        description="Benchmark the vLLM gRPC proxy bridge against the native OpenAI server.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # ---- compare subcommand ----
    cmp = sub.add_parser("compare", help="Compare two results.json files for regressions")
    cmp.add_argument("baseline", metavar="BASELINE_PATH", help="Path to baseline results.json")
    cmp.add_argument("new_results", metavar="NEW_RESULTS_PATH", help="Path to new results.json")
    cmp.add_argument("--threshold", type=float, default=0.10)

    # ---- compare-cross subcommand ----
    cmp_cross = sub.add_parser(
        "compare-cross",
        help="Head-to-head comparison of two separate runs (e.g. REST vs gRPC)",
    )
    cmp_cross.add_argument("--result-a", required=True, metavar="PATH", help="First results.json")
    cmp_cross.add_argument("--result-b", required=True, metavar="PATH", help="Second results.json")
    cmp_cross.add_argument("--label-a", default="run-a", metavar="LABEL", help="Label for run A")
    cmp_cross.add_argument("--label-b", default="run-b", metavar="LABEL", help="Label for run B")
    cmp_cross.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write report to file (default: stdout)",
    )

    # ---- compare-three-way subcommand ----
    cmp_three = sub.add_parser(
        "compare-three-way",
        help="Three-way comparison of REST / gRPC-proxy / gRPC-direct runs",
    )
    cmp_three.add_argument("--result-a", required=True, metavar="PATH", help="REST results.json")
    cmp_three.add_argument(
        "--result-b", required=True, metavar="PATH", help="gRPC-proxy results.json"
    )
    cmp_three.add_argument(
        "--result-c", required=True, metavar="PATH", help="gRPC-direct results.json"
    )
    cmp_three.add_argument("--label-a", default="rest", metavar="LABEL")
    cmp_three.add_argument("--label-b", default="grpc-proxy", metavar="LABEL")
    cmp_three.add_argument("--label-c", default="grpc-direct", metavar="LABEL")
    cmp_three.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write report to file (default: stdout)",
    )

    # ---- m3 mode (channel + schema tuning sweep) ----
    parser.add_argument(
        "--m3",
        action="store_true",
        help="Run the M3 channel-tuning sweep (see specs/015-m3-protobuf-grpc-tuning).",
    )
    parser.add_argument(
        "--axis",
        choices=("max_message_size", "keepalive", "compression", "http2_framing", "all"),
        default="all",
        help="Which channel axis to sweep (M3 mode).",
    )
    parser.add_argument(
        "--width",
        default="all",
        help="Embedding hidden_size: 2048|4096|8192|all|<positive_integer> (M3 mode).",
    )
    parser.add_argument(
        "--path",
        choices=("embed", "chat_stream", "both"),
        default="both",
        help="Which RPC path(s) to exercise (M3 mode).",
    )
    parser.add_argument(
        "--iters-per-cell", type=int, default=30, help="Iterations per cell (M3 mode)."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("docs/benchmarks"),
        help="Where to write report files (M3 mode).",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="One iter/cell, no CI math, transient artefact under bench-results/.",
    )
    parser.add_argument("--seed", type=int, default=0, help="RNG seed (M3 mode).")
    parser.add_argument(
        "--p2-revision",
        default=None,
        help="P2 schema candidate name (requires --frozen-channel).",
    )
    parser.add_argument(
        "--frozen-channel",
        default=None,
        help="Frozen ChannelConfig preset name for P2 (required with --p2-revision).",
    )
    parser.add_argument(
        "--reanalyze",
        type=Path,
        default=None,
        metavar="EXISTING_JSON",
        help=(
            "Phase A (US3) re-analysis mode: read an existing M3 sweep JSON, "
            "compute time/TTFT-metric verdicts (no re-sweep), and write a sibling "
            "<stem>-time.json. Per FR-014, embed cells use metric=time; "
            "chat_stream cells use metric=ttft."
        ),
    )

    # ---- M4 mode (time-axis sweep with shared baseline + schema candidates) ----
    parser.add_argument(
        "--m4",
        action="store_true",
        help="Run the M4 time-axis sweep (see specs/016-m4-time-axis-tuning).",
    )
    pacing_group = parser.add_mutually_exclusive_group()
    pacing_group.add_argument(
        "--no-pacing",
        dest="m4_pacing",
        action="store_const",
        const="no_pacing",
        help="M4: disable inter-token pacing in the mock engine (default).",
    )
    pacing_group.add_argument(
        "--paced",
        dest="m4_pacing",
        action="store_const",
        const="paced",
        help="M4: keep M3-style inter-token pacing (compatibility).",
    )
    baseline_group = parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        "--shared-baseline",
        dest="m4_shared_baseline",
        action="store_const",
        const=True,
        help="M4: share the M1_BASELINE cohort across all axes (default).",
    )
    baseline_group.add_argument(
        "--per-axis-baseline",
        dest="m4_shared_baseline",
        action="store_const",
        const=False,
        help="M4: re-measure the M1_BASELINE per axis (M3-compat; not defensible).",
    )
    parser.add_argument("--baseline-n", type=int, default=100)
    parser.add_argument("--candidate-n", type=int, default=100)
    parser.add_argument("--expand-n", type=int, default=250)
    parser.add_argument(
        "--warmup-n",
        type=int,
        default=10,
        help=(
            "M4: discard this many leading RPCs per cohort to absorb cold-start "
            "cost (channel setup, first-RPC HTTP/2 negotiation, descriptor caches). "
            "Larger values keep per-cohort CV (FR-005) lower on noisy hosts."
        ),
    )
    parser.add_argument(
        "--baseline-cv-warn",
        type=float,
        default=0.05,
        help=(
            "M4: within-cohort CV warn threshold for baseline cohorts (FR-005 / R-11). "
            "The run never aborts on CV; cohorts above this threshold are flagged "
            "`noisy_baseline=true` in the published JSON and named in a closing "
            "stderr warning so the report reader can adjudicate trust."
        ),
    )
    parser.add_argument(
        "--widths",
        default="2048,4096,8192",
        help="M4: csv list of hidden_size values (default 2048,4096,8192).",
    )
    parser.add_argument(
        "--paths",
        default="embed,chat_stream",
        help="M4: csv list of paths (default embed,chat_stream).",
    )
    parser.add_argument(
        "--axes",
        default="max_message_size,keepalive,compression,http2_framing",
        help="M4: csv list of channel axes to sweep.",
    )
    parser.add_argument(
        "--schema-candidates",
        default="packed_token_ids,oneof_flattened_input,chunk_granularity",
        help="M4 / US3: csv list of named schema candidates.",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="M4: skip US3 schema-candidate measurement entirely.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("bench-results/m4-full"),
        help="M4: output directory for transient per-iteration JSON.",
    )

    # ---- M5.2 mode (REST transport path x gRPC tuning surface) ----
    parser.add_argument(
        "--m5_2",
        action="store_true",
        help="Run the M5.2 transport-vs-tuning sweep (see specs/019-m5-2-transport-tuning).",
    )
    parser.add_argument(
        "--m5_2-smoke",
        action="store_true",
        help="M5.2: pre-flight smoke gate (FR-005a). Runs the 4-cell smoke "
        "set + M5.2-specific assertions before any cohort dispatches.",
    )
    parser.add_argument(
        "--m5_2-modal-region",
        default="eu-west-1",
        help="M5.2: Modal region for the dual-protocol deploy (default eu-west-1).",
    )
    parser.add_argument(
        "--m5_2-modal-token-env",
        default="MODAL_BENCH_TOKEN",
        help="M5.2: env-var name carrying the bearer token (token VALUE never logged).",
    )
    parser.add_argument(
        "--m5_2-modal-endpoint",
        default=None,
        help="M5.2: pre-existing endpoint "
        "'grpc=tcp+plaintext://...,rest_https_edge=https://...,"
        "rest_plain_tcp=tcp+plaintext://...' (implies --m5_2-skip-deploy).",
    )
    parser.add_argument(
        "--m5_2-skip-deploy",
        action="store_true",
        help="M5.2: skip deploy and reuse --m5_2-modal-endpoint.",
    )
    parser.add_argument(
        "--m5_2-n",
        type=int,
        default=250,
        help="M5.2: per-cohort sample size (default 250 per FR-011; "
        "borderline-expand cascade does NOT expand beyond this).",
    )
    parser.add_argument(
        "--m5_2-warmup-n",
        type=int,
        default=20,
        help="M5.2: warmup requests per (path x protocol) before measurement.",
    )
    parser.add_argument(
        "--m5_2-rtt-validity-threshold-ms",
        type=float,
        default=1.0,
        help="M5.2: refuse verdict below this median RTT (default 1.0 ms).",
    )
    parser.add_argument(
        "--m5_2-rtt-exercise-threshold-ms",
        type=float,
        default=20.0,
        help="M5.2: low_rtt_caveat fires below this median RTT (default 20.0 ms).",
    )
    parser.add_argument(
        "--m5_2-shim-overhead-warn-pct",
        type=float,
        default=5.0,
        help="M5.2: warn if shim overhead exceeds this fraction of cohort wallclock.",
    )
    parser.add_argument(
        "--m5_2-events-sidecar-out",
        type=Path,
        default=Path("bench-results/m5_2-full"),
        help="M5.2: events sidecar output directory.",
    )
    parser.add_argument(
        "--m5_2-report-out",
        type=Path,
        default=None,
        help="M5.2: override default report output prefix "
        "(default docs/benchmarks/m5_2-transport-vs-tuning).",
    )
    parser.add_argument(
        "--m5_2-skip-geolocation-lookup",
        action="store_true",
        help="M5.2: skip the best-effort ipinfo.io client-geolocation lookup.",
    )
    parser.add_argument(
        "--m5_2-run-id",
        default=None,
        help="M5.2: override the auto-generated run identifier (used for "
        "the events sidecar + run config filename).",
    )

    # ---- M5.1 mode (REST vs gRPC head-to-head on real wire) ----
    parser.add_argument(
        "--m5_1",
        action="store_true",
        help="Run the M5.1 REST-vs-gRPC head-to-head sweep (see specs/018-m5-1-rest-vs-grpc).",
    )
    parser.add_argument(
        "--m5_1-modal-region",
        default="eu-west-1",
        help="M5.1: Modal region for the dual-protocol deploy (default eu-west-1).",
    )
    parser.add_argument(
        "--m5_1-modal-token-env",
        default="MODAL_BENCH_TOKEN",
        help="M5.1: env-var name carrying the bearer token (token VALUE is never logged).",
    )
    parser.add_argument(
        "--m5_1-modal-endpoint",
        default=None,
        help="M5.1: pre-existing endpoint in the form "
        "'grpc=tcp+plaintext://...,rest=https://...' (implies --m5_1-skip-deploy).",
    )
    parser.add_argument(
        "--m5_1-skip-deploy",
        action="store_true",
        help="M5.1: skip deploy and reuse --m5_1-modal-endpoint.",
    )
    parser.add_argument(
        "--m5_1-rtt-validity-threshold-ms",
        type=float,
        default=1.0,
        help="M5.1: refuse verdict below this median RTT (default 1.0 ms).",
    )
    parser.add_argument(
        "--m5_1-rtt-exercise-threshold-ms",
        type=float,
        default=20.0,
        help="M5.1: low_rtt_caveat fires below this median RTT (default 20.0 ms).",
    )
    parser.add_argument(
        "--m5_1-warmup-n",
        type=int,
        default=20,
        help="M5.1: warmup requests per (path × protocol) before measurement.",
    )
    parser.add_argument(
        "--m5_1-shim-overhead-warn-pct",
        type=float,
        default=5.0,
        help="M5.1: warn if shim overhead exceeds this fraction of cohort wallclock.",
    )
    parser.add_argument(
        "--m5_1-report-out",
        type=Path,
        default=None,
        help="M5.1: override default report output directory (default docs/benchmarks/).",
    )
    parser.add_argument(
        "--m5_1-smoke",
        action="store_true",
        help=(
            "M5.1: smoke mode — 3 cells (chat_stream c=1, chat_stream c=4, embed c=4) "
            "at n=10 per cohort with rtt_probe_n=4. Covers every code path "
            "(REST, all 4 gRPC sub-cohort kinds, both metric types) in ~90s "
            "including Modal deploy. Pair with --m5_1-skip-deploy to iterate "
            "in ~15-25s against a long-lived deploy."
        ),
    )

    # ---- M5 mode (cross-host time-axis validation) ----
    parser.add_argument(
        "--m5",
        action="store_true",
        help="Run the M5 cross-host sweep (see specs/017-m5-cross-host-validation).",
    )
    parser.add_argument(
        "--m5-modal-region",
        default="auto-far",
        help=(
            "M5: Modal region for the cross-host gRPC server. Sentinel "
            "`auto-far` resolves to us-east-1; override with eu-west-1 or "
            "ap-southeast-1 from a US/EU operator to land in the 30–100 ms RTT band."
        ),
    )
    parser.add_argument(
        "--m5-modal-token-env",
        default="MODAL_BENCH_TOKEN",
        help="M5: env-var name containing the per-deploy bearer token (FR-002).",
    )
    parser.add_argument(
        "--m5-rtt-validity-threshold-ms",
        type=float,
        default=1.0,
        help=(
            "M5: refuse to issue verdicts on cohorts whose measured median RTT "
            "is below this value (FR-004 same-host-fallback)."
        ),
    )
    parser.add_argument(
        "--m5-rtt-exercise-threshold-ms",
        type=float,
        default=20.0,
        help=(
            "M5: cohorts whose median RTT is below this value get "
            "`low_rtt_caveat: true` (FR-004 exercise-threshold)."
        ),
    )
    parser.add_argument(
        "--m5-warmup-n",
        type=int,
        default=32,
        help="M5: per-path warmup cohort size (R-5). Set to 0 to disable (not recommended).",
    )
    parser.add_argument(
        "--m5-skip-deploy",
        action="store_true",
        help=(
            "M5: skip the Modal deploy/teardown handshake; connect to an "
            "already-running endpoint via --m5-modal-endpoint."
        ),
    )
    parser.add_argument(
        "--m5-modal-endpoint",
        default=None,
        help=(
            "M5: explicit Modal tunnel endpoint (host:port) for use with "
            "--m5-skip-deploy. Required when --m5-skip-deploy is set."
        ),
    )

    # ---- run (default) ----
    parser.add_argument("--proxy-url", required=False, default=None)
    parser.add_argument("--native-url", required=False, default=None)
    parser.add_argument("--corpus", type=Path, default=_DEFAULT_CORPUS)
    parser.add_argument("--concurrency", default="1,4,8")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output-dir", type=Path, default=Path("bench-results"))
    parser.add_argument("--compare-to", type=Path, default=None)
    parser.add_argument("--regression-threshold", type=float, default=0.10)
    parser.add_argument("--save-baseline", type=Path, default=None)
    parser.add_argument(
        "--streaming",
        action="store_true",
        help="Use streaming endpoints; also benchmarks gRPC-direct if --grpc-direct-addr is set",
    )
    parser.add_argument(
        "--grpc-direct-addr",
        default=None,
        metavar="HOST:PORT",
        help="gRPC-direct address for streaming benchmark (e.g. localhost:50051)",
    )

    return parser


async def _run(args: argparse.Namespace) -> int:
    import os

    proxy_url: str | None = args.proxy_url or os.environ.get("BENCH_PROXY_URL")
    native_url: str | None = args.native_url or os.environ.get("BENCH_NATIVE_URL")

    if not proxy_url or not native_url:
        print(
            "Error: --proxy-url and --native-url are required"
            " (or set BENCH_PROXY_URL / BENCH_NATIVE_URL)",
            file=sys.stderr,
        )
        return 2

    try:
        concurrency_levels = [int(c.strip()) for c in str(args.concurrency).split(",")]
    except ValueError:
        print("Error: --concurrency must be a comma-separated list of integers", file=sys.stderr)
        return 2

    corpus_path: Path = args.corpus
    if not corpus_path.exists():
        print(f"Error: corpus file not found: {corpus_path}", file=sys.stderr)
        return 3

    try:
        samples = load_corpus(corpus_path)
    except Exception as exc:
        print(f"Error loading corpus: {exc}", file=sys.stderr)
        return 3

    cfg = BenchmarkConfig(
        proxy_url=proxy_url,
        native_url=native_url,
        corpus_path=str(corpus_path),
        concurrency_levels=concurrency_levels,
        timeout_seconds=args.timeout,
        output_dir=str(args.output_dir),
        compare_to=str(args.compare_to) if args.compare_to else None,
        regression_threshold=args.regression_threshold,
    )
    meta = build_run_meta(cfg)

    streaming: bool = getattr(args, "streaming", False)
    grpc_direct_addr: str | None = getattr(args, "grpc_direct_addr", None)

    all_results: list[RequestResult] = []
    for conc in concurrency_levels:
        for target in ("proxy", "native"):
            url = proxy_url if target == "proxy" else native_url
            mode = "streaming" if streaming else "non-streaming"
            print(f"Running {target} ({mode}) @ concurrency={conc} …", flush=True)
            try:
                if streaming:
                    results = await run_target_streaming(
                        target=target,
                        url=url,
                        samples=samples,
                        concurrency=conc,
                        timeout=args.timeout,
                    )
                else:
                    results = await run_target(
                        target=target,
                        url=url,
                        samples=samples,
                        concurrency=conc,
                        timeout=args.timeout,
                    )
            except Exception as exc:
                print(f"Error reaching {target} at {url}: {exc}", file=sys.stderr)
                return 3
            all_results.extend(results)

        if streaming and grpc_direct_addr:
            print(f"Running grpc-direct (streaming) @ concurrency={conc} …", flush=True)
            try:
                grpc_results = await run_grpc_target_streaming(
                    addr=grpc_direct_addr,
                    samples=samples,
                    concurrency=conc,
                    timeout=args.timeout,
                )
            except Exception as exc:
                print(f"Error reaching grpc-direct at {grpc_direct_addr}: {exc}", file=sys.stderr)
                return 3
            all_results.extend(grpc_results)

    summaries = compute_summaries(all_results)
    run = BenchmarkRun(meta=meta, summaries=summaries, raw_results=all_results)

    output_dir: Path = args.output_dir
    json_path = write_json(run, output_dir)
    csv_path = write_csv(run, output_dir)
    md_path = write_summary_md(run, output_dir)
    print(f"Results written to {output_dir}/: {json_path.name}, {csv_path.name}, {md_path.name}")

    if args.save_baseline:
        import shutil

        save_path: Path = args.save_baseline
        save_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(json_path, save_path)
        print(f"Baseline saved to {save_path}")

    if args.compare_to:
        baseline_path: Path = args.compare_to
        if not baseline_path.exists():
            print(f"Warning: baseline file not found: {baseline_path}", file=sys.stderr)
            return 0
        try:
            baseline_run = load_run(baseline_path)
            report = compare(baseline_run, run, threshold=args.regression_threshold)
        except Exception as exc:
            print(f"Warning: comparison failed: {exc}", file=sys.stderr)
            return 0
        _print_comparison(report)
        if report.has_regression:
            return 1

    return 0


def _print_comparison(report: ComparisonReport) -> None:
    if not report.has_regression:
        print("No regressions detected.")
        return
    print(f"Regressions detected (threshold={report.threshold:.0%}):")
    print(f"{'Metric':<50} {'Baseline':>10} {'New':>10} {'Δ':>8}")
    print("-" * 82)
    for reg in report.regressions:
        print(
            f"{reg.metric:<50} {reg.baseline_value:>10.3f}"
            f" {reg.new_value:>10.3f} {reg.delta_pct:>+8.1%}"
        )


def _parse_widths(spec: str) -> tuple[int, ...]:
    if spec == "all":
        return (2048, 4096, 8192)
    if spec.isdigit():
        v = int(spec)
        if v <= 0:
            raise ValueError("width must be a positive integer")
        return (v,)
    if spec in ("2048", "4096", "8192"):
        return (int(spec),)
    raise ValueError(f"--width must be 2048|4096|8192|all|<positive_integer>, got {spec!r}")


def _parse_axes(spec: str) -> tuple[str, ...]:
    if spec == "all":
        return ("max_message_size", "keepalive", "compression", "http2_framing")
    return (spec,)


def _parse_paths(spec: str) -> tuple[str, ...]:
    if spec == "both":
        return ("embed", "chat_stream")
    return (spec,)


def _run_m3(args: argparse.Namespace) -> int:
    from datetime import datetime

    from vllm_grpc_bench import m3_sweep
    from vllm_grpc_bench.channel_config import preset_by_name

    if args.reanalyze is not None:
        return _run_m3_reanalyze(args)

    if args.p2_revision is not None and args.frozen_channel is None:
        print(
            "Error: --p2-revision requires --frozen-channel to be set",
            file=sys.stderr,
        )
        return 2
    if args.frozen_channel is not None:
        try:
            preset_by_name(args.frozen_channel)
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    try:
        widths = _parse_widths(str(args.width))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    axes = _parse_axes(args.axis)
    paths = _parse_paths(args.path)

    if args.smoke:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        smoke_path = Path("bench-results") / f"m3-smoke-{ts}.json"
        return asyncio.run(
            m3_sweep.run_smoke(
                axis=axes[0],  # type: ignore[arg-type]
                width=widths[0],
                path=paths[0],  # type: ignore[arg-type]
                seed=args.seed,
                out_path=smoke_path,
            )
        )

    cohorts = asyncio.run(
        m3_sweep.run_sweep(
            axes=axes,  # type: ignore[arg-type]
            widths=widths,
            paths=paths,  # type: ignore[arg-type]
            iterations=args.iters_per_cell,
            seed=args.seed,
        )
    )
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    is_p2 = args.p2_revision is not None
    base = "m3-schema-tuning" if is_p2 else "m3-channel-tuning"
    json_path = out_dir / f"{base}.json"

    recs: list[dict[str, object]] = []
    for axis in axes:
        for r in m3_sweep.build_recommendations(cohorts, axis=axis):  # type: ignore[arg-type]
            recs.append(m3_sweep.recommendation_to_dict(r))

    payload = {
        "mode": "p2" if is_p2 else "p1",
        "axes": list(axes),
        "widths": list(widths),
        "paths": list(paths),
        "iterations_per_cell": args.iters_per_cell,
        "seed": args.seed,
        "p2_revision": args.p2_revision,
        "frozen_channel": args.frozen_channel,
        "cohorts": [m3_sweep.cohort_to_dict(c) for c in cohorts],
        "recommendations": recs,
    }
    try:
        json_path.write_text(json.dumps(payload, indent=2, default=str))
    except OSError as exc:
        print(f"Error writing report: {exc}", file=sys.stderr)
        return 4
    print(f"M3 report written to {json_path}")

    has_unmeasurable = any(not c.measurable for c in cohorts)
    return 3 if has_unmeasurable else 0


def _run_m3_reanalyze(args: argparse.Namespace) -> int:
    """Phase A (US3) — read an existing M3 sweep JSON, compute time/TTFT
    verdicts using ``build_recommendations(metric=...)``, and write a sibling
    ``<stem>-time.json`` with the time-axis recommendations and a
    ``p1_frozen_config_time`` field.

    Per FR-014: embed cells use ``metric="time"``; chat_stream cells use
    ``metric="ttft"``. The two builds are concatenated into a single
    recommendations list in the output. Cohorts and metadata are passed
    through unchanged from the input JSON; per-iteration ``samples`` arrays
    are stripped (slim format).
    """
    from vllm_grpc_bench import m3_sweep

    in_path: Path = args.reanalyze
    if not in_path.exists():
        print(f"Error: --reanalyze input not found: {in_path}", file=sys.stderr)
        return 3
    try:
        payload = json.loads(in_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error reading {in_path}: {exc}", file=sys.stderr)
        return 3

    try:
        cohorts = [m3_sweep.cohort_from_dict(c) for c in payload.get("cohorts", [])]
    except (KeyError, ValueError, TypeError) as exc:
        print(f"Error reconstructing cohorts from {in_path}: {exc}", file=sys.stderr)
        return 3

    if not cohorts:
        print(f"Error: no cohorts in {in_path}", file=sys.stderr)
        return 3

    axes_in_input = list(payload.get("axes", []))
    if not axes_in_input:
        print(f"Error: no axes recorded in {in_path}", file=sys.stderr)
        return 3

    recs: list[dict[str, object]] = []
    for axis in axes_in_input:
        # Embed cells: metric="time" (total per-RPC wall-clock).
        for r in m3_sweep.build_recommendations(cohorts, axis=axis, metric="time"):
            if r.applies_to_path == "embed":
                recs.append(m3_sweep.recommendation_to_dict(r))
        # chat_stream cells: metric="ttft" (per FR-014). The ttft path filters
        # to chat_stream internally, so all returned recs are chat_stream.
        for r in m3_sweep.build_recommendations(cohorts, axis=axis, metric="ttft"):
            recs.append(m3_sweep.recommendation_to_dict(r))

    # FR-008-equivalent for the time metric: union of each axis's winning config
    # if recommend, else M1_BASELINE for that axis. If any axis has any
    # noise_bounded verdict, fall back to M1_BASELINE for that axis (we cannot
    # freeze a config we couldn't defensibly verdict).
    p1_frozen_config_time: dict[str, str] = {}
    for axis in ("max_message_size", "keepalive", "compression", "http2_framing"):
        axis_recs = [r for r in recs if r["axis"] == axis]
        verdicts = {str(r["verdict"]) for r in axis_recs}
        winners: set[str] = {
            str(r["winning_config"])
            for r in axis_recs
            if r["verdict"] == "recommend" and r.get("winning_config")
        }
        if "noise_bounded" in verdicts or not winners:
            p1_frozen_config_time[axis] = "default"
        elif len(winners) == 1:
            p1_frozen_config_time[axis] = next(iter(winners))
        else:
            # Multiple winning configs across width/path/corpus — record as
            # "split" so the report's reader knows the axis didn't converge on
            # one config; revisit in M4.
            p1_frozen_config_time[axis] = "split"

    has_recommend = any(r["verdict"] == "recommend" for r in recs)
    has_noise_bounded = any(r["verdict"] == "noise_bounded" for r in recs)
    p1_frozen_config_time["rationale"] = (
        f"Time-metric Phase A re-analysis (US3) of {in_path.name}; "
        f"recommend={has_recommend}, noise_bounded={has_noise_bounded}. "
        "Cells with noise_bounded verdicts re-measure under M4's shared-baseline "
        "harness (FR-013)."
    )

    # Build the output payload: same shape as input, slim cohorts, new
    # recommendations, time-axis frozen config field.
    slim_cohorts = []
    for c in payload.get("cohorts", []):
        cc = dict(c)
        cc.pop("samples", None)
        slim_cohorts.append(cc)

    out_payload = dict(payload)
    out_payload["mode"] = "p1-time-reanalysis"
    out_payload["cohorts"] = slim_cohorts
    out_payload["recommendations"] = recs
    out_payload["p1_frozen_config_time"] = p1_frozen_config_time
    out_payload["reanalyze_source"] = str(in_path)

    out_path = in_path.with_name(in_path.stem + "-time.json")
    try:
        out_path.write_text(json.dumps(out_payload, indent=2, default=str))
    except OSError as exc:
        print(f"Error writing {out_path}: {exc}", file=sys.stderr)
        return 4
    print(f"Phase A re-analysis written to {out_path}")
    print(
        f"  recommendations: {len(recs)} "
        f"(recommend={sum(1 for r in recs if r['verdict'] == 'recommend')}, "
        f"no_winner={sum(1 for r in recs if r['verdict'] == 'no_winner')}, "
        f"noise_bounded={sum(1 for r in recs if r['verdict'] == 'noise_bounded')}, "
        f"not_measurable={sum(1 for r in recs if r['verdict'] == 'not_measurable')})"
    )
    return 0


def _build_m4_config(args: argparse.Namespace) -> M4SweepConfig:
    from vllm_grpc_bench.m3_types import M4SweepConfig, PacingMode

    pacing_raw = args.m4_pacing or "no_pacing"
    if pacing_raw not in ("paced", "no_pacing"):
        raise ValueError(f"--no-pacing/--paced expected, got {pacing_raw!r}")
    pacing_mode: PacingMode = pacing_raw  # type: ignore[assignment]
    shared_baseline = True if args.m4_shared_baseline is None else args.m4_shared_baseline
    try:
        widths = tuple(int(w.strip()) for w in str(args.widths).split(",") if w.strip())
        paths = tuple(p.strip() for p in str(args.paths).split(",") if p.strip())
        axes = tuple(a.strip() for a in str(args.axes).split(",") if a.strip())
        schema_candidates = tuple(
            s.strip() for s in str(args.schema_candidates).split(",") if s.strip()
        )
    except ValueError as exc:
        raise SystemExit(2) from exc

    canonical_width = 4096 if 4096 in widths else widths[0]
    return M4SweepConfig(
        pacing_mode=pacing_mode,
        shared_baseline=shared_baseline,
        baseline_n=int(args.baseline_n),
        candidate_n=int(args.candidate_n),
        expand_n=int(args.expand_n),
        warmup_n=int(args.warmup_n),
        baseline_cv_warn=float(args.baseline_cv_warn),
        widths=widths,
        paths=paths,  # type: ignore[arg-type]
        axes=axes,
        schema_candidates=schema_candidates,
        schema_canonical_width=canonical_width,
        skip_schema=bool(args.skip_schema),
        seed=int(args.seed),
    )


def _run_m4(args: argparse.Namespace) -> int:
    from vllm_grpc_bench import m4_sweep

    if args.m4_pacing is None:
        args.m4_pacing = "no_pacing"
    if args.m4_shared_baseline is None:
        args.m4_shared_baseline = True
    if args.expand_n <= args.candidate_n:
        print(
            "Error: --expand-n must be greater than --candidate-n "
            f"(got expand_n={args.expand_n}, candidate_n={args.candidate_n})",
            file=sys.stderr,
        )
        return 2
    if args.baseline_n < 100:
        print(
            "Error: --baseline-n must be >= 100 (FR-002)",
            file=sys.stderr,
        )
        return 2
    try:
        config = _build_m4_config(args)
    except (ValueError, SystemExit) as exc:
        print(f"Error: invalid M4 sweep configuration: {exc}", file=sys.stderr)
        return 2

    run = asyncio.run(m4_sweep.run_m4_sweep(config, progress=True))
    try:
        m4_sweep.validate_run(run)
    except ValueError as exc:
        print(f"Error: M4 run validation failed: {exc}", file=sys.stderr)
        return 4

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    docs_dir = Path("docs/benchmarks")
    docs_dir.mkdir(parents=True, exist_ok=True)
    json_path = docs_dir / "m4-time-axis-tuning.json"
    md_path = docs_dir / "m4-time-axis-tuning.md"

    from vllm_grpc_bench.reporter import write_m4_json, write_m4_markdown

    write_m4_json(run, json_path)
    write_m4_markdown(run, md_path)
    n_recommend = sum(1 for r in run.recommendations if r.verdict == "recommend")
    n_no_winner = sum(1 for r in run.recommendations if r.verdict == "no_winner")
    n_client_bound = sum(1 for r in run.recommendations if r.verdict == "client_bound")
    n_super = len(run.supersedes)
    print(
        f"M4 sweep complete: {n_recommend} recommend, {n_no_winner} no_winner, "
        f"{n_client_bound} client_bound. {n_super} M3 cells superseded."
    )
    return 0


def _build_m5_config(args: argparse.Namespace) -> object:
    """Build an ``M5SweepConfig`` from ``argparse``-parsed args.

    Reuses ``_build_m4_config`` for the inherited M4 surface and layers M5
    flags on top. Raises ``SystemExit(2)`` on validation failure (mirrors
    M4's behavior).
    """
    from vllm_grpc_bench.m5_sweep import M5SweepConfig

    m4_config = _build_m4_config(args)
    # M5's default baseline_cv_warn is 0.10 (the M4 default is 0.05) to
    # absorb real-network jitter (per plan.md). Operators can override via
    # --baseline-cv-warn.
    from dataclasses import replace as _replace

    m4_config = _replace(m4_config, baseline_cv_warn=max(float(args.baseline_cv_warn), 0.05))

    region_raw = str(args.m5_modal_region)
    if region_raw == "auto-far":
        region_raw = "us-east-1"
    return M5SweepConfig(
        base=m4_config,
        modal_region=region_raw,
        token_env=str(args.m5_modal_token_env),
        rtt_validity_threshold_ms=float(args.m5_rtt_validity_threshold_ms),
        rtt_exercise_threshold_ms=float(args.m5_rtt_exercise_threshold_ms),
        warmup_n=int(args.m5_warmup_n),
        skip_deploy_endpoint=str(args.m5_modal_endpoint) if args.m5_modal_endpoint else None,
    )


def _validate_m5_args(args: argparse.Namespace) -> int:
    """Pre-flight validation for M5 mode. Returns exit code; 0 means OK."""
    import os as _os

    # Mutual exclusion with --m3 / --m4.
    if getattr(args, "m3", False) or getattr(args, "m4", False):
        print(
            "Error: --m5 is mutually exclusive with --m3 and --m4",
            file=sys.stderr,
        )
        return 2
    if bool(args.m5_skip_deploy) and not args.m5_modal_endpoint:
        print(
            "Error: --m5-skip-deploy requires --m5-modal-endpoint",
            file=sys.stderr,
        )
        return 2
    if args.expand_n <= args.candidate_n:
        print(
            "Error: --expand-n must be greater than --candidate-n",
            file=sys.stderr,
        )
        return 2
    if args.baseline_n < 100:
        print(
            "Error: --baseline-n must be >= 100 (FR-008)",
            file=sys.stderr,
        )
        return 2
    if float(args.m5_rtt_exercise_threshold_ms) < float(args.m5_rtt_validity_threshold_ms):
        print(
            "Error: --m5-rtt-exercise-threshold-ms must be >= --m5-rtt-validity-threshold-ms",
            file=sys.stderr,
        )
        return 2
    # Token env var must be set unless we're in deploy mode (still required for
    # provide_endpoint).
    token_env = str(args.m5_modal_token_env)
    if not _os.environ.get(token_env):
        print(
            f"Error: bearer-token env var {token_env!r} is unset; "
            "export it before running --m5 (see quickstart.md)",
            file=sys.stderr,
        )
        return 2
    return 0


def _run_m5(args: argparse.Namespace) -> int:
    import asyncio as _asyncio

    from vllm_grpc_bench import m5_sweep
    from vllm_grpc_bench.reporter import write_m5_json, write_m5_markdown

    rc = _validate_m5_args(args)
    if rc != 0:
        return rc
    # The M4 helper needs m4_pacing/m4_shared_baseline defaults to be filled in.
    if args.m4_pacing is None:
        args.m4_pacing = "no_pacing"
    if args.m4_shared_baseline is None:
        args.m4_shared_baseline = True
    try:
        config = _build_m5_config(args)
    except (ValueError, SystemExit) as exc:
        print(f"Error: invalid M5 sweep configuration: {exc}", file=sys.stderr)
        return 2

    try:
        run = _asyncio.run(m5_sweep.run_m5_sweep(config, progress=True))  # type: ignore[arg-type]
    except Exception as exc:
        # Map RTT-validity failure → exit code 8 per CLI contract.
        msg = str(exc)
        if "rtt_below_validity_threshold" in msg or "shared-baseline measurement failed" in msg:
            print(f"Error: M5 RTT validity check failed: {exc}", file=sys.stderr)
            return 8
        # Modal handshake failures → exit code 3.
        from vllm_grpc_bench.modal_endpoint import ModalDeployError

        if isinstance(exc, ModalDeployError):
            print(f"Error: Modal handshake failed: {exc}", file=sys.stderr)
            return 3
        raise

    docs_dir = Path("docs/benchmarks")
    docs_dir.mkdir(parents=True, exist_ok=True)
    json_path = docs_dir / "m5-cross-host-validation.json"
    md_path = docs_dir / "m5-cross-host-validation.md"
    write_m5_json(run, json_path)
    write_m5_markdown(run, md_path)

    n_recommend = sum(1 for r in run.recommendations if r.verdict == "recommend")
    n_no_winner = sum(1 for r in run.recommendations if r.verdict == "no_winner")
    n_client_bound = sum(1 for r in run.recommendations if r.verdict == "client_bound")
    n_server_bound = sum(1 for r in run.recommendations if r.verdict == "server_bound")
    n_super = len(run.supersedes_m4)
    n_super_changed = sum(1 for e in run.supersedes_m4 if e.verdict_changed)
    assert run.m5_metadata is not None
    rtt_med = run.m5_metadata.m5_rtt_summary_ms.median_ms
    n_cohorts = sum(1 for c in run.cohorts if not c.discarded)
    print(
        f"M5 sweep complete: {n_recommend} recommend, {n_no_winner} no_winner, "
        f"{n_client_bound} client_bound, {n_server_bound} server_bound. "
        f"{n_super} M4 cells superseded ({n_super_changed} verdict-changed, "
        f"{n_super - n_super_changed} verdict-confirmed). "
        f"RTT median {rtt_med:.1f} ms across {n_cohorts} cohorts."
    )
    return 0


def _validate_m5_1_args(args: argparse.Namespace) -> int:
    """Pre-flight validation for M5.1 mode. Returns exit code; 0 means OK."""
    import os as _os

    if getattr(args, "m3", False) or getattr(args, "m4", False) or getattr(args, "m5", False):
        print(
            "Error: --m5_1 is mutually exclusive with --m3, --m4, and --m5",
            file=sys.stderr,
        )
        return 2
    if bool(args.m5_1_skip_deploy) and not args.m5_1_modal_endpoint:
        print(
            "Error: --m5_1-skip-deploy requires --m5_1-modal-endpoint",
            file=sys.stderr,
        )
        return 2
    if float(args.m5_1_rtt_exercise_threshold_ms) < float(args.m5_1_rtt_validity_threshold_ms):
        print(
            "Error: --m5_1-rtt-exercise-threshold-ms must be >= --m5_1-rtt-validity-threshold-ms",
            file=sys.stderr,
        )
        return 2
    token_env = str(args.m5_1_modal_token_env)
    if not _os.environ.get(token_env):
        print(
            f"Error: bearer-token env var {token_env!r} is unset; "
            "export it before running --m5_1 "
            "(see specs/018-m5-1-rest-vs-grpc/quickstart.md)",
            file=sys.stderr,
        )
        return 4
    return 0


def _run_m5_1(args: argparse.Namespace) -> int:
    """M5.1 sweep entry-point — dispatches via run_m5_1_sweep."""
    import asyncio as _asyncio

    rc = _validate_m5_1_args(args)
    if rc != 0:
        return rc

    from vllm_grpc_bench.m5_1_sweep import run_m5_1_sweep

    # Endpoint resolution: in skip-deploy mode the endpoint string carries
    # both URLs in a `grpc=...,rest=...` form. In full-deploy mode the
    # harness would call provide_rest_grpc_endpoint; for CLI parity with
    # the existing M5 pattern we accept the endpoints as flags rather than
    # building the deploy plumbing here.
    rest_url: str | None = None
    grpc_target: str | None = None
    if args.m5_1_modal_endpoint:
        for pair in str(args.m5_1_modal_endpoint).split(","):
            if pair.startswith("grpc="):
                grpc_target = _strip_endpoint_scheme(pair[len("grpc=") :])
            elif pair.startswith("rest="):
                rest_url = pair[len("rest=") :]
        if not rest_url or not grpc_target:
            print(
                "Error: --m5_1-modal-endpoint must include both 'grpc=' and 'rest=' parts",
                file=sys.stderr,
            )
            return 2

    if rest_url is None or grpc_target is None:
        # Full-deploy path: deploy the dual-protocol Modal app, run the
        # sweep against the returned URLs, tear down at exit.
        async def _run_with_deploy() -> int:
            from vllm_grpc_bench.modal_endpoint import (
                ModalDeployError,
                provide_rest_grpc_endpoint,
            )

            try:
                async with provide_rest_grpc_endpoint(
                    region=str(args.m5_1_modal_region),
                    token_env=str(args.m5_1_modal_token_env),
                ) as endpoints:
                    cfg = _build_m5_1_config(
                        args,
                        rest_url=endpoints.rest_url,
                        grpc_target=endpoints.grpc_url,
                    )
                    run = await run_m5_1_sweep(cfg, progress=True)
            except ModalDeployError as exc:
                print(f"Error: Modal deploy failed: {exc}", file=sys.stderr)
                return 3
            return _emit_m5_1_outputs(args, run)

        return _asyncio.run(_run_with_deploy())

    # Skip-deploy path.
    cfg = _build_m5_1_config(args, rest_url=rest_url, grpc_target=grpc_target)
    try:
        run = _asyncio.run(run_m5_1_sweep(cfg, progress=True))
    except Exception as exc:  # noqa: BLE001
        print(f"Error: M5.1 sweep failed: {exc}", file=sys.stderr)
        return 7
    return _emit_m5_1_outputs(args, run)


def _strip_endpoint_scheme(endpoint: str) -> str:
    for prefix in ("tcp+plaintext://", "tcp://", "grpcs://", "grpc://", "https://"):
        if endpoint.startswith(prefix):
            return endpoint[len(prefix) :]
    return endpoint


def _build_m5_1_config(
    args: argparse.Namespace, *, rest_url: str, grpc_target: str
) -> M5_1SweepConfig:
    """Construct the M5_1SweepConfig from argparse args."""
    from vllm_grpc_bench.m5_1_sweep import SMOKE_CELLS, M5_1SweepConfig

    smoke = bool(getattr(args, "m5_1_smoke", False))
    # Warmup: smoke uses 5 (enough to flush HTTP/2 cold-channel handshake
    # cost without inflating wall-clock); full sweep uses --m5_1-warmup-n
    # (default 20).
    warmup_n = 5 if smoke else int(args.m5_1_warmup_n)
    return M5_1SweepConfig(
        rest_url=rest_url,
        grpc_target=grpc_target,
        token_env_var=str(args.m5_1_modal_token_env),
        modal_region=str(args.m5_1_modal_region),
        n_per_cohort=10 if smoke else 100,
        rtt_probe_n=4 if smoke else 16,
        warmup_n=warmup_n,
        low_rtt_threshold_ms=float(args.m5_1_rtt_exercise_threshold_ms),
        shim_overhead_warn_pct=float(args.m5_1_shim_overhead_warn_pct),
        cells_override=list(SMOKE_CELLS) if smoke else None,
    )


# ---------------------------------------------------------------------------
# M5.2 mode dispatcher (T039 + T040 + T042)
# ---------------------------------------------------------------------------


def _validate_m5_2_args(args: argparse.Namespace) -> int:
    """Pre-flight validation for M5.2 mode. Returns exit code; 0 means OK."""
    import os as _os

    # Mutual exclusion with M3 / M4 / M5 / M5.1 modes.
    if (
        getattr(args, "m3", False)
        or getattr(args, "m4", False)
        or getattr(args, "m5", False)
        or getattr(args, "m5_1", False)
    ):
        print(
            "Error: --m5_2 is mutually exclusive with --m3, --m4, --m5, and --m5_1",
            file=sys.stderr,
        )
        return 2
    if bool(args.m5_2_skip_deploy) and not args.m5_2_modal_endpoint:
        print(
            "Error: --m5_2-skip-deploy requires --m5_2-modal-endpoint",
            file=sys.stderr,
        )
        return 2
    if float(args.m5_2_rtt_exercise_threshold_ms) < float(args.m5_2_rtt_validity_threshold_ms):
        print(
            "Error: --m5_2-rtt-exercise-threshold-ms must be >= --m5_2-rtt-validity-threshold-ms",
            file=sys.stderr,
        )
        return 2
    token_env = str(args.m5_2_modal_token_env)
    if not _os.environ.get(token_env):
        print(
            f"Error: bearer-token env var {token_env!r} is unset; "
            "export it before running --m5_2 "
            "(see specs/019-m5-2-transport-tuning/quickstart.md)",
            file=sys.stderr,
        )
        return 4
    return 0


def _parse_m5_2_endpoint(spec: str) -> tuple[str, str, str] | None:
    """Parse the ``--m5_2-modal-endpoint`` form into (grpc, https_edge, plain_tcp).

    Returns ``None`` on malformed input. The format is
    ``grpc=...,rest_https_edge=...,rest_plain_tcp=...``.
    """
    grpc: str | None = None
    edge: str | None = None
    tcp: str | None = None
    for pair in spec.split(","):
        if pair.startswith("grpc="):
            grpc = _strip_endpoint_scheme(pair[len("grpc=") :])
        elif pair.startswith("rest_https_edge="):
            edge = pair[len("rest_https_edge=") :]
        elif pair.startswith("rest_plain_tcp="):
            tcp = pair[len("rest_plain_tcp=") :]
    if grpc and edge and tcp:
        return grpc, edge, tcp
    return None


def _build_m5_2_config(
    args: argparse.Namespace,
    *,
    rest_https_edge_url: str,
    rest_plain_tcp_url: str,
    grpc_target: str,
    https_edge_endpoint: str,
    smoke: bool,
    run_id: str,
) -> object:
    from vllm_grpc_bench.m5_2_sweep import SMOKE_CELLS, M5_2SweepConfig

    cells_override: tuple | None = SMOKE_CELLS if smoke else None
    n = 5 if smoke else int(args.m5_2_n)
    warmup_n = 2 if smoke else int(args.m5_2_warmup_n)
    rtt_probe_n = 4 if smoke else 16
    return M5_2SweepConfig(
        rest_https_edge_url=rest_https_edge_url,
        rest_plain_tcp_url=rest_plain_tcp_url,
        grpc_target=grpc_target,
        run_id=run_id,
        events_sidecar_out_dir=Path(args.m5_2_events_sidecar_out),
        token_env_var=str(args.m5_2_modal_token_env),
        modal_region=str(args.m5_2_modal_region),
        https_edge_endpoint=https_edge_endpoint,
        n_per_cohort=n,
        expand_n=n,
        rtt_probe_n=rtt_probe_n,
        warmup_n=warmup_n,
        rtt_validity_threshold_ms=float(args.m5_2_rtt_validity_threshold_ms),
        rtt_exercise_threshold_ms=float(args.m5_2_rtt_exercise_threshold_ms),
        shim_overhead_warn_pct=float(args.m5_2_shim_overhead_warn_pct),
        cells_override=cells_override,
        smoke=smoke,
    )


def _run_m5_2(args: argparse.Namespace) -> int:
    """M5.2 sweep entry-point — dispatches via run_m5_2_sweep."""
    import asyncio as _asyncio
    import uuid as _uuid

    rc = _validate_m5_2_args(args)
    if rc != 0:
        return rc

    smoke = bool(getattr(args, "m5_2_smoke", False))
    run_id = (
        str(args.m5_2_run_id)
        if getattr(args, "m5_2_run_id", None)
        else f"m5_2-{'smoke-' if smoke else ''}{_uuid.uuid4().hex[:12]}"
    )

    # Endpoint resolution.
    rest_https_edge_url: str | None = None
    rest_plain_tcp_url: str | None = None
    grpc_target: str | None = None
    if args.m5_2_modal_endpoint:
        parsed = _parse_m5_2_endpoint(str(args.m5_2_modal_endpoint))
        if parsed is None:
            print(
                "Error: --m5_2-modal-endpoint must include 'grpc=', 'rest_https_edge=', "
                "and 'rest_plain_tcp=' parts",
                file=sys.stderr,
            )
            return 2
        grpc_target, rest_https_edge_url, rest_plain_tcp_url = parsed

    async def _run_with_deploy() -> int:
        nonlocal rest_https_edge_url, rest_plain_tcp_url, grpc_target
        from vllm_grpc_bench.modal_endpoint import (
            ModalDeployError,
            provide_rest_grpc_endpoint,
        )

        try:
            if rest_https_edge_url is None:
                async with provide_rest_grpc_endpoint(
                    region=str(args.m5_2_modal_region),
                    token_env=str(args.m5_2_modal_token_env),
                    with_rest_plain_tcp=True,
                ) as endpoints:
                    assert endpoints.rest_plain_tcp_url is not None
                    rest_https_edge_url = endpoints.rest_url
                    rest_plain_tcp_url = _strip_endpoint_scheme(endpoints.rest_plain_tcp_url)
                    # The plain-TCP URL needs an explicit http:// scheme for
                    # httpx; strip the tcp+plaintext:// prefix and re-prepend.
                    if not rest_plain_tcp_url.startswith("http://"):
                        rest_plain_tcp_url = f"http://{rest_plain_tcp_url}"
                    grpc_target = endpoints.grpc_url
                    cfg = _build_m5_2_config(
                        args,
                        rest_https_edge_url=rest_https_edge_url,
                        rest_plain_tcp_url=rest_plain_tcp_url,
                        grpc_target=grpc_target,
                        https_edge_endpoint=endpoints.rest_url,
                        smoke=smoke,
                        run_id=run_id,
                    )
                    return await _do_m5_2_run(args, cfg, smoke=smoke)
            cfg = _build_m5_2_config(
                args,
                rest_https_edge_url=rest_https_edge_url,
                rest_plain_tcp_url=rest_plain_tcp_url or "",
                grpc_target=grpc_target or "",
                https_edge_endpoint=rest_https_edge_url,
                smoke=smoke,
                run_id=run_id,
            )
            return await _do_m5_2_run(args, cfg, smoke=smoke)
        except ModalDeployError as exc:
            print(f"Error: M5.2 Modal deploy failed: {exc}", file=sys.stderr)
            return 3

    return _asyncio.run(_run_with_deploy())


async def _do_m5_2_run(args: argparse.Namespace, cfg: object, *, smoke: bool) -> int:
    """Run the M5.2 sweep + emit the smoke-PASS line on smoke success.

    Errors are mapped to the contract's exit codes (5 = symmetry, 6 = RTT,
    7 = cohort failure, 8 = sidecar write).
    """
    import time as _time

    from vllm_grpc_bench.m5_2_sweep import (
        M5_2SmokeAssertionFailure,
        run_m5_2_sweep,
    )
    from vllm_grpc_bench.m5_2_symmetry import SymmetryAssertionFailed

    try:
        run = await run_m5_2_sweep(cfg, progress=True)  # type: ignore[arg-type]
    except SymmetryAssertionFailed as exc:
        print(f"Error: M5.2 symmetry assertion failed: {exc}", file=sys.stderr)
        return 5
    except M5_2SmokeAssertionFailure as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 6
    except Exception as exc:  # noqa: BLE001
        print(f"Error: M5.2 sweep failed: {exc}", file=sys.stderr)
        return 7

    if smoke:
        # T042: emit the structured smoke-pass line the operator copies into
        # the PR description per SC-012.
        iso = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
        rtt_summary = []
        for label, kind in (
            ("rest_https_edge", "rest_https_edge"),
            ("rest_plain_tcp", "rest_plain_tcp"),
            ("default_grpc", "default_grpc"),
        ):
            medians = []
            if kind in ("rest_https_edge", "rest_plain_tcp"):
                target = (
                    run.rest_https_edge_results
                    if kind == "rest_https_edge"
                    else run.rest_plain_tcp_results
                )
                medians = [r.rtt_record.median_ms for r in target if r.rtt_record is not None]
            else:
                medians = [r.rtt_record.median_ms for k, r in run.grpc_results if k == kind]
            if medians:
                rtt_summary.append(f"{label}={medians[0]:.1f}")
        tuned_medians = [
            r.rtt_record.median_ms for k, r in run.grpc_results if k.startswith("tuned_grpc")
        ]
        if tuned_medians:
            rtt_summary.append(f"tuned_grpc_*={tuned_medians[0]:.1f}")
        print(
            f"M5_2 smoke gate: PASS — {iso}, asserted_clauses_count: 4, "
            f"per-cohort RTT medians (ms): {', '.join(rtt_summary)}"
        )
        return 0

    print(
        f"M5.2 sweep complete: run_id={run.run_id}, "
        f"sidecar={run.events_sidecar_path}, SHA-256={run.events_sidecar_sha256}, "
        f"realized {run.run_realized_runtime_s:.1f}s. "
        "Next: run the regenerator on the sidecar + run config "
        "(see specs/019-m5-2-transport-tuning/quickstart.md Step 5)."
    )
    return 0


def _emit_m5_1_outputs(args: argparse.Namespace, run: M5_1Run) -> int:
    """Render JSON + Markdown and exit with success/failure code."""
    from vllm_grpc_bench.reporter import write_m5_1_json, write_m5_1_markdown

    docs_dir = args.m5_1_report_out if args.m5_1_report_out is not None else Path("docs/benchmarks")
    docs_dir.mkdir(parents=True, exist_ok=True)
    json_path = docs_dir / "m5_1-rest-vs-grpc.json"
    md_path = docs_dir / "m5_1-rest-vs-grpc.md"
    try:
        write_m5_1_json(run.metadata, run.cohorts, sample_size=100, path=json_path)
        write_m5_1_markdown(run.metadata, md_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Error: M5.1 report rendering failed: {exc}", file=sys.stderr)
        return 8
    print(f"M5.1 report written to {json_path} and {md_path}")
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if getattr(args, "m5_2", False) or getattr(args, "m5_2_smoke", False):
        sys.exit(_run_m5_2(args))

    if getattr(args, "m5_1", False):
        sys.exit(_run_m5_1(args))

    if getattr(args, "m5", False):
        sys.exit(_run_m5(args))

    if getattr(args, "m4", False):
        sys.exit(_run_m4(args))

    if getattr(args, "m3", False):
        sys.exit(_run_m3(args))

    if args.subcommand == "compare":
        baseline_path = Path(args.baseline)
        new_path = Path(args.new_results)
        if not baseline_path.exists():
            print(f"Error: {baseline_path} not found", file=sys.stderr)
            sys.exit(3)
        if not new_path.exists():
            print(f"Error: {new_path} not found", file=sys.stderr)
            sys.exit(3)
        baseline_run = load_run(baseline_path)
        new_run = load_run(new_path)
        report = compare(baseline_run, new_run, threshold=args.threshold)
        _print_comparison(report)
        sys.exit(1 if report.has_regression else 0)

    if args.subcommand == "compare-three-way":
        path_a = Path(args.result_a)
        path_b = Path(args.result_b)
        path_c = Path(args.result_c)
        for p in (path_a, path_b, path_c):
            if not p.exists():
                print(f"Error: {p} not found", file=sys.stderr)
                sys.exit(2)
        run_a = load_run(path_a)
        run_b = load_run(path_b)
        run_c = load_run(path_c)
        three_report = compare_three_way(
            run_a,
            run_b,
            run_c,
            label_a=args.label_a,
            label_b=args.label_b,
            label_c=args.label_c,
        )
        output_path_three: Path | None = args.output
        if output_path_three is not None:
            write_three_way_md(three_report, output_path_three)
            print(f"Report written to {output_path_three}")
        else:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
                tmp_path = Path(tf.name)
            write_three_way_md(three_report, tmp_path)
            print(tmp_path.read_text())
            tmp_path.unlink(missing_ok=True)
        sys.exit(0)

    if args.subcommand == "compare-cross":
        path_a = Path(args.result_a)
        path_b = Path(args.result_b)
        if not path_a.exists():
            print(f"Error: {path_a} not found", file=sys.stderr)
            sys.exit(2)
        if not path_b.exists():
            print(f"Error: {path_b} not found", file=sys.stderr)
            sys.exit(2)
        run_a = load_run(path_a)
        run_b = load_run(path_b)
        cross_report = compare_cross(run_a, run_b, label_a=args.label_a, label_b=args.label_b)
        output_path: Path | None = args.output
        if output_path is not None:
            write_cross_run_md(cross_report, output_path)
            print(f"Report written to {output_path}")
        else:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
                tmp_path = Path(tf.name)
            write_cross_run_md(cross_report, tmp_path)
            print(tmp_path.read_text())
            tmp_path.unlink(missing_ok=True)
        sys.exit(0)

    exit_code = asyncio.run(_run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
