#!/usr/bin/env python3
"""
build_formats.py — IPNova extended format generator

Generates additional output formats from ipnova's data.json:
  - ipnova-apac.mmdb   : MaxMind-compatible MMDB (via mmdb/ module)
  - regions.json       : Per-region combined JSON (zero dependencies)
  - json/{CC}.json     : Per-region individual JSON (zero dependencies)
  - nginx/{CC}.conf    : Nginx geo module format (zero dependencies)
  - iptables/{CC}.ipset: iptables ipset restore format (zero dependencies)

Usage:
    python3 scripts/build_formats.py [--output-dir output] [--skip-mmdb] [-v]

Run after generate_ip_list.py.
Requires for MMDB: pip install mmdb-writer maxminddb
"""

import argparse
import json
import logging
import os
import sys
import datetime

log = logging.getLogger("ipnova.formats")


# ================================================================
# Helpers
# ================================================================

def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )


def load_data_json(output_dir):
    path = os.path.join(output_dir, "data.json")
    if not os.path.exists(path):
        log.error("data.json not found at %s — run generate_ip_list.py first", path)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ================================================================
# Format 1: MMDB (via mmdb/ module)
# ================================================================

def build_mmdb(data, output_dir):
    """Build ipnova-apac.mmdb via mmdb.builder."""
    # Add project root to path so mmdb/ module is importable
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    try:
        from mmdb.builder import build
        from mmdb.validator import validate
    except ImportError as e:
        log.warning("mmdb module error: %s", e)
        return False

    try:
        out_path = build(data.get("regions", {}), output_dir)
        validate(out_path)
        return True
    except ImportError as e:
        log.warning("%s", e)
        log.warning("Skipping MMDB — install with: pip install mmdb-writer maxminddb")
        return False


# ================================================================
# Format 2: Per-region JSON
# ================================================================

def build_json_per_region(data, output_dir):
    """Build per-region JSON files and a combined regions.json."""
    json_dir = os.path.join(output_dir, "json")
    os.makedirs(json_dir, exist_ok=True)

    regions = data.get("regions", {})
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    combined = {
        "schema_version": data.get("schema_version", "3.1"),
        "project": "ipnova",
        "version": data.get("version", ""),
        "generated_at": generated_at,
        "regions": {}
    }

    for cc, payload in regions.items():
        region_data = {
            "region": cc,
            "region_name": payload.get("region_name", cc),
            "total_cidrs": payload.get("total_cidrs", 0),
            "total_ips": payload.get("total_ips", 0),
            "generated_at": generated_at,
            "cidrs": payload.get("cidrs", []),
        }
        out_path = os.path.join(json_dir, f"{cc}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(region_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        combined["regions"][cc] = region_data
        log.info("  json/%s.json — %d CIDRs", cc, payload.get("total_cidrs", 0))

    combined_path = os.path.join(output_dir, "regions.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info("  regions.json — all %d regions combined", len(regions))
    return True


# ================================================================
# Format 3: Nginx geo module
# ================================================================

def build_nginx(data, output_dir):
    """Build Nginx geo module format files."""
    nginx_dir = os.path.join(output_dir, "nginx")
    os.makedirs(nginx_dir, exist_ok=True)

    regions = data.get("regions", {})
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    for cc, payload in regions.items():
        out_path = os.path.join(nginx_dir, f"{cc}.conf")
        cidrs = payload.get("cidrs", [])
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# IPNova — Nginx geo module — {cc} ({payload.get('region_name', cc)})\n")
            f.write(f"# Generated : {timestamp}\n")
            f.write(f"# CIDRs     : {len(cidrs)}\n")
            f.write(f"# Project   : https://github.com/harryheros/ipnova\n")
            f.write("#\n")
            f.write(f"# Usage in nginx.conf:\n")
            f.write(f"#   geo $ipnova_country {{\n")
            f.write(f"#       default \"\";\n")
            f.write(f"#       include /path/to/ipnova/nginx/{cc}.conf;\n")
            f.write(f"#   }}\n")
            f.write("#\n")
            for cidr in cidrs:
                f.write(f"{cidr} {cc};\n")
        log.info("  nginx/%s.conf — %d CIDRs", cc, len(cidrs))
    return True


# ================================================================
# Format 4: iptables ipset
# ================================================================

def build_iptables(data, output_dir):
    """Build iptables ipset restore format files."""
    ipt_dir = os.path.join(output_dir, "iptables")
    os.makedirs(ipt_dir, exist_ok=True)

    regions = data.get("regions", {})
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    for cc, payload in regions.items():
        out_path = os.path.join(ipt_dir, f"{cc}.ipset")
        cidrs = payload.get("cidrs", [])
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# IPNova — ipset restore — {cc} ({payload.get('region_name', cc)})\n")
            f.write(f"# Generated : {timestamp}\n")
            f.write(f"# CIDRs     : {len(cidrs)}\n")
            f.write(f"# Project   : https://github.com/harryheros/ipnova\n")
            f.write("#\n")
            f.write(f"# Usage:\n")
            f.write(f"#   ipset restore < {cc}.ipset\n")
            f.write(f"#   iptables -I FORWARD -m set --match-set ipnova_{cc} dst -j ACCEPT\n")
            f.write("#\n")
            f.write(f"create ipnova_{cc} hash:net family inet hashsize 4096 maxelem 65536\n")
            for cidr in cidrs:
                f.write(f"add ipnova_{cc} {cidr}\n")
        log.info("  iptables/%s.ipset — %d CIDRs", cc, len(cidrs))
    return True


# ================================================================
# CLI
# ================================================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog="build_formats",
        description="IPNova extended format generator — run after generate_ip_list.py",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="output",
        help="Output directory (default: output, must contain data.json)",
    )
    parser.add_argument(
        "--skip-mmdb",
        action="store_true",
        help="Skip MMDB generation",
    )
    parser.add_argument(
        "--skip-nginx",
        action="store_true",
        help="Skip Nginx format generation",
    )
    parser.add_argument(
        "--skip-iptables",
        action="store_true",
        help="Skip iptables format generation",
    )
    parser.add_argument(
        "--skip-json",
        action="store_true",
        help="Skip per-region JSON generation",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging",
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
    log.info("  ipnova build_formats — extended output generator")
    log.info("=" * 55)

    data = load_data_json(args.output_dir)
    regions = data.get("regions", {})
    log.info("Loaded data.json — %d regions", len(regions))
    log.info("")

    results = {}

    if not args.skip_mmdb:
        log.info("--- MMDB ---")
        results["mmdb"] = build_mmdb(data, args.output_dir)
        log.info("")

    if not args.skip_json:
        log.info("--- JSON per region ---")
        results["json"] = build_json_per_region(data, args.output_dir)
        log.info("")

    if not args.skip_nginx:
        log.info("--- Nginx geo module ---")
        results["nginx"] = build_nginx(data, args.output_dir)
        log.info("")

    if not args.skip_iptables:
        log.info("--- iptables ipset ---")
        results["iptables"] = build_iptables(data, args.output_dir)
        log.info("")

    log.info("Done.")
    log.info("")
    log.info("Output summary:")
    if results.get("mmdb"):
        log.info("  %-20s output/ipnova-apac.mmdb", "MMDB:")
    if results.get("json"):
        log.info("  %-20s output/regions.json + output/json/{CC}.json", "JSON:")
    if results.get("nginx"):
        log.info("  %-20s output/nginx/{CC}.conf", "Nginx:")
    if results.get("iptables"):
        log.info("  %-20s output/iptables/{CC}.ipset", "iptables:")


if __name__ == "__main__":
    main()
