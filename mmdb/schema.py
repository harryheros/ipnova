"""
mmdb/schema.py — IPNova MMDB field schema definition

Defines the data structure written into ipnova-apac.mmdb.
Compatible with MaxMind GeoIP2 Country format.
"""

# Regions covered by IPNova
APAC_REGIONS = {
    "CN": "China (Mainland)",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "MO": "Macau",
    "JP": "Japan",
    "KR": "South Korea",
    "SG": "Singapore",
}

# Continent code for all APAC regions
CONTINENT_CODE = "AS"
CONTINENT_NAME = "Asia"

# MMDB database metadata
DATABASE_TYPE = "IPNOVA-GeoIP2-Country"
DATABASE_DESCRIPTION = {
    "en": (
        "IPNova Asia-Pacific IPv4 database — "
        "routing-aware CIDR intelligence for CN/HK/TW/MO/JP/KR/SG. "
        "Source: APNIC delegated + BGP multi-source fusion. "
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
