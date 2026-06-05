#!/usr/bin/env python3
"""
cache_probe.py — 探查 .geoloc_cache.json 的家底(纯离线,只读)

判断能否用现有缓存做离线 dry-run,不联网、不改任何文件。
用法:放在 ipnova 项目根目录,python3 cache_probe.py
"""
import json, os, sys, datetime

CACHE = os.path.join("output", ".geoloc_cache.json")
DATA  = os.path.join("output", "data.json")

if not os.path.exists(CACHE):
    print(f"❌ 找不到缓存文件 {CACHE}")
    print("   说明上次构建没留下缓存(或被清理)。离线 dry-run 不可行,")
    print("   只能等限流缓解后联网跑,或改抽样方案。")
    sys.exit(1)

raw = json.load(open(CACHE, encoding="utf-8"))
entries = raw.get("entries", raw)  # 兼容两种存法
print(f"✅ 缓存文件存在: {CACHE}")
print(f"   rule_version : {raw.get('rule_version', '(未知)')}")
print(f"   ttl_hours    : {raw.get('ttl_hours', '(未知)')}")
print(f"   缓存条目总数  : {len(entries)}")

# level 分布
from collections import Counter
levels = Counter(rec.get("level") for rec in entries.values())
print(f"   level 分布    : {dict(levels)}")

# 覆盖率:data.json 里 source=bgp 的段,有多少能在缓存里找到对应 level?
if os.path.exists(DATA):
    d = json.load(open(DATA, encoding="utf-8"))
    bgp_cidrs = []
    for cc, blk in d["regions"].items():
        for o in blk.get("cidr_objects", []):
            if o.get("source") == "bgp":
                bgp_cidrs.append(o["cidr"])
    hit = sum(1 for c in bgp_cidrs if c in entries)
    print(f"\n   data.json 中 bgp 段: {len(bgp_cidrs)}")
    print(f"   其中能在缓存命中 level 的: {hit}")
    if bgp_cidrs:
        print(f"   命中率: {hit/len(bgp_cidrs)*100:.1f}%")
    print("\n   注:命中率低属正常 —— 缓存 key 是 collapse 前的原始 prefix,")
    print("   data.json 的 bgp 段是 collapse 后的;离线 dry-run 会用【区间求交】")
    print("   而非字符串匹配来跨过这个差异,所以真实可用率比这个数字高。")

print("\n探查完成,未修改任何文件。把以上输出贴回给 Claude。")
