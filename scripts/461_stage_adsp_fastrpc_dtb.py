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
def unique_apps_smmu(p):
    # Exact physical TCU identity and TG 2-cell translator, not KGSL SMMU.
    matches=[]
    for n in nodes(p):
        if n.rsplit("/",1)[-1] != "apps-smmu@15000000":
            continue
        compatible=(prop(p,n,"compatible") or "").split()
        if "qcom,qsmmu-v500" not in compatible:
            continue
        if cells(p,n,"#iommu-cells") != [2]:
            continue
        if "qcom,skip-init" not in (run("fdtget","-p",p,n) or "").splitlines():
            continue
        reg=cells(p,n,"reg")
        if not reg or 0x15000000 not in reg[:2]:
            continue
        ph=cells(p,n,"phandle")
        if not ph:
            ph=cells(p,n,"linux,phandle")
        if ph and len(ph)==1 and ph[0]!=0:
            matches.append((n,ph[0]))
    if len(matches)!=1:
        raise RuntimeError("P461 cannot prove unique 0x15000000 apps-SMMU phandle "
                           +repr(matches))
    return matches[0]

def add_cb(p,parent,n,smmu):
    dst=parent+"/qcom,msm_fastrpc_compute_cb"+str(n)
    if dst in set(nodes(p)):
        raise RuntimeError("P461 refusing to overwrite existing "+dst)
    run("fdtput","-c",p,dst)
    run("fdtput","-t","s",p,dst,"compatible","qcom,msm-fastrpc-compute-cb")
    run("fdtput","-t","s",p,dst,"label","adsprpc-smd")
    run("fdtput","-t","x",p,dst,"iommus",hex(smmu),hex(0x1003+n-10),"0")
    run("fdtput","-t","x",p,dst,"qcom,iommu-dma-addr-pool",
        "0x80000000","0x78000000")
    run("fdtput","-t","s",p,dst,"qcom,iommu-faults",
        "stall-disable","HUPCF")
    run("fdtput",p,dst,"dma-coherent")
    if n==12:
        run("fdtput","-t","x",p,dst,"shared-cb","5")

def stage(p):
    parent_candidates=[n for n in nodes(p)
                       if "qcom,msm-fastrpc-compute" in
                       (prop(p,n,"compatible") or "").split()]
    if len(parent_candidates)>1:
        raise RuntimeError("P461 ambiguous existing fastrpc parents "
                           +repr(parent_candidates))
    smmu_node,smmu=unique_apps_smmu(p)
    generated=False
    if not parent_candidates:
        # P460b's TG-derived packaged DTB does not have this parent.
        # Create ONLY the ADSP subset from pinned TG lagoon.dtsi.
        parent="/soc/qcom,msm_fastrpc"
        if prop(p,"/soc","compatible") is None and "/soc" not in set(nodes(p)):
            raise RuntimeError("P461 cannot locate parent /soc")
        if parent in set(nodes(p)):
            raise RuntimeError("P461 existing parent without expected compatible")
        run("fdtput","-c",p,parent)
        run("fdtput","-t","s",p,parent,"compatible","qcom,msm-fastrpc-compute")
        run("fdtput","-t","x",p,parent,"qcom,rpc-latency-us","235")
        for cb in (10,11,12):
            add_cb(p,parent,cb,smmu)
        generated=True
    else:
        parent=parent_candidates[0]
    before=children(p,parent)
    chosen=["qcom,msm_fastrpc_compute_cb"+str(n) for n in (10,11,12)]
    removed=[]
    for name in before:
        if name in chosen:
            continue
        n=parent+"/"+name
        label=prop(p,n,"label")
        if label!="cdsprpc-smd" or not name.startswith("qcom,msm_fastrpc_compute_cb"):
            raise RuntimeError("P461 unexpected compute child: "+n+" label="+str(label))
        sid=cells(p,n,"iommus")
        if sid is None or len(sid)!=3 or sid[1] not in range(0x1401,0x140a):
            raise RuntimeError("P461 refusing unexpected CDSP SID: "+n+" "+repr(sid))
        run("fdtput","-r",p,n)
        removed.append({"node":n,"sid":sid[1]})
    if len(removed) not in (0,9):
        raise RuntimeError("P461 partial CDSP context banks "+repr(removed))
    for index,k in zip((10,11,12),chosen):
        check_cb(p,parent+"/"+k,index,smmu)
    if sorted(children(p,parent))!=sorted(chosen):
        raise RuntimeError("P461 ADSP-only node set incorrect: "
                           +repr(children(p,parent)))
    edge="/soc/qcom,lpass@3000000/glink-edge/qcom,msm_fastrpc_rpmsg"
    if prop(p,edge,"compatible")!="qcom,msm-fastrpc-rpmsg":
        raise RuntimeError("P461 existing ADSP RPMSG binding absent "+edge)
    if prop(p,edge,"qcom,glink-channels")!="fastrpcglink-apps-dsp":
        raise RuntimeError("P461 wrong ADSP RPMSG channel "+edge)
    if inspect_pstore(p,patched=True)["ecc_size"]!=[48]:
        raise RuntimeError("P461 ECC48 lost")
    return {"parent":parent,"generated_parent":generated,
            "smmu_node":smmu_node,"smmu_phandle":smmu,
            "remaining_cb":chosen,"sids":["0x1003","0x1004","0x1005"],
            "tbu":"ADSP only","rpmsg":edge,
            "removed":removed,
            "status":"PREBUILD DTB ONLY - downstream driver NOT ported"}
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
