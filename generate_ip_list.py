#!/usr/bin/env python3
"""
Project : ipnova
Repo    : https://github.com/harryheros/ipnova
Desc    : High-quality IPv4 CIDR list generator for CN / HK / TW / MO
Source  : APNIC RIR official delegation data (upstream, not derived)
"""

import urllib.request
import urllib.error
import ipaddress
import os
import sys
import time
import argparse
import datetime
import json
import logging
from collections import defaultdict

# ================================================================
# Version
# ================================================================
__version__ = "2.1.0"

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
TARGET_REGIONS = {
    "CN": "China (Mainland)",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "MO": "Macau",
}

# ================================================================
# Sanity thresholds: minimum expected CIDR counts per region
# If output falls below these, something is very wrong upstream
# ================================================================
SANITY_THRESHOLDS = {
    "CN": 3000,
    "HK": 1000,
    "TW": 300,
    "MO": 10,
}

APNIC_URL = "https://ftp.apnic.net/stats/apnic/delegated-apnic-latest"
RIPE_STAT_URL = "https://stat.ripe.net/data/announced-prefixes/data.json"

# Retry / rate-limit constants
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2   # seconds, exponential: 2, 4, 8
RIPE_REQUEST_INTERVAL = 1.5  # seconds between RIPE Stat requests


# ================================================================
# HTTP helpers with retry
# ================================================================
def http_get(url, timeout=30, retries=MAX_RETRIES, ua="ipnova-bot/2.1",
             return_content_type=False):
    """
    Fetch URL with exponential backoff retry.
    Returns response body as str, or (body, content_type) if requested.
    Raises on total failure.
    """
    headers = {"User-Agent": ua}
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if return_content_type:
                    content_type = resp.headers.get("Content-Type", "")
                    return body, content_type
                return body
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait = RETRY_BACKOFF_BASE ** attempt
                log.warning("HTTP attempt %d/%d failed for %s: %s (retry in %ds)",
                            attempt, retries, url[:80], e, wait)
                time.sleep(wait)
            else:
                log.error("HTTP failed after %d attempts for %s: %s",
                          retries, url[:80], e)

    raise last_err


# ================================================================
# Data acquisition
# ================================================================
def download_apnic_data():
    """Download the latest APNIC delegation file with retry."""
    log.info("Fetching APNIC delegation data from %s", APNIC_URL)
    data = http_get(APNIC_URL, timeout=60)
    line_count = len(data.splitlines())
    log.info("Downloaded %d lines from APNIC", line_count)

    if line_count < 1000:
        raise RuntimeError(
            f"APNIC data suspiciously small ({line_count} lines). "
            "Upstream may be broken. Aborting."
        )

    return data


def fetch_asn_prefixes(asn):
    """
    Fetch announced IPv4 prefixes for a single ASN from RIPE Stat.
    Returns list of IPv4Network objects.
    """
    url = f"{RIPE_STAT_URL}?resource=AS{asn}"
    body, content_type = http_get(url, timeout=20, return_content_type=True)

    if "json" not in content_type.lower():
        preview = body[:200].replace("\n", " ").strip()
        raise RuntimeError(
            f"Unexpected RIPE content type for AS{asn}: {content_type!r}; "
            f"body preview={preview!r}"
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        preview = body[:200].replace("\n", " ").strip()
        raise RuntimeError(
            f"RIPE API returned non-JSON for AS{asn}: {e}; "
            f"body preview={preview!r}"
        )

    if not isinstance(payload, dict):
        raise RuntimeError(f"Malformed RIPE response for AS{asn}: root is not object")

    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"Malformed RIPE response for AS{asn}: missing data object")

    prefixes = data.get("prefixes", [])
    if not isinstance(prefixes, list):
        raise RuntimeError(f"Malformed RIPE response for AS{asn}: prefixes is not list")

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

        for asn in sorted(EXCLUDED_ASNS):
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

            # Rate limit: pause between requests
            time.sleep(RIPE_REQUEST_INTERVAL)

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
def subtract_excluded_from_network(network, excluded_networks):
    """
    Precisely subtract excluded subnets from a source network.

    Important:
    - Do NOT drop the entire network merely because it overlaps with
      an excluded subnet.
    - Instead, cut out the excluded portions and keep the remainder.

    Returns:
        list[IPv4Network]
    """
    remaining = [network]

    for ex in excluded_networks:
        new_remaining = []

        for current in remaining:
            if not current.overlaps(ex):
                new_remaining.append(current)
                continue

            # current fully covered by excluded network
            if current.subnet_of(ex):
                continue

            # excluded network is a subnet of current -> subtract precisely
            if ex.subnet_of(current):
                try:
                    new_remaining.extend(current.address_exclude(ex))
                except ValueError:
                    # Fallback: keep original if subtraction fails unexpectedly
                    new_remaining.append(current)
                continue

            # Defensive fallback: keep original if overlap shape is unexpected
            new_remaining.append(current)

        remaining = new_remaining
        if not remaining:
            break

    return remaining


# ================================================================
# Parsing & filtering
# ================================================================
def parse_and_cleanse(raw_data, excluded_networks):
    """
    Parse APNIC delegation file, extract IPv4 CIDRs for target regions,
    and filter out excluded networks.

    Optimisation: pre-collapse excluded_networks to reduce overlap checks.
    """
    # Pre-process: collapse excluded networks for faster overlap checking
    try:
        collapsed_excluded = sorted(
            ipaddress.collapse_addresses(excluded_networks),
            key=lambda n: (int(n.network_address), n.prefixlen),
        )
        log.debug("Collapsed %d excluded networks -> %d",
                  len(excluded_networks), len(collapsed_excluded))
    except Exception:
        collapsed_excluded = excluded_networks
        log.debug("Could not collapse excluded networks, using raw list")

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

    log.info("Parsing complete: %d lines -> %d kept, %d excluded, %d errors",
             stats["lines_processed"], stats["kept"],
             stats["excluded"], stats["parse_errors"])

    return result, stats


# ================================================================
# Normalization & aggregation
# ================================================================
def normalize_region_data(region_data):
    """Collapse and normalize region data into structured JSON-ready form."""
    normalized = {}

    for cc in TARGET_REGIONS:
        networks = region_data.get(cc, [])
        merged = sorted(ipaddress.collapse_addresses(networks))

        total_ips = sum(net.num_addresses for net in merged)

        normalized[cc] = {
            "region_code": cc,
            "region_name": TARGET_REGIONS[cc],
            "total_cidrs": len(merged),
            "total_ips": total_ips,
            "cidrs": [str(net) for net in merged],
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


# ================================================================
# Output writers
# ================================================================
def save_txt_outputs(normalized_data, output_dir="output"):
    """Write per-region .txt files with metadata headers."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    for cc, payload in normalized_data.items():
        filepath = os.path.join(output_dir, f"{cc}.txt")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# Project     : ipnova\n")
            f.write(f"# Version     : {__version__}\n")
            f.write(f"# Region      : {payload['region_name']}\n")
            f.write(f"# Last Updated: {timestamp}\n")
            f.write("# Source      : APNIC delegated-apnic-latest\n")
            f.write(f"# Total CIDRs : {payload['total_cidrs']}\n")
            f.write(f"# Total IPs   : {payload['total_ips']:,}\n")
            f.write("# Note        : HK / TW / MO are NOT included in CN\n")
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
        "schema_version": "2.1",
        "project": "ipnova",
        "version": __version__,
        "generated_at": generated_at,
        "regions": normalized_data,
    }

    # --- meta.json: enriched metadata for monitoring & pro integration ---
    meta_payload = {
        "schema_version": "2.1",
        "project": "ipnova",
        "version": __version__,
        "generated_at": generated_at,
        "source": "APNIC delegated-apnic-latest",
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
            "asns_succeeded": asn_report["succeeded"],
            "asns_failed": asn_report["failed"],
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
        },
        "sanity_thresholds": SANITY_THRESHOLDS,
    }

    with open(os.path.join(output_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data_payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    with open(os.path.join(output_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta_payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    log.info("  data.json - structured dataset written")
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
        help="Skip RIPE Stat ASN queries (use static blacklist only)",
    )
    parser.add_argument(
        "--skip-sanity",
        action="store_true",
        help="Skip sanity check (not recommended for production)",
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
def main():
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    log.info("=" * 55)
    log.info("  ipnova %s - High-quality IP database generator", __version__)
    log.info("=" * 55)

    start_time = time.time()

    # Step 1: Download APNIC data
    raw_data = download_apnic_data()

    # Step 2: Build exclusion set
    excluded_networks, asn_report = build_excluded_networks(
        skip_ripe=args.skip_ripe
    )

    # Step 3: Parse and filter
    region_data, parse_stats = parse_and_cleanse(raw_data, excluded_networks)

    # Step 4: Normalize and aggregate
    normalized_data = normalize_region_data(region_data)

    # Step 5: Sanity check
    if not args.skip_sanity:
        sanity_check(normalized_data)

    # Step 6: Write outputs
    log.info("Writing outputs to %s/", args.output_dir)
    save_txt_outputs(normalized_data, output_dir=args.output_dir)
    save_json_outputs(normalized_data, asn_report, parse_stats,
                      output_dir=args.output_dir)

    elapsed = time.time() - start_time
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
    except RuntimeError as e:
        log.error("FATAL: %s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        sys.exit(130)
