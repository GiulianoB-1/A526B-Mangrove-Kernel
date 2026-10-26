#!/usr/bin/env python3
"""P462 auditable inventory: diagnostic/bypass probe returns with PM callbacks.

Scans *final materialized source* after phase generators, not the repo's
incomplete script collection. All candidates are listed in JSON/Markdown.
Known high-confidence unsafe paths fail CI. This is heuristic source
triage, not a substitute for runtime suspend/resume testing.
"""
import argparse,json,re
from pathlib import Path

DIAG=re.compile(r'A52[^\n"]{0,110}(?:diagnostic|disabled|bypass|skip)',re.I)
PM=re.compile(r'SIMPLE_DEV_PM_OPS|DEFINE_SIMPLE_DEV_PM_OPS|\bdev_pm_ops\b|\.pm\s*=')
PM_CB=re.compile(r'\.(?:suspend|resume|freeze|thaw|poweroff|restore)\s*=\s*([a-zA-Z_]\w*)')
FUNC=re.compile(r'(?:static\s+)?(?:int|void|long|bool|ssize_t|irqreturn_t)\s+(?:__\w+\s+)?([a-zA-Z_]\w*)\s*\([^;{}]*?\)\s*\{',re.S)
SETDATA=re.compile(r'(?:platform_set_drvdata|dev_set_drvdata)\s*\(')

def functions(s):
    arr=[]
    for m in FUNC.finditer(s):
        i=m.end()-1;depth=0
        while i<len(s):
            if s[i]=='{':depth+=1
            if s[i]=='}':
                depth-=1
                if depth==0:break
            i+=1
        if i<len(s):arr.append((m.group(1),m.start(),i+1))
    return arr

def scan_file(p,root):
    s=p.read_text(errors="replace")
    if not DIAG.search(s):return []
    fmap=functions(s)
    callbacks=sorted(set(PM_CB.findall(s)))
    sm=re.search(r'SIMPLE_DEV_PM_OPS\s*\([^,]+,\s*(\w+)\s*,\s*(\w+)',s)
    if sm:callbacks=sorted(set(callbacks+[sm.group(1),sm.group(2)]))
    haspm=bool(PM.search(s))
    records=[]
    for m in DIAG.finditer(s):
        begin,end=next(((a,b) for _,a,b in fmap if a<=m.start()<b),(0,len(s)))
        fn=next((n for n,a,b in fmap if a==begin and b==end),"<unresolved>")
        local=s[begin:end];rel=m.start()-begin
        # Explicitly capture nearby return site; a marker may appear in
        # diagnostics without controlling a return in the probe.
        tail=local[rel:rel+700]
        ret=re.search(r'\breturn\s+([^;]+);',tail)
        before=local[:rel+ret.start()] if ret else local[:rel]
        drvdata_before=bool(SETDATA.search(before))
        line=s.count("\n",0,m.start())+1
        retline=line+tail.count("\n",0,ret.start()) if ret else None
        is_probe=fn.endswith("_probe") or fn=="probe"
        rc=ret.group(1).strip() if ret else None
        unsafe=is_probe and haspm and rc in ("0","-0") and not drvdata_before
        records.append({
            "path":str(p.relative_to(root)),"function":fn,
            "diagnostic_line":line,
            "diagnostic":s[m.start():s.find("\n",m.start())].strip()[:150],
            "nearby_return_line":retline,"nearby_return":rc,
            "pm_ops_present":haspm,"pm_callbacks_in_file":callbacks,
            "drvdata_set_before_return":drvdata_before,
            "drvdata_set_somewhere_in_file":bool(SETDATA.search(s)),
            "probe_function":is_probe,"unsafe_heuristic":unsafe,
        })
    return records

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    x=ap.parse_args()
    data=[]
    for p in sorted((x.root/"drivers").rglob("*.c")):
        data.extend(scan_file(p,x.root))
    wdt=[z for z in data if z["path"]=="drivers/watchdog/qcom-wdt.c"
         and "watchdog disabled for manual recovery" in z["diagnostic"]]
    if len(wdt)!=1 or wdt[0]["nearby_return"]!="-ENODEV":
        raise RuntimeError("P462 watchdog known-bad diagnostic path not fail-closed: "+repr(wdt))
    unsafe=[z for z in data if z["unsafe_heuristic"]]
    result={"scope":"drivers/**/*.c final generated source",
            "method":"heuristic source triage, manually review unrecognized probe syntax",
            "diagnostic_sites":data,
            "unsafe_early_probe_returns":unsafe,
            "watchdog":wdt[0]}
    x.out.parent.mkdir(parents=True,exist_ok=True)
    x.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    lines=["# P462 disabled/bypass probe ↔ system PM audit","",
        "This is a search of the final generated drivers tree. It is not a runtime proof.",
        "",
        "| Driver / function | diagnostic : line | near return | PM callbacks | drvdata before return |",
        "|---|---|---|---|---|"]
    for z in data:
        if not (z["probe_function"] or z["pm_ops_present"]):
            continue
        lines.append("| "+z["path"]+" / "+z["function"]+" | "+str(z["diagnostic_line"])+
          " | "+str(z["nearby_return"])+" @"+str(z["nearby_return_line"])+
          " | "+", ".join(z["pm_callbacks_in_file"])+
          " | "+str(z["drvdata_set_before_return"])+" |")
    x.out.with_suffix(".md").write_text("\n".join(lines)+"\n")
    if unsafe:
        raise RuntimeError("P462 unsafe diagnostic probe returns found: "+
                           repr([(x["path"],x["function"],x["nearby_return_line"]) for x in unsafe]))
    print("P462 PM BYPASS AUDIT PASS candidates=",len(data),"unsafe=",len(unsafe))
if __name__=="__main__":
    main()
