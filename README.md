# IPNova — Routing-Aware IP Intelligence Dataset

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Update](https://img.shields.io/badge/update-weekly-brightgreen)
![Data Source](https://img.shields.io/badge/source-APNIC-orange)
![Status](https://img.shields.io/badge/status-active-success)

IPNova is a routing-aware IPv4 dataset built from official APNIC allocation data, enhanced with ASN-level filtering and dynamic prefix analysis.

It provides clean, structured CIDR lists for:

- China (CN)
- Hong Kong (HK)
- Taiwan (TW)
- Macau (MO)

---

## ✨ Features

- Based on official APNIC delegated data (no third-party aggregation)
- ASN-level filtering using real BGP announced prefixes (RIPE Stat)
- Dynamic exclusion of major anycast / CDN / cloud providers
- Static fallback blacklist for critical anycast ranges
- CN / HK / TW / MO fully separated
- Accurate CIDR generation via `summarize_address_range`
- CIDR aggregation for optimized size and performance
- Fully automated updates via GitHub Actions

---

## 📦 Dataset

| File | Description |
|------|-------------|
| `output/CN.txt` | Mainland China IPv4 CIDR list |
| `output/HK.txt` | Hong Kong IPv4 CIDR list |
| `output/TW.txt` | Taiwan IPv4 CIDR list |
| `output/MO.txt` | Macau IPv4 CIDR list |

Each file includes metadata headers:

- Region
- Last updated timestamp (UTC)
- Source
- CIDR count

---

## ⬇️ Direct Download

```bash
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/HK.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/TW.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/MO.txt
```

---

## 🚀 Usage

### Local generation

```bash
git clone https://github.com/harryheros/ipnova
cd ipnova
python3 generate_ip_list.py
```

---

## 🧩 Use Cases

- Routing and traffic filtering
- Firewall / ACL configuration
- Network policy enforcement
- Data analysis and infrastructure research

---

## 🔄 Update Schedule

- Automatically updated **weekly**
- Manual trigger supported via GitHub Actions

---

## 📊 Data Sources

- APNIC delegated data  
  https://ftp.apnic.net/stats/apnic/delegated-apnic-latest

- RIPE Stat (ASN announced prefixes)  
  https://stat.ripe.net/

---

## ⚙️ Processing Pipeline

1. Fetch APNIC delegation data  
2. Extract IPv4 allocations for target regions  
3. Fetch announced prefixes for blacklisted ASNs (RIPE Stat)  
4. Merge dynamic ASN prefixes with static anycast blacklist  
5. Generate accurate CIDRs via address range summarization  
6. Aggregate and output optimized CIDR lists  

---

## ⚠️ Notes

- This dataset is intended for networking, routing, filtering, and infrastructure use cases
- It does **not** represent precise geolocation
- This dataset reflects IP allocation (RIR-based), not real-time traffic origin
- HK / TW / MO are intentionally separated from CN

---

## ❤️ Support

If IPNova is useful to you, consider giving it a ⭐ on GitHub.

---

## 📄 License

MIT
