#!/usr/bin/env python3
"""P470-A1 read-only TG Lagoon hardware contract and 5.10 provider gates.

Verified source contracts are reported separately from missing/untested
hardware readiness. This NEVER enables IPA, modem, PIL or SMMU mappings.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

TG_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
DONOR_SHA = "c560cc3c2840fb0ebc55ceef5b27549c66143637"
TG_DTS = "arch/arm64/boot/dts/vendor/qcom/lagoon.dtsi"
FEATURES = (
    "CONFIG_GSI=y",
    "CONFIG_GSI_REGISTER_VERSION_2=y",
    "CONFIG_IPA3=y",
    "CONFIG_IPA_WDI_UNIFIED_API=y",
    "CONFIG_RMNET_IPA3=y",
    "CONFIG_RNDIS_IPA=y",
    "# CONFIG_IPA3_REGDUMP is not set",
)

def git_sha(path):
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()

def block(src, name):
    m = re.search(r"(?m)^\s*(?:[A-Za-z0-9_]+:\s*)?"
                  + re.escape(name) + r"\s*\{", src)
    if not m:
        raise RuntimeError("P470-A1 missing pinned TG node: " + name)
    pos, depth = m.end(), 1
    # DTS blocks here contain no brace-bearing strings.
    while pos < len(src) and depth:
        if src[pos] == "{":
            depth += 1
        elif src[pos] == "}":
            depth -= 1
        pos += 1
    if depth:
        raise RuntimeError("P470-A1 unterminated node " + name)
    return src[m.end():pos-1]

def expect(s, v, label):
    if v not in s:
        raise RuntimeError("P470-A1 pinned Lagoon drift: " + label)

def has_source(root, path, token):
    p = root / path
    return p.is_file() and token in p.read_text(errors="replace")

def main():
    ap = argparse.ArgumentParser()
    for name in ("root", "donor", "tg", "config", "report"):
        ap.add_argument("--" + name, required=True, type=Path)
    a = ap.parse_args()
    if git_sha(a.tg) != TG_SHA or git_sha(a.donor) != DONOR_SHA:
        raise RuntimeError("P470-A1 refuse unpinned TG/dataipa")
    dt = (a.tg / TG_DTS).read_text()
    conf = (a.tg / "arch/arm64/configs/a52xq_defconfig").read_text()
    for item in FEATURES:
        if item not in conf.splitlines():
            raise RuntimeError("P470-A1 TG config drift: " + item)
    ipa = block(dt, "qcom,ipa@1e00000")
    firmware = block(dt, "qcom,ipa_fws")
    ap_cb = block(dt, "ipa_smmu_ap")
    wlan_cb = block(dt, "ipa_smmu_wlan")
    uc_cb = block(dt, "ipa_smmu_uc")
    required = [
        (dt, "reg = <0x0 0x8b700000 0x0 0x10000>", "IPA firmware reserve"),
        (dt, "reg = <0x0 0x8b710000 0x0 0x5400>", "GSI firmware reserve"),
        (dt, 'qcom,entry-name = "ipa"', "modem SMP2P ipa"),
        (firmware, "qcom,pas-id = <0xf>", "firmware PAS15"),
        (firmware, 'qcom,firmware-name = "lagoon_ipa_fws"', "firmware name"),
        (firmware, "memory-region = <&pil_ipa_fw_mem>", "PAS15 reserved region"),
        (ipa, "reg = <0x1e00000 0x84000>", "IPA MMIO"),
        (ipa, "<0x1e04000 0x23000>", "GSI MMIO"),
        (ipa, "GIC_SPI 311 IRQ_TYPE_LEVEL_HIGH", "IPA IRQ"),
        (ipa, "GIC_SPI 432 IRQ_TYPE_LEVEL_HIGH", "GSI IRQ"),
        (ipa, "qcom,ipa-hw-ver = <18>", "IPA 4.7 hardware"),
        (ipa, 'qcom,use-gsi-ipa-fw = "lagoon_ipa_fws"', "IPA driver PIL name"),
        (ipa, "qcom,smmu-fast-map", "SMMU fast-map needed"),
        (ipa, "qcom,msm-bus,num-paths = <5>", "five ICC paths"),
        (ipa, "qcom,msm-bus,num-cases = <5>", "five ICC operating points"),
        (ipa, "qcom,smp2p_map_ipa_1_out", "SMP2P out"),
        (ipa, "qcom,smp2p_map_ipa_1_in", "SMP2P in"),
        (ap_cb, "iommus = <&apps_smmu 0x0440 0x0>", "AP SID"),
        (ap_cb, 'qcom,iommu-dma = "fastmap"', "AP fast-map"),
        (ap_cb, "qcom,additional-mapping = <0x146a8000 0x146a8000 0x2000>", "AP extra map"),
        (wlan_cb, "iommus = <&apps_smmu 0x0441 0x0>", "WLAN SID"),
        (wlan_cb, "qcom,additional-mapping = <0x1ea0000 0x1ea0000 0x80000>", "WLAN uC map"),
        (uc_cb, "iommus = <&apps_smmu 0x0442 0x0>", "uC SID"),
    ]
    for source, token, label in required:
        expect(source, token, label)
    donor_ipa = (a.donor / "drivers/platform/msm/ipa/ipa_v3/ipa.c").read_text()
    for token in ("subsystem_get(sub_sys)", '"qcom,use-gsi-ipa-fw"',
                  "ipa3_attach_to_smmu()", "ipa3_post_init(&ipa3_res"):
        expect(donor_ipa, token, "real IPA donor sequence " + token)
    config = a.config.read_text()
    root = a.root
    smmu = (root / "drivers/iommu/arm/arm-smmu/arm-smmu.c").read_text()
    providers = {
        "scm_pas_auth_and_reset": has_source(root, "drivers/firmware/qcom_scm.c", "qcom_scm_pas_auth_and_reset"),
        "pil_subsystem_get": has_source(root, "drivers/a52_pil/subsystem_restart.c", "subsystem_get("),
        "pil_pas15_node_installed": False,
        "iommu_domain_attr_s1_bypass": has_source(root, "include/linux/iommu.h", "DOMAIN_ATTR_S1_BYPASS"),
        "iommu_domain_attr_fast": has_source(root, "include/linux/iommu.h", "DOMAIN_ATTR_FAST"),
        "default_apps_smmu_suspend_veto": "system suspend blocked until qsmmuv500 TBU support is ported" in smmu,
        "smmu_p460b_opt_in": "A52_P460B_APPS_SMMU_TG_OPTIN_V1" in smmu,
        "real_ipa_driver_in_composed_kernel": (root / "drivers/platform/msm/ipa/ipa_v3/ipa.c").is_file(),
    }
    # The P469b boot's IPA nodes are disabled by design. Firmware is not
    # owned merely because the original TG source contains a legacy PIL node.
    blockers = [
        "P470-A1: real SMMU DOMAIN_ATTR_S1_BYPASS / FAST semantics and fastmap not established",
        "P470-A1: AP/WLAN/uC SID 0x440/0x441/0x442 context banks not attached",
        "P470-A1: P460B default apps-SMMU suspend veto retained; test retention before activation",
        "P470-A1: real PAS15 firmware owner / lager IPA FW lifecycle not brought up",
        "P470-A1: IPA + GSI DT, SMP2P, ICC vote paths not enabled on production boot",
        "P470-A1: modem SSR / IPA QMI / rmnet_ipa0 runtime not verified",
    ]
    if "CONFIG_IPA3=y" in config.splitlines() or "CONFIG_IPA3=m" in config.splitlines():
        raise RuntimeError("P470-A1 REFUSE: experimental baseline enabled production IPA3")
    result = {
        "phase": "P470-A1-HARDWARE-CONTRACT",
        "status": "BLOCKED_NOT_FLASHABLE",
        "donor_sha": DONOR_SHA, "tg_sha": TG_SHA,
        "source_contract_verified": True,
        "lagoon_features": list(FEATURES),
        "hardware": {
            "ipa": "v4.7, 0x1e00000+0x84000, SPI311",
            "gsi": "0x1e04000+0x23000, SPI432",
            "pas": "0xf; lagoon_ipa_fws; 0x8b700000+0x10000",
            "gsi_reserved": "0x8b710000+0x5400",
            "iommu_sids": {"AP":"0x440","WLAN":"0x441","uC":"0x442"},
            "interconnect": "5 paths, 5 levels",
            "smp2p": "ipa in/out",
        },
        "actual_composed_provider_snapshot": providers,
        "gates": blockers,
        "scm_policy": "mem_protect_region and secure dump remain fail-closed in compile probe",
        "runtime_or_firmware_tested": False,
        "flashable": False,
    }
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("P470-A1 TG LAGOON SOURCE GATE PASS: v4.7 PAS15 CB 0x440/1/2 real contract")
    print("P470-A1 HARDWARE GATE: BLOCKED_NOT_FLASHABLE; P460B veto retained")

if __name__ == "__main__":
    main()
