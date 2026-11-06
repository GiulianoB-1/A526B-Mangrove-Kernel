#!/usr/bin/env python3
"""P474: create a boot-v2 HLT peer by removing only the 'nohlt' token."""
import argparse
import gzip
import hashlib
import json
import re
import runpy
from pathlib import Path

BOOT = runpy.run_path("scripts/38_repack_a52_p1_boot.py")
parse_boot = BOOT["parse_boot"]
sha256 = lambda b: hashlib.sha256(b).hexdigest()

def remove_nohlt(cmdline: str) -> str:
    hits = [m for m in re.finditer(r"\S+", cmdline) if m.group() == "nohlt"]
    if len(hits) != 1:
        raise ValueError(f"P474 expected exactly one standalone nohlt, found {len(hits)}")
    m = hits[0]
    start, end = m.span()
    # Delete the token plus exactly one adjoining space, preserving all
    # remaining characters and their order. Never add an 'hlt' parameter.
    if end < len(cmdline) and cmdline[end] == " ":
        end += 1
    elif start and cmdline[start - 1] == " ":
        start -= 1
    result = cmdline[:start] + cmdline[end:]
    if [t for t in cmdline.split() if t != "nohlt"] != result.split():
        raise ValueError("P474 changed a boot argument other than nohlt")
    return result

def create_peer(normal_bytes: bytes) -> tuple[bytes, dict]:
    normal = parse_boot(normal_bytes)
    if normal["header_version"] != 2:
        raise ValueError("P474 requires Samsung Android boot-v2")
    before = normal["cmdline"]
    after = remove_nohlt(before)
    raw = after.encode("ascii")
    if len(raw) > 1535:
        raise ValueError("P474 HLT cmdline exceeds boot-v2 capacity")
    hlt = bytearray(normal_bytes)
    hlt[64:576] = raw[:512].ljust(512, b"\0")
    hlt[608:1632] = raw[512:].ljust(1024, b"\0")
    hlt_bytes = bytes(hlt)
    check = parse_boot(hlt_bytes)
    # Prove that the boot images differ nowhere except the two v2 cmdline fields.
    def outside_cmdline(buf):
        return buf[:64] + buf[576:608] + buf[1632:]
    validations = {
        "exact_cmdline_only_change": outside_cmdline(normal_bytes) == outside_cmdline(hlt_bytes),
        "normal_has_exactly_one_nohlt": before.split().count("nohlt") == 1,
        "hlt_has_zero_nohlt": check["cmdline"].split().count("nohlt") == 0,
        "hlt_cmdline_exact_removal": check["cmdline"] == after,
        "tokens_identical_except_nohlt": check["cmdline"].split() == [
            t for t in before.split() if t != "nohlt"],
        "same_kernel": normal["kernel"] == check["kernel"],
        "same_ramdisk": normal["ramdisk"] == check["ramdisk"],
        "same_dtb": normal["dtb"] == check["dtb"],
        "same_second": normal["second"] == check["second"],
        "same_recovery_dtbo": normal["recovery_dtbo"] == check["recovery_dtbo"],
        "same_boot_id": normal["id"] == check["id"],
        "same_partition_bytes": len(normal_bytes) == len(hlt_bytes),
        "same_header_kernel_addresses": all(
            normal[k] == check[k] for k in (
                "header_version", "page_size", "kernel_addr", "ramdisk_addr",
                "tags_addr", "dtb_addr", "board", "kernel_size", "os_version"
            )),
    }
    failed = [k for k, ok in validations.items() if not ok]
    if failed:
        raise ValueError("P474 invariants failed: " + ", ".join(failed))
    return hlt_bytes, {
        "phase": "P474",
        "status": "CMDLINE_ONLY_PEER_VERIFIED",
        "no_arm": True,
        "boot_v2_cmdline_source": "boot header fields 64:576 and 608:1632",
        "normal_cmdline": before,
        "hlt_cmdline": after,
        "normal_nohlt": 1,
        "hlt_nohlt": 0,
        "kernel_sha256": sha256(normal["kernel"]),
        "ramdisk_sha256": sha256(normal["ramdisk"]),
        "dtb_sha256": sha256(normal["dtb"]),
        "boot_id_sha256": sha256(normal["id"]),
        "invariants": validations,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--normal", type=Path, required=True)
    p.add_argument("--hlt", type=Path, required=True)
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    original = args.normal.read_bytes()
    out, report = create_peer(original)
    actual_image = gzip.decompress(parse_boot(out)["kernel"])
    if actual_image != args.image.read_bytes():
        raise SystemExit("P474 HLT kernel differs from the native Image")
    report["native_image_sha256"] = sha256(actual_image)
    report["normal_boot_sha256"] = sha256(original)
    report["hlt_boot_sha256"] = sha256(out)
    args.hlt.parent.mkdir(parents=True, exist_ok=True)
    args.hlt.write_bytes(out)
    if args.hlt.read_bytes() != out:
        raise SystemExit("P474 output write did not roundtrip")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("P474 CMDLINE normal nohlt=1 HLT nohlt=0: ONLY cmdline bytes differ; native Image identical; NO ARM")

if __name__ == "__main__":
    main()
