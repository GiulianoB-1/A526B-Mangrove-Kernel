#!/usr/bin/env python3
"""P470 pre-port audit of the *real* 5.10 dataipa donor against Mangrove.

This is NOT an IPA driver or a modem-stability fix. Never enable IPA or
publish this as a flashable Phase A0 image based only on this report.
Audits source/UAPI/SSR dependencies without replacing the P469b boot.
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

DONOR_REPO = "https://github.com/CodeLinaro-mirror/la_platform_vendor_opensource_dataipa.git"
DONOR_SHA = "c560cc3c2840fb0ebc55ceef5b27549c66143637"
TG_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
DATAIPA = Path("drivers/platform/msm")
REQUIRED_FILES = [
    "gsi/gsi.c", "gsi/gsi_reg_v2.h",
    "ipa/ipa_v3/ipa.c", "ipa/ipa_v3/ipa_utils.c",
    "ipa/ipa_v3/ipahal/ipahal.c",
    "ipa/ipa_v3/ipa_pm.c", "ipa/ipa_v3/ipa_qmi_service.c",
    "ipa/ipa_v3/ipa_qmi_service_v01.c",
    "ipa/ipa_v3/rmnet_ipa.c", "ipa/ipa_v3/rmnet_ipa_fd_ioctl.c",
]
# Headers included by the true vendor 5.10 implementation. Some may be
# provided through the existing TG/SSR ports; the audit checks the *actual*
# composed tree, not what is present in an arbitrary donor.
ABI_HEADERS = [
    "include/linux/ipa.h",
    "include/linux/msm_gsi.h",
    "include/linux/rmnet_ipa_fd_ioctl.h",
    "include/linux/ipa_qmi_service_v01.h",
    "include/uapi/linux/msm_ipa.h",
    "include/uapi/linux/msm_rmnet.h",
    "include/soc/qcom/subsystem_notif.h",
    "include/soc/qcom/subsystem_restart.h",
]
RMNET_SYMBOLS = [
    "IPA_WWAN_DEV_NAME", "rmnet_ipa%d", "ipa3_wwan_ioctl",
    "RMNET_IOCTL_EXTENDED", "RMNET_IOCTL_GET_EP_PAIR",
    "IPA_CLIENT_APPS_WAN_CONS", "IPA_CLIENT_APPS_WAN_PROD",
    "IPA_EP_NOT_ALLOCATED", "producer_pipe_num", "consumer_pipe_num",
    "RMNET_IOCTL_SET_EGRESS_DATA_FORMAT",
    "RMNET_IOCTL_SET_INGRESS_DATA_FORMAT",
    "RMNET_IOCTL_ADD_MUX_CHANNEL",
    "RMNET_IOCTL_GET_SUPPORTED_FEATURES",
    "CAP_NET_ADMIN", "SUBSYS_BEFORE_SHUTDOWN", "SUBSYS_AFTER_POWERUP",
]
HARDWARE = {
    "soc": "lagoon/sm7225",
    "hw_version": 18,
    "ipa_version": "4.7",
    "ipa_base": "0x1e00000",
    "gsi_base": "0x1e04000",
    "ipa_spi": 311,
    "gsi_spi": 432,
    "cb_sids": {"ap": "0x0440", "wlan": "0x0441", "uc": "0x0442"},
    "fw": "lagoon_ipa_fws",
    "fw_pas_id": "0x0f",
    "fw_region": ["0x8b700000", "0x10000"],
    "gsi_region": ["0x8b710000", "0x5400"],
}

def commit_of(path):
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()

def audit(root, donor, tg=None):
    if not (root / "Makefile").is_file():
        raise RuntimeError("P470: missing actual composed GKI root")
    if commit_of(donor) != DONOR_SHA:
        raise RuntimeError("P470: dataipa donor SHA mismatch, refuse drift")
    tree = donor / DATAIPA
    missing_files = [p for p in REQUIRED_FILES if not (tree / p).is_file()]
    missing_abi = [p for p in ABI_HEADERS if not (root / p).is_file()]
    rmnet = (tree / "ipa/ipa_v3/rmnet_ipa.c")
    source = rmnet.read_text() if rmnet.is_file() else ""
    absent_rmnet = [s for s in RMNET_SYMBOLS if s not in source]
    get_ep_pair = re.search(
        r"case\s+RMNET_IOCTL_GET_EP_PAIR\s*:(.*?)(?=\n\s*case\s+|\Z)",
        source, re.S,
    )
    ep = get_ep_pair.group(1) if get_ep_pair else ""
    real_ep_mapping = (
        bool(ep)
        and ep.count("ipa_get_ep_mapping(") == 2
        and ep.count("IPA_EP_NOT_ALLOCATED") == 2
        and "IPA_CLIENT_APPS_WAN_CONS" in ep
        and "IPA_CLIENT_APPS_WAN_PROD" in ep
        and "producer_pipe_num" in ep and "consumer_pipe_num" in ep
    )
    ipa_src = (tree / "ipa/ipa_v3/ipa.c")
    hw47_in_donor = ipa_src.is_file() and "IPA_HW_v4_7" in ipa_src.read_text()
    qmi_src = (tree / "ipa/ipa_v3/ipa_qmi_service.c")
    qmi_present = qmi_src.is_file() and "IPA_Q6_SERVICE_SVC_ID" in qmi_src.read_text()
    ssr_header = root / "include/soc/qcom/subsystem_notif.h"
    ssr_api_in_root = ssr_header.is_file() and (
        "SUBSYS_BEFORE_SHUTDOWN" in ssr_header.read_text()
        and "subsys_notif_register_notifier" in ssr_header.read_text()
    )
    # P469b contains rproc-level shutdown, not legacy TG subsystem notifier
    # delivery. No SSR bridge is present until explicitly added and tested.
    vendor_ipa_in_gki = (root / "drivers/platform/msm/ipa/ipa_v3/ipa.c").is_file()
    tg_summary = None
    if tg:
        if commit_of(tg) != TG_SHA:
            raise RuntimeError("P470: TouchGrass donor SHA mismatch")
        dtsi = tg / "arch/arm64/boot/dts/qcom/lagoon.dtsi"
        if dtsi.is_file():
            raw = dtsi.read_text()
            tg_summary = {
                "lagoon_dtsi": str(dtsi.relative_to(tg)),
                "hwver_18": "qcom,ipa-hw-ver = <18>" in raw,
                "pas_f": "qcom,ipa_fws" in raw,
                "ipa_fw_name": "lagoon_ipa_fws" in raw,
                "rmnet_ipa3": 'compatible = "qcom,rmnet-ipa3"' in raw,
                "ap_cb_sid": "0x0440" in raw,
                "wlan_cb_sid": "0x0441" in raw,
                "uc_cb_sid": "0x0442" in raw,
            }
    blockers = []
    if missing_files: blockers.append("missing donor translation units")
    if missing_abi: blockers.append("missing matched Qualcomm ABI headers")
    if absent_rmnet or not real_ep_mapping: blockers.append("RIL extended ioctl contract incomplete")
    if not hw47_in_donor: blockers.append("hardware v4.7 support unverified")
    if not qmi_present: blockers.append("IPA QMI service source not verified")
    if not ssr_api_in_root: blockers.append("subsys_notif provider not verified in composed kernel")
    blockers += [
        "A0: source not linked or hardware-probed in this audit",
        "A0: SMMU CBs, IPA clocks and interconnect votes not verified",
        "A1: PAS 0xf / lagoon_ipa_fws firmware not loaded",
        "A2: real GSI endpoints, QMI init, rmnet_ipa0 and modem SSR bridge absent",
        "P468 auto-start must be bounded-gated on real IPA READY before A2",
    ]
    report = {
        "phase": "P470-A0-SOURCE-DEPENDENCY-AUDIT",
        "status": "BLOCKED_NOT_FLASHABLE",
        "baseline": {"phase": "P469b", "build": 605,
                     "commit": "19ff2acfc334f42788b645f29b690c33b652d1eb"},
        "donor": {"repository": DONOR_REPO, "sha": DONOR_SHA,
                  "file_count": sum(p.is_file() for p in tree.rglob("*"))},
        "tg_sha": TG_SHA, "hardware_from_workorder": HARDWARE,
        "missing_donor_files": missing_files, "missing_gki_abi_headers": missing_abi,
        "external_required_not_in_module": ["ipa_api.c (upstream core/kernel interface or TG equivalent)"],
        "rmnet_missing_symbols": absent_rmnet, "rmnet_real_endpoint_mapping": real_ep_mapping,
        "ipa_v4_7_token_present": hw47_in_donor, "ipa_qmi_source_present": qmi_present,
        "legacy_ssr_interface_usable": ssr_api_in_root,
        "upstream_ipa_source_already_in_tree": vendor_ipa_in_gki,
        "touchgrass_dtsi": tg_summary,
        "unresolved": blockers, "ipa_config_enabled": False,
        "flashable": False, "fake_rmnet_or_endpoints": False,
    }
    return report

def self_test():
    sample = """case RMNET_IOCTL_GET_EP_PAIR:
        a = ipa_get_ep_mapping(IPA_CLIENT_APPS_WAN_CONS);
        if (a == IPA_EP_NOT_ALLOCATED) return -EFAULT;
        p->producer_pipe_num = a;
        b = ipa_get_ep_mapping(IPA_CLIENT_APPS_WAN_PROD);
        if (b == IPA_EP_NOT_ALLOCATED) return -EFAULT;
        p->consumer_pipe_num = b;
        break;
    case RMNET_IOCTL_GET_SUPPORTED_FEATURES:"""
    ep = re.search(r"case\s+RMNET_IOCTL_GET_EP_PAIR\s*:(.*?)(?=\n\s*case\s+|\Z)", sample, re.S)
    assert ep and ep.group(1).count("ipa_get_ep_mapping(") == 2
    assert ep.group(1).count("IPA_EP_NOT_ALLOCATED") == 2
    print("P470 A0 donor contract parser self-test PASS")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path)
    p.add_argument("--donor", type=Path)
    p.add_argument("--tg", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--self-test", action="store_true")
    x = p.parse_args()
    if x.self_test:
        self_test()
        return
    if not x.root or not x.donor:
        p.error("--root and --donor required")
    result = audit(x.root, x.donor, x.tg)
    if x.report:
        x.report.parent.mkdir(parents=True, exist_ok=True)
        x.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("P470 A0 SOURCE AUDIT status=BLOCKED_NOT_FLASHABLE")
    print(json.dumps({k: result[k] for k in
        ("missing_donor_files", "missing_gki_abi_headers", "rmnet_real_endpoint_mapping",
         "ipa_v4_7_token_present", "ipa_qmi_source_present", "legacy_ssr_interface_usable",
         "unresolved")}, indent=2))
    if result["missing_donor_files"] or result["rmnet_missing_symbols"] \
            or not result["rmnet_real_endpoint_mapping"] or not result["ipa_v4_7_token_present"]:
        raise SystemExit("P470 incompatible donor; fail closed before integration")

if __name__ == "__main__":
    main()
