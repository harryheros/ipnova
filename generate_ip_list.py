#!/usr/bin/env python3
"""
Project : ipnova
Repo    : https://github.com/harryheros/ipnova
Desc    : High-quality IPv4 CIDR list generator for Asia-Pacific regions (CN / HK / TW / MO / JP / KR / SG)
Source  : APNIC RIR delegation data + BGP multi-source fusion (upstream, not derived)
"""

import urllib.request
import urllib.parse
import urllib.error
import ipaddress
import hashlib
import os
import sys
import tempfile
import time
import argparse
import datetime
import json
import logging
from collections import defaultdict
from bisect import bisect_left, bisect_right

# Ensure the script's own directory is on sys.path so `import regions` works
# regardless of the cwd from which generate_ip_list.py was invoked.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# ================================================================
# Version
# ================================================================
__version__ = "3.5.0"

# Data-layer schema version (data.json / meta.json / regions.json).
SCHEMA_VERSION = "3.4"

# HTTP User-Agent — single source: __version__ above, plus repo URL so
# upstream operators (RIPE Stat, APNIC) can contact the maintainer if
# our traffic ever misbehaves. Derived once at module load to avoid the
# previous bug where the UA string was hardcoded to "ipnova-bot/3.2"
# and silently drifted from __version__.
USER_AGENT = f"ipnova/{__version__} (+https://github.com/harryheros/ipnova)"

# ================================================================
# Logging
# ================================================================
log = logging.getLogger("ipnova")


def setup_logging(verbose=False):
    """Configure structured logging with level control."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "[%(levelname)s] %(message)s"
    logging.basicConfig(level=level, format=fmt, stream=sys.stdout)


# ================================================================
# Step timer — logs elapsed time for each pipeline stage
# ================================================================
class StepTimer:
    """Context manager that logs elapsed time for a named step."""

    def __init__(self, name):
        self.name = name
        self.start = None
        self.elapsed = 0.0

    def __enter__(self):
        self.start = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.monotonic() - self.start
        log.info("[timer] %s completed in %.1fs", self.name, self.elapsed)
        return False


# ================================================================
# ASN Blacklist: Exclude global Anycast / CDN / Cloud providers
# ================================================================
EXCLUDED_ASNS = {
    # Cloudflare
    13335, 209242,
    # Google
    15169, 396982,
    # Akamai
    20940, 16625,
    # Fastly
    54113,
    # AWS
    16509, 14618,
    # Microsoft / Azure
    8075, 8069,
    # Meta
    32934,
    # Twitter / X
    13414,
}

# Human-readable labels for reporting
ASN_LABELS = {
    13335: "Cloudflare", 209242: "Cloudflare",
    15169: "Google", 396982: "Google",
    20940: "Akamai", 16625: "Akamai",
    54113: "Fastly",
    16509: "AWS", 14618: "AWS",
    8075: "Microsoft", 8069: "Microsoft",
    32934: "Meta",
    13414: "X/Twitter",
}

# ================================================================
# CIDR Blacklist: Known Anycast prefixes (static fallback)
# ================================================================
ANYCAST_BLACKLIST = [
    "1.0.0.0/24",       # Cloudflare DNS
    "1.1.1.0/24",       # Cloudflare DNS
    "8.8.8.0/24",       # Google DNS
    "8.8.4.0/24",       # Google DNS
    "9.9.9.0/24",       # Quad9
    "208.67.222.0/24",  # OpenDNS
    "208.67.220.0/24",  # OpenDNS
]

# ================================================================
# Target regions
# ================================================================
# Single source of truth lives in regions.py. Re-exported here so existing
# `from generate_ip_list import TARGET_REGIONS` consumers keep working.
from regions import TARGET_REGIONS  # noqa: E402  (intentional position)

# ================================================================
# Sanity thresholds: minimum expected CIDR counts per region
# If output falls below these, something is very wrong upstream
# ================================================================
SANITY_THRESHOLDS = {
    "CN": 3000,
    "HK": 1000,
    "TW": 300,
    "MO": 10,
    "JP": 2500,  # was 3000; actual ~3183 but 6% margin was too tight for RIPE Stat flakiness
    "KR": 800,
    "SG": 300,
}

APNIC_URL = "https://ftp.apnic.net/stats/apnic/delegated-apnic-latest"
RIPE_STAT_URL = "https://stat.ripe.net/data/announced-prefixes/data.json"

# Retry / rate-limit constants
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2   # seconds, exponential: 2, 4, 8
RIPE_REQUEST_INTERVAL = 1.5  # seconds between RIPE Stat requests

# Per-host throttling: RIPE Stat has no documented per-IP rate limit but
# burst traffic risks 429/503. http_get enforces RIPE_REQUEST_INTERVAL
# between any two RIPE requests automatically, regardless of caller, so
# callers don't need to remember to sleep.
_RIPE_HOSTS = ("stat.ripe.net",)
_RIPE_LAST_CALL = 0.0  # monotonic timestamp of last RIPE request

# ── RIPE Stat circuit breaker ───────────────────────────────────────────────
# The existing throttle above limits *rate* (one request per interval) but not
# *total duration / total volume*. During a wide RIPE Stat outage, every one of
# hundreds of ASN/prefix queries fails and retries, and the throttle politely
# spaces them out — producing a 50+ minute run that hammers RIPE Stat the whole
# time. That sustained-volume pattern is what trips GitHub's abuse detection.
#
# The breaker adds the missing "stop" gate: once RIPE Stat has failed too many
# times in a row, OR the cumulative RIPE phase has run too long, all further
# RIPE requests fail fast (no network call, no retry, no sleep). The build then
# degrades gracefully (uses cache / proceeds APNIC-only) instead of grinding on.
# It only governs RIPE hosts; APNIC and other one-shot downloads are untouched.
RIPE_BREAKER_MAX_CONSECUTIVE_FAILURES = 15   # trip after this many in a row
# Hard wall-clock cap on the RIPE phase. v3.4 used 600s, but a cold-cache
# cloud-supplement run alone measured ~560s (meta.json 2026-07-01), leaving
# almost no headroom: the breaker would trip part-way through and silently
# drop the remaining cloud prefixes. Overridable via --ripe-budget.
RIPE_BREAKER_MAX_PHASE_SECONDS = 900

_RIPE_BREAKER_TRIPPED = False
_RIPE_CONSECUTIVE_FAILURES = 0
_RIPE_PHASE_START = 0.0  # monotonic; set on first RIPE request


class RipeBreakerOpen(Exception):
    """Raised when the RIPE Stat circuit breaker is open (fail fast, no network)."""


def _ripe_breaker_check():
    """Return True (and trip) if the breaker should be open for RIPE requests.

    Trips on either condition:
      - too many consecutive RIPE failures, or
      - the RIPE phase has exceeded its wall-clock cap.
    Once tripped it stays tripped for the rest of the run.
    """
    global _RIPE_BREAKER_TRIPPED
    if _RIPE_BREAKER_TRIPPED:
        return True
    if _RIPE_CONSECUTIVE_FAILURES >= RIPE_BREAKER_MAX_CONSECUTIVE_FAILURES:
        _RIPE_BREAKER_TRIPPED = True
        log.error(
            "RIPE Stat circuit breaker TRIPPED: %d consecutive failures. "
            "Failing all further RIPE requests fast; build will degrade "
            "gracefully (cache / APNIC-only) instead of hammering RIPE.",
            _RIPE_CONSECUTIVE_FAILURES,
        )
        return True
    if _RIPE_PHASE_START and (
        time.monotonic() - _RIPE_PHASE_START > RIPE_BREAKER_MAX_PHASE_SECONDS
    ):
        _RIPE_BREAKER_TRIPPED = True
        log.error(
            "RIPE Stat circuit breaker TRIPPED: RIPE phase exceeded %ds cap. "
            "Failing all further RIPE requests fast.",
            RIPE_BREAKER_MAX_PHASE_SECONDS,
        )
        return True
    return False


# ================================================================
# HTTP helpers with retry
# ================================================================
def _is_ripe_host(url):
    """Return True iff the URL's hostname is a RIPE Stat host.

    Uses urlparse rather than substring matching so that pathological URLs
    (e.g. https://evil.com/?ref=stat.ripe.net) cannot bypass intent or
    falsely trigger throttling. Supports exact match and subdomain match
    against any entry in _RIPE_HOSTS.
    """
    try:
        host = urllib.parse.urlparse(url).hostname
    except (ValueError, AttributeError):
        return False
    if not host:
        return False
    host = host.lower()
    for ripe in _RIPE_HOSTS:
        if host == ripe or host.endswith("." + ripe):
            return True
    return False


def _retry_after_seconds(err, cap=60):
    """Return a bounded Retry-After delay (seconds) from a 429/503 error."""
    if not isinstance(err, urllib.error.HTTPError) or err.code not in (429, 503):
        return None
    try:
        value = err.headers.get("Retry-After") if err.headers else None
        if value is None:
            return None
        return max(0, min(int(value), cap))
    except (TypeError, ValueError):
        return None


def http_get(url, timeout=30, retries=MAX_RETRIES, ua=None,
             strict_decode=False, return_content_type=False):
    """
    Fetch URL with exponential backoff retry.

    Args:
        ua: Optional User-Agent override; defaults to USER_AGENT (module
            constant derived from __version__).
        strict_decode: If True, raise on non-UTF-8 bytes (use for APNIC).
                       If False, use errors='replace' (use for RIPE/error pages).
        return_content_type: If True, return (body, content_type) tuple.

    Returns response body as str, or raises on total failure.

    RIPE Stat throttling: any URL whose hostname matches a RIPE Stat host
    is automatically throttled to at most one request per
    RIPE_REQUEST_INTERVAL seconds, regardless of which caller initiated it.
    """
    global _RIPE_LAST_CALL
    global _RIPE_CONSECUTIVE_FAILURES, _RIPE_PHASE_START
    headers = {"User-Agent": ua or USER_AGENT}
    decode_errors = "strict" if strict_decode else "replace"
    last_err = None
    is_ripe = _is_ripe_host(url)

    # Circuit breaker: once tripped, RIPE requests fail fast with no network
    # call, no retry, no sleep — this is the gate that stops a wide RIPE outage
    # from turning into a 50-minute hammering run. Non-RIPE URLs are unaffected.
    if is_ripe:
        if _RIPE_PHASE_START == 0.0:
            _RIPE_PHASE_START = time.monotonic()
        if _ripe_breaker_check():
            raise RipeBreakerOpen(f"RIPE breaker open; skipped {url[:80]}")

    for attempt in range(1, retries + 1):
        try:
            if is_ripe:
                gap = RIPE_REQUEST_INTERVAL - (time.monotonic() - _RIPE_LAST_CALL)
                if gap > 0:
                    time.sleep(gap)
                _RIPE_LAST_CALL = time.monotonic()

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                body = raw.decode("utf-8", errors=decode_errors)
                if is_ripe:
                    _RIPE_CONSECUTIVE_FAILURES = 0  # success resets the streak
                if return_content_type:
                    content_type = resp.headers.get("Content-Type", "")
                    return body, content_type
                return body
        except Exception as e:
            last_err = e
            # Permanent client errors (400/401/403/404/410/...) will not heal
            # on retry; retrying only adds load on the upstream and delay to
            # the build. 408 (timeout) and 429 (rate limited) are transient.
            if (isinstance(e, urllib.error.HTTPError)
                    and 400 <= e.code < 500 and e.code not in (408, 429)):
                log.error("HTTP %d (not retryable) for %s", e.code, url[:80])
                break
            if attempt < retries:
                wait = RETRY_BACKOFF_BASE ** attempt
                retry_after = _retry_after_seconds(e)
                if retry_after is not None:
                    wait = max(wait, retry_after)
                log.warning("HTTP attempt %d/%d failed for %s: %s (retry in %ds)",
                            attempt, retries, url[:80], e, wait)
                time.sleep(wait)
            else:
                log.error("HTTP failed after %d attempts for %s: %s",
                          retries, url[:80], e)

    # All retries exhausted. If this was a RIPE request, count it toward the
    # breaker so a sustained outage trips the gate and later calls fail fast.
    if is_ripe:
        _RIPE_CONSECUTIVE_FAILURES += 1
        _ripe_breaker_check()
    raise last_err


# ================================================================
# Data acquisition
# ================================================================
def download_apnic_data():
    """Download the latest APNIC delegation file with retry and validation."""
    log.info("Fetching APNIC delegation data from %s", APNIC_URL)
    data = http_get(APNIC_URL, timeout=60, strict_decode=True)
    lines = data.splitlines()
    line_count = len(lines)
    log.info("Downloaded %d lines from APNIC", line_count)

    # Size sanity
    if line_count < 1000:
        raise RuntimeError(
            f"APNIC data suspiciously small ({line_count} lines). "
            "Upstream may be broken. Aborting."
        )

    # Format validation: APNIC files may start with comment lines (######...)
    # The real version header looks like "2|apnic|20260328|..." or "2.3|apnic|..."
    # Find the first non-empty, non-comment line and verify it contains "apnic"
    header = ""
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            header = stripped
            break

    if not header or "apnic" not in header.lower():
        preview = header[:120] if header else "(empty)"
        raise RuntimeError(
            f"APNIC data format unexpected. First data line: {preview!r}. "
            "This may be an error page or corrupted download."
        )

    log.debug("APNIC header: %s", header[:80])
    return data


def fetch_asn_prefixes(asn):
    """
    Fetch announced IPv4 prefixes for a single ASN from RIPE Stat.
    Returns list of IPv4Network objects.
    """
    url = f"{RIPE_STAT_URL}?resource=AS{asn}"
    body, content_type = http_get(url, timeout=20, return_content_type=True)

    # Validate content type (RIPE sometimes returns HTML error pages)
    if "json" not in content_type.lower():
        preview = body[:200].replace("\n", " ").strip()
        raise RuntimeError(
            f"Unexpected RIPE content type for AS{asn}: {content_type!r}; "
            f"body preview={preview!r}"
        )

    # Parse JSON with clear error reporting
    try:
        payload = json.loads(body.strip())
    except json.JSONDecodeError as e:
        preview = body[:200].replace("\n", " ").strip()
        raise RuntimeError(
            f"RIPE API returned non-JSON for AS{asn}: {e}; "
            f"body preview={preview!r}"
        )

    # Structural validation
    if not isinstance(payload, dict):
        raise RuntimeError(f"Malformed RIPE response for AS{asn}: root is not object")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"Malformed RIPE response for AS{asn}: missing data object")

    prefixes = data.get("prefixes", [])
    if not isinstance(prefixes, list):
        raise RuntimeError(f"Malformed RIPE response for AS{asn}: prefixes is not list")

    # Extract IPv4 networks
    networks = []
    for p in prefixes:
        if not isinstance(p, dict):
            continue
        raw = p.get("prefix", "")
        try:
            net = ipaddress.ip_network(raw, strict=False)
            if net.version == 4:
                networks.append(net)
        except ValueError:
            continue

    return networks


def build_excluded_networks(skip_ripe=False):
    """
    Build the full exclusion set:
    1. Dynamic: fetch announced prefixes per blacklisted ASN (RIPE Stat)
    2. Static:  merge ANYCAST_BLACKLIST as fallback

    Returns (excluded_networks, report) where report tracks successes/failures.
    """
    excluded = []
    report = {
        "succeeded": [],
        "failed": [],
        "total_prefixes": 0,
        "mode": "static_only" if skip_ripe else "dynamic+static",
    }

    if skip_ripe:
        log.info("Skipping RIPE Stat queries (--skip-ripe)")
    else:
        log.info("Fetching prefixes for %d blacklisted ASNs...", len(EXCLUDED_ASNS))
        sorted_asns = sorted(EXCLUDED_ASNS)

        for asn in sorted_asns:
            label = ASN_LABELS.get(asn, "Unknown")
            try:
                nets = fetch_asn_prefixes(asn)
                excluded.extend(nets)
                report["succeeded"].append(asn)
                report["total_prefixes"] += len(nets)
                log.info("  AS%-6d %-12s %d IPv4 prefixes", asn, label, len(nets))
            except Exception as e:
                report["failed"].append(asn)
                log.warning("  AS%-6d %-12s FAILED: %s", asn, label, e)

            # Note: per-host throttling is now enforced inside http_get for
            # any RIPE Stat URL, so this loop no longer needs an explicit
            # time.sleep(). Kept the iteration order stable for log clarity.

    # Evaluate failure rate
    total_asns = len(EXCLUDED_ASNS)
    failed_count = len(report["failed"])

    if not skip_ripe and failed_count > 0:
        fail_pct = failed_count / total_asns * 100
        if fail_pct > 50:
            raise RuntimeError(
                f"RIPE Stat query failure rate too high: {failed_count}/{total_asns} "
                f"({fail_pct:.0f}%). Exclusion list unreliable. Aborting."
            )
        log.warning("RIPE Stat: %d/%d ASN queries failed (%.0f%%). "
                    "Static blacklist will partially compensate.",
                    failed_count, total_asns, fail_pct)

    # Sort for stable output (ensures consistent meta.json diffs)
    report["succeeded"] = sorted(report["succeeded"])
    report["failed"] = sorted(report["failed"])

    # Static blacklist (always applied)
    static_count = 0
    for cidr in ANYCAST_BLACKLIST:
        try:
            excluded.append(ipaddress.ip_network(cidr, strict=False))
            static_count += 1
        except ValueError:
            log.warning("Invalid static blacklist entry: %s", cidr)

    log.info("Exclusion set ready: %d dynamic + %d static = %d total networks",
             report["total_prefixes"], static_count, len(excluded))

    return excluded, report


# ================================================================
# Parsing helpers
# ================================================================
class SortedNetworks:
    """Collapsed, address-sorted IPv4 networks with O(log n) range lookup.

    Collapsing guarantees the member networks are pairwise disjoint, which
    makes both their start and end addresses monotonically increasing. The
    set of members overlapping any query range is therefore one contiguous
    slice, found with two binary searches.

    v3.4 used a linear scan from the beginning of the list for every query,
    which made enforce_mutual_exclusivity() O(N x M) (~10s on the published
    dataset, far more on raw APNIC input). This index removes that cost
    without changing results.
    """

    __slots__ = ("nets", "starts", "ends")

    def __init__(self, networks=()):
        v4 = [n for n in networks if n.version == 4]
        self.nets = sorted(ipaddress.collapse_addresses(v4),
                           key=lambda n: int(n.network_address)) if v4 else []
        self.starts = [int(n.network_address) for n in self.nets]
        self.ends = [int(n.broadcast_address) for n in self.nets]

    def __len__(self):
        return len(self.nets)

    def __bool__(self):
        return bool(self.nets)

    def overlapping(self, network):
        """Return members that overlap `network` (in address order)."""
        lo = bisect_left(self.ends, int(network.network_address))
        hi = bisect_right(self.starts, int(network.broadcast_address))
        return self.nets[lo:hi] if lo < hi else []

    def containing(self, network):
        """Return the member that fully contains `network`, or None."""
        hits = self.overlapping(network)
        if len(hits) == 1 and network.subnet_of(hits[0]):
            return hits[0]
        return None


def _as_sorted_networks(excluded):
    if isinstance(excluded, SortedNetworks):
        return excluded
    return SortedNetworks(excluded or [])


def _find_relevant_excluded(network, excluded_sorted):
    """Return only the excluded networks whose range overlaps `network`.

    Accepts a SortedNetworks index (fast path) or any iterable of networks
    (converted on the fly; kept for backward compatibility).
    """
    return _as_sorted_networks(excluded_sorted).overlapping(network)


def subtract_excluded_from_network(network, excluded_sorted):
    """
    Precisely subtract excluded subnets from a source network.

    - Do NOT drop the entire network merely because it overlaps
      with an excluded subnet.
    - Cut out only the excluded portions and keep the remainder.
    - `excluded_sorted` may be a SortedNetworks index (preferred for
      repeated calls) or a plain list of networks.

    Returns:
        list[IPv4Network]
    """
    # Pre-filter: only check excluded nets that could possibly overlap
    relevant = _find_relevant_excluded(network, excluded_sorted)
    if not relevant:
        return [network]

    remaining = [network]

    for ex in relevant:
        new_remaining = []

        for current in remaining:
            if not current.overlaps(ex):
                new_remaining.append(current)
                continue

            # current fully covered by excluded network -> drop entirely
            if current.subnet_of(ex):
                continue

            # excluded network is a subnet of current -> subtract precisely
            if ex.subnet_of(current):
                try:
                    new_remaining.extend(current.address_exclude(ex))
                except ValueError:
                    new_remaining.append(current)
                continue

            # In standard CIDR, overlapping blocks always have a subnet
            # relationship, so this branch should not trigger. Keep the
            # network intact as a safety measure.
            new_remaining.append(current)

        remaining = new_remaining
        if not remaining:
            break

    return remaining


# ================================================================
# Parsing & filtering
# ================================================================
# ============================================================
# Cloud / Internet Company ASNs for ARIN-gap supplementation
# ============================================================
CN_CLOUD_ASNS_TIER1 = {
    37963: "Aliyun Computing",
    45102: "Alibaba US Technology",
    132203: "Tencent Cloud International",
    136907: "Huawei Clouds International",
}

CN_CLOUD_ASNS_TIER2 = {
    45090: "Tencent",
    38365: "Baidu",
    58593: "ByteDance",
}

CN_CLOUD_ASNS = {**CN_CLOUD_ASNS_TIER1, **CN_CLOUD_ASNS_TIER2}

# Lookup table: ASN -> tier integer (1 or 2), used for cidr_objects provenance
_ASN_TIER_MAP: dict[int, int] = {
    **{asn: 1 for asn in CN_CLOUD_ASNS_TIER1},
    **{asn: 2 for asn in CN_CLOUD_ASNS_TIER2},
}

# ============================================================
# FORBIDDEN: Operator backbone ASNs - must NEVER be in CN_CLOUD_ASNS
# Purpose: prevent accidentally adding ISP backbones which would
# pollute CN.txt with consumer broadband / IDC access networks
# ============================================================
FORBIDDEN_ASNS = {
    58466: "China Telecom",
    4134:  "China Telecom Backbone",
    4837:  "China Unicom Backbone",
    9808:  "China Mobile",
    4538:  "CERNET",
    17621: "China Unicom Shanghai",
    9394:  "China Railway Telecom",
}

# Module-load sanity check
_overlap = set(CN_CLOUD_ASNS.keys()) & set(FORBIDDEN_ASNS.keys())
if _overlap:
    raise RuntimeError(
        f"Forbidden ASN(s) found in CN_CLOUD_ASNS: {_overlap}. "
        f"Operator backbone ASNs must never be used as cloud sources."
    )


_ASN_COUNTRY_CACHE = {}

def fetch_asn_country(asn):
    """Return ISO country code for ASN holder, cached. None on failure."""
    if asn in _ASN_COUNTRY_CACHE:
        return _ASN_COUNTRY_CACHE[asn]

    cc = None

    try:
        url = f"https://stat.ripe.net/data/as-overview/data.json?resource=AS{asn}"
        body, _ct = http_get(url, timeout=8, retries=2, return_content_type=True)
        payload = json.loads(body.strip())

        holder_cc = (payload.get("data", {}) or {}).get("holder", "")
        if isinstance(holder_cc, str) and " - " in holder_cc:
            tail = holder_cc.rsplit(" - ", 1)[-1].strip()
            if len(tail) == 2 and tail.isalpha():
                cc = tail.upper()

        if not cc:
            url2 = f"https://stat.ripe.net/data/rir-stats-country/data.json?resource=AS{asn}"
            body2, _ = http_get(url2, timeout=8, retries=2, return_content_type=True)
            p2 = json.loads(body2.strip())
            located = (p2.get("data", {}) or {}).get("located_resources") or []
            if located:
                cc = (located[0].get("location") or "").upper() or None

    except Exception:
        cc = None

    _ASN_COUNTRY_CACHE[asn] = cc
    return cc


_GEOLOC_CACHE_PATH = os.path.join("output", ".geoloc_cache.json")
# 10 days. v3.4 used exactly 168h (7 days) with a weekly cron, so entries
# written during last Monday's run were typically a few minutes *past* the
# TTL by the next Monday's run and got discarded (meta.json showed 1 cache
# hit out of 1,866 prefixes). The TTL must comfortably exceed the cron period.
_GEOLOC_CACHE_TTL_HOURS = 240
_GEOLOC_CACHE_RULE_VERSION = "2026-04-13-l1-located-resources-pct-vote"
_GEOLOC_CACHE = None  # lazy-loaded dict {prefix: {"cc": str, "level": str, "ts": iso}}


def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _load_geoloc_cache():
    global _GEOLOC_CACHE
    if _GEOLOC_CACHE is not None:
        return _GEOLOC_CACHE
    _GEOLOC_CACHE = {}
    if not os.path.exists(_GEOLOC_CACHE_PATH):
        return _GEOLOC_CACHE
    try:
        with open(_GEOLOC_CACHE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        entries = payload.get("entries") or {}
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=_GEOLOC_CACHE_TTL_HOURS)
        for prefix, rec in entries.items():
            try:
                if rec.get("rule_version") != _GEOLOC_CACHE_RULE_VERSION:
                    continue
                ts = datetime.datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
                if ts >= cutoff:
                    _GEOLOC_CACHE[prefix] = rec
            except Exception:
                pass
        log.info("[cloud-supp] loaded %d valid geoloc cache entries", len(_GEOLOC_CACHE))
    except Exception as e:
        log.warning("[cloud-supp] geoloc cache load failed: %s", e)
    return _GEOLOC_CACHE


def set_geoloc_cache_path(output_dir):
    """Bind persistent geolocation cache to the selected output directory."""
    global _GEOLOC_CACHE_PATH
    _GEOLOC_CACHE_PATH = os.path.join(output_dir, ".geoloc_cache.json")


def _save_geoloc_cache():
    if _GEOLOC_CACHE is None:
        return
    try:
        os.makedirs(os.path.dirname(_GEOLOC_CACHE_PATH) or ".", exist_ok=True)
        payload = {
            "version": 2,
            "rule_version": _GEOLOC_CACHE_RULE_VERSION,
            "ttl_hours": _GEOLOC_CACHE_TTL_HOURS,
            "generated_at": _utc_now_iso(),
            "entries": _GEOLOC_CACHE,
        }
        _atomic_write_text(
            _GEOLOC_CACHE_PATH,
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        )
        log.info("[cloud-supp] saved %d geoloc cache entries", len(_GEOLOC_CACHE))
    except Exception as e:
        log.warning("[cloud-supp] geoloc cache save failed: %s", e)


def build_region_index(region_data):
    """Return {cc: SortedNetworks} for fast containment / overlap queries."""
    index = {}
    for cc, nets in (region_data or {}).items():
        index[cc] = nets if isinstance(nets, SortedNetworks) else SortedNetworks(nets)
    return index


def _region_index(region_data):
    if not region_data:
        return {}
    if all(isinstance(v, SortedNetworks) for v in region_data.values()):
        return region_data
    return build_region_index(region_data)


def _cache_put(cache, prefix, cc, level):
    cache[prefix] = {
        "cc": cc,
        "level": level,
        "ts": _utc_now_iso(),
        "rule_version": _GEOLOC_CACHE_RULE_VERSION,
    }


def fetch_prefix_country(prefix, asn, region_data=None):
    """
    Multi-level lookup for a prefix's country code.

    L0: in-memory APNIC region containment (no HTTP, authoritative for
        this build). Checked FIRST so a fresh APNIC delegation always
        beats a cached answer from a previous week. Not cached.
    L-1 (cache): persistent geoloc cache of earlier L1/L2 answers.
    L1: RIPEstat geoloc (majority of covered_percentage).
    L2: ASN holder country (weak signal).
    L3: None.

    `region_data` may be dict[cc, list[network]] or the prebuilt index
    from build_region_index() (much faster for repeated calls).

    Returns (cc_or_None, level_str, from_cache).

    `level_str` is always the level of the *original* evidence (L0/L1/L2/L3).
    v3.4 returned the pseudo-level "L-1" for cache hits, which mapped to
    confidence "high" — so a weak L2 guess got silently promoted to "high"
    confidence on every run after the first. The cache hit is now reported
    separately via `from_cache`.
    """
    index = _region_index(region_data)
    if index:
        try:
            target = ipaddress.ip_network(prefix, strict=False)
            if target.version == 4:
                for rcc, idx in index.items():
                    if idx.containing(target) is not None:
                        return rcc, "L0", False
        except ValueError:
            pass

    cache = _load_geoloc_cache()
    rec = cache.get(prefix)
    # Only network-derived answers are served from cache. Legacy "L0" entries
    # (written by v3.4) depend on that week's APNIC data, so they are ignored
    # and re-derived instead of being trusted blindly.
    if rec and rec.get("cc") and rec.get("level") in ("L1", "L2"):
        return rec["cc"], rec["level"], True

    try:
        url = f"https://stat.ripe.net/data/geoloc/data.json?resource={prefix}"
        body, _ = http_get(url, timeout=10, retries=1, return_content_type=True)
        payload = json.loads(body.strip())
        data = payload.get("data") or {}
        # Current RIPE Stat API (v0.9.7+) wraps locations under located_resources.
        # Several located_resources may be returned (one per more-specific);
        # aggregate across all of them rather than only the first.
        located = data.get("located_resources") or []
        locs = []
        if located:
            for res in located:
                if isinstance(res, dict):
                    locs.extend(res.get("locations") or [])
        else:
            # Backward compat for older/simpler response shape
            locs = data.get("locations") or []
        if locs:
            # Aggregate covered_percentage by country, pick the dominant one.
            # This avoids being misled by the first element which may be noise
            # (e.g. 0% coverage in an unrelated country).
            by_country = {}
            for loc in locs:
                if not isinstance(loc, dict):
                    continue
                c = (loc.get("country") or "").upper().strip()
                if len(c) != 2:
                    continue
                pct = loc.get("covered_percentage")
                try:
                    pct = float(pct) if pct is not None else 0.0
                except (TypeError, ValueError):
                    pct = 0.0
                by_country[c] = by_country.get(c, 0.0) + pct
            if by_country:
                # Deterministic tie-break: highest share, then country code.
                cc = max(by_country.items(), key=lambda kv: (kv[1], kv[0]))[0]
                _cache_put(cache, prefix, cc, "L1")
                return cc, "L1", False
    except Exception as e:
        log.debug("[cloud-supp] geoloc lookup failed for %s: %s", prefix, e)

    cc = fetch_asn_country(asn)
    if cc in TARGET_REGIONS:
        _cache_put(cache, prefix, cc, "L2")
        return cc, "L2", False

    return None, "L3", False


def subtract_region_conflicts(network, cc, region_data):
    """Remove portions of a supplemental network already owned by other regions.

    APNIC/RIR delegated regional data is treated as authoritative for
    non-cloud regional ownership. Cloud supplement data must not create
    cross-region overlaps because TXT, JSON, ipset, Nginx, and MMDB consumers
    may resolve overlaps differently.

    `region_data` may be dict[cc, list[network]] or a build_region_index()
    result.
    """
    index = _region_index(region_data)
    conflicts = []
    for other_cc, idx in index.items():
        if other_cc == cc:
            continue
        conflicts.extend(idx.overlapping(network))

    if not conflicts:
        return [network]

    return subtract_excluded_from_network(network, SortedNetworks(conflicts))


def build_cloud_supplementary_networks(region_data):
    """Fetch cloud ASN prefixes, classify by country, keep TARGET_REGIONS only.

    Returns:
        supp:            dict[cc, list[IPv4Network]]  — collapsed supplementary networks
        supp_provenance: dict[cc, dict[cidr_str, {asn, tier}]]  — pre-collapse provenance
        stats:           run statistics dict
    """
    stats = {
        "prefixes_fetched": 0,
        "kept_per_region": {},
        "dropped_other_country": 0,
        "dropped_unknown": 0,
        "l0_local_hit": 0,
        "cache_hit": 0,
        "l1_success": 0,
        "l2_fallback": 0,
        "l3_fallback": 0,
        "dropped_region_conflict": 0,
        "trimmed_region_conflict": 0,
        "asns_failed": [],
        "duration_seconds": 0.0,
        "asn_count": len(CN_CLOUD_ASNS),
        "tier1_asn_count": len(CN_CLOUD_ASNS_TIER1),
        "tier2_asn_count": len(CN_CLOUD_ASNS_TIER2),
    }

    supp_raw = defaultdict(list)
    supp = {}
    # provenance: cc -> {cidr_str -> {asn, tier}} — pre-collapse, for metadata
    _supp_provenance: dict = defaultdict(dict)
    _t0 = time.time()
    # Build the APNIC containment / conflict index once; v3.4 rescanned every
    # region list linearly for each of ~1,900 prefixes.
    region_index = build_region_index(region_data)

    log.info("[cloud-supp] build_cloud_supplementary_networks start")

    for asn, name in CN_CLOUD_ASNS.items():
        try:
            prefixes = fetch_asn_prefixes(asn)
        except Exception as e:
            log.warning("[cloud-supp] ASN %s (%s) fetch failed: %s", asn, name, e)
            stats["asns_failed"].append(asn)
            continue

        for p in prefixes:
            stats["prefixes_fetched"] += 1

            cc, level, from_cache = fetch_prefix_country(str(p), asn, region_index)

            if from_cache:
                stats["cache_hit"] += 1
            if level == "L0":
                stats["l0_local_hit"] += 1
            elif level == "L1":
                stats["l1_success"] += 1
            elif level == "L2":
                stats["l2_fallback"] += 1
            elif level == "L3":
                stats["l3_fallback"] += 1

            if cc is None:
                stats["dropped_unknown"] += 1
                continue

            if cc not in TARGET_REGIONS:
                stats["dropped_other_country"] += 1
                continue

            try:
                net = ipaddress.ip_network(p, strict=False)
            except Exception:
                stats["dropped_unknown"] += 1
                continue

            conflict_free_parts = subtract_region_conflicts(net, cc, region_index)
            if not conflict_free_parts:
                stats["dropped_region_conflict"] += 1
                continue

            if len(conflict_free_parts) != 1 or conflict_free_parts[0] != net:
                stats["trimmed_region_conflict"] += 1

            supp_raw[cc].extend(conflict_free_parts)
            stats["kept_per_region"][cc] = (
                stats["kept_per_region"].get(cc, 0) + len(conflict_free_parts)
            )
            # Record pre-collapse provenance for each kept prefix.
            # `level` (L0/L1/L2 from fetch_prefix_country above) is carried
            # through so downstream confidence can reflect real signal
            # strength instead of a hardcoded value.
            for part in conflict_free_parts:
                _supp_provenance[cc][str(part)] = {
                    "asn": asn,
                    "tier": _ASN_TIER_MAP.get(asn),
                    "level": level,
                }

    for cc, nets in supp_raw.items():
        supp[cc] = list(ipaddress.collapse_addresses(nets))

    stats["duration_seconds"] = round(time.time() - _t0, 3)
    _save_geoloc_cache()
    return supp, dict(_supp_provenance), stats


def parse_and_cleanse(raw_data, excluded_networks):
    """
    Parse APNIC delegation file, extract IPv4 CIDRs for target regions,
    and filter out excluded networks.

    Optimisation:
    - Pre-collapse excluded_networks into a SortedNetworks index so each
      subtraction only touches the overlapping slice (binary search).
    """
    # Pre-process: collapse + index excluded networks once (O(log n) lookups)
    collapsed_excluded = SortedNetworks(excluded_networks)
    log.debug("Collapsed %d excluded networks -> %d",
              len(excluded_networks), len(collapsed_excluded))

    result = defaultdict(list)
    stats = {
        "kept": 0,
        "excluded": 0,
        "parse_errors": 0,
        "lines_processed": 0,
        "source_networks": 0,
        "excluded_source_networks": 0,
    }

    for line in raw_data.splitlines():
        if not line or line.startswith("#") or "|ipv4|" not in line:
            continue

        parts = line.strip().split("|")
        if len(parts) < 7:
            continue

        cc = parts[1]
        if cc not in TARGET_REGIONS:
            continue

        status = parts[6]
        if status not in ("allocated", "assigned"):
            continue

        stats["lines_processed"] += 1
        start_ip_str = parts[3]
        count_str = parts[4]

        try:
            start_ip = ipaddress.IPv4Address(start_ip_str)
            count = int(count_str)

            # Guard against zero or negative count
            if count < 1:
                stats["parse_errors"] += 1
                log.debug("Invalid count %d at line [%s]", count, start_ip_str)
                continue

            end_ip = start_ip + (count - 1)
            networks = list(ipaddress.summarize_address_range(start_ip, end_ip))

            for net in networks:
                stats["source_networks"] += 1
                kept_parts = subtract_excluded_from_network(net, collapsed_excluded)

                if kept_parts:
                    result[cc].extend(kept_parts)
                    stats["kept"] += len(kept_parts)
                    if len(kept_parts) != 1 or kept_parts[0] != net:
                        stats["excluded"] += 1
                else:
                    stats["excluded"] += 1
                    stats["excluded_source_networks"] += 1

        except (ValueError, TypeError) as e:
            stats["parse_errors"] += 1
            log.debug("Parse error at line [%s]: %s", start_ip_str, e)

    log.info("Parsing complete: %d lines -> %d source nets -> %d kept, %d excluded, %d errors",
             stats["lines_processed"], stats["source_networks"],
             stats["kept"], stats["excluded"], stats["parse_errors"])

    return result, stats



def enforce_mutual_exclusivity(region_data, supp_data=None, return_claims=False):
    """Make region CIDR sets mutually exclusive before final normalization.

    Authority order:
      Tier 1 — APNIC results (region_data) are authoritative; they claim
               their CIDRs first.
      Tier 2 — BGP supplement (supp_data) fills gaps APNIC doesn't cover.
               Any supp CIDR overlapping an already-claimed APNIC CIDR
               (regardless of which region claimed it) is trimmed.

    Within each tier, earlier TARGET_REGIONS entries have precedence; this
    only matters for the rare case of overlap inside the same tier and
    keeps outputs deterministic across TXT, JSON, Nginx, ipset and MMDB
    consumers, which may otherwise disagree when two regions contain
    overlapping CIDRs.

    Args:
        region_data:   dict[cc, list[IPv4Network]]  — APNIC-derived prefixes.
        supp_data:     optional dict[cc, list[IPv4Network]] — BGP supplement.
        return_claims: if True, also return the address space each region
                       actually gained from Tier 2 (used for provenance, so
                       an APNIC block is never labelled "bgp" merely because
                       a BGP prefix inside it was trimmed away).

    Returns:
        dict[cc, list[IPv4Network]] with all regions mutually exclusive,
        or (that dict, dict[cc, list[IPv4Network]] tier2_claims) when
        return_claims=True.
    """
    cleaned = {cc: [] for cc in TARGET_REGIONS}
    tier2_claims = {cc: [] for cc in TARGET_REGIONS}
    owned = SortedNetworks()

    def _claim(source_dict, claims_out=None):
        """Claim CIDRs from source_dict[cc] for each cc, subtracting whatever
        is already owned. Mutates `cleaned` (and `claims_out`) in place."""
        nonlocal owned
        for cc in TARGET_REGIONS:
            cleaned_nets = []
            for net in source_dict.get(cc, []):
                if net.version != 4:
                    continue
                parts = subtract_excluded_from_network(net, owned) if owned else [net]
                cleaned_nets.extend(parts)
            if not cleaned_nets:
                continue
            collapsed = list(ipaddress.collapse_addresses(cleaned_nets))
            if claims_out is not None:
                claims_out[cc] = sorted(
                    ipaddress.collapse_addresses(claims_out[cc] + collapsed),
                    key=lambda n: int(n.network_address),
                )
            # Merge with whatever this cc already has (relevant for Tier 2
            # adding to Tier 1 results).
            cleaned[cc] = sorted(
                ipaddress.collapse_addresses(cleaned[cc] + collapsed),
                key=lambda n: int(n.network_address),
            )
            owned = SortedNetworks(owned.nets + collapsed)

    # Tier 1 — APNIC authoritative
    _claim(region_data)
    # Tier 2 — BGP supplement fills gaps
    if supp_data:
        _claim(supp_data, tier2_claims)

    if return_claims:
        return cleaned, tier2_claims
    return cleaned


def restrict_provenance_to_claims(supp_provenance, tier2_claims):
    """Rebuild BGP provenance so it covers only address space that really
    entered the dataset through the Tier-2 supplement.

    Returns dict[cc, dict[cidr_str, meta]] keyed by the claimed networks.
    """
    index = _ProvenanceIndex(supp_provenance)
    out = {}
    for cc, nets in (tier2_claims or {}).items():
        for net in nets:
            hit = index.lookup(net, cc_hint=cc)
            if hit is None:
                continue
            asn, tier, level = hit
            out.setdefault(cc, {})[str(net)] = {"asn": asn, "tier": tier, "level": level}
    return out


# ================================================================
# Provenance interval matching (schema v3.3 — robust provenance)
# ================================================================
# Provenance used to be matched by exact CIDR string. But a supplement
# prefix's string changes whenever it is collapsed (here and in
# build_cloud_supplementary_networks) or trimmed (enforce_mutual_exclusivity),
# so string matching silently lost provenance and mislabelled BGP prefixes
# as "apnic". We now match by IP-range intersection, which survives any
# collapse/trim, and carry the attribution `level` through to a real
# confidence value.

# level -> confidence. L2 (ASN-holder-country guess) is the weakest signal
# and must not be advertised as "high". Unknown levels are treated as low.
_LEVEL_CONFIDENCE = {"L0": "high", "L1": "medium", "L2": "low"}
# rank for picking the most conservative level when a final CIDR spans
# multiple source prefixes (higher = weaker).
_LEVEL_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}


# Minimum fraction of a final CIDR's addresses that must come from the BGP
# supplement for the CIDR to be labelled source="bgp".
BGP_MAJORITY_SHARE = 0.5


def _level_to_confidence(level):
    return _LEVEL_CONFIDENCE.get(level, "low")


class _ProvenanceIndex:
    """Range-based provenance lookup for BGP supplement prefixes.

    Built from pre-collapse supp_provenance (cc -> {cidr_str -> {asn,tier,level}}).
    For any final CIDR, returns (asn, tier, level) of the intersecting source
    prefixes (same cc only), taking the dominant source's asn/tier and the
    most conservative (weakest) level. Returns None if no BGP source overlaps
    (i.e. the CIDR is genuinely APNIC-derived).
    """

    def __init__(self, supp_provenance):
        self._intervals = []  # (start_int, end_int, cc, meta)
        for cc, by_cidr in (supp_provenance or {}).items():
            for cidr_str, meta in by_cidr.items():
                net = ipaddress.ip_network(cidr_str, strict=False)
                self._intervals.append((
                    int(net.network_address),
                    int(net.broadcast_address),
                    cc, meta,
                ))
        self._intervals.sort(key=lambda t: t[0])
        self._starts = [t[0] for t in self._intervals]

    def lookup(self, net, cc_hint=None):
        hit = self.lookup_with_share(net, cc_hint=cc_hint)
        return None if hit is None else hit[:3]

    def lookup_with_share(self, net, cc_hint=None):
        """Like lookup(), plus the fraction (0..1] of `net`'s addresses that
        are covered by matching BGP source prefixes."""
        if not self._intervals:
            return None
        lo = int(net.network_address)
        hi = int(net.broadcast_address)
        # All source prefixes with start <= hi may intersect; scan and test.
        # Per-region source prefixes number in the hundreds–low thousands
        # (fewer after collapse), so O(n) here is fine and never misses a
        # large-span prefix whose start sits far to the left.
        hits = []
        spans = []
        cut = bisect_right(self._starts, hi)
        for j in range(cut):
            s, e, cc, meta = self._intervals[j]
            if e < lo:
                continue
            if cc_hint is None or cc == cc_hint:
                a, b = max(s, lo), min(e, hi)
                hits.append((b - a + 1, meta))
                spans.append((a, b))
        if not hits:
            return None
        # Deterministic dominant pick: largest overlap, then lowest ASN.
        hits.sort(key=lambda t: (-t[0], t[1].get("asn") or 0))
        dominant = hits[0][1]
        weakest = max((m.get("level") for _, m in hits),
                      key=lambda lv: _LEVEL_RANK.get(lv, 3))
        # Union of covered spans (source prefixes may overlap each other).
        spans.sort()
        covered = 0
        cur_a, cur_b = spans[0]
        for a, b in spans[1:]:
            if a <= cur_b + 1:
                cur_b = max(cur_b, b)
            else:
                covered += cur_b - cur_a + 1
                cur_a, cur_b = a, b
        covered += cur_b - cur_a + 1
        share = covered / (hi - lo + 1)
        return dominant.get("asn"), dominant.get("tier"), weakest, share


# ================================================================
# Normalization & aggregation
# ================================================================
def normalize_region_data(region_data, bgp_provenance=None):
    """Collapse and normalize region data into structured JSON-ready form.

    Args:
        region_data:     dict[cc, list[IPv4Network]]
        bgp_provenance:  optional dict[cc, dict[cidr_str, {asn, tier}]]
                         from build_cloud_supplementary_networks.
                         When supplied, each entry in cidr_objects carries
                         source/asn/tier/level/confidence metadata (schema v3.3).

    Returns:
        normalized dict with both legacy `cidrs` (list[str]) for backward
        compatibility and new `cidr_objects` (list[dict]) with provenance.
    """
    normalized = {}
    prov = bgp_provenance or {}
    # Build the range index once across all regions; lookup uses cc_hint to
    # keep matches within the same region.
    prov_index = _ProvenanceIndex(prov)

    for cc in TARGET_REGIONS:
        networks = region_data.get(cc, [])
        merged = sorted(ipaddress.collapse_addresses(networks))

        total_ips = sum(net.num_addresses for net in merged)

        cidr_objects = []
        for net in merged:
            s = str(net)
            hit = prov_index.lookup_with_share(net, cc_hint=cc)
            # A final CIDR is attributed to BGP only when the BGP supplement
            # contributed the majority of its addresses. Otherwise a large
            # APNIC block that merely absorbed a small adjacent/inner BGP
            # prefix during collapse would be mislabelled "bgp" (v3.4 did
            # this for e.g. 47.96.0.0/11).
            if hit is not None and hit[3] >= BGP_MAJORITY_SHARE:
                asn, tier, level, _share = hit
                cidr_objects.append({
                    "cidr": s,
                    "source": "bgp",
                    "asn": asn,
                    "tier": tier,
                    "level": level,
                    "confidence": _level_to_confidence(level),
                })
            else:
                cidr_objects.append({
                    "cidr": s,
                    "source": "apnic",
                    "asn": None,
                    "tier": None,
                    "level": "L0",
                    "confidence": "high",
                })

        normalized[cc] = {
            "region_code": cc,
            "region_name": TARGET_REGIONS[cc],
            "total_cidrs": len(merged),
            "total_ips": total_ips,
            # Legacy field — kept for backward compatibility
            "cidrs": [str(net) for net in merged],
            # v3.3: per-CIDR provenance objects (now with level + real confidence)
            "cidr_objects": cidr_objects,
        }

    return normalized


# ================================================================
# Sanity check
# ================================================================
def sanity_check(normalized_data):
    """
    Verify output meets minimum expected thresholds.
    Raises RuntimeError if any region falls below threshold.
    """
    failures = []

    for cc, threshold in SANITY_THRESHOLDS.items():
        actual = normalized_data.get(cc, {}).get("total_cidrs", 0)
        if actual < threshold:
            failures.append(
                f"{cc}: {actual} CIDRs (minimum expected: {threshold})"
            )
            log.error("SANITY FAIL - %s: got %d CIDRs, expected >= %d",
                      cc, actual, threshold)
        else:
            log.debug("Sanity OK - %s: %d CIDRs (threshold: %d)",
                      cc, actual, threshold)

    if failures:
        raise RuntimeError(
            "Sanity check FAILED. Output data is abnormally small, "
            "indicating upstream data issues:\n  " + "\n  ".join(failures)
        )

    log.info("Sanity check passed for all %d regions", len(SANITY_THRESHOLDS))


def _detect_commit_sha():
    """Best-effort detection of the commit that produced this build.

    Preference order:
      1. GITHUB_SHA env var (set in GitHub Actions)
      2. `git rev-parse HEAD` (local clone with .git present)
      3. None — recorded as 'unknown' in meta.json

    Stored in meta.json under `build.commit_sha` so anyone receiving the
    artifact can pin it to an exact source revision. Useful for both
    legitimate consumers (reproducibility) and provenance audits.
    """
    sha = os.environ.get("GITHUB_SHA")
    if sha:
        return sha.strip()

    try:
        import subprocess
        repo_root = os.path.dirname(os.path.abspath(__file__))
        result = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            out = (result.stdout or "").strip()
            if out:
                return out
    except Exception:
        pass

    return None


# ================================================================
# Output writers
# ================================================================
def _atomic_write_text(path, text):
    """Write text to `path` atomically (temp file + os.replace).

    A crash or cancelled CI job mid-write can no longer leave a truncated
    CN.txt / data.json behind for the commit step to publish.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _AtomicTextFile:
    """Context manager collecting writes, committed atomically on success."""

    def __init__(self, path):
        self.path = path
        self._chunks = []

    def write(self, text):
        self._chunks.append(text)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            _atomic_write_text(self.path, "".join(self._chunks))
        return False


def save_txt_outputs(normalized_data, output_dir="output"):
    """Write per-region .txt files with metadata headers."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    for cc, payload in normalized_data.items():
        filepath = os.path.join(output_dir, f"{cc}.txt")

        with _AtomicTextFile(filepath) as f:
            f.write("# Project     : ipnova\n")
            f.write(f"# Version     : {__version__}\n")
            f.write(f"# Region      : {payload['region_name']}\n")
            f.write(f"# Last Updated: {timestamp}\n")
            f.write("# Source      : APNIC delegated + BGP multi-source fusion\n")
            f.write(f"# Total CIDRs : {payload['total_cidrs']}\n")
            f.write(f"# Total IPs   : {payload['total_ips']:,}\n")
            f.write(
                f"# Note        : Each region is separated — "
                f"this file contains {payload['region_name']} only\n"
            )
            f.write(
                "# Provenance  : includes a few RFC5737 documentation-reserved "
                "CIDRs as\n#               fingerprints; they never route publicly "
                "and are safe to ignore\n"
            )
            f.write("# " + "=" * 48 + "\n")
            for cidr in payload["cidrs"]:
                f.write(cidr + "\n")

        log.info("  %s.txt - %s: %d CIDRs (%s IPs)",
                 cc, payload["region_name"],
                 payload["total_cidrs"], f"{payload['total_ips']:,}")


def save_json_outputs(normalized_data, asn_report, parse_stats, output_dir="output"):
    """
    Save structured JSON data layer and enriched metadata layer.
    The meta.json schema is the stable contract for ipnova-pro.
    """
    os.makedirs(output_dir, exist_ok=True)
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # --- data.json: the primary dataset ---
    data_payload = {
        "schema_version": SCHEMA_VERSION,
        "project": "ipnova",
        "version": __version__,
        "generated_at": generated_at,
        "regions": normalized_data,
    }

    data_json_str = json.dumps(data_payload, indent=2, ensure_ascii=False) + "\n"

    # SHA-256 checksum for data integrity (ipnova-pro can verify downloads)
    data_sha256 = hashlib.sha256(data_json_str.encode("utf-8")).hexdigest()

    _atomic_write_text(os.path.join(output_dir, "data.json"), data_json_str)

    # --- meta.json: enriched metadata for monitoring & pro integration ---
    from regions import CANARY_CIDRS as _CANARY_CIDRS
    commit_sha = _detect_commit_sha()
    meta_payload = {
        "schema_version": SCHEMA_VERSION,
        "project": "ipnova",
        "version": __version__,
        "generated_at": generated_at,
        "source": "APNIC delegated + BGP multi-source fusion",
        "build": {
            # Pin this artifact to its source revision. Lets downstream
            # consumers reproduce the build, and lets the author identify
            # which version of the code produced a redistributed copy.
            "commit_sha": commit_sha,
            "user_agent": USER_AGENT,
            "python": sys.version.split()[0],
            "ripe": parse_stats.get("ripe"),
        },
        "provenance": {
            # Canary CIDR set embedded in published artifacts. These are
            # RFC5737 documentation-reserved ranges that never route on
            # the public Internet, so they are harmless for downstream
            # firewall/ACL use but make unattributed redistribution
            # detectable. Listed openly here — the point is forensic
            # attribution, not concealment.
            "canary_cidrs": _CANARY_CIDRS,
            "canary_injected": parse_stats.get("canary_injected", 0),
        },
        "target_regions": TARGET_REGIONS,
        "counts": {
            cc: {
                "cidrs": normalized_data[cc]["total_cidrs"],
                "ips": normalized_data[cc]["total_ips"],
            }
            for cc in normalized_data
        },
        "exclusion": {
            "mode": asn_report.get("mode", "dynamic+static"),
            "asns_total": len(EXCLUDED_ASNS),
            "asns_succeeded": sorted(asn_report["succeeded"]),
            "asns_failed": sorted(asn_report["failed"]),
            "dynamic_prefixes": asn_report["total_prefixes"],
            "static_blacklist": ANYCAST_BLACKLIST,
        },
        "parsing": {
            "lines_processed": parse_stats["lines_processed"],
            "source_networks": parse_stats["source_networks"],
            "cidrs_kept": parse_stats["kept"],
            "cidrs_excluded": parse_stats["excluded"],
            "excluded_source_networks": parse_stats["excluded_source_networks"],
            "parse_errors": parse_stats["parse_errors"],
            "prefixes_before_collapse": parse_stats.get("prefixes_before_collapse"),
            "prefixes_after_collapse": parse_stats.get("prefixes_after_collapse"),
            "cloud_supplement": parse_stats.get("cloud_supplement"),
        },
        "sanity_thresholds": SANITY_THRESHOLDS,
        "checksum": {
            "data_json_sha256": data_sha256,
        },
    }

    _atomic_write_text(
        os.path.join(output_dir, "meta.json"),
        json.dumps(meta_payload, indent=2, ensure_ascii=False) + "\n",
    )

    log.info("  data.json - structured dataset (sha256: %s...)", data_sha256[:16])
    log.info("  meta.json - enriched metadata written")


# ================================================================
# CLI
# ================================================================
def build_parser():
    """Build argument parser."""
    parser = argparse.ArgumentParser(
        prog="ipnova",
        description="IPNova - High-quality IPv4 CIDR list generator",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="output",
        help="Output directory (default: output)",
    )
    parser.add_argument(
        "--skip-ripe",
        action="store_true",
        help="Skip all RIPE Stat queries (static blacklist only, no cloud supplement)",
    )
    parser.add_argument(
        "--skip-cloud-supplement",
        action="store_true",
        help="Skip CN cloud ASN supplement (APNIC-only output)",
    )
    parser.add_argument(
        "--skip-sanity",
        action="store_true",
        help="Skip sanity check (not recommended for production)",
    )
    parser.add_argument(
        "--skip-canary",
        action="store_true",
        help="Skip canary CIDR injection (for verification builds; "
             "do NOT use for published artifacts)",
    )
    parser.add_argument(
        "--ripe-budget",
        type=int,
        default=RIPE_BREAKER_MAX_PHASE_SECONDS,
        metavar="SECONDS",
        help="Wall-clock cap for all RIPE Stat traffic before the circuit "
             f"breaker trips (default: {RIPE_BREAKER_MAX_PHASE_SECONDS})",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ipnova {__version__}",
    )
    return parser


# ================================================================
# Main
# ================================================================
def ripe_breaker_status():
    """Snapshot of the RIPE circuit breaker, recorded in meta.json so a
    degraded (partially supplemented) build is visible to consumers."""
    return {
        "breaker_tripped": _RIPE_BREAKER_TRIPPED,
        "consecutive_failures": _RIPE_CONSECUTIVE_FAILURES,
        "phase_seconds": (round(time.monotonic() - _RIPE_PHASE_START, 1)
                          if _RIPE_PHASE_START else 0.0),
        "phase_budget_seconds": RIPE_BREAKER_MAX_PHASE_SECONDS,
    }


def main(argv=None):
    global RIPE_BREAKER_MAX_PHASE_SECONDS
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(verbose=args.verbose)
    if args.ripe_budget <= 0:
        parser.error("--ripe-budget must be a positive number of seconds")
    RIPE_BREAKER_MAX_PHASE_SECONDS = args.ripe_budget
    set_geoloc_cache_path(args.output_dir)

    log.info("=" * 55)
    log.info("  ipnova %s - High-quality IP database generator", __version__)
    log.info("=" * 55)

    start_time = time.monotonic()

    # Step 1: Download APNIC data
    with StepTimer("APNIC download"):
        raw_data = download_apnic_data()

    # Step 2: Build exclusion set
    with StepTimer("Exclusion set build"):
        excluded_networks, asn_report = build_excluded_networks(
            skip_ripe=args.skip_ripe
        )

    # Step 3: Parse and filter
    with StepTimer("Parse and filter"):
        region_data, parse_stats = parse_and_cleanse(raw_data, excluded_networks)

    # Step 3.1: Inject canary CIDRs. These are RFC5737 documentation-reserved
    # ranges that never route on the public Internet, so they are harmless
    # for downstream consumers but act as provenance fingerprints — if an
    # unattributed third-party dataset contains our exact canary set, that
    # is strong evidence it was derived from IPNova. Injected as APNIC-tier
    # so the canaries survive enforce_mutual_exclusivity even if a BGP-
    # supplement prefix somehow overlaps them.
    if not args.skip_canary:
        from regions import canary_networks
        canary_count = 0
        for cc, canary_net in canary_networks().items():
            region_data.setdefault(cc, []).append(canary_net)
            canary_count += 1
        log.info("Canary CIDRs injected: %d (one per region)", canary_count)
        parse_stats["canary_injected"] = canary_count
    else:
        log.info("Canary CIDR injection skipped (--skip-canary)")
        parse_stats["canary_injected"] = 0

    # Step 3.5: CN cloud ASN supplement
    supp = None
    if args.skip_ripe or args.skip_cloud_supplement:
        log.info("Skipping cloud ASN supplement")
        supp_provenance = {}
        parse_stats["cloud_supplement"] = {
            "skipped": True,
            "reason": "skip_ripe" if args.skip_ripe else "skip_cloud_supplement",
        }
    else:
        with StepTimer("Cloud ASN supplement"):
            supp, supp_provenance, supp_stats = build_cloud_supplementary_networks(region_data)
        parse_stats["cloud_supplement"] = supp_stats

    # Count APNIC + (optional) BGP supp prefixes *before* enforce + collapse,
    # so the meta stat reflects raw input volume.
    parse_stats["prefixes_before_collapse"] = (
        sum(len(v) for v in region_data.values())
        + (sum(len(v) for v in supp.values()) if supp else 0)
    )

    # Step 4: Normalize and aggregate
    # APNIC results are authoritative (Tier 1); BGP supplement fills gaps (Tier 2).
    with StepTimer("Normalize and aggregate"):
        region_data, tier2_claims = enforce_mutual_exclusivity(
            region_data, supp_data=supp, return_claims=True,
        )
        # Provenance only for address space that actually came from Tier 2.
        claimed_provenance = (
            restrict_provenance_to_claims(supp_provenance, tier2_claims)
            if supp_provenance else None
        )
        normalized_data = normalize_region_data(
            region_data, bgp_provenance=claimed_provenance,
        )
    parse_stats["prefixes_after_collapse"] = sum(
        v.get("total_cidrs", 0) for v in normalized_data.values()
    )

    parse_stats["ripe"] = ripe_breaker_status()
    if _RIPE_BREAKER_TRIPPED:
        log.warning(
            "RIPE circuit breaker tripped during this run — exclusion and/or "
            "cloud supplement data may be incomplete (recorded in meta.json)."
        )

    # Step 5: Sanity check
    if not args.skip_sanity:
        sanity_check(normalized_data)

    # Step 6: Write outputs
    log.info("Writing outputs to %s/", args.output_dir)
    with StepTimer("Write outputs"):
        save_txt_outputs(normalized_data, output_dir=args.output_dir)
        save_json_outputs(normalized_data, asn_report, parse_stats,
                          output_dir=args.output_dir)

    elapsed = time.monotonic() - start_time
    log.info("")
    log.info("Done in %.1fs. Output: %s/", elapsed, args.output_dir)

    # Summary
    total_cidrs = sum(d["total_cidrs"] for d in normalized_data.values())
    total_ips = sum(d["total_ips"] for d in normalized_data.values())
    log.info("Total: %d CIDRs, %s IPs across %d regions",
             total_cidrs, f"{total_ips:,}", len(normalized_data))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        sys.exit(130)
    except RuntimeError as e:
        log.error("FATAL: %s", e)
        sys.exit(1)
    except Exception as e:  # network errors, I/O errors, etc.
        log.error("FATAL: %s: %s", type(e).__name__, e,
                  exc_info=log.isEnabledFor(logging.DEBUG))
        sys.exit(1)
