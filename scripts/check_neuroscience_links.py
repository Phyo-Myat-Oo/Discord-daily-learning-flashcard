#!/usr/bin/env python3
"""Check curated neuroscience companion links without making CI depend on them."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from cardlib import ROOT

CATALOG = ROOT / "config/neuroscience_online_resources.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    resources = json.loads(CATALOG.read_text(encoding="utf-8"))["resources"]
    failures = 0
    for resource_id, resource in resources.items():
        url = resource["url"]
        if not url.startswith("https://"):
            print(f"FAIL {resource_id}: non-HTTPS URL {url}")
            failures += 1
            continue
        request = urllib.request.Request(url, headers={"User-Agent": "daily-learning-link-check/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                print(f"OK   {resource_id}: HTTP {response.status} {response.geturl()}")
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                print(f"OK   {resource_id}: HTTP {exc.code} (reachable; automated checks blocked)")
                continue
            print(f"FAIL {resource_id}: {exc}")
            failures += 1
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"FAIL {resource_id}: {exc}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
