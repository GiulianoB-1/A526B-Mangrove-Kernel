#!/usr/bin/env python3
"""P470-A5: reject IPA ARM hardware activation without a REAL bus voter.

Lagoon TG uses the old qcom,msm-bus 5x5 table. The pinned 5.10 donor
get_ipa_dts_pm_info() requires 'interconnects' and of_icc_get() and cannot
vote from the legacy table. This patch validates and logs all 25 vectors
but explicitly BLOCKS IPA hardware activation unless a provider exists.
Logging a DT vector is not voting. Do not replace this with a fake ICC
handle or an always-0 msm-bus shim. First IPA flash stays prohibited.
"""
import argparse
import json
from pathlib import Path

IPA = Path("drivers/platform/msm/ipa/ipa_v3/ipa.c")
TAG = "P470_A5_LEGACY_BUS_NO_SILENT_VOTE_V1"
CHECK = r'''
/* P470_A5_LEGACY_BUS_NO_SILENT_VOTE_V1
 * The DT contains legacy qcom,msm-bus tuples:
 *   <master slave AB_KBps IB_KBps> * five paths * five states.
 * The pinned GKI IPA donor only supports of_icc_get/interconnects.
 * We do NOT interpret MSM_BUS_* IDs as Linux ICC provider node IDs.
 * Conversion without the actual provider topology would be unsafe.
 * No clock, IPA GSI, firmware or SMMU hardware probe may proceed until
 * this source tree supplies a working voter for all five paths.
 */
static int p470_a5_require_bus_backend(struct device *dev)
{
    struct device_node *np = dev->of_node;
    u32 paths = 0, cases = 0, raw[5 * 5 * 4];
    unsigned int state, path;
    int ret;

    if (!of_machine_is_compatible("qcom,lagoon") ||
        !of_device_is_compatible(np, "qcom,ipa"))
        return 0;

    ret = of_property_read_u32(np, "qcom,msm-bus,num-paths", &paths);
    if (ret || paths != 5) {
        dev_err(dev, "P470 IPA BUS BLOCKED num_paths=%u rc=%d\n", paths, ret);
        return -EINVAL;
    }
    ret = of_property_read_u32(np, "qcom,msm-bus,num-cases", &cases);
    if (ret || cases != 5) {
        dev_err(dev, "P470 IPA BUS BLOCKED num_cases=%u rc=%d\n", cases, ret);
        return -EINVAL;
    }
    if (of_property_count_u32_elems(np, "qcom,msm-bus,vectors-KBps") !=
        ARRAY_SIZE(raw)) {
        dev_err(dev, "P470 IPA BUS BLOCKED malformed 5x5x4 vectors\n");
        return -EINVAL;
    }
    ret = of_property_read_u32_array(np, "qcom,msm-bus,vectors-KBps",
                                      raw, ARRAY_SIZE(raw));
    if (ret)
        return ret;
    for (state = 0; state < cases; state++) {
        for (path = 0; path < paths; path++) {
            unsigned int off = (state * paths + path) * 4;
            unsigned int base = path * 4;

            if (raw[off] != raw[base] || raw[off+1] != raw[base+1]) {
                dev_err(dev, "P470 IPA BUS BLOCKED path pair changed state=%u path=%u\n",
                        state, path);
                return -EINVAL;
            }
            if (!state && (raw[off+2] || raw[off+3])) {
                dev_err(dev, "P470 IPA BUS BLOCKED nonzero off vote path=%u\n", path);
                return -EINVAL;
            }
            dev_info(dev,
                     "P470 IPA BUS TABLE state=%u path=%u master=%u slave=%u ab_kBps=%u ib_kBps=%u APPLIED=0\n",
                     state, path, raw[off], raw[off+1],
                     raw[off+2], raw[off+3]);
        }
    }
    if (!of_find_property(np, "interconnects", NULL)) {
        dev_err(dev,
                "P470 IPA BUS BLOCKED legacy_vectors=5x5 interconnects=absent real_msm_bus_backend=not_ported rc=-EOPNOTSUPP\n");
        return -EOPNOTSUPP;
    }
    /* A real ICC provider still has to implement of_icc_get() and votes.
     * The unchanged pinned native IPA driver does that registration and
     * updates all five paths after this check.
     */
    dev_info(dev, "P470 IPA BUS ICC_PROVIDER_REQUIRED path_count=5 real_votes_pending\n");
    return 0;
}
'''


def patch(source):
    if TAG in source:
        raise RuntimeError("P470-A5 bus gate applied twice")
    if "P470 IPA ARM initialized disarmed=1" not in source:
        raise RuntimeError("P470-A5 requires A4 ARM state")
    if 'result = p470_a4_probe_permit(dev);' not in source:
        raise RuntimeError("P470-A5 needs before-hardware IPA probe precondition")
    if "get_ipa_dts_pm_info(struct platform_device" not in source:
        raise RuntimeError("P470-A5 requires pinned ICC-only IPA donor")
    tag = "static int p470_a4_probe_permit(struct device *dev)"
    if source.count(tag) != 1:
        raise RuntimeError("P470-A5 unexpected probe-gate anchor")
    source = source.replace(tag, CHECK + "\n" + tag, 1)
    old = '\tresult = p470_a4_probe_permit(dev);\n\tif (result)\n\t\treturn result;'
    if source.count(old) != 1:
        raise RuntimeError("P470-A5 early IPA gate call not uniquely located")
    source = source.replace(old, old +
        '\n\t/* P470-A5: do not mistake legacy table parsing for real voting. */\n'
        '\tresult = p470_a5_require_bus_backend(dev);\n'
        '\tif (result)\n\t\treturn result;', 1)
    return source


def check(root):
    s = (root / IPA).read_text()
    for x in (TAG, 'P470 IPA BUS TABLE', 'APPLIED=0',
              'P470 IPA BUS BLOCKED legacy_vectors=5x5',
              'real_msm_bus_backend=not_ported',
              'return -EOPNOTSUPP;', 'of_find_property(np, "interconnects"',
              'p470_a5_require_bus_backend(dev)',
              'of_property_count_u32_elems',
              'get_ipa_dts_pm_info(struct platform_device'):
        if x not in s:
            raise RuntimeError("P470-A5 missing bus gate evidence: " + x)
    if s.index("result = p470_a5_require_bus_backend(dev)") >= s.index(
            "result = get_ipa_dts_configuration(pdev_p"):
        raise RuntimeError("P470-A5 bus gate must precede IPA HW resource access")
    return {"phase": "P470-A5-BUS-VOTE-PREACTIVATION",
            "status": "NO_REAL_LEGACY_VOTER_BLOCKED",
            "legacy_vectors": "5 states * 5 paths * 4 fields",
            "dt_table_logging": True,
            "actual_bus_voting": False,
            "default_ipa_arm_off": True,
            "hardware_activation": "denied if legacy-only provider",
            "flashable": False}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--root", type=Path, required=True)
    a.add_argument("--report", type=Path)
    a.add_argument("--check-only", action="store_true")
    x = a.parse_args()
    if not x.check_only:
        f = x.root / IPA
        f.write_text(patch(f.read_text()))
    state = check(x.root)
    if x.report:
        x.report.parent.mkdir(parents=True, exist_ok=True)
        x.report.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    print("P470-A5 BUS preactivation check PASS: real legacy voter MISSING; NO FLASH")


if __name__ == "__main__":
    main()
