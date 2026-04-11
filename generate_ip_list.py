#!/usr/bin/env python3
import requests
import time
import ipaddress
from collections import defaultdict

# =========================
# CONFIG
# =========================

CN_CLOUD_ASNS = {
    37963: "Alibaba CN",
    45102: "Alibaba Global",
    132203: "Tencent Cloud Intl",
    136907: "Huawei Cloud Intl",
}

TIER2_ASNS = {
    45090: "Tencent Mixed",
    38365: "Baidu",
    58593: "ByteDance",
}

FORBIDDEN_ASNS = {
    58466: "China Telecom",
}

GEOLOC_API = "https://stat.ripe.net/data/geoloc/data.json?resource={}"
ASN_PREFIX_API = "https://stat.ripe.net/data/announced-prefixes/data.json?resource=AS{}"

GEOLOC_TIMEOUT = 5
GEOLOC_RETRIES = 1

ASN_TIMEOUT = 8
ASN_RETRIES = 2

REQUEST_INTERVAL = 0.3

_ASN_COUNTRY_CACHE = {}

# =========================
# HTTP
# =========================

def http_get(url, timeout=10, retries=2):
    for _ in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            return r.json()
        except Exception:
            time.sleep(1)
    return None


# =========================
# DATA FETCH
# =========================

def fetch_asn_prefixes(asn):
    data = http_get(ASN_PREFIX_API.format(asn))
    if not data:
        return []
    return [ipaddress.ip_network(p["prefix"]) for p in data["data"]["prefixes"]]


def fetch_geoloc(prefix):
    data = http_get(GEOLOC_API.format(prefix), GEOLOC_TIMEOUT, GEOLOC_RETRIES)
    if not data:
        return None

    locs = data["data"]["locations"]
    if not locs:
        return None

    best = max(locs, key=lambda x: x.get("coverage", 0))
    return best.get("country")


def fetch_asn_country(asn):
    if asn in _ASN_COUNTRY_CACHE:
        return _ASN_COUNTRY_CACHE[asn]

    url = f"https://stat.ripe.net/data/as-overview/data.json?resource=AS{asn}"
    data = http_get(url, ASN_TIMEOUT, ASN_RETRIES)

    if not data:
        return None

    holder = data["data"].get("holder", "")

    if "CN" in holder or "China" in holder:
        cc = "CN"
    else:
        cc = None

    _ASN_COUNTRY_CACHE[asn] = cc
    return cc


# =========================
# CLASSIFICATION
# =========================

def classify_prefix(prefix, asn):
    # L1: geoloc
    cc = fetch_geoloc(prefix)
    time.sleep(REQUEST_INTERVAL)

    if cc:
        return cc, "L1"

    # L2: ASN fallback
    cc = fetch_asn_country(asn)
    if cc:
        return cc, "L2"

    # L3: disabled for performance
    return None, "L3"


# =========================
# CLOUD SUPPLEMENT
# =========================

def build_cloud_supplementary_networks():
    print("[cloud-supp] start")

    cn_prefixes = []
    stats = defaultdict(int)

    for asn, name in CN_CLOUD_ASNS.items():
        print(f"[cloud-supp] ASN {asn} ({name})")

        prefixes = fetch_asn_prefixes(asn)

        cn_candidates = []

        for p in prefixes:
            cc, level = classify_prefix(str(p), asn)

            if cc == "CN":
                cn_candidates.append(p)

                if level == "L1":
                    stats["l1_success"] += 1
                elif level == "L2":
                    stats["l2_fallback"] += 1

            else:
                stats["dropped"] += 1

        # collapse only after classification (safe)
        collapsed = list(ipaddress.collapse_addresses(cn_candidates))
        cn_prefixes.extend(collapsed)

        print(f"  -> {len(prefixes)} -> {len(collapsed)} (CN)")

    print("[cloud-supp] done")
    print(dict(stats))

    return cn_prefixes


# =========================
# APNIC
# =========================

def load_apnic_cn():
    print("[apnic] loading")

    url = "https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest"
    r = requests.get(url)
    lines = r.text.splitlines()

    cn_prefixes = []

    for line in lines:
        parts = line.split("|")
        if len(parts) < 7:
            continue

        if parts[1] == "CN" and parts[2] == "ipv4":
            start = parts[3]
            count = int(parts[4])
            net = ipaddress.ip_network(
                f"{start}/{32 - (count.bit_length() - 1)}",
                strict=False
            )
            cn_prefixes.append(net)

    return cn_prefixes


# =========================
# MAIN
# =========================

def main():
    all_prefixes = set()

    # APNIC baseline
    apnic = load_apnic_cn()
    all_prefixes.update(apnic)

    # Cloud supplement
    cloud = build_cloud_supplementary_networks()
    all_prefixes.update(cloud)

    # final collapse
    final = list(ipaddress.collapse_addresses(all_prefixes))

    with open("CN.txt", "w") as f:
        for p in sorted(final):
            f.write(str(p) + "\n")

    print(f"[done] total: {len(final)}")


if __name__ == "__main__":
    main()
