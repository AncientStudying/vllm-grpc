#!/usr/bin/env python3
"""Generate the M6.2 Qwen3-8B prompt-embedding corpus (FR-035 prerequisite).

Loads Qwen/Qwen3-8B's embed_tokens layer, feeds each of the 1000 ShareGPT
prompts in tools/benchmark/corpus/chat_sharegpt_1000.json through it, and
saves a seq_len × 4096 fp16 tensor per prompt as a torch-save .pt file in
tools/benchmark/corpus/completions_embeds_qwen3_8b/. Also writes a
manifest.json with per-entry SHA + source_prompt_id + seq_len + bucket +
top-level corpus_sha256 + source_chat_corpus_sha256 + model + hidden_size +
generated_at_utc.

Usage (Modal A10G or local GPU with ~16 GB VRAM):

    uv run python scripts/python/gen_embed_corpus_qwen3_8b.py \\
        --source-corpus=tools/benchmark/corpus/chat_sharegpt_1000.json \\
        --output-dir=tools/benchmark/corpus/completions_embeds_qwen3_8b/ \\
        --model=Qwen/Qwen3-8B \\
        --hidden-size=4096 \\
        --dtype=float16

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


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _bucket_of(seq_len: int) -> str:
    """Map a tokenized seq_len onto the 3 buckets recorded in the chat
    corpus provenance file (short / medium / long)."""
    if seq_len < 128:
        return "short"
    if seq_len < 512:
        return "medium"
    return "long"


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

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print(
            "ERROR: torch + transformers required. Run: uv sync --all-packages",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.source_corpus.exists():
        print(f"ERROR: source corpus {args.source_corpus} not found.", file=sys.stderr)
        sys.exit(1)
    if not args.source_provenance.exists():
        print(
            f"ERROR: provenance file {args.source_provenance} not found.",
            file=sys.stderr,
        )
        sys.exit(1)

    source_provenance: dict[str, Any] = json.loads(args.source_provenance.read_text())
    source_chat_corpus_sha256 = source_provenance["corpus_sha256"]
    observed_source_sha = _sha256_of_file(args.source_corpus)
    if observed_source_sha != source_chat_corpus_sha256:
        print(
            f"ERROR: source corpus SHA mismatch.\n"
            f"  expected (provenance): {source_chat_corpus_sha256}\n"
            f"  observed (on-disk):    {observed_source_sha}",
            file=sys.stderr,
        )
        sys.exit(1)

    torch_dtype = torch.float16 if args.dtype == "float16" else torch.bfloat16
    device = "cuda" if torch.cuda.is_available() else "cpu"

    print(f"Loading tokenizer from {args.model}...")
    tokenizer = AutoTokenizer.from_pretrained(args.model)

    print(f"Loading {args.model} on {device} with dtype={args.dtype}...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        device_map=device,
        torch_dtype=torch_dtype,
    )
    embed_tokens = model.model.embed_tokens
    observed_hidden = embed_tokens.weight.shape[1]
    if observed_hidden != args.hidden_size:
        print(
            f"ERROR: model {args.model} reports hidden_size={observed_hidden}, "
            f"expected {args.hidden_size}.",
            file=sys.stderr,
        )
        sys.exit(1)

    corpus: list[dict[str, Any]] = json.loads(args.source_corpus.read_text())
    if args.limit is not None:
        corpus = corpus[: args.limit]

    args.output_dir.mkdir(parents=True, exist_ok=True)

    per_entry: list[dict[str, Any]] = []
    for idx, entry in enumerate(corpus):
        user_msg = next(m for m in entry["messages"] if m["role"] == "user")
        prompt_text: str = user_msg["content"]

        tokens = tokenizer(prompt_text, return_tensors="pt")
        input_ids = tokens["input_ids"]
        if input_ids.shape[1] > args.max_tokenized_len:
            input_ids = input_ids[:, : args.max_tokenized_len]
        input_ids = input_ids.to(device)

        with torch.no_grad():
            tensor = embed_tokens(input_ids)[0].to(torch_dtype).contiguous().cpu()

        seq_len = int(tensor.shape[0])
        pt_name = f"{idx:04d}.pt"
        pt_path = args.output_dir / pt_name
        torch.save(tensor, pt_path)
        sha = _sha256_of_file(pt_path)

        per_entry.append(
            {
                "id": idx,
                "source_prompt_id": entry["id"],
                "embed_file": pt_name,
                "seq_len": seq_len,
                "shape": [seq_len, args.hidden_size],
                "dtype": args.dtype,
                "bucket": _bucket_of(seq_len),
                "sha256": sha,
            }
        )
        if (idx + 1) % 50 == 0 or idx + 1 == len(corpus):
            bucket = per_entry[-1]["bucket"]
            print(f"  [{idx + 1:4d}/{len(corpus)}] last seq_len={seq_len} bucket={bucket}")

    sorted_shas = sorted(e["sha256"] for e in per_entry)
    corpus_sha256 = _sha256_of_bytes("\n".join(sorted_shas).encode("utf-8"))

    manifest = {
        "model": args.model,
        "hidden_size": args.hidden_size,
        "dtype": args.dtype,
        "n_entries": len(per_entry),
        "corpus_sha256": corpus_sha256,
        "source_chat_corpus_sha256": source_chat_corpus_sha256,
        "source_chat_corpus_path": str(args.source_corpus),
        "generated_at_utc": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": per_entry,
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {len(per_entry)} embed entries + manifest to {args.output_dir}")
    print(f"  corpus_sha256             = {corpus_sha256}")
    print(f"  source_chat_corpus_sha256 = {source_chat_corpus_sha256}")


if __name__ == "__main__":
    main()
