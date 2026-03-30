# IPNova — Routing-Aware IP Intelligence Dataset

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Update](https://img.shields.io/badge/update-weekly-brightgreen)
![Data Source](https://img.shields.io/badge/source-APNIC-orange)
![Status](https://img.shields.io/badge/status-active-success)
![Version](https://img.shields.io/badge/version-2.0.0-blue)

IPNova is a routing-aware IPv4 dataset built from official APNIC allocation data, enhanced with ASN-level filtering and dynamic prefix analysis.

IPNova is not a geolocation database.

It is a routing-aware IP dataset designed for traffic filtering, policy enforcement, and infrastructure-level decisions.

---

## ✨ Features

- Based on official APNIC delegated data (no third-party aggregation)
- ASN-level filtering using real BGP announced prefixes (RIPE Stat)
- Dynamic exclusion of major anycast / CDN / cloud providers
- Static fallback blacklist for critical anycast ranges
- CN / HK / TW / MO fully separated
- Accurate CIDR generation via `summarize_address_range`
- CIDR aggregation for optimized size and performance
- Structured JSON data layer with schema versioning
- Enriched metadata with exclusion & parsing reports
- Data sanity checks with automatic failure detection
- HTTP retry with exponential backoff
- RIPE Stat rate limiting to avoid API throttling
- CLI with `argparse` for flexible usage
- Fully automated updates via GitHub Actions with failure notifications

---

## 📦 Dataset

| File | Description |
|------|-------------|
| `output/CN.txt` | Mainland China IPv4 CIDR list |
| `output/HK.txt` | Hong Kong IPv4 CIDR list |
| `output/TW.txt` | Taiwan IPv4 CIDR list |
| `output/MO.txt` | Macau IPv4 CIDR list |
| `output/data.json` | Structured JSON dataset (schema v2.0) |
| `output/meta.json` | Enriched metadata with quality report |

Text files include metadata headers such as:

- Region
- Version
- Last updated timestamp (UTC)
- Source
- CIDR count and total IP count

---

## ⬇️ Direct Download

```bash
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/HK.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/TW.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/MO.txt
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
python3 generate_ip_list.py --skip-ripe              # Skip RIPE Stat queries
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

### Schema v2.0

`data.json` includes `schema_version`, `version`, and `total_ips` per region.

`meta.json` includes enriched quality metadata:
- ASN exclusion success/failure report
- Parsing statistics (kept, excluded, errors)
- Sanity check thresholds

This makes it easier to extend IPNova into formats such as MMDB, APIs, or additional machine-readable outputs in the future.

---

## 🔄 Update Schedule

- Automatically updated **weekly** (Monday 02:00 UTC)
- Manual trigger supported via GitHub Actions
- **Failure notifications**: auto-creates GitHub Issue on CI failure

---

## 📊 Data Sources

- APNIC delegated data  
  https://ftp.apnic.net/stats/apnic/delegated-apnic-latest

- RIPE Stat (ASN announced prefixes)  
  https://stat.ripe.net/

---

## ⚙️ Processing Pipeline

1. Fetch APNIC delegation data (with retry)
2. Extract IPv4 allocations for target regions
3. Fetch announced prefixes for blacklisted ASNs (RIPE Stat, rate-limited)
4. Merge dynamic ASN prefixes with static anycast blacklist
5. Collapse exclusion list for optimized filtering
6. Generate accurate CIDRs via address range summarization
7. Sanity check output against minimum thresholds
8. Aggregate outputs into TXT and JSON formats

---

## ⚠️ Notes

- This dataset is intended for networking, routing, filtering, and infrastructure use cases
- It does **not** represent precise geolocation
- This dataset reflects IP allocation (RIR-based), not real-time traffic origin
- HK / TW / MO are intentionally separated from CN
- Zero external dependencies — Python 3.10+ standard library only

---

## ❤️ Support

If IPNova is useful to you, consider giving it a ⭐ on GitHub.

---

## 📄 License

MIT
