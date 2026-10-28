#!/usr/bin/env python3
"""P468: give the existing P467 PAS modem node a phandle for real SSR state.
Only adds the property if absent; all P467/P462/ADSP/rail/IRQ bytes semantically
untouched. The 5.10 rproc_get_by_phandle requires the parent OF phandle.
"""
import argparse,hashlib,json,re,subprocess,tempfile,runpy
from pathlib import Path
MSS="/soc/qcom,mss@4080000"
P467=runpy.run_path("scripts/467_mss_boot_dtb.py")
def cmd(*args,check=True):
    p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if check and p.returncode:
        raise RuntimeError("P468 DTB command failed "+repr(args)+": "+p.stderr)
    return p
def get_phandle(path):
    p=cmd("fdtget","-t","x",str(path),MSS,"phandle",check=False)
    return int(p.stdout.strip().split()[0],16) if p.returncode==0 and p.stdout.strip() else None
def check(path):
    P467["check"](str(path))
    ph=get_phandle(path)
    if not ph:raise RuntimeError("P468 modem rproc parent phandle unavailable")
    dts=cmd("dtc","-q","-I","dtb","-O","dts",str(path)).stdout
    # Ensure no second node claims the chosen value.
    hits=re.findall(r'(?:linux,)?phandle\s*=\s*<0x([0-9a-fA-F]+)>',dts)
    if [int(x,16) for x in hits].count(ph)!=1:
        raise RuntimeError("P468 duplicate/unrecognized modem phandle")
    return {"modem_node":MSS,"phandle":ph,
            "legacy_mss":"P467 identical except possible new phandle",
            "pas_state":"real remoteproc, no fabricated online"}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dtb-in",required=True,type=Path)
    p.add_argument("--dtb-out",required=True,type=Path)
    p.add_argument("--report",required=True,type=Path)
    p.add_argument("--check-only",action="store_true")
    a=p.parse_args()
    with tempfile.TemporaryDirectory() as d:
        f=Path(d)/"P468.dtb"
        f.write_bytes(a.dtb_in.read_bytes())
        P467["check"](str(f))
        old=get_phandle(f)
        if not a.check_only and not old:
            dts=cmd("dtc","-q","-I","dtb","-O","dts",str(f)).stdout
            used={int(x,16) for x in re.findall(
                r'(?:linux,)?phandle\s*=\s*<0x([0-9a-fA-F]+)>',dts)}
            ph=max(used|{0})+1
            if ph>=0xfffffffe:raise RuntimeError("P468 exhausted phandles")
            cmd("fdtput","-t","x",str(f),MSS,"phandle",format(ph,"x"))
        result=check(f)
        result["added"]=bool(not old and not a.check_only)
        result["sha256"]=hashlib.sha256(f.read_bytes()).hexdigest()
        a.dtb_out.write_bytes(f.read_bytes())
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("P468 MSS rproc phandle DTB PASS",json.dumps(result,sort_keys=True))
if __name__=="__main__":main()
