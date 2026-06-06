# vllm-grpc-proxy

A REST-to-gRPC proxy for the [vllm-grpc](https://github.com/AncientStudying/vllm-grpc)
frontend. It exposes an HTTP surface (chat + completions endpoints and a
`/healthz` check) and forwards each request over gRPC to a running
`vllm-grpc-frontend` server. Use it when you want REST clients to reach the gRPC
backend.

> **Affiliation:** vllm-grpc is an independent, community project and is not affiliated with, endorsed by, or sponsored by the vLLM project. "vLLM" is used here only to identify the inference engine this project works with.

## Install

```bash
pip install vllm-grpc-proxy
```

## Run

The package installs a `vllm-grpc-proxy` console script that launches the REST
surface with uvicorn:

```bash
vllm-grpc-proxy        # serves on 0.0.0.0:8000 by default
```

Configure with environment variables:

- `PROXY_HOST` / `PROXY_PORT` — bind address (default `0.0.0.0:8000`)
- `FRONTEND_ADDR` — the gRPC frontend to forward to (default `localhost:50051`)

```bash
curl http://127.0.0.1:8000/healthz
# {"status": "ok"}   when the gRPC frontend is reachable
```

## Links

- Repository: https://github.com/AncientStudying/vllm-grpc
- Changelog: https://github.com/AncientStudying/vllm-grpc/blob/main/CHANGELOG.md
- Issues: https://github.com/AncientStudying/vllm-grpc/issues

## License

MIT
