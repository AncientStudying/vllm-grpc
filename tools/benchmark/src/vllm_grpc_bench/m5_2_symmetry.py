"""M5.2 3-tier symmetry block (FR-005b + research R-3).

Tier (a) — cross-cohort invariants the entire run MUST share (corpus hash,
Modal deploy handle, MockEngine config digest, warmup batch policy).
Asserted at run start; abort the run on any mismatch.

Tier (b) — intra-protocol pair invariants. The two REST cohorts MUST share
their client-config digest EXCEPT for the target URL field; the two
``tuned_grpc_*`` cohorts MUST share their channel-config digest EXCEPT for
the multiplexing topology field. At c=1 the two tuned cohorts collapse to
``tuned_grpc`` per FR-006, so the tuned-pair assertion is skipped (the
``tier_b_skipped_c1_tuned_grpc_pair`` flag is replicated onto every tier (c)
entry for the c=1 cohort).

Tier (c) — per-cohort metadata recorded for post-hoc audit (no
cross-assertion). Indexed by cohort name.

The block is persisted as a top-level key in the M5.2 JSON aggregate. The
asserter is invoked at run start AND at report-build time (by the
regenerator) so a post-hoc replay can't publish a corrupted-symmetry run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from vllm_grpc_bench.m3_types import M5_2CohortKind


class SymmetryAssertionFailed(RuntimeError):
    """Raised by :func:`assert_symmetry` on tier (a) or tier (b) divergence.

    The exception message names the diverging tier, field, and cohort pair so
    the operator can `grep` the symmetry block in the published JSON to
    locate the divergent state.
    """

    def __init__(
        self,
        *,
        tier: str,
        field: str,
        cohort_a: str = "",
        cohort_b: str = "",
        observed_a: str = "",
        observed_b: str = "",
    ) -> None:
        self.tier = tier
        self.field = field
        self.cohort_a = cohort_a
        self.cohort_b = cohort_b
        self.observed_a = observed_a
        self.observed_b = observed_b
        msg = (
            f"tier_{tier}_divergence: field={field}"
            + (f", cohort_a={cohort_a}" if cohort_a else "")
            + (f", cohort_b={cohort_b}" if cohort_b else "")
            + (f", observed_a={observed_a[:16]}…" if observed_a else "")
            + (f", observed_b={observed_b[:16]}…" if observed_b else "")
        )
        super().__init__(msg)


@dataclass(frozen=True)
class CrossCohortInvariants:
    """Tier (a) — every cohort MUST share these. Asserted fail-fast."""

    prompt_corpus_hash: str
    modal_deploy_handle: str
    mock_engine_config_digest: str
    warmup_batch_policy: str


@dataclass(frozen=True)
class IntraProtocolPairInvariants:
    """Tier (b) — within-protocol-pair invariants."""

    # REST pair: rest_https_edge + rest_plain_tcp share this digest (computed
    # with the target URL field excepted — URL is the operative variable
    # between the two REST transports).
    rest_client_config_digest_url_excepted: str

    # tuned-gRPC pair: tuned_grpc_multiplexed + tuned_grpc_channels share
    # this digest (channel_topology field excepted). None when the run is
    # exclusively at c=1; the asserter records the skip in tier (c).
    tuned_grpc_channel_config_digest_topology_excepted: str | None


@dataclass(frozen=True)
class PerCohortMetadata:
    """Tier (c) — per-cohort audit metadata. No cross-assertion."""

    cohort: M5_2CohortKind
    client_config_digest_full: str
    modal_app_handle: str
    modal_region: str
    warmup_batch_size: int
    tier_b_skipped_c1_tuned_grpc_pair: bool


@dataclass(frozen=True)
class SymmetryBlock:
    """3-tier symmetry block per FR-005b. Persisted as a top-level key in
    the M5.2 JSON aggregate. The asserter raises on tier (a) or tier (b)
    divergence; tier (c) is audit-only.
    """

    tier_a: CrossCohortInvariants
    tier_b: IntraProtocolPairInvariants
    tier_c: list[PerCohortMetadata]
    client_external_geolocation_country: str | None
    client_external_geolocation_region: str | None


@dataclass(frozen=True)
class CohortConfigInput:
    """Input to :func:`build_symmetry_block` — one entry per cohort the
    sweep will dispatch.

    The harness builds these from the per-cohort configuration *before* any
    cohort dispatches so the symmetry block is fully populated by the time
    :func:`assert_symmetry` runs.
    """

    cohort: M5_2CohortKind
    prompt_corpus_hash: str
    modal_deploy_handle: str
    modal_app_handle: str
    modal_region: str
    mock_engine_config_digest: str
    warmup_batch_policy: str
    warmup_batch_size: int

    # Full per-cohort client-config payload (URL, topology, etc.) — used to
    # build the tier (b) and tier (c) digests via canonical JSON hash.
    client_config_full: dict[str, Any] = field(default_factory=dict)

    # For REST cohorts: the operative URL field that's excepted from tier
    # (b)'s pair digest. The harness passes the key name (typically
    # ``"base_url"``) so the digester knows which field to drop.
    rest_url_excepted_field: str | None = None

    # For tuned-gRPC cohorts: the operative topology field that's excepted
    # from tier (b)'s pair digest (typically ``"channel_topology"``).
    grpc_topology_excepted_field: str | None = None


def canonical_digest(payload: dict[str, Any]) -> str:
    """SHA-256 hex of a canonical-JSON encoding of ``payload``.

    Canonical encoding is ``sort_keys=True`` + compact separators so the
    digest is byte-stable across Python versions and dict iteration orders.
    """
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _digest_excepting(payload: dict[str, Any], excepted_field: str | None) -> str:
    if excepted_field is None:
        return canonical_digest(payload)
    filtered = {k: v for k, v in payload.items() if k != excepted_field}
    return canonical_digest(filtered)


def build_symmetry_block(
    cohort_configs: list[CohortConfigInput],
    *,
    client_external_geolocation_country: str | None = None,
    client_external_geolocation_region: str | None = None,
) -> SymmetryBlock:
    """Build the 3-tier symmetry block from per-cohort configurations.

    Tier (a) uses the FIRST cohort's invariants as the canonical values;
    :func:`assert_symmetry` verifies every other cohort matches. The block
    is persistable as-is via dataclass-asdict-style serialization.
    """
    if not cohort_configs:
        raise ValueError("build_symmetry_block: cohort_configs must be non-empty")

    head = cohort_configs[0]
    tier_a = CrossCohortInvariants(
        prompt_corpus_hash=head.prompt_corpus_hash,
        modal_deploy_handle=head.modal_deploy_handle,
        mock_engine_config_digest=head.mock_engine_config_digest,
        warmup_batch_policy=head.warmup_batch_policy,
    )

    # tier (b) pair digests, computed by finding the first matching cohort
    # of each pair-side and digesting its config with the operative field
    # excepted. The asserter checks the OTHER side of the pair matches.
    rest_digest = ""
    grpc_topology_digest: str | None = None
    seen_c1_only_tuned = True
    for cfg in cohort_configs:
        if cfg.cohort in ("rest_https_edge", "rest_plain_tcp") and not rest_digest:
            rest_digest = _digest_excepting(cfg.client_config_full, cfg.rest_url_excepted_field)
        if cfg.cohort in ("tuned_grpc_multiplexed", "tuned_grpc_channels"):
            seen_c1_only_tuned = False
            if grpc_topology_digest is None:
                grpc_topology_digest = _digest_excepting(
                    cfg.client_config_full, cfg.grpc_topology_excepted_field
                )

    tier_b = IntraProtocolPairInvariants(
        rest_client_config_digest_url_excepted=rest_digest,
        tuned_grpc_channel_config_digest_topology_excepted=(
            None if seen_c1_only_tuned else grpc_topology_digest
        ),
    )

    tier_c: list[PerCohortMetadata] = [
        PerCohortMetadata(
            cohort=cfg.cohort,
            client_config_digest_full=canonical_digest(cfg.client_config_full),
            modal_app_handle=cfg.modal_app_handle,
            modal_region=cfg.modal_region,
            warmup_batch_size=cfg.warmup_batch_size,
            tier_b_skipped_c1_tuned_grpc_pair=(seen_c1_only_tuned and cfg.cohort == "tuned_grpc"),
        )
        for cfg in cohort_configs
    ]

    return SymmetryBlock(
        tier_a=tier_a,
        tier_b=tier_b,
        tier_c=tier_c,
        client_external_geolocation_country=client_external_geolocation_country,
        client_external_geolocation_region=client_external_geolocation_region,
    )


def assert_symmetry(
    block: SymmetryBlock,
    cohort_configs: list[CohortConfigInput],
    *,
    concurrency_levels: list[int] | None = None,
) -> None:
    """Verify the symmetry block's tier (a) and tier (b) invariants against
    the cohort configurations. Tier (c) is audit-only and never raises.

    ``concurrency_levels`` informs the c=1 degeneracy skip for the
    tuned-gRPC pair: if the run is exclusively at c=1, the tuned-pair
    digest in tier (b) is expected to be None and the asserter does NOT
    fail when the cohort list contains no ``tuned_grpc_multiplexed`` /
    ``tuned_grpc_channels`` entries.
    """
    if not cohort_configs:
        raise ValueError("assert_symmetry: cohort_configs must be non-empty")

    levels = list(concurrency_levels or [])
    only_c1 = bool(levels) and all(c == 1 for c in levels)

    # Tier (a): every cohort's invariants must match the block's tier (a).
    for cfg in cohort_configs:
        for field_name in (
            "prompt_corpus_hash",
            "modal_deploy_handle",
            "mock_engine_config_digest",
            "warmup_batch_policy",
        ):
            expected = getattr(block.tier_a, field_name)
            observed = getattr(cfg, field_name)
            if observed != expected:
                raise SymmetryAssertionFailed(
                    tier="a",
                    field=field_name,
                    cohort_a=cohort_configs[0].cohort,
                    cohort_b=cfg.cohort,
                    observed_a=expected,
                    observed_b=observed,
                )

    # Tier (b) REST pair: both REST cohorts must yield the same
    # ``digest_excepting(rest_url_excepted_field)``.
    rest_cohorts = [
        cfg for cfg in cohort_configs if cfg.cohort in ("rest_https_edge", "rest_plain_tcp")
    ]
    rest_digests: list[tuple[str, str]] = [
        (cfg.cohort, _digest_excepting(cfg.client_config_full, cfg.rest_url_excepted_field))
        for cfg in rest_cohorts
    ]
    if rest_digests:
        head_digest = rest_digests[0][1]
        if head_digest != block.tier_b.rest_client_config_digest_url_excepted:
            raise SymmetryAssertionFailed(
                tier="b",
                field="rest_client_config_digest_url_excepted",
                cohort_a="block",
                cohort_b=rest_digests[0][0],
                observed_a=block.tier_b.rest_client_config_digest_url_excepted,
                observed_b=head_digest,
            )
        for cohort_name, digest in rest_digests[1:]:
            if digest != head_digest:
                raise SymmetryAssertionFailed(
                    tier="b",
                    field="rest_client_config_digest_url_excepted",
                    cohort_a=rest_digests[0][0],
                    cohort_b=cohort_name,
                    observed_a=head_digest,
                    observed_b=digest,
                )

    # Tier (b) tuned-gRPC pair: SKIP at c=1-only runs.
    if not only_c1:
        tuned_cohorts = [
            cfg
            for cfg in cohort_configs
            if cfg.cohort in ("tuned_grpc_multiplexed", "tuned_grpc_channels")
        ]
        tuned_digests: list[tuple[str, str]] = [
            (
                cfg.cohort,
                _digest_excepting(cfg.client_config_full, cfg.grpc_topology_excepted_field),
            )
            for cfg in tuned_cohorts
        ]
        if tuned_digests:
            expected = block.tier_b.tuned_grpc_channel_config_digest_topology_excepted
            head_digest = tuned_digests[0][1]
            if expected is None or expected != head_digest:
                raise SymmetryAssertionFailed(
                    tier="b",
                    field="tuned_grpc_channel_config_digest_topology_excepted",
                    cohort_a="block",
                    cohort_b=tuned_digests[0][0],
                    observed_a=str(expected),
                    observed_b=head_digest,
                )
            for cohort_name, digest in tuned_digests[1:]:
                if digest != head_digest:
                    raise SymmetryAssertionFailed(
                        tier="b",
                        field="tuned_grpc_channel_config_digest_topology_excepted",
                        cohort_a=tuned_digests[0][0],
                        cohort_b=cohort_name,
                        observed_a=head_digest,
                        observed_b=digest,
                    )
