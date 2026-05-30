# Live benchmark: ~5 min for 10 samples × [1,4,8] concurrency × 2 targets (measured 2026-05-01)
# CI stub benchmark: <60 s (measured 2026-05-01)
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

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

    # ---- sweep: token-budget characterization (de-prefixed M6.2) ----
    sweep = sub.add_parser(
        "sweep",
        help="Token-budget characterization sweep against a Modal-deployed vLLM "
        "endpoint. Defaults to publish mode; pass --validate for the wiring-confidence "
        "subset. All flags are de-prefixed (FR-018a / SC-009).",
    )
    sweep.add_argument(
        "--validate",
        action="store_true",
        help="Validate sweep: 3-point axis subset {10, 50, 2048} x 4-cohort x 6-cell "
        "matrix at n=20 (hard-pinned). Produces "
        "docs/benchmarks/m6_2-token-budget-validate.{md,json}. Omit for the publish sweep.",
    )
    sweep.add_argument(
        "--n",
        type=int,
        default=None,
        help="Per-block sample size (FR-004). No silent default -- the operator MUST "
        "pass --n=<N> for the publish sweep. The pinned production value is n=40 "
        "(sweep_types.PUBLISH_N). Under --validate, hard-pinned to 20.",
    )
    sweep.add_argument(
        "--modal-region",
        default="eu-west-1",
        help="Modal region for the deploy (default eu-west-1).",
    )
    sweep.add_argument(
        "--modal-token-env",
        default="MODAL_BENCH_TOKEN",
        help="Env-var name carrying the bearer token.",
    )
    sweep.add_argument(
        "--modal-endpoint",
        default=None,
        help="Pre-existing endpoint (advanced; implies --skip-deploy).",
    )
    sweep.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip the Modal deploy and reuse --modal-endpoint (dev cycles + tests).",
    )
    sweep.add_argument("--base-seed", type=int, default=42, help="Base RNG seed (default 42).")
    sweep.add_argument(
        "--model",
        default="Qwen/Qwen3-8B",
        help="HuggingFace model identifier (default Qwen/Qwen3-8B).",
    )
    sweep.add_argument(
        "--baseline",
        type=Path,
        default=Path("docs/benchmarks/m6_1_3-attribution-closure.json"),
        help="Baseline JSON path: null-anchor reference (FR-013) + trajectory threshold "
        "(FR-031) + crossover base-verdict source (FR-016).",
    )
    sweep.add_argument(
        "--report-out",
        type=Path,
        default=None,
        help="Markdown output path (operator override; default inferred per FR-015).",
    )
    sweep.add_argument(
        "--report-json-out",
        type=Path,
        default=None,
        help="JSON companion output path (operator override; default inferred per FR-015).",
    )
    sweep.add_argument(
        "--events-sidecar-out",
        type=Path,
        default=Path("docs/benchmarks/m6_2-events.jsonl"),
        help="Per-RPC events sidecar (JSONL) with per-block UTC timestamps + retry "
        "markers + prompt_source.",
    )
    sweep.add_argument(
        "--allow-engine-mismatch",
        action="store_true",
        help="Acknowledge an engine_version divergence (dev escape hatch).",
    )
    sweep.add_argument(
        "--checkpoint-out",
        type=Path,
        default=None,
        help="JSONL checkpoint sidecar path (per-block + per-anchor; crash-safe fsync). "
        "Default: <artifact-json>.checkpoint.jsonl. Empty string disables checkpointing.",
    )
    sweep.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Resume from a checkpoint JSONL. The current invocation's sweep_mode, n, "
        "axis, base_seed, model, modal_region, git_sha, and corpus SHAs MUST match the "
        "checkpoint header; mismatch aborts. Already-completed blocks are skipped.",
    )

    # ---- bench (default, no subcommand): proxy-vs-native head-to-head ----
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


def _validate_args(args: argparse.Namespace) -> int:
    """Pre-flight validation for the sweep subcommand. Returns exit code; 0 = OK.

    Validate mode hard-pins ``--n`` at 20 (FR-001 round-1 Q2). The publish-mode
    explicit-``--n`` gate (FR-004) is enforced inside ``run_m6_2`` /
    ``sweep.gate_publish_mode_n`` (exit 5).
    """
    if getattr(args, "validate", False):
        n = getattr(args, "n", None)
        if n is not None and n != 20:
            print(
                f"Error: --validate is pinned at n=20 (FR-001 round-1 Q2); got --n={n}. "
                "Drop the flag or pass --n=20 explicitly.",
                file=sys.stderr,
            )
            return 1
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.subcommand == "sweep":
        rc = _validate_args(args)
        if rc != 0:
            sys.exit(rc)
        from vllm_grpc_bench.sweep_types import SweepMode
        from vllm_grpc_bench.validate import run_m6_2

        sweep_mode: SweepMode = "validate" if getattr(args, "validate", False) else "publish"
        sys.exit(run_m6_2(args, sweep_mode=sweep_mode))

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
