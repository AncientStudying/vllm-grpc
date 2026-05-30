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
    args = parser.parse_args()

    from vllm_grpc_bench.compare import compare_cross, compare_three_way
    from vllm_grpc_bench.io import load_run
    from vllm_grpc_bench.reporter import (
        write_cross_run_md,
        write_summary_md,
        write_three_way_md,
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

    # Phase-6 completions wire-size regeneration was dropped at v0.0.1: its
    # writer (``write_wire_size_comparison_md``) was deleted in T020 as an
    # orphaned M4/M5-era report writer (ADR 0007). Recover the M6.2-era wire-size
    # numbers from the `milestone/m6.2-token-budget` tag if needed.

    print("Done.")


if __name__ == "__main__":
    main()
