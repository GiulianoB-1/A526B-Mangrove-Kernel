#!/usr/bin/env python3
"""WX-only packaging gate: prove a boot header token is already present, exactly once.

The SHA-pinned Phase446WX boot template already has the source-level 446U/W/X
boot parameters. Never append a second copy. Never mutate any boot byte.
Original 446S packager remains untouched and still appends these parameters.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boot", required=True, type=Path)
    p.add_argument("--token", required=True)
    p.add_argument("--report", required=True, type=Path)
    args = p.parse_args()
    b = args.boot.read_bytes()
    if len(b) != 100663296 or b[:8] != b"ANDROID!" or struct.unpack_from("<I", b, 40)[0] != 2:
        raise SystemExit("WX boot token audit: not a 96 MiB Android boot v2")
    # Boot v2 primary cmdline may end at full 512 bytes in the middle of 'ramoops'.
    # Concatenate with extra_cmdline WITHOUT an inserted space.
    primary = b[64:576].split(b"\0", 1)[0]
    extra = b[608:1632].split(b"\0", 1)[0]
    words = (primary + extra).decode("ascii", "strict").split()
    if words.count(args.token) != 1:
        raise SystemExit(f"WX inherited boot token absent or duplicated: {args.token} count={words.count(args.token)}")
    # Mutually exclusive states are forbidden. Preserve every previously verified default.
    key = args.token.split("=",1)[0] + "="
    if sum(w.startswith(key) for w in words) != 1:
        raise SystemExit(f"WX inherited boot token conflicting value: {key}")
    required = ("a52.cb2_reuse=1", "no_console_suspend", "a52.usb_handover=1",
                "a52.446w_cold=0", "a52.446w_handoff=0", "a52.446w_tty=3", "a52.touch=1")
    for token in required:
        if words.count(token) != 1:
            raise SystemExit(f"WX boot mandatory token missing/duplicated: {token}")
    if "console=null" not in words:
        raise SystemExit("WX bootloader primary console must remain console=null")
    sha = hashlib.sha256(b).hexdigest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        "status": "verified-already-present-in-pinned-WX-boot",
        "token": args.token,
        "token_count": 1,
        "image_all_bytes_unchanged": True,
        "boot_id_unchanged": True,
        "original_cmdline": (primary + extra).decode("ascii", "strict"),
        "new_cmdline": (primary + extra).decode("ascii", "strict"),
        "source_sha256": sha,
        "output_sha256": sha,
        "bytes": len(b),
        "flash_authorized": False
    }, indent=2, sort_keys=True) + "\n")
    print(f"WX BOOT INHERITED TOKEN VERIFIED: {args.token} (no header mutation)")

if __name__ == "__main__":
    main()
