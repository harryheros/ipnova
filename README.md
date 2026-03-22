# IPNova — Routing-Aware IP Intelligence Dataset

IPNova is a high-accuracy IP dataset based on APNIC allocation data, enhanced with ASN-aware filtering and anycast exclusion.

It provides clean, structured IPv4 CIDR lists for China (CN), Hong Kong (HK), Taiwan (TW), and Macau (MO).

---

## Features

- Based on official APNIC delegated data (no third-party copying)
- Routing-aware filtering (ASN + prefix analysis)
- Excludes anycast and major CDN networks (Cloudflare, Google, etc.)
- CN / HK / TW / MO are separated (not merged)
- Weekly automated updates via GitHub Actions
- CIDR aggregation for optimized output

---

## Dataset

| File | Description |
|------|-------------|
| `CN.txt` | Mainland China IPv4 CIDR |
| `HK.txt` | Hong Kong IPv4 CIDR |
| `TW.txt` | Taiwan IPv4 CIDR |
| `MO.txt` | Macau IPv4 CIDR |

---

## Direct Download (Raw)

```bash
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/HK.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/TW.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/MO.txt
```

---

## Usage

### Clone and generate locally

```bash
git clone https://github.com/harryheros/ipnova
cd ipnova
python3 generate_ip_list.py
```

---

## Data Source

- APNIC delegated data:
  https://ftp.apnic.net/stats/apnic/delegated-apnic-latest

---

## Update Schedule

- Automatically updated weekly via GitHub Actions
- Manual trigger supported

---

## Project Structure

```
.
├── generate_ip_list.py
├── output/
│   ├── CN.txt
│   ├── HK.txt
│   ├── TW.txt
│   └── MO.txt
└── .github/workflows/update.yml
```

---

## Notes

- This dataset is designed for networking, routing, and infrastructure use cases
- It does not represent precise geolocation
- HK / TW / MO are intentionally separated from CN

---

## License

GPL-3.0
