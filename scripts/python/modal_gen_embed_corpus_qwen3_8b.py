#!/usr/bin/env python3
"""Modal wrapper for the M6.2 Qwen3-8B prompt-embedding corpus generator.

Runs :func:`generate_corpus` from :mod:`gen_embed_corpus_qwen3_8b` inside a
Modal A10G container (Qwen3-8B in fp16 needs ~16 GB VRAM, more than most
laptops). After generation the local entrypoint mirrors the Modal output
volume's contents to the local repo's
``tools/benchmark/corpus/completions_embeds_qwen3_8b/`` directory.

Volumes used (auto-created on first run):

- ``vllm-grpc-hf-cache`` — HuggingFace cache mounted at
  ``/root/.cache/huggingface``. Qwen3-8B (~16 GB) downloads once and is
  reused on subsequent runs.
- ``vllm-grpc-m6-2-embed-corpus`` — output volume mounted at ``/mnt/out``.
  Holds the 1000 ``.pt`` files + ``manifest.json`` between the remote run
  and the local mirror step.

Usage (requires Modal token: ``modal token new``):

    uv run --with modal modal run scripts/python/modal_gen_embed_corpus_qwen3_8b.py

Optional smoke-test flag emits only the first N prompts so the operator can
sanity-check the pipeline before paying for the full ~10-30 min A10G run:

    uv run --with modal modal run \\
        scripts/python/modal_gen_embed_corpus_qwen3_8b.py --limit=10

After the run completes, ``tools/benchmark/corpus/completions_embeds_qwen3_8b/``
contains the corpus + manifest; the operator commits it to the repo per
FR-035 (one-time Phase 1 prerequisite).

Reference: specs/027-m6-2-token-budget/contracts/prompt-source.md
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import modal

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_SOURCE_CORPUS_PATH = _PROJECT_ROOT / "tools" / "benchmark" / "corpus" / "chat_sharegpt_1000.json"
_SOURCE_PROVENANCE_PATH = (
    _PROJECT_ROOT / "tools" / "benchmark" / "corpus" / "chat_sharegpt_1000.provenance.json"
)
_LOCAL_OUTPUT_DIR = _PROJECT_ROOT / "tools" / "benchmark" / "corpus" / "completions_embeds_qwen3_8b"

_REMOTE_OUTPUT_DIR = "/mnt/out"
_REMOTE_HF_CACHE = "/root/.cache/huggingface"
_FUNCTION_TIMEOUT_S = 2400  # 40 minutes (first-run weight download + 1000-prompt embed)

# Pinned to the repo's torch / transformers versions (uv.lock as of M6.2 build).
# Bumping is safe but changes the generated tensors' bit-exactness — re-running
# invalidates the embed corpus SHA, so coordinate with the M6.2 sweep cadence.
_TORCH_VERSION = "2.11.0"
_TRANSFORMERS_VERSION = "5.7.0"


app = modal.App("vllm-grpc-m6-2-gen-embed-corpus")

_HF_CACHE_VOLUME = modal.Volume.from_name("vllm-grpc-hf-cache", create_if_missing=True)
_OUTPUT_VOLUME = modal.Volume.from_name("vllm-grpc-m6-2-embed-corpus", create_if_missing=True)

_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        f"torch=={_TORCH_VERSION}",
        f"transformers=={_TRANSFORMERS_VERSION}",
        "huggingface_hub>=0.23",
        "safetensors>=0.4",
        "accelerate>=0.34",
        "sentencepiece>=0.2",
    )
    # Ship the local generator module so the Modal function can call into
    # `generate_corpus(...)` without re-implementing the pipeline.
    .add_local_file(
        str(Path(__file__).resolve().parent / "gen_embed_corpus_qwen3_8b.py"),
        remote_path="/root/gen_embed_corpus_qwen3_8b.py",
    )
)


@app.function(
    image=_image,
    gpu="A10G",
    volumes={
        _REMOTE_HF_CACHE: _HF_CACHE_VOLUME,
        _REMOTE_OUTPUT_DIR: _OUTPUT_VOLUME,
    },
    timeout=_FUNCTION_TIMEOUT_S,
)
def generate_remote(
    source_corpus_bytes: bytes,
    source_provenance_bytes: bytes,
    *,
    model_name: str = "Qwen/Qwen3-8B",
    hidden_size: int = 4096,
    dtype: str = "float16",
    max_tokenized_len: int = 2048,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run the corpus generator inside the Modal container; return the manifest.

    The HuggingFace cache is on a persistent volume so the first run pays
    the ~16 GB Qwen3-8B download once; subsequent runs hit the cache.
    """
    import os
    import sys as _sys
    from pathlib import Path as _Path

    # Make the shipped generator module importable.
    _sys.path.insert(0, "/root")

    # Point HuggingFace cache at the mounted volume.
    os.environ["HF_HOME"] = _REMOTE_HF_CACHE
    os.environ["HUGGINGFACE_HUB_CACHE"] = f"{_REMOTE_HF_CACHE}/hub"
    os.environ["TRANSFORMERS_CACHE"] = f"{_REMOTE_HF_CACHE}/hub"

    from gen_embed_corpus_qwen3_8b import generate_corpus  # type: ignore[import-not-found]

    output_dir = _Path(_REMOTE_OUTPUT_DIR)
    # Start clean so a re-run doesn't leave stale files from a previous
    # smoke test (e.g., limit=10 followed by a full run).
    if output_dir.exists():
        for stale in output_dir.iterdir():
            if stale.is_file():
                stale.unlink()

    manifest = generate_corpus(
        source_corpus_bytes=source_corpus_bytes,
        source_provenance_bytes=source_provenance_bytes,
        output_dir=output_dir,
        model_name=model_name,
        hidden_size=hidden_size,
        dtype=dtype,
        max_tokenized_len=max_tokenized_len,
        limit=limit,
    )

    # Persist HF cache (so the next run skips the download) AND the output
    # volume (so the local entrypoint can read the generated files).
    _HF_CACHE_VOLUME.commit()
    _OUTPUT_VOLUME.commit()

    return manifest


def _mirror_volume_to_local(volume: modal.Volume, local_dir: Path) -> int:
    """Stream every file in ``volume`` into ``local_dir``.

    Returns the count of files written. Uses Modal's sync-callable hybrid
    Volume API (``iterdir`` + ``read_file_into_fileobj``) so the operator
    doesn't need to invoke ``modal volume get`` manually.
    """
    # Refresh the volume's view so we see the freshly-committed contents.
    volume.reload()

    local_dir.mkdir(parents=True, exist_ok=True)

    n_written = 0
    for entry in volume.iterdir("/", recursive=True):
        # Skip directories — they're recreated implicitly by the per-file
        # mkdir below. Modal's FileEntry.type is 1 for files, 2 for dirs
        # (per modal.volume.FileEntryType); guard generically via has-type.
        is_dir = getattr(getattr(entry, "type", None), "name", "") == "DIRECTORY"
        if is_dir:
            continue
        relative_path = entry.path.lstrip("/")
        local_path = local_dir / relative_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with local_path.open("wb") as f:
            volume.read_file_into_fileobj(entry.path, f)
        n_written += 1
    return n_written


@app.local_entrypoint()
def main(limit: int | None = None) -> None:
    """Local-side orchestration.

    Steps:
        1. Read the source corpus + provenance bytes from the local repo.
        2. Dispatch :func:`generate_remote` on a Modal A10G; wait for the
           manifest to come back.
        3. Mirror the output volume into the local corpus directory.
        4. Sanity-check the mirrored file count against the manifest.
    """
    if not _SOURCE_CORPUS_PATH.exists():
        print(f"ERROR: source corpus not found at {_SOURCE_CORPUS_PATH}", file=sys.stderr)
        sys.exit(1)
    if not _SOURCE_PROVENANCE_PATH.exists():
        print(
            f"ERROR: source provenance not found at {_SOURCE_PROVENANCE_PATH}",
            file=sys.stderr,
        )
        sys.exit(1)

    source_corpus_bytes = _SOURCE_CORPUS_PATH.read_bytes()
    source_provenance_bytes = _SOURCE_PROVENANCE_PATH.read_bytes()

    print(
        f"[modal_gen_embed_corpus] dispatching to Modal A10G "
        f"(limit={limit if limit is not None else 'none, full 1000-prompt run'}).",
        flush=True,
    )
    t0 = time.monotonic()
    manifest = generate_remote.remote(
        source_corpus_bytes,
        source_provenance_bytes,
        limit=limit,
    )
    remote_wall_s = time.monotonic() - t0

    n_entries = manifest["n_entries"]
    corpus_sha = manifest["corpus_sha256"]
    print(
        f"[modal_gen_embed_corpus] remote complete: n_entries={n_entries} "
        f"corpus_sha256={corpus_sha[:16]}... wall={remote_wall_s:.1f}s",
        flush=True,
    )

    print(
        f"[modal_gen_embed_corpus] mirroring volume → {_LOCAL_OUTPUT_DIR}...",
        flush=True,
    )
    t1 = time.monotonic()
    n_written = _mirror_volume_to_local(_OUTPUT_VOLUME, _LOCAL_OUTPUT_DIR)
    mirror_wall_s = time.monotonic() - t1
    print(
        f"[modal_gen_embed_corpus] mirrored {n_written} files in {mirror_wall_s:.1f}s.",
        flush=True,
    )

    # Sanity check: n_entries + manifest.json itself.
    expected_files = n_entries + 1
    if n_written != expected_files:
        print(
            f"WARN: mirrored {n_written} files but manifest reports "
            f"{n_entries} entries + 1 manifest = {expected_files}. "
            "Inspect the volume and the local directory.",
            file=sys.stderr,
        )
        sys.exit(2)

    print(
        f"\n[OK] M6.2 embed corpus generated. {n_entries} entries committed to "
        f"{_LOCAL_OUTPUT_DIR}.\n"
        f"     corpus_sha256             = {corpus_sha}\n"
        f"     source_chat_corpus_sha256 = {manifest['source_chat_corpus_sha256']}\n"
        f"Next: git add {_LOCAL_OUTPUT_DIR.relative_to(_PROJECT_ROOT)} && commit.",
        flush=True,
    )
