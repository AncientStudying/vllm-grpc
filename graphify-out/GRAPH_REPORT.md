# Graph Report - .  (2026-05-03)

## Corpus Check
- 185 files · ~118,131 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 880 nodes · 1491 edges · 40 communities detected
- Extraction: 72% EXTRACTED · 28% INFERRED · 0% AMBIGUOUS · INFERRED: 420 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_REST Proxy & Streaming API|REST Proxy & Streaming API]]
- [[_COMMUNITY_Modal Orchestration & Bench Scripts|Modal Orchestration & Bench Scripts]]
- [[_COMMUNITY_Design Decisions & Benchmarking|Design Decisions & Benchmarking]]
- [[_COMMUNITY_Prompt-Embeds Research & Env Choice|Prompt-Embeds Research & Env Choice]]
- [[_COMMUNITY_gRPC Frontend Server Layer|gRPC Frontend Server Layer]]
- [[_COMMUNITY_Chat Client Library|Chat Client Library]]
- [[_COMMUNITY_Streaming & Completions Architecture|Streaming & Completions Architecture]]
- [[_COMMUNITY_CI Benchmark & Tunnel State|CI Benchmark & Tunnel State]]
- [[_COMMUNITY_Benchmark Corpus Management|Benchmark Corpus Management]]
- [[_COMMUNITY_gRPC Servicer Implementations|gRPC Servicer Implementations]]
- [[_COMMUNITY_Modal Deployment Infrastructure|Modal Deployment Infrastructure]]
- [[_COMMUNITY_Completions gRPC Service Layer|Completions gRPC Service Layer]]
- [[_COMMUNITY_Completions Client Library|Completions Client Library]]
- [[_COMMUNITY_Benchmark Metrics & Statistics|Benchmark Metrics & Statistics]]
- [[_COMMUNITY_Package Architecture & Health API|Package Architecture & Health API]]
- [[_COMMUNITY_Completions Translation Layer|Completions Translation Layer]]
- [[_COMMUNITY_Benchmark Tool Modules|Benchmark Tool Modules]]
- [[_COMMUNITY_Completions Endpoint Tests|Completions Endpoint Tests]]
- [[_COMMUNITY_Chat Endpoint Tests|Chat Endpoint Tests]]
- [[_COMMUNITY_HTTP Test Fixtures|HTTP Test Fixtures]]
- [[_COMMUNITY_Fake Server (CI Stub)|Fake Server (CI Stub)]]
- [[_COMMUNITY_Prompt-Embeds Verification|Prompt-Embeds Verification]]
- [[_COMMUNITY_Weight Download Script|Weight Download Script]]
- [[_COMMUNITY_Modal GPU Verification|Modal GPU Verification]]
- [[_COMMUNITY_REST Smoke Test Script|REST Smoke Test Script]]
- [[_COMMUNITY_Test Configuration|Test Configuration]]
- [[_COMMUNITY_Health Endpoint Tests|Health Endpoint Tests]]
- [[_COMMUNITY_Wire Efficiency Benchmarks|Wire Efficiency Benchmarks]]
- [[_COMMUNITY_vLLM Mock Fixtures|vLLM Mock Fixtures]]
- [[_COMMUNITY_Health Servicer|Health Servicer]]
- [[_COMMUNITY_Toolchain Decisions|Toolchain Decisions]]
- [[_COMMUNITY_Streaming Latency Metrics|Streaming Latency Metrics]]
- [[_COMMUNITY_Phase 1 Constraints|Phase 1 Constraints]]
- [[_COMMUNITY_CI Baseline Results|CI Baseline Results]]
- [[_COMMUNITY_Bootstrap Flow|Bootstrap Flow]]
- [[_COMMUNITY_Task Runner Decision|Task Runner Decision]]
- [[_COMMUNITY_CI Strategy Decision|CI Strategy Decision]]
- [[_COMMUNITY_Chat Bridge Quickstart|Chat Bridge Quickstart]]
- [[_COMMUNITY_Benchmark Harness Spec|Benchmark Harness Spec]]
- [[_COMMUNITY_Modal gRPC Research|Modal gRPC Research]]

## God Nodes (most connected - your core abstractions)
1. `main()` - 23 edges
2. `RequestResult` - 22 edges
3. `CompletionsClient` - 22 edges
4. `compute_summaries()` - 19 edges
5. `Project plan: protobuf/gRPC frontend for vLLM` - 19 edges
6. `_run()` - 16 edges
7. `proto_to_sampling_params()` - 16 edges
8. `_make_result()` - 15 edges
9. `BenchmarkRun` - 15 edges
10. `VllmGrpcClient` - 15 edges

## Surprising Connections (you probably didn't know these)
- `Rationale: proxy runs inside Modal container (not local) to avoid unreliable modal.forward generator pattern` --rationale_for--> `modal_frontend_smoke.py gRPC+proxy smoke test`  [EXTRACTED]
  specs/005-modal-grpc-frontend/research.md → scripts/python/modal_frontend_smoke.py
- `bench_modal.py Modal benchmark orchestration` --references--> `Phase 4.1 benchmark baseline files (docs/benchmarks/phase-3-modal-*)`  [EXTRACTED]
  scripts/python/bench_modal.py → specs/007-modal-real-baselines/data-model.md
- `Rationale: define both serve functions in single bench_modal.py script` --rationale_for--> `bench_modal.py Modal benchmark orchestration`  [EXTRACTED]
  specs/007-modal-real-baselines/research.md → scripts/python/bench_modal.py
- `bench_modal.py Modal benchmark orchestration` --references--> `Phase 4.2 three-way baseline files (docs/benchmarks/phase-4.2-*)`  [EXTRACTED]
  scripts/python/bench_modal.py → specs/008-grpc-client-library/data-model.md
- `chat-nonstreaming.py OpenAI client smoke script` --calls--> `proxy FastAPI app (main.py)`  [INFERRED]
  scripts/python/chat-nonstreaming.py → packages/proxy/src/vllm_grpc_proxy/main.py

## Hyperedges (group relationships)
- **End-to-End Health Ping Flow: REST /healthz → gRPC Health.Ping → pong** — datamodel_proxypkg, healthgrpc_contract, datamodel_frontendpkg, resthealthz_contract, datamodel_healthservice [EXTRACTED 1.00]
- **uv Workspace: gen + proxy + frontend packages sharing proto stubs** — datamodel_workspacelayout, datamodel_proxypkg, datamodel_frontendpkg, healthgrpc_generatedartifacts, research_genstubplacement [EXTRACTED 1.00]
- **Three-way benchmark: REST baseline, gRPC-proxy, gRPC-direct all compared on A10G** —  [EXTRACTED 1.00]
- **Prompt-embeds design, corpus note, and vLLM runtime limitation form a coherent issue cluster** —  [INFERRED 0.80]
- **Modal deployment decisions: ADR 0001 environment choice feeds ADR 0002 deployment architecture** —  [EXTRACTED 1.00]
- **** — completions_completionsclient, gen_completions_pb2_grpc_completionsservicestub, frontend_completions_completionsservicer [INFERRED 0.85]
- **** — chat_chatclient, gen_chat_pb2_chatcompleterequest, frontend_chat_chatservicer [INFERRED 0.85]
- **** — frontend_completions_completionsservicer, completions_translate_decode_embeds, gen_completions_pb2_completionrequest [EXTRACTED 1.00]
- **hyperedge_proxy_request_pipeline** — chat_router_chat_completions_endpoint, chat_translate_openai_request_to_proto, grpc_client_grpcchatclient, chat_pb2_grpc_chatservicestub [EXTRACTED 1.00]
- **hyperedge_completions_request_pipeline** — completions_router_completions_endpoint, completions_translate_openai_request_to_proto, grpc_client_grpccompletionsclient [EXTRACTED 1.00]
- **hyperedge_modal_bench_deploy_stack** — bench_modal_script, modal_download_weights_script, modal_frontend_serve_script, proxy_main_app [INFERRED 0.82]
- **Phase 2 Environment Decision: research + empirical tests + ADR → Modal A10G chosen** —  [INFERRED]
- **Phase 3 Translation Pipeline: OpenAI JSON → proto → AsyncLLM → proto → OpenAI JSON** —  [INFERRED]
- **Phase 4 CI Benchmark Strategy: FakeHTTPServer + committed baseline + benchmark.yml → regression detection** —  [INFERRED]
- **Phase 3.1 gRPC smoke test: modal_frontend_smoke.py runs proxy+frontend in container against modal_weight_volume_entity and returns smoke_test_result_entity** — modal_frontend_smoke_script, modal_weight_volume_entity, smoke_test_result_entity [EXTRACTED 1.00]
- **Phase 3.2 serve lifecycle: modal_frontend_serve_script uses modal_forward_tcp_tunnel + modal_dict_coordination to expose gRPC frontend_addr to local proxy via frontend_addr_env_var** — modal_frontend_serve_script, modal_forward_tcp_tunnel, modal_dict_coordination, frontend_addr_env_var [EXTRACTED 1.00]
- **Benchmark measures proxy overhead: x_bench_proxy_ms_header produced by bench_middleware_producer and consumed by bench_runner_consumer to populate bench_proxy_overhead_metric** — x_bench_proxy_ms_header, bench_middleware_producer, bench_runner_consumer, bench_proxy_overhead_metric [EXTRACTED 1.00]
- **bench_modal.py orchestrates REST + gRPC-proxy + gRPC-direct via shared Modal deployment** —  [EXTRACTED 1.00]
- **Three-way comparison pipeline: compare_three_way() → ThreeWayReport → write_three_way_md()** —  [EXTRACTED 1.00]
- **Two-way comparison pipeline: compare_cross() → CrossRunReport → write_cross_run_md()** —  [EXTRACTED 1.00]
- **Phase 5 streaming chat requires proto, SSE contract, and client API to be defined before implementation** —  [INFERRED]
- **Phase 6 completions core trio: CompletionRequest (oneof), binary encoding rationale, and wire-size benchmark** —  [INFERRED]
- **fake_frontend_server wires both FakeChatServicer and FakeCompletionsServicer for integration tests** —  [INFERRED]
- **Benchmark pipeline: corpus -> runner -> metrics -> reporter** — bench_corpus, bench_runner, bench_metrics, bench_reporter [INFERRED 0.90]
- **Integration tests share fake_frontend fixture and proxy app** — test_chat_bridge, test_grpc_client, test_completions_bridge, fake_frontend_server [EXTRACTED 1.00]
- **Comparison flow: io.load_run -> compare -> reporter output** — bench_io, bench_compare, bench_reporter [EXTRACTED 1.00]
- **compare regression test suite uses BenchmarkRun and RunSummary fixtures** — test_compare_testcompare, compare_compare, metrics_benchmarkrun [INFERRED 0.85]
- **_make_run assembles BenchmarkRun from _meta and RunSummary instances** — test_compare_make_run, test_compare_meta, metrics_runsummary [EXTRACTED 1.00]
- **regression threshold tests exercise compare with varying latency summaries** — test_compare_testcompare, compare_compare, test_compare_make_summary [EXTRACTED 1.00]

## Communities

### Community 0 - "REST Proxy & Streaming API"
Cohesion: 0.05
Nodes (50): BaseModel, chat-nonstreaming.py OpenAI client smoke script, chat_completions(), chat_completions() FastAPI route handler, _stream_sse(), format_sse_done(), format_sse_error(), format_sse_role_delta() (+42 more)

### Community 1 - "Modal Orchestration & Bench Scripts"
Cohesion: 0.08
Nodes (52): main(), _poll_for_addr(), Start vLLM REST server, expose via TCP tunnel, block until stop signal., Start gRPC frontend, expose via TCP tunnel, block until stop signal., Run benchmark harness subprocess; return path to results.json or exit 1., _run_harness(), serve_rest_for_bench(), compare() (+44 more)

### Community 2 - "Design Decisions & Benchmarking"
Cohesion: 0.04
Nodes (60): ADR 0001 — Prompt-Embeds Environment Decision (Modal A10G chosen), tokenizer.apply_chat_template() — chat message list to prompt string, AsyncLLM.generate() — async generator for non-streaming completions, Benchmark Baseline (committed reference report), Benchmark Harness CLI Contract (vllm_grpc_bench), Benchmark Harness Requirements Checklist, Benchmark Harness Spec (Phase 4), bench_middleware.py (X-Bench-Proxy-Ms producer) (+52 more)

### Community 3 - "Prompt-Embeds Research & Env Choice"
Cohesion: 0.04
Nodes (60): Candidate B rejected: M2 CPU-only vLLM — missing prompt_embeds + tokenizer incompatibility, Candidate A rejected: M2 Metal (vllm-metal 0.2.0) — missing prompt_embeds + install blockers, Candidate C chosen: Modal A10G CUDA — only viable environment for prompt_embeds, ADR 0001: Prompt-embeds compute environment investigation, ADR 0002: Modal deployment of vllm-grpc-frontend, Phase 3.2: modal.forward(unencrypted=True) tunnel for local proxy to Modal gRPC, Rationale: Modal chosen for ephemeral A10G GPU, Python-native API, no idle cost, Architecture: proxy and frontend as subprocesses inside same Modal container (+52 more)

### Community 4 - "gRPC Frontend Server Layer"
Cohesion: 0.05
Nodes (32): serve_grpc_for_bench(), add_ChatServiceServicer_to_server(), ChatService, ChatServiceServicer, ChatServiceStub, Missing associated documentation comment in .proto file., Constructor.          Args:             channel: A grpc.Channel., Missing associated documentation comment in .proto file. (+24 more)

### Community 5 - "Chat Client Library"
Cohesion: 0.07
Nodes (31): ChatClient, ChatCompleteResult, StreamChunk, messages_to_prompt(), output_to_stream_chunk(), proto_to_sampling_params(), request_output_to_proto(), chat() (+23 more)

### Community 6 - "Streaming & Completions Architecture"
Cohesion: 0.05
Nodes (50): ADR 0003: Streaming Design (chunk granularity, error encoding, back-pressure, cancellation), ADR 0004: Completions Design (proto schema, tensor encoding, corpus), Native async generator back-pressure model, Three-layer asyncio cancellation chain design, ChatCompleteResponse — proto message (message, finish_reason, prompt_tokens, completion_tokens), ChatService gRPC Proto Contract (chat.proto), ChatStreamChunk protobuf message, One proto message per token chunk granularity decision (+42 more)

### Community 7 - "CI Benchmark & Tunnel State"
Cohesion: 0.05
Nodes (48): CI smoke test: make bench-ci with fake_server.py --streaming, bench_modal.py Modal benchmark orchestration, ChatClient sub-client (VllmGrpcClient.chat), ChatCompleteResult dataclass, CI step: modal-baseline-summary (benchmark.yml), TunnelState key: cold_start_s, compare_cross() function in compare.py, Rationale: compare_cross() aligns by concurrency only (not target+concurrency) (+40 more)

### Community 8 - "Benchmark Corpus Management"
Cohesion: 0.08
Nodes (39): CompletionEmbedSample, CompletionTextSample, load_completions_corpus(), load_corpus(), RequestSample, Measure wire size for text-prompt completions via native vLLM REST endpoint., Measure wire size for text-prompt completions via REST proxy., Measure wire size for embedding-prompt completions via REST proxy (base64-encode (+31 more)

### Community 9 - "gRPC Servicer Implementations"
Cohesion: 0.13
Nodes (29): ChatServicer, CompleteStream(), CompletionsServicer, _fake_generate(), _make_output(), _make_request(), _make_servicer(), _make_streaming_servicer() (+21 more)

### Community 10 - "Modal Deployment Infrastructure"
Cohesion: 0.08
Nodes (33): ADR 0002: Modal Deployment (docs/decisions/0002-modal-deployment.md), Rationale: blocking (non-generator) function keeps modal.forward() context open for tunnel lifetime, FRONTEND_ADDR environment variable (proxy gRPC target address), modal.Dict for cross-process state (address + stop signal), modal.forward(unencrypted=True) TCP Tunnel for gRPC/HTTP2, modal_frontend_smoke.py gRPC+proxy smoke test, Modal gRPC Frontend Requirements Checklist, Modal gRPC Frontend Data Model (+25 more)

### Community 11 - "Completions gRPC Service Layer"
Cohesion: 0.07
Nodes (16): add_CompletionsServiceServicer_to_server(), CompletionsService, CompletionsServiceServicer, Missing associated documentation comment in .proto file., Missing associated documentation comment in .proto file., Missing associated documentation comment in .proto file., Missing associated documentation comment in .proto file., fake_frontend_server() (+8 more)

### Community 12 - "Completions Client Library"
Cohesion: 0.12
Nodes (23): CompletionResult, CompletionsClient, CompletionStreamChunk, CompletionsServiceStub, Missing associated documentation comment in .proto file., Constructor.          Args:             channel: A grpc.Channel., CompletionsServicer, CompletionRequest (proto) (+15 more)

### Community 13 - "Benchmark Metrics & Statistics"
Cohesion: 0.13
Nodes (10): BenchmarkConfig, build_run_meta(), compute_summaries(), _percentile(), _make_result(), TestBuildRunMeta, TestComputeSummaries, TestComputeSummariesStreaming (+2 more)

### Community 14 - "Package Architecture & Health API"
Cohesion: 0.09
Nodes (30): Requirements Quality Checklist, Frontend Package (vllm_grpc_frontend), HealthRequest Proto Message, HealthResponse Proto Message, Health gRPC Service, Proxy Package (vllm_grpc_proxy), Service Availability State Transitions, Workspace Package Layout (+22 more)

### Community 15 - "Completions Translation Layer"
Cohesion: 0.18
Nodes (13): decode_embeds(), proto_to_sampling_params(), _make_request(), TestProtoToSamplingParams, _make_tensor_bytes(), test_decode_embeds_corrupted_bytes(), test_decode_embeds_valid_bfloat16(), test_decode_embeds_valid_float16() (+5 more)

### Community 16 - "Benchmark Tool Modules"
Cohesion: 0.13
Nodes (24): compare.py — regression detection and cross-run comparison (compare, compare_cross, compare_three_way), conftest.py — benchmark test fixtures: fake_http_server, fake_http_server_with_proxy_header, fake_streaming_server (httpx.MockTransport), corpus.py — RequestSample, CompletionTextSample, CompletionEmbedSample, load_corpus, load_completions_corpus, fake_server.py — standalone stub HTTP server for benchmark CI smoke tests, io.py — BenchmarkRun serialization: load_run deserializes results JSON, __main__.py — CLI entrypoint: run / compare / compare-cross / compare-three-way subcommands, metrics.py — benchmark dataclasses (RequestResult, RunSummary, BenchmarkRun, etc.) and compute_summaries/build_run_meta, reporter.py — benchmark output: write_json, write_csv, write_summary_md, write_cross_run_md, write_wire_size_comparison_md, write_three_way_md (+16 more)

### Community 17 - "Completions Endpoint Tests"
Cohesion: 0.17
Nodes (2): _fake_stream(), mock_completions_client()

### Community 18 - "Chat Endpoint Tests"
Cohesion: 0.18
Nodes (2): _fake_stream(), mock_chat_client()

### Community 19 - "HTTP Test Fixtures"
Cohesion: 0.48
Nodes (6): fake_http_server(), fake_http_server_with_proxy_header(), fake_streaming_server(), _make_streaming_transport(), _make_transport(), _sse_chunk()

### Community 20 - "Fake Server (CI Stub)"
Cohesion: 0.53
Nodes (5): _handle(), main(), Standalone stub HTTP server for CI and bench-ci smoke tests.  Usage:     python, serve(), _sse_chunk()

### Community 21 - "Prompt-Embeds Verification"
Cohesion: 0.47
Nodes (5): build_prompt_embeds(), main(), Return a base64-encoded torch.save() of a float32 zeros tensor [seq_len, HIDDEN_, Send a prompt_embeds completion request. Returns 0 on success, 1 on failure., run_verification()

### Community 22 - "Weight Download Script"
Cohesion: 0.5
Nodes (2): download_weights(), Download model weights into the persistent volume (CPU-only; no GPU needed).

### Community 23 - "Modal GPU Verification"
Cohesion: 0.5
Nodes (2): Run vLLM serve + prompt_embeds verification inside the Modal container., _verify_on_gpu()

### Community 24 - "REST Smoke Test Script"
Cohesion: 0.5
Nodes (2): Run REST smoke test inside the Modal container., smoke_test()

### Community 25 - "Test Configuration"
Cohesion: 0.5
Nodes (1): anyio_backend()

### Community 26 - "Health Endpoint Tests"
Cohesion: 0.67
Nodes (2): test_healthz_returns_200_when_ping_succeeds(), test_healthz_returns_503_when_ping_fails()

### Community 27 - "Wire Efficiency Benchmarks"
Cohesion: 0.5
Nodes (4): ~33% base64 overhead quantified as benchmark target, CI benchmark multi-phase PR comment aggregation, request_type Literal field on RequestResult/RunSummary, Phase 6 wire-size efficiency benchmark (REST base64 vs gRPC binary)

### Community 28 - "vLLM Mock Fixtures"
Cohesion: 0.67
Nodes (2): mock_vllm(), Inject a fake vllm module so frontend tests run without a GPU install.

### Community 29 - "Health Servicer"
Cohesion: 0.67
Nodes (1): HealthServicer

### Community 30 - "Toolchain Decisions"
Cohesion: 0.67
Nodes (3): Technical Context, mypy + grpc-stubs Decision, Python 3.12 Decision

### Community 31 - "Streaming Latency Metrics"
Cohesion: 0.67
Nodes (3): Extended RequestResult with TTFT/TPOT fields (Phase 5), Time-per-Output-Token (TPOT) measurement, Time-to-First-Token (TTFT) measurement

### Community 33 - "Phase 1 Constraints"
Cohesion: 1.0
Nodes (2): Constitution Check, No vLLM Dependency in Phase 1 Decision

### Community 34 - "CI Baseline Results"
Cohesion: 1.0
Nodes (2): CI benchmark summary (stub servers, no live model), Phase 3 CI baseline benchmark (stub servers)

### Community 54 - "Bootstrap Flow"
Cohesion: 1.0
Nodes (1): Bootstrap Flow

### Community 55 - "Task Runner Decision"
Cohesion: 1.0
Nodes (1): Task Runner (make) Decision

### Community 56 - "CI Strategy Decision"
Cohesion: 1.0
Nodes (1): CI Strategy Decision

### Community 57 - "Chat Bridge Quickstart"
Cohesion: 1.0
Nodes (1): Phase 3 Chat Bridge Quickstart

### Community 58 - "Benchmark Harness Spec"
Cohesion: 1.0
Nodes (1): Phase 4 Benchmark Harness Feature Specification

### Community 59 - "Modal gRPC Research"
Cohesion: 1.0
Nodes (1): Modal gRPC Frontend Research

## Knowledge Gaps
- **157 isolated node(s):** `Standalone stub HTTP server for CI and bench-ci smoke tests.  Usage:     python`, `FakeChatServicer yields: 'Hello' + ' world' + finish.     Proxy emits: role-delt`, `Download model weights into the persistent volume (CPU-only; no GPU needed).`, `Start gRPC frontend, expose via TCP tunnel, block until stop signal.`, `Run vLLM serve + prompt_embeds verification inside the Modal container.` (+152 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Completions Endpoint Tests`** (13 nodes): `test_completions_endpoint.py`, `_fake_stream()`, `mock_completions_client()`, `test_both_inputs_returns_422()`, `test_grpc_invalid_argument_returns_422_from_grpc()`, `test_grpc_unavailable_returns_502()`, `test_neither_input_returns_422()`, `test_non_streaming_embeds_prompt_returns_200()`, `test_non_streaming_text_prompt_returns_200()`, `test_streaming_consistent_id()`, `test_streaming_grpc_error_emits_error_event()`, `test_streaming_returns_event_stream()`, `test_streaming_sse_sequence()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Chat Endpoint Tests`** (12 nodes): `test_chat_endpoint.py`, `_fake_stream()`, `mock_chat_client()`, `test_grpc_unavailable_returns_502()`, `test_happy_path_returns_200_with_openai_json()`, `test_max_tokens_zero_returns_422()`, `test_missing_messages_returns_422()`, `test_non_stream_unaffected_by_streaming_changes()`, `test_stream_completion_id_consistent()`, `test_stream_event_sequence()`, `test_stream_grpc_error_emits_error_event()`, `test_stream_true_returns_sse_content_type()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Weight Download Script`** (4 nodes): `download_weights()`, `main()`, `Download model weights into the persistent volume (CPU-only; no GPU needed).`, `modal_download_weights.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Modal GPU Verification`** (4 nodes): `verify_prompt_embeds_modal.py`, `main()`, `Run vLLM serve + prompt_embeds verification inside the Modal container.`, `_verify_on_gpu()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `REST Smoke Test Script`** (4 nodes): `main()`, `Run REST smoke test inside the Modal container.`, `smoke_test()`, `modal_vllm_rest.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Test Configuration`** (4 nodes): `anyio_backend()`, `conftest.py`, `conftest.py`, `conftest.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Health Endpoint Tests`** (4 nodes): `test_healthz.py`, `test_healthz_returns_200_when_ping_succeeds()`, `test_healthz_returns_503_when_ping_fails()`, `test_healthz.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `vLLM Mock Fixtures`** (3 nodes): `mock_vllm()`, `Inject a fake vllm module so frontend tests run without a GPU install.`, `conftest.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Health Servicer`** (3 nodes): `HealthServicer`, `.Ping()`, `health.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Phase 1 Constraints`** (2 nodes): `Constitution Check`, `No vLLM Dependency in Phase 1 Decision`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `CI Baseline Results`** (2 nodes): `CI benchmark summary (stub servers, no live model)`, `Phase 3 CI baseline benchmark (stub servers)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Bootstrap Flow`** (1 nodes): `Bootstrap Flow`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Task Runner Decision`** (1 nodes): `Task Runner (make) Decision`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `CI Strategy Decision`** (1 nodes): `CI Strategy Decision`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Chat Bridge Quickstart`** (1 nodes): `Phase 3 Chat Bridge Quickstart`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Benchmark Harness Spec`** (1 nodes): `Phase 4 Benchmark Harness Feature Specification`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Modal gRPC Research`** (1 nodes): `Modal gRPC Frontend Research`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `proxy FastAPI app (main.py)` connect `REST Proxy & Streaming API` to `Modal Deployment Infrastructure`, `gRPC Frontend Server Layer`, `CI Benchmark & Tunnel State`?**
  _High betweenness centrality (0.252) - this node is a cross-community bridge._
- **Why does `bench_modal.py Modal benchmark orchestration` connect `CI Benchmark & Tunnel State` to `REST Proxy & Streaming API`, `Modal Deployment Infrastructure`, `Streaming & Completions Architecture`?**
  _High betweenness centrality (0.183) - this node is a cross-community bridge._
- **Are the 20 inferred relationships involving `main()` (e.g. with `load_corpus()` and `run_grpc_target()`) actually correct?**
  _`main()` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `RequestResult` (e.g. with `TestPercentile` and `TestComputeSummaries`) actually correct?**
  _`RequestResult` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `CompletionsClient` (e.g. with `_FakeStreamCall` and `Minimal async-iterable that also exposes .cancel() like a gRPC call object.`) actually correct?**
  _`CompletionsClient` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `compute_summaries()` (e.g. with `_make_run()` and `.test_all_success_non_none_p50()`) actually correct?**
  _`compute_summaries()` has 16 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Standalone stub HTTP server for CI and bench-ci smoke tests.  Usage:     python`, `FakeChatServicer yields: 'Hello' + ' world' + finish.     Proxy emits: role-delt`, `Download model weights into the persistent volume (CPU-only; no GPU needed).` to the rest of the system?**
  _157 weakly-connected nodes found - possible documentation gaps or missing edges._