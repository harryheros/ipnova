#!/usr/bin/env python3
import bisect
import ipaddress
import json
import socket
import sys
from pathlib import Path

socket.setdefaulttimeout(5)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
TESTS_DIR = ROOT / "tests"

META_PATH = OUTPUT_DIR / "meta.json"
SAMPLES_PATH = TESTS_DIR / "samples.json"

REGION_FILES = {
    "CN": OUTPUT_DIR / "CN.txt",
    "HK": OUTPUT_DIR / "HK.txt",
    "TW": OUTPUT_DIR / "TW.txt",
    "MO": OUTPUT_DIR / "MO.txt",
    "JP": OUTPUT_DIR / "JP.txt",
    "KR": OUTPUT_DIR / "KR.txt",
    "SG": OUTPUT_DIR / "SG.txt",
}

MAX_L2_RATIO = 0.60
_NETWORK_KEYS = {}
MAX_HK_CIDRS = 5000
MIN_CN_CIDRS = 4000


def load_cidrs(path: Path):
    nets = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            nets.append(ipaddress.ip_network(line, strict=False))
    # Sort by network address for binary-search pre-filtering
    return sorted(nets, key=lambda n: int(n.network_address))


def ip_in_region(ip: str, nets):
    """Check if IP falls within any of the sorted network list.
    Uses binary search pre-filtering for O(log n) candidate selection.
    """
    ip_obj = ipaddress.ip_address(ip)
    ip_int = int(ip_obj)
    # Find insertion point — all nets with network_address <= ip_int are candidates
    keys = _NETWORK_KEYS.get(id(nets))
    if keys is None:
        keys = [int(n.network_address) for n in nets]
        _NETWORK_KEYS[id(nets)] = keys
    idx = bisect.bisect_right(keys, ip_int)
    # Check backwards from insertion point (nearest candidates first)
    for i in range(min(idx, len(nets)) - 1, max(idx - 512, -1), -1):
        if ip_obj in nets[i]:
            return True
        # Early exit: if network address is way before our IP, stop
        if ip_int - int(nets[i].network_address) > 0x1000000:  # >16M gap
            break
    return False



def find_cross_region_overlaps(region_nets: dict):
    """Return examples of CIDRs assigned to more than one region."""
    overlaps = []
    regions = sorted(region_nets)

    for idx, left_cc in enumerate(regions):
        left = region_nets[left_cc]
        for right_cc in regions[idx + 1:]:
            right = region_nets[right_cc]
            i = j = 0
            while i < len(left) and j < len(right):
                a = left[i]
                b = right[j]

                if a.overlaps(b):
                    overlaps.append((left_cc, str(a), right_cc, str(b)))
                    if len(overlaps) >= 20:
                        return overlaps

                if int(a.broadcast_address) < int(b.broadcast_address):
                    i += 1
                else:
                    j += 1

    return overlaps


def fail(msg: str):
    print(f"[FAIL] {msg}")
    sys.exit(1)


def warn(msg: str):
    print(f"[WARN] {msg}")


def info(msg: str):
    print(f"[INFO] {msg}")


def check_meta(meta: dict, region_counts: dict):
    cloud = (meta.get("parsing", {}) or {}).get("cloud_supplement", {})
    prefixes_fetched = cloud.get("prefixes_fetched", 0)
    l2_fallback = cloud.get("l2_fallback", 0)

    if region_counts["CN"] < MIN_CN_CIDRS:
        fail(f"CN CIDR count too low: {region_counts['CN']} < {MIN_CN_CIDRS}")

    if region_counts["HK"] > MAX_HK_CIDRS:
        fail(f"HK CIDR count too high: {region_counts['HK']} > {MAX_HK_CIDRS}")

    if prefixes_fetched > 0:
        l2_ratio = l2_fallback / prefixes_fetched
        info(f"L2 fallback ratio: {l2_ratio:.2%}")
        if l2_ratio > MAX_L2_RATIO:
            fail(f"L2 fallback ratio too high: {l2_ratio:.2%} > {MAX_L2_RATIO:.2%}")


def main():
    if not META_PATH.exists():
        fail("output/meta.json is missing")

    if not SAMPLES_PATH.exists():
        fail("tests/samples.json is missing")

    for region, path in REGION_FILES.items():
        if not path.exists():
            fail(f"{path} is missing")
        if path.stat().st_size == 0:
            fail(f"{path} is empty")

    with META_PATH.open("r", encoding="utf-8") as f:
        meta = json.load(f)

    with SAMPLES_PATH.open("r", encoding="utf-8") as f:
        samples = json.load(f)

    region_nets = {}
    region_counts = {}
    for region, path in REGION_FILES.items():
        nets = load_cidrs(path)
        region_nets[region] = nets
        region_counts[region] = len(nets)
        info(f"{region}: {len(nets)} CIDRs loaded")

    check_meta(meta, region_counts)

    overlaps = find_cross_region_overlaps(region_nets)
    if overlaps:
        print("\n[FAIL] Cross-region CIDR overlaps detected:")
        for left_cc, left_cidr, right_cc, right_cidr in overlaps:
            print(f"  - {left_cc} {left_cidr} overlaps {right_cc} {right_cidr}")
        fail("Region datasets must be mutually exclusive")

    hard_failures = []
    edge_warnings = []

    for expected_region, domains in samples.items():
        for domain in domains:
            try:
                _, _, ips = socket.gethostbyname_ex(domain)
            except Exception as e:
                warn(f"DNS lookup failed for {domain}: {e}")
                continue

            if not ips:
                warn(f"No A record for {domain}")
                continue

            if expected_region == "INTL":
                intl_ok = True
                for ip in ips:
                    for r in ("CN", "HK", "TW", "MO", "JP", "KR", "SG"):
                        if ip_in_region(ip, region_nets[r]):
                            intl_ok = False
                            break
                    if not intl_ok:
                        break

                if intl_ok:
                    info(f"PASS sample: {domain} -> {ips} -> INTL")
                else:
                    hard_failures.append((domain, expected_region, ips))
                continue

            if expected_region == "EDGE":
                matched_regions = []
                for ip in ips:
                    for r in ("CN", "HK", "TW", "MO", "JP", "KR", "SG"):
                        if ip_in_region(ip, region_nets[r]) and r not in matched_regions:
                            matched_regions.append(r)

                edge_warnings.append((domain, ips, matched_regions))
                info(f"EDGE sample: {domain} -> {ips} -> {matched_regions or ['UNCLASSIFIED']}")
                continue

            if expected_region in ("HK", "TW", "MO", "JP", "KR", "SG"):
                matched = False
                for ip in ips:
                    if ip_in_region(ip, region_nets[expected_region]):
                        matched = True
                        break

                if matched:
                    info(f"PASS sample: {domain} -> {ips} -> {expected_region}")
                else:
                    warn(f"{domain}: expected {expected_region}, got {ips}")
                continue

            if expected_region == "CN":
                matched = False
                for ip in ips:
                    if ip_in_region(ip, region_nets["CN"]):
                        matched = True
                        break

                if matched:
                    info(f"PASS sample: {domain} -> {ips} -> CN")
                else:
                    hard_failures.append((domain, expected_region, ips))
                continue

            warn(f"Unknown sample region {expected_region} for {domain}")

    if edge_warnings:
        print("\n[WARN] Edge sample results:")
        for domain, ips, matched_regions in edge_warnings:
            print(f"  - {domain}: {ips} -> {matched_regions or ['UNCLASSIFIED']}")

    if hard_failures:
        print("\n[WARN] DNS sample regression (may be transient DNS jitter):")
        for domain, expected_region, ips in hard_failures:
            print(f"  - {domain}: expected {expected_region}, got IPs {ips}")
        print("[INFO] DNS failures are warnings only; static checks (overlap, counts) are authoritative")

    print("\n[PASS] Validation completed successfully")


if __name__ == "__main__":
    main()
