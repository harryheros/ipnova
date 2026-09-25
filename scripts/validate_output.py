#!/usr/bin/env python3
"""
validate_output.py — post-build validation for IPNova outputs.

Hard gates (exit 1):
  - required files present and non-empty
  - data.json SHA-256 matches meta.json checksum
  - every <CC>.txt matches data.json's CIDR list exactly
  - CN count >= sanity threshold, HK count <= MAX_HK_CIDRS
  - no cross-region CIDR overlap

Soft signals (warnings only):
  - L2 fallback ratio, RIPE circuit breaker state
  - DNS sample regressions (DNS answers jitter; never block a publish)

Usage:
    python3 scripts/validate_output.py [--output-dir output] [--skip-dns]
"""
import argparse
import bisect
import concurrent.futures
import hashlib
import ipaddress
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from regions import TARGET_REGIONS  # noqa: E402

TESTS_DIR = ROOT / "tests"
SAMPLES_PATH = TESTS_DIR / "samples.json"

# Filled in by configure(); kept as module globals for backward compatibility.
OUTPUT_DIR = ROOT / "output"
META_PATH = OUTPUT_DIR / "meta.json"
REGION_FILES = {cc: OUTPUT_DIR / f"{cc}.txt" for cc in TARGET_REGIONS}

# socket.gethostbyname_ex() ignores socket.setdefaulttimeout(), so v3.4 could
# stall for the resolver's own timeout per domain, serially. Lookups now run
# in a thread pool with a hard per-lookup deadline.
DNS_TIMEOUT_SECONDS = 8
DNS_WORKERS = 16


def configure(output_dir):
    global OUTPUT_DIR, META_PATH, REGION_FILES
    OUTPUT_DIR = Path(output_dir).resolve()
    META_PATH = OUTPUT_DIR / "meta.json"
    REGION_FILES = {cc: OUTPUT_DIR / f"{cc}.txt" for cc in TARGET_REGIONS}

# L2 fallback ratio threshold.
# Postmortem 5.2 measured the healthy baseline at ~0.6% (32 / 5745 prefixes).
# Anything beyond a few percent indicates L1 (RIPEstat geoloc) is degraded
# and prefixes are silently falling back to "ASN holder country", which
# over-attributes overseas regions of CN cloud ASNs to CN. This is a
# health signal, not a correctness gate — we warn loudly but do not fail
# the build so transient RIPEstat hiccups don't block weekly publishes.
# Real correctness gates are MIN_CN_CIDRS, MAX_HK_CIDRS, and cross-region
# overlap detection, all of which still fail.
MAX_L2_RATIO = 0.10
_NETWORK_KEYS = {}
# HK's APNIC allocation is naturally small and stable around the low
# thousands. A sudden jump beyond MAX_HK_CIDRS suggests an upstream
# anomaly: either APNIC re-classified large blocks, the BGP supplement
# is mis-attributing prefixes (e.g. CN cloud overseas regions leaking
# into HK), or the build pipeline collapse logic regressed. Set above
# the historical maximum with comfortable headroom; revisit only if
# real HK allocations grow past this.
MAX_HK_CIDRS = 5000

# Load SANITY_THRESHOLDS from generate_ip_list.py so MIN_CN_CIDRS shares a
# single source of truth with the build script.
import generate_ip_list as _gen  # noqa: E402

MIN_CN_CIDRS = _gen.SANITY_THRESHOLDS["CN"]  # single source of truth


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

    The previous heuristic early-exit (gap > 16M addresses) could produce
    false negatives for sparsely-allocated cloud BGP blocks that are far
    apart in address space. Replaced with a correct bisect-based approach:
    find the rightmost network whose network_address <= ip_int, then check
    backwards until the network cannot possibly contain ip_int.
    """
    ip_obj = ipaddress.ip_address(ip)
    ip_int = int(ip_obj)
    keys = _NETWORK_KEYS.get(id(nets))
    if keys is None:
        keys = [int(n.network_address) for n in nets]
        _NETWORK_KEYS[id(nets)] = keys
    # Find the rightmost candidate: all nets with network_address <= ip_int
    idx = bisect.bisect_right(keys, ip_int) - 1
    # Walk backwards — stop as soon as the broadcast_address is below ip_int
    while idx >= 0:
        net = nets[idx]
        if int(net.broadcast_address) < ip_int:
            break  # this net and all earlier ones cannot contain ip_int
        if ip_obj in net:
            return True
        idx -= 1
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


def check_integrity(meta: dict, region_nets: dict):
    """data.json must match meta.json's checksum and every <CC>.txt."""
    data_path = OUTPUT_DIR / "data.json"
    if not data_path.exists():
        fail(f"{data_path} is missing")

    raw = data_path.read_bytes()
    expected = (meta.get("checksum") or {}).get("data_json_sha256")
    actual = hashlib.sha256(raw).hexdigest()
    if not expected:
        fail("meta.json has no checksum.data_json_sha256")
    if actual != expected:
        fail(f"data.json sha256 {actual[:16]}... != meta.json {expected[:16]}...")
    info("data.json checksum matches meta.json")

    data = json.loads(raw.decode("utf-8"))
    regions = data.get("regions") or {}
    for cc, nets in region_nets.items():
        payload = regions.get(cc)
        if payload is None:
            fail(f"data.json has no region {cc}")
        txt_list = [str(n) for n in nets]
        json_list = [str(ipaddress.ip_network(c)) for c in payload.get("cidrs", [])]
        json_list.sort(key=lambda c: int(ipaddress.ip_network(c).network_address))
        if txt_list != json_list:
            fail(f"{cc}.txt ({len(txt_list)} CIDRs) does not match data.json "
                 f"({len(json_list)} CIDRs)")
        if payload.get("total_cidrs") != len(json_list):
            fail(f"data.json {cc}.total_cidrs={payload.get('total_cidrs')} "
                 f"but cidrs has {len(json_list)} entries")
        objs = payload.get("cidr_objects")
        if objs is not None and [o.get("cidr") for o in objs] != payload.get("cidrs"):
            fail(f"data.json {cc}.cidr_objects is out of sync with cidrs")
    info("Region TXT files match data.json")


def check_meta(meta: dict, region_counts: dict):
    ripe = (meta.get("build", {}) or {}).get("ripe") or {}
    if ripe.get("breaker_tripped"):
        warn("RIPE circuit breaker tripped during the build — cloud supplement "
             "and/or exclusion data may be incomplete.")

    # cloud_supplement is null / {"skipped": true} for --skip-ripe builds
    cloud = (meta.get("parsing") or {}).get("cloud_supplement") or {}
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
            warn(
                f"L2 fallback ratio {l2_ratio:.2%} exceeds healthy threshold "
                f"{MAX_L2_RATIO:.2%}. RIPEstat geoloc (L1) may be degraded; "
                f"cloud-ASN prefixes are falling back to holder-country "
                f"attribution, which can over-assign overseas regions to CN. "
                f"Inspect meta.json cloud_supplement counters."
            )


def resolve_all(domains):
    """Resolve domains concurrently. Returns {domain: list[ip] | Exception}."""
    results = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=DNS_WORKERS)
    try:
        futures = {pool.submit(socket.gethostbyname_ex, d): d for d in domains}
        done, pending = concurrent.futures.wait(futures, timeout=DNS_TIMEOUT_SECONDS)
        for fut in done:
            d = futures[fut]
            try:
                results[d] = fut.result()[2]
            except OSError as e:
                results[d] = e
        for fut in pending:
            results[futures[fut]] = TimeoutError(
                f"lookup exceeded {DNS_TIMEOUT_SECONDS}s")
    finally:
        # Don't wait for stuck resolver threads; they are daemonic enough to
        # be abandoned at interpreter exit.
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def matched_regions(ips, region_nets):
    found = []
    for ip in ips:
        for r in TARGET_REGIONS:
            if r not in found and ip_in_region(ip, region_nets[r]):
                found.append(r)
    return found


def check_dns_samples(samples, region_nets):
    all_domains = sorted({d for ds in samples.values() for d in ds})
    resolved = resolve_all(all_domains)

    hard_failures = []
    edge_warnings = []

    for expected_region, domains in samples.items():
        for domain in domains:
            ips = resolved.get(domain)
            if isinstance(ips, Exception):
                warn(f"DNS lookup failed for {domain}: {ips}")
                continue
            if not ips:
                warn(f"No A record for {domain}")
                continue

            regions_hit = matched_regions(ips, region_nets)

            if expected_region == "INTL":
                if not regions_hit:
                    info(f"PASS sample: {domain} -> {ips} -> INTL")
                else:
                    hard_failures.append((domain, expected_region, ips))
            elif expected_region == "EDGE":
                edge_warnings.append((domain, ips, regions_hit))
                info(f"EDGE sample: {domain} -> {ips} -> {regions_hit or ['UNCLASSIFIED']}")
            elif expected_region in TARGET_REGIONS:
                if expected_region in regions_hit:
                    info(f"PASS sample: {domain} -> {ips} -> {expected_region}")
                elif expected_region == "CN":
                    hard_failures.append((domain, expected_region, ips))
                else:
                    warn(f"{domain}: expected {expected_region}, got {ips}")
            else:
                warn(f"Unknown sample region {expected_region} for {domain}")

    if edge_warnings:
        print("\n[WARN] Edge sample results:")
        for domain, ips, hit in edge_warnings:
            print(f"  - {domain}: {ips} -> {hit or ['UNCLASSIFIED']}")

    if hard_failures:
        print("\n[WARN] DNS sample regression (may be transient DNS jitter):")
        for domain, expected_region, ips in hard_failures:
            print(f"  - {domain}: expected {expected_region}, got IPs {ips}")
        print("[INFO] DNS failures are warnings only; static checks (overlap, counts) are authoritative")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="validate_output",
        description="Validate IPNova build outputs",
    )
    parser.add_argument("-o", "--output-dir", default=str(ROOT / "output"),
                        help="Output directory to validate (default: output)")
    parser.add_argument("--skip-dns", action="store_true",
                        help="Skip live DNS sample checks (offline use)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    configure(args.output_dir)

    if not META_PATH.exists():
        fail(f"{META_PATH} is missing")

    if not args.skip_dns and not SAMPLES_PATH.exists():
        fail("tests/samples.json is missing")

    for region, path in REGION_FILES.items():
        if not path.exists():
            fail(f"{path} is missing")
        if path.stat().st_size == 0:
            fail(f"{path} is empty")

    with META_PATH.open("r", encoding="utf-8") as f:
        meta = json.load(f)

    region_nets = {}
    region_counts = {}
    for region, path in REGION_FILES.items():
        nets = load_cidrs(path)
        region_nets[region] = nets
        region_counts[region] = len(nets)
        info(f"{region}: {len(nets)} CIDRs loaded")

    check_integrity(meta, region_nets)
    check_meta(meta, region_counts)

    overlaps = find_cross_region_overlaps(region_nets)
    if overlaps:
        print("\n[FAIL] Cross-region CIDR overlaps detected:")
        for left_cc, left_cidr, right_cc, right_cidr in overlaps:
            print(f"  - {left_cc} {left_cidr} overlaps {right_cc} {right_cidr}")
        fail("Region datasets must be mutually exclusive")

    if args.skip_dns:
        info("DNS sample checks skipped (--skip-dns)")
    else:
        with SAMPLES_PATH.open("r", encoding="utf-8") as f:
            samples = json.load(f)
        check_dns_samples(samples, region_nets)

    print("\n[PASS] Validation completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
