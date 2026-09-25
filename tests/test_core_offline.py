#!/usr/bin/env python3
"""Lightweight offline checks for core IPNova transformations.

Run with either:
    python -m pytest -q tests/
    python tests/test_core_offline.py      # no pytest required
"""

import ipaddress
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import as a normal module so every test (and helper modules such as
# scripts/validate_output.py) shares one instance and its global state.
import generate_ip_list  # noqa: E402


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
        assert data["schema_version"] == generate_ip_list.SCHEMA_VERSION
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
    saved_modules = {k: v for k, v in sys.modules.items()
                     if k == "maxminddb" or k.startswith("mmdb")}
    sys.modules['maxminddb'] = fake_mmdb
    try:
        _run_validator_cases(_mapping)
    finally:
        # Restore the real modules so later tests are not polluted by the fake.
        for k in [k for k in sys.modules if k == "maxminddb" or k.startswith("mmdb")]:
            del sys.modules[k]
        sys.modules.update(saved_modules)


def _run_validator_cases(_mapping):
    import os
    import tempfile

    # Force fresh import of validator so it picks up the injected fake
    for m in list(sys.modules):
        if m.startswith('mmdb'):
            del sys.modules[m]
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


def test_provenance_survives_collapse_and_level_confidence():
    """Regression guard for the v3.3 provenance fix.

    Two bugs were fixed:
      (A) BGP supplement prefixes whose CIDR string changed via collapse/trim
          were silently mislabelled source="apnic" (string-match lookup miss).
      (B) confidence was hardcoded "high" for every prefix, so L2 (weakest,
          ASN-holder-country guess) prefixes were advertised as high.

    The fix matches provenance by IP-range intersection (survives collapse)
    and maps level -> confidence (L0/L-1 high, L1 medium, L2 low). This test
    must keep passing or the bugs have regressed.
    """
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import generate_ip_list as gen
    net = ipaddress.ip_network

    region_data = {cc: [] for cc in gen.TARGET_REGIONS}
    # 8.152.0.0/15 + 8.154.0.0/15 collapse into 8.152.0.0/14 (string changes)
    region_data["CN"] = [
        net("8.152.0.0/14"),    # collapsed from two L1 BGP /15s
        net("120.24.0.0/16"),   # an L2 (weak) BGP prefix
        net("1.0.1.0/24"),      # genuine APNIC prefix
    ]
    bgp_prov = {"CN": {
        "8.152.0.0/15":  {"asn": 37963, "tier": 1, "level": "L1"},
        "8.154.0.0/15":  {"asn": 37963, "tier": 1, "level": "L1"},
        "120.24.0.0/16": {"asn": 37963, "tier": 1, "level": "L2"},
    }}

    out = gen.normalize_region_data(region_data, bgp_provenance=bgp_prov)
    objs = {o["cidr"]: o for o in out["CN"]["cidr_objects"]}

    # (A) collapsed prefix must still be recognised as BGP, not apnic
    a = objs["8.152.0.0/14"]
    assert a["source"] == "bgp", f"BUG-A regressed: collapsed BGP mislabelled {a}"
    assert a["asn"] == 37963 and a["tier"] == 1
    assert a["confidence"] == "medium", f"L1 should map to medium, got {a}"

    # (B) L2 weak prefix must be downgraded to low, not high
    b = objs["120.24.0.0/16"]
    assert b["source"] == "bgp" and b["level"] == "L2"
    assert b["confidence"] == "low", f"BUG-B regressed: L2 not low, got {b}"

    # genuine APNIC prefix unaffected
    c = objs["1.0.1.0/24"]
    assert c["source"] == "apnic" and c["confidence"] == "high"

    # cross-region safety: querying CN prefix as JP must not claim it
    jp = gen.normalize_region_data(
        {**{cc: [] for cc in gen.TARGET_REGIONS}, "JP": [net("8.152.0.0/14")]},
        bgp_provenance=bgp_prov,
    )
    jp_obj = jp["JP"]["cidr_objects"][0]
    assert jp_obj["source"] == "apnic", "cross-region provenance leak"

    # backward-compat: no provenance -> all apnic/high, no crash
    out_none = gen.normalize_region_data(region_data, bgp_provenance=None)
    assert all(o["source"] == "apnic" and o["confidence"] == "high"
               for o in out_none["CN"]["cidr_objects"])




# ================================================================
# v3.5 regression tests
# ================================================================
def _addr_set(nets):
    out = set()
    for n in nets:
        out.update(range(int(n.network_address), int(n.broadcast_address) + 1))
    return out


def test_sorted_networks_subtraction_matches_bruteforce():
    """The O(log n) SortedNetworks path must equal naive set subtraction."""
    import random

    g = generate_ip_list
    rng = random.Random(1234)
    base = int(ipaddress.ip_address("10.0.0.0"))

    def rand_net(min_prefix, max_prefix):
        plen = rng.randint(min_prefix, max_prefix)
        size = 1 << (32 - plen)
        start = base + (rng.randrange(0, 1 << 14) // size) * size
        return ipaddress.ip_network(f"{ipaddress.ip_address(start)}/{plen}")

    for _ in range(300):
        net = rand_net(19, 26)
        excluded = [rand_net(20, 30) for _ in range(rng.randint(0, 12))]
        got = g.subtract_excluded_from_network(net, g.SortedNetworks(excluded))
        via_list = g.subtract_excluded_from_network(net, excluded)
        expected = _addr_set([net]) - _addr_set(excluded)
        assert _addr_set(got) == expected
        assert _addr_set(via_list) == expected
        # result pieces must be disjoint
        assert sum(n.num_addresses for n in got) == len(expected)


def test_enforce_is_mutually_exclusive_and_lossless():
    import random

    g = generate_ip_list
    rng = random.Random(99)
    ccs = list(g.TARGET_REGIONS)

    def rnd():
        plen = rng.randint(20, 26)
        size = 1 << (32 - plen)
        start = (int(ipaddress.ip_address("20.0.0.0")) + (rng.randrange(0, 1 << 14) // size) * size)
        return ipaddress.ip_network(f"{ipaddress.ip_address(start)}/{plen}")

    region = {cc: [rnd() for _ in range(6)] for cc in ccs}
    supp = {cc: [rnd() for _ in range(6)] for cc in ccs}
    out, claims = g.enforce_mutual_exclusivity(region, supp, return_claims=True)

    sets = {cc: _addr_set(out[cc]) for cc in ccs}
    for i, a in enumerate(ccs):
        for b in ccs[i + 1:]:
            assert not (sets[a] & sets[b]), f"{a}/{b} overlap"
    union_in = _addr_set([n for v in region.values() for n in v] + [n for v in supp.values() for n in v])
    assert set().union(*sets.values()) == union_in, "address space lost or invented"
    # Tier-2 claims never include Tier-1 space and are part of the output
    apnic = _addr_set([n for v in region.values() for n in v])
    for cc in ccs:
        c = _addr_set(claims[cc])
        assert not (c & apnic)
        assert c <= sets[cc]


def _with_cache(entries):
    g = generate_ip_list
    g._GEOLOC_CACHE = dict(entries)


def test_geoloc_cache_hit_keeps_original_level():
    """v3.4 bug: a cached L2 guess came back as 'L-1' => confidence 'high'."""
    g = generate_ip_list
    saved = g._GEOLOC_CACHE
    try:
        _with_cache({"120.24.0.0/16": {
            "cc": "CN", "level": "L2", "ts": "2099-01-01T00:00:00Z",
            "rule_version": g._GEOLOC_CACHE_RULE_VERSION}})
        cc, level, from_cache = g.fetch_prefix_country("120.24.0.0/16", 37963, None)
        assert (cc, level, from_cache) == ("CN", "L2", True)
        assert g._level_to_confidence(level) == "low"
    finally:
        g._GEOLOC_CACHE = saved


def test_fresh_apnic_beats_stale_cache():
    """v3.4 bug: cache was consulted before APNIC containment (L0)."""
    g = generate_ip_list
    saved = g._GEOLOC_CACHE
    try:
        _with_cache({"1.0.1.0/24": {
            "cc": "SG", "level": "L1", "ts": "2099-01-01T00:00:00Z",
            "rule_version": g._GEOLOC_CACHE_RULE_VERSION}})
        region = {"CN": [ipaddress.ip_network("1.0.0.0/16")]}
        assert g.fetch_prefix_country("1.0.1.0/24", 1, region) == ("CN", "L0", False)
        # the prebuilt index gives the same answer
        idx = g.build_region_index(region)
        assert g.fetch_prefix_country("1.0.1.0/24", 1, idx) == ("CN", "L0", False)
    finally:
        g._GEOLOC_CACHE = saved


def test_apnic_block_not_mislabelled_as_bgp():
    """v3.4 bug: 47.96.0.0/11 (APNIC) was labelled source=bgp because a BGP
    prefix inside it had been recorded in provenance, even though enforce
    had trimmed that prefix away entirely."""
    g = generate_ip_list
    net = ipaddress.ip_network
    region = {"CN": [net("47.96.0.0/11")]}
    supp = {"CN": [net("47.96.0.0/24"), net("198.18.0.0/24")]}
    prov = {"CN": {
        "47.96.0.0/24": {"asn": 37963, "tier": 1, "level": "L0"},
        "198.18.0.0/24": {"asn": 37963, "tier": 1, "level": "L1"},
    }}
    out, claims = g.enforce_mutual_exclusivity(region, supp, return_claims=True)
    claimed_prov = g.restrict_provenance_to_claims(prov, claims)
    norm = g.normalize_region_data(out, bgp_provenance=claimed_prov)
    objs = {o["cidr"]: o for o in norm["CN"]["cidr_objects"]}
    assert objs["47.96.0.0/11"]["source"] == "apnic"
    assert objs["198.18.0.0/24"]["source"] == "bgp"
    assert objs["198.18.0.0/24"]["confidence"] == "medium"


def test_minority_bgp_share_is_labelled_apnic():
    """A CIDR that is mostly APNIC but absorbed a small adjacent BGP piece
    during collapse must stay source=apnic."""
    g = generate_ip_list
    net = ipaddress.ip_network
    region = {"CN": [net("10.0.0.0/25"), net("10.0.0.128/26"), net("10.0.0.192/26")]}
    prov = {"CN": {"10.0.0.192/26": {"asn": 45090, "tier": 2, "level": "L1"}}}
    norm = g.normalize_region_data(region, bgp_provenance=prov)
    (obj,) = norm["CN"]["cidr_objects"]
    assert obj["cidr"] == "10.0.0.0/24" and obj["source"] == "apnic"


def _patched_urlopen(fn):
    import urllib.request

    class _Ctx:
        def __enter__(self):
            self.orig = urllib.request.urlopen
            urllib.request.urlopen = fn
        def __exit__(self, *a):
            urllib.request.urlopen = self.orig
            return False
    return _Ctx()


def test_http_get_does_not_retry_permanent_4xx():
    import urllib.error

    g = generate_ip_list
    calls = []

    def fake(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

    saved = g.RETRY_BACKOFF_BASE
    g.RETRY_BACKOFF_BASE = 0
    try:
        with _patched_urlopen(fake):
            try:
                g.http_get("https://example.com/missing")
                assert False, "should raise"
            except urllib.error.HTTPError:
                pass
        assert len(calls) == 1, f"404 retried {len(calls)} times"

        calls.clear()

        def fake429(req, timeout=None):
            calls.append(1)
            raise urllib.error.HTTPError(req.full_url, 429, "slow", {}, None)

        with _patched_urlopen(fake429):
            try:
                g.http_get("https://example.com/busy", retries=3)
            except urllib.error.HTTPError:
                pass
        assert len(calls) == 3, "429 must be retried"
    finally:
        g.RETRY_BACKOFF_BASE = saved


def test_atomic_writes_leave_no_temp_files():
    g = generate_ip_list
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "x.txt"
        g._atomic_write_text(str(path), "hello\n")
        assert path.read_text() == "hello\n"
        assert [p.name for p in Path(d).iterdir()] == ["x.txt"]


def _write_dataset(tmpdir):
    g = generate_ip_list
    raw = "\n".join([
        "2|apnic|20260901|1|1|summary",
        "apnic|CN|ipv4|1.0.1.0|256|20200101|allocated",
        "apnic|HK|ipv4|1.0.2.0|256|20200101|assigned",
        "apnic|TW|ipv4|1.0.4.0|256|20200101|assigned",
        "apnic|MO|ipv4|1.0.5.0|256|20200101|assigned",
        "apnic|JP|ipv4|1.0.3.0|256|20200101|allocated",
        "apnic|KR|ipv4|1.0.6.0|256|20200101|allocated",
        "apnic|SG|ipv4|1.0.7.0|256|20200101|allocated",
    ])
    region, stats = g.parse_and_cleanse(raw, [])
    norm = g.normalize_region_data(region)
    report = {"mode": "static_only", "succeeded": [], "failed": [], "total_prefixes": 0}
    g.save_txt_outputs(norm, tmpdir)
    g.save_json_outputs(norm, report, stats, tmpdir)


def test_validate_output_integrity_gates():
    import validate_output as v

    # The real thresholds need a full dataset; relax CN for the fixture.
    saved_min = v.MIN_CN_CIDRS
    v.MIN_CN_CIDRS = 1
    try:
        with tempfile.TemporaryDirectory() as d:
            _write_dataset(d)
            assert v.main(["-o", d, "--skip-dns"]) == 0

            # Tamper with a region file: must fail the TXT/data.json match.
            cn = Path(d) / "CN.txt"
            cn.write_text(cn.read_text() + "9.9.9.0/24\n")
            try:
                v.main(["-o", d, "--skip-dns"])
                assert False, "tampered CN.txt must fail validation"
            except SystemExit as e:
                assert e.code == 1

            # Tamper with data.json: checksum gate must fail.
            _write_dataset(d)
            dj = Path(d) / "data.json"
            dj.write_text(dj.read_text().replace('"project"', '"project" ', 1))
            try:
                v.main(["-o", d, "--skip-dns"])
                assert False, "checksum mismatch must fail validation"
            except SystemExit as e:
                assert e.code == 1
    finally:
        v.MIN_CN_CIDRS = saved_min


def test_build_formats_fails_when_a_format_fails():
    import build_formats as bf

    saved = bf.build_mmdb
    bf.build_mmdb = lambda data, out: False
    try:
        with tempfile.TemporaryDirectory() as d:
            _write_dataset(d)
            argv = sys.argv
            sys.argv = ["build_formats", "-o", d]
            try:
                assert bf.main() == 1
            finally:
                sys.argv = argv
            sys.argv = ["build_formats", "-o", d, "--skip-mmdb"]
            try:
                assert bf.main() == 0
            finally:
                sys.argv = argv
            # checksums must not list gitignored release files
            sums = (Path(d) / "checksums.txt").read_text()
            assert "ipnova-formats.tar.gz" not in sums
    finally:
        bf.build_mmdb = saved


def test_samples_json_regions_known():
    samples = json.loads((ROOT / "tests" / "samples.json").read_text(encoding="utf-8"))
    allowed = set(generate_ip_list.TARGET_REGIONS) | {"INTL", "EDGE"}
    assert set(samples) <= allowed
    assert all(isinstance(v, list) and v for v in samples.values())


if __name__ == "__main__":
    import inspect
    import traceback

    tests = [(name, fn) for name, fn in sorted(globals().items(), key=lambda kv: (
        inspect.getsourcelines(kv[1])[1] if inspect.isfunction(kv[1]) else 0))
        if name.startswith("test_") and inspect.isfunction(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  {name}: PASS")
        except Exception:
            failed += 1
            print(f"  {name}: FAIL")
            traceback.print_exc()
    if failed:
        print(f"\n{failed}/{len(tests)} tests FAILED")
        sys.exit(1)
    print(f"\nAll {len(tests)} offline tests passed.")
