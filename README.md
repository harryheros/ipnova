# IPNova — Routing-Aware IP Intelligence Dataset

![License](https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-blue.svg)
![Update](https://img.shields.io/badge/update-weekly-brightgreen)
![Data Source](https://img.shields.io/badge/source-5%20RIRs%20%2B%20BGP-orange)
![Version](https://img.shields.io/badge/version-4.1.0-blue)

IPNova is an IP dataset for networking, security, compliance and attribution workflows. It has two parts:

- **Asia-Pacific regions** — CN, HK, TW, MO, JP, KR and SG IPv4, built from APNIC data and refined with BGP announcements, so Chinese cloud providers' overseas regions land where they actually operate.
- **Global dataset** — every country, IPv4 + IPv6, from all five Regional Internet Registries.

IPNova shows where address space is registered and routed. It is not a geolocation database for end users.

Part of the [Nova infrastructure toolkit](https://github.com/harryheros).

> **License**: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) for all versions, including historical commits. Commercial use requires a separate written license — see [COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md).

---

## 📦 Asia-Pacific regions

Files in [`output/`](output/), updated weekly:

| File | Format |
|---|---|
| `{CC}.txt` | CIDR list with header (`CN`, `HK`, `TW`, `MO`, `JP`, `KR`, `SG`) |
| `plain/{CC}.txt` | CIDR list, no header |
| `ipnova-apac.mmdb` | MaxMind DB format, all seven regions |
| `data.json`, `regions.json`, `json/{CC}.json` | Structured data with per-CIDR provenance |
| `nginx/`, `haproxy/`, `caddy/`, `iptables/`, `terraform/` | Ready-made configs |
| `meta.json`, `checksums.txt` | Build report, SHA-256 checksums |

```text
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/plain/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/ipnova-apac.mmdb
```

The MMDB covers the seven regions only; other addresses return no result.

---

## 🌍 Global dataset

Every country, IPv4 + IPv6. Download links: **[`global/`](global/)**.

| File | Format |
|---|---|
| `geoip.dat` | V2Ray `geoip.dat` format: one entry per country code, plus `PRIVATE` |
| `ipnova-global-country.mmdb` | MaxMind DB format |
| `country/ipv4/{CC}.txt`, `country/ipv6/{CC}.txt` | CIDR list per country |
| `meta.json`, `SHA256SUMS` | Sources, counts, checksums |

```text
https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/geoip.dat
https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/ipnova-global-country.mmdb
```

- Country codes mean where a block is **registered**. CN / HK / TW / MO / JP / KR / SG IPv4 comes from the Asia-Pacific pipeline above, so both parts agree.
- The files live on the [`data` branch](https://github.com/harryheros/ipnova/tree/data), replaced on every build with no history, so the repository does not grow.

---

## 🛡️ Reliability

- Only first-party data: RIR delegation files and RIPE Stat BGP data.
- Every RIR file must pass its published MD5 checksum.
- A build that fails validation or shrinks sharply compared with the last one is not published; the last good data stays online.
- `meta.json` records each build's sources, counts and status, including weeks when BGP data was incomplete.

---

## 🚀 Usage

```bash
git clone https://github.com/harryheros/ipnova && cd ipnova
python3 generate_ip_list.py                 # Asia-Pacific regions (standard library only)
pip install -r requirements.txt
python3 scripts/build_formats.py            # MMDB and other formats
python3 scripts/build_global.py             # Global dataset
```

`python3 generate_ip_list.py --help` lists all options.

---

## 📊 Data sources

- [APNIC](https://www.apnic.net/), [ARIN](https://www.arin.net/), [RIPE NCC](https://www.ripe.net/), [LACNIC](https://www.lacnic.net/) and [AFRINIC](https://afrinic.net/) delegation files, used under each registry's terms.
- [RIPE Stat](https://stat.ripe.net/) for BGP announcements, used under the [RIPE NCC terms](https://www.ripe.net/manage-ips-and-asns/db/terms-conditions-ripe-database).

Release history: [CHANGELOG.md](./CHANGELOG.md).

---

## 📄 License and names

- **Non-commercial use**: permitted under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
- **Commercial use** (SaaS, API resale, redistribution, paid products, use inside a company beyond research): requires prior written authorization — see [COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md), or ask at [novaod.com/licensing](https://novaod.com/licensing).
- **Project names**: "IPNova", "DomainNova", "ShieldNova", "OsNova", "HarryWrt" and "Nova Toolkit" identify projects by the original author and may not be used for derivative products without attribution.
- **Provenance**: published files contain documentation-reserved ranges (RFC 5737) that never route on the Internet but make unattributed redistribution detectable.
- **Trademarks**: MaxMind, GeoIP and GeoLite are trademarks of MaxMind, Inc. IPNova is independent and contains no MaxMind data. The MMDB files use the open MaxMind DB format; `database_type` is set to `GeoLite2-Country` only so existing reader software can open them.

If IPNova is useful to you, a ⭐ is appreciated.
