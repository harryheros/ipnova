# IPNova — Routing-Aware IP Intelligence Dataset

![License](https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-blue.svg)
![Update](https://img.shields.io/badge/update-weekly-brightgreen)
![Data Source](https://img.shields.io/badge/source-APNIC%20%2B%20BGP-orange)
![Status](https://img.shields.io/badge/status-active-success)
![Version](https://img.shields.io/badge/version-3.2.0-blue)

IPNova is a routing-aware IPv4 dataset covering key Asia-Pacific regions, built from official APNIC allocation data and enhanced with **multi-source BGP fusion** and geographic attribution. It supplements APNIC's registry data with live BGP announcements from Chinese cloud providers, resolving coverage gaps for ARIN-registered IP blocks used by Alibaba Cloud, Tencent Cloud, and others in mainland China.

IPNova is part of the [Nova infrastructure toolkit](https://github.com/harryheros), providing the IP-level foundation for infrastructure attribution.

IPNova is not a geolocation database.  
It is designed for routing-aware infrastructure analysis rather than end-user location inference.

---

> **License Notice**: All versions of this project, including historical commits, are licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Commercial use of any version requires a separate written license agreement.
> **Versioning Notice**: Previous public versions of this project may have been distributed under different license terms. All current and future releases are governed solely by the LICENSE file in this repository.

## ✨ Features

- Based on official APNIC delegated data (no third-party aggregation)
- ASN-level filtering using real BGP announced prefixes (RIPE Stat)
- Dynamic exclusion of major anycast / CDN / cloud providers
- Static fallback blacklist for critical anycast ranges
- Precise CIDR subtraction — excluded prefixes are surgically removed, not bluntly dropped
- CN / HK / TW / MO / JP / KR / SG fully separated
- **Multi-source fusion (v3.0)**: supplements APNIC data with BGP-announced prefixes from Chinese cloud provider ASNs (Alibaba, Tencent, Baidu, Huawei, ByteDance), resolving ARIN-registered IP blocks invisible to APNIC-only pipelines
- **Four-level country attribution**: L-1 persistent cache → L0 in-memory APNIC containment → L1 RIPEstat geoloc (coverage-weighted vote) → L2 ASN holder country fallback
- **ASN tier model**: Tier 1 (pure cloud), Tier 2 (mixed internet company), Tier 3 (operator backbone, hard-forbidden)
- **Rule-versioned cache**: 168-hour TTL with semantic rule versioning for instant invalidation on classification logic changes; 15× speedup from cold to warm runs
- **Defensive operator exclusion**: `FORBIDDEN_ASNS` with module-load assertion prevents accidental inclusion of China Telecom/Unicom/Mobile backbone ASNs
- Accurate CIDR generation via `summarize_address_range`
- CIDR aggregation for optimized size and performance
- Structured JSON data layer with schema versioning
- Enriched metadata with exclusion reports, parsing stats, and SHA-256 checksum
- Data sanity checks with automatic failure detection
- HTTP retry with exponential backoff
- RIPE Stat rate limiting to avoid API throttling
- APNIC format validation to catch corrupted downloads
- Per-step timing for performance diagnostics
- CLI with `argparse` for flexible usage
- Fully automated updates via GitHub Actions with failure notifications
- Zero external dependencies — Python 3.10+ standard library only

---

## 📦 Dataset

| File | Description |
|------|-------------|
| `output/CN.txt` | Mainland China IPv4 CIDR list |
| `output/HK.txt` | Hong Kong IPv4 CIDR list |
| `output/TW.txt` | Taiwan IPv4 CIDR list |
| `output/MO.txt` | Macau IPv4 CIDR list |
| `output/JP.txt` | Japan IPv4 CIDR list |
| `output/KR.txt` | South Korea IPv4 CIDR list |
| `output/SG.txt` | Singapore IPv4 CIDR list |
| `output/data.json` | Structured JSON dataset (schema v3.1) |
| `output/meta.json` | Enriched metadata with quality report |
| `output/ipnova-apac.mmdb` | MaxMind-compatible MMDB database (all 7 regions) |
| `output/regions.json` | Per-region combined JSON |
| `output/json/{CC}.json` | Per-region individual JSON |
| `output/nginx/{CC}.conf` | Nginx geo module format |
| `output/iptables/{CC}.ipset` | iptables ipset restore format |

For current CIDR counts and IP coverage per region, see `output/meta.json`.

Text files include metadata headers such as region, version, last updated timestamp (UTC), source, CIDR count and total IP count.

---

## ⬇️ Direct Download

```bash
# MMDB (MaxMind-compatible, all 7 regions in one file)
https://raw.githubusercontent.com/harryheros/ipnova/main/output/ipnova-apac.mmdb

# Plain text (per region)
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/HK.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/TW.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/MO.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/JP.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/KR.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/SG.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/data.json
https://raw.githubusercontent.com/harryheros/ipnova/main/output/meta.json
```

---

## 🚀 Usage

### Local generation

```bash
git clone https://github.com/harryheros/ipnova
cd ipnova
python3 generate_ip_list.py
```

### CLI options

```bash
python3 generate_ip_list.py --help
python3 generate_ip_list.py -o custom_output/       # Custom output directory
python3 generate_ip_list.py --skip-ripe              # Skip all RIPE Stat queries (static blacklist only)
python3 generate_ip_list.py --skip-cloud-supplement  # Skip CN cloud ASN supplement (APNIC-only output)
python3 generate_ip_list.py -v                       # Verbose (debug) logging
python3 generate_ip_list.py --version                # Show version
```

---

## 🧩 Use Cases

- Routing and traffic filtering
- Firewall / ACL configuration
- DNS / proxy traffic routing
- Network policy enforcement
- Infrastructure-level traffic control

---

## 🧱 Data Layer

IPNova provides both:

- **TXT outputs** for direct human-readable use
- **JSON outputs** for system integration, future format conversion, and automation workflows

### Schema v3.1

`data.json` includes `schema_version`, `version`, and `total_ips` per region.

`meta.json` includes enriched quality metadata:
- ASN exclusion success/failure report with mode indicator
- Parsing statistics (source networks, kept, excluded, errors)
- Sanity check thresholds
- SHA-256 checksum of `data.json` for integrity verification

This makes it easier to extend IPNova into formats such as MMDB, APIs, or additional machine-readable outputs in the future.

---

## 🔄 Update Schedule

- Automatically updated **weekly** (Monday 02:00 UTC)
- Manual trigger supported via GitHub Actions
- **Failure notifications**: auto-creates GitHub Issue on CI failure

---

## 📊 Data Sources

- **APNIC delegated data** — [https://ftp.apnic.net/stats/apnic/delegated-apnic-latest](https://ftp.apnic.net/stats/apnic/delegated-apnic-latest)  
  Data sourced from [APNIC](https://www.apnic.net/) and used in accordance with [APNIC's terms of use](https://www.apnic.net/about-apnic/legal/terms-and-conditions/).

- **RIPE Stat** (ASN announced prefixes) — [https://stat.ripe.net/](https://stat.ripe.net/)  
  Data sourced from [RIPE NCC](https://www.ripe.net/) and used in accordance with [RIPE NCC's terms of service](https://www.ripe.net/manage-ips-and-asns/db/terms-conditions-ripe-database).

---

## ⚙️ Processing Pipeline

1. Fetch APNIC delegation data (with retry + format validation)
2. Extract IPv4 allocations for target regions
3. Fetch announced prefixes for blacklisted ASNs (RIPE Stat, rate-limited)
4. Merge dynamic ASN prefixes with static anycast blacklist
5. Collapse and sort exclusion list for optimized filtering
6. Generate accurate CIDRs via address range summarization
7. Precisely subtract excluded prefixes (surgical removal, not blunt drop)
8. Sanity check output against minimum thresholds
9. Aggregate outputs into TXT and JSON formats with SHA-256 checksum

---

## 📋 Changelog

### v3.2.0

- **New**: `scripts/build_formats.py` — extended format generator
- **New**: `output/ipnova-apac.mmdb` — MaxMind-compatible MMDB database for all 7 regions
- **New**: `output/regions.json` + `output/json/{CC}.json` — per-region JSON outputs
- **New**: `output/nginx/{CC}.conf` — Nginx geo module format
- **New**: `output/iptables/{CC}.ipset` — iptables ipset restore format
- **CI**: added `mmdb-writer` dependency install step; `build_formats.py` runs automatically after each dataset update

### v3.1.1

- **Fix**: f-string syntax error in region header write (Python < 3.12 compatibility)
- **Fix**: `--skip-ripe` now correctly skips cloud supplement as well
- **New**: `--skip-cloud-supplement` flag for APNIC-only output
- **Fix**: geolocation cache now follows `--output-dir` instead of hardcoded `output/`
- **Fix**: `validate_output.py` reads `cloud_supplement` from correct metadata path
- **CI**: added syntax check and offline smoke test steps; validation failures now block commit
- **Test**: added `tests/test_core_offline.py` for network-free core regression

### v3.1.0

- **Asia-Pacific expansion**: added Japan (JP), South Korea (KR), and Singapore (SG) to target regions
- All new regions sourced from APNIC delegation data (no BGP supplement needed — APNIC coverage is complete for these regions)
- Updated sanity thresholds for new regions (JP: 3000, KR: 800, SG: 300)
- Validation script and test samples updated with JP/KR/SG domains
- Cloud supplement remains CN-specific (resolves ARIN-registered Chinese cloud provider IP blocks)

### v3.0.0

- **Multi-source BGP fusion**: supplements APNIC data with live BGP announcements from Chinese cloud provider ASNs (Alibaba, Tencent, Baidu, Huawei, ByteDance, JD, NetEase)
- **ASN tier model**: Tier 1 (pure cloud), Tier 2 (mixed internet company), Tier 3 (operator backbone, hard-forbidden)
- **Four-level country attribution**: L-1 persistent cache → L0 in-memory APNIC containment → L1 RIPEstat geoloc (coverage-weighted vote) → L2 ASN holder country fallback
- **Rule-versioned cache**: 168-hour TTL with semantic rule versioning for instant invalidation on classification logic changes; 15× speedup from cold to warm runs
- **Defensive operator exclusion**: `FORBIDDEN_ASNS` with module-load assertion prevents accidental inclusion of China Telecom/Unicom/Mobile backbone ASNs
- TW and MO regions populated for the first time via cloud supplement pipeline
- Output validation script (`scripts/validate_output.py`) with sample-based testing
- Schema version bumped to 3.0

### v2.1.0

- Precise CIDR subtraction — excluded subnets are surgically removed instead of dropping entire networks on overlap
- APNIC format validation (header line check catches error pages / corrupted downloads)
- SHA-256 checksum of `data.json` in `meta.json` for integrity verification
- Per-step timing logs for performance diagnostics
- Binary-search pre-filtering for excluded network matching (significant speedup)
- Strict UTF-8 decoding for APNIC data (fail-fast on corruption)
- Guard against zero/negative count in APNIC records
- Rate-limit sleep skipped after last ASN request (saves ~1.5s)
- Sorted ASN lists in meta.json for stable git diffs
- CI diff report written to /tmp instead of repo (no noise in output/)
- CI auto-cleans legacy files (.gitkeep, diff_report.txt)
- `time.monotonic()` for accurate elapsed time measurement

### v2.0.0

- Replaced `print()` with `logging` module
- Added CLI via `argparse`
- HTTP retry with exponential backoff
- RIPE Stat rate limiting
- Data sanity checks
- Enriched `meta.json` schema
- CI lint check, diff reporting, failure notifications

### v1.0.0

- Initial release

---

## ⚠️ Notes

- This dataset is intended for networking, routing, filtering, and infrastructure use cases
- It does **not** represent precise geolocation
- This dataset reflects IP allocation (RIR-based), not real-time traffic origin
- HK / TW / MO / JP / KR / SG are intentionally separated from CN

---

## ❤️ Support

If IPNova is useful to you, consider giving it a ⭐ on GitHub.

---

## 📄 License

[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) — Attribution-NonCommercial-ShareAlike.

- **Non-commercial use**: Permitted under the terms of CC BY-NC-SA 4.0.
- **Commercial use**: Commercial use, SaaS deployment, API resale, redistribution, or integration into paid products or services requires explicit prior written authorization from the author. See [COMMERCIAL_LICENSE.md](./COMMERCIAL_LICENSE.md) or contact via [GitHub Issues](https://github.com/harryheros/ipnova/issues).

---

Part of the [Nova infrastructure toolkit](https://github.com/harryheros).
