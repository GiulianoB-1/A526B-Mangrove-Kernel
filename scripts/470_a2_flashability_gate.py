#!/usr/bin/env python3
"""P470-A2 fail-closed readiness contract. No flash without source, DT and runtime proof."""
import argparse
import json
from pathlib import Path

REQUIRED_BUILTIN = ("CONFIG_GSI=y", "CONFIG_IPA3=y", "CONFIG_RMNET_IPA3=y")
REQUIRED_MARKERS = (
    "P470 IPA PROBE", "P470 IPA SMMU",
    "P470 IPA FW_LOAD", "P470 IPA GSI READY",
    "P470 MSS NOTIF event=",
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    ap.add_argument("--dtb", type=Path, help="Exact final effective boot DTB")
    ap.add_argument("--enforce", action="store_true")
    a = ap.parse_args()
    r, build = a.root, a.build
    config_path = build / ".config"
    config = set(config_path.read_text().splitlines()) if config_path.is_file() else set()
    failures = []
    def require(ok, reason):
        if not ok:
            failures.append(reason)

    for flag in REQUIRED_BUILTIN:
        require(flag in config, "built-in config absent: " + flag)
    for p in ("drivers/platform/msm/ipa/ipa_v3/ipa.c",
              "drivers/platform/msm/gsi/gsi.c",
              "drivers/platform/msm/ipa_fmwk/ipa_fmwk.c"):
        require((r / p).is_file(), "real built-in provider absent: " + p)

    ipa_path = r / "drivers/platform/msm/ipa/ipa_v3/ipa.c"
    ipa = ipa_path.read_text(errors="replace") if ipa_path.is_file() else ""
    require('subsystem_get(sub_sys)' in ipa or 'subsystem_get("ipa_fws")' in ipa,
            "IPA PAS15 legacy subsystem_get provider not wired")
    require("P470_A0_COMPILE_ONLY" not in config,
            "A0 compile-only macro in final config")
    require("P470 IPA SMMU" in ipa, "no IPA SMMU diagnostic in real driver")
    require("P470 IPA FW_LOAD" in ipa, "no PAS15 firmware lifecycle diagnostic")

    # The old P468 legacy subsystem NOTIFIER *consumer* is insufficient.
    # Insist on an actual 5.10 remoteproc/PAS producer, not a string in docs.
    pas = r / "drivers/remoteproc/qcom_q6v5_pas.c"
    core = r / "drivers/remoteproc/remoteproc_core.c"
    notifier_code = (
        (pas.read_text(errors="replace") if pas.is_file() else "") +
        (core.read_text(errors="replace") if core.is_file() else "")
    )
    require("P470 MSS NOTIF event=" in notifier_code and
            "subsys_notif_queue_notification(" in notifier_code,
            "MSS 5.10 remoteproc/SSR notifier producer missing")
    require("P470 MSS IPA_WAIT" in notifier_code,
            "bounded IPA-ready gate before modem powerup missing")
    smmu_p = r / "drivers/iommu/arm/arm-smmu/arm-smmu.c"
    smmu = smmu_p.read_text(errors="replace") if smmu_p.is_file() else ""
    require("system suspend blocked until qsmmuv500 TBU support is ported" in smmu,
            "Phase206 system-suspend veto absent")
    require("A52_P460B_APPS_SMMU_TG_OPTIN_V1" in smmu and
            "a52_p460b_sme_checksum" in smmu,
            "P460B opt-in / SME checksum audit missing")
    require("P470 A2 REAL FASTMAP" in smmu,
            "real, audited S1_BYPASS/FAST and fastmap support not implemented")
    image = build / "arch/arm64/boot/Image"
    img = image.read_bytes() if image.is_file() else b""
    require(bool(img), "linked final Image missing")
    for marker in REQUIRED_MARKERS:
        require(marker.encode() in img,
                "required executable Image marker missing: " + marker)
    # A1's successful modpost of private .ko modules is not this gate:
    # final IPA must be linked into vmlinux; no external .ko in the boot.
    sym = build / "System.map"
    syms = sym.read_text(errors="replace") if sym.is_file() else ""
    require(" ipa_fmwk_register_ipa" in syms,
            "real IPA framework not built into linked vmlinux")
    require(" ipa3_get_ep_mapping" in syms,
            "real IPA endpoint mapping not built into linked vmlinux")

    # DTB verification is mandatory. A supplied unverified source .dtsi or
    # the old P469b DTB can never pass a P470-A2 flash gate.
    require(a.dtb is not None and a.dtb.is_file(),
            "final packed boot DTB not supplied for hardware verification")
    # A verified FDT parser/ABI check must replace this stop before enabling
    # flashing. Do not infer hardware validity from the source DTS alone.
    failures.append("final DTB: audited IPA/GSI/PAS15/SMP2P/ICC/SIDs binding not yet implemented")
    failures.append("live PAS15, SMMU and modem SSR hardware acceptance not yet observed")
    result = {
        "phase": "P470-A2",
        "status": "BLOCKED_NOT_FLASHABLE" if failures else "STATIC_PASS_RUNTIME_PENDING",
        "flashable": False,
        "enforce": a.enforce,
        "reasons": failures,
        "phase206_suspend_veto_preserved": "system suspend blocked until qsmmuv500 TBU support is ported" in smmu,
        "p460b_checksum_source_preserved": "a52_p460b_sme_checksum" in smmu,
        "dtb_path": str(a.dtb) if a.dtb else None,
    }
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("P470-A2 READINESS: " + result["status"])
    for reason in failures:
        print("P470-A2 BLOCKER: " + reason)
    if a.enforce and failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
