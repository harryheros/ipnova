# IPNova 多源融合改造規範書 v0.2

> Status: Draft · Target: IPNova v3.0
> Predecessor: DomainNova `PROPOSAL_MULTI_REGION.md`
> Changelog from v0.1: AS55990 移除、Tier 3 擴充、geoloc 加 fallback、Tier 2 局限明確化、性能優化補充

---

## 1. 問題陳述

### 1.1 觀察到的故障
DomainNova 對 `ctrip.com` 的打分返回 `dns_cn=0`，被排除在 `dist/domains.txt` 之外。實際解析到的 IP 為 `8.153.170.107` 與 `8.153.91.124`，這是阿里雲上海 region 的公網段。`matched_cidr` 為空，說明 IPNova 的 `CN.txt` 不包含 `8.153.0.0/16`。

### 1.2 根本原因
- IPNova 當前唯一數據源為 `ftp.apnic.net/stats/apnic/delegated-apnic-latest`
- `8.0.0.0/8` 整個 /8 屬於 ARIN 管轄（歷史上 Level 3 / 現 Lumen），**從未出現在 APNIC delegated 文件中**
- 阿里雲近年從 ARIN 體系購買/租用了 `8.128.0.0/10` 範圍內的多個段用於中國區業務
- IPNova 的 `parse_and_cleanse` 邏輯只能對 APNIC 結果做減法（去除 Anycast/CDN ASN），無法補充 ARIN 段
- 結論：**這是架構性盲區，不是腳本 bug**

### 1.3 影響範圍
所有部署在中國雲廠商海外購買 IP 段上的網站都會被誤判：
- 阿里雲 8.x、47.x 段上的客戶（攜程、部分電商、SaaS 服務）
- 騰訊雲、華為雲在 ARIN 體系下的同類段
- 估計受影響域名：在 DomainNova 當前 ~700 行 seed.txt 中至少 20-50 個大站

### 1.4 商業影響
這個盲區直接威脅 DomainNova 作為「精準 CN 基礎設施數據集」的商業價值。賣給合規客戶時，客戶用自己的已知資產一驗證就能發現漏報，信譽受損。

---

## 2. 方案演化記錄

### 2.1 已否決方案

**方案 A — APNIC 補丁清單**
手動維護一份「APNIC 漏收的 CN CIDR」靜態列表。
**否決理由**：信息會過時，每次雲廠商買新段都要手動更新，不可持續。

**方案 D — RIPE Stat geoloc 全量查詢**
對 APNIC 結果之外的所有 IP 段逐個查 geoloc。
**否決理由**：「APNIC 之外」是無界集合，查詢量不可估計。

**方案 E — 雲廠商官方 IP 列表 fetcher**
仿照 AWS `ip-ranges.json` 的模式，去阿里雲/騰訊雲/華為雲拉官方公開的全雲 IP 範圍 JSON。
**否決理由**：實地調研確認三家均無此類官方公開資源。只有 ListRegions/DescribeRegions 這類「地域元數據」API 和零散的產品級 endpoint 文檔，無法覆蓋計算實例範圍。商業文化差異——中國雲廠商沒有公開全 IP 範圍的動力，因為其客戶基本不做跨境白名單操作。

### 2.2 最終採納：方案 F + F1

**F：BGP 路由表反推（基於 ASN 宣告）**
通過 RIPE Stat 的 `announced-prefixes` API 拉取已知中國雲/互聯網公司 ASN 當前宣告的所有 BGP 前綴。BGP 是「網絡實際運行狀態」的信號，比任何註冊表都新鮮，且不受 RIR 邊界限制——無論前綴註冊在 APNIC 還是 ARIN，只要該 ASN 在宣告它，它就是該組織在用的網絡。

**F1：RIPE Stat geoloc 二次定位（含 fallback）**
對 F 拉到的每個前綴單獨查詢地理位置，按返回的國家代碼分桶到 CN/HK/TW/MO 對應的輸出文件。**這是解決「跨地區串庫」問題的唯一機制**——中國雲廠商在香港、新加坡、美西都有 region，這些段必須按地理位置精確分流。

### 2.3 為什麼選 F+F1
1. **零新依賴**：IPNova 已經在用 RIPE Stat 做 EXCLUDED_ASNS 的 BGP 查詢，所有 HTTP 客戶端、重試邏輯、rate limit 處理都是現成的，只是反向使用
2. **數據新鮮度**：BGP 是實時運行狀態
3. **天然解決串庫**：geoloc 二次定位從根源杜絕了香港段混入 CN.txt
4. **完全免費無需 license key**
5. **複用現有測試和維護心智模型**

---

## 3. ASN 分層模型

### 3.1 設計理念
不是所有 ASN 都「等價」。直接平等對待會有兩類風險：（a）混入運營商 ASN 導致全國家寬被誤標；（b）混合 ASN 內部的跨境段串庫。本規範採用三層分類，明確每層的處理策略。

### 3.2 Tier 1 — 純雲 ASN（高信任）
這些 ASN 的宣告段絕大多數是雲機房 IP，幾乎沒有家寬或辦公網污染。

| ASN | 組織 | 說明 |
|---|---|---|
| AS37963 | Aliyun Computing Co., Ltd. | 阿里雲中國，核心 ASN |
| AS45102 | Alibaba US Technology Co., Ltd. | 阿里雲海外主 ASN |
| AS132203 | Tencent Cloud Computing (Beijing) | 騰訊雲國際 |
| AS136907 | HUAWEI CLOUDS | 華為雲國際，乾淨的雲 ASN |

**處理策略**：geoloc 通過後直接寫入對應地區文件，元數據標記 `tier: 1, confidence: high`。

### 3.3 Tier 2 — 互聯網公司混合 ASN（中信任）

| ASN | 組織 | 包含內容 |
|---|---|---|
| AS45090 | Tencent Building, Kejizhongyi Avenue | 騰訊雲、微信、QQ、CDN、消費業務 |
| AS38365 | Baidu, Inc. | 搜索、CDN、Baidu Cloud |
| AS58593 | ByteDance | TikTok、抖音、CDN、火山引擎 |

**處理策略**：geoloc 通過後寫入對應地區文件，元數據標記 `tier: 2, confidence: medium`。

#### 3.3.1 Tier 2 已知局限（重要）

Tier 2 ASN 的宣告段內**確實會混入消費業務 IP**——騰訊家寬接入、字節跳動辦公網、百度企業專線等。對於這些段：

- **對「IP 國家歸屬」場景**：完全正確。這些 IP 本來就在中國，無論用途如何都應該屬於 CN.txt。
- **對「機房/雲基礎設施識別」場景**：是污染。下游需要做二次過濾才能區分雲段和消費段。

**本規範的決策**：IPNova 不在自身層面解決這個污染。理由：

1. **責任邊界**：IPNova 的職責是「IP 國家歸屬」，機房語義細分屬於下游問題
2. **不可逆性**：任何過濾規則（如 prefix length 閾值、rDNS 探測）都會誤殺正常雲段，而誤殺的數據無法找回
3. **成本不對等**：在 IPNova 層引入過濾會大幅增加複雜度（rDNS 查詢、緩存、超時處理），但收益僅服務於「機房識別」這一個下游場景
4. **更好的歸屬**：未來如真有「精準雲機房識別」需求，應另立 `asnnova` 項目（ASN 元數據庫），與 IPNova 解耦

**對下游消費者的承諾**：通過 `meta.json` 中 `confidence: medium` 標記讓下游明確知曉哪些前綴來自 Tier 2，下游可選擇是否信任這些條目。

### 3.4 Tier 3 — 運營商 ASN（永久禁止）
運營商骨幹 ASN 包含家寬、IDC、DSLAM 接入網、企業專線等所有類型，**範圍過大且語義不明確**。一旦混入會把全國家寬 IP 全標成「雲」或「機房」，下游打分模型徹底崩盤。

| ASN | 組織 |
|---|---|
| AS58466 | China Telecom |
| AS4134 | China Telecom Backbone |
| AS4837 | China Unicom Backbone |
| AS9808 | China Mobile |
| AS4538 | CERNET（教育網骨幹） |
| AS17621 | China Unicom Shanghai |
| AS9394 | China Railway Telecom |

**處理策略**：硬編碼為 `FORBIDDEN_ASNS` 常量。腳本啟動時做 sanity check：如果 `CN_CLOUD_ASNS` 與 `FORBIDDEN_ASNS` 有交集，立即報錯退出。這是防呆設計，避免未來有人手滑把運營商 ASN 加進收錄列表。

### 3.5 已評估但不收錄的 ASN

| ASN | 組織 | 不收錄原因 |
|---|---|---|
| **AS55990** | Huawei Technologies Co., Ltd. | 過於混雜（企業辦公網 + 設備測試網 + 研發中心 + 部分雲），污染程度高於 Tier 2 平均水平，可能引入大量非機房 IP。華為雲的覆蓋僅依靠 AS136907 一個 Tier 1 ASN。未來若有需要可作為 optional 擴展源，需配合 rDNS 過濾才能納入。 |

### 3.6 不採納的設計
某輪 Review 建議引入 `cloud_confidence: 0.6` 連續數字和 `tags: ["cloud","cdn","consumer"]` 標籤系統。本規範拒絕該建議：
- 超出 IPNova 範圍（IP 歸屬庫 ≠ ASN 風控標籤系統）
- confidence 數字的計算模型需要訓練數據，這是另一個項目
- 商業價值錯配——IPNova 的核心是國家歸屬精度，不是雲 IP 細分
- 應由獨立的 `asnnova` 項目承擔

本規範只引入兩級 tier 標記（1=high, 2=medium），不引入連續 confidence。

---

## 4. 技術改造設計

### 4.1 改動涉及的文件
- `generate_ip_list.py`（主要改動）
- `output/meta.json` schema 擴展
- `README.md` 章節更新
- `.github/workflows/update.yml`（延長 timeout）

### 4.2 新增常量

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

### 4.3 新增函數：geoloc 三級 fallback

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

### 4.4 新增函數：cloud supplementary builder

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

### 4.5 主流程集成
```
Step 1: APNIC download              (existing)
Step 2: build EXCLUDED networks     (existing)
Step 3: parse APNIC                 (existing)
Step 4: build cloud supplementary   (NEW)
Step 5: merge per region            (NEW - union + collapse_addresses)
Step 6: sanity check                (existing, threshold bumped)
Step 7: save outputs                (existing, with confidence metadata)
```

### 4.6 合併邏輯
對每個 region：`final = collapse_addresses(apnic_result + cloud_supplementary)`。`ipaddress.collapse_addresses` 自動去重和聚合相鄰段。

### 4.7 性能預期與優化
- 現有：1-2 分鐘
- 改造後：10-20 分鐘
- 主要開銷：geoloc 查詢數量 = ΣASN 宣告的前綴數，預估 2000-5000 次查詢 × rate limit
- **本地緩存**：單次運行內建立 `geoloc_cache` dict，避免重複查詢相同前綴
- **跨運行緩存**（可選 P0.5d 優化）：將 geoloc 結果持久化到 `output/.geoloc_cache.json`，TTL 24 小時，可進一步降低後續運行的查詢量
- 後台 cron 任務可接受

### 4.8 失敗模式與降級
- 單個 ASN 查詢失敗：log warning，跳過該 ASN，繼續其他
- 單個 prefix 三級 fallback 全部失敗：標記為 UNKNOWN，不寫入任何 region 文件
- 整體 RIPE Stat 不可用：回退到純 APNIC 模式（與現有行為一致），meta.json 標記 `cloud_supplement: failed`
- sanity check 失敗：腳本退出，不覆蓋上一次成功的輸出

---

## 5. meta.json schema 擴展

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

## 6. 測試策略

### 6.1 標杆驗證用例
| 域名/IP | 期望結果 |
|---|---|
| ctrip.com → 8.153.x.x | 改造後 8.153.0.0/16 應在 CN.txt 中 |
| 阿里雲 cn-hongkong region IP（如 47.x） | 應在 HK.txt，**不在** CN.txt |
| China Telecom 家寬 IP | 應在 CN.txt（來自 APNIC 既有覆蓋），不應因 cloud supplement 流程出現重複 |

### 6.2 回歸測試
改造後 CN.txt 行數應 **大於等於** 改造前（5493 個 CIDR），HK.txt 也應略增。如果反而減少，說明合併邏輯有 bug。

### 6.3 串庫驗證（負向測試）
- 從阿里雲文檔取一兩個已知的香港 region 樣本前綴
- 確認改造後 CN.txt **不包含**這些前綴
- 確認它們出現在 HK.txt 中

### 6.4 Tier 3 防呆測試
單元測試：構造一個臨時把 AS58466 加入 CN_CLOUD_ASNS 的場景，確認 module load 階段立即拋 RuntimeError。

---

## 7. 分階段路線圖

| 階段 | 範圍 | 預估規模 |
|---|---|---|
| **P0.5a** | CN_CLOUD_ASNS / FORBIDDEN_ASNS 常量、`fetch_prefix_country` 三級 fallback、`build_cloud_supplementary_networks` | ~180 行 |
| **P0.5b** | main 流程集成、合併邏輯、meta.json 擴展 | ~60 行 |
| **P0.5c** | sanity check 升級、失敗降級邏輯、Tier 3 防呆測試 | ~40 行 |
| **P0.5d** | README 更新、workflow timeout 調整、（可選）跨運行緩存、release v3.0 | 文檔為主 |
| **P0.5e（驗證）** | 本地跑通 + ctrip.com 標杆驗證 + 串庫驗證 | 用戶執行 |

P0.5a-d 可在一輪對話內完成代碼改造。

---

## 8. 與 DomainNova 的銜接

P0.5 完成後，DomainNova 不需要任何代碼改動，直接重跑 `build_domains.py`：
- ctrip.com 自動救回
- 其他被誤殺的大站自動恢復
- seed.txt 中那些「品牌名正確但 .com 主域實際在海外」的條目（bankofchina.com、icbc.com 等）依然被淘汰，這是正確行為
- 之後進入 DomainNova P1（多地區改造）

---

## 9. 待校準參數

| 參數 | 初版建議值 | 說明 |
|---|---|---|
| `GEOLOC_REQUEST_INTERVAL` | 0.5 秒 | RIPE Stat rate limit 緩衝 |
| `GEOLOC_CACHE_TTL_HOURS` | 24 | 跨運行緩存有效期 |
| sanity check CN 下限 | 5500 | 改造後預期 |
| sanity check HK 下限 | 1100 | 預期略增 |
| geoloc 失敗率閾值 | 30% | 超過則整體標記 degraded |

---

## 10. 下輪對話啟動指令

> **「開始 P0.5a-d：實施 IPNova 多源融合改造，按規範書 v0.2 執行」**

執行範圍：
1. 修改 `generate_ip_list.py`
2. 更新 `README.md`
3. 更新 `.github/workflows/update.yml`
4. 打包帶完整目錄結構的 zip（含 `generate_ip_list.py`，可通過 `ipnova_repo.sh` 完整性檢查）
5. 用戶本地拉取後執行 P0.5e 驗證
