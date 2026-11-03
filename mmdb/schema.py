"""
mmdb/schema.py — IPNova MMDB field schema definition

Defines the data structure written into ipnova-apac.mmdb.
Compatible with MaxMind GeoIP2 Country format.
"""

import os
import sys

# Ensure project root is on sys.path so `import regions` resolves whether
# this module is imported from build_formats.py (cwd = project root) or
# directly via `python -m mmdb.schema` etc.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from regions import TARGET_REGIONS  # noqa: E402

# Regions covered by IPNova — alias kept for backward compatibility with
# code that imported APAC_REGIONS directly from this module.
APAC_REGIONS = TARGET_REGIONS

# Continent code for all APAC regions
CONTINENT_CODE = "AS"
CONTINENT_NAME = "Asia"

# MMDB database metadata.
#
# One file. GeoIP2 reader libraries check `database_type` before a Country
# lookup and refuse anything that is not exactly "GeoIP2-Country" or
# "GeoLite2-Country", so the file uses the latter (the type free/open-source
# tools expect). It is a technical identifier required for interoperability;
# the file name stays neutral and the description identifies the file as an
# independent IPNova build. Same choice as the global MMDB.
#
# v4.1 merged the former ipnova-apac-country.mmdb (same records) into this
# file; RETIRED_FILENAMES are removed from output/ on the next build.
DATABASE_TYPE = "GeoLite2-Country"
PRIMARY_FILENAME = "ipnova-apac.mmdb"
RETIRED_FILENAMES = ("ipnova-apac-country.mmdb",)

DATABASE_DESCRIPTION = {
    "en": (
        "IPNova Asia-Pacific IPv4 database — "
        "routing-aware CIDR intelligence for CN/HK/TW/MO/JP/KR/SG. "
        "Source: APNIC delegated + BGP multi-source fusion. "
        "Independent dataset in MaxMind DB format; not affiliated with or "
        "endorsed by MaxMind, Inc. and contains no MaxMind data. "
        "https://github.com/harryheros/ipnova"
    )
}
DATABASE_LANGUAGES = ["en"]


def make_record(iso_code: str) -> dict:
    """
    Build the MMDB record for a given ISO country code.
    Follows MaxMind GeoIP2 Country schema for broad compatibility.
    """
    return {
        "country": {
            "iso_code": iso_code,
            "names": {
                "en": APAC_REGIONS.get(iso_code, iso_code),
            },
        },
        "continent": {
            "code": CONTINENT_CODE,
            "names": {
                "en": CONTINENT_NAME,
            },
        },
        "source": "ipnova",
    }
