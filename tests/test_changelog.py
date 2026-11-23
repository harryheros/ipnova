#!/usr/bin/env python3
"""CHANGELOG.md: one dated heading per version, newest first, and facts that
match what each version shipped."""

import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
HEADING = re.compile(r"^## (\d+)\.(\d+)\.(\d+) \((\d{4}-\d{2}-\d{2})\)$")


def entries():
    text = CHANGELOG.read_text(encoding="utf-8")
    parts = re.split(r"^(?=## )", text, flags=re.M)[1:]
    return [(p.splitlines()[0], p) for p in parts]


def test_every_heading_is_a_dated_version():
    bad = [h for h, _ in entries() if not HEADING.match(h)]
    assert not bad, f"headings without `## X.Y.Z (YYYY-MM-DD)`: {bad}"


def test_newest_first():
    versions = [tuple(int(x) for x in HEADING.match(h).groups()[:3])
                for h, _ in entries() if HEADING.match(h)]
    assert versions == sorted(versions, reverse=True)


def test_321_lists_the_mmdb_names_it_shipped():
    """The `-compatible` names came in 3.3.0; 3.2.1 shipped the plain ones."""
    body = next(b for h, b in entries() if h.startswith("## 3.2.1 "))
    assert "-compatible.mmdb" not in body
