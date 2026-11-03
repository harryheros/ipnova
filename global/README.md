# 🌍 IPNova Global Dataset

Every country, IPv4 + IPv6, rebuilt weekly from the delegation files of all five Regional Internet Registries (APNIC, ARIN, RIPE NCC, LACNIC, AFRINIC).

The files themselves are published on the **[`data` branch](https://github.com/harryheros/ipnova/tree/data)**, which is replaced on every build and keeps no history, so the repository stays small. This folder is the entry point.

## ⬇️ Download

| File | Use | Link |
|---|---|---|
| `geoip.dat` | V2Ray / Xray (Passwall2 GeoIP Update URL) | [Download](https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/geoip.dat) |
| `ipnova-global-country.mmdb` | MaxMind DB format, IPv4 + IPv6 | [Download](https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/ipnova-global-country.mmdb) |
| `country/ipv4/<CC>.txt` | IPv4 CIDR list per country | [Browse](https://github.com/harryheros/ipnova/tree/data/country/ipv4) |
| `country/ipv6/<CC>.txt` | IPv6 CIDR list per country | [Browse](https://github.com/harryheros/ipnova/tree/data/country/ipv6) |
| `meta.json` | Build time, sources, per-country counts | [View](https://github.com/harryheros/ipnova/blob/data/meta.json) |
| `SHA256SUMS` | Checksums | [View](https://github.com/harryheros/ipnova/blob/data/SHA256SUMS) |

URLs for apps and scripts:

```text
https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/geoip.dat
https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/ipnova-global-country.mmdb
https://cdn.jsdelivr.net/gh/harryheros/ipnova@data/country/ipv4/US.txt
```

Mirror (GitHub raw):

```text
https://raw.githubusercontent.com/harryheros/ipnova/data/geoip.dat
```

## ⚠️ Before switching

`geoip.dat` contains country codes and `PRIVATE` only. Service tags found in some third-party files, such as `geoip:telegram`, `geoip:google`, `geoip:netflix` or `geoip:ru-blocked`, are not included. Xray refuses to start when a rule refers to a tag the file does not have, so remove or replace such rules first.

Country codes mean where an address block is **registered**, not where it is used. See the [main README](../README.md#-global-dataset) for details.
