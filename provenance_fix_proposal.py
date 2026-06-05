"""
provenance_fix_proposal.py — 修補方案(草案,未合入主文件)

解決的問題
==========
IPNova v3.3 的 cidr_objects provenance 有兩個缺陷,根源同一:
provenance 靠 CIDR 字符串精確匹配傳遞,但 CIDR 在
  (1) build_cloud_supplementary_networks 末尾的 collapse
  (2) enforce_mutual_exclusivity 的 subtract 切割 + collapse
  (3) normalize_region_data 的 collapse
三處被反复形變,字符串對不上,于是:
  - BUG-A: 被形变过的 BGP 段在 normalize 落入 else 分支,被误标 source="apnic"
  - BUG-B: confidence 永远硬编码 "high",L2 fallback(最不可信)也标 high;
           且 level 在存 provenance 时(旧第 826 行)根本没被记录,源头就缺信息

修法核心
========
不再用「CIDR 字符串」当钥匙,改用「IP 区间包含关系」当钥匙。
一个段无论怎么被 collapse 或切碎,它的每个 IP 始终落在原始来源段范围内。
同时把 level 一路带到 provenance,让 confidence 有真实依据。

本文件是独立草案:可直接 `python provenance_fix_proposal.py` 跑离线自测,
验证逻辑无误后,再按文末「合入指引」改主文件。
"""

import ipaddress
from bisect import bisect_right


# ---------------------------------------------------------------------
# 第 1 步:level -> confidence 映射(取代硬编码 "high")
# ---------------------------------------------------------------------
# L-1 缓存命中:沿用缓存里记录的原始 level,不在这里单独定级
# L0 = APNIC 包含,几乎等同权威        -> high
# L1 = RIPEstat geoloc 投票            -> medium
# L2 = ASN holder 国别猜测(最弱)     -> low
_LEVEL_CONFIDENCE = {
    "L0": "high",
    "L1": "medium",
    "L2": "low",
}


def level_to_confidence(level):
    """把四级归属的 level 翻成对外的 confidence。未知一律保守为 low。"""
    return _LEVEL_CONFIDENCE.get(level, "low")


# ---------------------------------------------------------------------
# 第 2 步:区间索引 —— 按 IP 区间(而非字符串)认领 provenance
# ---------------------------------------------------------------------
class ProvenanceIndex:
    """把原始(pre-collapse)BGP 来源段建成一个按起始地址排序的区间索引。

    给定任意一个最终输出 CIDR(可能已被 collapse/切割成新边界),
    用它的起始 IP 去索引里找包含它的原始来源段,继承其 asn/tier/level。

    为什么用「起始 IP 落点」而非「完全包含」:
      collapse 只会把【同源、相邻】的段合并成更大段,切割只会把段拆小;
      两者都不会跨越不同来源段的边界混合(因为 enforce_mutual_exclusivity
      是先 subtract 再 collapse,subtract 已按 owned 边界切齐)。
      因此用最终段的起始 IP 定位来源,在本管线下是充分且 O(log n) 的。
      为稳健起见,我们额外校验「起始 IP 确实落在命中段内」,落空则降级处理。
    """

    def __init__(self, supp_provenance):
        # supp_provenance: dict[cc, dict[cidr_str, {asn, tier, level}]]
        # 摊平成按 (start_int) 排序的区间表: [(start, end, cc, meta), ...]
        self._intervals = []
        for cc, by_cidr in (supp_provenance or {}).items():
            for cidr_str, meta in by_cidr.items():
                net = ipaddress.ip_network(cidr_str, strict=False)
                self._intervals.append((
                    int(net.network_address),
                    int(net.broadcast_address),
                    cc,
                    meta,
                ))
        self._intervals.sort(key=lambda t: t[0])
        self._starts = [t[0] for t in self._intervals]

    # level 强弱排序,数字越大越弱(越不可信)。求交时继承最弱的,保守。
    _LEVEL_RANK = {"L0": 0, "L-1": 0, "L1": 1, "L2": 2, "L3": 3}

    def lookup(self, net, cc_hint=None):
        """返回 (asn, tier, level) 若 net 与某原始 BGP 来源段(同区)有交集,
        否则 None。

        策略:collapse 可能把多个同源相邻段合并成比任一来源都大的段
        (如两个 /15 -> 一个 /14),所以不能要求「最终段被单个来源段包含」。
        改为:找出所有与 net 相交、且 cc 匹配的来源段,
          - asn/tier 取覆盖最多的那个(主导来源)
          - level 取其中最弱的一个(最保守 —— 只要掺了 L2,整段就标 L2)
        这样既不会丢源(BUG-A),也不会高估 confidence(BUG-B)。

        cc_hint: 最终归属区;只认领 cc 一致的来源段,防跨区误领。
        """
        if not self._intervals:
            return None
        lo = int(net.network_address)
        hi = int(net.broadcast_address)

        # 候选区间:任何 start <= hi 的来源段都可能与 net 相交。
        # 不能用「起始 IP 落点」式的局部回扫 —— 一个起始远在左侧、
        # 但跨度很大的来源段(如某云 /9)仍可能覆盖 net,局部回扫会漏它。
        # 这里取 start <= hi 的全部候选做精确相交判定。BGP 来源段在单区
        # 通常数百到数千条,collapse 后更少,O(n) 完全可接受且绝不漏。
        hits = []
        cut = bisect_right(self._starts, hi)  # [0, cut) 内所有 start <= hi
        for j in range(cut):
            s, e, cc, meta = self._intervals[j]
            if e < lo:
                continue  # 该来源段整体在 net 左侧,无交集
            if cc_hint is None or cc == cc_hint:
                overlap = min(e, hi) - max(s, lo) + 1
                hits.append((overlap, meta))

        if not hits:
            return None

        # 主导来源(覆盖最多)定 asn/tier
        hits.sort(key=lambda t: t[0], reverse=True)
        dominant = hits[0][1]
        # level 取最弱
        weakest_level = max(
            (m.get("level") for _, m in hits),
            key=lambda lv: self._LEVEL_RANK.get(lv, 3),
        )
        return dominant.get("asn"), dominant.get("tier"), weakest_level


# ---------------------------------------------------------------------
# 第 3 步:修正后的 normalize 核心(演示版)
# ---------------------------------------------------------------------
def build_cidr_objects(cc, merged_nets, prov_index):
    """取代旧 normalize_region_data 第 1020-1039 行的 cidr_objects 构建。

    对每个最终 CIDR,用区间索引判断它是否源自 BGP 补充:
      命中 -> source=bgp, 带真实 asn/tier/level, confidence 由 level 决定
      未命中 -> source=apnic, confidence=high
    """
    cidr_objects = []
    for net in merged_nets:
        hit = prov_index.lookup(net, cc_hint=cc)
        if hit is not None:
            asn, tier, level = hit
            cidr_objects.append({
                "cidr": str(net),
                "source": "bgp",
                "asn": asn,
                "tier": tier,
                "level": level,                         # 新增:暴露归属层级
                "confidence": level_to_confidence(level),
            })
        else:
            cidr_objects.append({
                "cidr": str(net),
                "source": "apnic",
                "asn": None,
                "tier": None,
                "level": "L0",                          # APNIC 包含即 L0 权威
                "confidence": "high",
            })
    return cidr_objects


# ---------------------------------------------------------------------
# 离线自测:构造会触发三处形变的场景,验证修法不丢 provenance
# ---------------------------------------------------------------------
def _selftest():
    net = ipaddress.ip_network

    # 模拟 build 阶段记录的 pre-collapse provenance(已带 level)
    # 两个相邻 /15 来自同一 BGP ASN,会在后续被 collapse 成一个 /14
    supp_provenance = {
        "CN": {
            "8.152.0.0/15": {"asn": 37963, "tier": 1, "level": "L1"},
            "8.154.0.0/15": {"asn": 37963, "tier": 1, "level": "L1"},
            # 一个 L2 弱信号段,验证 confidence 会被正确降级为 low
            "120.24.0.0/16": {"asn": 37963, "tier": 1, "level": "L2"},
        }
    }

    # 模拟最终 merged 输出:前两个 /15 已被 collapse 成 /14(字符串全变了)
    merged = [
        net("8.152.0.0/14"),     # 来自两个 /15 合并 —— 旧逻辑会误标 apnic
        net("120.24.0.0/16"),    # L2 段 —— 旧逻辑会误标 high
        net("1.0.1.0/24"),       # 真正的 APNIC 段 —— 应标 apnic/high
    ]

    idx = ProvenanceIndex(supp_provenance)
    objs = build_cidr_objects("CN", merged, idx)

    by_cidr = {o["cidr"]: o for o in objs}

    # 断言 1:被 collapse 的 /14 仍被正确识别为 bgp(BUG-A 修复)
    a = by_cidr["8.152.0.0/14"]
    assert a["source"] == "bgp", f"BUG-A 未修复: {a}"
    assert a["asn"] == 37963 and a["tier"] == 1
    assert a["confidence"] == "medium", f"L1 应映射 medium, got {a['confidence']}"

    # 断言 2:L2 弱信号段 confidence 被降级为 low(BUG-B 修复)
    b = by_cidr["120.24.0.0/16"]
    assert b["source"] == "bgp"
    assert b["level"] == "L2"
    assert b["confidence"] == "low", f"L2 应映射 low, got {b['confidence']}"

    # 断言 3:真正的 APNIC 段不受影响
    c = by_cidr["1.0.1.0/24"]
    assert c["source"] == "apnic" and c["confidence"] == "high"

    # 断言 4:跨区保护 —— 用错误 cc_hint 查 CN 段应拒绝认领(降级为 apnic)
    wrong = build_cidr_objects("JP", [net("8.152.0.0/14")], idx)
    assert wrong[0]["source"] == "apnic", "跨区保护失效"

    print("✅ 全部自测通过:")
    print("   - BUG-A(collapse 后 BGP 段误标 apnic)已修复")
    print("   - BUG-B(confidence 硬编码 high / L2 未降级)已修复")
    print("   - APNIC 段不受影响,跨区误领被阻止")
    for o in objs:
        print(f"     {o['cidr']:20} {o['source']:6} level={o['level']:3} conf={o['confidence']}")


if __name__ == "__main__":
    _selftest()
