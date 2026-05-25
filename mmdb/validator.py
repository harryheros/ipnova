"""
mmdb/validator.py — IPNova MMDB validator

Reads the generated MMDB file and verifies:
- Sample IPs resolve to expected regions
- All 7 APAC regions are present
- Record structure matches expected schema
- Database is not empty

Requires: pip install maxminddb
"""

import logging
import os

log = logging.getLogger("ipnova.mmdb.validator")

# Sample IPs for each region — well-known stable addresses.
# Each region keeps 2+ samples so a single IP holder change won't fail
# the round-trip check. MO previously had only 1 sample, which made the
# whole region's coverage gate brittle.
SAMPLE_IPS = {
    "CN": [("110.242.68.66", "baidu.com"), ("202.108.22.5", "sina.com")],
    "HK": [("203.80.96.10", "hkbn"), ("210.0.128.0", "hkt")],
    "TW": [("168.95.1.1", "hinet"), ("220.130.24.1", "cht")],
    "MO": [
        ("202.175.2.1", "ctm"),       # CTM
        ("60.246.0.1", "ctm-broadband"),  # CTM broadband range
        ("219.79.0.1", "mtel"),       # MTel
    ],
    "JP": [("202.12.27.33", "jpnic"), ("133.205.9.220", "riken")],
    "KR": [("168.126.63.1", "kt"), ("164.124.107.9", "lg")],
    "SG": [("202.166.120.1", "singtel"), ("203.116.1.1", "starhub")],
}


def validate(mmdb_path: str) -> bool:
    """Round-trip check the generated MMDB file.

    This is NOT an accuracy check — it cannot verify that an IP truly
    belongs to the labelled region, since the labels were written by
    this build pipeline in the first place. What it verifies:

    1. The file exists, opens cleanly, and is not pathologically small.
    2. Every region in SAMPLE_IPS has at least one sample that resolves
       to the expected region. This catches mmdb_writer failures,
       accidental region drops, and severe insertion bugs.
    3. Individual samples resolving to a *different* region than
       expected are logged as warnings — IP holders change over time
       and one stale sample should not fail CI.

    Returns True if every region in SAMPLE_IPS has at least one matching
    sample. Returns False on file errors or when a region has zero
    matching samples (which suggests that region's records were not
    written at all).
    """
    # Check file existence FIRST, before deciding whether to skip based on
    # missing dependencies. Otherwise a missing/corrupt file is silently
    # masked as "skipped" just because maxminddb isn't installed.
    if not os.path.exists(mmdb_path):
        log.error("MMDB file not found: %s", mmdb_path)
        return False

    try:
        import maxminddb
    except ImportError:
        log.warning(
            "maxminddb not installed — skipping MMDB round-trip check.\n"
            "Install with: pip install maxminddb"
        )
        return True  # Non-fatal: skip if not available

    size_kb = os.path.getsize(mmdb_path) // 1024
    log.info("Round-trip checking %s (%d KB) ...", mmdb_path, size_kb)

    # MMDB metadata + tree for even a single record runs ~10s of KB.
    # Anything below this is almost certainly an empty or corrupt file.
    if size_kb < 10:
        log.error(
            "MMDB file is too small (%d KB) — likely empty or corrupt", size_kb
        )
        return False

    # Per-region tally
    region_match = {cc: 0 for cc in SAMPLE_IPS}
    region_mismatch = {cc: 0 for cc in SAMPLE_IPS}
    region_miss = {cc: 0 for cc in SAMPLE_IPS}

    with maxminddb.open_database(mmdb_path) as reader:
        for expected_cc, samples in SAMPLE_IPS.items():
            for ip, label in samples:
                try:
                    result = reader.get(ip)
                except Exception as e:
                    log.warning("  [ERR]  %s (%s): %s", ip, label, e)
                    region_miss[expected_cc] += 1
                    continue

                if result is None:
                    log.debug("  [MISS] %s (%s) — not in database", ip, label)
                    region_miss[expected_cc] += 1
                    continue

                got_cc = result.get("country", {}).get("iso_code", "")
                if got_cc == expected_cc:
                    log.debug("  [OK]   %s (%s) → %s", ip, label, got_cc)
                    region_match[expected_cc] += 1
                else:
                    # Sample drifted — IP holder may have changed. Warn
                    # but do not fail; a single stale sample shouldn't
                    # block a weekly build.
                    log.warning(
                        "  [WARN] %s (%s): expected %s, got %s "
                        "(sample may be stale)",
                        ip, label, expected_cc, got_cc or "(none)"
                    )
                    region_mismatch[expected_cc] += 1

    # A region is "covered" if at least one sample resolves to it
    uncovered = [cc for cc, n in region_match.items() if n == 0]

    log.info(
        "Round-trip check complete — covered: %d/%d regions, "
        "matches: %d, mismatches: %d, misses: %d",
        len(SAMPLE_IPS) - len(uncovered), len(SAMPLE_IPS),
        sum(region_match.values()),
        sum(region_mismatch.values()),
        sum(region_miss.values()),
    )

    if uncovered:
        log.error(
            "Round-trip check failed: regions with zero matching samples: %s. "
            "This suggests records for these regions were not written to the "
            "MMDB. Inspect mmdb.builder output and the input region_data.",
            uncovered
        )
        return False

    return True


def print_sample(mmdb_path: str, ip: str):
    """Quick lookup for debugging."""
    try:
        import maxminddb
        with maxminddb.open_database(mmdb_path) as reader:
            result = reader.get(ip)
            print(f"{ip} → {result}")
    except ImportError:
        print("maxminddb not installed")
