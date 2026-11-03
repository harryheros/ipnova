# IPNova global dataset (`data` branch)

Generated weekly by https://github.com/harryheros/ipnova — this branch is
force-pushed on every build and keeps no history.

| File | Content |
|---|---|
| `geoip.dat` | V2Ray `geoip.dat` format: every country code, plus `PRIVATE` |
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
