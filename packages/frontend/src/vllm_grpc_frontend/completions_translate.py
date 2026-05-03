from __future__ import annotations

import io
from typing import Any


def decode_embeds(raw_bytes: bytes) -> Any:
    import torch

    try:
        tensor: Any = torch.load(io.BytesIO(raw_bytes), weights_only=True)
    except Exception as exc:
        raise ValueError(f"Failed to deserialize prompt_embeds: {exc}") from exc

    if tensor.dtype not in (torch.float32, torch.bfloat16, torch.float16):
        raise ValueError(
            f"prompt_embeds must have dtype float32, bfloat16, or float16; got {tensor.dtype}"
        )
    if tensor.ndim != 2:
        raise ValueError(f"prompt_embeds must be a 2-D tensor; got ndim={tensor.ndim}")
    return tensor


def proto_to_sampling_params(req: Any) -> Any:
    from vllm import SamplingParams

    kwargs: dict[str, Any] = {"max_tokens": req.max_tokens}
    kwargs["temperature"] = req.temperature if req.HasField("temperature") else 1.0
    kwargs["top_p"] = req.top_p if req.HasField("top_p") else 1.0
    if req.HasField("seed"):
        kwargs["seed"] = req.seed
    return SamplingParams(**kwargs)
