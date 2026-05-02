# Live benchmark: ~5 min for 10 samples × [1,4,8] concurrency × 2 targets (measured 2026-05-01)
# CI stub benchmark: <60 s (measured 2026-05-01)
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from vllm_grpc_bench.compare import compare, compare_cross
from vllm_grpc_bench.corpus import load_corpus
from vllm_grpc_bench.metrics import (
    BenchmarkConfig,
    BenchmarkRun,
    ComparisonReport,
    RequestResult,
    RunMeta,
    RunSummary,
    build_run_meta,
    compute_summaries,
)
from vllm_grpc_bench.reporter import write_cross_run_md, write_csv, write_json, write_summary_md
from vllm_grpc_bench.runner import run_target

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

    all_results: list[RequestResult] = []
    for conc in concurrency_levels:
        for target in ("proxy", "native"):
            url = proxy_url if target == "proxy" else native_url
            print(f"Running {target} @ concurrency={conc} …", flush=True)
            try:
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
            baseline_run = _deserialize_run(json.loads(baseline_path.read_text()))
            report = compare(baseline_run, run, threshold=args.regression_threshold)
        except Exception as exc:
            print(f"Warning: comparison failed: {exc}", file=sys.stderr)
            return 0
        _print_comparison(report)
        if report.has_regression:
            return 1

    return 0


def _deserialize_run(data: Any) -> BenchmarkRun:
    meta_d: Any = data["meta"]
    _cs = meta_d.get("cold_start_s")
    meta = RunMeta(
        timestamp=str(meta_d["timestamp"]),
        git_sha=str(meta_d["git_sha"]),
        hostname=str(meta_d["hostname"]),
        corpus_path=str(meta_d["corpus_path"]),
        concurrency_levels=[int(v) for v in meta_d["concurrency_levels"]],
        proxy_url=str(meta_d["proxy_url"]),
        native_url=str(meta_d["native_url"]),
        modal_function_id=str(meta_d["modal_function_id"])
        if meta_d.get("modal_function_id")
        else None,
        gpu_type=str(meta_d["gpu_type"]) if meta_d.get("gpu_type") else None,
        cold_start_s=float(_cs) if _cs is not None else None,
    )

    def _f(d: Any, key: str) -> float | None:
        v = d.get(key)
        return float(v) if v is not None else None

    summaries_d: Any = data["summaries"]
    summaries = [
        RunSummary(
            target=s["target"],
            concurrency=int(s["concurrency"]),
            n_requests=int(s["n_requests"]),
            n_errors=int(s["n_errors"]),
            latency_p50_ms=_f(s, "latency_p50_ms"),
            latency_p95_ms=_f(s, "latency_p95_ms"),
            latency_p99_ms=_f(s, "latency_p99_ms"),
            throughput_rps=_f(s, "throughput_rps"),
            request_bytes_mean=float(s["request_bytes_mean"]),
            response_bytes_mean=_f(s, "response_bytes_mean"),
            proxy_ms_p50=_f(s, "proxy_ms_p50"),
            proxy_ms_p95=_f(s, "proxy_ms_p95"),
            proxy_ms_p99=_f(s, "proxy_ms_p99"),
        )
        for s in summaries_d
    ]
    raw_d: Any = data.get("raw_results", [])
    raw = [
        RequestResult(
            sample_id=str(r["sample_id"]),
            target=r["target"],
            concurrency=int(r["concurrency"]),
            latency_ms=_f(r, "latency_ms"),
            request_bytes=int(r["request_bytes"]),
            response_bytes=int(r["response_bytes"])
            if r.get("response_bytes") is not None
            else None,
            proxy_ms=_f(r, "proxy_ms"),
            success=bool(r["success"]),
            error=str(r["error"]) if r.get("error") is not None else None,
        )
        for r in raw_d
    ]
    return BenchmarkRun(meta=meta, summaries=summaries, raw_results=raw)


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


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.subcommand == "compare":
        baseline_path = Path(args.baseline)
        new_path = Path(args.new_results)
        if not baseline_path.exists():
            print(f"Error: {baseline_path} not found", file=sys.stderr)
            sys.exit(3)
        if not new_path.exists():
            print(f"Error: {new_path} not found", file=sys.stderr)
            sys.exit(3)
        baseline_run = _deserialize_run(json.loads(baseline_path.read_text()))
        new_run = _deserialize_run(json.loads(new_path.read_text()))
        report = compare(baseline_run, new_run, threshold=args.threshold)
        _print_comparison(report)
        sys.exit(1 if report.has_regression else 0)

    if args.subcommand == "compare-cross":
        path_a = Path(args.result_a)
        path_b = Path(args.result_b)
        if not path_a.exists():
            print(f"Error: {path_a} not found", file=sys.stderr)
            sys.exit(2)
        if not path_b.exists():
            print(f"Error: {path_b} not found", file=sys.stderr)
            sys.exit(2)
        run_a = _deserialize_run(json.loads(path_a.read_text()))
        run_b = _deserialize_run(json.loads(path_b.read_text()))
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
