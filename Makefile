PROXY_PORT ?= 8000
NATIVE_PORT ?= 8001
FRONTEND_PORT ?= 50051
FRONTEND_ADDR ?= localhost:$(FRONTEND_PORT)

BENCH_PROXY_PORT ?= 8900
BENCH_NATIVE_PORT ?= 8901

.PHONY: proto bootstrap lint typecheck test check run-proxy run-frontend bench bench-ci bench-compare download-weights smoke-grpc-frontend smoke-rest modal-serve-frontend bench-modal regen-bench-reports

proto:
	uv run python -m grpc_tools.protoc \
		-I proto \
		--python_out=packages/gen/src \
		--grpc_python_out=packages/gen/src \
		proto/vllm_grpc/v1/health.proto \
		proto/vllm_grpc/v1/chat.proto \
		proto/vllm_grpc/v1/completions.proto
	# M4 schema candidates (US3) — isolated namespace; not wired into production.
	mkdir -p packages/gen/src/vllm_grpc/v1/m4_candidates
	touch packages/gen/src/vllm_grpc/v1/m4_candidates/__init__.py
	uv run python -m grpc_tools.protoc \
		-I proto \
		--python_out=packages/gen/src \
		proto/vllm_grpc/v1/m4-candidates/packed_token_ids.proto \
		proto/vllm_grpc/v1/m4-candidates/oneof_flattened_input.proto \
		proto/vllm_grpc/v1/m4-candidates/chunk_granularity.proto

bootstrap:
	uv sync --all-packages
	$(MAKE) proto

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy --strict packages/proxy/src packages/frontend/src packages/client/src tools/benchmark/src

test:
	uv sync --all-packages
	uv run pytest packages/proxy/tests packages/frontend/tests packages/client/tests tests/integration tools/benchmark/tests -v

check: lint typecheck test

run-proxy:
	FRONTEND_ADDR=$(FRONTEND_ADDR) uv run uvicorn vllm_grpc_proxy.main:app \
		--host 0.0.0.0 --port $(PROXY_PORT)

run-frontend:
	FRONTEND_PORT=$(FRONTEND_PORT) uv run python -m vllm_grpc_frontend.main

bench:
	uv run python -m vllm_grpc_bench \
		--proxy-url http://localhost:$(PROXY_PORT) \
		--native-url http://localhost:$(NATIVE_PORT) \
		--output-dir bench-results

bench-ci:
	uv run python -m vllm_grpc_bench.fake_server --port $(BENCH_PROXY_PORT) --include-proxy-header & \
	FAKE_PROXY_PID=$$!; \
	uv run python -m vllm_grpc_bench.fake_server --port $(BENCH_NATIVE_PORT) & \
	FAKE_NATIVE_PID=$$!; \
	sleep 1; \
	uv run python -m vllm_grpc_bench \
		--proxy-url http://localhost:$(BENCH_PROXY_PORT) \
		--native-url http://localhost:$(BENCH_NATIVE_PORT) \
		--output-dir bench-ci-results; \
	BENCH_EXIT=$$?; \
	kill $$FAKE_PROXY_PID $$FAKE_NATIVE_PID 2>/dev/null || true; \
	exit $$BENCH_EXIT

bench-compare:
	uv run python -m vllm_grpc_bench compare $(BASELINE) $(RESULTS) --threshold $(or $(THRESHOLD),0.10)

download-weights:
	uv run --with modal modal run scripts/python/modal_download_weights.py

smoke-grpc-frontend:
	uv run --with modal modal run scripts/python/modal_frontend_smoke.py

smoke-rest:
	uv run --with modal modal run scripts/python/modal_vllm_rest.py

modal-serve-frontend:
	uv run --with modal modal run scripts/python/modal_frontend_serve.py

bench-modal:
	uv run --with modal --with torch modal run scripts/python/bench_modal.py

regen-bench-reports:
	uv run python scripts/python/regen_bench_reports.py
