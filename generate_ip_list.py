#!/usr/bin/env python3

import urllib.request
import ipaddress
import os
import datetime
import json
from collections import defaultdict

APNIC_URL = "https://ftp.apnic.net/stats/apnic/delegated-apnic-latest"

TARGET_REGIONS = {
    "CN": "China (Mainland)",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "MO": "Macau",
}

ANYCAST_BLACKLIST = [
    "1.1.1.0/24",
    "8.8.8.0/24",
    "8.8.4.0/24",
]

def download_data():
    print("Downloading APNIC data...")
    req = urllib.request.Request(
        APNIC_URL,
        headers={"User-Agent": "ipnova"}
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode()

def parse_data(raw):
    result = defaultdict(list)

    for line in raw.splitlines():
        if not line or line.startswith("#"):
            continue

        parts = line.split("|")
        if len(parts) < 7:
            continue

        cc = parts[1]
        rtype = parts[2]

        if rtype != "ipv4" or cc not in TARGET_REGIONS:
            continue

        start = parts[3]
        count = int(parts[4])

        start_ip = ipaddress.IPv4Address(start)
        end_ip = start_ip + (count - 1)

        nets = list(ipaddress.summarize_address_range(start_ip, end_ip))

        for net in nets:
            if any(net.overlaps(ipaddress.ip_network(x)) for x in ANYCAST_BLACKLIST):
                continue
            result[cc].append(net)

    return result

def save(result):
    os.makedirs("output", exist_ok=True)

    meta = {
        "name": "IPNova",
        "generated_at": datetime.datetime.utcnow().isoformat()
    }

    for cc, nets in result.items():
        merged = sorted(ipaddress.collapse_addresses(nets))

        with open(f"output/{cc}.txt", "w") as f:
            for n in merged:
                f.write(str(n) + "\n")

        print(cc, len(merged))

    with open("output/meta.json", "w") as f:
        json.dump(meta, f, indent=2)

def main():
    raw = download_data()
    data = parse_data(raw)
    save(data)
    print("Done.")

if __name__ == "__main__":
    main()
