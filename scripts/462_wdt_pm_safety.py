#!/usr/bin/env python3
"""P462: fail closed on disabled qcom-wdt probe; PM cannot dereference NULL.

This applies AFTER every old phase generator to the actual built 5.10 source.
It changes only drivers/watchdog/qcom-wdt.c; not SMMU/PM core/hardware.
"""
import argparse
import json
import re
from pathlib import Path

REL=Path("drivers/watchdog/qcom-wdt.c")
MARK="P462 WDT DIAG_SKIP no_bind_rc=-ENODEV"

def func_range(s, name):
    m=re.search(r"\b"+re.escape(name)+r"\s*\([^;]*?\)\s*\{",s,re.S)
    if not m: raise RuntimeError("P462 missing function "+name)
    st=m.end()-1
    i=st;depth=0
    while i<len(s):
        if s[i]=="{":depth+=1
        elif s[i]=="}":
            depth-=1
            if depth==0:return m.start(),i+1
        i+=1
    raise RuntimeError("P462 unterminated function "+name)

def patch(source):
    s=source
    marker="A52 diagnostic: watchdog disabled for manual recovery"
    if s.count(marker)!=1:
        raise RuntimeError("P462 expected one source watchdog-disabled marker, got "+str(s.count(marker)))
    st,en=func_range(s,"qcom_wdt_probe")
    probe=s[st:en]
    pos=probe.index(marker)
    # Only the explicitly disabled and logged success-return is modified.
    # Do NOT touch normal watchdog-register success or its drvdata.
    rem=probe[pos:]
    m=re.search(r"\breturn\s+(0|-ENODEV)\s*;",rem)
    if not m or m.start()>750:
        raise RuntimeError("P462 cannot identify bounded disabled-probe return")
    if "platform_set_drvdata" in rem[:m.start()] or "devm_watchdog_register_device" in rem[:m.start()]:
        raise RuntimeError("P462 disabled branch unexpectedly registered/initialized watchdog")
    if m.group(1)=="0":
        original=rem[m.start():m.end()]
        rem=rem[:m.start()]+f'dev_warn(dev, "{MARK}\\n");\n\t\treturn -ENODEV;'+rem[m.end():]
        probe=probe[:pos]+rem
        s=s[:st]+probe+s[en:]
    elif MARK not in probe:
        raise RuntimeError("P462 -ENODEV branch lacks known audit marker")
    # A defensive PM guard, even if another failure path leaves drvdata absent.
    # A nonbound device should never execute these callbacks; this guard is
    # intentionally idle and performs NO watchdog hardware writes.
    for name in ("qcom_wdt_suspend","qcom_wdt_resume"):
        st,en=func_range(s,name)
        sub=s[st:en]
        local="struct qcom_wdt *wdt = dev_get_drvdata(dev);"
        if sub.count(local)!=1:
            raise RuntimeError("P462 unexpected "+name+" drvdata declaration")
        gate=(f'\n\n\tif (!wdt) {{\n'
              f'\t\tdev_warn_once(dev, "P462 WDT {name.upper()} unbound drvdata, skip\\n");\n'
              f'\t\treturn 0;\n\t}}\n')
        if f'P462 WDT {name.upper()}' not in sub:
            sub=sub.replace(local,local+gate,1)
            s=s[:st]+sub+s[en:]
    return s

def validate(s):
    if MARK not in s:raise RuntimeError("P462 missing no-bind marker")
    st,en=func_range(s,"qcom_wdt_probe")
    probe=s[st:en]
    pos=probe.index("A52 diagnostic: watchdog disabled for manual recovery")
    rem=probe[pos:]
    m=re.search(r"\breturn\s+(-ENODEV|0)\s*;",rem)
    if not m or m.group(1)!="-ENODEV" or m.start()>750:
        raise RuntimeError("P462 watchdog disabled branch must return -ENODEV")
    if probe.count("platform_set_drvdata")!=1:
        raise RuntimeError("P462 normal watchdog probe lost drvdata assignment")
    for name in ("qcom_wdt_suspend","qcom_wdt_resume"):
        a,b=func_range(s,name)
        block=s[a:b]
        if (f'P462 WDT {name.upper()}' not in block
                or not re.search(r"if\s*\(!wdt\)\s*\{[^}]*return\s+0\s*;",block,re.S)):
            raise RuntimeError("P462 missing NULL-safe PM callback: "+name)
    if "SIMPLE_DEV_PM_OPS(qcom_wdt_pm_ops" not in s:
        raise RuntimeError("P462 PM ops layout drift")
    return {"watchdog_probe":"qcom_wdt_probe", "disable_return":"-ENODEV (no platform bind)",
            "normal_probe_drvdata":True, "pm_callbacks":["qcom_wdt_suspend","qcom_wdt_resume"],
            "pm_null_skip":True,"marker":MARK,
            "hardware_register_writes_added":False}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--report",type=Path)
    x=ap.parse_args()
    path=x.root/REL
    before=path.read_text()
    if not x.check_only:
        after=patch(before)
        validate(after)
        path.write_text(after)
    else:
        validate(before)
    result=validate(path.read_text())
    if x.report:
        x.report.parent.mkdir(parents=True,exist_ok=True)
        x.report.write_text(json.dumps(result,indent=2)+"\n")
    print("P462 WDT PM SAFETY PASS",json.dumps(result,sort_keys=True))
if __name__=="__main__":
    main()
