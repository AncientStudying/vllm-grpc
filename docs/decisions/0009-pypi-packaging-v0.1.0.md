# ADR 0009 — PyPI packaging for v0.1.0: build-time stubs, vLLM as an opt-in extra, static versioning

**Status:** accepted (2026-05-30) · feature `specs/030-pypi-release-v0.1.0/` · resolves the C1
constitution finding from `/speckit-analyze`

> This ADR records the non-obvious, hard-to-reverse architectural choices behind the first PyPI
> release of the four `packages/` workspace members (`vllm-grpc-gen`, `vllm-grpc-proxy`,
> `vllm-grpc-frontend`, `vllm-grpc-client`). The constitution's Development Workflow requires an ADR
> for non-obvious architectural choices; three qualify here. Mechanical packaging (filling
> classifiers, authors, URLs, READMEs) is *not* recorded — it is routine and reversible.

## Context

v0.1.0 brings the four packages to a publish-ready, installable state **without performing any
external upload** (the upload is a later, operator-gated action). Three decisions in that work are
non-obvious because each touches a constitution principle or an irreversible-once-published
property of distribution metadata:

1. **How do the generated protobuf/gRPC stubs reach the `vllm-grpc-gen` distribution?** The stubs
   are gitignored (`.gitignore` 217–221) and produced by `make proto`; a bare `uv build` of `gen`
   would otherwise ship an empty package. Constitution **Principle I (Proto-First)** forbids
   committing stubs and requires build-time generation from `proto/`.
2. **How does the frontend declare its vLLM requirement?** vLLM ships CUDA-only wheels with no
   macOS build (the repo already works around this with `vllm-metal` / `--with vllm`). A hard
   dependency would break `pip install vllm-grpc-frontend` on any platform without a vLLM wheel.
   But Constitution **Principle II (Library Dependency, Not Fork)** says the frontend MUST depend on
   vLLM "via its public `pyproject.toml` dependency declaration, pinned to a compatible version
   range." These pull in opposite directions.
3. **How is each package's version sourced?** The repo carries two independent tag namespaces —
   `v*` (codebase state / semver) and `milestone/*` (research deliverables) — so a VCS-derived
   version would be ambiguous.

## Decision

### D1 — Build-time stub generation via a hatchling build hook (honors Principle I)

`vllm-grpc-gen` gains a `hatch_build.py` build hook (a `BuildHookInterface`) that runs
`python -m grpc_tools.protoc -I proto --python_out=src --grpc_python_out=src` for the three
production protos during the wheel/sdist build, and declares `grpcio-tools` + `protobuf` in
`[build-system].requires`. Generated stubs stay **gitignored**; `proto/` remains the single source
of truth; the sdist force-includes the needed `proto/` sources so the hook reproduces stubs when
building from an sdist in a clean environment.

- *Reuse rule (honors Principle I's "single mechanism" intent):* the hook reuses the **same**
  `protoc` invocation as the `make proto` Makefile target, so the two never drift. The existing
  `proto.yml` CI no-diff check is unaffected.
- *Alternative rejected:* commit the stubs (violates Principle I); a `hatch-protobuf` plugin (adds a
  third-party build dep where a ~30-line in-repo hook suffices and is auditable).

### D2 — vLLM declared as an opt-in `engine` extra (reconciles Principle II with the peer posture)

The frontend declares vLLM **only** as an optional dependency extra, never as a default dependency:

```toml
[project.dependencies]            # base install — NO vLLM
# grpcio>=1.80, vllm-grpc-gen~=0.1.0
[project.optional-dependencies]
engine = ["vllm>=0.20"]           # opt-in: pip install "vllm-grpc-frontend[engine]"
```

- `pip install vllm-grpc-frontend` pulls **no** vLLM → stays installable on vLLM-less platforms
  (FR-005); the missing engine surfaces only at runtime, not at install time.
- `pip install "vllm-grpc-frontend[engine]"` resolves `vllm>=0.20` — the floor is now
  **machine-readable**, not buried in prose.
- Declaring vLLM as a pinned-range dependency in `pyproject.toml` **satisfies Principle II** (vLLM is
  a versioned library dependency, not a fork) without forcing it onto incompatible platforms — so
  **no constitution amendment is required**.
- The `>=0.20` floor is honest: it is "the line this project is built and tested against" (root
  `graph-targets` pins `vllm==0.20.1`, `uv.lock` agrees, macOS uses `vllm-metal 0.2.0`), and the
  frontend's V1 `AsyncLLM` engine path (see D-adjacent remediation FR-022) requires the V1 engine
  API. It is not a bisected absolute minimum.

**Decision history (why this ADR exists).** An earlier clarification pass chose "vLLM in **no**
metadata, floor documented only." `/speckit-analyze` finding **C1** showed this both (a) hid a real
functional floor and (b) conflicted with Principle II's MUST to declare vLLM via a pinned
`pyproject.toml` dependency. Three options were weighed:

| Option | Principle II | Base install on vLLM-less platform | Floor machine-readable |
|--------|--------------|-------------------------------------|------------------------|
| Hard dependency `vllm>=0.20` | ✅ satisfied | ❌ breaks (no wheel) | ✅ |
| Pure peer, zero metadata (prior choice) | ❌ conflict → needs amendment | ✅ installs | ❌ doc-only |
| **Opt-in `engine` extra (chosen)** | ✅ satisfied | ✅ installs | ✅ |

The extra is the only option that satisfies all three columns. The owner confirmed it on 2026-05-30.

### D3 — Static literal versioning (`version = "0.1.0"`), no VCS-derived version

Each package hard-codes `version = "0.1.0"`; no `dynamic = ["version"]`, no `hatch-vcs`. The release
procedure bumps all four in lockstep as one documented step (CONTRIBUTING) before tagging.

- *Rationale:* the dual `v*` / `milestone/*` tag namespaces make a VCS version ambiguous; static
  literals keep versioning explicit and auditable, and decouple package versions from the
  `milestone/*` research tags (which must never drive a package version).
- *Alternative rejected:* `hatch-vcs` deriving the version from tags — ambiguous under two tag
  namespaces.

### D4 — Four lean packages, internal pin `vllm-grpc-gen~=0.1.0`, gen owns the runtime imports

The three leaf packages depend on `vllm-grpc-gen~=0.1.0` (compatible-release: pins the minor line,
allows a patch `gen`) so an index install resolves a *published* stubs package, not a workspace
path. `vllm-grpc-gen` declares the runtime deps its generated code imports (`protobuf>=6.33`,
`grpcio>=1.80`) so it is independently installable; the leaves inherit `protobuf` transitively and
keep a direct `grpcio>=1.80`. Third-party floors are floor-only / no caps, bumped to the
`uv.lock`-resolved versions. (Recorded for completeness; this is standard SDK practice but the
`~=0.1.0` choice and the gen-owns-protobuf split were deliberate.)

## Consequences

- **Principle I upheld and reinforced:** stubs are build-time-generated and never committed; CI's
  proto no-diff check still passes; one protoc invocation shared between `make proto` and the build
  hook.
- **Principle II upheld without amendment:** the C1 conflict is resolved at the source. vLLM is a
  declared, version-ranged library dependency (the extra) that is never force-installed — so the
  frontend remains installable everywhere while the engine floor is auditable in `METADATA`
  (`Provides-Extra: engine` + `Requires-Dist: vllm>=0.20; extra == "engine"`).
- **New install surface for operators:** `pip install "vllm-grpc-frontend[engine]"` becomes the
  one-command path to a working engine on supported platforms; the bare install stays the
  platform-agnostic path. Documented in the frontend README + root install matrix (FR-005a/FR-016).
- **Versioning is manual:** the lockstep version bump is a release-procedure step (a small recurring
  cost) traded for unambiguous, tag-namespace-independent versions.
- **Lockfile coupling:** the dependency-floor bumps + new `gen` deps + the `engine` extra require a
  `uv.lock` refresh, or CI's `uv sync --frozen` fails (tracked as task T026a — the `/speckit-analyze`
  H1 finding).
- **Reversibility:** D1/D3/D4 are internal and reversible pre-publish. D2's *published* metadata is
  effectively permanent per version once uploaded — but no upload occurs in this feature, so the
  shape can still change before the operator's first publish.

## References

- `specs/030-pypi-release-v0.1.0/spec.md` — FR-005/FR-005a (vLLM extra), FR-007a (build hook),
  FR-003b (static version), FR-006/006a/006b/006c (deps), SC-007a/SC-013.
- `specs/030-pypi-release-v0.1.0/plan.md` — Constitution Check (Principle I, II) ; `research.md`
  R1 (build hook), R5 (vLLM floor + decision history), R7 (versioning).
- `specs/030-pypi-release-v0.1.0/contracts/package-metadata.md` — C-D4 (engine-extra assertion).
- `.specify/memory/constitution.md` — Principle I (Proto-First), Principle II (Library Dependency,
  Not Fork), Development Workflow (ADR requirement).
- `/speckit-analyze` report (2026-05-30) — finding **C1** (Principle II conflict), **H1** (lockfile
  refresh), **M4** (this ADR).
