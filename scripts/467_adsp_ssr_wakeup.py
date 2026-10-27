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
    if "adsp->dev = &pdev->dev;" not in probe:
        raise RuntimeError("P467 rproc parent is not PAS platform device")
    # Earlier P467 revisions mistook a device_init_wakeup(..., false)
    # cleanup call for an existing (..., true) registration. Check the
    # ENABLE argument explicitly, accepting normal C true or 1.
    enable_rx=r"device_init_wakeup\s*\(\s*(?:adsp->dev|&pdev->dev)\s*,\s*(?:true|1)\s*\)"
    disable_rx=r"device_init_wakeup\s*\(\s*(?:adsp->dev|&pdev->dev)\s*,\s*(?:false|0)\s*\)"
    enabled=re.findall(enable_rx,probe)
    if len(enabled)>1:
        raise RuntimeError("P467 PAS wakeup already enabled more than once; fail closed")

    # Both paths share this exact rproc_add success anchor. The source
    # must be preserved; no PM / PAS / recovery internals are changed.
    orig=("\tret = rproc_add(rproc);\n"
          "\tif (ret)\n"
          "\t\tgoto destroy_minidump_dev;\n\n"
          "\treturn 0;")
    if orig not in probe:
        raise RuntimeError("P467 PAS registration success anchor moved")
    if len(enabled)==0:
        # No existing initialization: create it AFTER successful rproc_add.
        # It is the actual parent (pdev), so remoteproc_core's
        # pm_stay_awake(rproc->dev.parent) can inhibit s2idle while
        # recovery_work executes. Do not replace the recovery policy.
        replacement=r'''	ret = rproc_add(rproc);
	if (ret)
		goto destroy_minidump_dev;

	/* P467 ADSP PAS WAKE_SOURCE: initialize the rproc *parent*
	 * so rproc_report_crash() can protect SSR against system suspend.
	 */
	ret = device_init_wakeup(&pdev->dev, true);
	if (ret) {
		dev_err(&pdev->dev,
			"P467 ADSP PAS WAKE_SOURCE init_failed rc=%d\n", ret);
		rproc_del(rproc);
		goto destroy_minidump_dev;
	}
	dev_info(&pdev->dev,
		 "P467 ADSP PAS WAKE_SOURCE enabled=%d can=%d parent=%s manual=1\n",
		 device_may_wakeup(&pdev->dev),
		 device_can_wakeup(&pdev->dev), dev_name(&pdev->dev));
	return 0;'''
        probe=unique(probe,orig,replacement,"register missing PAS parent wakeup")
    else:
        # Existing wakeup initialization: never initialize it twice.
        replacement=r'''	ret = rproc_add(rproc);
	if (ret)
		goto destroy_minidump_dev;

	/* P467 ADSP PAS WAKE_SOURCE existing init verified, never duplicated. */
	dev_info(&pdev->dev,
		 "P467 ADSP PAS WAKE_SOURCE enabled=%d can=%d parent=%s manual=1 existing=1\n",
		 device_may_wakeup(&pdev->dev),
		 device_can_wakeup(&pdev->dev), dev_name(&pdev->dev));
	return 0;'''
        probe=unique(probe,orig,replacement,"log previously enabled wakeup")

    # Keep existing probe-failure cleanup; if this tree has no cleanup
    # call, add one only at the rproc registration unwind label.
    if not re.search(disable_rx,probe):
        needle="destroy_minidump_dev:"
        if probe.count(needle)!=1:
            raise RuntimeError("P467 cannot guarantee wakeup cleanup")
        probe=unique(probe,needle,
                     needle+"\n\tdevice_init_wakeup(&pdev->dev, false);",
                     "probe failure wakeup cleanup")
    s=s[:a]+probe+s[b:]

    a,b=function(s,"adsp_remove")
    remove=s[a:b]
    if not re.search(disable_rx,remove):
        remove=unique(remove,"\trproc_del(adsp->rproc);",
                      "\trproc_del(adsp->rproc);\n"
                      "\tdevice_init_wakeup(&pdev->dev, false);",
                      "remove wakeup after rproc_del")
    else:
        if not (remove.index("rproc_del(adsp->rproc);") <
                re.search(disable_rx,remove).start()):
            raise RuntimeError("P467 remove releases wakeup before rproc_del")
    s=s[:a]+remove+s[b:]
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
    en=re.findall(r"device_init_wakeup\s*\(\s*(?:adsp->dev|&pdev->dev)\s*,\s*(?:true|1)\s*\)",probe)
    if len(en)!=1:
        raise RuntimeError("P467 expected exactly one parent wakeup enable, got "+str(len(en)))
    for token in ("adsp->dev = &pdev->dev;",
                  "P467 ADSP PAS WAKE_SOURCE enabled=",
                  "device_may_wakeup(&pdev->dev)",
                  "rproc_add(rproc)"):
        if token not in probe:
            raise RuntimeError("P467 PAS source contract missing "+token)
    if not (probe.index("rproc_add(rproc)") <
            probe.index("P467 ADSP PAS WAKE_SOURCE enabled=")):
        raise RuntimeError("P467 PAS wakeup log before rproc registration")
    if "ret = device_init_wakeup(&pdev->dev, true);" in probe:
        if not (probe.index("rproc_add(rproc)") <
                probe.index("ret = device_init_wakeup(&pdev->dev, true);") <
                probe.index("P467 ADSP PAS WAKE_SOURCE enabled=")):
            raise RuntimeError("P467 new wakeup must follow rproc_add")
        if "rproc_del(rproc);" not in probe:
            raise RuntimeError("P467 new wakeup init failure must undo rproc_add")
    a,b=function(s,"adsp_remove")
    remove=s[a:b]
    m=re.search(r"device_init_wakeup\s*\(\s*(?:adsp->dev|&pdev->dev)\s*,\s*(?:false|0)\s*\)",remove)
    if not m or remove.index("rproc_del(adsp->rproc);")>m.start():
        raise RuntimeError("P467 wakeup remove cleanup must follow rproc_del")
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
    # Test both source variants: base 5.10 tree with or without
    # device_init_wakeup(...,true). A cleanup-only call MUST NOT count.
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
	ret = rproc_add(rproc);
	if (ret)
		goto destroy_minidump_dev;

	return 0;
destroy_minidump_dev:
    device_init_wakeup(adsp->dev, false);
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
    for version in (fixture, fixture.replace(
            '    adsp->dev = &pdev->dev;',
            '    adsp->dev = &pdev->dev;\n    device_init_wakeup(adsp->dev, true);')):
        transformed=patch_pas(version)
        if len(re.findall(
            r"device_init_wakeup\s*\(\s*(?:adsp->dev|&pdev->dev)\s*,\s*(?:true|1)\s*\)",
            transformed))!=1:
            raise RuntimeError("P467 fixture enabled source duplicate/missing")
        if "P467 ADSP PAS WAKE_SOURCE enabled=" not in transformed:
            raise RuntimeError("P467 PAS fixture wakeup log absent")
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
    report={"parent_wakeup_exactly_once":True,
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
