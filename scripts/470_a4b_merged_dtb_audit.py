#!/usr/bin/env python3
"""P470-A4b: classify IPA nodes in BASE, real DTBO #1, MERGED, live FDT.

No fabricated overlay, no DT writes, and no duplication of PAS15 owner.
The merge is done by fdtoverlay, not by concatenating source properties.
The actual flashed DTBO partition must be supplied explicitly. If absent,
record NO_MERGED_PROOF and fail closed. A live FDT supersedes a simulated
bootloader merge for device observations, but never proves a different
boot image was flashed.
"""
import argparse
import hashlib
import json
import runpy
import subprocess
import tempfile
from pathlib import Path

BASE = runpy.run_path("scripts/461_dtbo_live_audit.py")
AUDIT = runpy.run_path("scripts/470_a4_dtb_audit.py")
fdt = BASE["fdt"]
dtbo_images = BASE["dtbo_images"]
extract_boot = BASE["extract_boot"]
audit = AUDIT["audit"]

COMPAT = {
    "ipa": ("qcom,ipa",),
    "pas15": ("qcom,pil-tz-generic",),
    "ap_cb": ("qcom,ipa-smmu-ap-cb",),
    "wlan_cb": ("qcom,ipa-smmu-wlan-cb",),
    "uc_cb": ("qcom,ipa-smmu-uc-cb",),
    "rmnet": ("qcom,rmnet-ipa3",),
    "gsi": ("qcom,msm_gsi",),
    "ipa_in": ("qcom,smp2p-map-ipa-1-in",),
    "ipa_out": ("qcom,smp2p-map-ipa-1-out",),
}


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def strings(blob):
    if blob is None:
        return []
    return [x.decode("utf-8", "replace") for x in blob.rstrip(b"\0").split(b"\0")]


def status(props):
    s = strings(props.get("status", b""))
    return s[0] if s else "okay (implicit)"


def effective_active(props):
    return status(props) in ("okay", "ok", "okay (implicit)")


def describe(tree):
    out = {}
    for name, compatibles in COMPAT.items():
        found = []
        for path, props in tree.items():
            cs = strings(props.get("compatible", b""))
            if not any(c in cs for c in compatibles):
                continue
            if name == "pas15":
                pas = props.get("qcom,pas-id")
                if pas != b"\x00\x00\x00\x0f":
                    continue
            found.append({"path": path, "status": status(props),
                          "compatible": cs,
                          "active": effective_active(props)})
        out[name] = sorted(found, key=lambda x: x["path"])
    return out


def classify(base, merged, live):
    names = {}
    for name in COMPAT:
        b = base[name]
        m = merged[name] if merged is not None else None
        l = live[name] if live is not None else None
        if m is None:
            label = "NO_MERGED_PROOF"
        elif len(m) != 1 and name not in ("gsi",):
            label = "MISSING" if not m else "DUPLICATE"
        elif len(m) == 0:
            label = "MISSING"
        elif not m[0]["active"]:
            label = "DISABLED_IN_MERGED"
        elif not b:
            label = "OVERLAY_ADDED"
        elif b[0]["path"] != m[0]["path"]:
            label = "OVERLAY_PATH_CHANGED"
        elif b[0]["active"]:
            label = "PRESENT_ACTIVE_IN_BASE_AND_MERGED"
        else:
            label = "OVERLAY_ENABLED_EXISTING"
        names[name] = {
            "base": b,
            "merged": m,
            "live": l,
            "classification": label,
            "live_consistent_with_merge": (
                sorted((x["path"], x["status"]) for x in l) ==
                sorted((x["path"], x["status"]) for x in m)
                if l is not None and m is not None else None),
        }
    return names


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--boot", type=Path, help="EXACT final packaged boot.img")
    p.add_argument("--base-dtb", type=Path,
                   help="Staged DTB only, diagnostic; not flash-proof")
    p.add_argument("--dtbo", type=Path,
                   help="Read-only dump of actual /dev/block/by-name/dtbo")
    p.add_argument("--dtbo-index", type=int, default=1)
    p.add_argument("--live-fdt", type=Path,
                   help="Optional phone /sys/firmware/fdt dump")
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--merged-out", type=Path)
    p.add_argument("--enforce", action="store_true")
    a = p.parse_args()
    if bool(a.boot) == bool(a.base_dtb):
        p.error("exactly one of --boot or --base-dtb required")
    if a.dtbo_index != 1:
        p.error("P470-A4b only validated for the phone's DTBO idx 1")
    base_blob, src = (extract_boot(a.boot.read_bytes())[0], "exact_final_boot")
                     if a.boot else (a.base_dtb.read_bytes(), "staged_only")
    base = describe(fdt(base_blob))
    merged_blob = None
    entry = None
    causes = []
    if a.dtbo:
        raw = a.dtbo.read_bytes()
        overlays = list(dtbo_images(raw))
        matching = [(meta, blob) for idx, meta, blob in overlays if idx == 1]
        if len(matching) != 1:
            raise RuntimeError("DTBO idx1 unavailable or duplicated")
        entry, overlay = matching[0]
        entry = {**entry, "partition_sha256": sha(raw),
                 "entry_sha256": sha(overlay)}
        with tempfile.TemporaryDirectory() as temp:
            d = Path(temp)
            bd = d / "base.dtb"
            od = d / "dtbo1.dtb"
            md = d / "merged.dtb"
            bd.write_bytes(base_blob)
            od.write_bytes(overlay)
            cmd = subprocess.run(["fdtoverlay", "-i", str(bd), "-o",
                                  str(md), str(od)], capture_output=True,
                                 text=True, check=False)
            if cmd.returncode or not md.is_file():
                causes.append("DTBO_INDEX1_FDTOVERLAY_FAILED:" + cmd.stderr[-320:])
            else:
                merged_blob = md.read_bytes()
    else:
        causes.append("ACTUAL_FLASHED_DTBO_PARTITION_NOT_SUPPLIED")
    live_blob = a.live_fdt.read_bytes() if a.live_fdt else None
    base_tree = fdt(base_blob)
    merged_tree = fdt(merged_blob) if merged_blob else None
    live_tree = fdt(live_blob) if live_blob else None
    classes = classify(base, describe(merged_tree) if merged_tree else None,
                       describe(live_tree) if live_tree else None)
    if src != "exact_final_boot":
        causes.append("STAGED_DTB_NOT_FINAL_PACKED_BOOT")
    if merged_tree is None:
        causes.append("NO_RECONSTRUCTED_MERGED_FDT")
    if live_tree is None:
        causes.append("COLLECTOR_LIVE_FDT_NOT_SUPPLIED")
    active = (describe(merged_tree) if merged_tree is not None else None)
    if active:
        for name in ("ipa", "pas15", "ap_cb", "wlan_cb",
                     "uc_cb", "rmnet", "ipa_in", "ipa_out"):
            if len(active[name]) != 1 or not active[name][0]["active"]:
                causes.append("MERGED_NODE_NOT_UNIQUE_ACTIVE:" + name)
        for name in ("gsi",):
            if len(active[name]) != 1 or not active[name][0]["active"]:
                causes.append("MERGED_GSI_PROVIDER_NOT_UNIQUE_ACTIVE")
        pas_nodes = []
        for path, props in merged_tree.items():
            if props.get("qcom,pas-id") == b"\x00\x00\x00\x0f":
                pas_nodes.append(path)
        if len(pas_nodes) != 1 or pas_nodes[0] != active["pas15"][0]["path"]:
            causes.append("PAS15_AUTHENTICATION_OWNER_DUPLICATED_OR_MISMATCHED")
    old_audit = None
    if merged_blob:
        with tempfile.TemporaryDirectory() as temp:
            merged = Path(temp) / "merged.dtb"
            merged.write_bytes(merged_blob)
            old_audit = audit(merged)
        # This original A4 audit runs *on the actual reconstructed tree*.
        causes += ["STATIC_ABI:" + x for x in old_audit["blockers"]]
    if live_tree is not None and merged_tree is not None:
        if any(x["live_consistent_with_merge"] is False
               for x in classes.values()):
            causes.append("LIVE_FDT_DIFFERS_FROM_DTBO1_MERGE_BOOTLOADER_FIXUPS_OR_WRONG_INPUT")
    result = {
        "phase": "P470-A4b-FDT-PROVENANCE",
        "base_source": src,
        "base_sha256": sha(base_blob),
        "dtbo_idx": 1,
        "dtbo_partition_proven": bool(a.dtbo),
        "dtbo_idx1": entry,
        "merged_sha256": sha(merged_blob) if merged_blob else None,
        "live_sha256": sha(live_blob) if live_blob else None,
        "node_classification": classes,
        "merged_static_abi": old_audit,
        "blockers": sorted(set(causes)),
        "status": "MERGED_STATIC_PASS_RUNTIME_PENDING" if not causes
                  else "BLOCKED_NOT_FLASHABLE",
        "flashable": False,
    }
    if a.merged_out and merged_blob:
        a.merged_out.parent.mkdir(parents=True, exist_ok=True)
        a.merged_out.write_bytes(merged_blob)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"P470-A4b MERGED DT audit status={result['status']}"
          f" blockers={len(result['blockers'])}")
    for k in result["blockers"]:
        print("P470-A4b DT BLOCKER:", k)
    for name, info in classes.items():
        print(f"P470-A4b DT {name}: {info['classification']},"
              f" base={len(info['base'])},"
              f" merged={None if info['merged'] is None else len(info['merged'])}")
    if a.enforce and causes:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
