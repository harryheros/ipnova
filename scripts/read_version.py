#!/usr/bin/env python3
"""Read __version__ from generate_ip_list.py and write to GITHUB_OUTPUT."""
import re
import os
import sys

with open("generate_ip_list.py", encoding="utf-8") as f:
    content = f.read()

m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
version = m.group(1) if m else "0.0.0"

github_output = os.environ.get("GITHUB_OUTPUT")
if github_output:
    with open(github_output, "a") as out:
        out.write(f"version={version}\n")
        out.write(f"tag=v{version}\n")

print(f"version={version}")
print(f"tag=v{version}")
