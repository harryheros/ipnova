# IPNova

> Routing-aware IP dataset: seven Asia-Pacific regions refined with BGP, and every country from all five RIRs.

[![Version](https://img.shields.io/badge/version-v4.2.1-blue.svg)](https://github.com/harryheros/ipnova/releases)
[![License](https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-blue.svg)](#license-and-names)
[![Weekly update](https://github.com/harryheros/ipnova/actions/workflows/update.yml/badge.svg)](https://github.com/harryheros/ipnova/actions/workflows/update.yml)
[![Sources](https://img.shields.io/badge/sources-5%20RIRs%20%2B%20BGP-orange)](#data-sources)

[Asia-Pacific regions](#asia-pacific-regions) · [Global dataset](#global-dataset) · [How it is built](#how-it-is-built) · [Changelog](./CHANGELOG.md) · [License](#license-and-names)

IPNova is an IP dataset for networking, security, compliance and attribution work. It shows where address space is registered, routed and, for cloud providers, operated. It is not a geolocation database for end users.

- [**Asia-Pacific regions**](#asia-pacific-regions): CN, HK, TW, MO, JP, KR and SG, IPv4. Built from APNIC data, refined with BGP announcements.
- [**Global dataset**](#global-dataset): every country, IPv4 and IPv6. Built from all five Regional Internet Registries.

> [!NOTE]
> **License**: [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) for all versions, including historical commits. Commercial use requires a separate written license — see [COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md).

## Asia-Pacific regions

Files in [`output/`](output/), updated weekly (`{CC}` is `CN`, `HK`, `TW`, `MO`, `JP`, `KR` or `SG`):

- `{CC}.txt`: CIDR list with a header; `plain/{CC}.txt` without one.
- `ipnova-apac.mmdb`: MaxMind DB format, all seven regions.
- `data.json`, `regions.json`, `json/{CC}.json`: structured data with per-CIDR provenance.
- `nginx/`, `haproxy/`, `caddy/`, `iptables/`, `terraform/`: ready-made configs.
- `meta.json`, `checksums.txt`: build report and SHA-256 checksums.

```text
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/plain/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/ipnova-apac.mmdb
```

The MMDB covers the seven regions only; other addresses return no result.

## Global dataset

Every country, IPv4 and IPv6. Download links and notes: [`global/`](global/).

- `geoip.dat`: V2Ray `geoip.dat` format, one entry per country code plus `PRIVATE`.
- `ipnova-global-country.mmdb`: MaxMind DB format.
- `country/ipv4/{CC}.txt`, `country/ipv6/{CC}.txt`: CIDR list per country.
- `meta.json`, `SHA256SUMS`: sources, counts and checksums.

```text
https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/geoip.dat
https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/ipnova-global-country.mmdb
```

- Country codes mean where a block is **registered**. CN, HK, TW, MO, JP, KR and SG IPv4 comes from the Asia-Pacific pipeline, so both parts agree; space registered in those seven that the pipeline leaves out (anycast and CDN networks, cloud space operated elsewhere) has no country code.
- The files live on the [`data` branch](https://github.com/harryheros/ipnova/tree/data), replaced on every build with no history, so the repository does not grow.

## How it is built

- **Registered and routed.** Each region starts from APNIC's delegations and is refined with the prefixes that networks announce in BGP.
- **Cloud space where it is operated.** Chinese cloud providers register large blocks in Singapore and serve data centres worldwide from them, so each part of those blocks goes to the region it is located in, or to none.
- **Global networks left out.** Anycast, CDN and cloud operators (Cloudflare, Google including its in-country edge in China, Akamai, Fastly, AWS, Microsoft, Meta, X) are in no region.
- **Checked before it is published.** Every RIR file must pass its published MD5 checksum. A build that fails validation, or shrinks sharply compared with the last one, is not published, and the last good data stays online. `meta.json` records each build's sources, counts and status, including weeks when BGP data was incomplete.

### Data sources

- [APNIC](https://www.apnic.net/), [ARIN](https://www.arin.net/), [RIPE NCC](https://www.ripe.net/), [LACNIC](https://www.lacnic.net/) and [AFRINIC](https://afrinic.net/) delegation files, used under each registry's terms.
- [RIPEstat](https://stat.ripe.net/) for BGP announcements, and for where cloud providers' prefixes are located (RIPEstat geolocation, based on MaxMind GeoLite2: it only decides which region a prefix belongs to, and IPNova publishes no location data), used under the [RIPEstat Service Terms and Conditions](https://www.ripe.net/about-us/legal/ripestat-service-terms-and-conditions/). Commercial products or services based on RIPEstat data need the RIPE NCC's permission; an IPNova commercial license does not include it.

## Build it yourself

```bash
git clone https://github.com/harryheros/ipnova && cd ipnova
python3 generate_ip_list.py                 # Asia-Pacific regions (standard library only)
pip install -r requirements.txt
python3 scripts/build_formats.py            # MMDB and other formats
python3 scripts/build_global.py             # Global dataset
```

`python3 generate_ip_list.py --help` lists all options. Release history: [CHANGELOG.md](./CHANGELOG.md).

## License and names

- **Non-commercial use**: permitted under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
- **Commercial use** (SaaS, API resale, redistribution, paid products, use inside a company beyond research): requires prior written authorization — see [COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md), or ask at [novaod.com/licensing](https://novaod.com/licensing).
- **Project names**: "IPNova", "DomainNova", "ShieldNova", "DNSNova", "RuleNova", "OsNova", "HarryWrt" and "Nova infrastructure toolkit" identify projects by the original author and may not be used for derivative products without attribution.
- **Provenance**: published files contain documentation-reserved ranges (RFC 5737) that never route on the Internet but make unattributed redistribution detectable.
- **Trademarks**: MaxMind, GeoIP and GeoLite are trademarks of MaxMind, Inc. IPNova is independent and contains no MaxMind data. The MMDB files use the open MaxMind DB format; `database_type` is set to `GeoLite2-Country` only so existing reader software can open them.

If IPNova is useful to you, a ⭐ is appreciated.

Part of the [Nova infrastructure toolkit](https://github.com/harryheros).
