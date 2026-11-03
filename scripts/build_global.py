#!/usr/bin/env python3
"""
build_global.py — IPNova global country dataset (IPv4 + IPv6).

Source: the delegation files of all five Regional Internet Registries
(APNIC, ARIN, RIPE NCC, LACNIC, AFRINIC) — first-party registry data only.
The seven Asia-Pacific regions IPNova already refines (CN/HK/TW/MO/JP/KR/SG)
use IPNova's own IPv4 results (output/<CC>.txt, BGP-corrected), so the
global files never disagree with the regional ones.

Output (one directory, published as the `data` branch by CI):

    geoip.dat                       V2Ray / Xray GeoIP list, every country + PRIVATE
    ipnova-global-country.mmdb      MaxMind DB format, IPv4 + IPv6,
                                    database_type "GeoLite2-Country"
    country/ipv4/<CC>.txt           plain CIDR lists
    country/ipv6/<CC>.txt
    meta.json                       sources, per-country counts, build info
    SHA256SUMS
    README.md

The data says where an address block is REGISTERED (the RIR's country
code), not where it is used. Codes are the RIRs' own: ISO 3166 alpha-2
plus a few registry codes such as EU and AP.

Usage:
    python3 scripts/build_global.py --output dist-global [--previous old_meta.json]
                                    [--regions-dir output] [--allow-shrink]
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generate_ip_list as core  # noqa: E402  (USER_AGENT, __version__)
from regions import TARGET_REGIONS  # noqa: E402

log = logging.getLogger("ipnova.global")

RIRS = {
    "apnic":   "https://ftp.apnic.net/stats/apnic/delegated-apnic-extended-latest",
    "arin":    "https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest",
    "ripencc": "https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest",
    "lacnic":  "https://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-extended-latest",
    "afrinic": "https://ftp.afrinic.net/pub/stats/afrinic/delegated-afrinic-extended-latest",
}

# A registry file with fewer IPv4 records than this is truncated or broken;
# the build stops instead of publishing a world map with a hole in it.
# Deliberately conservative (real files are several times larger).
MIN_IPV4_RECORDS = {"apnic": 10000, "arin": 20000, "ripencc": 30000,
                    "lacnic": 3000, "afrinic": 1000}

USED_STATUS = {"allocated", "assigned"}

# IANA special-purpose address blocks (RFC 6890 registries) -> geoip:private.
# Rules such as "geoip:private -> direct" are common; a geoip.dat without
# this tag makes Xray refuse to start.
PRIVATE_V4 = [
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
    "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
    "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
]
# Same set as v2fly/geoip "private". Deliberately NOT included: blocks that
# carry or translate public traffic (::ffff:0:0/96 IPv4-mapped,
# 64:ff9b::/96 NAT64) — with "geoip:private -> direct" they would send
# real Internet traffic around the proxy.
PRIVATE_V6 = ["::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8"]

# jsDelivr serves GitHub files up to 20 MB; GitHub rejects files over 100 MB.
WARN_FILE_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 95 * 1024 * 1024

# Shrink guard: compared with the last published build.
MIN_RATIO_ADDRESSES = 0.80
MIN_RATIO_COUNTRIES = 0.90


class GlobalBuildError(RuntimeError):
    pass


# ---------------------------------------------------------------- fetch

def _md5_from_file(text: str) -> str | None:
    m = re.search(r"\b([0-9a-fA-F]{32})\b", text or "")
    return m.group(1).lower() if m else None


def fetch_bytes(url: str, timeout: int = 120, retries: int = 3) -> bytes:
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": core.USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(5 * attempt)
    raise GlobalBuildError(f"download failed after {retries} attempts: {url} ({last})")


def fetch_registry(name: str, url: str) -> tuple[str, dict]:
    """Download one delegation file and check it against its published MD5."""
    info = {"url": url, "md5": "unchecked"}
    raw = fetch_bytes(url)
    # Strict: no checksum, no publish. The previous data branch stays live.
    try:
        expected = _md5_from_file(fetch_bytes(url + ".md5", timeout=30, retries=3).decode("ascii", "replace"))
    except GlobalBuildError as e:
        raise GlobalBuildError(f"{name}: checksum file unavailable ({e}); refusing to publish") from e
    if not expected:
        raise GlobalBuildError(f"{name}: checksum file has no MD5 value; refusing to publish")
    if hashlib.md5(raw).hexdigest() != expected:
        raise GlobalBuildError(f"{name}: MD5 mismatch (download corrupt or truncated)")
    info["md5"] = "ok"
    return raw.decode("utf-8", "replace"), info


# ---------------------------------------------------------------- parse

def parse_delegated(text: str, registry: str) -> tuple[dict, dict]:
    """Parse an RIR delegated(-extended) file.

    Returns ({"ipv4": [(start, end, cc)], "ipv6": [...]}, info) with integer
    address ranges (inclusive). Only allocated/assigned records with a real
    country code are kept.
    """
    out = {"ipv4": [], "ipv6": []}
    info = {"ipv4_records": 0, "ipv6_records": 0, "serial": None, "skipped": 0}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split("|")
        if len(f) < 7:
            continue
        if f[0] and f[0][0].isdigit() and len(f) >= 3:      # version line
            info["serial"] = f[2]
            continue
        if f[5] == "summary" or f[1] == "*":
            continue
        cc, typ, start, value, status = f[1].upper(), f[2], f[3], f[4], f[6].lower()
        if typ not in ("ipv4", "ipv6") or status not in USED_STATUS:
            continue
        if not re.fullmatch(r"[A-Z]{2}", cc) or cc == "ZZ":
            info["skipped"] += 1
            continue
        try:
            if typ == "ipv4":
                s = int(ipaddress.IPv4Address(start))
                n = int(value)
                if n <= 0 or s + n - 1 > 0xFFFFFFFF:
                    raise ValueError
                out["ipv4"].append((s, s + n - 1, cc))
            else:
                net = ipaddress.IPv6Network(f"{start}/{int(value)}", strict=False)
                out["ipv6"].append((int(net.network_address), int(net.broadcast_address), cc))
        except ValueError:
            info["skipped"] += 1
            continue
        info[typ + "_records"] += 1
    return out, info


# ---------------------------------------------------------------- range maths

def make_exclusive(ranges: list) -> tuple[list, int]:
    """Sort (start, end, cc) ranges and trim overlaps so every address has
    one country. The earlier-starting (then larger) range wins; overlaps are
    rare (blocks in transfer between registries). Returns (ranges, conflicts)."""
    ranges = sorted(ranges, key=lambda r: (r[0], -r[1]))
    out, last_end, conflicts = [], -1, 0
    for s, e, cc in ranges:
        if e <= last_end:
            conflicts += 1
            continue
        if s <= last_end:
            conflicts += 1
            s = last_end + 1
        out.append((s, e, cc))
        last_end = e
    return out, conflicts


def subtract(ranges: list, holes: list) -> list:
    """Remove the (start, end) intervals in `holes` from (start, end, cc) ranges."""
    holes = merge([(s, e) for s, e in holes])
    out, j = [], 0
    for s, e, cc in sorted(ranges):
        cur = s
        while j < len(holes) and holes[j][1] < cur:
            j += 1
        k = j
        while k < len(holes) and holes[k][0] <= e:
            hs, he = holes[k]
            if hs > cur:
                out.append((cur, hs - 1, cc))
            cur = max(cur, he + 1)
            if cur > e:
                break
            k += 1
        if cur <= e:
            out.append((cur, e, cc))
    return out


def merge(ranges: list) -> list:
    """Coalesce overlapping/adjacent (start, end) intervals."""
    out = []
    for s, e in sorted(ranges):
        if out and s <= out[-1][1] + 1:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def to_cidrs(intervals: list, version: int) -> list:
    cls = ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address
    cidrs = []
    for s, e in intervals:
        cidrs.extend(ipaddress.summarize_address_range(cls(s), cls(e)))
    return cidrs


def load_region_cidrs(regions_dir: Path) -> dict:
    """IPNova's refined IPv4 lists for the seven regions (output/<CC>.txt)."""
    out = {}
    for cc in TARGET_REGIONS:
        path = regions_dir / f"{cc}.txt"
        if not path.exists():
            raise GlobalBuildError(f"{path} missing — run generate_ip_list.py first")
        ranges = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            net = ipaddress.IPv4Network(line, strict=False)
            ranges.append((int(net.network_address), int(net.broadcast_address)))
        if not ranges:
            raise GlobalBuildError(f"{path} is empty")
        out[cc] = merge(ranges)
    return out


def build_countries(parsed: list, regions: dict) -> tuple[dict, dict]:
    """Combine registry records into exclusive per-country CIDR lists.

    parsed:  list of {"ipv4": [...], "ipv6": [...]} from parse_delegated
    regions: {cc: [(start, end)]} IPv4 overrides from IPNova
    Returns ({cc: {"ipv4": [IPv4Network], "ipv6": [IPv6Network]}}, stats)
    """
    v4 = [r for p in parsed for r in p["ipv4"]]
    v6 = [r for p in parsed for r in p["ipv6"]]
    v4, c4 = make_exclusive(v4)
    v6, c6 = make_exclusive(v6)

    # IPv4 of the seven regions comes from IPNova; their address space is
    # removed from every other country first (e.g. an Alibaba Cloud block
    # registered in the US but announced from Singapore is SG in IPNova).
    override = [iv for ivs in regions.values() for iv in ivs]
    v4 = [r for r in v4 if r[2] not in regions]
    v4 = subtract(v4, override)
    for cc, ivs in regions.items():
        v4.extend((s, e, cc) for s, e in ivs)

    per = {}
    for fam, rows, ver in (("ipv4", v4, 4), ("ipv6", v6, 6)):
        by_cc: dict[str, list] = {}
        for s, e, cc in rows:
            by_cc.setdefault(cc, []).append((s, e))
        for cc, ivs in by_cc.items():
            per.setdefault(cc, {"ipv4": [], "ipv6": []})[fam] = to_cidrs(merge(ivs), ver)
    stats = {"conflicts_trimmed": {"ipv4": c4, "ipv6": c6},
             "apac_ipv4_from_ipnova": sorted(regions)}
    return dict(sorted(per.items())), stats


# ---------------------------------------------------------------- geoip.dat

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field_bytes(field: int, payload: bytes) -> bytes:
    return _varint(field << 3 | 2) + _varint(len(payload)) + payload


def encode_geoip_dat(entries: dict) -> bytes:
    """V2Ray/Xray GeoIPList protobuf (app/router/config.proto):

        message CIDR      { bytes ip = 1; uint32 prefix = 2; }
        message GeoIP     { string country_code = 1; repeated CIDR cidr = 2; }
        message GeoIPList { repeated GeoIP entry = 1; }

    entries: {tag: [ip_network, ...]}; tags are written upper-case, like
    the widely used geoip.dat files (Xray matches them case-insensitively).
    """
    out = bytearray()
    for tag in sorted(entries):
        body = bytearray(_field_bytes(1, tag.upper().encode("ascii")))
        for net in entries[tag]:
            cidr = _field_bytes(1, net.network_address.packed) + _varint(2 << 3 | 0) + _varint(net.prefixlen)
            body += _field_bytes(2, cidr)
        out += _field_bytes(1, bytes(body))
    return bytes(out)


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = val = 0
    while True:
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7


def decode_geoip_dat(buf: bytes) -> dict:
    """Inverse of encode_geoip_dat (used by the build's own check)."""
    def fields(b):
        i = 0
        while i < len(b):
            key, i = _read_varint(b, i)
            wt = key & 7
            if wt == 2:
                n, i = _read_varint(b, i)
                yield key >> 3, b[i:i + n]
                i += n
            elif wt == 0:
                v, i = _read_varint(b, i)
                yield key >> 3, v
            else:
                raise ValueError(f"unexpected wire type {wt}")
    out = {}
    for f, entry in fields(buf):
        if f != 1:
            continue
        tag, nets = None, []
        for ef, ev in fields(entry):
            if ef == 1:
                tag = ev.decode("ascii")
            elif ef == 2:
                ip, prefix = b"", 0
                for cf, cv in fields(ev):
                    if cf == 1:
                        ip = cv
                    elif cf == 2:
                        prefix = cv
                nets.append(ipaddress.ip_network((ipaddress.ip_address(ip), prefix)))
        out[tag] = nets
    return out


# ---------------------------------------------------------------- MMDB

def build_mmdb(per: dict, path: Path) -> None:
    from mmdb_writer import MMDBWriter
    from netaddr import IPSet

    names = {cc: TARGET_REGIONS[cc] for cc in TARGET_REGIONS}
    writer = MMDBWriter(
        ip_version=6, ipv4_compatible=True,
        database_type="GeoLite2-Country", languages=["en"],
        description={"en": (
            "IPNova global country database (IPv4 + IPv6) from the delegation "
            "files of APNIC, ARIN, RIPE NCC, LACNIC and AFRINIC; CN/HK/TW/MO/JP/KR/SG "
            "IPv4 refined by IPNova. Registration country, not geolocation. "
            "Independent dataset in MaxMind DB format; not affiliated with or "
            "endorsed by MaxMind, Inc. and contains no MaxMind data. "
            "https://github.com/harryheros/ipnova")},
    )
    for cc, fams in per.items():
        cidrs = [str(n) for n in fams["ipv4"] + fams["ipv6"]]
        if not cidrs:
            continue
        country = {"iso_code": cc}
        if cc in names:
            country["names"] = {"en": names[cc]}
        writer.insert_network(IPSet(cidrs), {"country": country, "source": "ipnova"})
    tmp = path.with_suffix(".tmp")
    writer.to_db_file(str(tmp))
    os.replace(tmp, path)


def check_mmdb(path: Path, per: dict) -> None:
    """Round-trip: one address of each of the 30 largest countries resolves back."""
    try:
        import maxminddb
    except ImportError:
        log.warning("maxminddb not installed — skipping MMDB round-trip check")
        return
    biggest = sorted(per, key=lambda c: -sum(n.num_addresses for n in per[c]["ipv4"]))[:30]
    with maxminddb.open_database(str(path)) as r:
        if r.metadata().database_type != "GeoLite2-Country":
            raise GlobalBuildError("global MMDB has the wrong database_type")
        for cc in biggest:
            for fam in ("ipv4", "ipv6"):
                if not per[cc][fam]:
                    continue
                ip = str(per[cc][fam][0].network_address)
                got = (r.get(ip) or {}).get("country", {}).get("iso_code")
                if got != cc:
                    raise GlobalBuildError(f"global MMDB round-trip: {ip} -> {got}, expected {cc}")


# ---------------------------------------------------------------- output

def write_lists(per: dict, out: Path) -> None:
    for fam in ("ipv4", "ipv6"):
        d = out / "country" / fam
        d.mkdir(parents=True, exist_ok=True)
        for cc, fams in per.items():
            if fams[fam]:
                (d / f"{cc}.txt").write_text("\n".join(map(str, fams[fam])) + "\n", encoding="utf-8")


def shrink_problems(meta: dict, previous: dict | None) -> list:
    if not previous:
        return []
    problems = []
    for key in ("ipv4_addresses", "ipv6_prefixes_48"):
        old, new = previous.get("totals", {}).get(key, 0), meta["totals"][key]
        if old and new < old * MIN_RATIO_ADDRESSES:
            problems.append(f"{key} {old} -> {new}")
    old, new = previous.get("totals", {}).get("countries", 0), meta["totals"]["countries"]
    if old and new < old * MIN_RATIO_COUNTRIES:
        problems.append(f"countries {old} -> {new}")
    return problems


DATA_README = """# IPNova global dataset (`data` branch)

Generated weekly by https://github.com/harryheros/ipnova — this branch is
force-pushed on every build and keeps no history.

| File | Content |
|---|---|
| `geoip.dat` | V2Ray / Xray GeoIP list: every country code, plus `PRIVATE` |
| `ipnova-global-country.mmdb` | MaxMind DB format, IPv4 + IPv6, `database_type` = `GeoLite2-Country` |
| `country/ipv4/<CC>.txt`, `country/ipv6/<CC>.txt` | Plain CIDR lists |
| `meta.json` | Sources, per-country counts, build info |
| `SHA256SUMS` | Checksums of every file |

Source: the delegation files of APNIC, ARIN, RIPE NCC, LACNIC and AFRINIC.
CN / HK / TW / MO / JP / KR / SG IPv4 comes from IPNova's routing-aware
pipeline. The data shows where an address block is **registered**, not
where it is used. Country codes are the registries' own (ISO 3166 alpha-2,
plus registry codes such as `EU` and `AP`).

Licence: CC BY-NC-SA 4.0 — see the main branch.
"""


def build(output: Path, regions_dir: Path, previous: dict | None,
          allow_shrink: bool, texts: dict | None = None) -> dict:
    """texts: optional {registry: file content} (tests); otherwise downloaded."""
    output.mkdir(parents=True, exist_ok=True)
    parsed, sources = [], {}
    for name, url in RIRS.items():
        if texts is not None:
            body, info = texts[name], {"url": url, "md5": "unchecked"}
        else:
            log.info("Fetching %s ...", name)
            body, info = fetch_registry(name, url)
        p, pinfo = parse_delegated(body, name)
        info.update(pinfo)
        if pinfo["ipv4_records"] < MIN_IPV4_RECORDS[name] and texts is None:
            raise GlobalBuildError(
                f"{name}: only {pinfo['ipv4_records']} IPv4 records "
                f"(expected >= {MIN_IPV4_RECORDS[name]}); refusing to publish")
        log.info("  %s: %d IPv4 + %d IPv6 records (serial %s, md5 %s)", name,
                 pinfo["ipv4_records"], pinfo["ipv6_records"], pinfo["serial"], info["md5"])
        parsed.append(p)
        sources[name] = info

    per, bstats = build_countries(parsed, load_region_cidrs(regions_dir))

    v4_total = sum(n.num_addresses for f in per.values() for n in f["ipv4"])
    v6_48 = sum(n.num_addresses >> 80 if n.prefixlen <= 48 else 1
                for f in per.values() for n in f["ipv6"])
    meta = {
        "project": "ipnova",
        "dataset": "global",
        "version": core.__version__,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "RIR delegation files (APNIC, ARIN, RIPE NCC, LACNIC, AFRINIC); "
                  "CN/HK/TW/MO/JP/KR/SG IPv4 from IPNova",
        "meaning": "registration country, not geolocation",
        "sources": sources,
        "build": bstats,
        "totals": {
            "countries": len(per),
            "ipv4_cidrs": sum(len(f["ipv4"]) for f in per.values()),
            "ipv6_cidrs": sum(len(f["ipv6"]) for f in per.values()),
            "ipv4_addresses": v4_total,
            "ipv6_prefixes_48": v6_48,
        },
        "countries": {cc: {"ipv4_cidrs": len(f["ipv4"]),
                           "ipv4_addresses": sum(n.num_addresses for n in f["ipv4"]),
                           "ipv6_cidrs": len(f["ipv6"])} for cc, f in per.items()},
    }
    problems = shrink_problems(meta, previous)
    if problems:
        msg = "global dataset shrank compared with the last published build: " + "; ".join(problems)
        if not allow_shrink:
            raise GlobalBuildError(msg + " — not published (use --allow-shrink if intended)")
        log.warning("%s (continuing: --allow-shrink)", msg)

    # geoip.dat
    entries = {cc: f["ipv4"] + f["ipv6"] for cc, f in per.items()}
    entries["PRIVATE"] = [ipaddress.ip_network(c) for c in PRIVATE_V4 + PRIVATE_V6]
    dat = encode_geoip_dat(entries)
    back = decode_geoip_dat(dat)
    if {k: [str(n) for n in v] for k, v in back.items()} != \
            {k.upper(): [str(n) for n in v] for k, v in entries.items()}:
        raise GlobalBuildError("geoip.dat round-trip mismatch")
    (output / "geoip.dat").write_bytes(dat)

    write_lists(per, output)
    mmdb_path = output / "ipnova-global-country.mmdb"
    build_mmdb(per, mmdb_path)
    check_mmdb(mmdb_path, per)

    (output / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    (output / "README.md").write_text(DATA_README, encoding="utf-8")

    files = sorted(p for p in output.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    for p in files:
        size = p.stat().st_size
        if size > MAX_FILE_BYTES:
            raise GlobalBuildError(f"{p.name} is {size // 2**20} MB, over GitHub's file limit")
        if size > WARN_FILE_BYTES:
            log.warning("%s is %d MB — over jsDelivr's 20 MB limit; use the raw URL",
                        p.relative_to(output), size // 2**20)
    with open(output / "SHA256SUMS", "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(output).as_posix()}\n")

    log.info("Global dataset: %d countries, %d IPv4 + %d IPv6 CIDRs, geoip.dat %d KB",
             meta["totals"]["countries"], meta["totals"]["ipv4_cidrs"],
             meta["totals"]["ipv6_cidrs"], len(dat) // 1024)
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the IPNova global country dataset")
    ap.add_argument("--output", default="dist-global")
    ap.add_argument("--regions-dir", default=str(ROOT / "output"))
    ap.add_argument("--previous", help="meta.json of the last published global build")
    ap.add_argument("--allow-shrink", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
                        datefmt="%H:%M:%S")
    previous = None
    if args.previous and Path(args.previous).exists():
        try:
            previous = json.loads(Path(args.previous).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("could not read %s; shrink guard skipped", args.previous)
    try:
        build(Path(args.output), Path(args.regions_dir), previous, args.allow_shrink)
    except GlobalBuildError as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
