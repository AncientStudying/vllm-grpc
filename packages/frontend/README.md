# vllm-grpc-frontend

The gRPC frontend server for [vllm-grpc](https://github.com/AncientStudying/vllm-grpc).
It wraps vLLM's V1 `AsyncLLM` engine and serves the project's protobuf
`ChatService`, `CompletionsService`, and `HealthService` over gRPC.

> **Affiliation:** vllm-grpc is an independent, community project and is not affiliated with, endorsed by, or sponsored by the vLLM project. "vLLM" is used here only to identify the inference engine this frontend works with.

## Install

```bash
pip install vllm-grpc-frontend
```

The base install pulls **no** vLLM, so it succeeds on any platform — including
those without a vLLM wheel. vLLM is required only to actually run the engine.

### vLLM prerequisite (V1 engine)

The frontend drives vLLM's **V1 `AsyncLLM`** API, so it requires `vllm>=0.20`.
Install it via the opt-in `engine` extra:

```bash
pip install "vllm-grpc-frontend[engine]"     # pulls vllm>=0.20
```

Or provide vLLM yourself — useful on platforms where the stock wheel does not
build (for example macOS, which uses `vllm-metal`). If vLLM is missing at
runtime, the server raises an `ImportError` when it starts; the package still
installs fine without it.

## Run

The package installs a `vllm-grpc-frontend` console script:

```bash
vllm-grpc-frontend        # serves gRPC on 0.0.0.0:50051 by default
```

Configure with environment variables:

- `MODEL_NAME` — model to load (default `Qwen/Qwen3-0.6B`)
- `FRONTEND_HOST` / `FRONTEND_PORT` — bind address (default `0.0.0.0:50051`)

## Links

- Repository: https://github.com/AncientStudying/vllm-grpc
- Changelog: https://github.com/AncientStudying/vllm-grpc/blob/main/CHANGELOG.md
- Issues: https://github.com/AncientStudying/vllm-grpc/issues

## License

MIT
