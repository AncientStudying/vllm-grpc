# Contract: REST Health Endpoint

**Endpoint**: `GET /healthz`
**Server**: `packages/proxy` (listens on `localhost:8000` by default)

---

## Request

```
GET /healthz HTTP/1.1
Host: localhost:8000
```

No request body, headers, or query parameters required.

---

## Responses

### 200 OK — Frontend reachable

The proxy successfully called `Health.Ping` on the gRPC frontend.

```
HTTP/1.1 200 OK
Content-Type: application/json

{"status": "ok"}
```

### 503 Service Unavailable — Frontend unreachable

The proxy could not reach the gRPC frontend (connection refused, timeout, or gRPC error).

```
HTTP/1.1 503 Service Unavailable
Content-Type: application/json

{"status": "error", "detail": "<human-readable reason>"}
```

---

## Behaviour Contract

- The proxy MUST attempt a `Health.Ping` gRPC call as part of every `/healthz` request.
- The proxy MUST NOT cache a prior successful ping result — each call probes the frontend.
- The gRPC call MUST use a client-side deadline of 2 seconds; exceeding it → 503.
- Response time MUST be < 3 seconds under normal conditions (2 s gRPC deadline + overhead).

---

## curl Example

```bash
curl -s http://localhost:8000/healthz
# → {"status":"ok"}
```
