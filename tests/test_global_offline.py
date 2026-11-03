"""Offline tests for scripts/build_global.py (no network)."""
from __future__ import annotations

import ipaddress
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_global as bg  # noqa: E402
from regions import TARGET_REGIONS  # noqa: E402


def rir(registry: str, rows: list[str]) -> str:
    head = [f"2.3|{registry}|20261102|{len(rows)}|19830101|20261101|+0000",
            f"{registry}|*|ipv4|*|{len(rows)}|summary"]
    return "\n".join(["# comment"] + head + rows) + "\n"


def fixtures() -> dict:
    return {
        "apnic": rir("apnic", [
            "apnic|AU|ipv4|1.0.0.0|256|20110811|assigned|A1",
            "apnic|CN|ipv4|1.0.1.0|256|20110414|allocated|A2",      # replaced by IPNova CN
            "apnic|AU|ipv4|1.1.0.0|768|20110811|allocated|A3",       # non power of two
            "apnic|AP|ipv4|1.2.0.0|256|20110811|allocated|A4",       # registry code kept
            "apnic|JP|ipv6|2001:200::|23|19990813|allocated|A5",
            "apnic|ZZ|ipv4|1.3.0.0|256|20110811|reserved|A6",        # skipped
            "apnic||ipv4|1.4.0.0|256||available|",                   # skipped
            "apnic|AU|asn|7545|1|20000101|allocated|A7",             # not an IP record
        ]),
        "arin": rir("arin", [
            "arin|US|ipv4|3.0.0.0|16777216|19880223|allocated|B1",
            "arin|US|ipv4|8.128.0.0|4194304|20181019|allocated|B2",  # IPNova puts part in SG
            "arin|CA|ipv4|24.0.0.0|65536|19950101|allocated|B3",
            "arin|US|ipv6|2600::|12|20060920|allocated|B4",
        ]),
        "ripencc": rir("ripencc", [
            "ripencc|DE|ipv4|5.0.0.0|65536|20100101|allocated|C1",
            "ripencc|EU|ipv4|5.1.0.0|65536|20100101|allocated|C2",
            "ripencc|NL|ipv4|24.0.128.0|256|20100101|assigned|C3",   # overlaps arin CA block
            "ripencc|DE|ipv6|2a00::|12|20050101|allocated|C4",
        ]),
        "lacnic": rir("lacnic", [
            "lacnic|BR|ipv4|177.0.0.0|1048576|20100101|allocated|D1",
            "lacnic|BR|ipv6|2804::|16|20100101|allocated|D2",
        ]),
        "afrinic": rir("afrinic", [
            "afrinic|ZA|ipv4|41.0.0.0|2097152|20050101|allocated|E1",
        ]),
    }


def regions_dir(tmp: Path) -> Path:
    d = tmp / "regions"
    d.mkdir()
    for cc in TARGET_REGIONS:
        nets = {"CN": ["1.0.1.0/24", "1.0.2.0/23"], "SG": ["8.128.0.0/16"]}.get(cc, [])
        if not nets:
            nets = [f"203.0.113.{8 * list(TARGET_REGIONS).index(cc)}/29"]
        (d / f"{cc}.txt").write_text("# header\n" + "\n".join(nets) + "\n", encoding="utf-8")
    return d


def test_parse_delegated():
    p, info = bg.parse_delegated(fixtures()["apnic"], "apnic")
    assert info["serial"] == "20261102"
    assert info["ipv4_records"] == 4 and info["ipv6_records"] == 1
    assert (int(ipaddress.IPv4Address("1.1.0.0")), int(ipaddress.IPv4Address("1.1.2.255")), "AU") in p["ipv4"]
    assert all(cc != "ZZ" for _, _, cc in p["ipv4"])


def test_make_exclusive_and_subtract():
    rows, conflicts = bg.make_exclusive([(0, 99, "A"), (50, 149, "B"), (10, 20, "C")])
    assert rows == [(0, 99, "A"), (100, 149, "B")] and conflicts == 2
    assert bg.subtract([(0, 99, "A")], [(10, 19), (50, 200)]) == [(0, 9, "A"), (20, 49, "A")]
    assert bg.merge([(5, 9), (0, 4), (20, 30), (25, 40)]) == [(0, 9), (20, 40)]


def test_build_countries_overrides_apac():
    with tempfile.TemporaryDirectory() as d:
        regions = bg.load_region_cidrs(regions_dir(Path(d)))
    parsed = [bg.parse_delegated(t, n)[0] for n, t in fixtures().items()]
    per, stats = bg.build_countries(parsed, regions)
    assert [str(n) for n in per["CN"]["ipv4"]] == ["1.0.1.0/24", "1.0.2.0/23"]
    assert [str(n) for n in per["SG"]["ipv4"]] == ["8.128.0.0/16"]
    # SG space removed from the US registration
    us = per["US"]["ipv4"]
    assert not any(n.overlaps(ipaddress.ip_network("8.128.0.0/16")) for n in us)
    assert any(n.overlaps(ipaddress.ip_network("8.129.0.0/16")) for n in us)
    assert [str(n) for n in per["AU"]["ipv4"]] == ["1.0.0.0/24", "1.1.0.0/23", "1.1.2.0/24"]
    assert "AP" in per and "EU" in per and "ZZ" not in per
    assert per["JP"]["ipv6"] == [ipaddress.ip_network("2001:200::/23")]
    # overlapping RIPE NL record inside the ARIN CA block is trimmed
    assert "NL" not in per and stats["conflicts_trimmed"]["ipv4"] == 1


def test_geoip_dat_roundtrip_and_protobuf():
    entries = {"cn": [ipaddress.ip_network("1.0.1.0/24")],
               "US": [ipaddress.ip_network("3.0.0.0/8"), ipaddress.ip_network("2600::/12")],
               "PRIVATE": [ipaddress.ip_network("10.0.0.0/8"), ipaddress.ip_network("fc00::/7")]}
    dat = bg.encode_geoip_dat(entries)
    back = bg.decode_geoip_dat(dat)
    assert list(back) == ["PRIVATE", "US", "CN"] or set(back) == {"PRIVATE", "US", "CN"}
    assert back["US"] == entries["US"] and back["CN"] == entries["cn"]
    # Independent check with the official protobuf runtime, if available.
    try:
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    except ImportError:
        return
    fdp = descriptor_pb2.FileDescriptorProto(name="geoip_test.proto", package="t", syntax="proto3")
    cidr = fdp.message_type.add(name="CIDR")
    cidr.field.add(name="ip", number=1, type=12, label=1)
    cidr.field.add(name="prefix", number=2, type=13, label=1)
    gi = fdp.message_type.add(name="GeoIP")
    gi.field.add(name="country_code", number=1, type=9, label=1)
    gi.field.add(name="cidr", number=2, type=11, label=3, type_name=".t.CIDR")
    gi.field.add(name="reverse_match", number=3, type=8, label=1)
    gl = fdp.message_type.add(name="GeoIPList")
    gl.field.add(name="entry", number=1, type=11, label=3, type_name=".t.GeoIP")
    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    GeoIPList = message_factory.GetMessageClass(pool.FindMessageTypeByName("t.GeoIPList"))
    msg = GeoIPList()
    msg.ParseFromString(dat)
    got = {e.country_code: [str(ipaddress.ip_network((ipaddress.ip_address(c.ip), c.prefix))) for c in e.cidr]
           for e in msg.entry}
    assert got == {"CN": ["1.0.1.0/24"], "US": ["3.0.0.0/8", "2600::/12"],
                   "PRIVATE": ["10.0.0.0/8", "fc00::/7"]}
    assert msg.SerializeToString() == dat


def test_full_build_and_shrink_guard():
    try:
        import mmdb_writer  # noqa: F401
        import netaddr  # noqa: F401
    except ImportError:
        return  # CI installs both
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        rd = regions_dir(d)
        out = d / "dist"
        meta = bg.build(out, rd, None, False, texts=fixtures())
        names = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
        assert {"geoip.dat", "ipnova-global-country.mmdb", "meta.json", "SHA256SUMS",
                "README.md", "country/ipv4/US.txt", "country/ipv6/DE.txt"} <= set(names)
        dat = bg.decode_geoip_dat((out / "geoip.dat").read_bytes())
        assert "PRIVATE" in dat and "CN" in dat and "US" in dat
        assert meta["totals"]["countries"] == len(json.loads((out / "meta.json").read_text())["countries"])
        sums = (out / "SHA256SUMS").read_text().splitlines()
        assert len(sums) == len(names) - 1
        # shrink guard: half the addresses -> refused
        prev = json.loads(json.dumps(meta))
        prev["totals"]["ipv4_addresses"] *= 2
        try:
            bg.build(d / "dist2", rd, prev, False, texts=fixtures())
        except bg.GlobalBuildError as e:
            assert "ipv4_addresses" in str(e)
        else:
            raise AssertionError("shrink guard did not trigger")
        bg.build(d / "dist3", rd, prev, True, texts=fixtures())  # --allow-shrink


def test_private_blocks_valid():
    for c in bg.PRIVATE_V4 + bg.PRIVATE_V6:
        ipaddress.ip_network(c)  # strict: raises on host bits


def test_private_matches_v2fly_and_excludes_public_carriers():
    v6 = {str(ipaddress.ip_network(c)) for c in bg.PRIVATE_V6}
    assert v6 == {"::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8"}
    nets = [ipaddress.ip_network(c) for c in bg.PRIVATE_V4 + bg.PRIVATE_V6]
    for public in ("8.8.8.8", "::ffff:8.8.8.8", "64:ff9b::808:808", "2001:4860:4860::8888"):
        a = ipaddress.ip_address(public)
        assert not any(a.version == n.version and a in n for n in nets), public


def test_fetch_registry_requires_md5():
    import hashlib
    body = b"2.3|apnic|x\n"
    good = hashlib.md5(body).hexdigest()

    def fake(responses):
        def _f(url, timeout=120, retries=3):
            r = responses[url]
            if isinstance(r, Exception):
                raise r
            return r
        return _f

    orig = bg.fetch_bytes
    try:
        bg.fetch_bytes = fake({"u": body, "u.md5": f"MD5 (x) = {good}".encode()})
        _, info = bg.fetch_registry("apnic", "u")
        assert info["md5"] == "ok"
        for md5 in (bg.GlobalBuildError("404"), b"no hash here", b"0" * 32):
            bg.fetch_bytes = fake({"u": body, "u.md5": md5})
            try:
                bg.fetch_registry("apnic", "u")
            except bg.GlobalBuildError:
                pass
            else:
                raise AssertionError(f"accepted bad checksum {md5!r}")
    finally:
        bg.fetch_bytes = orig
