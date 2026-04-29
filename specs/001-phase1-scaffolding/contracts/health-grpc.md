# Contract: Health gRPC Service

**Service**: `Health`
**Proto file**: `proto/vllm_grpc/v1/health.proto`
**Package**: `vllm_grpc.v1`
**Server**: `packages/frontend` (listens on `localhost:50051` by default)

---

## Proto Definition

```protobuf
syntax = "proto3";

package vllm_grpc.v1;

service Health {
  rpc Ping (HealthRequest) returns (HealthResponse);
}

message HealthRequest {}

message HealthResponse {
  string message = 1;
}
```

---

## RPC: Ping

| Property | Value |
|----------|-------|
| Type | Unary |
| Request | `HealthRequest` (empty) |
| Response | `HealthResponse` |
| Default address | `localhost:50051` |

### Behaviour

- The server MUST respond with `HealthResponse(message="pong")` for every valid request.
- The server MUST NOT return an error status for a well-formed `HealthRequest`.
- Response latency MUST be < 50 ms on localhost (no I/O involved).

### Error conditions

| gRPC Status | Trigger |
|-------------|---------|
| `UNAVAILABLE` | Server not running or listener not bound |
| `DEADLINE_EXCEEDED` | Client timeout fires before server responds |

---

## Generated Artifacts

After running `make proto`:

| File | Import path |
|------|-------------|
| `packages/gen/src/vllm_grpc/v1/health_pb2.py` | `from vllm_grpc.v1 import health_pb2` |
| `packages/gen/src/vllm_grpc/v1/health_pb2_grpc.py` | `from vllm_grpc.v1 import health_pb2_grpc` |

Client usage:
```python
import grpc
from vllm_grpc.v1 import health_pb2, health_pb2_grpc

channel = grpc.aio.insecure_channel("localhost:50051")
stub = health_pb2_grpc.HealthStub(channel)
response = await stub.Ping(health_pb2.HealthRequest())
assert response.message == "pong"
```
