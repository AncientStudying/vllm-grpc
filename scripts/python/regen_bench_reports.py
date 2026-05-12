#!/usr/bin/env python3
"""Regenerate markdown benchmark reports from existing JSON result files.

Run this after fixing reporter logic to refresh docs/benchmarks/ without
a full Modal GPU run.  All inputs default to the version-controlled phase-4.2
JSON baselines in docs/benchmarks/.

Usage:
    make regen-bench-reports
    # or with explicit paths:
    uv run python scripts/python/regen_bench_reports.py \
        --rest    docs/benchmarks/phase-4.2-rest-baseline.json \
        --grpc-proxy docs/benchmarks/phase-4.2-grpc-proxy-baseline.json \
        --grpc-direct docs/benchmarks/phase-4.2-grpc-direct-baseline.json
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

_DOCS = Path("docs/benchmarks")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate markdown benchmark reports from JSON result files."
    )

    # M5.2 mode (see specs/019-m5-2-transport-tuning/contracts/m5_2-regenerator.md).
    parser.add_argument(
        "--m5_2-sidecar",
        type=Path,
        default=None,
        metavar="PATH",
        help="M5.2: gzipped events JSONL sidecar (e.g. docs/benchmarks/m5_2-...events.jsonl.gz).",
    )
    parser.add_argument(
        "--m5_2-run-config",
        type=Path,
        default=None,
        metavar="PATH",
        help="M5.2: per-run config JSON (bench-results/m5_2-full/{run_id}.run_config.json).",
    )
    parser.add_argument(
        "--m5_2-report-out",
        type=Path,
        default=None,
        metavar="PATH",
        help="M5.2: output path prefix (writes {prefix}.md and {prefix}.json).",
    )
    parser.add_argument(
        "--m5_2-m5_1-published",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "M5.2: override path to M5.1's published JSON "
            "(default docs/benchmarks/m5_1-rest-vs-grpc.json)."
        ),
    )

    # Phase 4.2 non-streaming
    parser.add_argument(
        "--rest",
        type=Path,
        default=_DOCS / "phase-4.2-rest-baseline.json",
        metavar="PATH",
    )
    parser.add_argument(
        "--grpc-proxy",
        type=Path,
        default=_DOCS / "phase-4.2-grpc-proxy-baseline.json",
        metavar="PATH",
    )
    parser.add_argument(
        "--grpc-direct",
        type=Path,
        default=_DOCS / "phase-4.2-grpc-direct-baseline.json",
        metavar="PATH",
    )
    # Phase 5 streaming
    parser.add_argument(
        "--phase5-rest",
        type=Path,
        default=_DOCS / "phase-5-rest-streaming.json",
        metavar="PATH",
    )
    parser.add_argument(
        "--phase5-proxy",
        type=Path,
        default=_DOCS / "phase-5-grpc-proxy-streaming.json",
        metavar="PATH",
    )
    parser.add_argument(
        "--phase5-direct",
        type=Path,
        default=_DOCS / "phase-5-grpc-direct-streaming.json",
        metavar="PATH",
    )
    # Phase 6 completions
    parser.add_argument(
        "--phase6-native",
        type=Path,
        default=_DOCS / "phase-6-completions-native.json",
        metavar="PATH",
    )
    parser.add_argument(
        "--phase6-proxy",
        type=Path,
        default=_DOCS / "phase-6-completions-proxy.json",
        metavar="PATH",
    )
    parser.add_argument(
        "--phase6-direct",
        type=Path,
        default=_DOCS / "phase-6-completions-grpc-direct.json",
        metavar="PATH",
    )
    args = parser.parse_args()

    # M5.2 mode short-circuit. When --m5_2-sidecar and --m5_2-run-config are
    # both set, dispatch into the round-trippable regenerator and exit per
    # the contract's exit-code mapping. M5.2 mode does NOT also produce the
    # phase-3/-4/-5/-6 markdown — it is the M5.2-only entry point.
    if args.m5_2_sidecar is not None or args.m5_2_run_config is not None:
        if args.m5_2_sidecar is None or args.m5_2_run_config is None:
            print(
                "Error: --m5_2-sidecar and --m5_2-run-config must be set together",
                file=sys.stderr,
            )
            sys.exit(2)
        from vllm_grpc_bench.m5_2_regen import (
            RunConfigInvalid,
            SidecarChecksumMismatch,
            regen_m5_2,
        )
        from vllm_grpc_bench.m5_2_supersede import M5_1PublishedJsonUnavailable
        from vllm_grpc_bench.m5_2_symmetry import SymmetryAssertionFailed

        try:
            result = regen_m5_2(
                args.m5_2_sidecar,
                args.m5_2_run_config,
                report_out_prefix=args.m5_2_report_out,
                m5_1_published_path=args.m5_2_m5_1_published,
            )
        except RunConfigInvalid as exc:
            print(f"Error: M5.2 run config invalid: {exc}", file=sys.stderr)
            sys.exit(4)
        except SidecarChecksumMismatch as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(8)
        except SymmetryAssertionFailed as exc:
            print(f"Error: M5.2 symmetry assertion failed at report-build: {exc}", file=sys.stderr)
            sys.exit(5)
        except M5_1PublishedJsonUnavailable as exc:
            print(f"Error: M5.1 published JSON unavailable: {exc}", file=sys.stderr)
            sys.exit(9)
        print(
            f"M5.2 regenerated → {result.markdown_path} + {result.json_path}; "
            f"records: {result.computed_aggregates_count}; "
            f"sidecar SHA-256: {result.observed_sha256}"
        )
        sys.exit(0)

    from vllm_grpc_bench.compare import compare_cross, compare_three_way
    from vllm_grpc_bench.io import load_run
    from vllm_grpc_bench.reporter import (
        write_cross_run_md,
        write_summary_md,
        write_three_way_md,
        write_wire_size_comparison_md,
    )

    rest_path: Path = args.rest
    proxy_path: Path = args.grpc_proxy
    direct_path: Path = args.grpc_direct

    missing = [p for p in (rest_path, proxy_path, direct_path) if not p.exists()]
    if missing:
        for p in missing:
            print(f"Error: {p} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {rest_path} ...")
    rest_run = load_run(rest_path)
    print(f"Loading {proxy_path} ...")
    proxy_run = load_run(proxy_path)
    print(f"Loading {direct_path} ...")
    direct_run = load_run(direct_path)

    _DOCS.mkdir(parents=True, exist_ok=True)

    # Phase-3 per-target summaries
    with tempfile.TemporaryDirectory() as tmp:
        md = write_summary_md(rest_run, Path(tmp))
        dest = _DOCS / "phase-3-modal-rest-baseline.md"
        shutil.copy(md, dest)
        print(f"Written {dest}")

    with tempfile.TemporaryDirectory() as tmp:
        md = write_summary_md(proxy_run, Path(tmp))
        dest = _DOCS / "phase-3-modal-grpc-baseline.md"
        shutil.copy(md, dest)
        print(f"Written {dest}")

    cross_report = compare_cross(rest_run, proxy_run, label_a="REST", label_b="gRPC")
    dest = _DOCS / "phase-3-modal-comparison.md"
    write_cross_run_md(cross_report, dest)
    print(f"Written {dest}")

    # Phase-4.2 gRPC-direct summary
    with tempfile.TemporaryDirectory() as tmp:
        md = write_summary_md(direct_run, Path(tmp))
        dest = _DOCS / "phase-4.2-grpc-direct-baseline.md"
        shutil.copy(md, dest)
        print(f"Written {dest}")

    # Phase-4.2 three-way comparison
    three_report = compare_three_way(
        rest_run,
        proxy_run,
        direct_run,
        label_a="REST",
        label_b="gRPC-proxy",
        label_c="gRPC-direct",
    )
    dest = _DOCS / "phase-4.2-three-way-comparison.md"
    write_three_way_md(three_report, dest)
    print(f"Written {dest}")

    # Phase-5 streaming comparison (skip if files not present)
    p5_paths = (args.phase5_rest, args.phase5_proxy, args.phase5_direct)
    if all(p.exists() for p in p5_paths):
        print(f"Loading {args.phase5_rest} ...")
        p5_rest = load_run(args.phase5_rest)
        print(f"Loading {args.phase5_proxy} ...")
        p5_proxy = load_run(args.phase5_proxy)
        print(f"Loading {args.phase5_direct} ...")
        p5_direct = load_run(args.phase5_direct)
        p5_report = compare_three_way(
            p5_rest,
            p5_proxy,
            p5_direct,
            label_a="REST",
            label_b="gRPC-proxy",
            label_c="gRPC-direct",
        )
        dest = _DOCS / "phase-5-streaming-comparison.md"
        write_three_way_md(p5_report, dest)
        print(f"Written {dest}")
    else:
        missing_p5 = [p for p in p5_paths if not p.exists()]
        print(f"Skipping Phase 5 streaming (missing: {', '.join(str(p) for p in missing_p5)})")

    # Phase-6 completions comparison (skip if files not present)
    p6_paths = (args.phase6_native, args.phase6_proxy, args.phase6_direct)
    if all(p.exists() for p in p6_paths):
        print(f"Loading {args.phase6_native} ...")
        p6_native = load_run(args.phase6_native)
        print(f"Loading {args.phase6_proxy} ...")
        p6_proxy = load_run(args.phase6_proxy)
        print(f"Loading {args.phase6_direct} ...")
        p6_direct = load_run(args.phase6_direct)
        combined_summaries = p6_native.summaries + p6_proxy.summaries + p6_direct.summaries
        dest = _DOCS / "phase-6-completions-comparison.md"
        write_wire_size_comparison_md(combined_summaries, dest)
        print(f"Written {dest}")
    else:
        missing_p6 = [p for p in p6_paths if not p.exists()]
        print(f"Skipping Phase 6 completions (missing: {', '.join(str(p) for p in missing_p6)})")

    print("Done.")


if __name__ == "__main__":
    main()
