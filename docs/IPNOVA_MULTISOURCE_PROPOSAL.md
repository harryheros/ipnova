# IPNova Multi-Source Fusion Specification v0.2

> Status: Implemented (2026-04-16) · Delivered in IPNova v3.0.0
> Predecessor: DomainNova `PROPOSAL_MULTI_REGION.md`
> Changelog from v0.1: AS55990 removed, Tier 3 expanded, geoloc fallback chain added, Tier 2 limitations made explicit, performance optimizations.

---

## 1. Problem Statement

### 1.1 Observed Failure
DomainNova's scoring returned `dns_cn=0` for `ctrip.com`, excluding it from `dist/domains.txt`. The domain in fact resolved to `8.153.170.107` and `8.153.91.124`, which are Aliyun Shanghai region public addresses. `matched_cidr` was empty, indicating IPNova's `CN.txt` did not contain `8.153.0.0/16`.

### 1.2 Root Cause
- IPNova's only data source was `ftp.apnic.net/stats/apnic/delegated-apnic-latest`.
- The entire `8.0.0.0/8` block is under ARIN administration (historically Level 3, now Lumen) and never appears in APNIC delegated files.
- Aliyun acquired multiple segments within `8.128.0.0/10` from the ARIN system for use in their mainland China business.
- IPNova's `parse_and_cleanse` logic could only subtract from APNIC results (remove Anycast/CDN ASNs); it had no mechanism to add ARIN-registered blocks.
- Conclusion: this is an architectural blind spot, not a script bug.

### 1.3 Impact Scope
Every site hosted on overseas-purchased IP blocks held by Chinese cloud providers would be mis-classified:
- Customers on Aliyun 8.x and 47.x ranges (Ctrip, various e-commerce and SaaS).
- Equivalent ARIN-system ranges held by Tencent Cloud and Huawei Cloud.
- Estimated affected domains: at least 20–50 large sites within DomainNova's current ~700-line seed.txt.

### 1.4 Business Impact
This blind spot directly threatens DomainNova's commercial value as a "precise CN infrastructure dataset". When sold to compliance customers, a single validation against the customer's own known assets reveals the omissions, damaging credibility.

---

## 2. Evolution of Approaches

### 2.1 Rejected Approaches

**Approach A — APNIC patch list**
Maintain a static "CIDRs APNIC is missing" file by hand.
**Rejected**: information goes stale; every new IP purchase by a cloud provider requires a manual edit. Not sustainable.

**Approach D — Full RIPE Stat geoloc scan**
Query geoloc for every IP block outside APNIC data.
**Rejected**: "outside APNIC" is an unbounded set; query volume cannot be estimated.

**Approach E — Cloud provider official IP list fetcher**
Modeled on AWS `ip-ranges.json`: fetch official public cloud IP range JSON from Aliyun, Tencent Cloud, and Huawei Cloud.
**Rejected**: field investigation confirmed none of the three publishes such a resource. Only `ListRegions`/`DescribeRegions`-style "region metadata" APIs and scattered product-level endpoint documentation exist, none of which cover compute-instance ranges. The cultural reason is straightforward: Chinese cloud customers rarely perform cross-border allowlisting, so providers have no incentive to publish full IP ranges.

### 2.2 Adopted: Approach F + F1

**F: BGP route reversal (ASN announcement based)**
Use RIPE Stat's `announced-prefixes` API to pull all current BGP prefixes announced by known Chinese cloud / internet-company ASNs. BGP is a "live operational" signal — fresher than any registry, and independent of RIR boundaries: whether a prefix is registered with APNIC or ARIN, if the ASN is announcing it, the prefix is part of that organization's live network.

**F1: RIPE Stat geoloc secondary classification (with fallback)**
For each prefix collected via F, query geographic location separately and bucket into CN/HK/TW/MO output files by returned country code. This is the only mechanism that solves the "cross-region pollution" problem: Chinese cloud providers run regions in Hong Kong, Singapore, and the US West, and these prefixes must be precisely separated by geography.

### 2.3 Why F+F1
1. **No new dependencies**: IPNova already uses RIPE Stat for `announced-prefixes` queries against `EXCLUDED_ASNS`. All HTTP client code, retry logic, and rate-limiting are reused — only the direction of use is inverted.
2. **Data freshness**: BGP reflects live state.
3. **Cross-region separation is intrinsic**: geoloc secondary classification structurally prevents Hong Kong segments from leaking into CN.txt.
4. **Free, no license key required.**
5. **Reuses existing testing and maintenance mental model.**

---

## 3. ASN Tier Model

### 3.1 Design Principle
Not all ASNs are equivalent. Treating them uniformly creates two classes of risk: (a) including operator ASNs causes nationwide consumer broadband to be mislabeled; (b) within mixed ASNs, cross-border segments leak between regions. This specification adopts a three-tier classification with explicit per-tier handling.

### 3.2 Tier 1 — Pure cloud ASNs (high trust)
These ASNs' announced prefixes are almost exclusively cloud datacenter IPs, with negligible residential or office-network contamination.

| ASN | Organization | Notes |
|---|---|---|
| AS37963 | Aliyun Computing Co., Ltd. | Aliyun mainland, core ASN |
| AS45102 | Alibaba US Technology Co., Ltd. | Aliyun overseas primary ASN |
| AS132203 | Tencent Cloud Computing (Beijing) | Tencent Cloud International |
| AS136907 | HUAWEI CLOUDS | Huawei Cloud International, clean cloud ASN |

**Handling**: prefixes that pass geoloc are written directly into the corresponding region file with metadata tag `tier: 1, confidence: high`.

### 3.3 Tier 2 — Internet company mixed ASNs (medium trust)

| ASN | Organization | Contents |
|---|---|---|
| AS45090 | Tencent Building, Kejizhongyi Avenue | Tencent Cloud, WeChat, QQ, CDN, consumer business |
| AS38365 | Baidu, Inc. | Search, CDN, Baidu Cloud |
| AS58593 | ByteDance | TikTok, Douyin, CDN, Volcano Engine |

**Handling**: prefixes that pass geoloc are written into the corresponding region file with metadata tag `tier: 2, confidence: medium`.

#### 3.3.1 Tier 2 Known Limitations (Important)

Tier 2 ASN prefixes do contain consumer-business IPs — Tencent residential broadband, ByteDance office networks, Baidu enterprise circuits, and so on. For these prefixes:

- **For the "IP country attribution" use case**: completely correct. These IPs are physically in China, and regardless of intended use should belong in CN.txt.
- **For the "datacenter / cloud infrastructure identification" use case**: this is contamination. Downstream consumers must perform secondary filtering to distinguish cloud segments from consumer segments.

**Decision in this specification**: IPNova does not resolve this contamination at its own layer. Rationale:

1. **Responsibility boundary**: IPNova's job is IP country attribution; datacenter semantic refinement is a downstream concern.
2. **Irreversibility**: any filter rule (prefix length threshold, rDNS probing, etc.) will collaterally exclude legitimate cloud segments, and excluded data cannot be recovered.
3. **Cost asymmetry**: introducing filtering at the IPNova layer would add significant complexity (rDNS queries, caching, timeouts) while serving only the one downstream use case of datacenter identification.
4. **Better placement**: if "precise cloud-datacenter identification" becomes a real need, the right answer is a separate `asnnova` project (ASN metadata database), decoupled from IPNova.

**Commitment to downstream consumers**: the `confidence: medium` tag in `meta.json` makes Tier 2 prefixes explicitly identifiable, so downstream consumers can choose whether to trust them.

### 3.4 Tier 3 — Operator ASNs (permanently forbidden)
Operator backbone ASNs contain residential broadband, IDC, DSLAM access networks, and enterprise leased lines — too broad, with unclear semantics. Including them would label entire residential broadband ranges as "cloud" or "datacenter", collapsing any downstream scoring model.

| ASN | Organization |
|---|---|
| AS58466 | China Telecom |
| AS4134 | China Telecom Backbone |
| AS4837 | China Unicom Backbone |
| AS9808 | China Mobile |
| AS4538 | CERNET (education network backbone) |
| AS17621 | China Unicom Shanghai |
| AS9394 | China Railway Telecom |

**Handling**: hard-coded as `FORBIDDEN_ASNS`. At module load, a sanity check raises `RuntimeError` immediately if `CN_CLOUD_ASNS` and `FORBIDDEN_ASNS` intersect. This is defensive design against future maintainers accidentally adding operator ASNs to the inclusion list.

### 3.5 Evaluated but Not Included

| ASN | Organization | Reason for exclusion |
|---|---|---|
| **AS55990** | Huawei Technologies Co., Ltd. | Too heterogeneous (enterprise office + device test net + R&D + some cloud); contamination higher than the Tier 2 average; would inject a large volume of non-datacenter IPs. Huawei Cloud coverage relies on the single Tier 1 AS136907. Could be considered as an optional future source pending rDNS filtering. |

### 3.6 Rejected Designs
A review iteration suggested introducing continuous `cloud_confidence: 0.6` values and a `tags: ["cloud", "cdn", "consumer"]` system. This specification rejects that:
- Out of scope (IP attribution database ≠ ASN risk-scoring system).
- Confidence scores require training data, which is a separate project.
- Commercial value mismatch — IPNova's core is country attribution precision, not cloud-IP subdivision.
- Belongs in a hypothetical separate `asnnova` project.

This specification introduces only two tier tags (1 = high, 2 = medium); no continuous confidence is introduced.

---

## 4. Technical Implementation

### 4.1 Files Touched
- `generate_ip_list.py` (primary changes)
- `output/meta.json` schema extensions
- `README.md` documentation updates
- `.github/workflows/update.yml` (extended timeout)

### 4.2 New Constants

```python
# Cloud / Internet Company ASNs for ARIN-gap supplementation
CN_CLOUD_ASNS_TIER1 = {
    37963: "Aliyun Computing",
    45102: "Alibaba US Technology",
    132203: "Tencent Cloud International",
    136907: "Huawei Clouds International",
}

CN_CLOUD_ASNS_TIER2 = {
    45090: "Tencent",
    38365: "Baidu",
    58593: "ByteDance",
}

CN_CLOUD_ASNS = {**CN_CLOUD_ASNS_TIER1, **CN_CLOUD_ASNS_TIER2}

# Operator backbone ASNs - must NEVER be in CN_CLOUD_ASNS
FORBIDDEN_ASNS = {
    58466: "China Telecom",
    4134:  "China Telecom Backbone",
    4837:  "China Unicom Backbone",
    9808:  "China Mobile",
    4538:  "CERNET",
    17621: "China Unicom Shanghai",
    9394:  "China Railway Telecom",
}

# Module-load sanity check
_overlap = set(CN_CLOUD_ASNS.keys()) & set(FORBIDDEN_ASNS.keys())
if _overlap:
    raise RuntimeError(
        f"Forbidden ASN(s) found in CN_CLOUD_ASNS: {_overlap}. "
        f"Operator backbone ASNs must never be used as cloud sources."
    )

RIPE_GEOLOC_URL = "https://stat.ripe.net/data/geoloc/data.json"
RIPE_AS_OVERVIEW_URL = "https://stat.ripe.net/data/as-overview/data.json"
GEOLOC_REQUEST_INTERVAL = 0.5
GEOLOC_CACHE_TTL_HOURS = 24
```

### 4.3 New Function: geoloc 3-Level Fallback

```python
def fetch_prefix_country(prefix: str, asn: int, cache: dict) -> Optional[str]:
    """
    Determine the country code for a BGP prefix using a 3-level fallback chain.

    Level 1 (primary): RIPE Stat geoloc API
    Level 2 (fallback): RIPE Stat as-overview holder country (cached per ASN)
    Level 3 (fallback): APNIC delegated record for the prefix (if exists)

    Returns ISO country code (e.g. "CN", "HK") or None if all levels fail.
    Results cached locally to avoid duplicate queries within a single run.
    """
    # Cache check
    if prefix in cache:
        return cache[prefix]

    # Level 1: geoloc
    try:
        url = f"{RIPE_GEOLOC_URL}?resource={prefix}"
        data = http_get(url, timeout=15)
        country = parse_geoloc_response(data)
        if country:
            cache[prefix] = country
            return country
    except Exception as e:
        log.debug("geoloc L1 failed for %s: %s", prefix, e)

    # Level 2: ASN holder country
    try:
        country = fetch_asn_country(asn)  # cached per ASN
        if country:
            log.debug("Using L2 fallback for %s: %s (from AS%d)", prefix, country, asn)
            cache[prefix] = country
            return country
    except Exception as e:
        log.debug("geoloc L2 failed for AS%d: %s", asn, e)

    # Level 3: APNIC delegated lookup (if prefix is in APNIC data)
    country = lookup_in_apnic_data(prefix)
    if country:
        log.debug("Using L3 fallback for %s: %s", prefix, country)
        cache[prefix] = country
        return country

    cache[prefix] = None
    return None
```

### 4.4 New Function: Cloud Supplementary Builder

```python
def build_cloud_supplementary_networks(apnic_data) -> Dict[str, List[ipaddress.IPv4Network]]:
    """
    For each ASN in CN_CLOUD_ASNS:
      1. Fetch all announced prefixes via fetch_asn_prefixes() (existing function)
      2. For each prefix, determine country via fetch_prefix_country() with 3-level fallback
      3. Bucket into {region: [networks]} where region is CN/HK/TW/MO
      4. Drop prefixes that resolve to non-target regions or UNKNOWN

    Returns {region_code: [IPv4Network, ...]}
    """
    result = {region: [] for region in TARGET_REGIONS}
    geoloc_cache = {}
    stats = {"queried": 0, "kept": 0, "dropped_other": 0, "dropped_unknown": 0}

    for asn, label in sorted(CN_CLOUD_ASNS.items()):
        tier = "tier1" if asn in CN_CLOUD_ASNS_TIER1 else "tier2"
        try:
            prefixes = fetch_asn_prefixes(asn)
            log.info("AS%d %s [%s]: %d prefixes from BGP", asn, label, tier, len(prefixes))
            for net in prefixes:
                stats["queried"] += 1
                country = fetch_prefix_country(str(net), asn, geoloc_cache)
                if country in TARGET_REGIONS:
                    result[country].append(net)
                    stats["kept"] += 1
                elif country is None:
                    stats["dropped_unknown"] += 1
                else:
                    stats["dropped_other"] += 1
                time.sleep(GEOLOC_REQUEST_INTERVAL)
        except Exception as e:
            log.error("Failed to process AS%d: %s", asn, e)
    return result, stats
```

### 4.5 Main Pipeline Integration
```
Step 1: APNIC download              (existing)
Step 2: build EXCLUDED networks     (existing)
Step 3: parse APNIC                 (existing)
Step 4: build cloud supplementary   (NEW)
Step 5: merge per region            (NEW - union + collapse_addresses)
Step 6: sanity check                (existing, threshold bumped)
Step 7: save outputs                (existing, with confidence metadata)
```

### 4.6 Merge Logic
Per region: `final = collapse_addresses(apnic_result + cloud_supplementary)`. `ipaddress.collapse_addresses` deduplicates and aggregates adjacent ranges automatically.

### 4.7 Performance Expectations and Optimizations
- Current: 1–2 minutes
- After change: 10–20 minutes
- Main cost: geoloc query count = Σ prefixes announced per ASN, estimated 2,000–5,000 queries × rate limit
- **In-run cache**: build a `geoloc_cache` dict within a single run to avoid duplicate prefix queries.
- **Cross-run cache** (optional P0.5d optimization): persist geoloc results to `output/.geoloc_cache.json` with a 24-hour TTL, further reducing subsequent run query volume.
- Acceptable for a background cron job.

### 4.8 Failure Modes and Degradation
- Single ASN query failure: log warning, skip the ASN, continue with others.
- All three fallback levels fail for a single prefix: mark as UNKNOWN, do not write to any region file.
- RIPE Stat entirely unavailable: fall back to APNIC-only mode (existing behavior); meta.json marks `cloud_supplement: failed`.
- Sanity check failure: script exits without overwriting the last successful output.

---

## 5. meta.json Schema Extension

```json
{
  "version": "3.0",
  "sources": [
    {"name": "APNIC delegated-apnic-latest", "type": "registry"},
    {"name": "RIPE Stat BGP + geoloc", "type": "bgp_supplement"}
  ],
  "cloud_supplement": {
    "enabled": true,
    "asn_count": 7,
    "tier1_asn_count": 4,
    "tier2_asn_count": 3,
    "prefixes_fetched": 3421,
    "prefixes_kept_cn": 412,
    "prefixes_kept_hk": 89,
    "prefixes_kept_tw": 12,
    "prefixes_kept_mo": 0,
    "prefixes_dropped_other_country": 156,
    "prefixes_dropped_unknown": 23,
    "geoloc_l1_success": 3128,
    "geoloc_l2_fallback": 245,
    "geoloc_l3_fallback": 25,
    "duration_seconds": 847
  },
  "confidence_breakdown": {
    "high": 5905,
    "medium": 412
  }
}
```

---

## 6. Test Strategy

### 6.1 Benchmark Test Cases
| Domain / IP | Expected Outcome |
|---|---|
| ctrip.com → 8.153.x.x | After change, `8.153.0.0/16` should be in CN.txt |
| Aliyun cn-hongkong region IP (e.g. 47.x) | Should be in HK.txt, **not** in CN.txt |
| China Telecom residential broadband IP | Should be in CN.txt (from existing APNIC coverage); must not be duplicated by the cloud supplement path |

### 6.2 Regression Test
After the change, CN.txt line count must be **≥** the pre-change count (5,493 CIDRs); HK.txt should also see a small increase. A decrease indicates a bug in the merge logic.

### 6.3 Cross-Region Pollution Test (Negative)
- Take one or two known Aliyun Hong Kong region sample prefixes from Aliyun documentation.
- Confirm CN.txt does **not** contain those prefixes after the change.
- Confirm they appear in HK.txt.

### 6.4 Tier 3 Defensive Test
Unit test: construct a scenario that temporarily adds AS58466 to `CN_CLOUD_ASNS`, and confirm the module-load phase immediately raises `RuntimeError`.

---

## 7. Phased Roadmap

| Phase | Scope | Estimated Size |
|---|---|---|
| **P0.5a** | `CN_CLOUD_ASNS` / `FORBIDDEN_ASNS` constants, `fetch_prefix_country` 3-level fallback, `build_cloud_supplementary_networks` | ~180 lines |
| **P0.5b** | Main pipeline integration, merge logic, meta.json extension | ~60 lines |
| **P0.5c** | Sanity check upgrade, failure-degradation logic, Tier 3 defensive test | ~40 lines |
| **P0.5d** | README update, workflow timeout adjustment, (optional) cross-run cache, release v3.0 | Docs-heavy |
| **P0.5e (validation)** | Local run + ctrip.com benchmark + cross-region pollution test | User-executed |

P0.5a-d can be completed in a single conversation window.

---

## 8. Handoff to DomainNova

After P0.5 lands, DomainNova requires no code changes; simply re-run `build_domains.py`:
- ctrip.com is recovered automatically.
- Other previously-excluded major sites recover automatically.
- Entries in seed.txt that have a correct brand name but whose `.com` primary domain is actually hosted overseas (bankofchina.com, icbc.com, etc.) remain excluded — this is the correct behavior.
- DomainNova then proceeds to P1 (multi-region refactor).

---

## 9. Parameters Pending Calibration

| Parameter | Initial Suggested Value | Notes |
|---|---|---|
| `GEOLOC_REQUEST_INTERVAL` | 0.5 s | RIPE Stat rate-limit buffer |
| `GEOLOC_CACHE_TTL_HOURS` | 24 | Cross-run cache validity |
| Sanity check CN minimum | 5,500 | Post-change expectation |
| Sanity check HK minimum | 1,100 | Slight increase expected |
| Geoloc failure-rate threshold | 30% | Above this, mark the run as degraded overall |

---

## 10. Implementation Kickoff (Historical)

> Begin P0.5a-d: implement IPNova multi-source fusion per specification v0.2.

Scope:
1. Modify `generate_ip_list.py`
2. Update `README.md`
3. Update `.github/workflows/update.yml`
4. Package a zip with the full directory layout (including `generate_ip_list.py`, verifiable via `ipnova_repo.sh` integrity check)
5. User executes local P0.5e validation
