#!/usr/bin/env python3
"""P461 final-output ECC48 gate: audit exact Android boot-v2 DTB bytes.

Check the LAST image that the workflow publishes, not an intermediate
ramoops DTB. Disallow silent P453 ECC16 fallback, inert reservation and
multiple ramoops nodes. Preserve image SHA and extracted DTB in artifacts.
"""
import argparse
import hashlib
import json
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
parser = runpy.run_path("scripts/38_repack_a52_p1_boot.py")["parse_boot"]
ramoops = runpy.run_path("scripts/458_pstore_ecc48_dtb.py")["inspect"]

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def verify(image_path):
    image = image_path.read_bytes()
    if len(image) != 96 * 1024 * 1024 or image[:8] != b"ANDROID!":
        raise RuntimeError("P461 unexpected final Android boot image")
    data = parser(image)
    if data["header_version"] != 2:
        raise RuntimeError("P461 requires boot v2")
    dtb = data["dtb"]
    if not dtb or dtb[:4] != b"\xd0\x0d\xfe\xed":
        raise RuntimeError("P461 final image has no single valid FDT")
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "dtb"
        path.write_bytes(dtb)
        info = ramoops(path, patched=True)
    if info["ecc_size"] != [48] or info["duplicate"] or info["primary"] is None:
        raise RuntimeError("P461 FINAL ECC48/no-duplicate invariant violated")
    if info["reg"] != [0,0xb1b00000,0,0x100000]:
        raise RuntimeError("P461 final reserve address/size drift")
    return image, dtb, info

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boot", type=Path, required=True)
    p.add_argument("--dtb-out", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--expect-boot-sha", default=None)
    a = p.parse_args()
    image, dtb, info = verify(a.boot)
    if a.expect_boot_sha and sha256(image) != a.expect_boot_sha:
        raise RuntimeError("P461 final image SHA differs from expected artifact")
    a.dtb_out.parent.mkdir(parents=True, exist_ok=True)
    a.dtb_out.write_bytes(dtb)
    # Re-read the saved DTB and verify artifact identity byte-for-byte.
    if a.dtb_out.read_bytes() != dtb:
        raise RuntimeError("P461 DTB artifact writeback mismatch")
    report = {
        "marker": "P461 FINAL BOOT DTB ECC48 PASS",
        "checked_image": str(a.boot),
        "boot_sha256": sha256(image),
        "boot_size": len(image),
        "final_dtb_sha256": sha256(dtb),
        "final_dtb_size": len(dtb),
        "exported_dtb": str(a.dtb_out),
        "ramoops": info,
        "runtime_pstore_registered": "NOT VERIFIED: must check pstore: Registered ramoops"
    }
    a.report.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
    print("P461 FINAL BOOT DTB ECC48 PASS", report["boot_sha256"], report["final_dtb_sha256"])
if __name__ == "__main__":
    main()
