#!/usr/bin/env python3
"""Stamp exact GitHub run+commit into real A1 compiled APR probe log."""
import argparse
import os
import re
from pathlib import Path

FILE = Path("drivers/rpmsg/p472_apr_q6core.c")
OLD = 'P472 A1 BUILD run_id=UNSTAMPED sha=UNSTAMPED'

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--check-only", action="store_true")
    a = p.parse_args()
    rid = os.environ.get("GITHUB_RUN_ID", "")
    sha = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9]+", rid):
        raise SystemExit("P472 A1 missing real Actions run ID")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise SystemExit("P472 A1 missing real full commit SHA")
    stamp = "P472 A1 BUILD run_id=" + rid + " sha=" + sha.lower()
    src = a.root / FILE
    text = src.read_text()
    if not a.check_only:
        if text.count(OLD) != 1:
            raise RuntimeError("P472 A1 unique provenance placeholder missing")
        src.write_text(text.replace(OLD, stamp, 1))
        text = src.read_text()
    if text.count(stamp) != 1 or OLD in text:
        raise RuntimeError("P472 A1 final source provenance not unique")
    if 'dev_info(&rpdev->dev, P472_A1_PROVENANCE "\\n");' not in text:
        raise RuntimeError("P472 A1 runtime provenance log not linked to probe")
    print("P472 A1 provenance STAMP PASS " + stamp)

if __name__ == "__main__":
    main()
