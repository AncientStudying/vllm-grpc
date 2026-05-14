#!/usr/bin/env python3
"""Generate the M5.2 chat corpus by subsetting ShareGPT V3.

ShareGPT (anon8231489123/ShareGPT_Vicuna_unfiltered's canonical
``ShareGPT_V3_unfiltered_cleaned_split.json``, pinned to revision SHA
``192ab2185289094fc556ec8ce5ce1e8e587154ca``) is the de-facto reference
corpus for LLM serving benchmarks — vLLM, SGLang, TGI, and most published
throughput numbers use it. Pinning the corpus to this canonical source
gives M5.2 numbers that are directly comparable to those references.

Algorithm:
1. Download the raw ShareGPT V3 file (~673 MB) into the gitignored
   ``bench-results/sharegpt-raw/`` cache. Re-download is skipped if the
   cached file's SHA-256 matches the recorded value.
2. Parse the JSON; iterate over conversations; for each, take ONLY the
   first ``from=human`` turn (vLLM's benchmark convention — single-turn
   TTFT, no multi-turn context).
3. Filter to prompts in ``[--min-chars, --max-chars]`` (default 4-2048).
4. Random-sample ``--count`` records with a fixed ``--seed`` (default 42)
   for deterministic subset identity across re-runs.
5. Emit the subset to ``tools/benchmark/corpus/chat_sharegpt_<COUNT>.json``
   in the ``RequestSample`` schema (the same shape ``corpus.py`` already
   reads via ``load_corpus``). Adds an auto-derived ``bucket`` field
   (``short`` | ``medium`` | ``long``) per sample for diagnostic clarity.
6. Emit a sibling ``.provenance.json`` recording the source URL, source
   SHA, file SHA-256, filter criteria, and random seed so the audit can
   verify the corpus identity without re-running this script.

Usage::

    uv run python scripts/python/gen_chat_corpus.py --count 1000 \\
        --min-chars 4 --max-chars 2048 --max-tokens 128 --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CORPUS_DIR = _REPO_ROOT / "tools" / "benchmark" / "corpus"
_CACHE_DIR = _REPO_ROOT / "bench-results" / "sharegpt-raw"

_SHAREGPT_REPO = "anon8231489123/ShareGPT_Vicuna_unfiltered"
_SHAREGPT_FILE = "ShareGPT_V3_unfiltered_cleaned_split.json"
# Pin to the SHA at the time of authoring so re-runs of this script
# fetch byte-equal source data forever (HF preserves historical
# revisions). Update the pin only with a deliberate corpus-bump commit.
_SHAREGPT_REVISION = "192ab2185289094fc556ec8ce5ce1e8e587154ca"
_SHAREGPT_URL = (
    f"https://huggingface.co/datasets/{_SHAREGPT_REPO}"
    f"/resolve/{_SHAREGPT_REVISION}/{_SHAREGPT_FILE}"
)
# SHA-256 of the raw ShareGPT V3 file at the pinned revision. Computed
# on first authoring run (2026-05-12); subsequent runs hard-fail on
# mismatch to protect against upstream force-push of the pinned revision.
_SHAREGPT_FILE_SHA256_EXPECTED = "35f0e213ce091ed9b9af2a1f0755e9d39f9ccec34ab281cd4ca60d70f6479ba4"


def _bucket_for_prompt(prompt: str) -> str:
    """Auto-derive a short/medium/long bucket from prompt char count.

    Boundaries chosen to span ShareGPT's empirical first-turn-prompt
    length distribution: ~33% of prompts under 100 chars, ~50% in
    100-500, ~17% in 500-2048.
    """
    n = len(prompt)
    if n <= 100:
        return "short"
    if n <= 500:
        return "medium"
    return "long"


def _download_sharegpt(cache_path: Path, *, verify_sha: bool = True) -> str:
    """Download the raw ShareGPT V3 file into the gitignored cache.

    Returns the file's SHA-256 hex. Skips re-download if the cache hit
    matches the pinned expected hash.
    """
    if cache_path.exists():
        observed = hashlib.sha256(cache_path.read_bytes()).hexdigest()
        if not verify_sha or observed == _SHAREGPT_FILE_SHA256_EXPECTED:
            print(f"[cache hit] {cache_path} ({cache_path.stat().st_size / 1e6:.1f} MB)")
            return observed
        print(
            f"[cache stale] hash mismatch — re-downloading "
            f"(observed={observed[:16]}…, expected={_SHAREGPT_FILE_SHA256_EXPECTED[:16]}…)"
        )

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[downloading] {_SHAREGPT_URL}")
    print(f"  → {cache_path} (~673 MB, this can take a minute or two)")
    with (
        httpx.Client(follow_redirects=True, timeout=600.0) as client,
        client.stream("GET", _SHAREGPT_URL) as resp,
        cache_path.open("wb") as out,
    ):
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        hasher = hashlib.sha256()
        for chunk in resp.iter_bytes(chunk_size=1 << 20):
            out.write(chunk)
            hasher.update(chunk)
            downloaded += len(chunk)
            if total:
                pct = 100 * downloaded / total
                print(
                    f"\r  {downloaded / 1e6:.1f} / {total / 1e6:.1f} MB ({pct:.1f}%)",
                    end="",
                    flush=True,
                )
        print()
    observed = hasher.hexdigest()
    if verify_sha and _SHAREGPT_FILE_SHA256_EXPECTED and observed != _SHAREGPT_FILE_SHA256_EXPECTED:
        cache_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded ShareGPT V3 hash mismatch: "
            f"observed={observed}, expected={_SHAREGPT_FILE_SHA256_EXPECTED}. "
            f"The pinned revision SHA ({_SHAREGPT_REVISION}) was probably "
            "force-pushed upstream. Investigate before bumping the pin."
        )
    return observed


def _extract_first_user_prompts(raw_path: Path) -> list[str]:
    """Stream the ShareGPT JSON and yield each conversation's first
    ``from=human`` turn's text. ShareGPT format:

        [{"id": "...", "conversations": [{"from": "human", "value": "..."},
                                          {"from": "gpt", "value": "..."},
                                          ...]}, ...]
    """
    raw = json.loads(raw_path.read_text())
    prompts: list[str] = []
    for entry in raw:
        convs = entry.get("conversations", []) or []
        for turn in convs:
            if turn.get("from") == "human":
                value = turn.get("value", "")
                if isinstance(value, str):
                    prompts.append(value)
                break  # first human turn only
    return prompts


def _filter_and_sample(
    prompts: list[str], *, min_chars: int, max_chars: int, count: int, seed: int
) -> list[str]:
    eligible = [p for p in prompts if min_chars <= len(p) <= max_chars]
    if len(eligible) < count:
        raise RuntimeError(
            f"Only {len(eligible)} eligible prompts (min_chars={min_chars}, "
            f"max_chars={max_chars}); requested count={count}. Loosen the "
            "filter or reduce --count."
        )
    rng = random.Random(seed)
    sampled = rng.sample(eligible, count)
    return sampled


def _to_request_samples(
    prompts: list[str], *, max_tokens: int, model: str = "Qwen/Qwen3-0.6B"
) -> list[dict]:
    samples = []
    for i, prompt in enumerate(prompts):
        samples.append(
            {
                "id": f"sharegpt-{i:04d}",
                "messages": [{"role": "user", "content": prompt}],
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0.0,
                "seed": 42,
                "bucket": _bucket_for_prompt(prompt),
            }
        )
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--count", type=int, default=1000, help="Number of samples to keep (default 1000)."
    )
    parser.add_argument(
        "--min-chars", type=int, default=4, help="Minimum prompt length in chars (default 4)."
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=2048,
        help="Maximum prompt length in chars (default 2048).",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=128,
        help=(
            "Per-sample max_tokens written into the corpus "
            "(default 128, vLLM benchmark convention)."
        ),
    )
    parser.add_argument("--seed", type=int, default=42, help="Random sampling seed (default 42).")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output corpus JSON path (default tools/benchmark/corpus/chat_sharegpt_<COUNT>.json).",
    )
    parser.add_argument(
        "--skip-sha-verify",
        action="store_true",
        help=(
            "Skip SHA-256 verification of the downloaded ShareGPT V3 file. "
            "Use only on first authoring run."
        ),
    )
    args = parser.parse_args()

    cache_path = _CACHE_DIR / _SHAREGPT_FILE
    file_sha = _download_sharegpt(cache_path, verify_sha=not args.skip_sha_verify)

    print("[parsing] extracting first-user-message prompts …")
    prompts = _extract_first_user_prompts(cache_path)
    print(f"  total conversations with a human turn: {len(prompts):,}")

    print(f"[filtering] keeping prompts of length [{args.min_chars}, {args.max_chars}] chars …")
    sampled = _filter_and_sample(
        prompts,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
        count=args.count,
        seed=args.seed,
    )
    print(f"  sampled {len(sampled)} prompts (seed={args.seed})")

    samples = _to_request_samples(sampled, max_tokens=args.max_tokens)
    bucket_counts: dict[str, int] = {}
    for s in samples:
        bucket_counts[s["bucket"]] = bucket_counts.get(s["bucket"], 0) + 1
    print(
        f"  bucket distribution: short={bucket_counts.get('short', 0)}, "
        f"medium={bucket_counts.get('medium', 0)}, "
        f"long={bucket_counts.get('long', 0)}"
    )

    out_path = (
        args.out if args.out is not None else _CORPUS_DIR / f"chat_sharegpt_{args.count}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n")
    out_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    print(f"[wrote] {out_path} ({out_path.stat().st_size / 1024:.1f} KB; sha256={out_sha[:16]}…)")

    provenance = {
        "corpus_path": str(out_path.relative_to(_REPO_ROOT)),
        "corpus_sha256": out_sha,
        "source_repo": _SHAREGPT_REPO,
        "source_file": _SHAREGPT_FILE,
        "source_revision_sha": _SHAREGPT_REVISION,
        "source_url": _SHAREGPT_URL,
        "source_file_sha256": file_sha,
        "filter": {
            "first_human_turn_only": True,
            "min_chars": args.min_chars,
            "max_chars": args.max_chars,
        },
        "subset": {
            "count": args.count,
            "random_seed": args.seed,
        },
        "schema": {
            "max_tokens": args.max_tokens,
            "temperature": 0.0,
            "seed": 42,
            "model": "Qwen/Qwen3-0.6B",
        },
        "bucket_distribution": bucket_counts,
    }
    provenance_path = out_path.with_suffix(".provenance.json")
    provenance_path.write_text(
        json.dumps(provenance, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    )
    print(f"[wrote] {provenance_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
