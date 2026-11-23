#!/usr/bin/env python3
"""v4.2.0: international cloud space goes where it is operated.

Tencent's 43.128.0.0/13 and Alibaba's 8.128.0.0/10 are registered in SG but
operated all over the world. The BGP step only *added* cloud prefixes to a
region; a prefix inside a region's APNIC space was settled by containment
(L0) and stayed in the registered region, wherever it ran. All tests are
offline: RIPEstat answers are faked.
"""

import contextlib
import ipaddress
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import generate_ip_list as g  # noqa: E402

net = ipaddress.ip_network
TENCENT = 132203

# AS132203's prefixes, all inside the SG allocation 43.128.0.0/11, with the
# country shares RIPEstat reports for each.
GEO = {
    "43.157.0.0/18": {"DE": 100.0},              # Frankfurt: leaves SG
    "43.128.224.0/19": {"JP": 96.0, "SG": 1.0},  # Tokyo: SG -> JP
    "43.134.0.0/16": {"SG": 100.0},              # Singapore: stays
    "43.131.0.0/18": {"SG": 30.0, "US": 30.0},   # no majority: stays
    "43.152.0.0/16": {"DE": 80.0},               # moves ...
    "43.152.10.0/24": {"SG": 100.0},             # ... except this /24
    "43.152.20.0/24": {},                        # no data: follows the /16
}

APNIC = "\n".join([
    "2|apnic|20261123|5|19830613|20261122|+1000",
    "apnic|SG|ipv4|43.128.0.0|2097152|20200101|allocated",   # 43.128.0.0/11
    "apnic|SG|ipv4|116.14.0.0|131072|20200101|allocated",
    "apnic|JP|ipv4|126.0.0.0|16777216|20200101|allocated",
    "apnic|CN|ipv4|1.0.1.0|256|20200101|allocated",
    "apnic|HK|ipv4|1.0.2.0|256|20200101|allocated",
]) + "\n"


@contextlib.contextmanager
def patched(**attrs):
    saved = {k: getattr(g, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(g, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(g, k, v)


@contextlib.contextmanager
def fresh_cache(entries=None):
    with tempfile.TemporaryDirectory() as tmp:
        with patched(_GEOLOC_CACHE=dict(entries) if entries is not None else None,
                     _GEOLOC_CACHE_PATH=str(Path(tmp) / ".geoloc_cache.json")):
            yield


def geo_payload(geo):
    rows = []
    for prefix, shares in geo.items():
        rows.append({"resource": prefix, "unknown_percentage": 0.0, "locations": [
            {"country": cc, "city": "", "covered_percentage": pct}
            for cc, pct in shares.items()]})
    return json.dumps({"data": {"located_resources": rows}, "status": "ok"})


def fake_http_get(geo_by_asn):
    def _get(url, timeout=30, retries=3, ua=None, strict_decode=False,
             return_content_type=False):
        if url.startswith(g.RIPE_GEO_BY_ASN_URL):
            asn = int(url.rsplit("AS", 1)[1])
            if asn not in geo_by_asn:
                raise OSError("simulated RIPEstat failure")
            return geo_payload(geo_by_asn[asn]), "application/json"
        raise OSError(f"unexpected request {url}")
    return _get


def holds(cidrs, ip):
    return any(ipaddress.ip_address(ip) in net(c) for c in cidrs)


def read_list(path):
    return [ln for ln in path.read_text().splitlines() if ln and not ln.startswith("#")]


def run_build(*extra):
    """main() on the fixture above; returns ({cc: [cidr]}, meta, data)."""
    prefixes = {TENCENT: [net(p) for p in GEO]}
    with tempfile.TemporaryDirectory() as out, patched(
            download_apnic_data=lambda: APNIC,
            build_excluded_networks=lambda skip_ripe=False: (
                [], {"mode": "test", "succeeded": [], "failed": [], "total_prefixes": 0}),
            fetch_asn_prefixes=lambda asn: list(prefixes.get(asn, [])),
            fetch_asn_country=lambda asn: None,
            http_get=fake_http_get({TENCENT: GEO}),
            _GEOLOC_CACHE=None,
            _GEOLOC_CACHE_PATH=g._GEOLOC_CACHE_PATH):
        g.main(["-o", out, "--skip-canary", "--skip-sanity", *extra])
        o = Path(out)
        lists = {cc: read_list(o / f"{cc}.txt") for cc in g.TARGET_REGIONS}
        meta = json.loads((o / "meta.json").read_text())
        data = json.loads((o / "data.json").read_text())
    return lists, meta, data


def test_cloud_space_is_listed_where_it_is_operated():
    """End to end through main(): before 4.2.0 every one of these prefixes
    stayed in SG.txt because it is inside SG's APNIC allocation."""
    lists, meta, data = run_build()
    sg, jp = lists["SG"], lists["JP"]
    everything = [c for cidrs in lists.values() for c in cidrs]

    assert not holds(everything, "43.157.0.1"), "Frankfurt space must be in no region"
    assert not holds(sg, "43.128.224.1") and holds(jp, "43.128.224.1")
    assert holds(sg, "43.134.0.1") and holds(sg, "43.131.0.1")
    assert not holds(everything, "43.152.0.1")
    assert holds(sg, "43.152.10.1"), "a more specific verdict wins inside a moved prefix"
    assert not holds(everything, "43.152.20.1"), "a prefix without data follows its parent"
    assert holds(sg, "43.140.0.1") and holds(sg, "116.14.0.1"), "the rest of SG is untouched"

    rel = meta["parsing"]["cloud_relocation"]
    assert (rel["moved"], rel["stayed"], rel["undecided"]) == (3, 2, 2)
    assert rel["removed_addresses"] == {"SG": 16384 + 8192 + 65536 - 256}
    assert rel["added_addresses"] == {"JP": 8192}
    assert rel["moved_addresses"] == {"SG->DE": 16384 + 65536 - 256, "SG->JP": 8192}
    assert rel["asns"][str(TENCENT)]["source"] == "ripestat"
    assert rel["asns"]["45102"]["source"] == "none"
    assert set(rel["asns"]) == {str(a) for a in g.RELOCATION_ASNS}
    assert meta["parsing"]["cloud_supplement"]["handled_by_relocation"] == len(GEO)

    objs = {o["cidr"]: o for o in data["regions"]["JP"]["cidr_objects"]}
    assert objs["43.128.224.0/19"] == {
        "cidr": "43.128.224.0/19", "source": "bgp", "asn": TENCENT, "tier": 1,
        "level": "L1", "confidence": "medium"}


def test_skip_relocation_keeps_the_registration():
    lists, meta, _data = run_build("--skip-relocation")
    assert holds(lists["SG"], "43.157.0.1") and holds(lists["SG"], "43.128.224.1")
    assert meta["parsing"]["cloud_relocation"] == {"skipped": True, "reason": "skip_relocation"}


def test_failed_lookup_moves_nothing_without_cached_answers():
    def fail(asn):
        raise OSError("RIPEstat down")
    with fresh_cache({}), patched(fetch_asn_geoloc=fail):
        region = {"SG": [net("43.128.0.0/11")]}
        out, moved_in, _prov, handled, stats = g.relocate_cloud_space(region)
    assert [str(n) for n in out["SG"]] == ["43.128.0.0/11"]
    assert moved_in == {} and handled == set()
    assert {s["source"] for s in stats["asns"].values()} == {"none"}


def test_failed_lookup_uses_answers_cached_by_earlier_runs():
    def fail(asn):
        raise OSError("RIPEstat down")
    rec = {"cc": "DE", "level": "L1", "share": 100.0, "asn": TENCENT,
           "ts": "2099-01-01T00:00:00Z", "rule_version": g._GEOLOC_CACHE_RULE_VERSION}
    with fresh_cache({"43.157.0.0/18": rec}), patched(fetch_asn_geoloc=fail):
        out, _moved_in, _prov, handled, stats = g.relocate_cloud_space(
            {"SG": [net("43.128.0.0/11")]})
    assert not holds(out["SG"], "43.157.0.1") and holds(out["SG"], "43.156.0.1")
    assert handled == {"43.157.0.0/18"}
    assert stats["asns"][str(TENCENT)]["source"] == "cache"


def test_asn_geolocation_is_one_call_and_warms_the_prefix_cache():
    calls = []
    payload = json.dumps({"data": {"located_resources": [
        # covered_percentage relative to the whole ASN; the listed block
        # shows the /24 is entirely in the US.
        {"resource": "47.251.0.0/24", "locations": [
            {"country": "US", "covered_percentage": 0.39, "resources": ["47.251.0.0/16"]}]},
        {"resource": "2404:2280::/40", "locations": [
            {"country": "SG", "covered_percentage": 100.0}]},
    ]}})

    def get(url, **kw):
        calls.append(url)
        if url.startswith(g.RIPE_GEO_BY_ASN_URL) and url.endswith("AS134963"):
            return payload, "application/json; charset=utf-8"
        raise OSError("down")

    with fresh_cache({}), patched(http_get=get, fetch_asn_country=lambda asn: None):
        assert g.fetch_asn_geoloc(134963) == {"47.251.0.0/24": {"US": 100.0}}
        calls.clear()
        g.relocate_cloud_space({"SG": [net("8.208.0.0/12")]})
        assert sum("AS134963" in u for u in calls) == 1
        calls.clear()
        # Outside every region: the supplement's lookup now comes from the cache.
        assert g.fetch_prefix_country("47.251.0.0/24", 134963, {}) == ("US", "L1", True)
        assert calls == []


def test_cn_registrations_stay_but_cloud_space_can_join_cn():
    """Part of Alibaba's 8.128.0.0/10 (SG) runs mainland regions; it belongs
    in CN. Space registered in CN is never moved out."""
    geo = {"8.130.0.0/16": {"CN": 100.0}, "47.96.0.0/16": {"HK": 100.0}}
    with fresh_cache({}), patched(
            fetch_asn_geoloc=lambda asn: geo if asn == 37963 else {}):
        out, moved_in, _prov, handled, _stats = g.relocate_cloud_space(
            {"SG": [net("8.128.0.0/10")], "CN": [net("47.96.0.0/11")]})
    assert not holds(out["SG"], "8.130.0.1") and holds(moved_in["CN"], "8.130.0.1")
    assert holds(out["CN"], "47.96.0.1") and "47.96.0.0/16" not in handled
    assert set(g.RELOCATION_ASNS) == set(g.CN_CLOUD_ASNS)
    assert 134963 in g.CN_CLOUD_ASNS_TIER1


def test_shares_are_measured_from_the_located_blocks():
    """The share must not depend on what covered_percentage is relative to."""
    p = net("43.152.0.0/16")
    locs = [
        {"country": "DE", "covered_percentage": 0.3,
         "resources": ["43.152.0.0/18", "43.152.64.0/18", "43.152.128.0/18"]},
        {"country": "SG", "covered_percentage": 0.1, "resources": ["43.152.192.0/18"]},
        {"country": "DE", "city": "Berlin", "covered_percentage": 0.1,
         "resources": ["43.152.0.0/18", "2404:2280::/40", "10.0.0.0/8"]},
    ]
    assert g._located_shares(p, locs) == {"DE": 75.0, "SG": 25.0}
    # a block larger than the prefix covers all of it
    assert g._located_shares(p, [{"country": "JP", "resources": ["43.152.0.0/12"]}]) == {"JP": 100.0}
    # no blocks listed: the reported percentage is used as is
    assert g._located_shares(p, [{"country": "US", "covered_percentage": 40}]) == {"US": 40.0}
