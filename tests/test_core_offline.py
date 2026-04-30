#!/usr/bin/env python3
"""Lightweight offline checks for core IPNova transformations."""

import importlib.util
import ipaddress
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("generate_ip_list", ROOT / "generate_ip_list.py")
generate_ip_list = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_ip_list)


def test_parse_normalize_and_write_outputs():
    raw_data = "\n".join([
        "2|apnic|20260429|1|1|summary",
        "apnic|CN|ipv4|1.0.1.0|256|20200101|allocated",
        "apnic|HK|ipv4|1.0.2.0|256|20200101|assigned",
        "apnic|JP|ipv4|1.0.3.0|256|20200101|allocated",
        "apnic|US|ipv4|8.8.8.0|256|20200101|allocated",
        "apnic|CN|ipv4|1.1.1.0|256|20200101|allocated",
    ])
    excluded = [ipaddress.ip_network("1.1.1.0/24")]

    region_data, parse_stats = generate_ip_list.parse_and_cleanse(raw_data, excluded)
    normalized = generate_ip_list.normalize_region_data(region_data)

    assert normalized["CN"]["cidrs"] == ["1.0.1.0/24"]
    assert normalized["HK"]["cidrs"] == ["1.0.2.0/24"]
    assert normalized["JP"]["cidrs"] == ["1.0.3.0/24"]
    assert normalized["SG"]["cidrs"] == []
    assert parse_stats["excluded_source_networks"] == 1

    with tempfile.TemporaryDirectory() as tmpdir:
        asn_report = {
            "mode": "static_only",
            "succeeded": [],
            "failed": [],
            "total_prefixes": 0,
        }
        generate_ip_list.save_txt_outputs(normalized, tmpdir)
        generate_ip_list.save_json_outputs(normalized, asn_report, parse_stats, tmpdir)

        data = json.loads((Path(tmpdir) / "data.json").read_text())
        meta = json.loads((Path(tmpdir) / "meta.json").read_text())
        assert data["schema_version"] == "3.1"
        assert meta["checksum"]["data_json_sha256"]
        assert "Japan" in (Path(tmpdir) / "JP.txt").read_text()


if __name__ == "__main__":
    test_parse_normalize_and_write_outputs()
    print("offline tests passed")
