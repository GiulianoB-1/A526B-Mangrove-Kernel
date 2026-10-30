#!/usr/bin/env python3
"""P470-A4b manual/recovery MSS SSR notifications with legacy de-duplication.

The P468 /dev/subsys_modem wrapper *already emits* legacy SSR notifications.
When that wrapper owns the current rproc start/stop call, skip our core
producer. Manual sysfs rproc state changes and P469b fatal recovery need a
real producer; queue them onto a dedicated ordered worker so callbacks never
run while the rproc lock is held. No modem power or reference changes.
"""
import argparse
import json
from pathlib import Path

CORE = Path("drivers/remoteproc/remoteproc_core.c")
PAS = Path("drivers/remoteproc/qcom_q6v5_pas.c")
MAKE = Path("drivers/remoteproc/Makefile")
TAG = "P470_A4B_MSS_NOTIF_PRODUCER_V1"
HELPER = r'''
/* P470_A4B_MSS_NOTIF_PRODUCER_V1
 * P468's legacy SSR wrapper already publishes start/stop notifications.
 * Only send for manual remoteproc sysfs and real P469b recovery paths.
 * Queue work outside rproc->lock to prevent SRCU notifier callbacks from
 * recursively waiting on the same remoteproc lock.
 */
static struct task_struct *p470_mss_legacy_task;
static struct workqueue_struct *p470_mss_notif_wq;

struct p470_mss_notif_work {
    struct work_struct work;
    enum subsys_notif_type type;
    bool crashed;
    struct device *parent;
};

void a52_p470_mss_legacy_enter(void)
{
    WRITE_ONCE(p470_mss_legacy_task, current);
}
EXPORT_SYMBOL_GPL(a52_p470_mss_legacy_enter);

void a52_p470_mss_legacy_exit(void)
{
    if (READ_ONCE(p470_mss_legacy_task) == current)
        WRITE_ONCE(p470_mss_legacy_task, NULL);
}
EXPORT_SYMBOL_GPL(a52_p470_mss_legacy_exit);

static void p470_mss_notif_workfn(struct work_struct *work)
{
    struct p470_mss_notif_work *task =
        container_of(work, struct p470_mss_notif_work, work);
    void *handle = subsys_notif_add_subsys("modem");
    struct notif_data data = { 0 };
    int ret;

    if (IS_ERR_OR_NULL(handle)) {
        pr_err("P470 MSS NOTIF event=%d missing notifier handle\n",
               task->type);
        goto done;
    }
    data.crashed = task->crashed ?
                   CRASH_STATUS_ERR_FATAL : CRASH_STATUS_NO_CRASH;
    data.enable_ramdump = 0;
    if (task->parent)
        data.pdev = to_platform_device(task->parent);
    ret = subsys_notif_queue_notification(handle, task->type, &data);
    pr_info("P470 MSS NOTIF event=%d producer=remoteproc rc=%d\n",
            task->type, ret);
done:
    if (task->parent)
        put_device(task->parent);
    kfree(task);
}

static void p470_mss_queue_notify(struct rproc *rproc,
                                  enum subsys_notif_type type,
                                  bool crashed)
{
    struct p470_mss_notif_work *task;

    if (!a52_p469_is_mss(rproc) ||
        READ_ONCE(p470_mss_legacy_task) == current)
        return;
    if (!p470_mss_notif_wq) {
        dev_err(&rproc->dev,
                "P470 MSS NOTIF event=%d queue_not_ready\n", type);
        return;
    }
    task = kzalloc(sizeof(*task), GFP_KERNEL);
    if (!task) {
        dev_err(&rproc->dev,
                "P470 MSS NOTIF event=%d no_memory\n", type);
        return;
    }
    task->type = type;
    task->crashed = crashed;
    task->parent = get_device(rproc->dev.parent);
    if (!task->parent) {
        kfree(task);
        return;
    }
    INIT_WORK(&task->work, p470_mss_notif_workfn);
    if (!queue_work(p470_mss_notif_wq, &task->work)) {
        dev_err(&rproc->dev, "P470 MSS NOTIF event=%d queue_rejected\n", type);
        put_device(task->parent);
        kfree(task);
    }
}

static int __init p470_mss_notif_init(void)
{
    p470_mss_notif_wq =
        alloc_ordered_workqueue("p470_mss_notif", WQ_MEM_RECLAIM);
    if (!p470_mss_notif_wq)
        return -ENOMEM;
    pr_info("P470 MSS NOTIF ordered deferred producer ready\n");
    return 0;
}
subsys_initcall(p470_mss_notif_init);
'''
HDR = r'''/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _LINUX_A52_P470_MSS_NOTIF_H
#define _LINUX_A52_P470_MSS_NOTIF_H
void a52_p470_mss_legacy_enter(void);
void a52_p470_mss_legacy_exit(void);
#endif
'''


def once(s, needle, replacement, label):
    n = s.count(needle)
    if n != 1:
        raise RuntimeError(f"P470-A4b notifier {label} anchor count={n}")
    return s.replace(needle, replacement, 1)


def body(s, start, stop):
    if s.count(start) != 1 or s.count(stop) != 1:
        raise RuntimeError("P470-A4b notifier function boundaries changed")
    a = s.index(start)
    b = s.index(stop, a)
    return a, b, s[a:b]


def modify_core(s):
    if TAG in s:
        raise RuntimeError("P470-A4b notifier already applied")
    if "P469 MSS CRASHLOOP_STOP" not in s or "P469B MSS STOP_OFFLINE" not in s:
        raise RuntimeError("P470-A4b requires exact P469b remoteproc core")
    s = once(s, "#include <linux/remoteproc.h>",
             "#include <linux/remoteproc.h>\n"
             "#include <linux/sched.h>\n"
             "#include <linux/workqueue.h>\n"
             "#include <linux/platform_device.h>\n"
             "#include <soc/qcom/subsystem_notif.h>\n"
             "#include <soc/qcom/subsystem_restart.h>",
             "real TG notifier ABI include")
    s = once(s, "static bool a52_p469_is_mss(struct rproc *rproc)",
             HELPER + "\nstatic bool a52_p469_is_mss(struct rproc *rproc)",
             "MSS marker and task-owner helper")
    # The notifier helper precedes a52_p469_is_mss in the C file; forward
    # declaration is needed because the P469 helper follows the insertion.
    s = once(s, "/* P470_A4B_MSS_NOTIF_PRODUCER_V1",
             "static bool a52_p469_is_mss(struct rproc *rproc);\n"
             "/* P470_A4B_MSS_NOTIF_PRODUCER_V1",
             "forward declaration")
    a, b, fragment = body(s, "static int rproc_start(struct rproc *rproc,",
                          "static int rproc_attach(")
    fragment = once(fragment, "\trproc->state = RPROC_RUNNING;",
                    "\trproc->state = RPROC_RUNNING;\n"
                    "\tp470_mss_queue_notify(rproc, SUBSYS_AFTER_POWERUP, false);",
                    "actual RUNNING notification")
    s = s[:a] + fragment + s[b:]
    a, b, fragment = body(s, "static int rproc_stop(struct rproc *rproc,",
                          "int rproc_trigger_recovery(")
    fragment = once(fragment, "\trproc_stop_subdevices(rproc, crashed);",
                    "\tp470_mss_queue_notify(rproc, SUBSYS_BEFORE_SHUTDOWN, crashed);\n"
                    "\trproc_stop_subdevices(rproc, crashed);",
                    "actual remoteproc stop")
    fragment = once(fragment, "\trproc->state = RPROC_OFFLINE;",
                    "\trproc->state = RPROC_OFFLINE;\n"
                    "\tp470_mss_queue_notify(rproc, SUBSYS_AFTER_SHUTDOWN, crashed);",
                    "actual OFFLINE notification")
    s = s[:a] + fragment + s[b:]
    return s


def patch_pas(s):
    if "P470 MSS IPA_WAIT" not in s or "P469B MSS AUTO_REBOOT_BLOCK" not in s:
        raise RuntimeError("P470-A4b notifier requires compiled P470-A4 modem wait")
    s = once(s, "#include <linux/a52_ipa_arm.h>",
             "#include <linux/a52_ipa_arm.h>\n"
             "#include <linux/a52_p470_mss_notif.h>", "PAS header")
    a, b, part = body(s, "static int a52_modem_subsys_powerup(const struct subsys_desc *desc)",
                      "static int a52_modem_subsys_shutdown(")
    part = once(part, "    ret = rproc_boot(adsp->rproc);",
                "    a52_p470_mss_legacy_enter();\n"
                "    ret = rproc_boot(adsp->rproc);\n"
                "    a52_p470_mss_legacy_exit();", "powerup task scope")
    s = s[:a] + part + s[b:]
    # Do not change reference counting or state logic in P469b.
    a = s.index("static int a52_modem_subsys_shutdown(")
    b = s.find("\nstatic ", a + 10)
    if b < 0:
        raise RuntimeError("P470-A4b cannot bound modem shutdown callback")
    part = s[a:b]
    part = once(part, "    rproc_shutdown(adsp->rproc);",
                "    a52_p470_mss_legacy_enter();\n"
                "    rproc_shutdown(adsp->rproc);\n"
                "    a52_p470_mss_legacy_exit();", "shutdown task scope")
    s = s[:a] + part + s[b:]
    return s


def check(root):
    core = (root / CORE).read_text()
    pas = (root / PAS).read_text()
    mk = (root / MAKE).read_text()
    for token in (TAG, "subsys_notif_queue_notification(handle,",
                  "subsys_notif_add_subsys(\"modem\")",
                  "P470 MSS NOTIF event=",
                  "p470_mss_queue_notify(rproc, SUBSYS_AFTER_POWERUP, false)",
                  "p470_mss_queue_notify(rproc, SUBSYS_BEFORE_SHUTDOWN, crashed)",
                  "p470_mss_queue_notify(rproc, SUBSYS_AFTER_SHUTDOWN, crashed)",
                  "alloc_ordered_workqueue(",
                  "READ_ONCE(p470_mss_legacy_task) == current"):
        if token not in core:
            raise RuntimeError("P470-A4b remoteproc notifier missing " + token)
    for token in ("a52_p470_mss_legacy_enter();",
                  "a52_p470_mss_legacy_exit();",
                  "P469B MSS AUTO_REBOOT_BLOCK",
                  "P470 MSS WAIT_TIMEOUT modem_not_started"):
        if token not in pas:
            raise RuntimeError("P470-A4b PAS wrapper notifier missing " + token)
    if core.count("p470_mss_queue_notify(rproc, SUBSYS_AFTER_POWERUP, false);") != 1:
        raise RuntimeError("P470-A4b duplicate SSR ready producer")
    if pas.count("a52_p470_mss_legacy_enter();") != 2:
        raise RuntimeError("P470-A4b need exactly two legacy callback scopes")
    if "CFLAGS_remoteproc_core.o += -I$(srctree)/a52-compat/include" not in mk:
        raise RuntimeError("P470-A4b remoteproc core notifier ABI include missing")
    return {"phase": "P470-A4b-MSS-REMOTE-PRODUCER",
            "actual_mss_states": ["RUNNING", "stop-intent", "OFFLINE"],
            "no_duplicate_p468_first_open_events": True,
            "srcu_handlers_run_from_ordered_workqueue": True,
            "adsp_unmodified": True, "hardware_verified": False,
            "flashable": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    hdr = a.root / "include/linux/a52_p470_mss_notif.h"
    if not a.check_only:
        if hdr.exists():
            raise RuntimeError("P470-A4b header already present")
        (a.root / CORE).write_text(modify_core((a.root / CORE).read_text()))
        (a.root / PAS).write_text(patch_pas((a.root / PAS).read_text()))
        m = a.root / MAKE
        m.write_text(m.read_text().rstrip() +
                     "\n# P470-A4b TG SSR notifier ABI for real MSS remoteproc producer\n"
                     "CFLAGS_remoteproc_core.o += -I$(srctree)/a52-compat/include\n")
        hdr.write_text(HDR)
    data = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("P470-A4b MSS remoteproc notifier source PASS; NO FLASH")


if __name__ == "__main__":
    main()
