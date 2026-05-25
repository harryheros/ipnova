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
    # v3.2: cidr_objects provenance (apnic when no bgp_provenance supplied)
    assert normalized["CN"]["cidr_objects"][0]["cidr"] == "1.0.1.0/24"
    assert normalized["CN"]["cidr_objects"][0]["source"] == "apnic"
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
        assert data["schema_version"] == "3.2"
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


def test_enforce_apnic_authoritative_over_supp():
    """APNIC results must not be displaced by overlapping BGP supplement.

    Scenario: APNIC assigns 1.0.0.0/24 to HK. A misclassified cloud ASN
    BGP-announces 1.0.0.0/22 and the supplement pipeline labels it CN.
    The new layered enforce must keep HK's 1.0.0.0/24 intact and only
    grant CN the non-overlapping remainder (1.0.1.0/24 + 1.0.2.0/23).
    """
    import ipaddress as ip
    region_data = {
        "HK": [ip.ip_network("1.0.0.0/24")],
    }
    supp_data = {
        "CN": [ip.ip_network("1.0.0.0/22")],
    }
    out = generate_ip_list.enforce_mutual_exclusivity(region_data, supp_data=supp_data)

    hk_cidrs = {str(n) for n in out["HK"]}
    cn_cidrs = {str(n) for n in out["CN"]}

    assert "1.0.0.0/24" in hk_cidrs, "APNIC HK assignment must survive"
    assert "1.0.0.0/24" not in cn_cidrs, "BGP supp must not eat APNIC HK block"
    assert cn_cidrs == {"1.0.1.0/24", "1.0.2.0/23"}, (
        f"CN should fill the gap, got {cn_cidrs}"
    )


def test_enforce_supp_none_backward_compat():
    """Calling enforce without supp_data must behave like the original.

    No supp means existing APNIC-only path; output should still be mutually
    exclusive and identical to passing supp_data=None.
    """
    import ipaddress as ip
    region_data = {
        "CN": [ip.ip_network("1.0.0.0/22")],
        "HK": [ip.ip_network("1.0.0.0/24")],
    }
    out_none = generate_ip_list.enforce_mutual_exclusivity(region_data)
    out_explicit = generate_ip_list.enforce_mutual_exclusivity(region_data, supp_data=None)

    assert {cc: [str(n) for n in nets] for cc, nets in out_none.items()} == \
           {cc: [str(n) for n in nets] for cc, nets in out_explicit.items()}


def test_http_get_ripe_throttle():
    """Two successive RIPE Stat calls must be at least RIPE_REQUEST_INTERVAL apart.

    Patches urlopen with a fake response; measures wall-clock between calls.
    A non-RIPE URL must not be throttled. URLs that merely contain
    'stat.ripe.net' in their query string must NOT be classified as RIPE.
    """
    import time
    import urllib.request

    g = generate_ip_list

    # ---- 1. Pure hostname classification (no network calls) ----
    assert g._is_ripe_host("https://stat.ripe.net/data/x") is True
    assert g._is_ripe_host("https://STAT.RIPE.NET/data/x") is True  # case-insensitive
    assert g._is_ripe_host("https://api.stat.ripe.net/x") is True   # subdomain
    assert g._is_ripe_host("https://evil.com/?ref=stat.ripe.net") is False
    assert g._is_ripe_host("https://stat.ripe.net.evil.com/x") is False  # not a real RIPE subdomain
    assert g._is_ripe_host("https://ftp.apnic.net/x") is False
    assert g._is_ripe_host("not-a-url") is False

    # ---- 2. Throttle timing via patched urlopen ----
    # Reset throttle state to make the test deterministic regardless of order
    g._RIPE_LAST_CALL = 0.0

    class _FakeResp:
        def __init__(self, body=b'{"data":{"prefixes":[]}}', content_type="application/json"):
            self._body = body
            self.headers = {"Content-Type": content_type}
        def read(self):
            return self._body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        return _FakeResp()

    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        # Two RIPE calls back-to-back: second must be delayed
        t0 = time.monotonic()
        g.http_get("https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS1")
        t1 = time.monotonic()
        g.http_get("https://stat.ripe.net/data/geoloc/data.json?resource=1.0.0.0/24")
        t2 = time.monotonic()

        # First call should be roughly instant (no prior RIPE call this test run)
        assert (t1 - t0) < 0.5, f"first RIPE call delayed unexpectedly: {t1 - t0:.2f}s"
        # Second call should be delayed close to RIPE_REQUEST_INTERVAL
        gap = t2 - t1
        assert gap >= g.RIPE_REQUEST_INTERVAL - 0.05, (
            f"second RIPE call gap {gap:.2f}s < RIPE_REQUEST_INTERVAL "
            f"{g.RIPE_REQUEST_INTERVAL}s"
        )

        # Non-RIPE URL must NOT be throttled even when _RIPE_LAST_CALL is fresh
        g._RIPE_LAST_CALL = time.monotonic()
        t3 = time.monotonic()
        g.http_get("https://ftp.apnic.net/stats/apnic/delegated-apnic-latest",
                   strict_decode=False)
        t4 = time.monotonic()
        assert (t4 - t3) < 0.5, f"non-RIPE call wrongly throttled: {t4 - t3:.2f}s"

        # URL whose query string contains 'stat.ripe.net' must NOT be throttled
        g._RIPE_LAST_CALL = time.monotonic()
        t5 = time.monotonic()
        g.http_get("https://example.com/x?ref=stat.ripe.net")
        t6 = time.monotonic()
        assert (t6 - t5) < 0.5, (
            f"spoofed URL wrongly throttled: {t6 - t5:.2f}s "
            "(host classification must use urlparse hostname, not substring)"
        )
    finally:
        urllib.request.urlopen = original
        g._RIPE_LAST_CALL = 0.0


def test_mmdb_validator_roundtrip_semantics():
    """MMDB validator should: pass when every region has at least one match,
    tolerate individual stale samples (warn but pass), fail when any region
    has zero matching samples, and fail on pathologically small files.
    """
    import os
    import sys
    import tempfile
    import types

    # Inject fake maxminddb so the test works without the real dep installed
    fake_mmdb = types.ModuleType("maxminddb")

    class _FakeReader:
        def __init__(self, mapping):
            self._m = mapping
        def get(self, ip):
            return self._m.get(ip)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    _mapping = {}

    def open_database(path):
        return _FakeReader(_mapping)

    fake_mmdb.open_database = open_database
    sys.modules['maxminddb'] = fake_mmdb

    # Force fresh import of validator so it picks up the injected fake
    for m in list(sys.modules):
        if m.startswith('mmdb'):
            del sys.modules[m]
    mmdb_root = str(ROOT)
    if mmdb_root not in sys.path:
        sys.path.insert(0, mmdb_root)
    from mmdb.validator import validate, SAMPLE_IPS

    def good(cc):
        return {"country": {"iso_code": cc, "names": {"en": cc}}}

    def write_temp(size_kb):
        fd, path = tempfile.mkstemp(suffix=".mmdb")
        os.write(fd, b"X" * (size_kb * 1024))
        os.close(fd)
        return path

    # 1) Happy path
    _mapping.clear()
    for cc, samples in SAMPLE_IPS.items():
        for ip, _ in samples:
            _mapping[ip] = good(cc)
    p = write_temp(50)
    try:
        assert validate(p) is True, "happy path should pass"
    finally:
        os.unlink(p)

    # 2) Individual stale sample: one mismatch in a region that has other matches
    _mapping.clear()
    for cc, samples in SAMPLE_IPS.items():
        for i, (ip, _) in enumerate(samples):
            if cc == "CN" and i == 1:
                _mapping[ip] = good("US")  # drifted
            else:
                _mapping[ip] = good(cc)
    p = write_temp(50)
    try:
        assert validate(p) is True, "single stale sample should warn but pass"
    finally:
        os.unlink(p)

    # 3) Whole region missing
    _mapping.clear()
    for cc, samples in SAMPLE_IPS.items():
        for ip, _ in samples:
            _mapping[ip] = None if cc == "CN" else good(cc)
    p = write_temp(50)
    try:
        assert validate(p) is False, "missing region should fail"
    finally:
        os.unlink(p)

    # 4) File too small
    p = write_temp(5)
    try:
        assert validate(p) is False, "tiny file should fail"
    finally:
        os.unlink(p)


def test_regions_single_source_of_truth():
    """regions.TARGET_REGIONS must be the same object referenced everywhere.

    Drift between generate_ip_list.TARGET_REGIONS and mmdb.schema.APAC_REGIONS
    used to be possible because both were defined independently. Now both
    must point at regions.TARGET_REGIONS.
    """
    import sys
    # Ensure project root is importable
    mmdb_root = str(ROOT)
    if mmdb_root not in sys.path:
        sys.path.insert(0, mmdb_root)

    import regions
    from mmdb import schema as mmdb_schema

    # Identity check (same object, not just equal contents) — guarantees
    # any future edit goes through regions.py.
    assert generate_ip_list.TARGET_REGIONS is regions.TARGET_REGIONS, (
        "generate_ip_list.TARGET_REGIONS is not regions.TARGET_REGIONS"
    )
    assert mmdb_schema.APAC_REGIONS is regions.TARGET_REGIONS, (
        "mmdb.schema.APAC_REGIONS is not regions.TARGET_REGIONS"
    )
    # And mmdb_schema also re-exports the original name
    assert mmdb_schema.TARGET_REGIONS is regions.TARGET_REGIONS


def test_user_agent_derives_from_version():
    """USER_AGENT must always include __version__ and the repo URL.

    Prevents the previous bug where the UA string was hardcoded to
    'ipnova-bot/3.2' and drifted from __version__ as the project
    bumped to 3.2.1.
    """
    g = generate_ip_list
    assert g.__version__ in g.USER_AGENT, (
        f"USER_AGENT {g.USER_AGENT!r} must contain __version__ "
        f"{g.__version__!r}"
    )
    assert "github.com/harryheros/ipnova" in g.USER_AGENT, (
        "USER_AGENT must include repo URL for contactability"
    )
    assert g.USER_AGENT.startswith("ipnova/"), (
        "UA must start with project name + version, not legacy '-bot' suffix"
    )


def test_canary_cidrs_well_formed():
    """Each region must have exactly one canary CIDR from RFC5737 test ranges.

    RFC5737 reserves 192.0.2.0/24, 198.51.100.0/24, and 203.0.113.0/24 for
    documentation; these ranges are guaranteed never to route on the public
    Internet, making them safe to embed in published artifacts.
    """
    import ipaddress as ip
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import regions

    rfc5737 = [
        ip.ip_network("192.0.2.0/24"),
        ip.ip_network("198.51.100.0/24"),
        ip.ip_network("203.0.113.0/24"),
    ]

    canaries = regions.canary_networks()
    # Every target region must have a canary
    assert set(canaries.keys()) == set(regions.TARGET_REGIONS.keys()), (
        "canary regions must match TARGET_REGIONS exactly"
    )

    # Each canary must live inside an RFC5737 documentation block
    for cc, canary in canaries.items():
        inside = any(canary.subnet_of(test_net) for test_net in rfc5737)
        assert inside, (
            f"canary for {cc} = {canary} is NOT inside any RFC5737 "
            f"documentation range; this would risk colliding with real "
            f"public addresses"
        )

    # All canaries must be mutually exclusive (no two regions share a canary)
    canary_list = list(canaries.values())
    for i, a in enumerate(canary_list):
        for b in canary_list[i + 1:]:
            assert not a.overlaps(b), (
                f"canary overlap detected: {a} overlaps {b}"
            )


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
    test_enforce_apnic_authoritative_over_supp()
    print("  test_enforce_apnic_authoritative_over_supp: PASS")
    test_enforce_supp_none_backward_compat()
    print("  test_enforce_supp_none_backward_compat: PASS")
    test_http_get_ripe_throttle()
    print("  test_http_get_ripe_throttle: PASS")
    test_mmdb_validator_roundtrip_semantics()
    print("  test_mmdb_validator_roundtrip_semantics: PASS")
    test_regions_single_source_of_truth()
    print("  test_regions_single_source_of_truth: PASS")
    test_user_agent_derives_from_version()
    print("  test_user_agent_derives_from_version: PASS")
    test_canary_cidrs_well_formed()
    print("  test_canary_cidrs_well_formed: PASS")
    print("\nAll offline tests passed.")
