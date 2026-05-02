# Contract: Modal Weight Volume

**Version**: 1.0 | **Phase**: 3.1

## Identity

| Field | Value |
|-------|-------|
| Volume name | `vllm-grpc-model-weights` |
| Mount path (all containers) | `/mnt/weights` |
| Model | `Qwen/Qwen3-0.6B` |
| Layout | HuggingFace `snapshot_download` format (contains `config.json`, `tokenizer.json`, `tokenizer_config.json`, weight shards) |

## Creation Contract

The volume is created and populated by `scripts/python/modal_download_weights.py`. Callers MUST run this script before running any smoke-test scripts.

```
Precondition:  Modal auth configured (`modal token new` completed)
Postcondition: /mnt/weights/config.json exists and volume is committed
Idempotent:    Yes — re-running is a no-op if /mnt/weights/config.json already exists
```

## Consumer Contract

Any Modal function that mounts this volume MUST:
- Declare `volumes={"/mnt/weights": _MODEL_VOLUME}` in `@app.function`
- Treat the mount as read-only (no writes, no `.commit()` needed)
- Pass `model="/mnt/weights"` to `AsyncEngineArgs` (frontend) or `--model /mnt/weights` to vLLM server (REST target)

## Failure Modes

| Condition | Behaviour |
|-----------|-----------|
| Volume does not exist | Modal raises `NotFoundError`; re-run `modal_download_weights.py` |
| Volume exists but weights incomplete | vLLM fails to load model; re-run download script to re-stage |
| HuggingFace rate limit during download | Download script exits non-zero; re-run with HF token if needed |
