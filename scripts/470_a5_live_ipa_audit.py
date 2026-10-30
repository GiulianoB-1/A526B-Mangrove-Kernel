#!/usr/bin/env python3
"""P470-A5: authoritative, sanitized P469b live IPA FDT ABI audit.

Read-only. /sys/firmware/fdt already contains the bootloader's merge of boot
DTB and DTBO idx 1. Does not require /chosen/bootargs or /chosen/kaslr-seed.
No node additions. Distinguishes DT correctness from driver/ICC readiness.
"""
import argparse
import json
import runpy
import struct
from pathlib import Path

fdt = runpy.run_path("scripts/461_dtbo_live_audit.py")["fdt"]

NAMES = {
    "ipa": "qcom,ipa",
    "pas15": "qcom,pil-tz-generic",
    "ap_cb": "qcom,ipa-smmu-ap-cb",
    "wlan_cb": "qcom,ipa-smmu-wlan-cb",
    "uc_cb": "qcom,ipa-smmu-uc-cb",
    "gsi": "qcom,msm_gsi",
    "rmnet": "qcom,rmnet-ipa3",
    "ipa_in": "qcom,smp2p-map-ipa-1-in",
    "ipa_out": "qcom,smp2p-map-ipa-1-out",
}
SIDS = {"ap_cb": 0x440, "wlan_cb": 0x441, "uc_cb": 0x442}


def cells(props, name):
    v = props.get(name)
    if v is None or len(v) % 4:
        return None
    return list(struct.unpack(">" + "I" * (len(v) // 4), v))


def strings(props, name):
    return [x.decode("utf-8", "replace") for x in props.get(name, b"").rstrip(b"\0").split(b"\0") if x]


def active(props):
    return not strings(props, "status") or strings(props, "status")[0] in ("okay", "ok")


def audit(blob):
    tree = fdt(blob)
    fails, passed, nodes = [], [], {}

    def test(ok, reason):
        (passed if ok else fails).append(reason)

    for kind, compat in NAMES.items():
        found = [(name, props) for name, props in tree.items()
                 if compat in strings(props, "compatible")
                 and (kind != "pas15" or cells(props, "qcom,pas-id") == [15])]
        nodes[kind] = [name for name, _ in found]
        test(len(found) == 1, "unique node: " + kind)
        if len(found) == 1:
            test(active(found[0][1]), "enabled (status absent is okay): " + kind)

    def prop(kind):
        return tree[nodes[kind][0]] if len(nodes[kind]) == 1 else {}

    ipa = prop("ipa")
    test(cells(ipa, "reg") == [0x1e00000, 0x84000, 0x1e04000, 0x23000],
         "IPA/GSI MMIO geometry")
    test(cells(ipa, "interrupts") == [0, 311, 4, 0, 432, 4],
         "IPA/GSI IRQ SPI311/432")
    test(cells(ipa, "qcom,ipa-hw-ver") == [18], "Lagoon IPAv4.7")
    test(strings(ipa, "qcom,use-gsi-ipa-fw") == ["lagoon_ipa_fws"],
         "IPA uses existing lagoon_ipa_fws")
    test(not ipa.get("interconnects"), "DT uses legacy msm-bus only, no ICC provider phandles")
    test(cells(ipa, "qcom,msm-bus,num-cases") == [5] and
         cells(ipa, "qcom,msm-bus,num-paths") == [5],
         "legacy bus matrix is 5 cases by 5 paths")
    vec = cells(ipa, "qcom,msm-bus,vectors-KBps")
    pairs = []
    if vec is not None and len(vec) == 100:
        pairs = [(vec[j], vec[j + 1]) for j in range(0, 20, 4)]
        test(all([(vec[case * 20 + j], vec[case * 20 + j + 1])
                  for j in range(0, 20, 4)] == pairs for case in range(5)),
             "all five bus cases preserve same source/dest path order")
        test(all(vec[j + 2] == 0 and vec[j + 3] == 0
                 for j in range(0, 20, 4)), "case zero no-vote")
        test(any(vec[j + 2] or vec[j + 3]
                 for j in range(20, 100, 4)), "active cases contain nonzero BW")
    test(vec is not None and len(vec) == 100, "legacy bus vectors: 5*5*4 u32")

    pas = prop("pas15")
    test(strings(pas, "qcom,firmware-name") == ["lagoon_ipa_fws"],
         "PAS15 named firmware owner")
    other_pas15 = [n for n, p in tree.items()
                   if cells(p, "qcom,pas-id") == [15]]
    test(len(other_pas15) == 1, "no second PAS15 authentication owner")

    for kind, sid in SIDS.items():
        iom = cells(prop(kind), "iommus")
        test(iom is not None and len(iom) == 3 and iom[1:] == [sid, 0],
             kind + " SID " + hex(sid))
    test(cells(prop("ap_cb"), "qcom,iommu-dma-addr-pool") ==
         [0x20000000, 0x40000000], "AP allocator-owned DMA pool")
    test(cells(prop("uc_cb"), "qcom,iommu-dma-addr-pool") ==
         [0x40000000, 0x20000000], "uC allocator-owned DMA pool")
    test(cells(prop("ap_cb"), "qcom,geometry-mapping") == [0, 0xf0000000],
         "AP IOVA aperture")
    test(cells(prop("ap_cb"), "qcom,additional-mapping") ==
         [0x146a8000, 0x146a8000, 0x2000], "AP translated DIRECT")
    test(cells(prop("wlan_cb"), "qcom,additional-mapping") ==
         [0x1ea0000, 0x1ea0000, 0x80000], "WLAN translated DIRECT")

    for kind in ("ipa_in", "ipa_out"):
        test(len(nodes[kind]) == 1 and nodes[kind][0].startswith(nodes["ipa"][0] + "/")
             if nodes["ipa"] else False, kind + " under IPA parent")
    test(any(path.startswith("/soc/") and "apps-smmu@15000000" in path
             and "qcom,skip-init" in props
             for path, props in tree.items()), "apps-smmu@15000000 skip-init retained")
    reserved = [(path, p) for path, p in tree.items()
                if path.startswith("/reserved-memory/")]
    def reserved_reg(address, size):
        return any(cells(p, "reg") in ([0, address, 0, size],
                                      [address, size]) for _, p in reserved)
    test(reserved_reg(0x8b700000, 0x10000), "PAS15 reserved memory")
    test(reserved_reg(0x8b710000, 0x5400), "GSI reserved memory")
    return {
        "phase": "P470-A5-LIVE-MERGED-IPA-ABI",
        "source": "live sanitized /sys/firmware/fdt from P469b",
        "dt_static_pass": not fails,
        "dtb_nodes": nodes,
        "bus_source_dest_pairs": pairs,
        "bus_legacy_only": not ipa.get("interconnects"),
        "checks_passed": passed,
        "blockers": fails,
        "no_new_dt_nodes": True,
        "bus_voting_backend_proved": False,
        "live_ipa_hw_runtime_proved": False,
        "flashable": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--live-fdt", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--enforce", action="store_true")
    a = p.parse_args()
    result = audit(a.live_fdt.read_bytes())
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("P470-A5 LIVE DT " + ("STATIC_PASS" if result["dt_static_pass"] else "BLOCKED") +
          " checks=" + str(len(result["checks_passed"])) +
          " blockers=" + str(len(result["blockers"])) +
          " BUS_VOTE_BACKEND=UNPROVEN NO_FLASH")
    for x in result["blockers"]:
        print("P470-A5 LIVE DT BLOCKER: " + x)
    if a.enforce and result["blockers"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
