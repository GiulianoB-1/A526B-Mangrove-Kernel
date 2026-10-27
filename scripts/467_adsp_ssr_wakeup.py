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
    if TAG in s:raise RuntimeError("P467 PAS double applied")
    if "#include <linux/pm_wakeup.h>" not in s:
        s=unique(s, "#include <linux/platform_device.h>",
                 "#include <linux/platform_device.h>\n#include <linux/pm_wakeup.h>",
                 "explicit parent wakeup API header")
    if ("A52_PHASE451_SM6350_ADSP_PAS_V1" not in s or
        "P451 ADSP PROBE manual_start=1" not in s or
        "rproc->auto_boot = desc->auto_boot;" not in s):
        raise RuntimeError("P467 unexpected P451 PAS baseline")
    a,b=function(s,"adsp_probe")
    probe=s[a:b]
    if re.search(r'device_init_wakeup\s*\(',probe):
        raise RuntimeError("P467 PAS probe already initializes wakeup; audit required")
    pattern=re.compile(r'(\tret = rproc_add\(rproc\);\n\tif \(ret\)\n\t\tgoto ([a-z_][a-z0-9_]*);\n)\n(\treturn 0;)', re.M)
    matches=list(pattern.finditer(probe))
    if len(matches)!=1:
        raise RuntimeError(f"P467 PAS rproc_add success/failure gate count={len(matches)}")
    m=matches[0];cleanup=m.group(2)
    body=r'''/* P467 ADSP PAS WAKE_SOURCE. Remoteproc crash handler calls
     * pm_stay_awake(rproc->dev.parent) in IRQ and pm_relax(parent)
     * once recovery work is done. Must be a registered, enabled
     * wakeup-capable PARENT, not just a wakeup-capable rproc child.
     * Manual boot and the existing rproc suspend policy are unchanged.
     */
    ret = device_init_wakeup(&pdev->dev, true);
    if (ret) {
        dev_err(&pdev->dev, "P467 ADSP PAS WAKE_SOURCE failed rc=%d\n",
                ret);
        /* rproc_add succeeded: remove before normal probe unwinding. */
        rproc_del(rproc);
        goto CLEANUP_LABEL;
    }
    dev_info(&pdev->dev,
             "P467 ADSP PAS WAKE_SOURCE enabled=%d can=%d parent=%s manual=1\n",
             device_may_wakeup(&pdev->dev),
             device_can_wakeup(&pdev->dev), dev_name(&pdev->dev));
'''.replace("CLEANUP_LABEL",cleanup)
    probe=probe[:m.end(1)]+ "\n" +body+probe[m.start(3):]
    s=s[:a]+probe+s[b:]
    # Disable only after rproc_del; keep wakeup active through teardown.
    # The generated G PAS must have a conventional adsp_remove path.
    m=re.search(r'(?m)^static\s+int\s+adsp_remove\s*\([^;{}]*?\)\s*\{',s)
    if not m:raise RuntimeError("P467 missing PAS remove")
    depth=0;end=None
    for i in range(m.end()-1,len(s)):
        if s[i]=='{':depth+=1
        elif s[i]=='}':
            depth-=1
            if depth==0:end=i+1;break
    if end is None:raise RuntimeError("P467 unterminated remove")
    remove=s[m.start():end]
    remove=unique(remove,
        "\trproc_del(adsp->rproc);",
        '\trproc_del(adsp->rproc);\n'
        '\tdevice_init_wakeup(&pdev->dev, false);\n'
        '\tdev_info(&pdev->dev, "P467 ADSP PAS WAKE_SOURCE disabled after rproc_del\\n");',
        "unregister PAS wakeup")
    s=s[:m.start()]+remove+s[end:]
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
    if probe.count("device_init_wakeup(&pdev->dev, true)")!=1 or TAG not in probe:
        raise RuntimeError("P467 PAS wake source not enabled exactly once")
    if not (probe.index("rproc_add(rproc)") <
            probe.index("device_init_wakeup(&pdev->dev, true)") <
            probe.index("P467 ADSP PAS WAKE_SOURCE enabled")):
        raise RuntimeError("P467 PAS wakeup placement invalid")
    if "rproc_del(rproc);" not in probe[probe.index("device_init_wakeup(&pdev->dev, true)"):]:
        raise RuntimeError("P467 PAS wakeup registration failure lacks rproc_del")
    ix=s.index("static int adsp_remove(")
    cleanup=s[ix:]
    if not (cleanup.index("rproc_del(adsp->rproc)") <
            cleanup.index("device_init_wakeup(&pdev->dev, false)")):
        raise RuntimeError("P467 PAS unregister must follow rproc_del")
    for invariant in (".auto_boot = false","P451 ADSP PROBE manual_start=1",
                      "regulator_set_voltage(adsp->cx_supply,384,0xffff)",
                      "regulator_set_voltage(adsp->px_supply,384,0xffff)"):
        if invariant not in s:raise RuntimeError("P467 PAS invariant lost: "+invariant)

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
    # PAS is restored from an exact source tarball later in CI. Exercise
    # the rproc_add/cleanup anchor and require matching real-source gate.
    fixture='''#include <linux/platform_device.h>
static int adsp_probe(struct platform_device *pdev)
{
    struct rproc *rproc;
    int ret;
    rproc->auto_boot = desc->auto_boot;
    /* A52_PHASE451_SM6350_ADSP_PAS_V1 */
    dev_info(&pdev->dev,"P451 ADSP PROBE manual_start=1");
	ret = rproc_add(rproc);
	if (ret)
		goto destroy_minidump_dev;

	return 0;
destroy_minidump_dev:
    return ret;
}
static int adsp_remove(struct platform_device *pdev)
{
    struct qcom_adsp *adsp;
	rproc_del(adsp->rproc);
	return 0;
}
'''
    patched=patch_pas(fixture)
    if "P467 ADSP PAS WAKE_SOURCE" not in patched:
        raise RuntimeError("P467 PAS fixture did not inject wakeup")
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
    report={"parent_wakeup_enabled":True,
            "parent_wakeup_removed_after_rproc_del":True,
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
