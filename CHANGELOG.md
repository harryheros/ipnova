# IPNova Changelog

Releases, newest first. The weekly data updates are the
`chore: update dataset` commits. Versions before 3.1.1 have no GitHub
release.

## 4.2.1 (2026-11-23)

- **Relocation works block by block.** RIPEstat's per-ASN answer merges adjacent announced prefixes into one entry: Tencent's `43.156.0.0/15` holds its Singapore, Frankfurt and São Paulo data centres, and `43.165.0.0/16` four data centres, none of them in Singapore. 4.2.0 voted over each entry, so such entries stayed in SG whole. Now the located blocks inside each entry decide, and each goes where it is located. Blocks smaller than /24 vote for their /24, so the lists are never cut finer than /24. The answer's `covered_percentage` is not used: it is relative to the whole ASN.
- **The first 4.2.0 run ran out of RIPE budget.** The cloud supplement matched relocated space by exact prefix string, which the merged entries never match, so hundreds of prefixes that relocation had already placed were looked up again one by one. The RIPE breaker tripped after 900 s and five cloud ASNs were skipped; HK lost 75,776 addresses of Huawei Cloud for the week. The supplement now leaves any prefix that touches moved space alone, and places the others from the same per-ASN answer (`geo_hit` in `meta.json`) before it tries the cache or a per-prefix lookup.
- **No ASN-country guess for the international cloud networks** (AS45102, AS134963, AS132203, AS136907). Their holder country is CN, so a prefix with no known location was put in CN: Alibaba's Hong Kong `47.56.0.0/15`, `47.76.0.0/17` and `47.89.0.0/18` sat in CN.txt until the 4.2.0 run. Such a prefix is now left out.
- AS58593 is Azure China (21Vianet Blue Cloud), not ByteDance; the label is corrected. Its space runs in mainland China and stays in CN.
- `meta.json`: `cloud_relocation` reports addresses (`located_addresses`, `kept_addresses`, and moved per region pair) instead of prefix counts.
- Relocation tests rewritten with RIPEstat answers in the shape the real data call returns (8 tests, 45 in total).

## 4.2.0 (2026-11-23)

- **Cloud space is listed where it is operated.** The cloud companies register large blocks in Singapore and run data centres around the world from them: Alibaba's `8.128.0.0/10` carries Aliyun's mainland regions (`8.129`–`8.147`, AS37963), its `8.208.0.0/12` and `149.129.0.0/16` serve Manila and Mumbai, and Tencent's `43.128.0.0/13` serves Tokyo and Frankfurt. The BGP step only added cloud prefixes from outside APNIC space; a prefix inside a region's APNIC space was settled by containment and stayed where it was registered. So SG.txt listed all of these (its two largest entries, `43.0.0.0/9` and `8.128.0.0/10`, were 45% of its addresses), and DomainNova placed sites hosted on them in SG, mainland ones included.
- Each prefix the cloud ASNs announce is now checked against RIPEstat geolocation, with one call per ASN. If at least half of it is located in another country, it leaves the region it is registered in and joins that country when it is one of the seven (SG → CN, SG → JP, …); space located anywhere else belongs to no region. Inside a less specific prefix, a more specific prefix's result wins. Weaker evidence keeps the registration, and space registered in CN never moves. When RIPEstat fails, the answers cached by earlier runs are used; without them nothing moves, and the run summary marks the week as degraded.
- `meta.json` reports the result under `parsing.cloud_relocation`: prefixes moved, kept and undecided, and addresses moved per region pair (also listed in the weekly commit message). `--skip-relocation` keeps the old behaviour.
- AS134963 (Alibaba Cloud Singapore) joins the cloud ASNs.
- The per-ASN answers also fill the geolocation cache, so the cloud supplement no longer needs one RIPEstat call per prefix for these networks.
- Global dataset: space registered in the seven regions but operated elsewhere has no country code, like the anycast networks the regional lists leave out.
- README: it said cloud regions already landed where they operate, which held only for space outside APNIC. It now describes the relocation and lists RIPEstat geolocation as a source.
- 7 new offline tests (44 total).

## 4.1.1 (2026-11-19)

- **Google's in-country edge is no longer in CN.txt.** `203.208.32.0/19` is announced by AS24424 (GOOGLECN, Beijing Gu Xiang Information Technology), Google's network in China, which serves Google's global services to users there. Only Google's global ASNs (15169, 396982) were excluded, so the prefix stayed in the CN list, and services resolving to it looked like mainland services: DomainNova placed googletagmanager.com and googleoptimize.com in CN. AS24424 is now excluded like Google's other ASNs, and the prefix is also on the static list, so it stays out in a week when RIPEstat fails. CN loses 8,192 addresses.

## 4.1.0 (2026-11-03)

- **One APAC MMDB**: `ipnova-apac-country.mmdb` is merged into `ipnova-apac.mmdb`, which now uses `database_type` `GeoLite2-Country` and works with GeoIP2 reader libraries. The records are unchanged. Use `ipnova-apac.mmdb` in place of the removed file.
- **README**: shortened; the full history moved to this file.

## 4.0.0 (2026-11-03)

- **Global dataset**: every country, IPv4 + IPv6, from the delegation files of all five RIRs (MD5-checked), published weekly on the history-free `data` branch: `geoip.dat` (V2Ray format, with `PRIVATE` matching v2fly/geoip), a global MMDB (`database_type` `GeoLite2-Country`) and per-country CIDR lists, with `meta.json` and `SHA256SUMS`. CN/HK/TW/MO/JP/KR/SG IPv4 comes from IPNova's own pipeline.
- **Safety**: a registry download that is missing, fails or lacks its MD5 checksum, or is truncated stops the global build; a >20% drop in addresses (or >10% in countries) versus the last build is refused.
- **Status**: the run summary marks a week as *degraded* when the RIPEstat budget runs out or cloud ASNs fail; CN is unaffected (APNIC-based).
- **Verification**: `geoip.dat` is decoded after writing and cross-checked against the official protobuf runtime in the tests; the global MMDB is read back for the 30 largest countries.
- The existing regional outputs on `main` are unchanged.

## 3.5.1 (2026-10-10)

- **Bugfix (MMDB compatibility)**: the compatibility MMDB files were byte copies of `ipnova-apac.mmdb`, so their metadata `database_type` was `IPNOVA-GeoIP2-Country`. GeoIP2 readers check this field before a Country lookup and refused the files with *"The database is not marked as type GeoLite2-Country or type GeoIP2-Country"*. The compatibility file is now built separately with the correct `database_type`; the records are unchanged.
- **Single compatibility file, neutral name**: the two identical `GeoIP2-Country-compatible.mmdb` / `GeoLite2-Country-compatible.mmdb` files are replaced by one `ipnova-apac-country.mmdb` (`database_type` = `GeoLite2-Country`, accepted by mainstream GeoIP2 readers). The old files have been removed.
- **Coverage note**: the README now states that the MMDB covers the seven regions only and is not a drop-in replacement for a global GeoIP database.
- **Trademark notice**: added to the README and to the metadata description of every MMDB file.
- **Validation**: the MMDB round-trip check now verifies `database_type` for every file, so a wrong type fails the build instead of being published. New regression tests, including a guard against third-party product names in file names (28 total).

## 3.5.0 (2026-09-25)

- **CI (critical)**: `actions/github-script` v7 → v9. v7 runs on Node 20, which GitHub removed from hosted runners on 2026-09-16, so the failure-notification job could no longer run. Also `actions/checkout` v6 → v7, Python 3.12 → 3.13, pip caching, a `concurrency` guard, and push-with-rebase retry.
- **Bugfix (geoloc cache never refreshed)**: the workflow saved the cache under the same key it restored from; Actions caches are immutable, so every save after the first was rejected. Each run now saves under a unique key. The TTL (168h) also equalled the cron period, so last week's entries were expired by the time they were read — raised to 240h — and a Thursday keep-alive prevents GitHub's 7-day eviction.
- **Bugfix (confidence inflation)**: cache hits were returned as level `L-1` and mapped to `confidence: "high"`, promoting weak `L2` guesses to high confidence on every warm run. The original level is now preserved.
- **Bugfix (stale cache vs fresh APNIC)**: APNIC containment (L0) is now checked before the cache, so a new APNIC delegation always wins over last week's cached answer.
- **Bugfix (provenance)**: APNIC blocks such as `47.96.0.0/11` were labelled `source: "bgp"` because a same-region BGP prefix inside them was recorded in provenance even after being trimmed away. Provenance now covers only address space actually claimed from the BGP tier, and uses a majority-share rule (schema 3.4).
- **Bugfix (silent MMDB failure)**: `build_formats.py` logged MMDB failures but exited 0, so CI committed a run with a stale MMDB. It now exits 1 and skips release assets. The MMDB builder also refuses to write a database with a region missing.
- **Bugfix (validator crash)**: `validate_output.py` crashed on `--skip-ripe` builds (`cloud_supplement: null`).
- **HTTP**: permanent 4xx errors are no longer retried; `429`/`503` honour `Retry-After` (bounded).
- **RIPE breaker**: default budget 600s → 900s (a cold cloud-supplement run measured ~560s), configurable via `--ripe-budget`; breaker state is recorded in `meta.json`.
- **Performance**: range subtraction now uses a binary-search index (`SortedNetworks`) — mutual-exclusivity enforcement went from ~9.7s to ~0.4s with identical output; cloud-supplement L0/conflict checks no longer rescan every region list per prefix.
- **Robustness**: all outputs are written atomically; the release tarball is reproducible (sorted entries, fixed mtime/owner); `checksums.txt` no longer lists gitignored release artifacts.
- **Validation**: new hard gates — `data.json` SHA-256 must match `meta.json`, and every `<CC>.txt` must match `data.json`. DNS samples resolve in parallel with a real deadline (`gethostbyname_ex` ignores socket timeouts); `--output-dir` / `--skip-dns` added. Stale DNS samples that moved behind global CDNs were replaced.
- **Tooling**: `requirements-dev.txt` (ruff, pytest) split from runtime requirements; `pyproject.toml` with ruff/pytest config; lint now covers tests. 11 new regression tests (26 total), including randomized brute-force checks of subtraction and mutual exclusivity. Fixed a test that leaked a fake `maxminddb` module into later tests.

## 3.4.0 (2026-06-05)

- **Bugfix (provenance)**: `cidr_objects` provenance was matched to final CIDRs by exact string, but a BGP supplement prefix's string changes whenever it is collapsed or trimmed during normalization — so a large share of BGP-sourced prefixes were silently mislabelled `source: "apnic"`. Provenance is now matched by **IP-range intersection**, which survives any collapse/trim. The core region CIDR lists (TXT/MMDB/etc.) were never affected — only the `cidr_objects` metadata.
- **Bugfix (confidence)**: `confidence` was hardcoded to `"high"` for every prefix, so `L2` (ASN-holder-country fallback, the weakest signal) was advertised as high-confidence. The attribution `level` (L0/L1/L2) is now carried through and `confidence` is derived from it: `L0`/`L-1` → `high`, `L1` → `medium`, `L2` → `low`.
- **Schema v3.3**: `cidr_objects` gains a `level` field exposing the attribution tier. `confidence` values now span `high`/`medium`/`low` (previously always `high`). Backward-compatible additive change — existing `cidrs`, `source`, `asn`, `tier` fields are unchanged.
- **Testing**: added `test_provenance_survives_collapse_and_level_confidence` — a regression guard that constructs a collapse scenario and asserts BGP prefixes keep their provenance and L2 prefixes are downgraded to `low`.

## 3.3.0 (2026-05-25)

- **Architecture**: extracted `TARGET_REGIONS` into `regions.py` as a single source of truth, eliminating definition drift between the build pipeline and `mmdb/schema.py`
- **Correctness**: `enforce_mutual_exclusivity` now treats APNIC results as Tier 1 (authoritative) and BGP supplement as Tier 2 (gap-filling), so a misclassified supplement prefix can no longer displace an APNIC-assigned region block
- **Reliability**: per-host RIPEstat throttling enforced inside `http_get` (canonical hostname matching via `urlparse`, not substring), so callers can no longer accidentally bypass rate limits, and spoofed URLs cannot trigger throttling
- **Operations**: `MAX_L2_RATIO` threshold tightened from 0.60 to 0.10 and downgraded from CI gate to loud warning — transient RIPEstat hiccups no longer block weekly publishes, while genuine L1 degradation is still surfaced
- **MMDB validator**: rewritten as an explicit round-trip check rather than an "accuracy" check it could not actually perform; tolerates individual stale samples (warn-only), fails only when an entire region has zero matching samples
- **Security/Provenance**: canary CIDR set embedded in published artifacts using RFC5737 documentation-reserved ranges (harmless for downstream firewall/ACL use, but enables forensic attribution of unattributed redistributions); `meta.json` gains a `build` section recording the commit SHA that produced the artifact
- **HTTP**: `User-Agent` is now derived from `__version__` and includes the repository URL for contactability (was hardcoded and had drifted)
- **CLI**: new `--skip-canary` flag for verification builds
- **MaxMind aliases renamed**: `GeoIP2-Country.mmdb` → `GeoIP2-Country-compatible.mmdb` (and likewise for GeoLite2). The `-compatible` suffix avoids using MaxMind's trademarked product names directly.
- **iptables**: `ipset` maxelem sized dynamically (`max(num_cidrs * 2, 65536)`, rounded to next power of two) so future region growth doesn't silently truncate
- **MMDB validator**: expanded MO sample set so a single IP holder change can't fail the region-coverage gate
- **Documentation**: project-language consistency — translated `IPNOVA_MULTISOURCE_PROPOSAL.md` to English (`P0_5_POSTMORTEM.md` already English)
- **Testing**: 7 new offline tests covering tier-layered enforce, hostname-based RIPE throttle classification, MMDB round-trip semantics, regions single-source-of-truth, User-Agent derivation, and canary CIDR well-formedness — 14 tests total

## 3.2.1 (2026-05-07)

- **New**: `cidr_objects`, per-CIDR provenance metadata in `output/data.json` (schema v3.2) — each CIDR now carries `source`, `asn`, `tier`, and `confidence` fields
- **New**: two copies of `ipnova-apac.mmdb` under the file names GeoIP2 Country tools expect (renamed with a `-compatible` suffix in 3.3.0)
- **New**: `output/haproxy/{CC}.acl` — HAProxy ACL format
- **New**: `output/caddy/{CC}.conf` — Caddy remote_ip matcher format
- **New**: `output/plain/{CC}.txt` — pure CIDR files with no comment headers (for programmatic consumption)
- **New**: `output/terraform/{CC}.auto.tfvars.json` — Terraform-compatible variable files
- **New**: `output/checksums.txt` — SHA-256 checksums covering all output files
- **CI**: `build_formats.py` now runs with `--release-assets`, generating `ipnova-formats.tar.gz` and `SHA256SUMS` on every update
- **Internal**: `_ASN_TIER_MAP` added for O(1) tier lookup; `build_cloud_supplementary_networks` returns provenance alongside networks

## 3.2.0 (2026-04-30)

- **New**: `scripts/build_formats.py` — extended format generator
- **New**: `output/ipnova-apac.mmdb` — MaxMind-compatible MMDB database for all 7 regions
- **New**: `output/regions.json` + `output/json/{CC}.json` — per-region JSON outputs
- **New**: `output/nginx/{CC}.conf` — Nginx geo module format
- **New**: `output/iptables/{CC}.ipset` — iptables ipset restore format
- **CI**: added `mmdbwriter` dependency install step; `build_formats.py` runs automatically after each dataset update

## 3.1.1 (2026-04-30)

- **Fix**: f-string syntax error in region header write (Python < 3.12 compatibility)
- **Fix**: `--skip-ripe` now correctly skips cloud supplement as well
- **New**: `--skip-cloud-supplement` flag for APNIC-only output
- **Fix**: geolocation cache now follows `--output-dir` instead of hardcoded `output/`
- **Fix**: `validate_output.py` reads `cloud_supplement` from correct metadata path
- **CI**: added syntax check and offline smoke test steps; validation failures now block commit
- **Test**: added `tests/test_core_offline.py` for network-free core regression

## 3.1.0 (2026-04-26)

- **Asia-Pacific expansion**: added Japan (JP), South Korea (KR), and Singapore (SG) to target regions
- All new regions sourced from APNIC delegation data (no BGP supplement needed — APNIC coverage is complete for these regions)
- Updated sanity thresholds for new regions (JP: 3000, KR: 800, SG: 300)
- Validation script and test samples updated with JP/KR/SG domains
- Cloud supplement remains CN-specific (resolves ARIN-registered Chinese cloud provider IP blocks)

## 3.0.0 (2026-04-21)

- **Multi-source BGP fusion**: supplements APNIC data with live BGP announcements from Chinese cloud provider ASNs (Alibaba, Tencent, Baidu, Huawei, ByteDance, JD, NetEase)
- **ASN tier model**: Tier 1 (pure cloud), Tier 2 (mixed internet company), Tier 3 (operator backbone, hard-forbidden)
- **Four-level country attribution**: L-1 persistent cache → L0 in-memory APNIC containment → L1 RIPEstat geoloc (coverage-weighted vote) → L2 ASN holder country fallback
- **Rule-versioned cache**: 168-hour TTL with semantic rule versioning for instant invalidation on classification logic changes; 15× speedup from cold to warm runs
- **Defensive operator exclusion**: `FORBIDDEN_ASNS` with module-load assertion prevents accidental inclusion of China Telecom/Unicom/Mobile backbone ASNs
- TW and MO regions populated for the first time via cloud supplement pipeline
- Output validation script (`scripts/validate_output.py`) with sample-based testing
- Schema version bumped to 3.0

## 2.1.0 (2026-03-30)

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

## 2.0.0 (2026-03-30)

- Replaced `print()` with `logging` module
- Added CLI via `argparse`
- HTTP retry with exponential backoff
- RIPEstat rate limiting
- Data sanity checks
- Enriched `meta.json` schema
- CI lint check, diff reporting, failure notifications

## 1.0.0 (2026-03-22)

- Initial release
