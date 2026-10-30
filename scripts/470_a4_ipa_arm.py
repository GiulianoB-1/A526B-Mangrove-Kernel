#!/usr/bin/env python3
"""P470-A4: fail-closed Lagoon IPA manual arming and real MSS ready barrier.

Apply only to the ephemeral A3 in-tree experiment, after A3 source staging.
Do not enable IPA DT or publish a boot image from this source-only stage.
Retains donor BUG() assertions: ARM is a dangerous one-shot hardware test.
"""
import argparse
import json
from pathlib import Path

IPA = Path("drivers/platform/msm/ipa/ipa_v3/ipa.c")
PAS = Path("drivers/remoteproc/qcom_q6v5_pas.c")
HDR = Path("include/linux/a52_ipa_arm.h")
TAG = "P470_A4_IPA_ARM_READY_V1"
INCLUDES = r'''#include <linux/capability.h>
#include <linux/completion.h>
#include <linux/device.h>
#include <linux/jiffies.h>
#include <linux/kobject.h>
#include <linux/mutex.h>
#include <linux/qcom_scm.h>
#include <linux/sysfs.h>
'''
HELPERS = r'''
/* P470_A4_IPA_ARM_READY_V1: fail-closed one-shot root-only ARM.
 * Boot defaults disarmed. Deferred master probe is retried only by an
 * explicit /sys/kernel/a52_ipa/enable write from the privileged controller.
 * Keep a device reference so the deferred device cannot be freed.
 * This is NOT a crash-recovery mechanism: donor ipa_assert() still BUG()s.
 */
static atomic_t p470_a4_armed = ATOMIC_INIT(0);
static atomic_t p470_a4_pas15_loaded = ATOMIC_INIT(0);
static DECLARE_COMPLETION(p470_a4_ipa_ready);
static DEFINE_MUTEX(p470_a4_lock);
static struct device *p470_a4_deferred;

int a52_p470_ipa_wait_ready(unsigned long timeout)
{
    if (!of_machine_is_compatible("qcom,lagoon"))
        return 0;
    if (!wait_for_completion_timeout(&p470_a4_ipa_ready, timeout)) {
        pr_err("P470 MSS IPA_WAIT timeout armed=%d pas15=%d rc=-ETIMEDOUT\n",
               atomic_read(&p470_a4_armed),
               atomic_read(&p470_a4_pas15_loaded));
        return -ETIMEDOUT;
    }
    if (!atomic_read(&p470_a4_armed) ||
        !atomic_read(&p470_a4_pas15_loaded)) {
        pr_err("P470 MSS IPA_WAIT forbidden: no PAS15 or arm\n");
        return -EIO;
    }
    pr_info("P470 MSS IPA_WAIT ready=1 pas15=1\n");
    return 0;
}
EXPORT_SYMBOL_GPL(a52_p470_ipa_wait_ready);

static ssize_t p470_a4_arm_store(struct kobject *kobj,
                                struct kobj_attribute *attr,
                                const char *buf, size_t count)
{
    struct device *dev = NULL;
    int ret = 0;

    if (!capable(CAP_SYS_ADMIN))
        return -EPERM;
    if (!sysfs_streq(buf, "1"))
        return -EINVAL;
    if (atomic_cmpxchg(&p470_a4_armed, 0, 1))
        return -EALREADY;
    pr_warn("P470 IPA ARM one_shot=1 authorized=CAP_SYS_ADMIN\n");
    mutex_lock(&p470_a4_lock);
    if (p470_a4_deferred)
        dev = get_device(p470_a4_deferred);
    mutex_unlock(&p470_a4_lock);
    if (dev) {
        ret = device_reprobe(dev);
        put_device(dev);
    }
    if (ret)
        pr_err("P470 IPA ARM reprobe rc=%d (no forced modem boot)\n", ret);
    return count;
}
static struct kobj_attribute p470_a4_enable_attr =
    __ATTR(enable, 0200, NULL, p470_a4_arm_store);

static int __init p470_a4_arm_init(void)
{
    struct kobject *kobj;
    int ret;

    kobj = kobject_create_and_add("a52_ipa", kernel_kobj);
    if (!kobj)
        return -ENOMEM;
    ret = sysfs_create_file(kobj, &p470_a4_enable_attr.attr);
    if (ret) {
        kobject_put(kobj);
        pr_err("P470 IPA ARM knob registration failed rc=%d\n", ret);
        return ret;
    }
    pr_info("P470 IPA ARM initialized disarmed=1 sysfs=0200\n");
    return 0;
}
late_initcall(p470_a4_arm_init);

static int p470_a4_probe_permit(struct device *dev)
{
    if (!of_machine_is_compatible("qcom,lagoon"))
        return 0;
    if (!atomic_read(&p470_a4_armed)) {
        if (of_device_is_compatible(dev->of_node, "qcom,ipa")) {
            mutex_lock(&p470_a4_lock);
            if (!p470_a4_deferred)
                p470_a4_deferred = get_device(dev);
            mutex_unlock(&p470_a4_lock);
        }
        dev_info_once(dev, "P470 IPA PROBE deferred arm=0\n");
        return -EPROBE_DEFER;
    }
    if (!qcom_scm_is_available()) {
        dev_info_once(dev, "P470 IPA PROBE deferred SCM unavailable\n");
        return -EPROBE_DEFER;
    }
    dev_info_once(dev, "P470 IPA PROBE armed=1 scm=available\n");
    return 0;
}
'''
HEADER = r'''/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LINUX_A52_IPA_ARM_H
#define _LINUX_A52_IPA_ARM_H
/* Real completion from the pinned IPA post-init path; no fake ready. */
int a52_p470_ipa_wait_ready(unsigned long timeout_jiffies);
#endif
'''


def once(text, before, after, label):
    n = text.count(before)
    if n != 1:
        raise RuntimeError(f"P470-A4 {label}: pinned anchor count={n}, expected 1")
    return text.replace(before, after, 1)


def transform_ipa(s):
    if TAG in s:
        raise RuntimeError("P470-A4 arm already installed")
    for required in ("P470_A2_TRANSLATED_LAGOON_CB_V2",
                     "P470_A0_COMPILE_ONLY",
                     "void ipa_assert(void)",
                     "subsys_initcall(ipa_module_init);"):
        if required not in s:
            raise RuntimeError("P470-A4 pinned IPA missing: " + required)

    # Insert declaration before post_init (and before all driver callbacks).
    s = once(s, "#include <linux/module.h>",
             "#include <linux/module.h>\n" + INCLUDES,
             "kernel headers")
    s = once(s, "struct ipa3_context *ipa3_ctx = NULL;",
             "struct ipa3_context *ipa3_ctx = NULL;\n" + HELPERS,
             "one-shot safety and API")

    # All paths (master IPA, CBs and SMP2P children) must defer before
    # touching hardware or setting up workqueues.
    anchor = '''\tpr_debug("ipa: IPA driver probing started for %s\\n",
\t\tpdev_p->dev.of_node->name);

'''
    insert = '''\t/* P470 IPA PROBE: never initialize HW until explicitly armed. */
\tresult = p470_a4_probe_permit(dev);
\tif (result)
\t\treturn result;

'''
    s = once(s, anchor, anchor + insert, "probe precondition")

    # Real PAS15 completion only. The donor's DT firmware string is
    # "lagoon_ipa_fws", not "ipa_fws"; do not silently accept two owners.
    load = '''\tipa3_ctx->subsystem_get_retval = subsystem_get(sub_sys);'''
    replacement = '''\tif (of_machine_is_compatible("qcom,lagoon") &&
\t    strcmp(sub_sys, "lagoon_ipa_fws")) {
\t\tpr_err("P470 IPA FW_LOAD reject unexpected PAS15 name=%s\\n",
\t\t       sub_sys);
\t\treturn -EINVAL;
\t}
\tpr_info("P470 IPA FW_LOAD subsystem_get=%s\\n", sub_sys);
\tipa3_ctx->subsystem_get_retval = subsystem_get(sub_sys);'''
    s = once(s, load, replacement, "single firmware subsystem")
    success = '''\tIPADBG("PIL FW loading process is complete sub_sys=%s\\n", sub_sys);'''
    s = once(s, success,
             '''\tif (of_machine_is_compatible("qcom,lagoon")) {
\t\tatomic_set(&p470_a4_pas15_loaded, 1);
\t\tpr_info("P470 IPA FW_LOAD PAS15 acquisition OK name=%s\\n", sub_sys);
\t}
''' + success, "PAS15 loaded success event")
    completion = '''\tcomplete_all(&ipa3_ctx->init_completion_obj);'''
    s = once(s, completion, '''\tif (of_machine_is_compatible("qcom,lagoon")) {
\t\tif (!atomic_read(&p470_a4_pas15_loaded)) {
\t\t\tpr_err("P470 IPA GSI READY blocked: PAS15 not loaded\\n");
\t\t\treturn -EIO;
\t\t}
\t\tpr_info("P470 IPA GSI READY post_init=complete PAS15=1\\n");
\t\tcomplete_all(&p470_a4_ipa_ready);
\t}
''' + completion, "actual GSI post-init completion")
    return s


def transform_pas(s):
    if "P469B MSS AUTO_REBOOT_BLOCK" not in s or "P468 MSS SUBSYS" not in s:
        raise RuntimeError("P470-A4 requires proven P469b modem code")
    if "P470 MSS IPA_WAIT" in s:
        raise RuntimeError("P470-A4 modem ready barrier already installed")
    s = once(s, "#include <linux/remoteproc.h>",
             "#include <linux/remoteproc.h>\n#include <linux/a52_ipa_arm.h>\n#include <linux/jiffies.h>",
             "PAS include")
    start = "static int a52_modem_subsys_powerup(const struct subsys_desc *desc)"
    end = "static int a52_modem_subsys_shutdown(const struct subsys_desc *desc"
    if s.count(start) != 1 or s.count(end) != 1:
        raise RuntimeError("P470-A4 PAS powerup boundaries drifted")
    a, b = s.index(start), s.index(end)
    fn = s[a:b]
    anchor = "    ret = rproc_boot(adsp->rproc);"
    guard = '''    /* P470 MSS IPA_WAIT: only P468's first /dev/subsys_modem open.
     * Do not take a new rproc reference before actual IPA readiness.
     * Timeout leaves P469b manual sysfs start and recovery code unchanged.
     */
    ret = a52_p470_ipa_wait_ready(msecs_to_jiffies(15000));
    if (ret) {
        dev_err(adsp->dev, "P470 MSS IPA_WAIT blocked rc=%d\\n", ret);
        return ret;
    }
'''
    fn = once(fn, anchor, guard + anchor, "P468 first open")
    return s[:a] + fn + s[b:]


def check(root):
    ipa = (root / IPA).read_text()
    pas = (root / PAS).read_text()
    hdr = (root / HDR).read_text()
    required_ipa = (
        TAG, '__ATTR(enable, 0200, NULL, p470_a4_arm_store)',
        'atomic_cmpxchg(&p470_a4_armed, 0, 1)',
        'capable(CAP_SYS_ADMIN)',
        'p470_a4_probe_permit(dev)', 'qcom_scm_is_available()',
        'return -EPROBE_DEFER;', 'device_reprobe(dev)',
        'P470 IPA ARM', 'P470 IPA PROBE',
        'P470 IPA FW_LOAD', 'P470 IPA GSI READY',
        'complete_all(&p470_a4_ipa_ready);',
        'subsystem_get(sub_sys)',
        'strcmp(sub_sys, "lagoon_ipa_fws")',
        'P470_A2_TRANSLATED_LAGOON_CB_V2',
        'BUG();', # explicit risk accepted only after root-only ARM
    )
    required_pas = (
        '#include <linux/a52_ipa_arm.h>',
        'P470 MSS IPA_WAIT',
        'a52_p470_ipa_wait_ready(msecs_to_jiffies(15000));',
        'P469B MSS AUTO_REBOOT_BLOCK',
        'rproc_boot(adsp->rproc)',
    )
    for part, src, tokens in (("IPA", ipa, required_ipa),
                              ("MSS", pas, required_pas),
                              ("HEADER", hdr, ("a52_p470_ipa_wait_ready",))):
        for token in tokens:
            if token not in src:
                raise RuntimeError(f"P470-A4 {part} missing {token}")
    before = ipa.index('result = p470_a4_probe_permit(dev)')
    after = ipa.index('result = get_ipa_dts_configuration(pdev_p')
    if before >= after:
        raise RuntimeError("P470-A4 arm must precede master resource allocation")
    return {
        "phase": "P470-A4-ROOT-ARM-AND-MSS-READY",
        "state": "SOURCE_CHECK_ONLY",
        "root_only_arm": True,
        "one_shot": True,
        "scm_precondition": True,
        "pas15_name": "lagoon_ipa_fws",
        "modem_wait_ms": 15000,
        "real_post_init_completion": True,
        "donor_assert_still_bug": True,
        "hardware_verified": False,
        "flashable": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    if not a.check_only:
        if (a.root / HDR).exists():
            raise RuntimeError("P470-A4 existing header, refusing overwrite")
        (a.root / IPA).write_text(transform_ipa((a.root / IPA).read_text()))
        (a.root / PAS).write_text(transform_pas((a.root / PAS).read_text()))
        (a.root / HDR).write_text(HEADER)
    state = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    print("P470-A4 ARM/SCM/PAS15/MSS readiness source gate PASS; NO FLASH")


if __name__ == "__main__":
    main()
