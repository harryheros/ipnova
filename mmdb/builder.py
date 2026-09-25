"""
mmdb/builder.py — IPNova MMDB builder

Reads normalized region data and writes a MaxMind-compatible
MMDB database to the specified output path.

Requires: pip install mmdb-writer netaddr maxminddb
"""

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
        ImportError: if mmdb-writer or netaddr is not installed.
    """
    try:
        from mmdb_writer import MMDBWriter
        from netaddr import IPSet
    except ImportError as e:
        raise ImportError(
            "Required packages not installed.\n"
            "Install with: pip install mmdb-writer netaddr maxminddb"
        ) from e

    from mmdb.schema import (
        APAC_REGIONS, DATABASE_TYPE, DATABASE_DESCRIPTION, DATABASE_LANGUAGES,
        make_record,
    )

    writer = MMDBWriter(
        ip_version=4,
        database_type=DATABASE_TYPE,
        languages=DATABASE_LANGUAGES,
        description=DATABASE_DESCRIPTION,
    )

    total_inserted = 0
    failed = []

    # Deterministic insertion order (TARGET_REGIONS order, then any extras).
    order = [cc for cc in APAC_REGIONS if cc in normalized_data]
    order += sorted(cc for cc in normalized_data if cc not in APAC_REGIONS)

    for cc in order:
        payload = normalized_data[cc]
        cidrs = payload.get("cidrs", [])
        if not cidrs:
            log.warning("  %s: no CIDRs, skipping", cc)
            continue

        record = make_record(cc)

        try:
            writer.insert_network(IPSet(cidrs), record)
            total_inserted += len(cidrs)
            log.info(
                "  %s (%s): %d CIDRs inserted",
                cc, payload.get("region_name", cc), len(cidrs)
            )
        except Exception as e:
            log.error("  %s: insert failed — %s", cc, e)
            failed.append(cc)

    # A partially written MMDB (one region silently missing) is worse than
    # no MMDB: consumers would treat that region's IPs as "not APAC".
    if failed:
        raise RuntimeError(
            f"MMDB build failed: insert errors for region(s) {failed}. "
            "Check mmdb-writer and netaddr versions."
        )

    if total_inserted == 0:
        raise RuntimeError(
            "MMDB build failed: 0 CIDRs inserted. "
            "Check mmdb-writer and netaddr versions."
        )

    out_path = os.path.join(output_dir, "ipnova-apac.mmdb")
    os.makedirs(output_dir, exist_ok=True)
    # Write to a temp name first so a failed write never replaces the
    # previously published database with a truncated file.
    tmp_path = out_path + ".tmp"
    try:
        writer.to_db_file(tmp_path)
        os.replace(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    size_kb = os.path.getsize(out_path) // 1024
    log.info(
        "  ipnova-apac.mmdb — %d CIDRs, %d regions, %d KB",
        total_inserted, len(normalized_data), size_kb
    )

    return out_path
