#!/usr/bin/env python3
"""P469: Q6v5 MSS fatal crashloop stop and truthful manual retry after timeout.

Use only after the proven P468b P467-based source chain.
No PAS, SMEM, DTB, FastRPC, charger, or non-MSS remoteproc policy changes.
"""
import argparse
import json
from pathlib import Path

CORE = Path("drivers/remoteproc/remoteproc_core.c")
SYSFS = Path("drivers/remoteproc/remoteproc_sysfs.c")
TAG = "P469 MSS"


def once(s, a, b, why):
    n = s.count(a)
    if n != 1:
        raise RuntimeError(f"P469 {why}: expected one anchor, found {n}")
    return s.replace(a, b, 1)


def patch_core(s):
    if "P469 MSS CRASHLOOP_STOP" in s:
        raise RuntimeError("P469 crashloop patch applied twice")
    if 'static void rproc_crash_handler_work(struct work_struct *work)' not in s:
        raise RuntimeError("P469 missing 5.10 remoteproc crash handler")
    # This is a single SM6350 MSS rproc. Fatal IRQ calls rproc_report_crash
    # and the workqueue folds multiple IRQ reports into one crash episode.
    # Count only consumed fatal notifications, *not* watchdogs or queued
    # duplicate reports while already RPROC_CRASHED.
    marker = 'static struct workqueue_struct *rproc_recovery_wq;\n'
    helper = r'''
/* P469 MSS CRASHLOOP_STOP: the Q6v5 fatal IRQ may be raised more than
 * once for an episode. Consume at most one fatal in its crash work item.
 * Both counters below are accessed only under rproc->lock by the single
 * SM6350 MSS rproc; the IRQ-facing atomic has no sleeping lock.
 */
static atomic_t a52_mss_fatal_pending = ATOMIC_INIT(0);
static unsigned long a52_mss_fatal_window_start;
static unsigned int a52_mss_fatal_window_count;

static bool a52_p469_is_mss(struct rproc *rproc)
{
	return rproc && rproc->dev.parent &&
		rproc->dev.parent->of_node &&
		of_device_is_compatible(rproc->dev.parent->of_node,
				       "qcom,sm6350-mss-pas");
}

'''
    s = once(s, marker, marker + helper, "MSS helper")
    marker = '''\tif (rproc->state == RPROC_CRASHED) {
\t\t/* handle only the first crash detected */'''
    added = '''\tif (rproc->state == RPROC_CRASHED) {
\t\t/* P469 MSS: discard any duplicate fatal IRQ notifications. */
\t\tif (a52_p469_is_mss(rproc))
\t\t\tatomic_set(&a52_mss_fatal_pending, 0);
\t\t/* handle only the first crash detected */'''
    s = once(s, marker, added, "crashed state duplicate")
    marker = '''\tif (rproc->state == RPROC_OFFLINE) {
\t\t/* Don't recover if the remote processor was stopped */'''
    added = '''\tif (rproc->state == RPROC_OFFLINE) {
\t\tif (a52_p469_is_mss(rproc))
\t\t\tatomic_set(&a52_mss_fatal_pending, 0);
\t\t/* Don't recover if the remote processor was stopped */'''
    s = once(s, marker, added, "offline state duplicate")
    marker = '''\trproc->state = RPROC_CRASHED;
\tdev_err(dev, "handling crash #%u in %s\\n", ++rproc->crash_cnt,
\t\trproc->name);'''
    added = r'''	/* P469 MSS CRASHLOOP_STOP: TWO *fatal* crash episodes per 300s.
	 * No IPA workaround, no forced healthy status, and no automatic
	 * recovery after the second fatal. Other rprocs are untouched.
	 */
	if (a52_p469_is_mss(rproc) &&
	    atomic_xchg(&a52_mss_fatal_pending, 0)) {
		if (!a52_mss_fatal_window_count ||
		    time_after(jiffies, a52_mss_fatal_window_start +
			       msecs_to_jiffies(300000))) {
			a52_mss_fatal_window_start = jiffies;
			a52_mss_fatal_window_count = 0;
		}
		a52_mss_fatal_window_count++;
		if (a52_mss_fatal_window_count >= 2) {
			WRITE_ONCE(rproc->recovery_disabled, true);
			dev_err(dev,
				"P469 MSS CRASHLOOP_STOP fatals=%u window_ms=300000 recovery=disabled manual=recovery/recover\n",
				a52_mss_fatal_window_count);
		} else {
			dev_warn(dev,
				 "P469 MSS FATAL_WINDOW fatals=%u window_ms=300000\n",
				 a52_mss_fatal_window_count);
		}
	}
	rproc->state = RPROC_CRASHED;
	dev_err(dev, "handling crash #%u in %s\n", ++rproc->crash_cnt,
		rproc->name);'''
    s = once(s, marker, added, "crashloop hook")
    s = once(s,
        'if (!rproc->recovery_disabled)\n\t\trproc_trigger_recovery(rproc);',
        'if (!READ_ONCE(rproc->recovery_disabled))\n\t\trproc_trigger_recovery(rproc);',
        "auto-recovery gating")

    marker = '''\t/* Prevent suspend while the remoteproc is being recovered */
\tpm_stay_awake(rproc->dev.parent);'''
    added = '''\t/* Capture Q6v5 fatal type before its threaded crash handler.
\t * Ignore watchdogs: the threshold is two fatal events, not all SSRs.
\t */
\tif (type == RPROC_FATAL_ERROR && a52_p469_is_mss(rproc))
\t\tatomic_set(&a52_mss_fatal_pending, 1);

\t/* Prevent suspend while the remoteproc is being recovered */
\tpm_stay_awake(rproc->dev.parent);'''
    s = once(s, marker, added, "fatal-type producer")

    # After recovery rproc_stop succeeds, 5.10 marks the rproc OFFLINE.
    # If the follow-up PAS start times out, the SSR still holds a *valid*
    # rproc->power reference; next sysfs start increment (>1) skips boot.
    # An explicit sysfs 'recovery=recover' may retry rproc_start from this
    # exact OFFLINE+powered condition with no second rproc_stop. No changes
    # to rproc->power / refcounts, no fabricated RUNNING state.
    marker = '''\tstruct device *dev = &rproc->dev;
\tint ret;

\tret = mutex_lock_interruptible(&rproc->lock);'''
    added = '''\tstruct device *dev = &rproc->dev;
\tbool a52_retry_offline;
\tint ret;

\tret = mutex_lock_interruptible(&rproc->lock);'''
    # Limit this anchor to rproc_trigger_recovery() body, not other routines.
    a=s.index("int rproc_trigger_recovery(struct rproc *rproc)")
    b=s.index("static void rproc_crash_handler_work(struct work_struct *work)",a)
    part=once(s[a:b],marker,added,"local recovery declaration")
    part=once(part,
        '''\t/* State could have changed before we got the mutex */
\tif (rproc->state != RPROC_CRASHED)
\t\tgoto unlock_mutex;

\tdev_err(dev, "recovering %s\\n", rproc->name);

\tret = rproc_stop(rproc, true);
\tif (ret)
\t\tgoto unlock_mutex;

\t/* generate coredump */
\trproc->ops->coredump(rproc);''',
        r'''	/* P469 MSS MANUAL_RESTART: only a manual recovery sysfs request
	 * reaches the OFFLINE+powered branch after a failed PAS recovery.
	 * A duplicate sysfs "start" is explicitly rejected in sysfs.c.
	 */
	a52_retry_offline = a52_p469_is_mss(rproc) &&
		rproc->state == RPROC_OFFLINE &&
		atomic_read(&rproc->power) > 0;
	if (rproc->state != RPROC_CRASHED && !a52_retry_offline)
		goto unlock_mutex;

	if (a52_retry_offline) {
		dev_warn(dev,
			 "P469 MSS MANUAL_RESTART retry_offline=1 power=%d state=%d\n",
			 atomic_read(&rproc->power), rproc->state);
	} else {
		dev_err(dev, "recovering %s\n", rproc->name);
		ret = rproc_stop(rproc, true);
		if (ret)
			goto unlock_mutex;

		/* Generate one coredump for the originally crashed firmware. */
		rproc->ops->coredump(rproc);
	}''',"recovery gate")
    part=once(part,
        '''\tret = rproc_start(rproc, firmware_p);

\trelease_firmware(firmware_p);''',
        r'''	ret = rproc_start(rproc, firmware_p);
	if (a52_retry_offline)
		dev_info(dev,
			 "P469 MSS MANUAL_RESTART result=%d state=%d power=%d\n",
			 ret, READ_ONCE(rproc->state), atomic_read(&rproc->power));

	release_firmware(firmware_p);''',"manual result")
    s=s[:a]+part+s[b:]
    return s


def patch_sysfs(s):
    if "P469 MSS START_BLOCKED" in s:
        raise RuntimeError("P469 MSS sysfs patch applied twice")
    if 'static ssize_t state_store(struct device *dev,' not in s:
        raise RuntimeError("P469 missing GKI 5.10 sysfs state_store")
    # Keep non-MSS recovery/store interface unchanged, and do not silently
    # claim success on explicit MSS manual recovery errors.
    marker = '''\t} else if (sysfs_streq(buf, "recover")) {
\t\t/* begin the recovery process without changing the flag */
\t\trproc_trigger_recovery(rproc);'''
    added = r'''	} else if (sysfs_streq(buf, "recover")) {
		/* P469 MSS MANUAL_RESTART: propagate rc, do not fake success.
		 * Other rprocs retain the upstream sysfs ABI.
		 */
		if (rproc->dev.parent && rproc->dev.parent->of_node &&
		    of_device_is_compatible(rproc->dev.parent->of_node,
					    "qcom,sm6350-mss-pas")) {
			int rc = rproc_trigger_recovery(rproc);

			dev_info(&rproc->dev,
				 "P469 MSS MANUAL_RECOVER rc=%d state=%d power=%d\n",
				 rc, READ_ONCE(rproc->state),
				 atomic_read(&rproc->power));
			return rc ? rc : count;
		}
		/* begin the recovery process without changing the flag */
		rproc_trigger_recovery(rproc);'''
    s=once(s,marker,added,"manual recovery sysfs result")
    marker = '''\tif (sysfs_streq(buf, "start")) {
\t\tif (rproc->state == RPROC_RUNNING)
\t\t\treturn -EBUSY;

\t\tret = rproc_boot(rproc);'''
    added = r'''	if (sysfs_streq(buf, "start")) {
		if (rproc->state == RPROC_RUNNING)
			return -EBUSY;

		/* P469 MSS START_BLOCKED: a failed recovery can leave
		 * RPROC_OFFLINE with live SSR power references. rproc_boot()
		 * would increment power and return 0 without PAS start.
		 * A manual retry must use recovery/recover instead.
		 */
		if (rproc->dev.parent && rproc->dev.parent->of_node &&
		    of_device_is_compatible(rproc->dev.parent->of_node,
					    "qcom,sm6350-mss-pas") &&
		    atomic_read(&rproc->power) > 0) {
			dev_err(&rproc->dev,
				"P469 MSS START_BLOCKED state=%d power=%d use=recovery/recover rc=-EBUSY\n",
				rproc->state, atomic_read(&rproc->power));
			return -EBUSY;
		}

		ret = rproc_boot(rproc);'''
    s=once(s,marker,added,"sysfs fake-success block")
    return s


def verify_core(s):
    required=("P469 MSS CRASHLOOP_STOP", "P469 MSS FATAL_WINDOW",
              "RPROC_FATAL_ERROR", "atomic_xchg(&a52_mss_fatal_pending, 0)",
              "msecs_to_jiffies(300000)", "WRITE_ONCE(rproc->recovery_disabled, true)",
              "P469 MSS MANUAL_RESTART retry_offline=1",
              "P469 MSS MANUAL_RESTART result=",
              "rproc->state == RPROC_OFFLINE",
              "atomic_read(&rproc->power) > 0", "RPROC_CRASHED",
              "READ_ONCE(rproc->recovery_disabled)")
    for item in required:
        if item not in s:raise RuntimeError("P469 missing core guard "+item)
    if s.count("rproc_trigger_recovery(struct rproc *rproc)")!=1:
        raise RuntimeError("P469 changed recovery entrypoint cardinality")


def verify_sysfs(s):
    for item in ("P469 MSS START_BLOCKED", "P469 MSS MANUAL_RECOVER",
                 "return rc ? rc : count;", "return -EBUSY;"):
        if item not in s:raise RuntimeError("P469 missing sysfs "+item)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    fs=[(CORE,patch_core,verify_core),(SYSFS,patch_sysfs,verify_sysfs)]
    for path,fn,verify in fs:
        f=a.root/path
        s=f.read_text()
        if not a.check_only:
            s=fn(s)
            f.write_text(s)
        verify(s)
    report={"phase":"P469","MSS_fatal_limit":2,"window_seconds":300,
            "count_only":"RPROC_FATAL_ERROR episodes; not watchdog",
            "auto_recovery":"disabled after two fatals in window",
            "manual_command":"echo recover > /sys/class/remoteproc/remoteprocN/recovery",
            "stale_power":"state start returns EBUSY with diagnostic",
            "offline_retry":"manual recovery uses rproc_start without duplicate stop",
            "preserve_power_references":True,"fake_online":False,
            "non_MSS_remoteproc":"unchanged"}
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print("P469 MSS CRASHLOOP+MANUAL SOURCE PASS",json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
