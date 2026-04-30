#!/usr/bin/env python3
"""Lightweight offline checks for core IPNova transformations."""

import importlib.util
import ipaddress
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("generate_ip_list", ROOT / "generate_ip_list.py")
generate_ip_list = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_ip_list)


def test_parse_normalize_and_write_outputs():
    raw_data = "\n".join([
        "2|apnic|20260429|1|1|summary",
        "apnic|CN|ipv4|1.0.1.0|256|20200101|allocated",
        "apnic|HK|ipv4|1.0.2.0|256|20200101|assigned",
        "apnic|JP|ipv4|1.0.3.0|256|20200101|allocated",
        "apnic|US|ipv4|8.8.8.0|256|20200101|allocated",
        "apnic|CN|ipv4|1.1.1.0|256|20200101|allocated",
    ])
    excluded = [ipaddress.ip_network("1.1.1.0/24")]

    region_data, parse_stats = generate_ip_list.parse_and_cleanse(raw_data, excluded)
    normalized = generate_ip_list.normalize_region_data(region_data)

    assert normalized["CN"]["cidrs"] == ["1.0.1.0/24"]
    assert normalized["HK"]["cidrs"] == ["1.0.2.0/24"]
    assert normalized["JP"]["cidrs"] == ["1.0.3.0/24"]
    assert normalized["SG"]["cidrs"] == []
    assert parse_stats["excluded_source_networks"] == 1

    with tempfile.TemporaryDirectory() as tmpdir:
        asn_report = {
            "mode": "static_only",
            "succeeded": [],
            "failed": [],
            "total_prefixes": 0,
        }
        generate_ip_list.save_txt_outputs(normalized, tmpdir)
        generate_ip_list.save_json_outputs(normalized, asn_report, parse_stats, tmpdir)

        data = json.loads((Path(tmpdir) / "data.json").read_text())
        meta = json.loads((Path(tmpdir) / "meta.json").read_text())
        assert data["schema_version"] == "3.1"
        assert meta["checksum"]["data_json_sha256"]
        assert "Japan" in (Path(tmpdir) / "JP.txt").read_text()


def test_subtract_excluded_precision():
    """Verify surgical exclusion: only the excluded subnet is removed."""
    net = ipaddress.ip_network("1.0.0.0/22")
    excluded = sorted(
        ipaddress.collapse_addresses([ipaddress.ip_network("1.0.1.0/24")]),
        key=lambda n: int(n.network_address),
    )
    result = generate_ip_list.subtract_excluded_from_network(net, excluded)
    result_set = set(str(n) for n in result)

    assert "1.0.0.0/24" in result_set, "1.0.0.0/24 should be kept"
    assert "1.0.2.0/23" in result_set, "1.0.2.0/23 should be kept"
    assert not any("1.0.1" in s for s in result_set), "1.0.1.0/24 should be excluded"


def test_normalize_region_data_collapse():
    """Verify that adjacent CIDRs are collapsed into supernets."""
    region_data = {
        "CN": [
            ipaddress.ip_network("10.0.0.0/25"),
            ipaddress.ip_network("10.0.0.128/25"),
        ]
    }
    normalized = generate_ip_list.normalize_region_data(region_data)
    # Two adjacent /25 should collapse into one /24
    assert normalized["CN"]["cidrs"] == ["10.0.0.0/24"]
    assert normalized["CN"]["total_cidrs"] == 1
    assert normalized["CN"]["total_ips"] == 256


def test_sanity_check_passes():
    """Verify sanity check passes when all regions meet thresholds."""
    normalized = {}
    for cc, threshold in generate_ip_list.SANITY_THRESHOLDS.items():
        normalized[cc] = {
            "total_cidrs": threshold + 100,
            "total_ips": (threshold + 100) * 256,
            "cidrs": [],
            "region_code": cc,
            "region_name": cc,
        }
    # Should not raise
    generate_ip_list.sanity_check(normalized)


def test_sanity_check_fails():
    """Verify sanity check raises RuntimeError when a region is too small."""
    import sys
    normalized = {}
    for cc, threshold in generate_ip_list.SANITY_THRESHOLDS.items():
        normalized[cc] = {
            "total_cidrs": threshold + 100,
            "total_ips": 0,
            "cidrs": [],
            "region_code": cc,
            "region_name": cc,
        }
    # Force CN below threshold
    normalized["CN"]["total_cidrs"] = 1
    try:
        generate_ip_list.sanity_check(normalized)
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "CN" in str(e)


def test_forbidden_asns_not_in_cloud_asns():
    """FORBIDDEN_ASNS must not overlap with CN_CLOUD_ASNS."""
    overlap = set(generate_ip_list.FORBIDDEN_ASNS) & set(generate_ip_list.CN_CLOUD_ASNS)
    assert not overlap, f"FORBIDDEN_ASNS overlap with CN_CLOUD_ASNS: {overlap}"


def test_target_regions_complete():
    """All 7 APAC regions must be present."""
    expected = {"CN", "HK", "TW", "MO", "JP", "KR", "SG"}
    assert set(generate_ip_list.TARGET_REGIONS.keys()) == expected


if __name__ == "__main__":
    test_parse_normalize_and_write_outputs()
    print("  test_parse_normalize_and_write_outputs: PASS")
    test_subtract_excluded_precision()
    print("  test_subtract_excluded_precision: PASS")
    test_normalize_region_data_collapse()
    print("  test_normalize_region_data_collapse: PASS")
    test_sanity_check_passes()
    print("  test_sanity_check_passes: PASS")
    test_sanity_check_fails()
    print("  test_sanity_check_fails: PASS")
    test_forbidden_asns_not_in_cloud_asns()
    print("  test_forbidden_asns_not_in_cloud_asns: PASS")
    test_target_regions_complete()
    print("  test_target_regions_complete: PASS")
    print("\nAll offline tests passed.")
