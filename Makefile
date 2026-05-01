PROXY_PORT ?= 8000
FRONTEND_PORT ?= 50051
FRONTEND_ADDR ?= localhost:$(FRONTEND_PORT)

.PHONY: proto bootstrap lint typecheck test check run-proxy run-frontend

proto:
	uv run python -m grpc_tools.protoc \
		-I proto \
		--python_out=packages/gen/src \
		--grpc_python_out=packages/gen/src \
		proto/vllm_grpc/v1/health.proto

bootstrap:
	uv sync --all-packages
	$(MAKE) proto

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy --strict packages/proxy/src packages/frontend/src

test:
	uv sync --all-packages
	uv run pytest packages/proxy/tests packages/frontend/tests -v

check: lint typecheck test

run-proxy:
	FRONTEND_ADDR=$(FRONTEND_ADDR) uv run uvicorn vllm_grpc_proxy.main:app \
		--host 0.0.0.0 --port $(PROXY_PORT)

run-frontend:
	FRONTEND_PORT=$(FRONTEND_PORT) uv run python -m vllm_grpc_frontend.main
