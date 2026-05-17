"""M6.1.2 — Per-sweep ``tcptraceroute`` topology probe (Story 1 / US1).

Captures per-cohort topology evidence at sweep start (FR-001 / FR-001a /
FR-002 / FR-002a) and produces a ``dict[cohort, M6_1_2NetworkPath |
M6_1_2NetworkPathError]`` keyed by cohort name. Per-cohort 30s wall-clock
timeout; cohorts probed in parallel via ``asyncio.gather`` +
``asyncio.to_thread``.

Cohort-level CSP attribution (FR-007 / R-6) is the closed enum
``M6_1_2CloudProvider``; per-hop annotation is best-effort (FR-003 +
round-3 Q1). The probe is methodology-supporting, not measurement-critical
(FR-005 / FR-005a): probe failures NEVER abort the sweep — they record
per-cohort error blocks. Two loud-stderr warnings on aggregate failures:
FR-005a (every cohort failed) and FR-006 (cohort entered a different CSP
than spike-expected pattern).

Architectural references:
- Spike: ``docs/spikes/m6-1-roadmap-additions/traceroute_probe.py``
- Plan: ``specs/025-m6-1-2-methodology-discipline/plan.md`` (R-5, R-6).
- Contract: ``specs/025-m6-1-2-methodology-discipline/contracts/network-paths.md``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vllm_grpc_bench.m6_1_2_types import (
    M6_1_2_COHORTS,
    M6_1_2CloudProvider,
    M6_1_2CohortKind,
    M6_1_2NetworkPath,
    M6_1_2NetworkPathError,
    M6_1_2NetworkPathHop,
)

# --- Module constants -------------------------------------------------------

_TCPTRACEROUTE_FLAGS: tuple[str, ...] = ("-n", "-w", "2", "-q", "1", "-m", "18")
_PER_COHORT_TIMEOUT_S: float = 30.0
_PROBE_METHOD: str = "tcptraceroute"
_WHOIS_TIMEOUT_S: float = 5.0

# Mapping: M6.1.2 cohort name → key on the Modal handshake dict whose value
# is the cohort's endpoint URL. ``default_grpc`` and ``tuned_grpc_multiplexed``
# share the same gRPC endpoint (different client tuning, not different URL).
_COHORT_HANDSHAKE_KEY: dict[M6_1_2CohortKind, str] = {
    "rest_https_edge": "rest_https_edge_url",
    "rest_plain_tcp": "rest_plain_tcp_url",
    "default_grpc": "grpc",
    "tuned_grpc_multiplexed": "grpc",
}

# Spike #1 finding: the architectural CSP pattern. FR-006 fires when the
# observed cohort-level cloud_provider differs from this expectation.
_EXPECTED_COHORT_CSP: dict[M6_1_2CohortKind, M6_1_2CloudProvider] = {
    "rest_https_edge": "Microsoft Azure",
    "rest_plain_tcp": "AWS",
    "default_grpc": "AWS",
    "tuned_grpc_multiplexed": "AWS",
}

# CSP IP-range JSON sources (R-6 / network-paths.md "CSP attribution algorithm").
_AWS_RANGES_URL: str = "https://ip-ranges.amazonaws.com/ip-ranges.json"
_GCP_RANGES_URL: str = "https://www.gstatic.com/ipranges/cloud.json"
_AZURE_RANGES_URL_FALLBACK: str = "https://www.microsoft.com/en-us/download/details.aspx?id=56519"

_CACHE_DIR: Path = Path.home() / ".cache" / "vllm-grpc" / "ip-ranges"
_CACHE_TTL_SECONDS: float = 24 * 3600

# Regex for a tcptraceroute / traceroute hop line:
#   " 1  192.168.2.1  3.123 ms"      (success)
#   " 3  *"                          (filtered)
#   " 4  192.168.1.1 (host.name)  5.0 ms"  (some variants with reverse-DNS)
_HOP_REGEX: re.Pattern[str] = re.compile(
    r"^\s*(?P<hop>\d+)\s+"
    r"(?:(?P<ip>\d{1,3}(?:\.\d{1,3}){3}|[0-9a-fA-F:]+)"
    r"(?:\s+\([^)]*\))?"
    r"\s+(?P<rtt>\d+(?:\.\d+)?)\s*ms"
    r"|\*(?:\s+\*)*)"
)


# --- Helpers ----------------------------------------------------------------


def _stderr_ts() -> str:
    """ISO-8601 UTC bracket prefix ``[YYYY-MM-DDTHH:MM:SSZ]``.

    Mirrors ``m6_1_1_sweep.py``'s modern-import-shape helper per R-7.
    """
    return datetime.now(UTC).strftime("[%Y-%m-%dT%H:%M:%SZ]")


def _now_iso_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_url(url: str) -> tuple[str, int | None]:
    """Extract ``(host, port)`` from a URL.

    Supports ``tcp+plaintext://host:port``, ``http://host:port``,
    ``https://host[:port]``. Returns ``(host, None)`` if no port found.
    Mirrors the spike's ``_parse_url`` at ``traceroute_probe.py:50-67``.
    """
    if url.startswith("tcp+plaintext://"):
        rest = url[len("tcp+plaintext://") :]
    elif url.startswith("http://"):
        rest = url[len("http://") :]
    elif url.startswith("https://"):
        rest = url[len("https://") :]
        if ":" not in rest:
            return rest, 443
    else:
        rest = url
    # Strip path component if present.
    if "/" in rest:
        rest = rest.split("/", 1)[0]
    if ":" in rest:
        host, port_s = rest.rsplit(":", 1)
        return host, int(port_s)
    return rest, None


# --- Hop parser (T012 / FR-003) ---------------------------------------------


def parse_tcptraceroute_output(stdout: str) -> list[M6_1_2NetworkPathHop]:
    """Parse ``tcptraceroute`` stdout into an ordered list of hops.

    Format per Michael Toren's ``tcptraceroute(1)``:

    * Success line: `` <hop>  <ip>  <rtt> ms``
    * Filtered: `` <hop>  *`` (one or more asterisks)

    Reverse-DNS in parens is tolerated (`` <hop>  <ip> (name)  <rtt> ms``)
    although ``-n`` typically suppresses it.

    Returns hops in source order. ``cloud_provider`` is left as ``None`` —
    the caller (``run_topology_probe``) populates per-hop annotation.
    """
    hops: list[M6_1_2NetworkPathHop] = []
    for raw_line in stdout.splitlines():
        match = _HOP_REGEX.match(raw_line)
        if match is None:
            continue
        hop_number = int(match.group("hop"))
        ip = match.group("ip")
        rtt_raw = match.group("rtt")
        rtt_ms_or_null: float | None = float(rtt_raw) if rtt_raw is not None else None
        hops.append(
            M6_1_2NetworkPathHop(
                hop_number=hop_number,
                ip=ip,
                rtt_ms_or_null=rtt_ms_or_null,
                cloud_provider=None,
            )
        )
    return hops


# --- CSP IP-range fetch + attribution (T013 / FR-007 / R-6) -----------------


def _cache_path(provider: str) -> Path:
    return _CACHE_DIR / f"{provider}.json"


def _read_cached(provider: str, *, refresh: bool) -> dict[str, Any] | None:
    path = _cache_path(provider)
    if not path.exists():
        return None
    if refresh:
        return None
    age = time.time() - path.stat().st_mtime
    if age > _CACHE_TTL_SECONDS:
        return None
    try:
        parsed = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _write_cache(provider: str, payload: dict[str, Any]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(provider).write_text(json.dumps(payload))


def _fetch_url_json(url: str, *, timeout: float = 10.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (trusted CSP URLs)
            data = resp.read()
        parsed = json.loads(data)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _fetch_csp_ip_ranges(refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Return ``{"aws": ..., "azure": ..., "gcp": ...}`` (dicts may be empty).

    24h on-disk cache at :data:`_CACHE_DIR`. Network failures degrade to
    empty dicts so attribution falls through to the whois / unknown
    fallbacks rather than crashing the probe.
    """
    out: dict[str, dict[str, Any]] = {}
    aws = _read_cached("aws", refresh=refresh)
    if aws is None:
        fetched = _fetch_url_json(_AWS_RANGES_URL)
        if fetched is not None:
            aws = fetched
            _write_cache("aws", aws)
    out["aws"] = aws or {}

    gcp = _read_cached("gcp", refresh=refresh)
    if gcp is None:
        fetched = _fetch_url_json(_GCP_RANGES_URL)
        if fetched is not None:
            gcp = fetched
            _write_cache("gcp", gcp)
    out["gcp"] = gcp or {}

    # Azure's JSON is fronted by a download page; the actual file URL changes
    # weekly and requires scraping. Treat as best-effort.
    azure = _read_cached("azure", refresh=refresh)
    out["azure"] = azure or {}

    return out


def _ip_in_prefix(ip: str, prefix: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(prefix, strict=False)
    except (ValueError, TypeError):
        return False


def _attribute_aws(ip: str, aws: dict[str, Any]) -> tuple[M6_1_2CloudProvider, str | None] | None:
    for entry in aws.get("prefixes", []):
        prefix = entry.get("ip_prefix")
        if prefix and _ip_in_prefix(ip, prefix):
            return "AWS", entry.get("region")
    for entry in aws.get("ipv6_prefixes", []):
        prefix = entry.get("ipv6_prefix")
        if prefix and _ip_in_prefix(ip, prefix):
            return "AWS", entry.get("region")
    return None


def _attribute_azure(
    ip: str, azure: dict[str, Any]
) -> tuple[M6_1_2CloudProvider, str | None] | None:
    for value in azure.get("values", []):
        props = value.get("properties", {}) or {}
        region = props.get("region") or None
        for prefix in props.get("addressPrefixes", []) or []:
            if _ip_in_prefix(ip, prefix):
                return "Microsoft Azure", region
    return None


def _attribute_gcp(ip: str, gcp: dict[str, Any]) -> tuple[M6_1_2CloudProvider, str | None] | None:
    for entry in gcp.get("prefixes", []):
        prefix = entry.get("ipv4Prefix") or entry.get("ipv6Prefix")
        if prefix and _ip_in_prefix(ip, prefix):
            return "GCP", entry.get("scope")
    return None


def _whois_lookup(ip: str, timeout: float = _WHOIS_TIMEOUT_S) -> str | None:
    """Single-attempt ARIN whois query; no retry per round-3 Q1.

    Returns the OrgName line value when present, else None.
    """
    try:
        with socket.create_connection(("whois.arin.net", 43), timeout=timeout) as sock:
            sock.sendall(f"{ip}\r\n".encode())
            chunks: list[bytes] = []
            sock.settimeout(timeout)
            while True:
                try:
                    chunk = sock.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        text = b"".join(chunks).decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("OrgName:") or line.startswith("Organization:"):
            return line.split(":", 1)[1].strip() or None
    return None


_WHOIS_ORG_TO_CSP: dict[str, M6_1_2CloudProvider] = {
    "amazon": "AWS",
    "microsoft": "Microsoft Azure",
    "google": "GCP",
}


def attribute_cloud_provider(
    ip: str, *, ranges: dict[str, dict[str, Any]] | None = None
) -> tuple[M6_1_2CloudProvider, str | None]:
    """Resolve ``ip`` → cohort-level ``(cloud_provider, region)``.

    Algorithm (FR-007 + ``contracts/network-paths.md``):

    1. AWS IP-range hit → ``("AWS", region)``.
    2. Azure IP-range hit → ``("Microsoft Azure", region | None)``.
    3. GCP IP-range hit → ``("GCP", scope | None)``.
    4. ARIN whois fallback: org-name match → CSP enum; else ``("unknown", None)``.

    Per round-3 Q1: best-effort, no retry, no rate-limit handling.
    """
    if ranges is None:
        ranges = _fetch_csp_ip_ranges()

    hit = _attribute_aws(ip, ranges.get("aws", {}))
    if hit is not None:
        return hit
    hit = _attribute_azure(ip, ranges.get("azure", {}))
    if hit is not None:
        return hit
    hit = _attribute_gcp(ip, ranges.get("gcp", {}))
    if hit is not None:
        return hit

    org = _whois_lookup(ip)
    if org:
        org_lower = org.lower()
        for needle, csp in _WHOIS_ORG_TO_CSP.items():
            if needle in org_lower:
                return csp, None
    return "unknown", None


def _attribute_hop_provider(ip: str | None, ranges: dict[str, dict[str, Any]]) -> str | None:
    """Best-effort per-hop annotation. Returns the cohort-level enum string,
    or a transit-ASN OrgName (e.g. ``"Telia"``) when whois resolves but no
    CSP match, or ``None``."""
    if ip is None:
        return None
    csp, _region = attribute_cloud_provider(ip, ranges=ranges)
    if csp != "unknown":
        return csp
    org = _whois_lookup(ip)
    if org:
        return org
    return None


# --- Per-cohort probe (T014 / FR-002a / FR-005) -----------------------------


def _probe_one_cohort(
    host: str,
    port: int,
    *,
    timeout: float = _PER_COHORT_TIMEOUT_S,
    ranges: dict[str, dict[str, Any]] | None = None,
) -> M6_1_2NetworkPath | M6_1_2NetworkPathError:
    """Run ``tcptraceroute`` against one ``(host, port)`` and parse.

    Thread-safe blocking subprocess invocation suitable for
    ``asyncio.to_thread``. Per FR-002a: 30s wall-clock timeout maps to
    ``subprocess.TimeoutExpired`` → ``error: "probe_timeout"``.
    """
    probed_at = _now_iso_utc()
    cmd = ["tcptraceroute", *_TCPTRACEROUTE_FLAGS, host, str(port)]
    try:
        proc = subprocess.run(  # noqa: S603 (validated host/port from handshake dict)
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return M6_1_2NetworkPathError(
            error="probe_timeout",
            probe_method="tcptraceroute",
            probed_at_utc=probed_at,
            detail=(f"tcptraceroute exceeded {timeout}s wall-clock for {host}:{port}"),
        )
    except FileNotFoundError:
        return M6_1_2NetworkPathError(
            error="tcptraceroute_unavailable",
            probe_method="tcptraceroute",
            probed_at_utc=probed_at,
            detail="tcptraceroute binary not found on PATH",
        )
    except OSError as exc:
        return M6_1_2NetworkPathError(
            error="subprocess_error",
            probe_method="tcptraceroute",
            probed_at_utc=probed_at,
            detail=f"{type(exc).__name__}: {exc}",
        )

    if proc.returncode != 0 and not proc.stdout.strip():
        stderr_line = proc.stderr.strip().splitlines()[0] if proc.stderr.strip() else None
        return M6_1_2NetworkPathError(
            error="subprocess_error",
            probe_method="tcptraceroute",
            probed_at_utc=probed_at,
            detail=stderr_line,
        )

    hops = parse_tcptraceroute_output(proc.stdout)

    if ranges is None:
        ranges = _fetch_csp_ip_ranges()

    annotated_hops = [
        M6_1_2NetworkPathHop(
            hop_number=h.hop_number,
            ip=h.ip,
            rtt_ms_or_null=h.rtt_ms_or_null,
            cloud_provider=_attribute_hop_provider(h.ip, ranges),
        )
        for h in hops
    ]

    endpoint_ip = _resolve_endpoint_ip(host, hops)
    cohort_csp, region = (
        attribute_cloud_provider(endpoint_ip, ranges=ranges) if endpoint_ip else ("unknown", None)
    )

    return M6_1_2NetworkPath(
        endpoint_ip=endpoint_ip or "",
        hops=annotated_hops,
        cloud_provider=cohort_csp,
        region=region,
        probe_method="tcptraceroute",
        probed_at_utc=probed_at,
    )


def _resolve_endpoint_ip(host: str, hops: list[M6_1_2NetworkPathHop]) -> str | None:
    """Resolve the cohort endpoint IP, preferring the last hop with an IP."""
    try:
        return socket.gethostbyname(host)
    except OSError:
        for hop in reversed(hops):
            if hop.ip is not None:
                return hop.ip
        return None


# --- Orchestration (T014 / FR-001a) -----------------------------------------


async def run_topology_probe(
    handshake_dict: dict[str, object],
    cohorts: tuple[M6_1_2CohortKind, ...] = M6_1_2_COHORTS,
    per_cohort_timeout_seconds: float = _PER_COHORT_TIMEOUT_S,
    *,
    ranges: dict[str, dict[str, Any]] | None = None,
) -> dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError]:
    """Probe each cohort's endpoint in parallel; return per-cohort results.

    Per FR-001 + FR-001a + FR-002a:
    - Runs once per sweep (caller's responsibility).
    - Cohorts probed in parallel via ``asyncio.gather`` + ``asyncio.to_thread``.
    - 30s per-cohort wall-clock timeout.
    - Probe failure NEVER aborts: per-cohort errors recorded as
      ``M6_1_2NetworkPathError`` entries; warning emission per FR-005a / FR-006
      is the caller's responsibility (see :func:`emit_probe_warnings`).
    """
    if ranges is None:
        ranges = _fetch_csp_ip_ranges()

    # Resolve (cohort, host, port) tuples from the handshake dict.
    targets: list[tuple[M6_1_2CohortKind, str, int]] = []
    skipped: dict[M6_1_2CohortKind, M6_1_2NetworkPathError] = {}
    for cohort in cohorts:
        url = handshake_dict.get(_COHORT_HANDSHAKE_KEY[cohort])
        if not url or not isinstance(url, str):
            skipped[cohort] = M6_1_2NetworkPathError(
                error="subprocess_error",
                probe_method="tcptraceroute",
                probed_at_utc=_now_iso_utc(),
                detail=(
                    f"handshake dict missing key "
                    f"{_COHORT_HANDSHAKE_KEY[cohort]!r} for cohort {cohort!r}"
                ),
            )
            continue
        host, port = _parse_url(url)
        if port is None:
            skipped[cohort] = M6_1_2NetworkPathError(
                error="parse_error",
                probe_method="tcptraceroute",
                probed_at_utc=_now_iso_utc(),
                detail=f"could not parse port from URL {url!r} for cohort {cohort!r}",
            )
            continue
        targets.append((cohort, host, port))

    async def _run(
        cohort: M6_1_2CohortKind, host: str, port: int
    ) -> tuple[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError]:
        result = await asyncio.to_thread(
            _probe_one_cohort,
            host,
            port,
            timeout=per_cohort_timeout_seconds,
            ranges=ranges,
        )
        return cohort, result

    gathered = await asyncio.gather(*(_run(c, h, p) for (c, h, p) in targets))
    results: dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError] = dict(gathered)
    results.update(skipped)
    return results


# --- Warning emitters (T015 / FR-005a / FR-006) -----------------------------


def emit_probe_warnings(
    results: dict[M6_1_2CohortKind, M6_1_2NetworkPath | M6_1_2NetworkPathError],
) -> None:
    """Emit FR-005a (all-failed) and FR-006 (CSP-mismatch) warnings to stderr.

    All warning lines carry the ``_stderr_ts()`` prefix per FR-020.
    """
    if not results:
        return

    errors = {c: r for c, r in results.items() if isinstance(r, M6_1_2NetworkPathError)}
    if len(errors) == len(results):
        reason_summary = "/".join(
            f"{len(errors)}/{len(results)}: " + ",".join(sorted({r.error for r in errors.values()}))
            for _ in [0]
        )
        print(
            f"{_stderr_ts()} WARNING: every cohort probe failed ({reason_summary}); "
            "`network_paths` block contains error records only — topology evidence "
            "is unavailable for this sweep",
            file=sys.stderr,
            flush=True,
        )

    for cohort, result in results.items():
        if not isinstance(result, M6_1_2NetworkPath):
            continue
        expected = _EXPECTED_COHORT_CSP.get(cohort)
        if expected is None:
            continue
        if result.cloud_provider == expected:
            continue
        print(
            f"{_stderr_ts()} WARNING: cohort {cohort} entered {result.cloud_provider} "
            f"rather than expected {expected}; topology has changed",
            file=sys.stderr,
            flush=True,
        )


__all__ = [
    "attribute_cloud_provider",
    "emit_probe_warnings",
    "parse_tcptraceroute_output",
    "run_topology_probe",
]
