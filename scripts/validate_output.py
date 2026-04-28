#!/usr/bin/env python3
import json
import socket
import sys
import ipaddress
from pathlib import Path

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
    return nets


def ip_in_region(ip: str, nets):
    ip_obj = ipaddress.ip_address(ip)
    return any(ip_obj in net for net in nets)


def fail(msg: str):
    print(f"[FAIL] {msg}")
    sys.exit(1)


def warn(msg: str):
    print(f"[WARN] {msg}")


def info(msg: str):
    print(f"[INFO] {msg}")


def check_meta(meta: dict, region_counts: dict):
    cloud = meta.get("cloud_supplement", {})
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
        print("\n[FAIL] Sample regression failures:")
        for domain, expected_region, ips in hard_failures:
            print(f"  - {domain}: expected {expected_region}, got IPs {ips}")
        sys.exit(1)

    print("\n[PASS] Validation completed successfully")


if __name__ == "__main__":
    main()
