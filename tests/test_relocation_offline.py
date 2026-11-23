#!/usr/bin/env python3
"""Cloud space is listed where it is operated (4.2.0, located block by block
since 4.2.1).

The cloud companies register large blocks in Singapore and run data centres
all over the world from them. RIPEstat's per-ASN geolocation answer merges
adjacent announced prefixes into one entry (Tencent's 43.156.0.0/15 holds
Singapore, Frankfurt and São Paulo), so the located blocks inside each entry
decide, never a vote over the entry. All tests are offline: RIPEstat answers
are faked in the shape the real data call returns (covered_percentage is
relative to the whole ASN; `resources` lists the located blocks).
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

# AS132203's answer: entry -> [(country, [located blocks])]
GEO = {
    "43.156.0.0/15": [("SG", ["43.156.0.0/16"]), ("DE", ["43.157.0.0/18"]),
                      ("BR", ["43.157.128.0/18"]), ("ID", ["43.157.192.0/18"])],
    "43.165.0.0/16": [("DE", ["43.165.0.0/18"]), ("US", ["43.165.64.0/18"]),
                      ("JP", ["43.165.128.0/18"]), ("ID", ["43.165.192.0/18"])],
    "43.129.0.0/16": [("HK", ["43.129.0.0/18"]), ("SG", ["43.129.128.0/17"]),
                      # small blocks vote for their /24
                      ("ID", ["43.129.64.0/25", "43.129.64.128/26"]),
                      ("JP", ["43.129.65.0/26"])],
    # outside the regions' APNIC space: the supplement's business
    "129.226.0.0/16": [("HK", ["129.226.0.0/16"])],
    "170.106.0.0/16": [("US", ["170.106.0.0/16"])],
}
# what AS132203 announces (RIPEstat announced-prefixes)
ANNOUNCED = ["43.156.0.0/16", "43.157.0.0/18", "43.157.64.0/18", "43.165.0.0/16",
             "43.165.128.0/18", "43.129.0.0/16", "129.226.0.0/16", "170.106.0.0/16"]

APNIC = "\n".join([
    "2|apnic|20261123|5|19830613|20261122|+1000",
    "apnic|SG|ipv4|43.128.0.0|4194304|20200101|allocated",   # 43.128.0.0/10
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
    for prefix, locs in geo.items():
        rows.append({"resource": prefix, "unknown_percentage": 99.0, "locations": [
            {"country": cc, "city": "", "covered_percentage": 0.5, "resources": blocks}
            for cc, blocks in locs]})
    return json.dumps({"data": {"located_resources": rows}, "status": "ok"})


def fake_http_get(geo_by_asn, calls):
    def _get(url, timeout=30, retries=3, ua=None, strict_decode=False,
             return_content_type=False):
        calls.append(url)
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
    """main() on the fixture above; returns ({cc: [cidr]}, meta, data, urls)."""
    calls = []
    announced = {TENCENT: [net(p) for p in ANNOUNCED]}
    with tempfile.TemporaryDirectory() as out, patched(
            download_apnic_data=lambda: APNIC,
            build_excluded_networks=lambda skip_ripe=False: (
                [], {"mode": "test", "succeeded": [], "failed": [], "total_prefixes": 0}),
            fetch_asn_prefixes=lambda asn: list(announced.get(asn, [])),
            fetch_asn_country=lambda asn: "CN",
            http_get=fake_http_get({TENCENT: GEO}, calls),
            _GEOLOC_CACHE=None,
            _GEOLOC_CACHE_PATH=g._GEOLOC_CACHE_PATH):
        g.main(["-o", out, "--skip-canary", "--skip-sanity", *extra])
        o = Path(out)
        lists = {cc: read_list(o / f"{cc}.txt") for cc in g.TARGET_REGIONS}
        meta = json.loads((o / "meta.json").read_text())
        data = json.loads((o / "data.json").read_text())
    return lists, meta, data, calls


def test_cloud_space_is_listed_where_it_is_operated():
    """End to end through main(). Before 4.2.0 all of 43.128.0.0/10 stayed
    in SG.txt; 4.2.0 voted over whole entries, so 43.165.0.0/16 (four data
    centres, none in Singapore) and Frankfurt inside 43.156.0.0/15 stayed."""
    lists, meta, data, calls = run_build()
    sg, jp, hk = lists["SG"], lists["JP"], lists["HK"]
    everything = [c for cidrs in lists.values() for c in cidrs]

    for ip in ("43.157.0.1", "43.157.128.1", "43.157.192.1",
               "43.165.0.1", "43.165.64.1", "43.165.192.1", "43.129.64.1"):
        assert not holds(everything, ip), f"{ip} is operated outside the seven regions"
    assert holds(jp, "43.165.128.1") and not holds(sg, "43.165.128.1")
    assert holds(hk, "43.129.0.1") and not holds(sg, "43.129.0.1")
    for ip in ("43.156.0.1", "43.129.128.1", "43.140.0.1", "116.14.0.1"):
        assert holds(sg, ip), f"{ip} is located in SG (or unknown) and stays"
    assert holds(sg, "43.157.64.1"), "space without a location stays where it is registered"
    assert holds(sg, "43.129.65.1"), "a /24 less than half located stays"

    rel = meta["parsing"]["cloud_relocation"]
    q = 16384
    assert rel["moved_addresses"] == {
        "SG->BR": q, "SG->DE": 2 * q, "SG->HK": q, "SG->ID": 2 * q + 256,
        "SG->JP": q, "SG->US": q}
    assert rel["removed_addresses"] == {"SG": 8 * q + 256}
    assert rel["added_addresses"] == {"HK": q, "JP": q}
    assert rel["kept_addresses"] == 65536 + 32768
    assert rel["asns"][str(TENCENT)] == {"name": "Tencent Cloud International",
                                         "source": "ripestat", "parts": 13}
    assert {s["source"] for a, s in rel["asns"].items() if a != str(TENCENT)} == {"none"}

    # The supplement leaves moved space alone and places the rest from the
    # same answer: no per-prefix lookups, no ASN-country guess.
    cs = meta["parsing"]["cloud_supplement"]
    assert cs["handled_by_relocation"] == 4   # 43.157.0.0/18, 43.165.x (2), 43.129.0.0/16
    assert cs["geo_hit"] == 2 and cs["l2_fallback"] == 0
    assert holds(hk, "129.226.0.1") and not holds(everything, "170.106.0.1")
    assert not [u for u in calls if "/geoloc/" in u]

    objs = {o["cidr"]: o for o in data["regions"]["JP"]["cidr_objects"]}
    assert objs["43.165.128.0/18"] == {
        "cidr": "43.165.128.0/18", "source": "bgp", "asn": TENCENT, "tier": 1,
        "level": "L1", "confidence": "medium"}


def test_skip_relocation_keeps_the_registration():
    lists, meta, _data, _calls = run_build("--skip-relocation")
    assert holds(lists["SG"], "43.157.0.1") and holds(lists["SG"], "43.165.128.1")
    assert meta["parsing"]["cloud_relocation"] == {"skipped": True, "reason": "skip_relocation"}


def test_failed_lookup_moves_nothing_without_cached_parts():
    def fail(asn):
        raise OSError("RIPEstat down")
    with fresh_cache({}), patched(fetch_asn_geoloc=fail):
        out, moved_in, _prov, moved_space, stats = g.relocate_cloud_space(
            {"SG": [net("43.128.0.0/11")]})
    assert [str(n) for n in out["SG"]] == ["43.128.0.0/11"]
    assert moved_in == {} and moved_space == []
    assert {s["source"] for s in stats["asns"].values()} == {"none"}


def test_failed_lookup_uses_parts_cached_by_earlier_runs():
    def fail(asn):
        raise OSError("RIPEstat down")
    rec = {"cc": "DE", "level": "L1", "asn": TENCENT, "part": True,
           "ts": "2099-01-01T00:00:00Z", "rule_version": g._GEOLOC_CACHE_RULE_VERSION}
    with fresh_cache({"43.157.0.0/18": rec}), patched(fetch_asn_geoloc=fail):
        out, _moved_in, _prov, moved_space, stats = g.relocate_cloud_space(
            {"SG": [net("43.128.0.0/11")]})
    assert not holds(out["SG"], "43.157.0.1") and holds(out["SG"], "43.156.0.1")
    assert [str(n) for n in moved_space] == ["43.157.0.0/18"]
    assert stats["asns"][str(TENCENT)]["source"] == "cache"


def test_answer_is_one_call_per_asn_and_is_cached_for_a_failed_week():
    calls = []
    with fresh_cache({}), patched(http_get=fake_http_get({134963: {
            "8.208.136.0/22": [("GB", ["8.208.136.0/22"])]}}, calls)):
        geo = g.fetch_cloud_geoloc()
        assert sum("AS134963" in u for u in calls) == 1
        assert len(calls) == len(g.RELOCATION_ASNS)
        assert geo.parts == [(net("8.208.136.0/22"), "GB", 134963)]
        assert g._asn_parts_from_cache(134963) == [(net("8.208.136.0/22"), "GB")]


def test_located_blocks_not_covered_percentage_decide():
    r = net("43.129.0.0/16")
    locs = [
        {"country": "HK", "covered_percentage": 2.46,
         "resources": ["43.129.0.0/18", "43.0.0.0/8", "2404:2280::/40", "10.0.0.0/8"]},
        {"country": "SG", "covered_percentage": 0.15,
         "resources": ["43.129.111.0/25", "43.129.111.245/32"]},
        {"country": "ID", "covered_percentage": 0.37},           # no blocks: ignored
    ]
    parts = g._resource_parts(r, locs)
    # the /8 block covers the whole entry; the /25 + /32 carry 129 of 256
    assert sorted((str(n), cc) for n, cc in parts) == [
        ("43.129.0.0/16", "HK"), ("43.129.0.0/18", "HK"), ("43.129.111.0/24", "SG")]
    # an entry smaller than /24 is its own voting unit
    assert g._resource_parts(net("1.2.3.0/25"), [
        {"country": "JP", "resources": ["1.2.3.0/26"]}]) == [(net("1.2.3.0/25"), "JP")]


def test_cn_registrations_stay_but_cloud_space_can_join_cn():
    """Part of Alibaba's 8.128.0.0/10 (SG) runs Aliyun's mainland regions; it
    belongs in CN. Space registered in CN is never moved out."""
    geo = g.CloudGeo([(net("8.130.0.0/16"), "CN", 37963),
                      (net("47.96.0.0/16"), "HK", 37963)])
    out, moved_in, _prov, moved_space, _stats = g.relocate_cloud_space(
        {"SG": [net("8.128.0.0/10")], "CN": [net("47.96.0.0/11")]}, geo)
    assert not holds(out["SG"], "8.130.0.1") and holds(moved_in["CN"], "8.130.0.1")
    assert holds(out["CN"], "47.96.0.1") and moved_space == [net("8.130.0.0/16")]
    assert set(g.RELOCATION_ASNS) == set(g.CN_CLOUD_ASNS)


def test_no_asn_country_guess_for_international_clouds():
    """Alibaba's Hong Kong 47.56.0.0/15 was listed in CN: with no location
    known, the ASN holder's country (CN) was used."""
    with fresh_cache({"47.56.0.0/15": {
            "cc": "CN", "level": "L2", "ts": "2099-01-01T00:00:00Z",
            "rule_version": g._GEOLOC_CACHE_RULE_VERSION}}), patched(
            http_get=fake_http_get({}, []), fetch_asn_country=lambda asn: "CN"):
        assert g.fetch_prefix_country("47.56.0.0/15", 45102, {}) == (None, "L3", False)
        assert g.fetch_prefix_country("47.92.0.0/14", 37963, {}) == ("CN", "L2", False)
    assert "ByteDance" not in g.CN_CLOUD_ASNS.values(), "AS58593 is Azure China (21Vianet)"
