#!/usr/bin/env python3
"""P467 A52 PAS parent wakeup_source for SSR-safe suspend, and cheap audioPD
refusal. Applied only AFTER P451/P466 generation on G image.

Scope deliberately excludes remoteproc_core, P463 guard, P460B SMMU,
P457 SMMU probe, Phase206 veto, PAS auto_boot, SCM, P462 WDT and FastRPC
sensors/default PD paths.
"""
import argparse
import json
import re
import runpy
from pathlib import Path

PAS=Path("drivers/remoteproc/qcom_q6v5_pas.c")
RPC=Path("drivers/char/adsprpc.c")
TAG="P467 ADSP PAS WAKE_SOURCE"
AUDIO="P467 FASTRPC AUDIOPD_UNSUPPORTED"

def function(s,name):
    pat=re.compile(r"(?m)^static\s+int\s+"+re.escape(name)+r"\s*\([^;{}]*?\)\s*\{",re.S)
    m=pat.search(s)
    if not m:raise RuntimeError("P467 missing function "+name)
    depth=0
    for i in range(m.end()-1,len(s)):
        if s[i]=='{':depth+=1
        elif s[i]=='}':
            depth-=1
            if depth==0:return (m.start(),i+1)
    raise RuntimeError("P467 unterminated function "+name)

def unique(s,old,new,what):
    count=s.count(old)
    if count!=1:raise RuntimeError(f"P467 {what}: expected one anchor, got {count}")
    return s.replace(old,new,1)

def patch_pas(s):
    # The ACTUAL restored 5.10 PAS source already does
    # device_init_wakeup(adsp->dev, true) and unwinds it. Previous P467
    # incorrectly tried a second registration and failed during transform.
    # Do not duplicate registration, and do not change manual PAS behavior.
    if TAG in s:
        raise RuntimeError("P467 PAS double applied")
    if "#include <linux/pm_wakeup.h>" not in s:
        s=unique(s, "#include <linux/platform_device.h>",
                 "#include <linux/platform_device.h>\n#include <linux/pm_wakeup.h>",
                 "explicit parent wakeup API header")
    for token in ("A52_PHASE451_SM6350_ADSP_PAS_V1",
                  "P451 ADSP PROBE manual_start=1",
                  "rproc->auto_boot = desc->auto_boot;"):
        if token not in s:
            raise RuntimeError("P467 unexpected P451 PAS baseline "+token)
    a,b=function(s,"adsp_probe")
    probe=s[a:b]
    if probe.count("device_init_wakeup(adsp->dev, true)") != 1:
        raise RuntimeError("P467 PAS missing existing 5.10 wakeup initialization")
    if "adsp->dev = &pdev->dev;" not in probe:
        raise RuntimeError("P467 wakeup source is not rproc platform parent")
    if "if (ret)\n\t\tgoto deinit_wakeup_source;" not in probe:
        raise RuntimeError("P467 PAS wakeup cleanup labels changed")
    if "device_init_wakeup(adsp->dev, false);" not in probe:
        raise RuntimeError("P467 PAS missing probe-failure wakeup cleanup")

    old=("\tret = rproc_add(rproc);\n"
         "\tif (ret)\n"
         "\t\tgoto destroy_minidump_dev;\n\n"
         "\treturn 0;")
    new=r'''	ret = rproc_add(rproc);
	if (ret)
		goto destroy_minidump_dev;

	/* P467 ADSP PAS WAKE_SOURCE: 5.10 already registers the wakeup
	 * source above. Verify it is the rproc parent, not an unrelated
	 * device; rproc_report_crash uses pm_stay_awake(rproc->dev.parent).
	 * This does NOT prove async GLINK/RPMSG reprobe completion.
	 */
	dev_info(&pdev->dev,
		 "P467 ADSP PAS WAKE_SOURCE inherited=1 enabled=%d can=%d parent=%s rproc_parent=%s manual=1\n",
		 device_may_wakeup(&pdev->dev), device_can_wakeup(&pdev->dev),
		 dev_name(&pdev->dev), dev_name(rproc->dev.parent));
	if (!device_may_wakeup(&pdev->dev))
		dev_warn(&pdev->dev,
			 "P467 ADSP PAS WAKE_SOURCE DISABLED after rproc_add: pm_stay_awake will not protect SSR\n");
	return 0;'''
    probe=unique(probe,old,new,"log existing PAS wakeup after rproc registration")
    s=s[:a]+probe+s[b:]
    # Preserve the existing 5.10 remove ordering, not a second teardown.
    a,b=function(s,"adsp_remove")
    remove=s[a:b]
    if remove.count("device_init_wakeup(adsp->dev, false);") != 1:
        raise RuntimeError("P467 PAS missing original remove wakeup cleanup")
    if not (remove.index("rproc_del(adsp->rproc);") <
            remove.index("device_init_wakeup(adsp->dev, false);")):
        raise RuntimeError("P467 PAS wakeup removed before rproc teardown")
    return s

def patch_rpc(s):
    if AUDIO in s:raise RuntimeError("P467 FastRPC double applied")
    old='return a52_fastrpc_unsupported("audio-PD-remote-heap");'
    a,b=function(s,"fastrpc_init_create_static_process")
    f=s[a:b]
    f=unique(f,old,
         'pr_warn_once("P467 FASTRPC AUDIOPD_UNSUPPORTED static_pd/audiopd rc=-EOPNOTSUPP once=1\\n");\n'
         '    return -EOPNOTSUPP;',
         "cheap unsupported static audioPD")
    return s[:a]+f+s[b:]

def check_pas(s):
    a,b=function(s,"adsp_probe")
    probe=s[a:b]
    for token in ("adsp->dev = &pdev->dev;",
                  "device_init_wakeup(adsp->dev, true)",
                  "device_init_wakeup(adsp->dev, false)",
                  "P467 ADSP PAS WAKE_SOURCE inherited=1",
                  "device_may_wakeup(&pdev->dev)",
                  "rproc_add(rproc)"):
        if token not in probe:
            raise RuntimeError("P467 PAS source contract missing "+token)
    if probe.count("device_init_wakeup(adsp->dev, true)") != 1:
        raise RuntimeError("P467 PAS double init wakeup")
    if not (probe.index("device_init_wakeup(adsp->dev, true)") <
            probe.index("rproc_add(rproc)") <
            probe.index("P467 ADSP PAS WAKE_SOURCE inherited=1")):
        raise RuntimeError("P467 PAS registration/log placement incorrect")
    a,b=function(s,"adsp_remove")
    remove=s[a:b]
    if not (remove.index("rproc_del(adsp->rproc);") <
            remove.index("device_init_wakeup(adsp->dev, false);")):
        raise RuntimeError("P467 remove order must keep wakeup through rproc_del")
    for token in (".auto_boot = false","P451 ADSP PROBE manual_start=1",
                  "regulator_set_voltage(adsp->cx_supply,384,0xffff)",
                  "regulator_set_voltage(adsp->px_supply,384,0xffff)"):
        if token not in s:
            raise RuntimeError("P467 manual-PAS invariant lost "+token)

def check_rpc(s):
    a,b=function(s,"fastrpc_init_create_static_process")
    f=s[a:b]
    if ("pr_warn_once(\"P467 FASTRPC AUDIOPD_UNSUPPORTED" not in f or
        "return -EOPNOTSUPP;" not in f):
        raise RuntimeError("P467 cheap audioPD rejection missing")
    for invariant in ("P461 FASTRPC PD_START cid=",
                      "P466 FASTRPC DMA_MAP fd=",
                      "P466 FASTRPC RPC_LONG_WAIT",
                      "P465 FASTRPC NULL_TABLE"):
        if invariant not in s:raise RuntimeError("P467 FastRPC invariant lost "+invariant)
    if "pr_warn_ratelimited(\"P461 FASTRPC UNSUPPORTED feature=%s" not in s:
        raise RuntimeError("P467 general unsupported policy changed")

def selftest():
    # Exercise exactly the pinned donor FastRPC transformations.
    g461=runpy.run_path("scripts/461_enable_sensors_fastrpc.py",run_name="p467_461")
    g465=runpy.run_path("scripts/465_fastrpc_mmap_guard.py",run_name="p467_465")
    g466=runpy.run_path("scripts/466_fastrpc_dma_wait.py",run_name="p467_466")
    donor=Path("vendor/p461/a52-5.10-port/drivers/char/adsprpc.c").read_text()
    generated=g466["patch"](g465["patch"](g461["transform"](donor)))
    check_rpc(patch_rpc(generated))
    # Synthetic fixture follows the already-wakeup-capable 5.10 PAS
    # ownership/lifecycle; no extra device_init_wakeup is permitted.
    fixture='''#include <linux/platform_device.h>
static int adsp_probe(struct platform_device *pdev)
{
    struct qcom_adsp *adsp;
    struct rproc *rproc;
    int ret;
    rproc->auto_boot = desc->auto_boot;
    /* A52_PHASE451_SM6350_ADSP_PAS_V1 */
    dev_info(&pdev->dev,"P451 ADSP PROBE manual_start=1");
    adsp->dev = &pdev->dev;
    ret = device_init_wakeup(adsp->dev, true);
    if (ret)
        goto free_rproc;
    ret = adsp_alloc_memory_region(adsp);
    if (ret)
		goto deinit_wakeup_source;
	ret = rproc_add(rproc);
	if (ret)
		goto destroy_minidump_dev;

	return 0;
destroy_minidump_dev:
deinit_wakeup_source:
    device_init_wakeup(adsp->dev, false);
free_rproc:
    return ret;
}
static int adsp_remove(struct platform_device *pdev)
{
    struct qcom_adsp *adsp;
	rproc_del(adsp->rproc);
    device_init_wakeup(adsp->dev, false);
	return 0;
}
'''
    patched=patch_pas(fixture)
    if "P467 ADSP PAS WAKE_SOURCE inherited=1" not in patched:
        raise RuntimeError("P467 fixture log missing")
    if patched.count("device_init_wakeup(adsp->dev, true)") != 1:
        raise RuntimeError("P467 selftest duplicate wakeup source")
    print("P467 PINNED FASTRPC + PAS ANCHOR SELFTEST PASS")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path)
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--selftest",action="store_true")
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.root:
        ap.error("--root required unless --selftest")
    pf=args.root/PAS
    rf=args.root/RPC
    ps=pf.read_text()
    rs=rf.read_text()
    if not args.check_only:
        ps=patch_pas(ps)
        rs=patch_rpc(rs)
        pf.write_text(ps)
        rf.write_text(rs)
    check_pas(ps);check_rpc(rs)
    report={"parent_wakeup_already_initialized_in_5_10":True,
            "parent_wakeup_status_logged":True,
            "parent_wakeup_lifecycle_original_unchanged":True,
            "manual_pas_unchanged":True,
            "pm_stay_awake_core_unchanged":True,
            "audioPD_fast_refusal":"EOPNOTSUPP + once warning",
            "sensor_PD_unchanged":True,
            "rpc_wait_unchanged":True,
            "rpmsg_async_completion_not_proven":True}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("P467 ADSP SSR WAKEUP + AUDIOPD QUIET SOURCE PASS",json.dumps(report))

if __name__=="__main__":
    main()
