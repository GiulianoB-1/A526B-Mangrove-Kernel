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
    # The actual SHA-pinned Phase446S GKI 5.10 PAS source calls
    # device_wakeup_enable(adsp->dev) but NEVER marks the parent as
    # wakeup-capable. Consequently pm_stay_awake(rproc->dev.parent) can
    # be ineffective. Replace the original call at its actual site.
    # Do NOT invent extra rproc_add cleanup labels.
    if TAG in s:
        raise RuntimeError("P467 PAS already patched")
    if "#include <linux/pm_wakeup.h>" not in s:
        s=unique(s, "#include <linux/platform_device.h>",
                 "#include <linux/platform_device.h>\n#include <linux/pm_wakeup.h>",
                 "explicit parent wakeup API header")
    for token in ("A52_PHASE451_SM6350_ADSP_PAS_V1",
                  "P451 ADSP PROBE manual_start=1",
                  "rproc->auto_boot = desc->auto_boot;"):
        if token not in s:
            raise RuntimeError("P467 expected P451 manual PAS source: "+token)

    a,b=function(s,"adsp_probe")
    probe=s[a:b]
    if "adsp->dev = &pdev->dev;" not in probe:
        raise RuntimeError("P467 PAS missing real platform parent assignment")
    if re.search(r"device_init_wakeup\s*\([^;]*,\s*(?:true|1)\s*\)",probe):
        raise RuntimeError("P467 PAS already initializes wakeup; do not duplicate")
    old="\tdevice_wakeup_enable(adsp->dev);"
    new=r'''	/* P467 ADSP PAS WAKE_SOURCE: unlike device_wakeup_enable(),
	 * device_init_wakeup() makes the real rproc parent wakeup-capable
	 * AND allocates/enables its wakeup_source. The remoteproc crash
	 * path uses pm_stay_awake(rproc->dev.parent) until recovery_work
	 * returns. This does not guarantee asynchronous RPMSG reprobe.
	 */
	ret = device_init_wakeup(adsp->dev, true);
	if (ret) {
		dev_err(adsp->dev,
			"P467 ADSP PAS WAKE_SOURCE init_failed rc=%d\n", ret);
		goto free_rproc;
	}
	dev_info(adsp->dev,
		 "P467 ADSP PAS WAKE_SOURCE enabled=%d can=%d parent=%s manual=1\n",
		 device_may_wakeup(adsp->dev),
		 device_can_wakeup(adsp->dev), dev_name(adsp->dev));'''
    probe=unique(probe,old,new,"replace bare 5.10 device_wakeup_enable")
    if "free_rproc:" not in probe or "device_init_wakeup(adsp->dev, false);" not in probe:
        raise RuntimeError("P467 old failure cleanup must remain unchanged")
    s=s[:a]+probe+s[b:]
    a,b=function(s,"adsp_remove")
    remove=s[a:b]
    if not (remove.count("device_init_wakeup(adsp->dev, false);")==1 and
            remove.index("rproc_del(adsp->rproc);") <
            remove.index("device_init_wakeup(adsp->dev, false);")):
        raise RuntimeError("P467 old PAS remove must keep wakeup until rproc_del")
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
    for needle in ("adsp->dev = &pdev->dev;",
                   "P467 ADSP PAS WAKE_SOURCE enabled=",
                   "ret = device_init_wakeup(adsp->dev, true);",
                   "device_may_wakeup(adsp->dev)",
                   "device_can_wakeup(adsp->dev)",
                   "rproc_add(rproc);"):
        if needle not in probe:
            raise RuntimeError("P467 PAS source missing: "+needle)
    if probe.count("device_init_wakeup(adsp->dev, true);")!=1:
        raise RuntimeError("P467 parent wakeup initialized zero or multiple times")
    if "device_wakeup_enable(adsp->dev);" in probe:
        raise RuntimeError("P467 old bare wakeup call survived")
    if not (probe.index("adsp->dev = &pdev->dev;") <
            probe.index("ret = device_init_wakeup(adsp->dev, true);") <
            probe.index("rproc_add(rproc);")):
        raise RuntimeError("P467 parent wakeup must precede rproc_add")
    if not (probe.index("ret = device_init_wakeup(adsp->dev, true);") <
            probe.index("goto free_rproc;") <
            probe.index("free_rproc:") <
            probe.index("device_init_wakeup(adsp->dev, false);")):
        raise RuntimeError("P467 parent wakeup failure cleanup drift")
    a,b=function(s,"adsp_remove")
    remove=s[a:b]
    if not (remove.index("rproc_del(adsp->rproc);") <
            remove.index("device_init_wakeup(adsp->dev, false);")):
        raise RuntimeError("P467 PAS release ordering changed")
    for marker in (".auto_boot = false","P451 ADSP PROBE manual_start=1",
                   "regulator_set_voltage(adsp->cx_supply,384,0xffff)",
                   "regulator_set_voltage(adsp->px_supply,384,0xffff)"):
        if marker not in s:
            raise RuntimeError("P467 P451 regulator/PAS baseline changed "+marker)

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
    # Fixture mirrors the ACTUAL pinned Phase446S PAS, not sm8450 donor.
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
	device_wakeup_enable(adsp->dev);
	ret = adsp_alloc_memory_region(adsp);
	if (ret)
		goto free_rproc;
	ret = rproc_add(rproc);
	if (ret)
		goto detach_proxy_pds;
	return 0;
detach_proxy_pds:
free_rproc:
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
    generated=patch_pas(fixture)
    if generated.count("ret = device_init_wakeup(adsp->dev, true);")!=1:
        raise RuntimeError("P467 source fixture did not initialize parent wakeup once")
    if "device_wakeup_enable(adsp->dev);" in generated:
        raise RuntimeError("P467 source fixture bare wakeup call survived")
    if "P467 ADSP PAS WAKE_SOURCE enabled=" not in generated:
        raise RuntimeError("P467 source fixture missing enabled diagnostic")
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
