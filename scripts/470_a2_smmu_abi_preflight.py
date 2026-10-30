#!/usr/bin/env python3
"""P470-A2 external ABI preflight: replace missing vendor IOMMU get_attr
lookups with truthful GENERIC-DMA checks. Any TG fastmap/bypass request
FAILS CLOSED. This is NOT a fastmap port or production IPA implementation.

Applied after the A1 compiled probe and immediately before the fresh A2
strict build. The successful A1 source and P469b kernel remain untouched.
"""
import argparse
import json
from pathlib import Path

IPA = Path("drivers/platform/msm/ipa/ipa_v3/ipa.c")
MARKER = "P470_A2_IOMMU_UNSUPPORTED_FASTMAP_V1"

HELPER = r"""
/* P470_A2_IOMMU_UNSUPPORTED_FASTMAP_V1
 * A2 compile/link contract only. A vanilla Android 5.10 DMA domain
 * supplies standard IOMMU translation, NOT Qualcomm's fastmap cookie or
 * early-map/atomic/FAST semantics. Do NOT silently say FAST=0 if TG asks
 * for fastmap. For Lagoon that requirement must fail before any mapping.
 * No identity-domain assertion: DOMAIN_ATTR_S1_BYPASS semantics have
 * not been ported. Only standard translated DMA is supported here.
 */
static int p470_a2_get_s1_bypass(struct device *dev,
                                 struct iommu_domain *domain, int *bypass)
{
    const char *mode = NULL;
    int ret;

    if (!dev || !dev->of_node || !domain || !bypass)
        return -EPROBE_DEFER;
    ret = of_property_read_string(dev->of_node, "qcom,iommu-dma", &mode);
    if (!ret) {
        if (strcmp(mode, "default")) {
            dev_err(dev, "P470 IPA SMMU unsupported Qualcomm DMA mode=%s (real FAST/S1 bypass not ported)\\n", mode);
            return -EOPNOTSUPP;
        }
    } else if (ret != -EINVAL && ret != -ENODATA) {
        return ret;
    }
    if (domain->type != IOMMU_DOMAIN_DMA) {
        dev_err(dev, "P470 IPA SMMU unsupported domain type=%u; no identity/bypass claim\\n",
                domain->type);
        return -EOPNOTSUPP;
    }
    *bypass = 0; /* verified generic DMA translation, not identity */
    return 0;
}

static int p470_a2_get_fast(struct device *dev,
                             struct iommu_domain *domain, int *fast)
{
    if (!dev || !domain || !fast)
        return -EINVAL;
    /* p470_a2_get_s1_bypass() already rejected vendor fastmap/atomic
     * requests on this exact CB. Generic DMA is NOT vendor fastmap.
     */
    if (domain->type != IOMMU_DOMAIN_DMA)
        return -EOPNOTSUPP;
    *fast = 0;
    return 0;
}

"""
# The source was staged by 470_compile_real_dataipa_module_probe.sh.
S1 = "iommu_domain_get_attr(cb->iommu_domain, DOMAIN_ATTR_S1_BYPASS, &bypass);"
FAST = "iommu_domain_get_attr(cb->iommu_domain, DOMAIN_ATTR_FAST, &fast);"
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


def patch(src):
    if MARKER in src:
        raise RuntimeError("P470-A2 SMMU donor probe already patched")
    if src.count(S1) != 4 or src.count(FAST) != 3:
        raise RuntimeError("P470-A2 vendor SMMU attr callsite drift "
                           + str((src.count(S1), src.count(FAST))))
    start = "static int ipa_smmu_wlan_cb_probe("
    if src.count(start) != 1:
        raise RuntimeError("P470-A2 WLAN-CB anchor drift")
    # The two replacements leave the A0 guard in place, but the
    # P470_A2_UNSTUBBED compilation takes its actual (non-A0) branch.
    # Unsupported physical fastmap cannot pass even if linking succeeds.
    src = src.replace(S1, S1_SAFE)
    src = src.replace(FAST, FAST_SAFE)
    src = src.replace(start, HELPER + start, 1)
    return src


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--donor", required=True, type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    f = a.donor / IPA
    source = f.read_text()
    patched = patch(source)
    f.write_text(patched)
    data = {
        "phase": "P470-A2-EXTERNAL-IOMMU-ABI",
        "generic_dma_domain_semantics": "translated, bypass=0, fast=0",
        "fastmap_bypass_and_non_dma_domains": "runtime -EOPNOTSUPP",
        "vendor_smmu_features_implemented": False,
        "fastmap_supported": False,
        "built_in": False,
        "strict_post_image_required": True,
        "flashable": False,
        "source_callsites_replaced": {"s1_bypass": 4, "fast": 3}
    }
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("P470-A2 GENERIC DMA QUERY: vendor fastmap and bypass REFUSED; no hardware-ready claim")


if __name__ == "__main__":
    main()
