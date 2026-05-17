# Contract: `network_paths` block

**Branch**: `025-m6-1-2-methodology-discipline` | **Phase 1 output** | **Plan**: [../plan.md](../plan.md)

## Purpose

The `network_paths` top-level field on the M6.1.2 sweep artifact JSON captures per-sweep topology evidence — which cloud provider each cohort's endpoint actually routes through, and the hop-by-hop path the operator's machine traversed to reach it — for the SPECIFIC deploy that produced the sweep. Tunnel IDs are ephemeral per deploy (Spike #1 finding: `r437.modal.host`, `r439.modal.host`, `ta-01krv...modal.host` are all session-scoped); without per-sweep capture, the artifact can only assert the architectural pattern observed on the spike date.

## Wire shape

`network_paths` is a JSON object keyed by cohort name. Each cohort entry is one of two discriminated shapes:

### Success entry

```jsonc
{
  "network_paths": {
    "rest_https_edge": {
      "endpoint_ip": "20.125.113.97",
      "hops": [
        { "hop_number": 1, "ip": "192.168.2.1", "rtt_ms_or_null": 1.2,  "cloud_provider": null },
        { "hop_number": 2, "ip": "192.168.1.1", "rtt_ms_or_null": 1.5,  "cloud_provider": null },
        { "hop_number": 3, "ip": null,          "rtt_ms_or_null": null, "cloud_provider": null },
        { "hop_number": 4, "ip": "173.219.208.88", "rtt_ms_or_null": 5.6,  "cloud_provider": null },
        { "hop_number": 5, "ip": "173.219.197.48", "rtt_ms_or_null": 6.1,  "cloud_provider": null },
        { "hop_number": 6, "ip": "104.44.14.37",   "rtt_ms_or_null": 21.4, "cloud_provider": "Microsoft Azure" },
        { "hop_number": 9, "ip": "51.10.39.124",   "rtt_ms_or_null": 102.8, "cloud_provider": "Microsoft Azure" }
      ],
      "cloud_provider": "Microsoft Azure",
      "region": null,
      "probe_method": "tcptraceroute",
      "probed_at_utc": "2026-05-17T12:34:56Z"
    },
    "rest_plain_tcp": {
      "endpoint_ip": "54.193.31.244",
      "hops": [
        { "hop_number": 1, "ip": "192.168.2.1", "rtt_ms_or_null": 1.2, "cloud_provider": null },
        { "hop_number": 7, "ip": "62.115.138.65", "rtt_ms_or_null": 95.4, "cloud_provider": "Telia" }
      ],
      "cloud_provider": "AWS",
      "region": "us-west-1",
      "probe_method": "tcptraceroute",
      "probed_at_utc": "2026-05-17T12:34:56Z"
    },
    "default_grpc":            { /* ... same shape ... */ },
    "tuned_grpc_multiplexed":  { /* ... same shape ... */ }
  }
}
```

### Error entry (FR-005, per-cohort)

```jsonc
{
  "network_paths": {
    "rest_plain_tcp": {
      "error": "probe_timeout",
      "probe_method": "tcptraceroute",
      "probed_at_utc": "2026-05-17T12:34:56Z",
      "detail": "tcptraceroute exceeded 30s wall-clock for rest_plain_tcp endpoint 54.193.31.244:43209"
    }
  }
}
```

## Field reference

### Cohort-level fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `endpoint_ip` | string | yes (success) | The IP that DNS resolution returned at probe time. May differ across deploys (Modal tunnel IPs are ephemeral). |
| `hops` | array | yes (success) | Ordered list of `M6_1_2NetworkPathHop` entries; `hop_number` ascending. |
| `cloud_provider` | enum string | yes (success) | One of `"AWS"`, `"Microsoft Azure"`, `"GCP"`, `"unknown"`. Closed enum — no other values allowed at the cohort level. Round-1 Q5 + round-3 Q1 source-of-truth. |
| `region` | string \| null | yes (success) | e.g., `"us-west-1"`; `null` when `cloud_provider == "unknown"` OR when the IP-range file's prefix entry doesn't carry a region (rare for AWS/Azure; common for GCP global services). |
| `probe_method` | literal `"tcptraceroute"` | yes (always) | FR-002 + round-2 Q3 pinned to the literal string. |
| `probed_at_utc` | ISO-8601 UTC | yes (always) | Regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`. Second precision (matches `_stderr_ts()` per FR-019). |
| `error` | enum string | yes (failure) | One of `"tcptraceroute_unavailable"`, `"probe_timeout"`, `"subprocess_error"`, `"parse_error"`. Discriminates an error entry from a success entry. |
| `detail` | string \| null | optional (failure) | Human-readable detail (e.g., the stderr line that surfaced). May be `null`. |

### Per-hop fields (within `hops[]`)

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `hop_number` | integer ≥ 1 | yes | TTL value; monotonically increasing within the cohort. |
| `ip` | string \| null | yes | Dotted-decimal IPv4 or colon-separated IPv6. `null` when `tcptraceroute` reports an asterisk (filtered hop). |
| `rtt_ms_or_null` | float \| null | yes | Round-trip time in milliseconds; `null` when `ip` is `null` or RTT wasn't measured. |
| `cloud_provider` | string \| null | yes | **Best-effort** per FR-003 + round-3 Q1. Allowed values: cohort-level enum (`"AWS"` / `"Microsoft Azure"` / `"GCP"` / `"unknown"`) OR a transit-ASN string (`"Telia"`, `"Cogent"`, etc.) OR `null` when lookup didn't resolve. |

## Probe execution semantics (FR-001 / FR-001a / FR-002 / FR-002a)

The probe runs ONCE per sweep, BEFORE warmup and the first measurement cell. It executes in parallel across cohorts via `asyncio.gather(*(asyncio.to_thread(_probe_one_cohort, c) for c in cohorts))`. Per-cohort wall-clock timeout is 30 seconds; expiration fires `subprocess.TimeoutExpired` which is caught and converted to an error entry (`error: "probe_timeout"`).

Worst-case probe wall-clock at sweep start: ~30 seconds regardless of cohort count (parallel execution). Best-case: ~5-10 seconds (the spike's 3-cohort run completed in 97s total wallclock including Modal deploy; subtracting the ~74s cold start gives ~23s for the traceroute step).

## Warnings emitted to stderr (FR-005a / FR-006)

All warnings emitted during the probe phase carry the `[YYYY-MM-DDTHH:MM:SSZ]` ISO-8601 prefix per FR-020 (round-2 Q5).

### FR-005a: all-cohort-failed

If every cohort's probe records an error entry in a single sweep, the harness emits at sweep start:

```text
[2026-05-17T12:34:56Z] WARNING: every cohort probe failed (4/4: tcptraceroute_unavailable); `network_paths` block contains error records only — topology evidence is unavailable for this sweep
```

Sweep continues. Artifact records 4 error entries in `network_paths`. Per round-1 Q3: realistic all-fail scenarios (binary absent, firewall blocks scan-like SYN, transit hops time out) all leave the measurement RPCs themselves working, so aborting would punish operators in those environments.

### FR-006: cohort entered a different CSP than spike-expected

If the probe observes a cohort entering a different CSP than the spike-confirmed expectation (`rest_https_edge` → `"Microsoft Azure"`; `*.modal.host` cohorts → `"AWS"` `"us-west-1"`), the harness emits at sweep start:

```text
[2026-05-17T12:34:56Z] WARNING: cohort rest_https_edge entered AWS rather than expected Microsoft Azure; topology has changed
```

Sweep proceeds. Artifact records the observed reality unchanged. Per FR-006: methodology-disrupting Modal architecture changes are surfaced loudly rather than silently absorbed.

## Strict-superset schema evolution (FR-004)

`network_paths` is a new top-level key on the M6.1.2 artifact. M6.1.1-vintage readers (the M6.1.1 reporter's JSON loader, the M6.2 consumer-to-be) ignore the unknown top-level key without parse error. No `schema_version` bump. The M6.1.1 manifest at `docs/benchmarks/m6_1_1-engine-cost-instrumentation.json` is unchanged.

The integration test `tools/benchmark/tests/test_m6_1_2_artifact_schema.py` exercises this:

```python
def test_m6_1_2_artifact_parses_with_m6_1_1_reader() -> None:
    """FR-004 + SC-006: an M6.1.1-vintage reader parses an M6.1.2 artifact
    without error, ignoring the new top-level keys."""
    m6_1_2_artifact = synthesize_artifact_with_network_paths()
    from vllm_grpc_bench.m6_1_1_reporter import parse_json  # M6.1.1's reader
    result = parse_json(m6_1_2_artifact)  # Must not raise
    assert "network_paths" not in result.__dict__  # M6.1.1 reader doesn't know the field
    assert result.schema_version == m6_1_2_artifact["schema_version"]
```

## CSP attribution algorithm (FR-007)

The cohort-level `cloud_provider` is derived from `endpoint_ip` as follows:

1. **AWS check**: load `https://ip-ranges.amazonaws.com/ip-ranges.json` (24h cache); linear search `prefixes[]` for an `ip_prefix` that contains `endpoint_ip`. If hit, return `("AWS", prefix.region)`.
2. **Azure check**: load Azure's JSON (24h cache); linear search prefixes. If hit, return `("Microsoft Azure", prefix.region or null)`.
3. **GCP check**: load `https://www.gstatic.com/ipranges/cloud.json` (24h cache); linear search prefixes. If hit, return `("GCP", prefix.scope or null)`.
4. **Whois fallback**: ARIN whois on `endpoint_ip` (5s timeout, single attempt, no retry). If the org maps to a CSP (e.g., `"Amazon Technologies"` → `"AWS"`), return that. If it doesn't, return `(<org-name-string>, null)` for the per-hop field — but the COHORT-LEVEL field still requires the closed enum, so the cohort-level lookup returns `("unknown", null)` in this case.
5. **Final fallback**: `("unknown", null)`.

The per-hop `cloud_provider` field uses the same algorithm but without the enum-closure constraint: per-hop annotations may hold the transit-ASN org string (e.g., `"Telia"`) directly. Per round-3 Q1: best-effort, no retry, no rate-limit handling.

## Cross-references

- Plan: [`../plan.md`](../plan.md) — Technical Context (R-5, R-6).
- Data model: [`../data-model.md`](../data-model.md) — `M6_1_2NetworkPath`, `M6_1_2NetworkPathError`, `M6_1_2NetworkPathHop`.
- Spec: [`../spec.md`](../spec.md) — FR-001 / FR-001a / FR-002 / FR-002a / FR-003 / FR-004 / FR-005 / FR-005a / FR-006 / FR-007 + round-3 Q1.
- Spike reference: [`docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md`](../../../docs/spikes/m6-1-roadmap-additions/01-topology-traceroute-findings.md) — the live `traceroute` proof; the JSON shape in this contract is informed by that table.
- Spike probe code: [`docs/spikes/m6-1-roadmap-additions/traceroute_probe.py`](../../../docs/spikes/m6-1-roadmap-additions/traceroute_probe.py) — pattern that R-5 ports to `tcptraceroute`.
