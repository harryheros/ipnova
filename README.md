# IPNova — Routing-Aware IP Intelligence Dataset

IPNova is a routing-aware IPv4 dataset based on official APNIC allocation data, enhanced with ASN-aware filtering and anycast exclusion.

It provides clean IPv4 CIDR lists for:

- China (CN)
- Hong Kong (HK)
- Taiwan (TW)
- Macau (MO)

## Features

- Based on official APNIC delegated data
- ASN-aware filtering
- Excludes major anycast / CDN networks
- CN / HK / TW / MO separated
- Weekly automated updates via GitHub Actions
- CIDR aggregation for optimized output

## Dataset

| File | Description |
|------|-------------|
| `output/CN.txt` | Mainland China IPv4 CIDR list |
| `output/HK.txt` | Hong Kong IPv4 CIDR list |
| `output/TW.txt` | Taiwan IPv4 CIDR list |
| `output/MO.txt` | Macau IPv4 CIDR list |
| `output/meta.json` | Dataset metadata |

## Direct Download

```bash
https://raw.githubusercontent.com/harryheros/ipnova/main/output/CN.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/HK.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/TW.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/MO.txt
https://raw.githubusercontent.com/harryheros/ipnova/main/output/meta.json
```

## Local Generation

```bash
git clone https://github.com/harryheros/ipnova
cd ipnova
python3 generate_ip_list.py
```

## Update Schedule

- Automatically updated weekly via GitHub Actions
- Manual workflow trigger supported

## Notes

- This dataset is intended for networking, routing, filtering, and infrastructure use cases
- It does not represent precise geolocation
- HK / TW / MO are intentionally separated from CN

## License

GPL-3.0
