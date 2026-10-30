#!/usr/bin/env python3
"""P470-A4: bounded IPA AP/uC DMA IOVA diagnostics, no mapping changes.

Insert into the *disposable A3/A4 native in-tree build only*. The logged
IOVAs come from successful dma-iommu maps, not a fabricated address pool.
"""
import argparse
import json
from pathlib import Path

PATH = Path("drivers/iommu/dma-iommu.c")
TAG = "P470_A4_LAGOON_DMA_IOVA_FIRST8_V1"
HELPER = r'''
/* P470_A4_LAGOON_DMA_IOVA_FIRST8_V1
 * Observe only Lagoon IPA AP/uC IOVA maps, capped at the first eight
 * successful map operations. Never alter the DMA allocator or its
 * allocations. An IOVA outside the TG pool is a hardware blocker.
 */
static atomic_t p470_a4_ipa_map_count = ATOMIC_INIT(0);

static void p470_a4_log_ipa_dma_map(struct device *dev,
                                    struct iommu_domain *domain,
                                    dma_addr_t iova, size_t size,
                                    const char *method)
{
    u64 start, end, addr = iova;
    const char *cb;
    int count;
    bool in_pool;

    if (!dev || !dev->of_node || !domain)
        return;
    if (of_device_is_compatible(dev->of_node, "qcom,ipa-smmu-ap-cb")) {
        cb = "ap";
        start = 0x20000000ULL;
        end = 0x60000000ULL;
    } else if (of_device_is_compatible(dev->of_node,
                                      "qcom,ipa-smmu-uc-cb")) {
        cb = "uc";
        start = 0x40000000ULL;
        end = 0x60000000ULL;
    } else {
        return;
    }
    count = atomic_inc_return(&p470_a4_ipa_map_count);
    if (count > 8)
        return;

    in_pool = addr >= start && addr < end &&
              size <= end - addr;
    dev_info(dev,
             "P470 IPA DMA_MAP n=%d cb=%s op=%s type=%d iova=%pad size=%zu pool=[%llx,%llx) in_pool=%d aperture=[%llx,%llx]\n",
             count, cb, method, domain->type, &iova, size,
             start, end, in_pool,
             (u64)domain->geometry.aperture_start,
             (u64)domain->geometry.aperture_end);
    if (!in_pool)
        dev_err(dev, "P470 IPA DMA_MAP OUT_OF_POOL n=%d cb=%s\n",
                count, cb);
}
'''


def replace(s, a, b, name):
    count = s.count(a)
    if count != 1:
        raise RuntimeError(f"P470-A4 DMA {name}: expected one anchor, got {count}")
    return s.replace(a, b, 1)


def apply(s):
    if TAG in s:
        raise RuntimeError("P470-A4 DMA instrumentation already present")
    s = replace(s, "#include <linux/dma-iommu.h>",
                "#include <linux/dma-iommu.h>\n#include <linux/of.h>",
                "of helper declaration")
    s = replace(s, "struct iommu_dma_msi_page {",
                HELPER + "\nstruct iommu_dma_msi_page {",
                "IPA-only first-eight helper")
    s = replace(s, "\treturn iova + iova_off;\n",
                '\tp470_a4_log_ipa_dma_map(dev, domain, iova + iova_off,\n'
                '\t\t\t\t       size - iova_off, "page");\n'
                "\treturn iova + iova_off;\n",
                "successful page map")
    s = replace(s, "\treturn __finalise_sg(dev, sg, nents, iova);\n",
                '\tp470_a4_log_ipa_dma_map(dev, domain, iova, iova_len, "sg");\n'
                "\treturn __finalise_sg(dev, sg, nents, iova);\n",
                "successful sg map")
    return s


def check(s):
    for marker in (TAG, "P470 IPA DMA_MAP n=", "P470 IPA DMA_MAP OUT_OF_POOL",
                   '"page"', '"sg"', "count > 8",
                   "of_device_is_compatible(dev->of_node",
                   "domain->geometry.aperture_start",
                   "iommu_map_atomic(domain, iova",
                   "iommu_map_sg_atomic(domain, iova"):
        if marker not in s:
            raise RuntimeError("P470-A4 missing DMA guard: " + marker)
    if s.count("p470_a4_log_ipa_dma_map(dev, domain,") != 2:
        raise RuntimeError("P470-A4 exactly two successful DMA map sites expected")
    return {"phase": "P470-A4-DMA-IOVA-TRACE",
            "ipa_ap_uc_only": True, "first_n": 8,
            "map_types": ["dma-map-page", "dma-map-sg"],
            "changes_dma_algorithm": False,
            "hardware_verified": False, "flashable": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--check-only", action="store_true")
    a = p.parse_args()
    f = a.root / PATH
    if not a.check_only:
        f.write_text(apply(f.read_text()))
    result = check(f.read_text())
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("P470-A4 IPA first-eight successful DMA IOVA mapping diagnostics PASS; NO FLASH")


if __name__ == "__main__":
    main()
