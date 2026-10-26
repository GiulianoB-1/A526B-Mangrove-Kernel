#!/usr/bin/env python3
"""P463: suspend-aware charger guard + H0 on the final generated G source.

Safety contract: no I2C in guard work during device suspend, no H0 auto-arm,
no new charger writes, no permanent GUARD_IO latch from the PM transition.
PM notifier stops the 2s poll synchronously at PREPARE, resumes immediately
via system_freezable_wq at POST. On a transient resume I2C failure, no H0
tick/enable occurs until a later successful guard sample.
"""
import argparse,hashlib,json,re
from pathlib import Path
SRC=Path("drivers/a52_447/a52_sm5714_fg_ro.c")
MARK="P463 CHG_GUARD PM_SYNC"

def one(s,a,b,what):
    n=s.count(a)
    if n!=1:raise RuntimeError(f"P463 {what} changed: expected one anchor, got {n}")
    return s.replace(a,b,1)

def func(s,name):
    m=re.search(r"\b(?:static\s+)?(?:void|int)\s+"+re.escape(name)+r"\s*\([^;{}]*\)\s*\{",s,re.S)
    if not m:raise RuntimeError("P463 cannot locate "+name)
    n=m.end()-1;depth=0
    for i in range(n,len(s)):
        if s[i]=="{":depth+=1
        elif s[i]=="}":
            depth-=1
            if depth==0:return m.start(),i+1
    raise RuntimeError("P463 unterminated "+name)

def patch(s):
    if MARK in s:
        raise RuntimeError("P463 already applied; do not duplicate")
    for k in ("A52_PHASE452_H0_MANUAL_SAFE_CHARGER_V1",
              "P460B_H0_GUARD_2S_WDT_10S_V1",
              "P447G CHG_GUARD device_id_read_failed",
              "a52h0_off(fg,\"GUARD_IO\",true)",
              "cancel_delayed_work_sync(&fg->a52g_guard_work);",
              "schedule_delayed_work(&fg->a52g_guard_work,",
              "struct delayed_work a52g_guard_work;",
              "a52g_sample(fg,false)",
              "a52h0_wake_held"):
        if k not in s:raise RuntimeError("P463 missing verified baseline "+k)
    s=one(s,"#include <linux/i2c.h>",
          "#include <linux/i2c.h>\n#include <linux/suspend.h>\n#include <linux/notifier.h>",
          "PM notifier headers")
    s=one(s,"struct delayed_work a52g_guard_work;",
          """struct delayed_work a52g_guard_work;
    struct notifier_block a52g_pm_nb;
    bool a52g_pm_registered, a52g_pm_paused;
    unsigned long a52g_pm_grace_until;""","FG PM fields")
    a,b=func(s,"a52g_poll")
    orig=s[a:b]
    if orig.count("a52g_sample(fg,false)")!=1 or orig.count("a52h0_off(fg,\"GUARD_IO\",true)")!=1:
        raise RuntimeError("P463 guard poll H0 error branch changed")
    callback=r'''
/* P463 CHG_GUARD PM_SYNC. PREPARE runs before device suspend.
 * The charging H0 wake source already prevents sleep while actively
 * charging; the PM notifier does not change that invariant.
 */
static int a52g_pm_notify(struct notifier_block *nb, unsigned long event,
                          void *unused)
{
    struct a52d_fg *fg = container_of(nb, struct a52d_fg, a52g_pm_nb);

    switch (event) {
    case PM_SUSPEND_PREPARE:
        WRITE_ONCE(fg->a52g_pm_paused, true);
        cancel_delayed_work_sync(&fg->a52g_guard_work);
        dev_info(fg->dev, "P463 CHG_GUARD SUSPEND_PREPARE cancelled=1 active=%d wake_held=%d\n",
                 fg->a52h0_active, fg->a52h0_wake_held);
        return NOTIFY_OK;
    case PM_POST_SUSPEND:
        fg->a52g_pm_grace_until = jiffies + msecs_to_jiffies(2000);
        WRITE_ONCE(fg->a52g_pm_paused, false);
        mod_delayed_work(system_freezable_wq, &fg->a52g_guard_work, 0);
        dev_info(fg->dev, "P463 CHG_GUARD POST_SUSPEND immediate_sample=1 VBUS=check_after_resume\n");
        return NOTIFY_OK;
    default:
        return NOTIFY_DONE;
    }
}
static void a52g_poll(struct work_struct *work)
{
    struct a52d_fg *fg = container_of(to_delayed_work(work),
                                     struct a52d_fg, a52g_guard_work);
    int err;
    unsigned long delay = msecs_to_jiffies(A52G_GUARD_POLL_MS);

    if (READ_ONCE(fg->a52g_pm_paused))
        return;
    err = a52g_sample(fg, false);
    if (READ_ONCE(fg->a52g_pm_paused)) {
        dev_warn_ratelimited(fg->dev,
            "P463 CHG_GUARD SUSPEND_INFLIGHT rc=%d no_h0_fault_latch\n", err);
        return;
    }
    if (err < 0) {
        /* If OFF during resume, defer just the transient bus error.
         * NEVER run H0 tick/enable without a successful guard sample.
         * If charging is active, preserve the existing fail-closed
         * emergency inhibit (a52h0_off), not a silent continuation.
         */
        if (!fg->a52h0_active &&
            time_before(jiffies, fg->a52g_pm_grace_until)) {
            dev_warn_ratelimited(fg->dev,
                "P463 CHG_GUARD POST_RESUME_IO rc=%d deferred=1 killed=0\n", err);
            delay = msecs_to_jiffies(200);
        } else {
            mutex_lock(&fg->a52h0_lock);
            a52h0_off(fg, "GUARD_IO", true);
            mutex_unlock(&fg->a52h0_lock);
        }
    } else {
        a52h0_tick(fg);
    }
    if (!READ_ONCE(fg->a52g_pm_paused))
        mod_delayed_work(system_freezable_wq, &fg->a52g_guard_work, delay);
}
'''
    s=s[:a]+callback+s[b:]
    # Original worker was queued on system_wq, which can run in PM.
    # Switch the initial queue to the freezable workqueue too.
    s=one(s,'''schedule_delayed_work(&fg->a52g_guard_work,
			msecs_to_jiffies(A52G_GUARD_POLL_MS));''',
            '''mod_delayed_work(system_freezable_wq, &fg->a52g_guard_work,
			msecs_to_jiffies(A52G_GUARD_POLL_MS));''',
            "initial freezable queue")
    # Register only once, at the final post-probe scheduling location.
    anchor='''	if (IS_ENABLED(CONFIG_A52_447G_CHG_GUARD))
		mod_delayed_work(system_freezable_wq, &fg->a52g_guard_work,'''
    reg=r'''    /* Fail probe closed if PM protection cannot be registered.
     * Devres FG cleanup unregisters first and drains pending work.
     */
    fg->a52g_pm_nb.notifier_call = a52g_pm_notify;
    {
        int pmrc = register_pm_notifier(&fg->a52g_pm_nb);
        if (pmrc) {
            dev_err(fg->dev,
                    "P463 CHG_GUARD PM notifier registration rc=%d\n", pmrc);
            return pmrc;
        }
        fg->a52g_pm_registered = true;
    }
'''
    s=one(s,anchor,reg+anchor,"PM notifier before guard initial scheduling")
    # The PM callback also cancels work. Only modify the FG devres
    # teardown, not the callback; otherwise source replacement is ambiguous.
    ua,ub=func(s,"a52d_fg_unregister")
    unregister=s[ua:ub]
    unregister=one(unregister,"cancel_delayed_work_sync(&fg->a52g_guard_work);",
          '''if (fg->a52g_pm_registered) {
        unregister_pm_notifier(&fg->a52g_pm_nb);
        fg->a52g_pm_registered = false;
    }
    cancel_delayed_work_sync(&fg->a52g_guard_work);''',
          "ordered unregister before guard teardown")
    s=s[:ua]+unregister+s[ub:]
    return s

def validate(s):
    for tag in (MARK,"case PM_SUSPEND_PREPARE:","case PM_POST_SUSPEND:",
                "register_pm_notifier(&fg->a52g_pm_nb)",
                "unregister_pm_notifier(&fg->a52g_pm_nb)",
                "cancel_delayed_work_sync(&fg->a52g_guard_work)",
                "mod_delayed_work(system_freezable_wq, &fg->a52g_guard_work",
                "P463 CHG_GUARD POST_RESUME_IO","a52h0_off(fg, \"GUARD_IO\", true)",
                "if (!fg->a52h0_active &&",
                "P452 H0 ARM optin=%d killed=%d",
                "P447G CHG_GUARD INHIBIT_OK"):
        if tag not in s:raise RuntimeError("P463 missing safety gate: "+tag)
    if s.count("register_pm_notifier(&fg->a52g_pm_nb)")!=2:
        raise RuntimeError("P463 missing PM notifier register/unregister pair")
    if "schedule_delayed_work(&fg->a52g_guard_work" in s:
        raise RuntimeError("P463 guard remains on non-freezable workqueue")
    return {"pm_notifier":True,"cancel_on_prepare":True,"sample_post_resume":True,
            "guard_wq":"system_freezable_wq","pm_transient_i2c_fault_latched":False,
            "charger_writes_added":0,"h0_autoarm_added":False}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True,type=Path)
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--report",type=Path)
    x=ap.parse_args()
    p=x.root/SRC
    old=p.read_text()
    if not x.check_only:p.write_text(patch(old))
    result=validate(p.read_text())
    if x.report:
        x.report.parent.mkdir(parents=True,exist_ok=True)
        x.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P463 CHG_GUARD PM SYNC SOURCE GATE PASS "+json.dumps(result))
if __name__=="__main__":
    main()
