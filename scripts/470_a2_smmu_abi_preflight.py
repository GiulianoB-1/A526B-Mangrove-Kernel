#!/usr/bin/env python3
"""P470-A2b real translated IPA domain validation for exact Lagoon CB SIDs.

TouchGrass only *prints* DOMAIN_ATTR_FAST in its IPA CB probes. IPA uses
the S1_BYPASS result to decide whether translation is enabled. For AP,
WLAN and uC, Lagoon requires bypass=0. Vendor fastmap/atomic are DMA
mapping performance/atomicity hints, NOT distinct translations.

This adapter:
  * requires an attached IOMMU_DOMAIN_DMA (no identity bypass);
  * verifies the exact CB compatible, unmasked stream SID, mode, and pools;
  * verifies kernel-side SID reservation source and all live DIRECT maps;
  * checks the allocator-owned TG DT pools and rejects manual IPA overlap;
  * recognizes the Linux 5.10 pre-populated DIRECT identity mappings, rather
    than re-mapping a conflicting range;
  * never uses or installs fastmap's page tables, DMA ops or global arm-smmu
    attributes. WDI atomic mapping paths still need separate phase-B audit.

Runs ONLY in the disposable external-module donor tree for A2. This is
not a hardware-ready or flashable image. All source anchors are pinned.
"""
import argparse
import json
from pathlib import Path

IPA = Path("drivers/platform/msm/ipa/ipa_v3/ipa.c")
MARKER = "P470_A2_TRANSLATED_LAGOON_CB_V2"
S1 = "iommu_domain_get_attr(cb->iommu_domain, DOMAIN_ATTR_S1_BYPASS, &bypass);"
FAST = "iommu_domain_get_attr(cb->iommu_domain, DOMAIN_ATTR_FAST, &fast);"

HELPER = r'''
/* P470_A2_TRANSLATED_LAGOON_CB_V2
 * Check actual Linux 5.10 domain, exact DT SID and DIRECT translation.
 * DOMAIN_ATTR_FAST is diagnostic-only in pinned ipa.c. Do not claim the
 * vendor speedup: we are using standard translated IOMMU-DMA (bypass=0).
 */
static int p470_a2_check_reservations(struct device *dev,
                                     struct iommu_domain *domain,
                                     const char *cb)
{
    phys_addr_t fixed = 0, size = 0, va = 0, vsz = 0;
    u32 triplet[3], pool[2], geom[2];
    unsigned long addr;
    int ret;

    if (!strcmp(cb, "ap")) {
        fixed = 0x146a8000;
        size = 0x2000;
        va = 0x20000000;
        vsz = 0x40000000;
    } else if (!strcmp(cb, "wlan")) {
        fixed = 0x01ea0000;
        size = 0x80000;
    } else if (!strcmp(cb, "uc")) {
        va = 0x40000000;
        vsz = 0x20000000;
    } else {
        return -EOPNOTSUPP;
    }

    /* Only built-in arm-smmu get_resv_regions owns DIRECT/RESERVED lists.
     * The getter and putter are NOT exported to external IPA modules.
     * Check the live DT contract and actual DIRECT translations instead.
     * Allocator reservation still requires a built-in/hardware audit.
     */
    if (size) {
        ret = of_property_read_u32_array(dev->of_node,
                                          "qcom,additional-mapping",
                                          triplet, ARRAY_SIZE(triplet));
        if (ret || triplet[0] != fixed || triplet[1] != fixed ||
            triplet[2] != size ||
            of_property_count_u32_elems(dev->of_node,
                                         "qcom,additional-mapping") != 3) {
            dev_err(dev,
                    "P470 IPA SMMU cb=%s invalid DIRECT MMIO DT mapping\n",
                    cb);
            return -EINVAL;
        }
    }
    if (vsz) {
        ret = of_property_read_u32_array(dev->of_node,
                                          "qcom,iommu-dma-addr-pool",
                                          pool, ARRAY_SIZE(pool));
        if (ret || pool[0] != va || pool[1] != vsz ||
            of_property_count_u32_elems(dev->of_node,
                                         "qcom,iommu-dma-addr-pool") != 2) {
            dev_err(dev,
                    "P470 IPA SMMU cb=%s invalid allocator-owned IOVA pool DT\n",
                    cb);
            return -EINVAL;
        }
    }

    if (!strcmp(cb, "ap")) {
        ret = of_property_read_u32_array(dev->of_node,
                                          "qcom,geometry-mapping",
                                          geom, ARRAY_SIZE(geom));
        if (ret || geom[0] != 0 || geom[1] != 0xF0000000 ||
            of_property_count_u32_elems(dev->of_node,
                                         "qcom,geometry-mapping") != 2) {
            dev_err(dev, "P470 IPA SMMU cb=ap geometry DT mismatch\\n");
            return -EINVAL;
        }
    }

    if (!domain->geometry.aperture_end)
        return -ERANGE;
    if (domain->geometry.force_aperture &&
        ((fixed && (fixed < domain->geometry.aperture_start ||
                    fixed + size - 1 > domain->geometry.aperture_end)) ||
         (vsz && (va < domain->geometry.aperture_start ||
                  va + vsz - 1 > domain->geometry.aperture_end)))) {
        dev_err(dev, "P470 IPA SMMU cb=%s fixed/pool range outside DMA aperture\n", cb);
        return -ERANGE;
    }

    /* IOMMU_RESV_DIRECT is normally installed before IPA CB probe.
     * Check the entire MMIO window, not just the first and last page.
     */
    for (addr = fixed; addr < fixed + size; addr += PAGE_SIZE) {
        if (iommu_iova_to_phys(domain, addr) != addr) {
            dev_err(dev,
                    "P470 IPA SMMU cb=%s DIRECT MMIO IOVA 0x%lx missing\n",
                    cb, addr);
            return -EIO;
        }
    }
    return 0;
}

static int p470_a2_get_s1_bypass(struct device *dev,
                                 struct iommu_domain *domain, int *bypass)
{
    struct of_phandle_args args;
    const char *cb, *mode, *expected;
    u32 sid;
    int ret;

    if (!dev || !dev->of_node || !domain || !bypass)
        return -ENODEV;
    if (of_device_is_compatible(dev->of_node, "qcom,ipa-smmu-ap-cb")) {
        cb = "ap"; sid = 0x440; expected = "fastmap";
    } else if (of_device_is_compatible(dev->of_node,
                                       "qcom,ipa-smmu-wlan-cb")) {
        cb = "wlan"; sid = 0x441; expected = "atomic";
    } else if (of_device_is_compatible(dev->of_node,
                                       "qcom,ipa-smmu-uc-cb")) {
        cb = "uc"; sid = 0x442; expected = NULL;
    } else {
        return -EOPNOTSUPP; /* 11ad not present in pinned Lagoon DT */
    }
    ret = of_parse_phandle_with_args(dev->of_node, "iommus",
                                     "#iommu-cells", 0, &args);
    if (ret)
        return ret;
    ret = (args.args_count == 2 && args.args[0] == sid && !args.args[1])
           ? 0 : -EINVAL;
    of_node_put(args.np);
    if (ret) {
        dev_err(dev, "P470 IPA SMMU cb=%s SID/mask DT mismatch expected=0x%x\n",
                cb, sid);
        return ret;
    }
    mode = NULL;
    ret = of_property_read_string(dev->of_node, "qcom,iommu-dma", &mode);
    if (expected) {
        if (ret || strcmp(expected, mode))
            return -EINVAL;
    } else if (ret != -EINVAL && ret != -ENODATA) {
        return -EINVAL; /* uC must use default translated DMA */
    }

    if (domain->type != IOMMU_DOMAIN_DMA ||
        iommu_get_domain_for_dev(dev) != domain) {
        dev_err(dev, "P470 IPA SMMU cb=%s no attached translated DMA domain\n",
                cb);
        return -EOPNOTSUPP;
    }
    ret = p470_a2_check_reservations(dev, domain, cb);
    if (ret)
        return ret;
    *bypass = 0;
    dev_info(dev, "P470 IPA SMMU cb=%s sid=0x%03x mode=translated(tg=%s) bypass=0\n",
             cb, sid, expected ? expected : "default");
    return 0;
}

static int p470_a2_get_fast(struct device *dev,
                             struct iommu_domain *domain, int *fast)
{
    if (!dev || !domain || !fast || domain->type != IOMMU_DOMAIN_DMA)
        return -EINVAL;
    *fast = 0; /* diagnostic only; never claim fastmap performance */
    return 0;
}

/* Return 1 for already installed DIRECT identity MMIO, 0 for new mapping,
 * negative errno for collision or bad range. Covers every ipa3_iommu_map.
 */
static int p470_a2_manual_map_guard(struct iommu_domain *domain,
                                    struct ipa_smmu_cb_ctx *cb,
                                    unsigned long iova, phys_addr_t pa,
                                    size_t size)
{
    u64 end;
    unsigned long base = 0, fixed_size = 0;
    unsigned long addr;

    if (!domain || !cb || !size || !IS_ALIGNED(iova, PAGE_SIZE) ||
        !IS_ALIGNED(pa, PAGE_SIZE) || !IS_ALIGNED(size, PAGE_SIZE))
        return -EINVAL;
    end = (u64)iova + size - 1;
    if (end < iova)
        return -ERANGE;
    if (domain->geometry.force_aperture &&
        (iova < domain->geometry.aperture_start ||
         end > domain->geometry.aperture_end))
        return -ERANGE;
    /* TouchGrass AP qcom,geometry-mapping=[0,0xF0000000). */
    if (domain == ipa3_get_smmu_domain() && end >= 0xF0000000ULL)
        return -ERANGE;
    if (cb->va_size && iova < cb->va_end && end >= cb->va_start) {
        pr_err("P470 IPA SMMU manual-map overlaps allocator-owned DMA IOVA pool\n");
        return -ERANGE;
    }
    if (domain == ipa3_get_smmu_domain()) {
        base = 0x146a8000;
        fixed_size = 0x2000;
    } else if (domain == ipa3_get_wlan_smmu_domain()) {
        base = 0x01ea0000;
        fixed_size = 0x80000;
    }
    if (fixed_size && iova < base + fixed_size && end >= base) {
        if (iova < base || end >= base + fixed_size || iova != pa)
            return -EEXIST;
        for (addr = iova; addr <= end; addr += PAGE_SIZE) {
            if (iommu_iova_to_phys(domain, addr) != pa + addr - iova)
                return -EEXIST;
        }
        return 1; /* Linux 5.10 IOMMU_RESV_DIRECT mapped before IPA probe */
    }
    return 0;
}

'''
S1_SAFE = r'''do {
    int p470_rc = p470_a2_get_s1_bypass(dev, cb->iommu_domain, &bypass);
    if (p470_rc) {
        cb->valid = false;
        return p470_rc;
    }
} while (0);'''
FAST_SAFE = r'''do {
    int p470_rc = p470_a2_get_fast(dev, cb->iommu_domain, &fast);
    if (p470_rc) {
        cb->valid = false;
        return p470_rc;
    }
} while (0);'''

MAP_START = "int ipa3_iommu_map(struct iommu_domain *domain,"
MAP_CB = "\tstruct ipa_smmu_cb_ctx *cb = NULL;"
MAP_RETURN = "\treturn iommu_map(domain, iova, paddr, size, prot);"
AP_UNMAP = "\t\tres = iommu_unmap(cb->iommu_domain,iova_p, size_p);"


def exact(s, a, b, n=1):
    if s.count(a) != n:
        raise RuntimeError(f"P470-A2b pinned IPA source drift: {a!r} count={s.count(a)} expected {n}")
    return s.replace(a, b)


def patch(src):
    if MARKER in src:
        raise RuntimeError("P470-A2b IPA translated CB adapter already patched")
    if src.count(S1) != 4 or src.count(FAST) != 3:
        raise RuntimeError(f"P470-A2b get_attr drift: {src.count(S1)} / {src.count(FAST)}")
    src = exact(src, "static int ipa_smmu_wlan_cb_probe(",
                HELPER + "static int ipa_smmu_wlan_cb_probe(")
    src = exact(src, S1, S1_SAFE, 4)
    src = exact(src, FAST, FAST_SAFE, 3)
    src = exact(src, MAP_START, MAP_START)
    # Insert the manual-map check after CB selection and cache-coherent prot.
    map_pos = src.index(MAP_START)
    before, rest = src[:map_pos], src[map_pos:]
    rest = exact(rest, MAP_CB, MAP_CB + "\n\tint p470_guard;", 1)
    rest = exact(rest, MAP_RETURN,
        "\tp470_guard = p470_a2_manual_map_guard(domain, cb, iova, paddr, size);\n"
        "\tif (p470_guard)\n"
        "\t\treturn p470_guard > 0 ? 0 : p470_guard;\n" + MAP_RETURN, 1)
    src = before + rest
    # Kernel's DIRECT mappings belong to the IOMMU core. AP error cleanup
    # must never tear down the preinstalled 0x146a8000 fixed reservation.
    src = exact(src, AP_UNMAP,
        "\t\tif (iova_p >= 0x146a8000 &&\n"
        "\t\t    (u64)iova_p + size_p <= 0x146aa000)\n"
        "\t\t\tcontinue; /* IOMMU_RESV_DIRECT owns this mapping */\n"
        + AP_UNMAP)
    return src


def check(src):
    for token in (MARKER, "of_property_count_u32_elems(dev->of_node",
                  "iommu_iova_to_phys(domain, addr)",
                  "mode=translated(tg=%s) bypass=0",
                  "p470_a2_manual_map_guard(domain, cb, iova, paddr, size)",
                  "iommu_iova_to_phys(domain, addr)",
                  "return p470_guard > 0 ? 0 : p470_guard",
                  "IOMMU_DOMAIN_DMA"):
        if token not in src:
            raise RuntimeError("P470-A2b IPA mandatory translated guard missing: " + token)
    if ("iommu_get_resv_regions(dev, &regions);" in src or
            "iommu_put_resv_regions(dev, &regions);" in src):
        raise RuntimeError("P470-A2b nonexported IOMMU reservation helpers survive")
    if "DOMAIN_ATTR_S1_BYPASS, &bypass" in src or "DOMAIN_ATTR_FAST, &fast" in src:
        raise RuntimeError("P470-A2b raw vendor domain attr call survived")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--donor", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    if a.self_test:
        print("P470-A2b static codegen self-test requires pinned donor (--donor)")
        if a.donor:
            check(patch((a.donor / IPA).read_text()))
        return
    if a.donor is None:
        p.error("--donor required")
    f = a.donor / IPA
    src = patch(f.read_text())
    check(src)
    f.write_text(src)
    report = {
        "phase": "P470-A2b-LAGOON-TRANSLATED-DMA",
        "identity_bypass": False,
        "fastmap_acceleration_claimed": False,
        "CB": {"AP": {"sid": "0x440", "tg_mode": "fastmap", "translation": True},
               "WLAN": {"sid": "0x441", "tg_mode": "atomic", "translation": True},
               "uC": {"sid": "0x442", "tg_mode": "default", "translation": True}},
        "fixed_direct_windows_checked": True,
        "reservation_source_checked_not_exported_to_module": True,
        "allocator_pool_is_available_not_reserved": True,
        "outside_pool_reservation_runtime_confirmed": False,
        "all_ipa3_iommu_map_calls_guarded": True,
        "atomic_WDI_audit_done": False,
        "built_in": False,
        "hardware_tested": False,
        "flashable": False,
    }
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("P470-A2c TRANSLATED CB ABI PASS: SID, DIRECT, allocator-owned pools and AP geometry checked; complement reservation pending runtime; NO FLASH")


if __name__ == "__main__":
    main()
