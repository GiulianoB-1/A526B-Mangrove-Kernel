#!/usr/bin/env python3
"""P461 PREBUILD ONLY: stage exact ADSP-only downstream FastRPC FDT.

Input is the already-packaged P460b ECC48 boot image.
Output is an AUDITED DTB ONLY, deliberately NOT a boot.img: do not
advertise sensors or RPC as working before genuine adsprpc driver port.
"""
import argparse, hashlib, json, runpy, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
parse=runpy.run_path("scripts/38_repack_a52_p1_boot.py")["parse_boot"]
inspect_pstore=runpy.run_path("scripts/458_pstore_ecc48_dtb.py")["inspect"]
def run(*args,optional=False):
    p=subprocess.run([str(a) for a in args],capture_output=True,text=True)
    if p.returncode and not optional:
        raise RuntimeError(f"P461 FDT {args} rc={p.returncode}: {p.stderr[-350:]}")
    return None if p.returncode else p.stdout.strip()
def children(p,n):
    c=run("fdtget","-l",p,n,optional=True)
    return c.splitlines() if c else []
def nodes(p,n="/",level=0):
    if level>=32:raise RuntimeError("P461 runaway tree")
    yield n
    for child in children(p,n):
        yield from nodes(p,n.rstrip("/")+"/"+child,level+1)
def prop(p,n,k,fmt="s"):
    return run("fdtget","-t",fmt,p,n,k,optional=True)
def cells(p,n,k):
    s=prop(p,n,k,"x")
    return None if s is None else [int(v,16) for v in s.split()]
def check_cb(p,n,index,common=None):
    assert prop(p,n,"compatible")=="qcom,msm-fastrpc-compute-cb",(n,"compatible")
    assert prop(p,n,"label")=="adsprpc-smd",(n,"label")
    got=cells(p,n,"iommus")
    assert got and len(got)==3 and got[1]==0x1003+(index-10) and got[2]==0,(n,"SID",got)
    if common is not None:assert got[0]==common,(n,"SMMU phandle mismatch")
    assert cells(p,n,"qcom,iommu-dma-addr-pool")==[0x80000000,0x78000000],(n,"dma pool")
    assert prop(p,n,"qcom,iommu-faults").split()==["stall-disable","HUPCF"],(n,"fault")
    assert "dma-coherent" in (run("fdtget","-p",p,n) or "").splitlines(),(n,"coherency")
    if index==12:assert cells(p,n,"shared-cb")==[5],(n,"shared-cb")
    return got[0]
def stage(p):
    parents=[n for n in nodes(p)
             if prop(p,n,"compatible")=="qcom,msm-fastrpc-compute"]
    if len(parents)!=1:raise RuntimeError("P461 missing/ambiguous compute parent "+repr(parents))
    parent=parents[0]; children0=children(p,parent)
    chosen=["qcom,msm_fastrpc_compute_cb"+str(n) for n in (10,11,12)]
    for idx,k in zip((10,11,12),chosen):
        check_cb(p,parent+"/"+k,idx)
    smmu=cells(p,parent+"/"+chosen[0],"iommus")[0]
    for idx,k in zip((10,11,12),chosen):
        check_cb(p,parent+"/"+k,idx,smmu)
    removed=[]
    for name in children0:
        if name in chosen:continue
        n=parent+"/"+name
        label=prop(p,n,"label")
        if label!="cdsprpc-smd" or not name.startswith("qcom,msm_fastrpc_compute_cb"):
            raise RuntimeError("P461 unexpected compute child: "+n+" label="+str(label))
        sid=cells(p,n,"iommus")
        if sid is None or len(sid)!=3 or sid[1] not in range(0x1401,0x140a):
            raise RuntimeError("P461 refusing unexpected CDSP SID: "+n+" "+repr(sid))
        run("fdtput","-r",p,n)
        removed.append({"node":n,"sid":sid[1]})
    if len(removed)!=9:
        raise RuntimeError(f"P461 expected 9 CDSP CBs, removed {len(removed)}")
    assert children(p,parent)==chosen,(parent,children(p,parent))
    edge="/soc/qcom,lpass@3000000/glink-edge/qcom,msm_fastrpc_rpmsg"
    assert prop(p,edge,"compatible")=="qcom,msm-fastrpc-rpmsg",(edge,"compatible")
    assert prop(p,edge,"qcom,glink-channels")=="fastrpcglink-apps-dsp",(edge,"channel")
    assert inspect_pstore(p,patched=True)["ecc_size"]==[48],"P461 ECC48 missing"
    return {"parent":parent,"remaining_cb":chosen,"sids":["0x1003","0x1004","0x1005"],
            "tbu":"ADSP only","smmu_phandle":smmu,"rpmsg":edge,
            "removed":removed,"status":"PREBUILD DTB ONLY - downstream driver NOT ported"}
def main():
    a=argparse.ArgumentParser()
    a.add_argument("--boot",type=Path,required=True)
    a.add_argument("--dtb-out",type=Path,required=True)
    a.add_argument("--report",type=Path,required=True)
    o=a.parse_args()
    dtb=parse(o.boot.read_bytes())["dtb"]
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"adsp-only.dtb";p.write_bytes(dtb)
        info=stage(p);new=p.read_bytes()
    o.dtb_out.write_bytes(new)
    info.update({"input_dtb_sha256":hashlib.sha256(dtb).hexdigest(),
                 "staged_dtb_sha256":hashlib.sha256(new).hexdigest(),
                 "verified_dtb_out_sha256":hashlib.sha256(o.dtb_out.read_bytes()).hexdigest()})
    if info["staged_dtb_sha256"]!=info["verified_dtb_out_sha256"]:
        raise RuntimeError("P461 DTB output corruption")
    o.report.write_text(json.dumps(info,indent=2,sort_keys=True)+"\n")
    print("P461 ADSP-ONLY DTB STAGED (NOT FLASHABLE, NO DRIVER): "+json.dumps(info,sort_keys=True))
if __name__=="__main__":main()
