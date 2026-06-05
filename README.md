# IPNova — Routing-Aware IP Intelligence Dataset

![License](https://img.shields.io/badge/license-CC%20BY--NC--SA%204.0-blue.svg)
![Update](https://img.shields.io/badge/update-weekly-brightgreen)
![Data Source](https://img.shields.io/badge/source-APNIC%20%2B%20BGP-orange)
![Status](https://img.shields.io/badge/status-active-success)
![Version](https://img.shields.io/badge/version-3.4.0-blue)

IPNova is a routing-aware IPv4 dataset covering key Asia-Pacific regions, built from official APNIC allocation data and enhanced with **multi-source BGP fusion** and geographic attribution. It supplements APNIC's registry data with live BGP announcements from Chinese cloud providers, resolving coverage gaps for ARIN-registered IP blocks used by Alibaba Cloud, Tencent Cloud, and others in mainland China.

IPNova is designed as a reusable infrastructure intelligence dataset for networking, security, compliance, and attribution workflows.

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
| `output/data.json` | Structured JSON dataset (schema v3.3, includes cidr_objects provenance) |
| `output/meta.json` | Enriched metadata with quality report |
| `output/ipnova-apac.mmdb` | MaxMind-compatible MMDB database (all 7 regions) |
| `output/regions.json` | Per-region combined JSON |
| `output/json/{CC}.json` | Per-region individual JSON |
| `output/nginx/{CC}.conf` | Nginx geo module format |
| `output/haproxy/{CC}.acl` | HAProxy ACL format |
| `output/caddy/{CC}.conf` | Caddy remote_ip matcher format |
| `output/iptables/{CC}.ipset` | iptables ipset restore format |
| `output/plain/{CC}.txt` | Plain CIDR list (no headers, for programmatic use) |
| `output/terraform/{CC}.auto.tfvars.json` | Terraform variable file |
| `output/GeoIP2-Country-compatible.mmdb` | MaxMind GeoIP2 schema-compatible alias |
| `output/GeoLite2-Country-compatible.mmdb` | MaxMind GeoLite2 schema-compatible alias |
| `output/checksums.txt` | SHA-256 checksums for all output files |

For current CIDR counts and IP coverage per region, see `output/meta.json`.

Text files include metadata headers such as region, version, last updated timestamp (UTC), source, CIDR count and total IP count.

---

## ⬇️ Direct Download

```bash
# MMDB — primary branded build
https://raw.githubusercontent.com/harryheros/ipnova/main/output/ipnova-apac.mmdb

# MMDB — schema-compatible aliases (same data as ipnova-apac.mmdb, named to avoid MaxMind's trademarks)
https://raw.githubusercontent.com/harryheros/ipnova/main/output/GeoIP2-Country-compatible.mmdb
https://raw.githubusercontent.com/harryheros/ipnova/main/output/GeoLite2-Country-compatible.mmdb

# Plain text with headers (per region)
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/HK.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/TW.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/MO.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/JP.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/KR.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/SG.txt

# Plain CIDR only — no headers (for programmatic use)
https://raw.githubusercontent.com/harryheros/ipnova/main/output/plain/CN.txt

# HAProxy / Caddy / Nginx / iptables / Terraform
https://raw.githubusercontent.com/harryheros/ipnova/main/output/haproxy/CN.acl
https://raw.githubusercontent.com/harryheros/ipnova/main/output/caddy/CN.conf
https://raw.githubusercontent.com/harryheros/ipnova/main/output/nginx/CN.conf
https://raw.githubusercontent.com/harryheros/ipnova/main/output/iptables/CN.ipset
https://raw.githubusercontent.com/harryheros/ipnova/main/output/terraform/CN.auto.tfvars.json

# Structured data
https://raw.githubusercontent.com/harryheros/ipnova/main/output/data.json
https://raw.githubusercontent.com/harryheros/ipnova/main/output/meta.json
https://raw.githubusercontent.com/harryheros/ipnova/main/output/checksums.txt
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

- Routing and traffic classification
- Firewall / ACL configuration
- DNS routing and infrastructure attribution
- Network policy enforcement
- Infrastructure-level traffic control

---

## 🧱 Data Layer

IPNova provides both:

- **TXT outputs** for direct human-readable use
- **JSON outputs** for system integration, future format conversion, and automation workflows

### Schema v3.3

`data.json` includes `schema_version`, `version`, and `total_ips` per region.

Each region now includes both:
- `cidrs` — flat list of CIDR strings (backward-compatible)
- `cidr_objects` — per-CIDR provenance objects:

```json
{"cidr": "8.152.0.0/13", "source": "bgp",   "asn": 37963, "tier": 1,    "level": "L1", "confidence": "medium"}
{"cidr": "1.0.1.0/24",   "source": "apnic",  "asn": null,  "tier": null, "level": "L0", "confidence": "high"}
```

`source` is `"bgp"` for prefixes sourced from cloud ASN BGP announcements (the ARIN blind-spot coverage), and `"apnic"` for prefixes from APNIC delegation data.

`level` (new in v3.3) records which attribution tier resolved the prefix's
region: `L0` = APNIC containment (authoritative), `L1` = RIPEstat geoloc vote,
`L2` = ASN-holder-country fallback (weakest). `confidence` is derived from
`level`: `L0`/`L-1` → `high`, `L1` → `medium`, `L2` → `low`. This means a
prefix attributed only by ASN-holder country is honestly marked `low` rather
than overstated as `high`.

> Provenance is matched to final CIDRs by IP-range intersection, so it stays
> correct even after CIDRs are collapsed or trimmed during normalization.

`meta.json` includes enriched quality metadata:
- ASN exclusion success/failure report with mode indicator
- Parsing statistics (source networks, kept, excluded, errors)
- Cloud supplement stats: per-level signal attribution (L0/L1/L2/L3)
- Sanity check thresholds
- SHA-256 checksum of `data.json` for integrity verification

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
10. Build extended formats: MMDB (+ schema-compatible aliases), HAProxy, Caddy, Nginx, iptables, plain CIDR, Terraform

---

## 📋 Changelog

### v3.4.0

- **Bugfix (provenance)**: `cidr_objects` provenance was matched to final CIDRs by exact string, but a BGP supplement prefix's string changes whenever it is collapsed or trimmed during normalization — so a large share of BGP-sourced prefixes were silently mislabelled `source: "apnic"`. Provenance is now matched by **IP-range intersection**, which survives any collapse/trim. The core region CIDR lists (TXT/MMDB/etc.) were never affected — only the `cidr_objects` metadata.
- **Bugfix (confidence)**: `confidence` was hardcoded to `"high"` for every prefix, so `L2` (ASN-holder-country fallback, the weakest signal) was advertised as high-confidence. The attribution `level` (L0/L1/L2) is now carried through and `confidence` is derived from it: `L0`/`L-1` → `high`, `L1` → `medium`, `L2` → `low`.
- **Schema v3.3**: `cidr_objects` gains a `level` field exposing the attribution tier. `confidence` values now span `high`/`medium`/`low` (previously always `high`). Backward-compatible additive change — existing `cidrs`, `source`, `asn`, `tier` fields are unchanged.
- **Testing**: added `test_provenance_survives_collapse_and_level_confidence` — a regression guard that constructs a collapse scenario and asserts BGP prefixes keep their provenance and L2 prefixes are downgraded to `low`.

### v3.3.0

- **Architecture**: extracted `TARGET_REGIONS` into `regions.py` as a single source of truth, eliminating definition drift between the build pipeline and `mmdb/schema.py`
- **Correctness**: `enforce_mutual_exclusivity` now treats APNIC results as Tier 1 (authoritative) and BGP supplement as Tier 2 (gap-filling), so a misclassified supplement prefix can no longer displace an APNIC-assigned region block
- **Reliability**: per-host RIPE Stat throttling enforced inside `http_get` (canonical hostname matching via `urlparse`, not substring), so callers can no longer accidentally bypass rate limits, and spoofed URLs cannot trigger throttling
- **Operations**: `MAX_L2_RATIO` threshold tightened from 0.60 to 0.10 and downgraded from CI gate to loud warning — transient RIPEstat hiccups no longer block weekly publishes, while genuine L1 degradation is still surfaced
- **MMDB validator**: rewritten as an explicit round-trip check rather than an "accuracy" check it could not actually perform; tolerates individual stale samples (warn-only), fails only when an entire region has zero matching samples
- **Security/Provenance**: canary CIDR set embedded in published artifacts using RFC5737 documentation-reserved ranges (harmless for downstream firewall/ACL use, but enables forensic attribution of unattributed redistributions); `meta.json` gains a `build` section recording the commit SHA that produced the artifact
- **HTTP**: `User-Agent` is now derived from `__version__` and includes the repository URL for contactability (was hardcoded and had drifted)
- **CLI**: new `--skip-canary` flag for verification builds
- **MaxMind aliases renamed**: `GeoIP2-Country.mmdb` → `GeoIP2-Country-compatible.mmdb` (and likewise for GeoLite2). The `-compatible` suffix avoids using MaxMind's trademarked product names directly.
- **iptables**: `ipset` maxelem sized dynamically (`max(num_cidrs * 2, 65536)`, rounded to next power of two) so future region growth doesn't silently truncate
- **MMDB validator**: expanded MO sample set so a single IP holder change can't fail the region-coverage gate
- **Documentation**: project-language consistency — translated `IPNOVA_MULTISOURCE_PROPOSAL.md` to English (`P0_5_POSTMORTEM.md` already English)
- **Testing**: 4 new offline tests covering tier-layered enforce, hostname-based RIPE throttle classification, MMDB round-trip semantics, regions single-source-of-truth, User-Agent derivation, and canary CIDR well-formedness — 14 tests total

### v3.2.1

- **New**: `output/cidr_objects` per-CIDR provenance metadata in `data.json` (schema v3.2) — each CIDR now carries `source`, `asn`, `tier`, and `confidence` fields
- **New**: `output/GeoIP2-Country-compatible.mmdb` + `output/GeoLite2-Country-compatible.mmdb` — schema-compatible aliases (named with `-compatible` suffix to avoid using MaxMind's trademarked product names directly)
- **New**: `output/haproxy/{CC}.acl` — HAProxy ACL format
- **New**: `output/caddy/{CC}.conf` — Caddy remote_ip matcher format
- **New**: `output/plain/{CC}.txt` — pure CIDR files with no comment headers (for programmatic consumption)
- **New**: `output/terraform/{CC}.auto.tfvars.json` — Terraform-compatible variable files
- **New**: `output/checksums.txt` — SHA-256 checksums covering all output files
- **CI**: `build_formats.py` now runs with `--release-assets`, generating `ipnova-formats.tar.gz` and `SHA256SUMS` on every update
- **Internal**: `_ASN_TIER_MAP` added for O(1) tier lookup; `build_cloud_supplementary_networks` returns provenance alongside networks

### v3.2.0

- **New**: `scripts/build_formats.py` — extended format generator
- **New**: `output/ipnova-apac.mmdb` — MaxMind-compatible MMDB database for all 7 regions
- **New**: `output/regions.json` + `output/json/{CC}.json` — per-region JSON outputs
- **New**: `output/nginx/{CC}.conf` — Nginx geo module format
- **New**: `output/iptables/{CC}.ipset` — iptables ipset restore format
- **CI**: added `mmdbwriter` dependency install step; `build_formats.py` runs automatically after each dataset update

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

## 🛡️ Names and Provenance

**Project names** — "IPNova", "DomainNova", "ShieldNova", "OsNova", "HarryWrt", and the umbrella "Nova Toolkit" — identify projects authored and maintained by the original author. Use of these names to describe forked, repackaged, or derivative products without attribution may constitute identity confusion and is not authorized.

**Provenance fingerprinting** — published artifacts contain documentation-reserved CIDR ranges (RFC 5737) embedded for forensic attribution. These ranges are harmless for downstream use (they never route on the public Internet) but make unattributed redistribution detectable. See `regions.py` and `meta.json` for the per-release fingerprint set.

If you build something useful on top of IPNova, attribution and a backlink to this repository are appreciated; if you intend to do so commercially, please reach out via the channels above.

---

Part of the [Nova infrastructure toolkit](https://github.com/harryheros).
