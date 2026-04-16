# IPNova P0.5 Postmortem

> **Date**: 2026-04-16
> **Scope**: Multi-source fusion architecture for CN IP attribution
> **Trigger**: `ctrip.com` misclassified as non-CN; root cause traced to ARIN-registered Alibaba Cloud prefixes invisible to APNIC-only pipeline
> **Outcome**: Four-region (CN/HK/TW/MO) dataset with TW and MO populated for the first time; L1 geoloc signal activated; 15× cold-to-warm speedup via persistent cache with rule versioning

---

## 1. Problem Discovery

The investigation started from a seemingly mundane observation: DomainNova's build run returned `dns_cn=0, score=0, matched_cidr=(empty)` for `ctrip.com`. Manual inspection showed the domain resolved to `8.153.170.107` and `8.153.91.124` — both verifiable as Alibaba Cloud Shanghai infrastructure via reverse DNS and WHOIS.

The inconsistency between "infrastructure clearly operated by a Chinese cloud provider" and "matched_cidr empty" pointed at a coverage gap in the underlying IP attribution library (IPNova). One manual probe later:

```
$ grep "^8\." output/CN.txt
(no output)
```

The `8.0.0.0/8` block, including all Alibaba Cloud prefixes in the 8.128.0.0/10 range, was entirely absent from IPNova's `CN.txt`.

## 2. Root Cause Analysis

IPNova v2.x consumed a single source — APNIC's `delegated-apnic-latest` file — applied subtractive filtering (Cloudflare, AWS, Google, and other CDN/anycast ASNs), and emitted region files.

The fatal assumption: **all Chinese infrastructure is registered with APNIC.**

This assumption held for most of the 2010s. It began failing around 2020 when major Chinese cloud providers started purchasing IPv4 blocks from the ARIN-registered market to supplement their allocations. `8.128.0.0/10`, originally held by Level 3 Communications (later Lumen) under ARIN, was acquired in segments by Alibaba Cloud for mainland deployments. These blocks are announced via BGP by AS37963 (Aliyun Computing), are physically located in Chinese data centers, and host Chinese consumer services — but they are invisible to any APNIC-only lens.

The problem was not a bug in IPNova's code. The architecture itself had a blind spot baked in from day one.

## 3. Solution Design

### 3.1 Rejected Approaches

**Manual patch list.** Append known-missing CIDRs to a static file. Rejected because IP acquisitions continue; manual curation cannot keep pace and introduces accuracy decay over time.

**Full RIPEstat geoloc scan of non-APNIC ranges.** Query every prefix not in APNIC data against RIPE. Rejected because "not in APNIC" is an unbounded set; query volume is unestimable.

**Cloud provider official IP lists.** Follow the AWS `ip-ranges.json` model and fetch official CIDR inventories from Alibaba, Tencent, and Huawei Cloud. Rejected after field research confirmed none of the three publish comprehensive per-region IP range JSON endpoints. Only `DescribeRegions`-style metadata APIs and per-product endpoint documentation exist. This reflects a business-culture divergence: Chinese cloud customers rarely perform cross-border allowlist configurations, so providers have little incentive to publish such lists.

### 3.2 Adopted Approach: BGP + Geoloc Fusion

The insight: IPNova already has infrastructure for querying RIPEstat's `announced-prefixes` endpoint (used to enumerate blacklisted CDN ASN prefixes for subtraction). The same API can be inverted — instead of fetching prefixes to subtract, fetch prefixes to add, keyed off curated Chinese cloud ASNs.

For each listed ASN, the BGP announcement set yields the authoritative "what networks is this organization currently routing" answer — independent of RIR boundaries. The ARIN-vs-APNIC distinction ceases to matter.

However, BGP announcements alone cannot solve the "same ASN, multiple regions" problem. AS37963 announces prefixes used in both Hangzhou and Hong Kong. A second signal — geographic location per prefix — is needed to route each prefix into the correct regional bucket. RIPEstat's `geoloc` endpoint provides exactly this.

The resulting pipeline, designated F+F1 in the specification:

```
APNIC delegated-latest     ─┐
                            ├─ merge ─→ per-region CIDR lists
ASN-announced prefixes     ─┘          (with geoloc routing per prefix)
  (filtered through geoloc)
```

### 3.3 ASN Tier Model

Not all cloud ASNs are equally clean. A three-tier classification was adopted:

- **Tier 1 — pure cloud ASNs** (AS37963 Aliyun, AS45102 Alibaba US, AS132203 Tencent Cloud International, AS136907 Huawei Clouds): prefix announcements are almost entirely data-center infrastructure.
- **Tier 2 — mixed ASNs** (AS45090 Tencent, AS38365 Baidu, AS58593 ByteDance): contain cloud, CDN, office network, and consumer service prefixes. Accepted because for *country attribution* (IPNova's scope) the heterogeneity is irrelevant; all prefixes under these ASNs announce within Chinese regulatory jurisdiction. Downstream consumers wanting "cloud datacenter vs consumer access" distinction must perform secondary filtering.
- **Tier 3 — forbidden ASNs** (AS58466 China Telecom, AS4134, AS4837, AS9808, AS4538 CERNET, AS17621, AS9394): operator backbones. Hard-coded into `FORBIDDEN_ASNS` with a module-load assertion that raises `RuntimeError` if any ASN appears in both the cloud and forbidden sets. Defensive coding to prevent future accidental inclusion during maintenance.

## 4. Implementation Timeline

The implementation spanned multiple conversation windows, intentionally partitioned to manage context budget and produce auditable incremental commits.

**Phase P0.5a — constants and primitives.** Added `CN_CLOUD_ASNS_TIER1/TIER2`, `FORBIDDEN_ASNS`, the overlap sanity check, `_ASN_COUNTRY_CACHE`, `fetch_asn_country`, and `fetch_prefix_country` with a three-level fallback chain (L1 RIPEstat geoloc → L2 ASN holder country → L3 APNIC delegated lookup). Strict adherence to incremental modification: no existing function was rewritten.

**Phase P0.5b — supplementary builder and main-flow integration.** Added `build_cloud_supplementary_networks`, which iterates the merged cloud ASN set, fetches announced prefixes, classifies by country, buckets into target regions, and returns both the supplementary dictionary and a statistics structure. Main-flow wiring inserts the supplementary result into `region_data` between `parse_and_cleanse` and `normalize_region_data`, allowing the existing `collapse_addresses` pathway to deduplicate the union.

**Phase P0.5c — metadata write-through, persistent cache, and post-hoc fixes.**

- `meta.json` `parsing` section extended with `cloud_supplement`, `prefixes_before_collapse`, and `prefixes_after_collapse` fields.
- Persistent geoloc cache introduced at `output/.geoloc_cache.json` with a 168-hour TTL matching the weekly cron interval.
- First cold run measured at 15m47s; first warm run (cache populated) at 1m04s — a 15× speedup. This matched the projected ratio and validated the cache design.
- Bug fix: `prefixes_after_collapse` was initially computed as `len(v) for v in normalized_data.values()`, which returned the number of dict keys (5) per region, summing to 20 instead of thousands. Corrected to read `v.get("total_cidrs", 0)`.
- Bug fix: initial version cached only L1 hits; L0 and L2 results were discarded. Extended cache writes to cover all three levels.

**Phase P0.5d — adversarial review and tightening.** An independent review raised concerns about L0 containment semantics, L2 geographic scope, and cache invalidation when rules change. Two outcomes:

1. **L0 strictness tightened.** Original containment check accepted `supernet_of OR subnet_of OR overlaps`, which caused a BGP-announced supernet to be classified as CN whenever *any* APNIC CN subnet fell inside it — over-extension in edge cases. Tightened to `target.subnet_of(n)`: the BGP prefix is accepted as belonging to region R only if fully contained by an APNIC-known prefix in R.
2. **Cache rule versioning.** A `_GEOLOC_CACHE_RULE_VERSION` constant was added, encoding the semantic state of classification rules (e.g., `2026-04-13-l1-located-resources-pct-vote`). Cache load filters entries whose `rule_version` does not match the current constant, forcing a clean rebuild whenever classification semantics change. This handles the class of invalidation that TTL alone cannot: rules change instantaneously, while TTL only captures gradual data staleness.

The rule versioning discipline was promoted from an IPNova-specific fix to a project-wide convention documented for future use in DomainNova and IPv6 work.

**Phase P0.5e — L1 parser repair.** Post-deployment monitoring revealed `l1_success: 0` across three consecutive runs. Initial hypothesis: RIPEstat geoloc throttling the requesting IP. A manual `curl` against the endpoint returned a valid response with the expected data — but the response shape had changed. The code expected `data.locations[0].country`; the actual current shape is `data.located_resources[0].locations[0].country`, with an additional wrapping layer under `located_resources`.

The L1 parser had therefore been broken since P0.5a. Every run since deployment had been silently falling through to L2 (ASN holder country), which is a coarser signal. The symptom was masked by L2 providing acceptable-looking answers for the dominant case (most Chinese cloud ASNs have holder country CN, so prefixes ended up in CN.txt regardless of their actual geographic location).

The fix:

- Parser updated to traverse `data.located_resources[0].locations`, with a fallback to the legacy flat structure for forward compatibility.
- Per-country aggregation of `covered_percentage` replaces "trust the first location in the array". This prevents noise entries (e.g., a 0.0% sliver in an unrelated country appearing first in the list) from dominating the classification.
- `rule_version` bumped to `2026-04-13-l1-located-resources-pct-vote` to invalidate all cache entries produced under the broken parser.

Offline verification using a real RIPEstat response for `8.152.0.0/13`:

```
by_country: {'CN': 100.0, 'CO': 0.0}
winner: CN
```

A 0% Colombia entry was present in the response; the aggregation correctly discarded it.

## 5. Measured Outcomes

### 5.1 Dataset Completeness

Comparison between the run prior to L1 repair and the run immediately after:

| Region | Before L1 fix | After L1 fix | Δ |
|--------|---------------|--------------|---|
| CN     | 5796 CIDRs    | 5542 CIDRs   | −254 |
| HK     | 2598 CIDRs    | 2564 CIDRs   | −34 |
| TW     | 0 CIDRs       | 740 CIDRs    | +740 |
| MO     | 0 CIDRs       | 30 CIDRs     | +30 |

The CN decrease reflects the L2 fallback over-assigning prefixes whose holder country is CN but whose actual geographic footprint (per RIPE geoloc) is in Singapore, the US, or Japan. These are now correctly excluded, recorded in `dropped_other_country: 1760`.

TW and MO being empty prior to this run was an artifact of two combined failures: the earlier `l2-cn-only` policy explicitly blocked non-CN L2 returns, and L1 was silently broken. With both fixed, Chinese cloud providers' Taiwan and Macau regional deployments are represented for the first time.

### 5.2 Signal Distribution

The distribution of classification levels for a warm run (5745 prefixes fetched):

| Level | Count | Share | Semantics |
|-------|-------|-------|-----------|
| L0 (APNIC containment) | 3304 | 57.5% | Prefix fully contained in an APNIC-known region block |
| L1 (RIPEstat geoloc)   | 2383 | 41.5% | RIPE's prefix-level geolocation signal |
| L2 (ASN holder country) | 32  | 0.6% | Fallback for prefixes RIPE cannot geolocate |
| L3 (unresolved)         | 0   | 0.0% | Exhausted all signals |

The dominance of L0 (57.5%) reflects that most Chinese cloud ASNs still primarily announce APNIC-registered prefixes; the BGP supplementation catches the minority of ARIN-registered additions. L1's 41.5% share is the true new coverage — these are prefixes that APNIC alone cannot classify.

### 5.3 Performance Characteristics

- First cold run (empty cache, L1 working): 22m05s
- Second cold run (rule version bump, rebuild): 26m30s
- First warm run after cache populated: 1m04s (15× speedup over cold)
- `.geoloc_cache.json` size: approximately 1 MB for ~5700 entries
- 60-minute workflow timeout confirmed sufficient with margin

## 6. Operational Lessons

### 6.1 Silent Degradation Is the Hardest Failure Mode

The L1 parser bug existed from the first deployment and produced wrong-but-plausible outputs for multiple runs before being noticed. The symptom was not a crash or an error log but a distributional shift: prefixes ended up in CN.txt because L2 said so, not because their actual geography warranted it. This class of failure is difficult to detect through unit tests because each individual classification looks reasonable in isolation. Detection required aggregate monitoring: the `l1_success: 0` counter, once it was exposed in `meta.json`, made the failure visible at a glance.

The lesson for future pipelines: emit fine-grained signal-attribution counters in run metadata. Summary statistics are not sufficient when a pipeline has multiple fallback paths.

### 6.2 Rule Versioning Is a First-Class Concern

The TTL-based cache was initially considered sufficient. It was not. TTL addresses temporal staleness; it does not address rule changes, which invalidate past results instantaneously. The introduction of `_GEOLOC_CACHE_RULE_VERSION` was a late-cycle addition driven by adversarial review, but in hindsight it should have been part of the cache design from day one.

Promoted convention: **any persistent cache whose entries depend on classification or filtering rules must record a `rule_version` field. Code changes that alter classification semantics must bump the version constant as a matter of engineering discipline.** This has been formalized for use in DomainNova and future IPv6 work.

### 6.3 API Schema Drift Demands Defensive Parsing

RIPEstat's response shape changed between the time the code was written (based on memory and possibly stale documentation) and the time it was deployed. The code failed open — parsing an empty locations list as "no data" rather than raising a schema mismatch error — which masked the problem.

Defensive parsing pattern adopted: traverse both current and legacy shapes, return None on mismatch, and ensure the None path is *observable* in metadata rather than silently falling through to lower-confidence fallbacks.

### 6.4 Cross-Window Collaboration With Explicit Handoff

The implementation spanned multiple independent conversation sessions due to context budget constraints. Without explicit handoff artifacts — the v0.2 specification, the `TURN2_HANDOFF` summary, exact line-number anchors, and verbatim ASN lists — each new session would have reconstructed prior decisions from memory, which at one point produced a wrong ASN list (misremembered AS45090 as Huawei instead of Tencent, inserted forbidden operator ASNs AS4837 and AS9808 into the cloud list, invented ASN numbers that did not exist).

The recovery mechanism — `grep`-based verification at handoff boundaries and forcing the receiving session to output the actual ASN numbers it committed — caught the regression before it could contaminate production data. The lesson generalizes: when context cannot be preserved, knowledge must be serialized into artifacts that resist paraphrasing.

## 7. Follow-Up Work

The following items are identified but deferred:

- **P0.5d documentation pass**: README rewrite describing the multi-source architecture, and a v3.0 release note.
- **Concurrency for cold runs**: the warm path is already fast enough; cold runs remain 20+ minutes. Parallelizing the per-prefix geoloc queries (with RIPEstat rate-limit respect) could reduce cold runs to 2–3 minutes. Low priority given that cold runs are rare after cache persistence.
- **Stale-fallback cache policy**: currently expired entries are discarded; an alternative is to retain them as a degraded-source fallback when RIPEstat is unavailable, with explicit `confidence: stale` marking.
- **IPv6 support**: a separate specification, `IPNOVA_IPV6_PROPOSAL.md`, is planned. Decision already locked: separate output files (`CN6.txt` etc.), independent script (`generate_ipv6_list.py`), independent workflow, first version using APNIC-only without BGP fusion (IPv6 does not suffer the same ARIN-gap problem).

## 8. Final State

IPNova P0.5 closes with a dataset that, for the first time, provides separate high-confidence CIDR lists for mainland China, Hong Kong, Taiwan, and Macau. The classification is driven by authoritative BGP signals filtered through prefix-level geographic attribution, with a disciplined fallback chain and persistent caching that makes weekly updates operationally trivial. The architecture can accommodate additional cloud-provider ASNs, additional target regions, and alternative geoloc sources without structural changes.

The downstream beneficiary, DomainNova, can now consume four separate region files and assign domains to mutually exclusive regional buckets — a prerequisite for productizing the dataset as distinct SKUs for compliance, routing-rule, and cross-border business-analysis use cases.

---

*This document is intended as both internal knowledge retention and external-facing technical narrative. The ctrip.com case, the ARIN blind spot, and the TW/MO-first-time-populated result are specific, verifiable claims suitable for commercial positioning.*
