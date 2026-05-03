#!/usr/bin/env python3
"""Generate prompt-embedding corpus for Phase 6 wire-size benchmark.

Loads Qwen3-0.6B tokenizer and embed_tokens layer (CPU), extracts 20 source
prompts from tools/benchmark/corpus/chat_nonstreaming.json, runs embed_tokens
to produce tensors, and saves them as .pt files with a manifest.json.

Usage:
    uv run python scripts/python/gen_embed_corpus.py

Output:
    tools/benchmark/corpus/completions_embeds/00.pt ... 19.pt
    tools/benchmark/corpus/completions_embeds/manifest.json
    tools/benchmark/corpus/completions_embeds/prompts.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Bucket definitions: (name, min_seq_len, max_seq_len, count)
_BUCKETS = [
    ("short", 8, 16, 5),
    ("medium", 32, 48, 5),
    ("long", 96, 128, 5),
    ("full", 192, 256, 5),
]

_MODEL_NAME = "Qwen/Qwen3-0.6B"
_CORPUS_PATH = Path("tools/benchmark/corpus/chat_nonstreaming.json")
_OUTPUT_DIR = Path("tools/benchmark/corpus/completions_embeds")
_MAX_TOKENS = 50
_SEED = 42


def main() -> None:
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print(
            "ERROR: torch and transformers must be installed. Run: uv sync --all-packages",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading tokenizer from {_MODEL_NAME}...")
    tokenizer = AutoTokenizer.from_pretrained(_MODEL_NAME)

    print("Loading embed_tokens layer (CPU)...")
    model = AutoModelForCausalLM.from_pretrained(
        _MODEL_NAME, device_map="cpu", torch_dtype=torch.float32
    )
    embed_tokens = model.model.embed_tokens

    print(f"Loading chat corpus from {_CORPUS_PATH}...")
    corpus = json.loads(_CORPUS_PATH.read_text())

    # Build source prompts of varying lengths
    base_texts = []
    for entry in corpus:
        text = " ".join(m["content"] for m in entry["messages"] if m["role"] == "user")
        base_texts.append(text)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    prompts_lines = []
    sample_id = 0

    for bucket_name, min_len, max_len, count in _BUCKETS:
        bucket_count = 0
        idx = 0
        while bucket_count < count and idx < len(base_texts) * 10:
            # For short/medium, use single entries; for long/full, concatenate adjacent
            if bucket_name in ("short", "medium"):
                text = base_texts[idx % len(base_texts)]
                source = "chat_corpus"
                idx += 1
            else:
                n = 2 if bucket_name == "long" else 4
                parts = [base_texts[(idx + j) % len(base_texts)] for j in range(n)]
                text = " ".join(parts)
                source = "concatenated"
                idx += n

            tokens = tokenizer(text, return_tensors="pt")
            seq_len = tokens["input_ids"].shape[1]

            if not (min_len <= seq_len <= max_len):
                # Truncate or skip if outside range
                if seq_len > max_len:
                    tokens["input_ids"] = tokens["input_ids"][:, :max_len]
                    seq_len = max_len
                elif seq_len < min_len:
                    continue

            with torch.no_grad():
                tensor = embed_tokens(tokens["input_ids"])[0]  # [seq_len, hidden_size]

            pt_file = f"{sample_id:02d}.pt"
            pt_path = _OUTPUT_DIR / pt_file
            torch.save(tensor, pt_path)

            entry = {
                "id": sample_id,
                "source_prompt": text[:500],  # truncate for manifest readability
                "seq_len": int(tensor.shape[0]),
                "shape": list(tensor.shape),
                "dtype": "float32",
                "embed_file": f"corpus/completions_embeds/{pt_file}",
                "max_tokens": _MAX_TOKENS,
                "seed": _SEED,
                "bucket": bucket_name,
                "source": source,
            }
            manifest.append(entry)
            prompts_lines.append(text[:500])
            print(
                f"  [{sample_id:02d}] bucket={bucket_name} seq_len={tensor.shape[0]}"
                f" shape={list(tensor.shape)}"
            )
            sample_id += 1
            bucket_count += 1

    manifest_path = _OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote {len(manifest)} entries to {manifest_path}")

    prompts_path = _OUTPUT_DIR / "prompts.txt"
    prompts_path.write_text("\n".join(prompts_lines))
    print(f"Wrote prompts to {prompts_path}")


if __name__ == "__main__":
    main()
