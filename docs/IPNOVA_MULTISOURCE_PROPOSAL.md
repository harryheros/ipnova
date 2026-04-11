# IPNova 多源融合改造規範書 v0.1

> Status: Draft · Author: collaborative session · Target: IPNova v3.0
> Predecessor: DomainNova `PROPOSAL_MULTI_REGION.md`

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
- 估計受影響域名數量：在 DomainNova 當前 ~700 行 seed.txt 中，至少 20-50 個大站受此問題影響

### 1.4 商業影響
這個盲區直接威脅 DomainNova 作為「精準 CN 基礎設施數據集」的商業價值。賣給合規客戶時，客戶用自己的已知資產一驗證就能發現漏報，信譽受損。

---

## 2. 方案演化記錄

### 2.1 已否決方案

**方案 A — APNIC 補丁清單**
手動維護一份「APNIC 漏收的 CN CIDR」靜態列表。
**否決理由**：信息會過時，每次雲廠商買新段都要手動更新，不可持續。

**方案 E — 雲廠商官方 IP 列表 fetcher**
仿照 AWS `ip-ranges.json` 的模式，去阿里雲/騰訊雲/華為雲拉官方公開的全雲 IP 範圍 JSON。
**否決理由**：實地調研確認三家雲廠商均無此類官方公開資源。只有 ListRegions/DescribeRegions 這類「地域元數據」API 和零散的產品級 endpoint 文檔，無法覆蓋計算實例範圍。商業文化差異——中國雲廠商沒有公開全 IP 範圍的動力，因為其客戶基本不做跨境白名單操作。

**方案 D — RIPE Stat geoloc 全量查詢**
對 APNIC 結果之外的所有 IP 段逐個查 geoloc。
**否決理由**：「APNIC 之外」是一個無界集合，查詢量不可估計。

### 2.2 最終採納：方案 F + F1

**F：BGP 路由表反推（基於 ASN 宣告）**
通過 RIPE Stat 的 `announced-prefixes` API 拉取已知中國雲/互聯網公司 ASN 當前宣告的所有 BGP 前綴。BGP 是「網絡實際運行狀態」的信號，比任何註冊表都新鮮，且不受 RIR 邊界限制——無論前綴註冊在 APNIC 還是 ARIN，只要該 ASN 在宣告它，它就是該組織在用的網絡。

**F1：RIPE Stat geoloc 二次定位**
對 F 拉到的每個前綴單獨查詢地理位置，按返回的國家代碼分桶到 CN/HK/TW/MO 對應的輸出文件。**這是解決「跨地區串庫」問題的唯一機制**——中國雲廠商在香港、新加坡、美西都有 region，這些段必須按地理位置精確分流，而不是無腦塞進 CN.txt。

### 2.3 為什麼選 F+F1
1. **零新依賴**：IPNova 已經在用 RIPE Stat 做 EXCLUDED_ASNS 的 BGP 查詢，所有 HTTP 客戶端、重試邏輯、rate limit 處理都是現成的，只是反向使用
2. **數據新鮮度**：BGP 是實時運行狀態
3. **天然解決串庫**：geoloc 二次定位從根源杜絕了香港段混入 CN.txt
4. **完全免費無需 license key**
5. **複用現有測試和維護心智模型**

---

## 3. ASN 分層模型

### 3.1 設計理念
不是所有 ASN 都「等價」。直接把所有 ASN 平等對待會有兩類風險：（a）混入運營商 ASN 導致全國家寬被誤標；（b）混合 ASN 內部的跨境段串庫。本規範採用三層分類，明確每層的處理策略。

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
這些 ASN 屬於中國互聯網大廠，宣告段內混合了雲服務、CDN、消費業務、辦公網等多種用途。**對 CN 國家歸屬識別場景而言，這種混合不是問題**——這些段全部都在中國境內活動，無論用途如何都應該屬於 CN.txt。需要警惕的只是**跨境段**。

| ASN | 組織 | 包含內容 |
|---|---|---|
| AS45090 | Tencent Building, Kejizhongyi Avenue | 騰訊雲、微信、QQ、CDN、消費業務 |
| AS38365 | Baidu, Inc. | 搜索、CDN、Baidu Cloud |
| AS58593 | ByteDance | TikTok、抖音、CDN、火山引擎 |
| AS55990 | Huawei Technologies | 華為雲、企業網絡、設備測試網 |

**處理策略**：geoloc 通過後寫入對應地區文件，元數據標記 `tier: 2, confidence: medium`。下游消費者（如 DomainNova）可選擇是否信任 medium 級別的條目。

### 3.4 Tier 3 — 運營商 ASN（永久禁止）
運營商骨幹 ASN 的宣告段包含家寬、IDC、DSLAM 接入網、企業專線等所有類型，**範圍過大且語義不明確**。一旦混入會把全國家寬 IP 全標成「雲」或「機房」，下游打分模型徹底崩盤。

| ASN | 組織 |
|---|---|
| AS58466 | China Telecom |
| AS4134 | China Telecom Backbone |
| AS4837 | China Unicom |
| AS9808 | China Mobile |

**處理策略**：硬編碼為**禁止清單常量** `FORBIDDEN_ASNS`。腳本啟動時做 sanity check：如果 `CN_CLOUD_ASNS` 與 `FORBIDDEN_ASNS` 有交集，立即報錯退出。這是防呆設計，避免未來有人手滑把運營商 ASN 加進收錄列表。

### 3.5 不採納的設計
那份分析建議引入 `cloud_confidence: 0.6` 數字和 `tags: ["cloud","cdn","consumer"]` 標籤系統。**本規範拒絕該建議**，理由：
- 超出 IPNova 範圍（IP 歸屬庫 ≠ ASN 風控標籤系統）
- confidence 數字的計算模型需要訓練數據，這是另一個項目
- 商業價值錯配——IPNova 的核心是國家歸屬精度，不是雲 IP 細分
- 如未來確需 ASN 元數據能力，應另立 `asnnova` 項目，與 IPNova 解耦

本規範只引入兩級 tier 標記（1=high, 2=medium），不引入連續 confidence。

---

## 4. 技術改造設計

### 4.1 改動涉及的文件
- `generate_ip_list.py`（主要改動）
- `output/meta.json` schema 擴展
- `README.md` 章節更新
- `.github/workflows/update.yml`（可能需要延長 timeout）

### 4.2 新增常量（`generate_ip_list.py` 頂部）

```python
# ================================================================
# Cloud / Internet Company ASNs for ARIN-gap supplementation
# ================================================================
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
    55990: "Huawei Technologies",
}

CN_CLOUD_ASNS = {**CN_CLOUD_ASNS_TIER1, **CN_CLOUD_ASNS_TIER2}

# ================================================================
# Forbidden ASNs - operator backbone, must NEVER be in CN_CLOUD_ASNS
# ================================================================
FORBIDDEN_ASNS = {
    58466: "China Telecom",
    4134:  "China Telecom Backbone",
    4837:  "China Unicom",
    9808:  "China Mobile",
}

# Sanity check at module load time
_overlap = set(CN_CLOUD_ASNS.keys()) & set(FORBIDDEN_ASNS.keys())
if _overlap:
    raise RuntimeError(
        f"Forbidden ASN(s) found in CN_CLOUD_ASNS: {_overlap}. "
        f"Operator backbone ASNs must never be used as cloud sources."
    )

RIPE_GEOLOC_URL = "https://stat.ripe.net/data/geoloc/data.json"
```

### 4.3 新增函數

```python
def fetch_prefix_geoloc(prefix: str) -> Optional[str]:
    """
    Query RIPE Stat geoloc for a single prefix, return ISO country code or None.
    Uses the same http_get retry/backoff as existing RIPE Stat calls.
    """
    url = f"{RIPE_GEOLOC_URL}?resource={prefix}"
    try:
        data = http_get(url, timeout=15)
        # Parse JSON, extract country code from data.locations[0].country
        # Return None on parse failure (caller treats as UNKNOWN)
    except Exception as e:
        log.warning("geoloc fetch failed for %s: %s", prefix, e)
        return None


def build_cloud_supplementary_networks() -> Dict[str, List[ipaddress.IPv4Network]]:
    """
    For each ASN in CN_CLOUD_ASNS:
      1. Fetch all announced prefixes via fetch_asn_prefixes() (existing function)
      2. For each prefix, query geoloc to determine country
      3. Bucket into {region: [networks]} where region is CN/HK/TW/MO
      4. Drop prefixes that resolve to non-target regions (US/SG/EU/etc)

    Returns {region_code: [IPv4Network, ...]}
    """
    result = {region: [] for region in TARGET_REGIONS}
    for asn, label in sorted(CN_CLOUD_ASNS.items()):
        try:
            prefixes = fetch_asn_prefixes(asn)
            log.info("AS%d %s: %d prefixes from BGP", asn, label, len(prefixes))
            for net in prefixes:
                country = fetch_prefix_geoloc(str(net))
                if country in TARGET_REGIONS:
                    result[country].append(net)
                time.sleep(GEOLOC_REQUEST_INTERVAL)
        except Exception as e:
            log.error("Failed to process AS%d: %s", asn, e)
    return result
```

### 4.4 主流程集成（`main()` 修改）
在現有的「APNIC 解析 → 減去 EXCLUDED_ASNS → sanity check → 輸出」流程中插入新步驟：

```
Step 1: APNIC download              (existing)
Step 2: build EXCLUDED networks     (existing)
Step 3: parse APNIC                 (existing)
Step 4: build cloud supplementary   (NEW - this proposal)
Step 5: merge per region            (NEW - union + collapse_addresses)
Step 6: sanity check                (existing, threshold may bump)
Step 7: save outputs                (existing)
```

### 4.5 合併邏輯
對每個 region：`final = collapse_addresses(apnic_result + cloud_supplementary)`。`ipaddress.collapse_addresses` 會自動去重和聚合相鄰段，確保輸出乾淨。

### 4.6 性能預期
- 現有：1-2 分鐘
- 改造後：10-20 分鐘
- 主要開銷：geoloc 查詢數量 = ΣASN 宣告的前綴數，預估 2000-5000 次查詢 × rate limit
- 後台 cron 任務可接受

### 4.7 失敗模式與降級
- 單個 ASN 查詢失敗：log warning，跳過該 ASN，繼續其他 ASN
- 單個 prefix geoloc 失敗：標記為 UNKNOWN，不寫入任何 region 文件
- 整體 RIPE Stat 不可用：回退到純 APNIC 模式（與現有行為一致），meta.json 標記 `cloud_supplement: failed`
- sanity check 失敗：腳本退出，不覆蓋上一次成功的輸出

---

## 5. meta.json schema 擴展

新增字段：
```json
{
  "version": "3.0",
  "sources": [
    {"name": "APNIC delegated-apnic-latest", "type": "registry"},
    {"name": "RIPE Stat BGP + geoloc", "type": "bgp_supplement"}
  ],
  "cloud_supplement": {
    "enabled": true,
    "asn_count": 8,
    "tier1_asn_count": 4,
    "tier2_asn_count": 4,
    "prefixes_fetched": 3421,
    "prefixes_kept_cn": 412,
    "prefixes_kept_hk": 89,
    "prefixes_kept_tw": 12,
    "prefixes_kept_mo": 0,
    "prefixes_dropped_other_country": 156,
    "prefixes_dropped_no_geoloc": 23,
    "duration_seconds": 847
  }
}
```

下游消費者（DomainNova）可讀取這些統計做監控告警。

---

## 6. 測試策略

### 6.1 標杆驗證用例
| 域名 | 期望 IP | 期望結果 |
|---|---|---|
| ctrip.com | 8.153.x.x | 改造後 8.153.0.0/16 應在 CN.txt 中 |
| 任意阿里雲 cn-hongkong region IP | 47.x | 應在 HK.txt 中，**不在** CN.txt |
| 任意 China Telecom 家寬 IP | 自選 | 應在 CN.txt（來自 APNIC 既有覆蓋），不應因 cloud supplement 流程出現重複 |

### 6.2 回歸測試
改造後的 CN.txt 行數應 **大於等於** 改造前（5493 個 CIDR），HK.txt 也應略增。如果反而減少，說明合併邏輯有 bug。

### 6.3 串庫驗證
專門檢查改造後 CN.txt 是否混入任何阿里雲香港 region 已知段。可從阿里雲文檔或實測中取一兩個樣本前綴做負向測試。

---

## 7. 分階段路線圖

| 階段 | 範圍 | 預估規模 |
|---|---|---|
| **P0.5a** | 實現 CN_CLOUD_ASNS / FORBIDDEN_ASNS 常量、`fetch_prefix_geoloc` 函數、`build_cloud_supplementary_networks` 函數 | ~150 行新代碼 |
| **P0.5b** | main 流程集成、合併邏輯、meta.json 擴展 | ~50 行 |
| **P0.5c** | sanity check 升級、失敗降級邏輯 | ~30 行 |
| **P0.5d** | README 更新、workflow timeout 調整、release v3.0 | 文檔為主 |
| **P0.5e（驗證）** | 本地跑通 + ctrip.com 標杆驗證 + 串庫驗證 | 你來跑 |

P0.5a-d 可在一輪對話內完成代碼改造，P0.5e 由你本地驗證。

---

## 8. 與 DomainNova 的銜接

P0.5 全部完成後，DomainNova 不需要做任何代碼改動，直接重跑 `build_domains.py` 即可：
- ctrip.com 會被自動救回
- 其他被誤殺的大站也會自動恢復
- seed.txt 中那些「品牌名正確但 .com 主域實際在海外」的條目（如 bankofchina.com、icbc.com）依然會被淘汰，這是正確行為
- 之後再進入 DomainNova P1（多地區改造）

---

## 9. 待校準參數

| 參數 | 初版建議值 | 說明 |
|---|---|---|
| `GEOLOC_REQUEST_INTERVAL` | 0.5 秒 | RIPE Stat geoloc rate limit 緩衝 |
| sanity check CN 下限 | 5000 → 5500 | 改造後預期會增加 |
| sanity check HK 下限 | 1000 → 1100 | 預期略增 |
| geoloc 失敗率閾值 | 30% | 超過則整體標記為 degraded |

---

## 10. 下輪對話啟動指令

> 「**開始 P0.5a-d：實施 IPNova 多源融合改造，按規範書執行**」

收到此指令後，我會：
1. 直接修改 `generate_ip_list.py`
2. 更新 README.md
3. 更新 `.github/workflows/update.yml`
4. 打包帶完整目錄結構的 zip
5. 你本地拉取後執行 P0.5e 驗證
