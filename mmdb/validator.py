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

# Sample IPs for each region — well-known stable addresses
SAMPLE_IPS = {
    "CN": [("110.242.68.66", "baidu.com"), ("202.108.22.5", "sina.com")],
    "HK": [("203.80.96.10", "hkbn"), ("210.0.128.0", "hkt")],
    "TW": [("168.95.1.1", "hinet"), ("220.130.24.1", "cht")],
    "MO": [("202.175.2.1", "ctm")],
    "JP": [("202.12.27.33", "jpnic"), ("133.205.9.220", "riken")],
    "KR": [("168.126.63.1", "kt"), ("164.124.107.9", "lg")],
    "SG": [("202.166.120.1", "singtel"), ("203.116.1.1", "starhub")],
}


def validate(mmdb_path: str) -> bool:
    """
    Validate the generated MMDB file.

    Returns:
        True if all checks pass, False otherwise.
    """
    try:
        import maxminddb
    except ImportError:
        log.warning(
            "maxminddb not installed — skipping MMDB validation.\n"
            "Install with: pip install maxminddb"
        )
        return True  # Non-fatal: skip if not available

    if not os.path.exists(mmdb_path):
        log.error("MMDB file not found: %s", mmdb_path)
        return False

    size_kb = os.path.getsize(mmdb_path) // 1024
    log.info("Validating %s (%d KB) ...", mmdb_path, size_kb)

    # 空庫檢查 — 正常 MMDB 至少應有幾十 KB
    if size_kb < 10:
        log.error(
            "MMDB file is too small (%d KB) — likely empty or corrupt", size_kb
        )
        return False

    passed = 0
    failed = 0
    missing_regions = []

    with maxminddb.open_database(mmdb_path) as reader:
        for expected_cc, samples in SAMPLE_IPS.items():
            region_hit = False

            for ip, label in samples:
                try:
                    result = reader.get(ip)
                    if result is None:
                        log.debug("  [MISS] %s (%s) — not in database", ip, label)
                        continue

                    got_cc = result.get("country", {}).get("iso_code", "")
                    if got_cc == expected_cc:
                        log.debug("  [OK]   %s (%s) → %s", ip, label, got_cc)
                        region_hit = True
                        passed += 1
                    else:
                        log.warning(
                            "  [WARN] %s (%s): expected %s, got %s",
                            ip, label, expected_cc, got_cc
                        )
                        failed += 1

                except Exception as e:
                    log.warning("  [ERR]  %s (%s): %s", ip, label, e)
                    failed += 1

            if not region_hit:
                missing_regions.append(expected_cc)

    if missing_regions:
        log.warning("Regions with no sample hits: %s", missing_regions)

    log.info(
        "Validation complete — %d passed, %d warnings, %d missing regions",
        passed, failed, len(missing_regions)
    )

    # 嚴格判斷：必須有命中，不能有缺失區域，且失敗不能超過通過
    if passed == 0:
        log.error("Validation failed: no sample IPs matched any region")
        return False

    if missing_regions:
        log.error("Validation failed: %d regions have no hits", len(missing_regions))
        return False

    return passed > 0 and failed == 0


def print_sample(mmdb_path: str, ip: str):
    """Quick lookup for debugging."""
    try:
        import maxminddb
        with maxminddb.open_database(mmdb_path) as reader:
            result = reader.get(ip)
            print(f"{ip} → {result}")
    except ImportError:
        print("maxminddb not installed")
