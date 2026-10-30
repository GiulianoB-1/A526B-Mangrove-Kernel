#!/usr/bin/env python3
"""P470-A4 packed DTB audit, with exact IPA/PAS15/SID owners.

Input is the DTB actually used by the boot packer, not an unrelated DTS.
No writes to the DTB. A passing static audit is NOT runtime acceptance.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def command(*args):
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, check=False)
    if p.returncode:
        return None
    return p.stdout.strip()


def children(blob, node):
    s = command("fdtget", "-l", str(blob), node)
    return s.splitlines() if s is not None else []


def value(blob, node, prop, kind="x"):
    s = command("fdtget", "-t", kind, str(blob), node, prop)
    if s is None:
        return None
    if kind == "x":
        return [int(k, 16) for k in s.split()]
    return s


def single_subnode(blob, path, prefix):
    candidates = [path.rstrip("/") + "/" + n for n in children(blob, path)
                  if n == prefix or n.startswith(prefix + "@")]
    return candidates[0] if len(candidates) == 1 else None


def audit(blob):
    findings = []
    blocks = []
    def require(ok, label):
        findings.append({"name": label, "ok": bool(ok)})
        if not ok:
            blocks.append(label)

    soc = "/soc"
    mem = "/reserved-memory"
    ipa = single_subnode(blob, soc, "qcom,ipa")
    pil = single_subnode(blob, soc, "qcom,ipa_fws")
    ap = single_subnode(blob, soc, "ipa_smmu_ap")
    wlan = single_subnode(blob, soc, "ipa_smmu_wlan")
    uc = single_subnode(blob, soc, "ipa_smmu_uc")
    fw = single_subnode(blob, mem, "ipa_fw_region")
    gsi = single_subnode(blob, mem, "ipa_gsi_region")
    nodes = {"ipa": ipa, "pas15": pil, "ap_cb": ap,
             "wlan_cb": wlan, "uc_cb": uc, "fw_resv": fw,
             "gsi_resv": gsi}
    for name, path in nodes.items():
        require(path is not None, f"unique {name} DT node")
    if ipa:
        require(value(blob, ipa, "compatible", "s") == "qcom,ipa",
                "real IPA provider binding")
        require(value(blob, ipa, "reg") ==
                [0x1e00000, 0x84000, 0x1e04000, 0x23000],
                "IPA4.7 and GSI exact MMIO")
        require(value(blob, ipa, "interrupts") ==
                [0, 311, 4, 0, 432, 4], "IPA SPI311 and GSI SPI432")
        require(value(blob, ipa, "qcom,ipa-hw-ver") == [18],
                "Lagoon IPAv4.7 (18)")
        require(value(blob, ipa, "qcom,use-gsi-ipa-fw", "s") ==
                "lagoon_ipa_fws", "single PAS15 name matches IPA donor")
        require(value(blob, ipa, "qcom,msm-bus,num-paths") == [5] and
                value(blob, ipa, "qcom,msm-bus,num-cases") == [5],
                "5-path/5-state bus policy")
        vectors = value(blob, ipa, "qcom,msm-bus,vectors-KBps")
        require(vectors is not None and len(vectors) == 100,
                "5x5x4 bus voting vectors")
        for n, compat in (("qcom,smp2p_map_ipa_1_in",
                           "qcom,smp2p-map-ipa-1-in"),
                          ("qcom,smp2p_map_ipa_1_out",
                           "qcom,smp2p-map-ipa-1-out")):
            path = ipa + "/" + n
            require(compat in (value(blob, path, "compatible", "s") or ""),
                    "IPA SMP2P child " + n)
    if pil:
        require(value(blob, pil, "compatible", "s") ==
                "qcom,pil-tz-generic", "single legacy PIL-TZ PAS owner")
        require(value(blob, pil, "qcom,pas-id") == [15], "PAS id 0x0f")
        require(value(blob, pil, "qcom,firmware-name", "s") ==
                "lagoon_ipa_fws", "PAS subsystem matches real firmware name")
        require(value(blob, pil, "memory-region") is not None,
                "PAS15 memory-region phandle")
        # Every firmware owner must be unique by firmware-name. A second
        # compatible node could authenticate the same PAS ID twice.
        names = []
        for name in children(blob, soc):
            candidate = soc + "/" + name
            if value(blob, candidate, "qcom,pas-id") == [15]:
                names.append(candidate)
        require(names == [pil], "exactly one PAS15 authentication owner")
    if fw:
        require(value(blob, fw, "reg") ==
                [0, 0x8b700000, 0, 0x10000],
                "PAS15 region 8b700000+10000")
        require("no-map" in (command("fdtget", "-p", str(blob), fw) or "").splitlines(),
                "PAS15 firmware reservation no-map")
        if pil:
            require(value(blob, pil, "memory-region") ==
                    value(blob, fw, "phandle"),
                    "PAS15 phandle points to exact reserved region")
    if gsi:
        require(value(blob, gsi, "reg") ==
                [0, 0x8b710000, 0, 0x5400],
                "GSI firmware region 8b710000+5400")
        require("no-map" in (command("fdtget", "-p", str(blob), gsi) or "").splitlines(),
                "GSI firmware reservation no-map")
    for name, path, sid in (("ap", ap, 0x440),
                            ("wlan", wlan, 0x441),
                            ("uc", uc, 0x442)):
        if path:
            iom = value(blob, path, "iommus")
            require(iom is not None and len(iom) == 3 and
                    iom[-2:] == [sid, 0],
                    f"IPA {name} exact unmasked SMMU SID {sid:03x}")
    if ap:
        require(value(blob, ap, "qcom,iommu-dma-addr-pool") ==
                [0x20000000, 0x40000000],
                "AP allocator window, NOT reservation")
        require(value(blob, ap, "qcom,geometry-mapping") ==
                [0, 0xf0000000], "AP 0xf0000000 geometry bound")
        require(value(blob, ap, "qcom,additional-mapping") ==
                [0x146a8000, 0x146a8000, 0x2000],
                "AP DIRECT MMIO mapping")
    if wlan:
        require(value(blob, wlan, "qcom,additional-mapping") ==
                [0x1ea0000, 0x1ea0000, 0x80000],
                "WLAN DIRECT MMIO mapping")
    if uc:
        require(value(blob, uc, "qcom,iommu-dma-addr-pool") ==
                [0x40000000, 0x20000000],
                "uC allocator window, NOT reservation")
    require(value(blob, "/firmware/scm", "status", "s") == "disabled",
            "SCM runtime knob remains required, no auto-enable")
    return {"phase": "P470-A4-PACKED-DTB-STATIC",
            "dtb": str(blob), "sha256": hashlib.sha256(blob.read_bytes()).hexdigest(),
            "nodes": nodes, "checks": findings, "blockers": blocks,
            "status": "STATIC_PASS_RUNTIME_PENDING" if not blocks else "BLOCKED_NOT_FLASHABLE",
            "pas15_runtime_verified": False, "iommu_runtime_verified": False,
            "modem_ssr_verified": False, "flashable": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dtb", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--enforce", action="store_true")
    a = p.parse_args()
    if not a.dtb.is_file():
        raise SystemExit("P470-A4 missing exact staged DTB")
    result = audit(a.dtb)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(f"P470-A4 DTB {result['status']} blockers={len(result['blockers'])}")
    for x in result["blockers"]:
        print("P470-A4 DTB BLOCKER: " + x)
    if a.enforce and result["blockers"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
