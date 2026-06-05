#!/usr/bin/env python3
"""
build_formats.py — IPNova extended format generator

Generates additional output formats from ipnova's data.json:

  MMDB:
    - ipnova-apac.mmdb          : Primary branded MMDB
    - GeoIP2-Country-compatible.mmdb   : MaxMind GeoIP2 schema-compatible
    - GeoLite2-Country-compatible.mmdb : MaxMind GeoLite2 schema-compatible

  JSON:
    - regions.json              : All regions combined
    - json/{CC}.json            : Per-region individual JSON

  Plain CIDR (no headers, for programmatic use):
    - plain/{CC}.txt            : Pure CIDR list, no comments

  Nginx:
    - nginx/{CC}.conf           : Nginx geo module format

  HAProxy:
    - haproxy/{CC}.acl          : HAProxy ACL format

  Caddy:
    - caddy/{CC}.conf           : Caddy remote_ip matcher format

  iptables:
    - iptables/{CC}.ipset       : iptables ipset restore format

  Terraform:
    - terraform/{CC}.auto.tfvars.json : Terraform-compatible variable files

  Checksums:
    - checksums.txt             : SHA-256 of all output files (human-readable)
    - SHA256SUMS                : SHA-256 of core release assets (--release-assets)

Usage:
    python3 scripts/build_formats.py [--output-dir output] [--skip-mmdb] [-v]

Run after generate_ip_list.py.
Requires for MMDB: pip install mmdb-writer netaddr maxminddb
"""

import argparse
import json
import logging
import os
import sys
import datetime
import tarfile
import hashlib

log = logging.getLogger("ipnova.formats")


# ================================================================
# Helpers
# ================================================================

def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )


def load_data_json(output_dir):
    path = os.path.join(output_dir, "data.json")
    if not os.path.exists(path):
        log.error("data.json not found at %s — run generate_ip_list.py first", path)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Fail loud rather than silently substituting a stale default: data.json
    # is the single source of truth for schema_version and version. If either
    # is missing the upstream generate_ip_list.py output is malformed, and
    # guessing a version here would propagate a wrong value into every
    # derived format. Surface it instead.
    for required in ("schema_version", "version"):
        if not data.get(required):
            log.error(
                "data.json at %s is missing required field '%s' — "
                "refusing to guess; regenerate it with generate_ip_list.py",
                path, required,
            )
            sys.exit(1)

    return data


def now_utc_str():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_output_files(output_dir):
    """Walk output_dir and return all non-hidden files, sorted."""
    result = []
    for root, dirs, files in os.walk(output_dir):
        dirs[:] = [d for d in sorted(dirs) if not d.startswith(".")]
        for fname in sorted(files):
            if fname.startswith("."):
                continue
            result.append(os.path.join(root, fname))
    return result


# ================================================================
# Format 1: MMDB + schema-compatible aliases
# ================================================================

def build_mmdb(data, output_dir):
    """
    Build ipnova-apac.mmdb via mmdb.builder, then write -compatible aliases
    as byte-identical copies. The aliases are *named differently* from
    MaxMind's own product files on purpose: 'GeoIP2-Country' and
    'GeoLite2-Country' are MaxMind trademarks, and shipping files with
    those exact names risks brand confusion and trademark issues. The
    `-compatible` suffix keeps the format interoperable while making clear
    this is an independent dataset, not a MaxMind product.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    try:
        from mmdb.builder import build
        from mmdb.validator import validate
    except ImportError as e:
        log.warning("mmdb module error: %s", e)
        return False

    try:
        out_path = build(data.get("regions", {}), output_dir)
        if not validate(out_path):
            raise RuntimeError("MMDB validation failed")
    except ImportError as e:
        log.warning("%s", e)
        log.warning("Skipping MMDB — install with: pip install mmdb-writer netaddr maxminddb")
        return False
    except RuntimeError as e:
        log.error("%s", e)
        return False

    # Schema-compatible aliases — same bytes, different (non-trademarked)
    # filenames. See docstring above.
    with open(out_path, "rb") as src:
        primary_data = src.read()
    for alias in ["GeoIP2-Country-compatible.mmdb", "GeoLite2-Country-compatible.mmdb"]:
        alias_path = os.path.join(output_dir, alias)
        with open(alias_path, "wb") as f:
            f.write(primary_data)
        log.info("  %s — schema-compatible alias", alias)

    return True


# ================================================================
# Format 2: Per-region JSON
# ================================================================

def build_json_per_region(data, output_dir):
    """Build per-region JSON files and a combined regions.json."""
    json_dir = os.path.join(output_dir, "json")
    os.makedirs(json_dir, exist_ok=True)

    regions = data.get("regions", {})
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    combined = {
        # schema_version & version are validated present in load_data_json,
        # so we inherit them faithfully here — no hardcoded fallback.
        "schema_version": data["schema_version"],
        "project": "ipnova",
        "version": data["version"],
        "generated_at": generated_at,
        "regions": {}
    }

    for cc, payload in regions.items():
        region_data = {
            "region": cc,
            "region_name": payload.get("region_name", cc),
            "total_cidrs": payload.get("total_cidrs", 0),
            "total_ips": payload.get("total_ips", 0),
            "generated_at": generated_at,
            "cidrs": payload.get("cidrs", []),
            # include cidr_objects so BGP provenance is available to
            # consumers of per-region files, not just data.json
            "cidr_objects": payload.get("cidr_objects", []),
        }
        out_path = os.path.join(json_dir, f"{cc}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(region_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        combined["regions"][cc] = region_data
        log.info("  json/%s.json — %d CIDRs", cc, payload.get("total_cidrs", 0))

    combined_path = os.path.join(output_dir, "regions.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info("  regions.json — all %d regions combined", len(regions))
    return True


# ================================================================
# Format 3: Plain CIDR (no headers)
# ================================================================

def build_plain(data, output_dir):
    """
    Build plain CIDR-only files with zero comment lines.
    Intended for tools that cannot strip comment headers.
    Output: output/plain/{CC}.txt
    """
    plain_dir = os.path.join(output_dir, "plain")
    os.makedirs(plain_dir, exist_ok=True)

    regions = data.get("regions", {})
    for cc, payload in regions.items():
        out_path = os.path.join(plain_dir, f"{cc}.txt")
        cidrs = payload.get("cidrs", [])
        with open(out_path, "w", encoding="utf-8") as f:
            for cidr in cidrs:
                f.write(f"{cidr}\n")
        log.info("  plain/%s.txt — %d CIDRs (no headers)", cc, len(cidrs))
    return True


# ================================================================
# Format 4: Nginx geo module
# ================================================================

def build_nginx(data, output_dir):
    """Build Nginx geo module format files."""
    nginx_dir = os.path.join(output_dir, "nginx")
    os.makedirs(nginx_dir, exist_ok=True)

    regions = data.get("regions", {})
    timestamp = now_utc_str()

    for cc, payload in regions.items():
        out_path = os.path.join(nginx_dir, f"{cc}.conf")
        cidrs = payload.get("cidrs", [])
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# IPNova — Nginx geo module — {cc} ({payload.get('region_name', cc)})\n")
            f.write(f"# Generated : {timestamp}\n")
            f.write(f"# CIDRs     : {len(cidrs)}\n")
            f.write("# Project   : https://github.com/harryheros/ipnova\n")
            f.write("# Note      : output includes a few RFC5737 documentation-reserved\n")
            f.write("#             CIDRs as provenance fingerprints; they never route on\n")
            f.write("#             the public Internet and are safe to ignore.\n")
            f.write("#\n")
            f.write("# Usage in nginx.conf:\n")
            f.write("#   geo $ipnova_country {\n")
            f.write("#       default \"\";\n")
            f.write(f"#       include /path/to/ipnova/nginx/{cc}.conf;\n")
            f.write("#   }\n")
            f.write("#\n")
            for cidr in cidrs:
                f.write(f"{cidr} {cc};\n")
        log.info("  nginx/%s.conf — %d CIDRs", cc, len(cidrs))
    return True


# ================================================================
# Format 5: HAProxy ACL
# ================================================================

def build_haproxy(data, output_dir):
    """
    Build HAProxy ACL files.
    Output: output/haproxy/{CC}.acl

    Usage in haproxy.cfg:
        acl is_CN src -f /path/to/ipnova/haproxy/CN.acl
        use_backend cn_backend if is_CN
    """
    haproxy_dir = os.path.join(output_dir, "haproxy")
    os.makedirs(haproxy_dir, exist_ok=True)

    regions = data.get("regions", {})
    timestamp = now_utc_str()

    for cc, payload in regions.items():
        out_path = os.path.join(haproxy_dir, f"{cc}.acl")
        cidrs = payload.get("cidrs", [])
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# IPNova — HAProxy ACL — {cc} ({payload.get('region_name', cc)})\n")
            f.write(f"# Generated : {timestamp}\n")
            f.write(f"# CIDRs     : {len(cidrs)}\n")
            f.write("# Project   : https://github.com/harryheros/ipnova\n")
            f.write("# Note      : output includes a few RFC5737 documentation-reserved\n")
            f.write("#             CIDRs as provenance fingerprints; they never route on\n")
            f.write("#             the public Internet and are safe to ignore.\n")
            f.write("#\n")
            f.write("# Usage in haproxy.cfg (frontend or backend section):\n")
            f.write(f"#   acl is_{cc} src -f /path/to/ipnova/haproxy/{cc}.acl\n")
            f.write(f"#   use_backend {cc.lower()}_backend if is_{cc}\n")
            f.write("#\n")
            for cidr in cidrs:
                f.write(f"{cidr}\n")
        log.info("  haproxy/%s.acl — %d CIDRs", cc, len(cidrs))
    return True


# ================================================================
# Format 6: Caddy remote_ip matcher
# ================================================================

def build_caddy(data, output_dir):
    """
    Build Caddy remote_ip matcher snippet files.
    Output: output/caddy/{CC}.conf

    Usage in Caddyfile:
        @ipnova_CN {
            import /path/to/ipnova/caddy/CN.conf
        }
        handle @ipnova_CN {
            # handle CN traffic
        }
    """
    caddy_dir = os.path.join(output_dir, "caddy")
    os.makedirs(caddy_dir, exist_ok=True)

    regions = data.get("regions", {})
    timestamp = now_utc_str()

    for cc, payload in regions.items():
        out_path = os.path.join(caddy_dir, f"{cc}.conf")
        cidrs = payload.get("cidrs", [])
        # Split into chunks of 500 to stay readable; Caddy has no hard limit
        # but very long lines hurt readability and some editors.
        chunk_size = 500
        chunks = [cidrs[i:i + chunk_size] for i in range(0, len(cidrs), chunk_size)]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# IPNova — Caddy remote_ip matcher — {cc} ({payload.get('region_name', cc)})\n")
            f.write(f"# Generated : {timestamp}\n")
            f.write(f"# CIDRs     : {len(cidrs)}\n")
            f.write("# Project   : https://github.com/harryheros/ipnova\n")
            f.write("# Note      : output includes a few RFC5737 documentation-reserved\n")
            f.write("#             CIDRs as provenance fingerprints; they never route on\n")
            f.write("#             the public Internet and are safe to ignore.\n")
            f.write("#\n")
            f.write("# Usage in Caddyfile:\n")
            f.write(f"#   @ipnova_{cc} {{\n")
            f.write(f"#       import /path/to/ipnova/caddy/{cc}.conf\n")
            f.write("#   }\n")
            f.write("#\n")
            for chunk in chunks:
                f.write("remote_ip " + " ".join(chunk) + "\n")
        log.info("  caddy/%s.conf — %d CIDRs (%d line(s))", cc, len(cidrs), len(chunks))
    return True


# ================================================================
# Format 7: iptables ipset
# ================================================================

def build_iptables(data, output_dir):
    """Build iptables ipset restore format files.

    The ipset `maxelem` parameter is sized dynamically to 2x the current
    CIDR count, rounded up to the next power of two, with a floor of
    65536 (legacy default). This keeps headroom for organic growth
    without silently truncating future additions once a region crosses
    the static cap.
    """
    ipt_dir = os.path.join(output_dir, "iptables")
    os.makedirs(ipt_dir, exist_ok=True)

    regions = data.get("regions", {})
    timestamp = now_utc_str()

    def _maxelem_for(n_cidrs):
        target = max(n_cidrs * 2, 65536)
        # Round up to next power of two for kernel-friendly sizing
        size = 1
        while size < target:
            size *= 2
        return size

    for cc, payload in regions.items():
        out_path = os.path.join(ipt_dir, f"{cc}.ipset")
        cidrs = payload.get("cidrs", [])
        maxelem = _maxelem_for(len(cidrs))
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# IPNova — ipset restore — {cc} ({payload.get('region_name', cc)})\n")
            f.write(f"# Generated : {timestamp}\n")
            f.write(f"# CIDRs     : {len(cidrs)}\n")
            f.write("# Project   : https://github.com/harryheros/ipnova\n")
            f.write("# Note      : output includes a few RFC5737 documentation-reserved\n")
            f.write("#             CIDRs as provenance fingerprints; they never route on\n")
            f.write("#             the public Internet and are safe to ignore.\n")
            f.write("#\n")
            f.write("# Usage:\n")
            f.write(f"#   ipset restore < {cc}.ipset\n")
            f.write(f"#   iptables -I FORWARD -m set --match-set ipnova_{cc} dst -j ACCEPT\n")
            f.write("#\n")
            f.write(f"create ipnova_{cc} hash:net family inet hashsize 4096 maxelem {maxelem}\n")
            for cidr in cidrs:
                f.write(f"add ipnova_{cc} {cidr}\n")
        log.info("  iptables/%s.ipset — %d CIDRs (maxelem=%d)", cc, len(cidrs), maxelem)
    return True


# ================================================================
# Format 8: Terraform auto.tfvars.json
# ================================================================

def build_terraform(data, output_dir):
    """
    Build Terraform-compatible variable files.
    Output: output/terraform/{CC}.auto.tfvars.json

    Recommended usage for large CIDR lists:
      - aws_wafv2_ip_set (up to 10,000 addresses)
      - aws_network_acl
      - google_compute_firewall (supports CIDR lists natively)

    Avoid aws_security_group_rule for_each on large lists:
    AWS SGs have a 60-rule limit per group.
    """
    tf_dir = os.path.join(output_dir, "terraform")
    os.makedirs(tf_dir, exist_ok=True)

    regions = data.get("regions", {})
    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for cc, payload in regions.items():
        out_path = os.path.join(tf_dir, f"{cc}.auto.tfvars.json")
        cidrs = payload.get("cidrs", [])
        var_name = f"ipnova_{cc.lower()}_cidrs"
        out_data = {
            "_ipnova_meta": {
                "region": cc,
                "region_name": payload.get("region_name", cc),
                "total_cidrs": len(cidrs),
                "generated_at": generated_at,
                "source": "https://github.com/harryheros/ipnova",
                "note": (
                    "AWS SG max 60 rules — use aws_network_acl or "
                    "aws_wafv2_ip_set for large lists."
                ),
            },
            var_name: cidrs,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        log.info("  terraform/%s.auto.tfvars.json — %d CIDRs", cc, len(cidrs))
    return True


# ================================================================
# Checksums: full output directory
# ================================================================

def build_checksums(output_dir):
    """
    Write checksums.txt covering every non-hidden file under output_dir.
    Paths are relative to output_dir for portability.
    """
    all_files = collect_output_files(output_dir)
    sums_path = os.path.join(output_dir, "checksums.txt")

    lines = [
        "# IPNova — SHA-256 checksums",
        f"# Generated : {now_utc_str()}",
        "# Format    : <sha256>  <relative-path>",
        "#",
    ]
    count = 0
    for fpath in all_files:
        if os.path.basename(fpath) in ("checksums.txt", "SHA256SUMS"):
            continue
        digest = sha256_file(fpath)
        rel = os.path.relpath(fpath, output_dir)
        lines.append(f"{digest}  {rel}")
        count += 1

    with open(sums_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    log.info("  checksums.txt — %d files checksummed", count)
    return sums_path


# ================================================================
# Packaging: release archive + SHA256SUMS
# ================================================================

def create_formats_archive(output_dir):
    """Bundle all compatibility formats into ipnova-formats.tar.gz."""
    archive_path = os.path.join(output_dir, "ipnova-formats.tar.gz")

    with tarfile.open(archive_path, "w:gz") as tar:
        for name in os.listdir(output_dir):
            if name.endswith(".txt") and not name.startswith("."):
                tar.add(os.path.join(output_dir, name), arcname=f"txt/{name}")
        for name in ["json", "nginx", "haproxy", "caddy", "iptables", "plain", "terraform"]:
            path = os.path.join(output_dir, name)
            if os.path.exists(path):
                tar.add(path, arcname=name)

    log.info("  ipnova-formats.tar.gz — bundled all compatibility formats")
    return archive_path


def create_sha256sums(output_dir, files):
    """Generate SHA256SUMS for core release assets."""
    sums_path = os.path.join(output_dir, "SHA256SUMS")

    with open(sums_path, "w", encoding="utf-8") as f:
        for file_path in files:
            if not os.path.exists(file_path):
                continue
            digest = sha256_file(file_path)
            f.write(f"{digest}  {os.path.basename(file_path)}\n")

    log.info("  SHA256SUMS — checksums for core release assets")
    return sums_path


# ================================================================
# CLI
# ================================================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog="build_formats",
        description="IPNova extended format generator — run after generate_ip_list.py",
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="output",
        help="Output directory (default: output, must contain data.json)",
    )
    parser.add_argument("--skip-mmdb",      action="store_true", help="Skip MMDB + aliases")
    parser.add_argument("--skip-json",      action="store_true", help="Skip per-region JSON")
    parser.add_argument("--skip-plain",     action="store_true", help="Skip plain CIDR files")
    parser.add_argument("--skip-nginx",     action="store_true", help="Skip Nginx format")
    parser.add_argument("--skip-haproxy",   action="store_true", help="Skip HAProxy format")
    parser.add_argument("--skip-caddy",     action="store_true", help="Skip Caddy format")
    parser.add_argument("--skip-iptables",  action="store_true", help="Skip iptables format")
    parser.add_argument("--skip-terraform", action="store_true", help="Skip Terraform format")
    parser.add_argument(
        "--release-assets",
        action="store_true",
        help="Also generate ipnova-formats.tar.gz and SHA256SUMS for core assets",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    return parser


# ================================================================
# Main
# ================================================================

def main():
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    log.info("=" * 60)
    # Read version from generate_ip_list at runtime so the banner cannot
    # drift from the project's single version source.
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from generate_ip_list import __version__ as _ipnova_version
    log.info("  ipnova build_formats v%s — extended output generator", _ipnova_version)
    log.info("=" * 60)

    data = load_data_json(args.output_dir)
    regions = data.get("regions", {})
    log.info("Loaded data.json — %d regions", len(regions))
    log.info("")

    results = {}

    if not args.skip_mmdb:
        log.info("--- MMDB (+ schema-compatible aliases) ---")
        results["mmdb"] = build_mmdb(data, args.output_dir)
        log.info("")

    if not args.skip_json:
        log.info("--- JSON per region ---")
        results["json"] = build_json_per_region(data, args.output_dir)
        log.info("")

    if not args.skip_plain:
        log.info("--- Plain CIDR (no headers) ---")
        results["plain"] = build_plain(data, args.output_dir)
        log.info("")

    if not args.skip_nginx:
        log.info("--- Nginx geo module ---")
        results["nginx"] = build_nginx(data, args.output_dir)
        log.info("")

    if not args.skip_haproxy:
        log.info("--- HAProxy ACL ---")
        results["haproxy"] = build_haproxy(data, args.output_dir)
        log.info("")

    if not args.skip_caddy:
        log.info("--- Caddy remote_ip matcher ---")
        results["caddy"] = build_caddy(data, args.output_dir)
        log.info("")

    if not args.skip_iptables:
        log.info("--- iptables ipset ---")
        results["iptables"] = build_iptables(data, args.output_dir)
        log.info("")

    if not args.skip_terraform:
        log.info("--- Terraform auto.tfvars.json ---")
        results["terraform"] = build_terraform(data, args.output_dir)
        log.info("")

    log.info("--- Checksums (all output files) ---")
    build_checksums(args.output_dir)
    log.info("")

    if args.release_assets:
        log.info("--- Release assets ---")
        archive_path = create_formats_archive(args.output_dir)
        core_files = [
            os.path.join(args.output_dir, "ipnova-apac.mmdb"),
            os.path.join(args.output_dir, "GeoIP2-Country-compatible.mmdb"),
            os.path.join(args.output_dir, "GeoLite2-Country-compatible.mmdb"),
            os.path.join(args.output_dir, "regions.json"),
            os.path.join(args.output_dir, "meta.json"),
            archive_path,
        ]
        create_sha256sums(args.output_dir, core_files)
        results["release_assets"] = True
        log.info("")

    log.info("Done. Output summary:")
    summary = [
        ("mmdb",      "output/ipnova-apac.mmdb + GeoIP2-Country-compatible.mmdb + GeoLite2-Country-compatible.mmdb"),
        ("json",      "output/regions.json + output/json/{CC}.json"),
        ("plain",     "output/plain/{CC}.txt"),
        ("nginx",     "output/nginx/{CC}.conf"),
        ("haproxy",   "output/haproxy/{CC}.acl"),
        ("caddy",     "output/caddy/{CC}.conf"),
        ("iptables",  "output/iptables/{CC}.ipset"),
        ("terraform", "output/terraform/{CC}.auto.tfvars.json"),
    ]
    for key, desc in summary:
        if results.get(key):
            log.info("  %-12s %s", key + ":", desc)
    log.info("  %-12s %s", "checksums:", "output/checksums.txt")
    if results.get("release_assets"):
        log.info("  %-12s %s", "release:", "output/ipnova-formats.tar.gz + SHA256SUMS")


if __name__ == "__main__":
    main()
