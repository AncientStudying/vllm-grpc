# Spike #1 — Live traceroute proof of HTTPS-Edge vs TCP-tunnel topology asymmetry

**Branch**: `spike/m6-1-roadmap-additions`
**Date**: 2026-05-17
**Probe script**: [`traceroute_probe.py`](./traceroute_probe.py) (throwaway; M6.1.2 will own the harness integration)

## TL;DR

The cohorts don't just use "different network paths" — they enter Modal via **entirely different cloud providers**:

- `rest_https_edge` (M5.x `*.modal.run` cohort) enters via **Microsoft Azure** infrastructure (Azure West US edge → Azure Europe ingress).
- `rest_plain_tcp` and `default_grpc` / `tuned_grpc_*` (M5.x `*.modal.host` cohorts) enter via **AWS us-west-1** infrastructure via Telia (Tier-1 transit).

This is a stronger architectural claim than ANALYSIS.md's "different network path." It means latency differences attributed to "HTTPS edge" actually conflate at least three variables: protocol (HTTPS vs raw TCP), TLS termination location (Modal edge POP vs Modal worker), and **CSP routing path** (Azure vs AWS).

## Method

1. Spawned `vllm-grpc-bench-rest-grpc-mock` on Modal `eu-west-1` (CPU-only mock, ~74s cold start).
2. Read the three tunnel URLs from the handshake `modal.Dict`.
3. Ran `traceroute -n -w 2 -q 1 -m 18` against each from this Mac in parallel.
4. Signaled `teardown=True` to gracefully stop the function.
5. Total wallclock: 97s. Approximate Modal cost: $0.05.

## Endpoint resolutions (single probe; live tunnel IDs)

| Cohort | URL | Resolved IP | Cloud | Region |
|---|---|---|---|---|
| `rest_https_edge` | `https://ta-01krv2x8qxtbbrr9zc28t0mk2x-8001-zloa21xno87y8brz8htww82qn.w.modal.host` | `20.125.113.97` | **Microsoft Azure** (MSFT) | (varies, see hops) |
| `rest_plain_tcp` | `tcp+plaintext://r439.modal.host:43209` | `54.193.31.244` | **AWS** (`54.193.0.0/16`) | **us-west-1** |
| `grpc` (default + tuned) | `tcp+plaintext://r437.modal.host:46869` | `54.183.130.86` | **AWS** (`54.183.0.0/16`) | **us-west-1** |

AWS region confirmation via `ip-ranges.amazonaws.com/ip-ranges.json`. Azure attribution via ARIN whois (`NetName: MSFT`, `OrgName: Microsoft Corporation`).

## Path traces (hops past hop 5; AWS/Azure firewall ICMP past edge)

| Hop | `rest_https_edge` | `rest_plain_tcp` | `grpc` |
|---|---|---|---|
| 1 | `192.168.2.1` (local) | same | same |
| 2 | `192.168.1.1` (local) | same | same |
| 3 | `*` (ISP edge) | same | same |
| 4 | `173.219.208.88` (ISP) | same | same |
| 5 | `173.219.197.48` (ISP) | same | same |
| 6 | **`104.44.14.37` (Microsoft, Redmond WA)** | `*` | `213.248.88.228` (Telia) |
| 7 | `*` | **`62.115.138.65` (Telia)** | `62.115.141.160` (Telia) |
| 8 | `*` | `62.115.140.246` (Telia) | `62.115.140.236` (Telia) |
| 9 | **`51.10.39.124` (Azure Europe, RIPE-NCC allocation)** | `62.115.142.167` (Telia) | `62.115.142.179` (Telia) |
| 10 | `51.10.32.29` (Azure Europe) | `*` | `*` |
| 11 | `51.10.11.166` (Azure Europe) | `*` | `*` |
| 12-18 | `*` (filtered past edge) | `*` | `*` |

**Divergence point: hop 6.** HTTPS-Edge enters Microsoft Azure; both TCP-tunnel cohorts enter Telia (Tier-1 transit), then traverse to AWS us-west-1.

## What this changes / confirms

1. **ANALYSIS.md's "different network path" claim is correct but understated.** The actual asymmetry is multi-cloud routing, not just route-level divergence. Worth updating the wording when this lands.

2. **The `rest_https_edge` cohort isn't a "Modal HTTPS edge" — it's Microsoft Azure's edge fronting a Modal worker.** When we attribute latency to "edge", we're really attributing it to the Azure→Modal handoff plus Modal's internal backbone Azure-Europe→eu-west-1-worker hop.

3. **The plain-TCP cohorts enter AWS us-west-1 even though the Modal worker is requested in `eu-west-1`.** That means TCP-tunnel traffic crosses the Atlantic at least twice for every RPC (Mac → AWS us-west-1 → Modal internal → eu-west-1 worker, response retraces). For latency-sensitive comparisons, the geographic asymmetry is large.

4. **The previously-observed REST vs gRPC ~2× RTT gap** (referenced in `modal_bench_rest_grpc_server.py:177` as "REST ~185 ms, gRPC ~360 ms") was almost certainly partly explained by Azure↔Modal vs AWS↔Modal transit cost differences, NOT purely TLS termination cost.

5. **The endpoint IPs are ephemeral per deploy.** `r437.modal.host` / `r439.modal.host` / `ta-01krv...modal.host` are session-scoped; the WILDCARD `*.modal.host` does not resolve. So per-sweep traceroute is the only way to capture the actual path for a given Phase 1 / Phase 2 run.

## Implications for M6.1.2

> **M6.1.2 scope MUST include "add per-sweep traceroute probe to harness" as a deliverable.**
>
> The architectural evidence (Azure for `*.modal.run`, AWS us-west-1 entry for `*.modal.host`) is stable enough to claim once, but for the "continually supported (or refuted) in data as we go through the two major test and validation phases" goal articulated in the spike-kickoff, the per-sweep probe is non-negotiable. Tunnel IDs change every deploy; without per-sweep traceroute, the artifact can only assert "the cohorts conform to the architectural pattern observed on 2026-05-17."

Concrete asks for M6.1.2:

- **Per-cohort hop-trace** captured at sweep start (before the first cell), stored in the artifact JSON under `network_paths: {<cohort>: {endpoint_ip, hops: [...], cloud_provider, region}}`.
- **Cloud-provider + region annotation** per hop, ideally via the AWS/Azure/GCP published IP-range files + whois fallback for transit ASNs (Telia / Cogent / etc.).
- **Stderr line on divergence**: if a future sweep observes the cohorts entering the SAME cloud (architectural change on Modal's side), surface it loudly — that's a methodology-disrupting event.
- **TCP-based probe**: standard `traceroute` (UDP/ICMP) dies at the AWS/Azure firewall around hop 5. Use `tcptraceroute` or equivalent (TCP SYN to the actual tunnel port) so the probe reaches further into the cloud network before dropping.
- **Single-shot per sweep**, not per cell. The path is stable for the duration of a deploy.

## Implications for the rest of the spike

- **Item 2 (cohort reintroduction)** is partially answered: the `rest_plain_tcp` cohort lives in the same `*.modal.host` AWS-fronted bucket as the gRPC cohorts. Comparing `rest_plain_tcp` vs `default_grpc` isolates pure protocol cost (same CSP, same region, same path); comparing either against `rest_https_edge` isolates the multi-cloud routing cost. This is a strong argument for the 3-cohort split the user proposed.
- **Item 3 (timestamp on progress lines)** unchanged.
- **Items 4-6 (proxy-edge instrumentation, drift root-cause, run-to-run variance)** independent of this finding.

## Raw probe output

See [`traceroute_probe.output.txt`](./traceroute_probe.output.txt) for the literal stdout of the probe run (includes the live tunnel IDs that have since been torn down).
