#!/usr/bin/env python3
"""P470-A2b: exact-SID Lagoon IPA DMA reservations in arm-smmu 5.10.

Only the compatible IPA CBs with EXACT unmasked streams 0x440/0x441/0x442
receive these entries. No change to the global allocator, default domain,
SMMU implementation, suspend path, SMR/S2CR state, GPU or ADSP mappings.

IOMMU_RESV_DIRECT identity-maps fixed IPA MMIO windows in Linux 5.10.
IOMMU_RESV_RESERVED removes the vendor IPA manual-map IOVA pools from the
generic DMA allocator. The IPA driver's explicit map must recognize the
preinstalled, correctly translated direct windows; never remap blindly.

This is source preparation. Production DT/PAS15/IPA built-in gates stay shut.
"""
import argparse
import json
from pathlib import Path

SOURCE = Path("drivers/iommu/arm/arm-smmu/arm-smmu.c")
TAG = "P470_A2_LAGOON_IPA_SID_RESV_V1"
ANCHOR = "static void arm_smmu_get_resv_regions(struct device *dev,"
CALL = "\tiommu_dma_get_resv_regions(dev, head);"

INSERT = r'''
/* P470_A2_LAGOON_IPA_SID_RESV_V1
 * Exact TouchGrass Lagoon IPA hardware streams only. Do not install
 * Qualcomm's FAST page tables and do not alter the Phase206/P460B veto.
 * At DMA-domain device attach, Linux creates the DIRECT identity mappings.
 * The RESERVED IPA pools are excluded from generic DMA API IOVA allocation.
 */
static void p470_a2_reserve_ipa_region(struct device *dev,
                                       struct list_head *head,
                                       phys_addr_t base, size_t size,
                                       enum iommu_resv_type type)
{
    struct iommu_resv_region *region;
    int prot = IOMMU_READ | IOMMU_WRITE | IOMMU_NOEXEC | IOMMU_MMIO;

    region = iommu_alloc_resv_region(base, size, prot, type);
    if (!region) {
        /* IPA CB must subsequently refuse probe when reservations absent. */
        dev_err(dev, "P470 IPA SMMU reservation allocation failed base=%pa size=%zu\\n",
                &base, size);
        return;
    }
    list_add_tail(&region->list, head);
}

static void p470_a2_lagoon_ipa_resv(struct device *dev,
                                    struct list_head *head)
{
    const struct iommu_fwspec *fw;
    const char *cb;
    u32 sid, mask, expected;

    if (!dev || !dev->of_node)
        return;
    if (of_device_is_compatible(dev->of_node, "qcom,ipa-smmu-ap-cb")) {
        cb = "ap";
        expected = 0x440;
    } else if (of_device_is_compatible(dev->of_node,
                                       "qcom,ipa-smmu-wlan-cb")) {
        cb = "wlan";
        expected = 0x441;
    } else if (of_device_is_compatible(dev->of_node,
                                       "qcom,ipa-smmu-uc-cb")) {
        cb = "uc";
        expected = 0x442;
    } else {
        return;
    }

    fw = dev_iommu_fwspec_get(dev);
    if (!fw || fw->num_ids != 1) {
        dev_err(dev, "P470 IPA SMMU cb=%s invalid fwspec; reserving nothing\\n",
                cb);
        return;
    }
    sid = FIELD_GET(ARM_SMMU_SMR_ID, fw->ids[0]);
    mask = FIELD_GET(ARM_SMMU_SMR_MASK, fw->ids[0]);
    if (sid != expected || mask) {
        dev_err(dev,
                "P470 IPA SMMU cb=%s SID mismatch sid=0x%x mask=0x%x expected=0x%x\\n",
                cb, sid, mask, expected);
        return;
    }

    if (sid == 0x440) {
        p470_a2_reserve_ipa_region(dev, head, 0x146a8000, 0x2000,
                                   IOMMU_RESV_DIRECT);
        p470_a2_reserve_ipa_region(dev, head, 0x20000000, 0x40000000,
                                   IOMMU_RESV_RESERVED);
    } else if (sid == 0x441) {
        p470_a2_reserve_ipa_region(dev, head, 0x01ea0000, 0x80000,
                                   IOMMU_RESV_DIRECT);
    } else if (sid == 0x442) {
        p470_a2_reserve_ipa_region(dev, head, 0x40000000, 0x20000000,
                                   IOMMU_RESV_RESERVED);
    }
    dev_info(dev, "P470 IPA SMMU cb=%s sid=0x%03x reservations submitted\\n",
             cb, sid);
}

'''


def transform(s):
    if TAG in s:
        raise RuntimeError("P470-A2 IPA SID reservation already installed")
    if s.count(ANCHOR) != 1 or s.count(CALL) != 1:
        raise RuntimeError("P470-A2 upstream arm-smmu get_resv_regions drift")
    s = s.replace(ANCHOR, INSERT + ANCHOR, 1)
    s = s.replace(CALL,
                  "\tp470_a2_lagoon_ipa_resv(dev, head);\n" + CALL, 1)
    return s


def check(s):
    for token in (TAG, "IOMMU_RESV_DIRECT", "IOMMU_RESV_RESERVED",
                  "0x146a8000", "0x01ea0000", "0x20000000, 0x40000000",
                  "0x40000000, 0x20000000",
                  "FIELD_GET(ARM_SMMU_SMR_ID, fw->ids[0])",
                  "FIELD_GET(ARM_SMMU_SMR_MASK, fw->ids[0])",
                  "p470_a2_lagoon_ipa_resv(dev, head);",
                  CALL):
        if token not in s:
            raise RuntimeError("P470-A2 reservation source missing " + token)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    if a.self_test:
        fixture = ANCHOR + "\n{\n" + CALL + "\n}\n"
        check(transform(fixture))
        try:
            transform(transform(fixture))
        except RuntimeError:
            pass
        else:
            raise AssertionError("must refuse repeated SMMU patch")
        print("P470-A2 SID reservation transformer selftest PASS")
        return
    if not a.root:
        p.error("--root required outside --self-test")
    f = a.root / SOURCE
    s = f.read_text()
    if not a.check_only:
        s = transform(s)
        f.write_text(s)
    check(s)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps({
            "phase": "P470-A2b-LAGOON-SID-RESV",
            "sids": {"ap": "0x440", "wlan": "0x441", "uc": "0x442"},
            "direct": {"ap": ["0x146a8000", "0x2000"],
                       "wlan": ["0x1ea0000", "0x80000"]},
            "reserved_iova_pools": {"ap": ["0x20000000", "0x40000000"],
                                    "uc": ["0x40000000", "0x20000000"]},
            "vendor_fastmap_implemented": False,
            "identity_bypass_enabled": False, "flashable": False,
        }, indent=2) + "\n")
    print("P470-A2 SID-scoped DIRECT+RESERVED entries PASS (NO IPA FLASH)")


if __name__ == "__main__":
    main()
