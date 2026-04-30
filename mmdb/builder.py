"""
mmdb/builder.py — IPNova MMDB builder

Reads normalized region data and writes a MaxMind-compatible
MMDB database to the specified output path.

Requires: pip install mmdb-writer maxminddb
"""

import ipaddress
import logging
import os

log = logging.getLogger("ipnova.mmdb.builder")


def build(normalized_data: dict, output_dir: str = "output") -> str:
    """
    Build ipnova-apac.mmdb from normalized region data.

    Args:
        normalized_data: dict of {cc: {cidrs: [...], region_name: ..., ...}}
        output_dir: directory to write the MMDB file

    Returns:
        Path to the generated MMDB file.

    Raises:
        ImportError: if mmdb-writer is not installed.
    """
    try:
        from mmdb_writer import MMDBWriter
    except ImportError:
        raise ImportError(
            "mmdb-writer is not installed.\n"
            "Install with: pip install mmdb-writer maxminddb"
        )

    from mmdb.schema import (
        DATABASE_TYPE, DATABASE_DESCRIPTION, DATABASE_LANGUAGES, APAC_REGIONS
    )

    writer = MMDBWriter(
        ip_version=4,
        database_type=DATABASE_TYPE,
        languages=DATABASE_LANGUAGES,
        description=DATABASE_DESCRIPTION,
    )

    total_inserted = 0
    total_skipped = 0

    for cc, payload in normalized_data.items():
        cidrs = payload.get("cidrs", [])

        # 使用純 Python dict，與 mmdb-writer API 完全兼容
        record = {
            "country": cc,
            "country_name": APAC_REGIONS.get(cc, cc),
            "continent": "AS",
            "source": "ipnova",
        }

        for cidr in cidrs:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
                writer.insert_network(network, record)
                total_inserted += 1
            except ValueError as e:
                log.debug("Skipping invalid CIDR %s (%s): %s", cidr, cc, e)
                total_skipped += 1
            except Exception as e:
                log.debug("Insert error for %s (%s): %s", cidr, cc, e)
                total_skipped += 1

        log.info(
            "  %s (%s): %d CIDRs inserted",
            cc, payload.get("region_name", cc), len(cidrs)
        )

    out_path = os.path.join(output_dir, "ipnova-apac.mmdb")
    os.makedirs(output_dir, exist_ok=True)
    writer.to_db_file(out_path)

    size_kb = os.path.getsize(out_path) // 1024
    log.info(
        "  ipnova-apac.mmdb — %d CIDRs, %d regions, %d KB",
        total_inserted, len(normalized_data), size_kb
    )
    if total_skipped:
        log.warning("  %d CIDRs skipped", total_skipped)

    return out_path
