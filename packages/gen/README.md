# vllm-grpc-gen

Generated protobuf and gRPC Python stubs for the [vllm-grpc](https://github.com/AncientStudying/vllm-grpc)
project. This package is the shared, foundational dependency of `vllm-grpc-proxy`,
`vllm-grpc-frontend`, and `vllm-grpc-client` — it carries the compiled message and
service definitions (`vllm_grpc.v1`) that every other package imports.

The stubs are produced at build time from the `proto/` source of truth (via a
`protoc` build hook); they are never committed to the repository.

> **Affiliation:** vllm-grpc is an independent, community project and is not affiliated with, endorsed by, or sponsored by the vLLM project. "vLLM" is used here only to identify the inference engine this project works with.

## Install

```bash
pip install vllm-grpc-gen
```

It installs transitively when you install any of the leaf packages, so you rarely
need to install it directly.

## Usage

```python
from vllm_grpc.v1 import chat_pb2, chat_pb2_grpc, completions_pb2, health_pb2

request = chat_pb2.ChatRequest(model="Qwen/Qwen3-0.6B")
# `chat_pb2_grpc.ChatServiceStub(channel)` then calls the service.
```

## Links

- Repository: https://github.com/AncientStudying/vllm-grpc
- Changelog: https://github.com/AncientStudying/vllm-grpc/blob/main/CHANGELOG.md
- Issues: https://github.com/AncientStudying/vllm-grpc/issues

## License

MIT
