# IPNova — Routing-Aware IP Intelligence Dataset

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Update](https://img.shields.io/badge/update-weekly-brightgreen)
![Data Source](https://img.shields.io/badge/source-APNIC-orange)
![Status](https://img.shields.io/badge/status-active-success)

IPNova is a routing-aware IPv4 dataset derived from official APNIC allocation data, designed for infrastructure, filtering, and network intelligence use cases.

It provides clean, structured CIDR lists for:

- China (CN)
- Hong Kong (HK)
- Taiwan (TW)
- Macau (MO)

---

## ✨ Features

- Based on official APNIC delegated data (no third-party aggregation)
- ASN-aware filtering for improved routing relevance
- Excludes major anycast and CDN networks (Cloudflare, Google, etc.)
- CN / HK / TW / MO fully separated
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
| `output/meta.json` | Dataset metadata |

---

## ⬇️ Direct Download

```bash
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/HK.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/TW.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/MO.txt
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

## 📊 Data Source

- APNIC delegated data  
  https://ftp.apnic.net/stats/apnic/delegated-apnic-latest

---

## ⚠️ Notes

- This dataset is intended for networking, routing, filtering, and infrastructure use cases
- It does **not** represent precise geolocation
- This dataset reflects IP allocation (RIR-based), not real-time geolocation or traffic origin
- HK / TW / MO are intentionally separated from CN

---

## ❤️ Support

If IPNova is useful to you, consider giving it a ⭐ on GitHub.

---

## 📄 License

MIT
