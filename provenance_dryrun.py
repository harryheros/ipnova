#!/usr/bin/env python3
"""
provenance_dryrun.py — provenance 修法「副作用偵察」腳本(只讀,零侵入)

用途
====
在你的 Debian 連網環境跑這個腳本,它會:
  1. 走一遍真實構建流程(下載 APNIC、查 RIPEstat、跑 cloud supplement);
  2. 在 enforce_mutual_exclusivity + normalize 之後,用【舊邏輯】和【新邏輯】
     各算一次每個 region 的 cidr_objects;
  3. 逐段對比,輸出一張报告:多少段 apnic→bgp、多少 high→medium、high→low;
  4. **不写任何 output 文件,不改主流程**。你的 output/ 目录一字节不变。

跑完你就拿到那个决定性的数字,再决定要不要合入修法。

放置位置
========
把本文件和 provenance_fix_proposal.py 一起放在 ipnova 项目根目录
(与 generate_ip_list.py 同级),然后:

    python3 provenance_dryrun.py                 # 完整重跑(需联网)
    python3 provenance_dryrun.py --skip-canary   # 同主程序的 flag 透传

如果只想用现有 output/data.json 做「旧逻辑现状」快照而不重跑,见 --from-data-json。
"""

import argparse
import json
import sys
import ipaddress
from collections import defaultdict

# 复用修法草案里的新逻辑
from provenance_fix_proposal import ProvenanceIndex, build_cidr_objects, level_to_confidence

import generate_ip_list as G


# ---------------------------------------------------------------------
# 旧逻辑复刻:精确照搬 normalize_region_data 第 1020-1039 行的 cidr_objects 构建
# (字符串精确匹配 + confidence 硬编码 high)。用于和新逻辑对照。
# ---------------------------------------------------------------------
def old_build_cidr_objects(cc, merged_nets, supp_provenance):
    cc_prov = (supp_provenance or {}).get(cc, {})
    objs = []
    for net in merged_nets:
        s = str(net)
        if s in cc_prov:
            entry = cc_prov[s]
            objs.append({"cidr": s, "source": "bgp", "asn": entry.get("asn"),
                         "tier": entry.get("tier"), "confidence": "high"})
        else:
            objs.append({"cidr": s, "source": "apnic", "asn": None,
                         "tier": None, "confidence": "high"})
    return objs


# ---------------------------------------------------------------------
# level 旁路捕获:monkey-patch fetch_prefix_country,把每个 prefix 的 level
# 记到一个旁路字典(prefix_str -> level),供新逻辑给 provenance 补上 level。
# 主文件一行不改;patch 只在本进程内存生效。
# ---------------------------------------------------------------------
_LEVEL_SIDECAR = {}

def _install_level_capture():
    orig = G.fetch_prefix_country
    def wrapped(prefix, asn, region_data=None):
        cc, level = orig(prefix, asn, region_data)
        try:
            _LEVEL_SIDECAR[str(ipaddress.ip_network(prefix, strict=False))] = level
        except Exception:
            pass
        return cc, level
    G.fetch_prefix_country = wrapped
    return orig


def _enrich_provenance_with_level(supp_provenance):
    """给 supp_provenance 每条记录补上 level(从旁路字典按 cidr_str 取;
    取不到的保守标 None -> 新逻辑会映射成 low)。返回新字典,不改原对象。"""
    out = {}
    for cc, by_cidr in (supp_provenance or {}).items():
        out[cc] = {}
        for cidr_str, meta in by_cidr.items():
            m = dict(meta)
            m["level"] = _LEVEL_SIDECAR.get(cidr_str)  # 可能 None
            out[cc][cidr_str] = m
    return out


def run_real_build(argv):
    """走真实构建流程,返回 (normalized_region_nets, supp_provenance_with_level)。
    normalized_region_nets: dict[cc, list[IPv4Network]] —— enforce 之后的最终段。
    """
    parser = G.build_parser()
    args = parser.parse_args(argv)
    G.setup_logging(verbose=getattr(args, "verbose", False))
    G.set_geoloc_cache_path(args.output_dir)

    _install_level_capture()

    raw_data = G.download_apnic_data()
    excluded_networks, asn_report = G.build_excluded_networks(skip_ripe=args.skip_ripe)
    region_data, parse_stats = G.parse_and_cleanse(raw_data, excluded_networks)

    if not getattr(args, "skip_canary", False):
        from regions import canary_networks
        for cc, canary_net in canary_networks().items():
            region_data.setdefault(cc, []).append(canary_net)

    supp = None
    supp_provenance = {}
    if not (args.skip_ripe or args.skip_cloud_supplement):
        supp, supp_provenance, _ = G.build_cloud_supplementary_networks(region_data)

    region_data = G.enforce_mutual_exclusivity(region_data, supp_data=supp)

    # 复刻 normalize 里的 collapse,拿到最终 merged 段(与输出完全一致)
    final = {}
    for cc in G.TARGET_REGIONS:
        nets = region_data.get(cc, [])
        final[cc] = sorted(ipaddress.collapse_addresses(nets))

    prov_with_level = _enrich_provenance_with_level(supp_provenance)
    return final, prov_with_level


def compare(final_nets, prov_with_level):
    """新旧逻辑逐段对比,打印报告。"""
    print("\n" + "=" * 64)
    print("  PROVENANCE 修法 DRY-RUN 对比报告(未改动任何输出文件)")
    print("=" * 64)

    grand = {
        "src_apnic_to_bgp": 0,
        "src_bgp_to_apnic": 0,   # 理论上不应发生;若有则是新逻辑过度认领,需警惕
        "conf_high_to_medium": 0,
        "conf_high_to_low": 0,
        "conf_unchanged_high": 0,
        "total": 0,
    }

    for cc in G.TARGET_REGIONS:
        nets = final_nets.get(cc, [])
        if not nets:
            continue
        idx = ProvenanceIndex({cc: prov_with_level.get(cc, {})})
        old = old_build_cidr_objects(cc, nets, prov_with_level)
        new = build_cidr_objects(cc, nets, idx)

        r = {"src_apnic_to_bgp": 0, "src_bgp_to_apnic": 0,
             "conf_high_to_medium": 0, "conf_high_to_low": 0,
             "conf_unchanged_high": 0, "total": len(nets)}

        for o, n in zip(old, new):
            assert o["cidr"] == n["cidr"], "对齐错位(不应发生)"
            if o["source"] == "apnic" and n["source"] == "bgp":
                r["src_apnic_to_bgp"] += 1
            elif o["source"] == "bgp" and n["source"] == "apnic":
                r["src_bgp_to_apnic"] += 1
            oc, nc = o["confidence"], n["confidence"]
            if oc == "high" and nc == "medium":
                r["conf_high_to_medium"] += 1
            elif oc == "high" and nc == "low":
                r["conf_high_to_low"] += 1
            elif oc == "high" and nc == "high":
                r["conf_unchanged_high"] += 1

        for k in grand:
            grand[k] += r[k]

        print(f"\n[{cc}] 共 {r['total']} 段")
        print(f"   source  apnic→bgp : {r['src_apnic_to_bgp']:5}   "
              f"(原误标为 apnic、实为 BGP 补充的段)")
        if r["src_bgp_to_apnic"]:
            print(f"   ⚠ source bgp→apnic : {r['src_bgp_to_apnic']:5}   "
                  f"(新逻辑反而收回认领,需人工核查!)")
        print(f"   conf    high→medium: {r['conf_high_to_medium']:5}   (L1 段降级)")
        print(f"   conf    high→low   : {r['conf_high_to_low']:5}   (L2 弱信号段降级)")

    print("\n" + "-" * 64)
    print("  全区汇总")
    print("-" * 64)
    print(f"  source apnic→bgp  : {grand['src_apnic_to_bgp']:6}  ← bug 真实污染规模(下限)")
    print(f"  source bgp→apnic  : {grand['src_bgp_to_apnic']:6}  ← 应为 0;非 0 需核查新逻辑")
    print(f"  conf high→medium  : {grand['conf_high_to_medium']:6}")
    print(f"  conf high→low     : {grand['conf_high_to_low']:6}  ← 这些段你过去把猜测当权威信了")
    print(f"  conf 仍 high       : {grand['conf_unchanged_high']:6}")
    print("\n  解读:")
    print("   • apnic→bgp 数 = 修法纠正的来源误标量。相对总段数越小,合入越安全。")
    print("   • high→low  数 = 你过去标成『高可信』、实则 L2 猜测的段。这是修法最大价值。")
    print("   • bgp→apnic 必须为 0;若非 0,先别合,把那几段贴给 Claude 一起查。")
    print("=" * 64 + "\n")


def main():
    ap = argparse.ArgumentParser(description="IPNova provenance 修法 dry-run(只读)")
    # 透传主程序常用 flag;其余用默认
    known, passthru = ap.parse_known_args()
    # 默认走完整构建;把未知参数原样传给主程序的 parser
    argv = passthru
    try:
        final_nets, prov = run_real_build(argv)
    except Exception as e:
        print(f"\n[dry-run] 构建过程出错: {e}", file=sys.stderr)
        print("[dry-run] 这通常是网络/RIPEstat 限流问题;稍后重试或检查连通性。",
              file=sys.stderr)
        sys.exit(1)
    compare(final_nets, prov)
    print("[dry-run] 完成。未写入或修改任何 output 文件。")


if __name__ == "__main__":
    main()
