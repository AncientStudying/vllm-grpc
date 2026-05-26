#!/usr/bin/env python3
"""Generate the M6.2 Qwen3-8B prompt-embedding corpus (FR-035 prerequisite).

Loads Qwen/Qwen3-8B's embed_tokens layer, feeds each of the 1000 ShareGPT
prompts in tools/benchmark/corpus/chat_sharegpt_1000.json through it, and
saves a seq_len × 4096 fp16 tensor per prompt as a torch-save .pt file in
tools/benchmark/corpus/completions_embeds_qwen3_8b/. Also writes a
manifest.json with per-entry SHA + source_prompt_id + seq_len + bucket +
top-level corpus_sha256 + source_chat_corpus_sha256 + model + hidden_size +
generated_at_utc.

This script supports two execution paths:

1. **Local GPU** (~16 GB VRAM required for Qwen3-8B in fp16):

       uv run python scripts/python/gen_embed_corpus_qwen3_8b.py

2. **Modal A10G** (operator default — no local GPU needed):

       uv run --with modal modal run scripts/python/modal_gen_embed_corpus_qwen3_8b.py

   The Modal wrapper imports :func:`generate_corpus` from this module and
   runs it inside a GPU-mounted Modal container, then mirrors the output
   files back to the local repo's ``tools/benchmark/corpus/completions_embeds_qwen3_8b/``.

Reference: specs/027-m6-2-token-budget/contracts/prompt-source.md
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

__all__ = [
    "generate_corpus",
    "main",
]


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _bucket_of(seq_len: int) -> str:
    """Map a tokenized seq_len onto 3 buckets calibrated to the actual
    ShareGPT first-human-turn distribution (median 18, p90 128, p99 479).

    Thresholds (post 2026-05-21 retune): ``< 16 → short``, ``16–127 → medium``,
    ``>= 128 → long``. Under the realized Qwen3-8B tokenization this splits
    the 1000-prompt corpus roughly 47% / 43% / 10%, making the bucket label
    a useful stratifier for the M6.2 reporter. The earlier ``< 128 → short``
    threshold put 90% of entries in ``short`` and was effectively useless.
    """
    if seq_len < 16:
        return "short"
    if seq_len < 128:
        return "medium"
    return "long"


def generate_corpus(
    *,
    source_corpus_bytes: bytes,
    source_provenance_bytes: bytes,
    output_dir: Path,
    model_name: str = "Qwen/Qwen3-8B",
    hidden_size: int = 4096,
    dtype: str = "float16",
    max_tokenized_len: int = 2048,
    limit: int | None = None,
    source_chat_corpus_path: str = "tools/benchmark/corpus/chat_sharegpt_1000.json",
    progress_print: bool = True,
) -> dict[str, Any]:
    """Generate the M6.2 embed corpus into ``output_dir`` and return the manifest.

    Accepts source corpus + provenance as bytes (rather than file paths) so
    that the Modal wrapper can ship them into the container without mounting
    the local repo. The on-disk source SHA is verified against the
    provenance file's recorded ``corpus_sha256``.

    Side effects: writes 1000 ``.pt`` files (one per prompt) and
    ``manifest.json`` into ``output_dir``. Caller is responsible for
    committing the output (e.g., `modal.Volume.commit()` in the Modal path).

    Raises:
        ImportError: torch / transformers not available.
        ValueError: source corpus SHA mismatch with provenance, or
            model hidden_size mismatch with the requested ``hidden_size``.
    """
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise ImportError(
            "torch + transformers required for embed-corpus generation. "
            "Install via `uv sync --all-packages`."
        ) from exc

    source_provenance: dict[str, Any] = json.loads(source_provenance_bytes.decode("utf-8"))
    expected_source_sha = source_provenance["corpus_sha256"]
    observed_source_sha = _sha256_of_bytes(source_corpus_bytes)
    if observed_source_sha != expected_source_sha:
        raise ValueError(
            f"Source corpus SHA mismatch.\n"
            f"  expected (provenance): {expected_source_sha}\n"
            f"  observed (in-memory):  {observed_source_sha}"
        )

    torch_dtype = torch.float16 if dtype == "float16" else torch.bfloat16
    device = "cuda" if torch.cuda.is_available() else "cpu"

    if progress_print:
        print(f"Loading tokenizer from {model_name}...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    if progress_print:
        print(f"Loading {model_name} on {device} with dtype={dtype}...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        device_map=device,
        torch_dtype=torch_dtype,
    )
    embed_tokens = model.model.embed_tokens
    observed_hidden = embed_tokens.weight.shape[1]
    if observed_hidden != hidden_size:
        raise ValueError(
            f"Model {model_name} reports hidden_size={observed_hidden}, expected {hidden_size}."
        )

    corpus: list[dict[str, Any]] = json.loads(source_corpus_bytes.decode("utf-8"))
    if limit is not None:
        corpus = corpus[:limit]

    output_dir.mkdir(parents=True, exist_ok=True)

    per_entry: list[dict[str, Any]] = []
    for idx, entry in enumerate(corpus):
        user_msg = next(m for m in entry["messages"] if m["role"] == "user")
        prompt_text: str = user_msg["content"]

        tokens = tokenizer(prompt_text, return_tensors="pt")
        input_ids = tokens["input_ids"]
        if input_ids.shape[1] > max_tokenized_len:
            input_ids = input_ids[:, :max_tokenized_len]
        input_ids = input_ids.to(device)

        with torch.no_grad():
            tensor = embed_tokens(input_ids)[0].to(torch_dtype).contiguous().cpu()

        seq_len = int(tensor.shape[0])
        pt_name = f"{idx:04d}.pt"
        pt_path = output_dir / pt_name
        torch.save(tensor, pt_path)
        sha = _sha256_of_file(pt_path)

        per_entry.append(
            {
                "id": idx,
                "source_prompt_id": entry["id"],
                "embed_file": pt_name,
                "seq_len": seq_len,
                "shape": [seq_len, hidden_size],
                "dtype": dtype,
                "bucket": _bucket_of(seq_len),
                "sha256": sha,
            }
        )
        if progress_print and ((idx + 1) % 50 == 0 or idx + 1 == len(corpus)):
            bucket = per_entry[-1]["bucket"]
            print(
                f"  [{idx + 1:4d}/{len(corpus)}] last seq_len={seq_len} bucket={bucket}",
                flush=True,
            )

    sorted_shas = sorted(e["sha256"] for e in per_entry)
    corpus_sha256 = _sha256_of_bytes("\n".join(sorted_shas).encode("utf-8"))

    manifest = {
        "model": model_name,
        "hidden_size": hidden_size,
        "dtype": dtype,
        "n_entries": len(per_entry),
        "corpus_sha256": corpus_sha256,
        "source_chat_corpus_sha256": expected_source_sha,
        "source_chat_corpus_path": source_chat_corpus_path,
        "generated_at_utc": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": per_entry,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-corpus",
        type=Path,
        default=Path("tools/benchmark/corpus/chat_sharegpt_1000.json"),
    )
    parser.add_argument(
        "--source-provenance",
        type=Path,
        default=Path("tools/benchmark/corpus/chat_sharegpt_1000.provenance.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tools/benchmark/corpus/completions_embeds_qwen3_8b"),
    )
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--hidden-size", type=int, default=4096)
    parser.add_argument("--dtype", default="float16", choices=("float16", "bfloat16"))
    parser.add_argument(
        "--max-tokenized-len",
        type=int,
        default=2048,
        help="Truncate any prompt longer than this many tokens.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="If set, only emit the first N prompts (for smoke tests).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if not args.source_corpus.exists():
        print(f"ERROR: source corpus {args.source_corpus} not found.", file=sys.stderr)
        sys.exit(1)
    if not args.source_provenance.exists():
        print(
            f"ERROR: provenance file {args.source_provenance} not found.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        manifest = generate_corpus(
            source_corpus_bytes=args.source_corpus.read_bytes(),
            source_provenance_bytes=args.source_provenance.read_bytes(),
            output_dir=args.output_dir,
            model_name=args.model,
            hidden_size=args.hidden_size,
            dtype=args.dtype,
            max_tokenized_len=args.max_tokenized_len,
            limit=args.limit,
            source_chat_corpus_path=str(args.source_corpus),
        )
    except (ImportError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"\nWrote {manifest['n_entries']} embed entries + manifest to {args.output_dir}")
    print(f"  corpus_sha256             = {manifest['corpus_sha256']}")
    print(f"  source_chat_corpus_sha256 = {manifest['source_chat_corpus_sha256']}")


if __name__ == "__main__":
    main()
