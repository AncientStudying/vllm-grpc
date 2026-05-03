from __future__ import annotations

from typing import Any

from vllm_grpc.v1 import chat_pb2


def proto_to_sampling_params(req: Any) -> Any:
    from vllm import SamplingParams

    kwargs: dict[str, Any] = {"max_tokens": req.max_tokens}
    kwargs["temperature"] = req.temperature if req.HasField("temperature") else 1.0
    kwargs["top_p"] = req.top_p if req.HasField("top_p") else 1.0
    if req.HasField("seed"):
        kwargs["seed"] = req.seed
    return SamplingParams(**kwargs)


def messages_to_prompt(
    messages: Any,
    tokenizer: Any,
) -> str:
    dicts = [{"role": m.role, "content": m.content} for m in messages]
    result: str = tokenizer.apply_chat_template(
        dicts,
        tokenize=False,
        add_generation_prompt=True,
    )
    return result


def output_to_stream_chunk(
    output: Any, token_index: int, prev_text: str
) -> chat_pb2.ChatStreamChunk:
    completion = output.outputs[0]
    delta = completion.text[len(prev_text) :]
    return chat_pb2.ChatStreamChunk(
        delta_content=delta,
        finish_reason="",
        token_index=token_index,
    )


def request_output_to_proto(output: Any) -> Any:
    completion = output.outputs[0]
    return chat_pb2.ChatCompleteResponse(
        message=chat_pb2.ChatMessage(role="assistant", content=completion.text),
        finish_reason=completion.finish_reason or "stop",
        prompt_tokens=len(output.prompt_token_ids),
        completion_tokens=len(completion.token_ids),
    )
