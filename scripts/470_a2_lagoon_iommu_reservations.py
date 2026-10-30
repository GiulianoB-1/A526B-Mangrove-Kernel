#!/usr/bin/env python3
"""P470-A2c: exact-SID Lagoon IPA translated-DMA allocator pool contract.

TouchGrass qcom,iommu-dma-addr-pool is the ALLOCATOR-OWNED IOVA WINDOW,
not the region to reserve. This source generator reserves the COMPLEMENT:
  AP  SID 0x440: [aperture_start, 0x20000000) and
                 [0x60000000, min(aperture_end+1,0xF0000000))
  uC  SID 0x442: [aperture_start, 0x40000000) and
                 [0x60000000, aperture_end+1)
WLAN SID 0x441 gets only its fixed IOMMU_RESV_DIRECT window.
The fixed AP/WLAN DIRECT identity mappings remain installed separately.

The code modifies ONLY the exact-CB branch of arm-smmu's reservation
callback. No global fastmap, SMMU default-domain, suspend, SMR/S2CR, GPU
or ADSP changes. Generated GKI source still requires build and hardware
verification; no IPA boot image is authorized by this source gate.
"""
import argparse
import json
from pathlib import Path

SOURCE = Path("drivers/iommu/arm/arm-smmu/arm-smmu.c")
TAG = "P470_A2_LAGOON_IPA_DMA_POOL_COMPLEMENT_V2"
ANCHOR = "static void arm_smmu_get_resv_regions(struct device *dev,"
CALL = "\tiommu_dma_get_resv_regions(dev, head);"

INSERT = r'''
/* P470_A2_LAGOON_IPA_DMA_POOL_COMPLEMENT_V2
 * qcom,iommu-dma-addr-pool is the DMA allocator's USABLE range.
 * Return IOMMU_RESV_RESERVED for the COMPLEMENT of that window, not for
 * the window itself. Linux 5.10's iommu_dma_init_domain() applies these
 * reservations to its IOVA allocator, while IOMMU_RESV_DIRECT creates
 * the fixed identity mapping via iommu_create_device_direct_mappings().
 *
 * Scope exactly to the three unmasked Lagoon IPA stream IDs. Keep the
 * Phase206/P460B system-suspend and SMR/SME code unchanged.
 */
static bool p470_a2_ipa_append_resv(struct device *dev,
                                    struct list_head *head,
                                    phys_addr_t base, size_t size,
                                    enum iommu_resv_type type)
{
    struct iommu_resv_region *region;
    int prot = IOMMU_READ | IOMMU_WRITE | IOMMU_NOEXEC | IOMMU_MMIO;

    if (!size)
        return true;
    region = iommu_alloc_resv_region(base, size, prot, type);
    if (!region) {
        dev_err(dev, "P470 IPA SMMU reservation allocation failed base=%pa size=%zu\n",
                &base, size);
        return false;
    }
    list_add_tail(&region->list, head);
    return true;
}

/* All ends are INCLUSIVE. Never form aperture_end+1 because the domain
 * can span the full 64-bit address width. Pool_end is EXCLUSIVE.
 */
static bool p470_a2_ipa_reserve_complement(struct device *dev,
                                            struct list_head *head,
                                            const char *cb,
                                            struct iommu_domain *domain,
                                            u64 pool_start, u64 pool_size,
                                            u64 ap_limit_exclusive)
{
    u64 lo, hi, pool_end;

    if (!domain || domain->type != IOMMU_DOMAIN_DMA ||
        !domain->geometry.force_aperture) {
        dev_err(dev, "P470 IPA SMMU cb=%s DMA aperture unavailable\n", cb);
        return false;
    }
    lo = domain->geometry.aperture_start;
    hi = domain->geometry.aperture_end;
    if (ap_limit_exclusive)
        hi = min_t(u64, hi, ap_limit_exclusive - 1);

    pool_end = pool_start + pool_size;
    if (!pool_size || pool_end <= pool_start ||
        pool_start < lo || pool_end - 1 > hi) {
        dev_err(dev,
                "P470 IPA SMMU cb=%s invalid pool/aperture [%llx,%llx] pool=%llx+%llx\n",
                cb, lo, hi, pool_start, pool_size);
        return false;
    }

    /* Reservation of [lo, pool_start) and [pool_end, hi] (inclusive).
     * The first byte of the pool and its last byte are NEVER reserved.
     */
    if (lo < pool_start &&
        !p470_a2_ipa_append_resv(dev, head, lo, pool_start - lo,
                                 IOMMU_RESV_RESERVED))
        return false;
    if (pool_end <= hi &&
        !p470_a2_ipa_append_resv(dev, head, pool_end,
                                 hi - pool_end + 1,
                                 IOMMU_RESV_RESERVED))
        return false;

    dev_info(dev,
             "P470 IPA SMMU cb=%s dma_pool=0x%llx+0x%llx outside_reserved=1 aperture=[0x%llx..0x%llx]\n",
             cb, pool_start, pool_size, lo, hi);
    return true;
}

static void p470_a2_lagoon_ipa_resv(struct device *dev,
                                    struct list_head *head)
{
    const struct iommu_fwspec *fw;
    struct iommu_domain *domain;
    const char *cb;
    u32 sid, mask, expected;
    u32 pool[2], geom[2];
    u64 pool_start = 0, pool_size = 0, limit = 0;
    u64 direct_start = 0, direct_size = 0;
    int ret;

    if (!dev || !dev->of_node)
        return;
    if (of_device_is_compatible(dev->of_node, "qcom,ipa-smmu-ap-cb")) {
        cb = "ap";
        expected = 0x440;
        pool_start = 0x20000000ULL;
        pool_size = 0x40000000ULL;
        limit = 0xF0000000ULL; /* TG qcom,geometry-mapping [0, 0xF0000000) */
        direct_start = 0x146a8000;
        direct_size = 0x2000;
    } else if (of_device_is_compatible(dev->of_node,
                                       "qcom,ipa-smmu-wlan-cb")) {
        cb = "wlan";
        expected = 0x441;
        direct_start = 0x01ea0000;
        direct_size = 0x80000;
    } else if (of_device_is_compatible(dev->of_node,
                                       "qcom,ipa-smmu-uc-cb")) {
        cb = "uc";
        expected = 0x442;
        pool_start = 0x40000000ULL;
        pool_size = 0x20000000ULL;
    } else {
        return;
    }

    fw = dev_iommu_fwspec_get(dev);
    if (!fw || fw->num_ids != 1) {
        dev_err(dev, "P470 IPA SMMU cb=%s invalid fwspec; reservations unavailable\n",
                cb);
        return;
    }
    sid = FIELD_GET(ARM_SMMU_SMR_ID, fw->ids[0]);
    mask = FIELD_GET(ARM_SMMU_SMR_MASK, fw->ids[0]);
    if (sid != expected || mask) {
        dev_err(dev,
                "P470 IPA SMMU cb=%s SID mismatch sid=0x%x mask=0x%x expected=0x%x\n",
                cb, sid, mask, expected);
        return;
    }

    /* The pool belongs to DMA. Reject changed DT sizes or an unexpected
     * AP geometry rather than letting an unscoped reservation run.
     */
    if (pool_size) {
        ret = of_property_read_u32_array(dev->of_node,
                                          "qcom,iommu-dma-addr-pool",
                                          pool, ARRAY_SIZE(pool));
        if (ret || pool[0] != pool_start || pool[1] != pool_size ||
            of_property_count_u32_elems(dev->of_node,
                                         "qcom,iommu-dma-addr-pool") != 2) {
            dev_err(dev, "P470 IPA SMMU cb=%s DMA pool DT mismatch\n", cb);
            return;
        }
    }
    if (sid == 0x440) {
        ret = of_property_read_u32_array(dev->of_node,
                                          "qcom,geometry-mapping",
                                          geom, ARRAY_SIZE(geom));
        if (ret || geom[0] != 0 || geom[1] != limit ||
            of_property_count_u32_elems(dev->of_node,
                                         "qcom,geometry-mapping") != 2) {
            dev_err(dev, "P470 IPA SMMU cb=ap geometry DT mismatch\n");
            return;
        }
    }

    domain = iommu_get_domain_for_dev(dev);
    if (pool_size &&
        !p470_a2_ipa_reserve_complement(dev, head, cb, domain,
                                         pool_start, pool_size, limit))
        return;

    /* Existing TG fixed windows must be preserved DIRECT and identity.
     * These windows are inside the reserved complement, but are mapped
     * once by the IOMMU core, NOT blindly remapped by IPA.
     */
    if (direct_size &&
        !p470_a2_ipa_append_resv(dev, head, direct_start, direct_size,
                                 IOMMU_RESV_DIRECT))
        return;

    dev_info(dev, "P470 IPA SMMU cb=%s sid=0x%03x DIRECT window ready for IOMMU core\n",
             cb, sid);
}

'''


def complement(lo, hi, start, size, cap=None):
    """Reference model using inclusive IOVA aperture endpoints."""
    if cap is not None:
        hi = min(hi, cap - 1)
    end = start + size
    if not size or lo > start or end - 1 > hi:
        raise ValueError("pool outside translated aperture")
    return ([(lo, start - 1)] if lo < start else []) + (
        [(end, hi)] if end <= hi else [])


def transform(s):
    if TAG in s:
        raise RuntimeError("P470-A2c IPA allocator complement already installed")
    if s.count(ANCHOR) != 1 or s.count(CALL) != 1:
        raise RuntimeError("P470-A2c upstream arm-smmu get_resv_regions drift")
    s = s.replace(ANCHOR, INSERT + ANCHOR, 1)
    s = s.replace(CALL, "\tp470_a2_lagoon_ipa_resv(dev, head);\n" + CALL, 1)
    return s


def check(s):
    for token in (TAG, "IOMMU_RESV_DIRECT", "IOMMU_RESV_RESERVED",
                  "p470_a2_ipa_reserve_complement(dev, head, cb, domain,",
                  "pool_start - lo", "hi - pool_end + 1",
                  "pool_end <= hi", "ap_limit_exclusive - 1",
                  "0x146a8000", "0x01ea0000",
                  "pool_start = 0x20000000ULL",
                  "pool_start = 0x40000000ULL",
                  "pool_size = 0x40000000ULL",
                  "pool_size = 0x20000000ULL",
                  "0xF0000000ULL",
                  "FIELD_GET(ARM_SMMU_SMR_ID, fw->ids[0])",
                  "FIELD_GET(ARM_SMMU_SMR_MASK, fw->ids[0])",
                  "outside_reserved=1",
                  "p470_a2_lagoon_ipa_resv(dev, head);", CALL):
        if token not in s:
            raise RuntimeError("P470-A2c allocator source missing " + token)
    if "p470_a2_ipa_append_resv(dev, head, pool_start, pool_size," in s:
        raise RuntimeError("P470-A2c pool itself illegally RESERVED")


def self_test():
    assert complement(0, 0xffffffffffffffff, 0x20000000, 0x40000000,
                      0xF0000000) == [
        (0, 0x1fffffff), (0x60000000, 0xefffffff)]
    assert complement(0, 0xffffffff, 0x40000000, 0x20000000) == [
        (0, 0x3fffffff), (0x60000000, 0xffffffff)]
    assert complement(0x20000000, 0x5fffffff, 0x20000000, 0x40000000) == []
    assert complement(0, 0xffffffffffffffff,
                      0x40000000, 0x20000000)[1][1] == 0xffffffffffffffff
    for lo, hi in complement(0, 0xefffffff, 0x20000000, 0x40000000):
        assert hi < 0x20000000 or lo >= 0x60000000
    try:
        complement(0, 0x5fffffff, 0x40000000, 0x30000000)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid aperture must fail")
    fixture = ANCHOR + "\n{\n" + CALL + "\n}\n"
    check(transform(fixture))
    try:
        transform(transform(fixture))
    except RuntimeError:
        pass
    else:
        raise AssertionError("must refuse repeated SMMU patch")
    print("P470-A2c TG DMA allocator complement selftest PASS")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    if a.self_test:
        self_test()
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
            "phase": "P470-A2c-LAGOON-IPA-DMA-POOL-COMPLEMENT",
            "sids": {"ap": "0x440", "wlan": "0x441", "uc": "0x442"},
            "direct": {"ap": ["0x146a8000", "0x2000"],
                       "wlan": ["0x1ea0000", "0x80000"]},
            "dma_allocator_pools_not_reserved": {
                "ap": ["0x20000000", "0x40000000"],
                "uc": ["0x40000000", "0x20000000"]},
            "reserved_complements": {
                "ap": [["0x0", "0x1fffffff"],
                       ["0x60000000", "0xefffffff"]],
                "uc": "runtime IOMMU aperture minus [0x40000000,0x5fffffff]"},
            "ap_geometry_end_exclusive": "0xF0000000",
            "runtime_acceptance_required": [
                "actual AP/uC dma_map IOVAs inside their allocator-owned pool",
                "zero IPA SID-specific SMMU faults",
                "the final packed DTB matches the pinned CB pools and fixed windows"
            ],
            "allocator_reservation_runtime_confirmed": False,
            "vendor_fastmap_implemented": False,
            "identity_bypass_enabled": False,
            "flashable": False,
        }, indent=2) + "\n")
    print("P470-A2c SID-scoped DMA allocator COMPLEMENT source PASS (NO FLASH)")


if __name__ == "__main__":
    main()
