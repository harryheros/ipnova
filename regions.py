"""
regions.py — IPNova region constants (single source of truth).

This module exists to prevent definition drift between the build
pipeline (generate_ip_list.py) and downstream consumers (mmdb.schema,
validators, etc.). Anything that needs to know "what regions does IPNova
cover" must import from here, not redefine its own copy.

Kept dependency-free so it can be imported from anywhere in the project
without pulling in HTTP code, logging, or runtime state.
"""

import ipaddress

# Target regions, in canonical priority order.
# Order matters for enforce_mutual_exclusivity tie-breaking within the
# same authority tier (APNIC or BGP supplement).
TARGET_REGIONS = {
    "CN": "China (Mainland)",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "MO": "Macau",
    "JP": "Japan",
    "KR": "South Korea",
    "SG": "Singapore",
}

# ---------------------------------------------------------------------
# Canary CIDRs — provenance fingerprints
# ---------------------------------------------------------------------
# Each region carries a tiny, harmless CIDR injected from documentation-
# reserved space (RFC5737 TEST-NET-1/2/3). These ranges are never routed
# on the public Internet, so embedding them in a firewall/ipset/ACL is a
# no-op for downstream consumers — they cause zero false positives and
# zero traffic impact.
#
# Their purpose is forensic: if an unattributed third-party dataset is
# discovered to contain IPNova's exact canary set, that is strong evidence
# the dataset was derived from IPNova in violation of CC BY-NC-SA 4.0
# (which requires attribution and forbids commercial use without a
# separate written license).
#
# The mapping is documented here in the open precisely because hiding it
# is not the point — anyone who reads regions.py knows about it, but
# anyone who simply copies our output files and strips the comment
# headers will redistribute these CIDRs without realizing it.
#
# Note: enforce_mutual_exclusivity treats these as authoritative (Tier 1)
# so cloud-supplement traffic cannot accidentally claim them.
CANARY_CIDRS = {
    "CN": "192.0.2.240/29",     # RFC5737 TEST-NET-1 tail
    "HK": "192.0.2.248/29",     # RFC5737 TEST-NET-1 tail
    "TW": "198.51.100.240/29",  # RFC5737 TEST-NET-2 tail
    "MO": "198.51.100.248/29",  # RFC5737 TEST-NET-2 tail
    "JP": "203.0.113.224/29",   # RFC5737 TEST-NET-3 tail
    "KR": "203.0.113.232/29",   # RFC5737 TEST-NET-3 tail
    "SG": "203.0.113.240/29",   # RFC5737 TEST-NET-3 tail
}


def canary_networks():
    """Return canary CIDRs as a dict[cc, IPv4Network]. Cached implicitly
    by Python's int+str hashing — cheap to call repeatedly."""
    return {cc: ipaddress.ip_network(c, strict=False)
            for cc, c in CANARY_CIDRS.items()}
