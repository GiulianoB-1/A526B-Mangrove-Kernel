#!/usr/bin/env python3
"""P469b post-P469 transformer for P469 run 40871537827 (SHA cde98b81).

Keep the two-fatal/300s policy. On the second fatal, do the same rproc_stop()
as regular 5.10 recovery, but do not restart. Keep the valid P468 subsys
power ref until the corresponding subsys_put. Permit a deliberate sysfs
state/start to reuse it without incrementing it. Do not resurrect from a
legacy subsystem_get after crashloop was stopped.
"""
import argparse
import json
from pathlib import Path

CORE = Path("drivers/remoteproc/remoteproc_core.c")
SYSFS = Path("drivers/remoteproc/remoteproc_sysfs.c")
PAS = Path("drivers/remoteproc/qcom_q6v5_pas.c")


def once(s, a, b, label):
    n = s.count(a)
    if n != 1:
        raise RuntimeError("P469b %s: unique anchor count %d" % (label, n))
    return s.replace(a, b, 1)


def sub(s, left, right, label):
    a = s.index(left)
    b = s.index(right, a + len(left))
    return a, b, s[a:b]


def core_patch(s):
    if "P469B MSS STOP_OFFLINE" in s:
        raise RuntimeError("P469b already installed")
    if "P469 MSS CRASHLOOP_STOP" not in s:
        raise RuntimeError("Must apply after P469 on exact G tree")

    a, b, p = sub(s,
        "int rproc_trigger_recovery(struct rproc *rproc)",
        "static void rproc_crash_handler_work(struct work_struct *work)",
        "recovery")
    p = once(p, "\tint ret;\n", "\tint ret = -EINVAL;\n",
             "initialization of nonmatching recovery result")
    s = s[:a] + p + s[b:]

    a, b, p = sub(s,
        "static void rproc_crash_handler_work(struct work_struct *work)",
        "/**\n * rproc_boot()",
        "crash handler")
    p = once(p,
        "\tstruct device *dev = &rproc->dev;\n",
        "\tstruct device *dev = &rproc->dev;\n"
        "\tbool a52_stop_mss = false;\n"
        "\tint a52_stop_rc;\n",
        "crash locals")
    p = once(p,
        '\tdev_err(dev, "handling crash #%u in %s\\n", ++rproc->crash_cnt,\n'
        '\t\trproc->name);\n\n'
        '\tmutex_unlock(&rproc->lock);\n\n'
        '\tif (!READ_ONCE(rproc->recovery_disabled))\n'
        '\t\trproc_trigger_recovery(rproc);\n',
        '\tdev_err(dev, "handling crash #%u in %s\\n", ++rproc->crash_cnt,\n'
        '\t\trproc->name);\n\n'
        '\t/* P469B MSS STOP_OFFLINE: with the rproc lock held, remove\n'
        '\t * the GLINK subdevice/QRTR transport and call the real PAS\n'
        '\t * shutdown. Keep P468 power references for their owners.\n'
        '\t * Only suppress restart. Never pretend PAS stop succeeded.\n'
        '\t */\n'
        '\ta52_stop_mss = a52_p469_is_mss(rproc) &&\n'
        '\t\tREAD_ONCE(rproc->recovery_disabled) &&\n'
        '\t\ta52_mss_fatal_window_count >= 2;\n'
        '\tif (a52_stop_mss) {\n'
        '\t\ta52_stop_rc = rproc_stop(rproc, true);\n'
        '\t\tif (!a52_stop_rc) {\n'
        '\t\t\trproc->ops->coredump(rproc);\n'
        '\t\t\tdev_info(dev,\n'
        '\t\t\t\t "P469B MSS STOP_OFFLINE rc=0 state=%d power=%d restart=skipped\\n",\n'
        '\t\t\t\t rproc->state, atomic_read(&rproc->power));\n'
        '\t\t} else {\n'
        '\t\t\tdev_err(dev,\n'
        '\t\t\t\t"P469B MSS STOP_FAILED rc=%d state=%d power=%d\\n",\n'
        '\t\t\t\ta52_stop_rc, rproc->state,\n'
        '\t\t\t\tatomic_read(&rproc->power));\n'
        '\t\t}\n'
        '\t}\n'
        '\tmutex_unlock(&rproc->lock);\n\n'
        '\tif (!a52_stop_mss && !READ_ONCE(rproc->recovery_disabled))\n'
        '\t\trproc_trigger_recovery(rproc);\n',
        "shutdown on crashloop threshold")
    s = s[:a] + p + s[b:]

    a, b, p = sub(s,
        "void rproc_shutdown(struct rproc *rproc)",
        "EXPORT_SYMBOL(rproc_shutdown);",
        "power release")
    p = once(p,
        "\tret = rproc_stop(rproc, false);\n"
        "\tif (ret) {\n"
        "\t\tatomic_inc(&rproc->power);\n"
        "\t\tgoto out;\n"
        "\t}\n",
        "\t/* P469B MSS LAST_REF: crashloop-stop or failed recovery has\n"
        "\t * already completed rproc_stop(). Do not issue a second\n"
        "\t * Q6v5/PAS shutdown when the final P468 subsys ref drops.\n"
        "\t */\n"
        "\tif (a52_p469_is_mss(rproc) && rproc->state == RPROC_OFFLINE) {\n"
        "\t\tdev_info(dev, \"P469B MSS LAST_REF offline_cleanup power=0\\n\");\n"
        "\t} else {\n"
        "\t\tret = rproc_stop(rproc, false);\n"
        "\t\tif (ret) {\n"
        "\t\t\tatomic_inc(&rproc->power);\n"
        "\t\t\tgoto out;\n"
        "\t\t}\n"
        "\t}\n",
        "offline power-ref cleanup")
    s = s[:a] + p + s[b:]
    return s


def sysfs_patch(s):
    if "P469B MSS MANUAL_START" in s:
        raise RuntimeError("P469b already installed in sysfs")
    a, b, p = sub(s,
        "static ssize_t state_store(struct device *dev,",
        "static DEVICE_ATTR_RW(state);", "sysfs start")
    old = '''\t\t/* P469 MSS START_BLOCKED: a failed recovery can leave
\t\t * RPROC_OFFLINE with live SSR power references. rproc_boot()
\t\t * would increment power and return 0 without PAS start.
\t\t * A manual retry must use recovery/recover instead.
\t\t */
\t\tif (rproc->dev.parent && rproc->dev.parent->of_node &&
\t\t    of_device_is_compatible(rproc->dev.parent->of_node,
\t\t\t\t\t    "qcom,sm6350-mss-pas") &&
\t\t    atomic_read(&rproc->power) > 0) {
\t\t\tdev_err(&rproc->dev,
\t\t\t\t"P469 MSS START_BLOCKED state=%d power=%d use=recovery/recover rc=-EBUSY\\n",
\t\t\t\trproc->state, atomic_read(&rproc->power));
\t\t\treturn -EBUSY;
\t\t}

\t\tret = rproc_boot(rproc);'''
    new = '''\t\t/* P469B MSS MANUAL_START: only a sysfs state/start request
\t\t * may restart an OFFLINE MSS with the P468 ref still held.
\t\t * rproc_trigger_recovery() reuses rproc_start and DOES NOT
\t\t * increment rproc->power. power=0 uses normal rproc_boot.
\t\t * A CRASHED MSS is not eligible for the normal boot path.
\t\t */
\t\tif (rproc->dev.parent && rproc->dev.parent->of_node &&
\t\t    of_device_is_compatible(rproc->dev.parent->of_node,
\t\t\t\t\t    "qcom,sm6350-mss-pas")) {
\t\t\tif (READ_ONCE(rproc->state) == RPROC_CRASHED)
\t\t\t\treturn -EBUSY;
\t\t\tif (READ_ONCE(rproc->state) == RPROC_OFFLINE &&
\t\t\t    atomic_read(&rproc->power) > 0) {
\t\t\t\tret = rproc_trigger_recovery(rproc);
\t\t\t\tdev_info(&rproc->dev,
\t\t\t\t\t"P469B MSS MANUAL_START ref_reuse=1 rc=%d state=%d power=%d\\n",
\t\t\t\t\tret, READ_ONCE(rproc->state),
\t\t\t\t\tatomic_read(&rproc->power));
\t\t\t} else {
\t\t\t\tret = rproc_boot(rproc);
\t\t\t\tdev_info(&rproc->dev,
\t\t\t\t\t"P469B MSS MANUAL_START ref_reuse=0 rc=%d state=%d power=%d\\n",
\t\t\t\t\tret, READ_ONCE(rproc->state),
\t\t\t\t\tatomic_read(&rproc->power));
\t\t\t}
\t\t} else {
\t\t\tret = rproc_boot(rproc);
\t\t}'''
    p = once(p, old, new, "P469 sysfs start replacement")
    s = s[:a] + p + s[b:]
    return s


def pas_patch(s):
    if "P469B MSS AUTO_REBOOT_BLOCK" in s:
        raise RuntimeError("P469b already installed in PAS")
    a, b, p = sub(s,
        "static int a52_modem_subsys_powerup(const struct subsys_desc *desc)",
        "static int a52_modem_subsys_shutdown", "legacy P468 powerup")
    p = once(p,
        "    if (READ_ONCE(adsp->rproc->state) == RPROC_CRASHED)\n"
        "        return -EPIPE;\n"
        "    ret = rproc_boot(adsp->rproc);",
        "    if (READ_ONCE(adsp->rproc->state) == RPROC_CRASHED)\n"
        "        return -EPIPE;\n"
        "    /* P469B MSS AUTO_REBOOT_BLOCK: RILD reopening /dev/subsys_modem\n"
        "     * must not bypass the crashloop guard after the last P468 put.\n"
        "     * Manual /sys/class/remoteproc/.../state start stays available.\n"
        "     */\n"
        "    if (READ_ONCE(adsp->rproc->state) == RPROC_OFFLINE &&\n"
        "        READ_ONCE(adsp->rproc->recovery_disabled)) {\n"
        "        dev_warn(adsp->dev,\n"
        "                 \"P469B MSS AUTO_REBOOT_BLOCK offline=1 rc=-EHOSTDOWN\\n\");\n"
        "        return -EHOSTDOWN;\n"
        "    }\n"
        "    ret = rproc_boot(adsp->rproc);",
        "legacy stop guard")
    s = s[:a] + p + s[b:]
    return s


def audit(core, sysfs, pas):
    for label, s, tokens in (
        ("core", core, ("P469 MSS CRASHLOOP_STOP", "P469B MSS STOP_OFFLINE",
                         "P469B MSS STOP_FAILED", "rproc_stop(rproc, true);",
                         "P469B MSS LAST_REF", "P469 MSS MANUAL_RESTART")),
        ("sysfs", sysfs, ("P469B MSS MANUAL_START", "rproc_trigger_recovery(rproc)",
                           "P469 MSS MANUAL_RECOVER")),
        ("PAS", pas, ("P468 MSS SUBSYS", "P469B MSS AUTO_REBOOT_BLOCK",
                       "P468B MSS SSR SMEM_SKIP" if False else "a52_modem_subsys_powerup")),
    ):
        for t in tokens:
            if t not in s:
                raise RuntimeError("P469b %s missing %s" % (label, t))
    if "P469 MSS START_BLOCKED state=" in sysfs:
        raise RuntimeError("P469b retained fake-error sysfs gate")
    return {"phase":"P469b","baseline_run":40871537827,
            "second_fatal":"rproc_stop(true), coredump, no restart",
            "stop_error":"leave state CRASHED, log nonzero rc",
            "GLINK_QRTR":"rproc subdevices stopped before PAS shutdown",
            "PAS":"real q6v5 stop, no fabricated OFFLINE",
            "manual_state_start":"reuse P468 reference without increment",
            "subsys_reopen":"blocked if offline and recovery disabled",
            "last_subsys_put":"cleanup without double PAS stop",
            "IPA":"unchanged"}


def main():
    pa = argparse.ArgumentParser()
    pa.add_argument("--root", required=True, type=Path)
    pa.add_argument("--report", type=Path)
    pa.add_argument("--check-only", action="store_true")
    a = pa.parse_args()
    fs=((CORE,core_patch),(SYSFS,sysfs_patch),(PAS,pas_patch))
    outputs={}
    for filename, transform in fs:
        dest=a.root/filename
        original=dest.read_text()
        outputs[filename]=original if a.check_only else transform(original)
    report=audit(outputs[CORE],outputs[SYSFS],outputs[PAS])
    if not a.check_only:
        for filename, _ in fs:
            (a.root/filename).write_text(outputs[filename])
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("P469B MSS CLEAN STOP SOURCE PASS "+json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
