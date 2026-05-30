# vllm-grpc-client

A lean async gRPC client for the [vllm-grpc](https://github.com/AncientStudying/vllm-grpc)
frontend. It speaks the project's protobuf `ChatService` and `CompletionsService`
directly over gRPC — no web-server stack, no `fastapi`/`uvicorn` pulled in. The
generated stubs (`vllm-grpc-gen`) install transitively.

## Install

```bash
pip install vllm-grpc-client
```

## Usage

```python
import asyncio

from vllm_grpc_client import VllmGrpcClient


async def main() -> None:
    async with VllmGrpcClient("localhost:50051") as client:
        result = await client.chat.complete(
            messages=[{"role": "user", "content": "Hello!"}],
            model="Qwen/Qwen3-0.6B",
            max_tokens=64,
        )
        print(result.content)


asyncio.run(main())
```

`client.completions.complete(...)` and the streaming variants
(`client.chat.complete_stream(...)`, `client.completions.complete_stream(...)`)
follow the same shape.

## Links

- Repository: https://github.com/AncientStudying/vllm-grpc
- Changelog: https://github.com/AncientStudying/vllm-grpc/blob/main/CHANGELOG.md
- Issues: https://github.com/AncientStudying/vllm-grpc/issues

## License

MIT
