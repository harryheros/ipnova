#!/usr/bin/env python3
"""
Project : ipnova
Repo    : https://github.com/harryheros/ipnova
Desc    : High-quality IPv4 CIDR list generator for CN / HK / TW / MO
Source  : APNIC RIR official delegation data (upstream, not derived)
"""

import urllib.request
import ipaddress
import os
import datetime
import json
from collections import defaultdict

# ----------------------------------------------------------------
# ASN Blacklist: Exclude global Anycast / CDN / Cloud providers
# This is the primary filter; CIDR blacklist is a fallback.
# ----------------------------------------------------------------
EXCLUDED_ASNS = {
    13335, 209242,      # Cloudflare
    15169, 396982,      # Google
    20940, 16625,       # Akamai
    54113,              # Fastly
    16509, 14618,       # AWS
    8075, 8069,         # Microsoft / Azure
    32934,              # Meta
    13414,              # Twitter / X
}

# ----------------------------------------------------------------
# CIDR Blacklist: Known Anycast prefixes (fallback / safety net)
# ----------------------------------------------------------------
ANYCAST_BLACKLIST = [
    "1.0.0.0/24",       # Cloudflare DNS
    "1.1.1.0/24",       # Cloudflare DNS
    "8.8.8.0/24",       # Google DNS
    "8.8.4.0/24",       # Google DNS
    "9.9.9.0/24",       # Quad9
    "208.67.222.0/24",  # OpenDNS
    "208.67.220.0/24",  # OpenDNS
]

# ----------------------------------------------------------------
# Target regions
# ----------------------------------------------------------------
TARGET_REGIONS = {
    "CN": "China (Mainland)",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "MO": "Macau",
}

APNIC_URL = "https://ftp.apnic.net/stats/apnic/delegated-apnic-latest"


def download_apnic_data():
    """Download the latest APNIC delegation file."""
    print("[*] Fetching latest APNIC delegation data...")
    req = urllib.request.Request(
        APNIC_URL,
        headers={"User-Agent": "ipnova-bot/1.0 (https://github.com/harryheros/ipnova)"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read().decode("utf-8")
    print(f"[+] Downloaded {len(data.splitlines())} lines")
    return data


def build_excluded_networks():
    """
    Dynamically fetch announced prefixes for each blacklisted ASN
    via RIPE Stat, then merge with the static CIDR blacklist.
    """
    excluded = []
    print("[*] Fetching prefixes for blacklisted ASNs...")

    for asn in EXCLUDED_ASNS:
        url = f"https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS{asn}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ipnova-bot/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            prefixes = payload.get("data", {}).get("prefixes", [])
            v4 = []
            for p in prefixes:
                try:
                    net = ipaddress.ip_network(p.get("prefix", ""), strict=False)
                    if net.version == 4:
                        excluded.append(net)
                        v4.append(net)
                except ValueError:
                    continue
            print(f"    AS{asn}: {len(v4)} IPv4 prefixes excluded")
        except Exception:
            print(f"    AS{asn}: query failed, skipping (static blacklist will cover)")

    for cidr in ANYCAST_BLACKLIST:
        try:
            excluded.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue

    print(f"[+] Total excluded networks: {len(excluded)} (ASN dynamic + static blacklist)")
    return excluded


def parse_and_cleanse(raw_data, excluded_networks):
    """
    Parse the APNIC delegation file and filter IPv4 CIDRs
    for target regions. Uses summarize_address_range for
    accurate handling of non-power-of-2 boundaries.
    """
    result = defaultdict(list)
    kept = 0
    skipped = 0

    for line in raw_data.splitlines():
        if not line or line.startswith("#") or "|ipv4|" not in line:
            continue
        parts = line.strip().split("|")
        if len(parts) < 7:
            continue

        cc = parts[1]
        start_ip_str = parts[3]
        count_str = parts[4]
        status = parts[6]

        if status not in ("allocated", "assigned"):
            continue
        if cc not in TARGET_REGIONS:
            continue

        try:
            start_ip = ipaddress.IPv4Address(start_ip_str)
            count = int(count_str)
            end_ip = start_ip + (count - 1)
            networks = list(ipaddress.summarize_address_range(start_ip, end_ip))

            for net in networks:
                if any(net.overlaps(ex) for ex in excluded_networks):
                    skipped += 1
                    continue
                result[cc].append(net)
                kept += 1

        except Exception:
            continue

    print(f"[+] Parsing complete: {kept} kept, {skipped} excluded")
    return result


def normalize_region_data(region_data):
    """
    Collapse and normalize region data into structured JSON-ready form.
    """
    normalized = {}

    for cc in TARGET_REGIONS:
        networks = region_data.get(cc, [])
        merged = sorted(ipaddress.collapse_addresses(networks))
        normalized[cc] = {
            "region_code": cc,
            "region_name": TARGET_REGIONS[cc],
            "total_cidrs": len(merged),
            "cidrs": [str(net) for net in merged],
        }

    return normalized


def save_txt_outputs(normalized_data, output_dir="output"):
    """Write per-region .txt files with metadata headers."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    for cc, payload in normalized_data.items():
        filepath = os.path.join(output_dir, f"{cc}.txt")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# Project     : ipnova\n")
            f.write(f"# Region      : {payload['region_name']}\n")
            f.write(f"# Last Updated: {timestamp}\n")
            f.write("# Source      : APNIC delegated-apnic-latest\n")
            f.write(f"# Total CIDRs : {payload['total_cidrs']}\n")
            f.write("# Note        : HK / TW / MO are NOT included in CN\n")
            f.write("# " + "=" * 48 + "\n")
            for cidr in payload["cidrs"]:
                f.write(cidr + "\n")

        print(f"[+] {cc}.txt - {payload['region_name']}: {payload['total_cidrs']} CIDRs")


def save_json_outputs(normalized_data, output_dir="output"):
    """
    Save structured JSON data layer and metadata layer.
    """
    os.makedirs(output_dir, exist_ok=True)
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    data_payload = {
        "project": "ipnova",
        "generated_at": generated_at,
        "regions": normalized_data,
    }

    meta_payload = {
        "project": "ipnova",
        "generated_at": generated_at,
        "source": "APNIC delegated-apnic-latest",
        "target_regions": TARGET_REGIONS,
        "excluded_asns": sorted(EXCLUDED_ASNS),
        "static_anycast_blacklist": ANYCAST_BLACKLIST,
        "counts": {
            cc: normalized_data[cc]["total_cidrs"] for cc in normalized_data
        },
    }

    with open(os.path.join(output_dir, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data_payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    with open(os.path.join(output_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta_payload, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("[+] data.json - structured dataset written")
    print("[+] meta.json - metadata written")


def main():
    print("=" * 55)
    print("  ipnova - High-quality IP database generator")
    print("=" * 55)

    raw_data = download_apnic_data()
    excluded_networks = build_excluded_networks()
    region_data = parse_and_cleanse(raw_data, excluded_networks)
    normalized_data = normalize_region_data(region_data)

    save_txt_outputs(normalized_data)
    save_json_outputs(normalized_data)

    print("\n[✓] Done. Output directory: ./output/")


if __name__ == "__main__":
    main()
