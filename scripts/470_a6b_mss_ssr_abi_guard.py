#!/usr/bin/env python3
"""P470-A6b: guard the TG SSR/PAS struct ABI at the module boundary.

A6 #678: SCM enabling wakes MSS deferred probe; P468B SSR register succeeds,
then __dev_printk <- _dev_info <- adsp_probe faults with a small address.
Do not remove the diagnostic or claim the incomplete pstore proves ABI skew.
Use a separately allocated, SSR-provider-sized descriptor, verify sizeof
and offsets, and log through the stable &pdev->dev. No DT/IPA modifications.
Apply only to the disposable post-A6 compiled source, not P469B fallback.
"""
import argparse
import json
from pathlib import Path

TAG = "P470_A6B_SSR_DESC_ABI_PROVIDER_V1"
PAS = Path("drivers/remoteproc/qcom_q6v5_pas.c")
SSR = Path("drivers/a52_pil/subsystem_restart.c")
HDR = Path("include/linux/a52_mss_ssr_abi.h")
HEADER = r'''/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LINUX_A52_MSS_SSR_ABI_H
#define _LINUX_A52_MSS_SSR_ABI_H
#include <linux/stddef.h>

/* Intentionally independent of struct subsys_desc definition. */
struct subsys_desc;
struct a52_ssr_desc_abi {
    size_t size;
    size_t name;
    size_t dev;
    size_t owner;
    size_t powerup;
    size_t shutdown;
    size_t state;
    size_t force_stop_bit;
    size_t err_fatal_irq;
};
struct subsys_desc *a52_p470_ssr_desc_alloc(const struct a52_ssr_desc_abi *caller);
void a52_p470_ssr_desc_free(struct subsys_desc *desc);
#endif
'''
HELPER = r'''
/* P470_A6B_SSR_DESC_ABI_PROVIDER_V1
 * Allocate in the unit that writes the descriptor. Fail closed if the PAS
 * caller sees a different layout (including fields written during DT parse).
 * Do not embed a variable-sized TG descriptor in qcom_adsp->rproc->priv.
 */
struct subsys_desc *a52_p470_ssr_desc_alloc(const struct a52_ssr_desc_abi *caller)
{
    struct a52_ssr_desc_abi provider = {
        .size = sizeof(struct subsys_desc),
        .name = offsetof(struct subsys_desc, name),
        .dev = offsetof(struct subsys_desc, dev),
        .owner = offsetof(struct subsys_desc, owner),
        .powerup = offsetof(struct subsys_desc, powerup),
        .shutdown = offsetof(struct subsys_desc, shutdown),
        .state = offsetof(struct subsys_desc, state),
        .force_stop_bit = offsetof(struct subsys_desc, force_stop_bit),
        .err_fatal_irq = offsetof(struct subsys_desc, err_fatal_irq),
    };

    if (!caller)
        return ERR_PTR(-EINVAL);
    pr_info("P470-A6b SSR ABI PAS size=%zu name=%zu dev=%zu owner=%zu powerup=%zu shutdown=%zu state=%zu force=%zu irq=%zu\n",
            caller->size, caller->name, caller->dev, caller->owner,
            caller->powerup, caller->shutdown, caller->state,
            caller->force_stop_bit, caller->err_fatal_irq);
    pr_info("P470-A6b SSR ABI TG size=%zu name=%zu dev=%zu owner=%zu powerup=%zu shutdown=%zu state=%zu force=%zu irq=%zu\n",
            provider.size, provider.name, provider.dev, provider.owner,
            provider.powerup, provider.shutdown, provider.state,
            provider.force_stop_bit, provider.err_fatal_irq);
    if (caller->size != provider.size ||
        caller->name != provider.name ||
        caller->dev != provider.dev ||
        caller->owner != provider.owner ||
        caller->powerup != provider.powerup ||
        caller->shutdown != provider.shutdown ||
        caller->state != provider.state ||
        caller->force_stop_bit != provider.force_stop_bit ||
        caller->err_fatal_irq != provider.err_fatal_irq) {
        pr_err("P470-A6b SSR ABI MISMATCH: refusing modem char shim\n");
        return ERR_PTR(-EPROTO);
    }
    return kzalloc(sizeof(struct subsys_desc), GFP_KERNEL);
}
EXPORT_SYMBOL_GPL(a52_p470_ssr_desc_alloc);

void a52_p470_ssr_desc_free(struct subsys_desc *desc)
{
    kfree(desc);
}
EXPORT_SYMBOL_GPL(a52_p470_ssr_desc_free);
'''
ABI_C = r'''{
        .size = sizeof(struct subsys_desc),
        .name = offsetof(struct subsys_desc, name),
        .dev = offsetof(struct subsys_desc, dev),
        .owner = offsetof(struct subsys_desc, owner),
        .powerup = offsetof(struct subsys_desc, powerup),
        .shutdown = offsetof(struct subsys_desc, shutdown),
        .state = offsetof(struct subsys_desc, state),
        .force_stop_bit = offsetof(struct subsys_desc, force_stop_bit),
        .err_fatal_irq = offsetof(struct subsys_desc, err_fatal_irq),
    }'''


def once(s, old, new, reason):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"A6b {reason}: expected 1 anchor, got {count}")
    return s.replace(old, new, 1)


def patch_ssr(s):
    if TAG in s:
        raise RuntimeError("A6b SSR already patched")
    s = once(s, '#include <soc/qcom/subsystem_restart.h>',
             '#include <soc/qcom/subsystem_restart.h>\n'
             '#include <linux/a52_mss_ssr_abi.h>\n'
             '#include <linux/err.h>\n'
             '#include <linux/slab.h>', "SSR provider includes")
    s = once(s, 'struct subsys_device *subsys_register(struct subsys_desc *desc)',
             HELPER + '\nstruct subsys_device *subsys_register(struct subsys_desc *desc)',
             "SSR provider allocation before registration")
    return s


def patch_pas(s):
    if TAG in s:
        raise RuntimeError("A6b PAS already patched")
    s = once(s, '#include <soc/qcom/subsystem_restart.h>',
             '#include <soc/qcom/subsystem_restart.h>\n'
             '#include <linux/a52_mss_ssr_abi.h>', "PAS ABI include")
    s = once(s, '\tstruct subsys_desc a52_modem_ssr_desc;',
             '\tstruct subsys_desc *a52_modem_ssr_desc;',
             "do not embed SSR descriptor before PAS dev")
    # Both callbacks use the PAS driver's already-published platform drvdata,
    # not container_of(desc) (which relied on the formerly embedded layout).
    old = '''struct qcom_adsp *adsp = container_of(desc, struct qcom_adsp,
                                         a52_modem_ssr_desc);'''
    new = '''struct qcom_adsp *adsp;

    if (!desc || !desc->dev)
        return -ENODEV;
    adsp = dev_get_drvdata(desc->dev);
    if (!adsp || adsp->a52_modem_ssr_desc != desc ||
        adsp->dev != desc->dev || !adsp->rproc)
        return -ENODEV;'''
    if s.count(old) != 2:
        raise RuntimeError(f"A6b MSS callback context anchor count {s.count(old)}")
    s = s.replace(old, new, 2)

    anchor = '''    if (desc->a52_mss_rails) {
        struct subsys_desc *ssr = &adsp->a52_modem_ssr_desc;

        ssr->name = "modem";'''
    replacement = '''    if (desc->a52_mss_rails) {
        /* A6b: P468B char shim is optional, PAS rproc stays alive if ABI
         * differs. Allocate from the actual SSR provider translation unit.
         */
        const struct a52_ssr_desc_abi caller_abi = ''' + ABI_C + ''';
        struct subsys_desc *ssr;

        dev_info(&pdev->dev,
                 "P470-A6b PAS ABI qcom_adsp_size=%zu dev_offset=%zu ssr_ptr_offset=%zu\\n",
                 sizeof(*adsp), offsetof(struct qcom_adsp, dev),
                 offsetof(struct qcom_adsp, a52_modem_ssr_desc));
        ssr = a52_p470_ssr_desc_alloc(&caller_abi);
        if (IS_ERR_OR_NULL(ssr)) {
            int abi_err = IS_ERR(ssr) ? PTR_ERR(ssr) : -ENOMEM;

            dev_err(&pdev->dev,
                    "P470-A6b MSS SSR ABI reject rc=%d P467_PAS_PRESERVED\\n",
                    abi_err);
            adsp->a52_modem_ssr_desc = NULL;
            adsp->a52_modem_ssr = NULL;
        } else {
        adsp->a52_modem_ssr_desc = ssr;
        ssr->name = "modem";'''
    s = once(s, anchor, replacement, "allocate real provider-owned descriptor")

    # Stable dev logging also on error; in the success branch the original
    # dev_info(adsp->dev) faulted on A6 immediately after subsys_register().
    original = '''            adsp->a52_modem_ssr = NULL;
            /* Preserve the proven P467 PAS even if optional RIL ABI fails. */
            dev_err(adsp->dev,
              "P468 MSS SUBSYS REGISTER failed=%d P467_PAS_PRESERVED\\n", err);
        } else {
            dev_info(adsp->dev,
              "P468 MSS SUBSYS REGISTER name=modem dev=subsys_modem rproc=%s rc=0\\n",
              rproc->name);
        }
    }
\treturn 0;'''
    replacement = '''            adsp->a52_modem_ssr = NULL;
            /* No client owns a failed registration. */
            a52_p470_ssr_desc_free(ssr);
            adsp->a52_modem_ssr_desc = NULL;
            dev_err(&pdev->dev,
              "P468 MSS SUBSYS REGISTER failed=%d P467_PAS_PRESERVED\\n", err);
        } else {
            dev_info(&pdev->dev,
              "P468 MSS SUBSYS REGISTER name=modem dev=subsys_modem rproc=%s rc=0\\n",
              rproc->name);
        }
        } /* ABI-matched descriptor allocation */
    }
\treturn 0;'''
    s = once(s, original, replacement, "log stability and register cleanup")

    old_remove = '''\tif (adsp->a52_modem_ssr) {
\t\tsubsys_unregister(adsp->a52_modem_ssr);
\t}
\trproc_del(adsp->rproc);'''
    new_remove = '''\tif (adsp->a52_modem_ssr) {
\t\tsubsys_unregister(adsp->a52_modem_ssr);
\t\tadsp->a52_modem_ssr = NULL;
\t}
\ta52_p470_ssr_desc_free(adsp->a52_modem_ssr_desc);
\tadsp->a52_modem_ssr_desc = NULL;
\trproc_del(adsp->rproc);'''
    s = once(s, old_remove, new_remove, "SSR descriptor lifetime")
    # Inspect and report at runtime without any dereference of adsp->dev.
    return s


def check(root):
    pas = (root / PAS).read_text()
    ssr = (root / SSR).read_text()
    header = (root / HDR).read_text()
    tokens = (
        "P470-A6b SSR ABI PAS size=", "P470-A6b SSR ABI TG size=",
        "P470-A6b SSR ABI MISMATCH", "a52_p470_ssr_desc_alloc",
        "EXPORT_SYMBOL_GPL(a52_p470_ssr_desc_alloc);",
        "a52_p470_ssr_desc_free",
        "EXPORT_SYMBOL_GPL(a52_p470_ssr_desc_free);",
    )
    for token in tokens:
        if token not in ssr:
            raise RuntimeError("A6b SSR missing " + token)
    if "struct subsys_desc a52_modem_ssr_desc;" in pas:
        raise RuntimeError("A6b still embeds downstream descriptor in qcom_adsp")
    for token in (
        "struct subsys_desc *a52_modem_ssr_desc;",
        "P470-A6b MSS SSR ABI reject",
        "P470-A6b PAS ABI qcom_adsp_size=",
        "adsp = dev_get_drvdata(desc->dev);",
        "a52_p470_ssr_desc_alloc(&caller_abi)",
        "a52_p470_ssr_desc_free(adsp->a52_modem_ssr_desc)",
        "dev_info(&pdev->dev,\n              \"P468 MSS SUBSYS REGISTER",
        "P470 MSS WAIT_TIMEOUT modem_not_started",
        "a52_p470_mss_legacy_enter();",
    ):
        if token not in pas:
            raise RuntimeError("A6b PAS missing " + repr(token))
    if pas.count("adsp = dev_get_drvdata(desc->dev);") != 2:
        raise RuntimeError("A6b both TG SSR callbacks must use guarded drvdata")
    if "struct a52_ssr_desc_abi" not in header:
        raise RuntimeError("A6b ABI header missing")
    return {
        "phase": "P470-A6b-MSS-SSR-PROBE-OOPS",
        "source_layout_guard": True,
        "provider_unit_allocation": True,
        "pas_ssr_descriptor_embedded": False,
        "layout_fields_compared": ["size","name","dev","owner","powerup",
                                   "shutdown","state","force_stop_bit","err_fatal_irq"],
        "mss_probe_log_uses_platform_dev": True,
        "pas_preserved_on_abi_mismatch": True,
        "a6_rpmh_bus_preserved": True,
        "hardware_oops_resolved": False,
        "flash_authorized": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    if not a.check_only:
        target = a.root / HDR
        if target.exists():
            raise RuntimeError("A6b ABI header collision")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(HEADER)
        f = a.root / SSR
        f.write_text(patch_ssr(f.read_text()))
        f = a.root / PAS
        f.write_text(patch_pas(f.read_text()))
    result = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("P470-A6b MSS SSR provider/PAS ABI guard source PASS; hardware Oops unverified")


if __name__ == "__main__":
    main()
