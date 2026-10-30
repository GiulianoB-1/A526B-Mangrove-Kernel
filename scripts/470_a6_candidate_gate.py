#!/usr/bin/env python3
"""P470-A6 exact P469B-to-IPA native Image.gz first-boot review gate.

Checks the boot-v2 packer output is actually bootable-format and surgical.
Does not assert on-device IPA success: no phone has booted this Image yet.
"""
import argparse
import gzip
import hashlib
import json
import runpy
from pathlib import Path

B = runpy.run_path("scripts/38_repack_a52_p1_boot.py")
parse = B["parse_boot"]
sha = lambda data: hashlib.sha256(data).hexdigest()
MARKERS = (
    b"P470 IPA ARM initialized disarmed=1",
    b"P470 MSS IPA_WAIT disarmed=1 P469b_passthrough=1",
    b"P470 MSS WAIT_TIMEOUT modem_not_started",
    b"P470 MSS NOTIF event=",
    b"P470 IPA SMMU cb=",
    b"P470 IPA BUS register client=%u cases=5 paths=5",
    b"P470 IPA BUS vote case=%d rc=%d",
    b"P470 IPA BUS VOTE_FAILED",
    b"P470 IPA BUS cleanup MIN case=0 rc=%d",
    b"P470 IPA FW_LOAD",
    b"P470 IPA GSI READY",
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--system-map", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    oldraw, newraw = a.baseline.read_bytes(), a.candidate.read_bytes()
    base, new = parse(oldraw), parse(newraw)
    kernel = gzip.decompress(new["kernel"])
    native = a.image.read_bytes()
    checks = {
        "boot_v2": base["header_version"] == 2 == new["header_version"],
        "partition_length": len(oldraw) == len(newraw),
        "same_ramdisk": base["ramdisk"] == new["ramdisk"],
        "same_dtb": base["dtb"] == new["dtb"],
        "same_second": base["second"] == new["second"],
        "same_recovery_dtbo": base["recovery_dtbo"] == new["recovery_dtbo"],
        "same_cmdline": base["cmdline"] == new["cmdline"],
        "same_board": base["board"] == new["board"],
        "same_addresses": all(base[k] == new[k] for k in
                              ("kernel_addr", "ramdisk_addr", "tags_addr", "dtb_addr")),
        "new_native_image": kernel == native,
        "kernel_replaced": sha(base["kernel"]) != sha(new["kernel"]),
        "boot_id_changed": base["id"] != new["id"],
        "all_linked_runtime_markers": all(t in native for t in MARKERS),
    }
    cfg = a.config.read_text()
    syms = a.system_map.read_text()
    checks["real_bus_config_built_in"] = all(
        "CONFIG_" + k + "=y" in cfg.splitlines() for k in
        ("QCOM_BUS_SCALING", "QCOM_BUS_CONFIG_RPMH"))
    checks["real_bus_symbols_linked"] = all(
        any(line.endswith(" " + k) for line in syms.splitlines()) for k in
        ("msm_bus_cl_get_pdata", "msm_bus_scale_register_client",
         "msm_bus_scale_client_update_request",
         "msm_bus_scale_unregister_client"))
    checks["no_forced_arm_cmdline"] = "a52.ipa=1" not in new["cmdline"]
    failed = [name for name, ok in checks.items() if not ok]
    data = {"phase": "P470-A6-BOOTV2-CANDIDATE",
            "status": "FORMAT_AND_LINK_PASS_ONDEVICE_PENDING" if not failed else "BLOCKED",
            "checks": checks, "blockers": failed,
            "preserved_baseline_sha256": sha(oldraw),
            "candidate_sha256": sha(newraw),
            "native_image_sha256": sha(native),
            "packaged_gzip_sha256": sha(new["kernel"]),
            "baseline_dtb_sha256": sha(base["dtb"]),
            "candidate_dtb_sha256": sha(new["dtb"]),
            "ramdisk_sha256": sha(new["ramdisk"]),
            "candidate_is_real_boot_image": not failed,
            "new_ipa_hardware_runtime_verified": False,
            "external_merged_fdt_evidence_verified": False,
            "user_autoarm_v2_enabled_by_default": "NOT_AUDITED",
            "first_flash_authorized": False}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    if failed:
        raise SystemExit("P470-A6 candidate blocked: " + ", ".join(failed))
    print("P470-A6 real boot-v2 candidate packaged and invariants PASS; runtime pending")


if __name__ == "__main__":
    main()
