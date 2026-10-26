#!/usr/bin/env python3
"""P462: normalize the actual boot-v2 ramoops consumer for DTBO idx=1 merge.

DO NOT patch or flash DTBO here. Create the same TG uppercase node name
reported in the live FDT; remove the duplicate a52-ramoops-reserved node.
This is a *candidate* until collector confirms one live ECC48 node and
"pstore: Registered". The DTBO may override values after U-Boot/ABL fixups.
"""
import argparse,hashlib,json,runpy,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
P=runpy.run_path("scripts/458_pstore_ecc48_dtb.py")
parse=P["parse"];repack=P["repack"]
from u1_patch_boot_dtb import walk
TARGET="/reserved-memory/ramoops@B1B00000"
PHYS=[0,0xB1B00000,0,0x100000]
ZONES=("record-size","console-size","ftrace-size","pmsg-size")

def run(*args,optional=False):
    out=subprocess.run([str(a) for a in args],capture_output=True,text=True)
    if out.returncode and not optional:
        raise RuntimeError("P462 fdt command "+repr(args)+" "+out.stderr[-500:])
    return out.stdout.strip() if not out.returncode else None
def cells(path,node,key):
    got=run("fdtget","-t","x",path,node,key,optional=True)
    return None if got is None else [int(v,16) for v in got.split()]
def paths_with_ramoops(raw):
    props=walk(raw)
    names={v[0] for v in props}
    compatible={v[0] for v in props if v[1]=="compatible" and
                b"ramoops" in v[5].split(b"\0")}
    return {n for n in names if "ramoops" in n.rsplit("/",1)[-1].lower()} | compatible
def validate(path):
    raw=path.read_bytes()
    paths=paths_with_ramoops(raw)
    if paths!={TARGET}:
        raise RuntimeError("P462 final ramoops nodes are not exactly canonical: "+repr(paths))
    if run("fdtget","-t","s",path,TARGET,"compatible")!="ramoops":
        raise RuntimeError("P462 canonical node lacks ramoops compatible")
    if cells(path,TARGET,"reg")!=PHYS:
        raise RuntimeError("P462 canonical ramoops physical region drift")
    if cells(path,TARGET,"ecc-size")!=[48]:
        raise RuntimeError("P462 canonical ramoops ECC48 missing")
    for k in ZONES:
        if cells(path,TARGET,k)!=[0x40000]:
            raise RuntimeError("P462 TG 256KiB "+k+" missing")
    return {"node":TARGET,"ecc_size":48,"reg":PHYS,
            "sizes":{k:0x40000 for k in ZONES},
            "total_zone_bytes":0x100000,"overlapping_node_count":1,
            "runtime_pstore_registered":False}

def patch(raw):
    with tempfile.TemporaryDirectory() as tmp:
        f=Path(tmp)/"dtb";f.write_bytes(raw)
        nodes=paths_with_ramoops(raw)
        if not nodes:
            raise RuntimeError("P462 missing any ramoops nodes; refuse create blindly")
        for n in nodes:
            if n==TARGET:continue
            if not n.startswith("/reserved-memory/"):
                raise RuntimeError("P462 unrelated ramoops path "+n)
            if n.rsplit("/",1)[-1].lower()!="a52-ramoops-reserved@b1b00000":
                raise RuntimeError("P462 refusing remove unexpected ramoops node "+n)
            if cells(f,n,"reg")!=PHYS:
                raise RuntimeError("P462 old node reg not physical B1B00000: "+n)
            if cells(f,n,"phandle") or cells(f,n,"linux,phandle"):
                raise RuntimeError("P462 old node has phandle references: "+n)
            run("fdtput","-r",f,n)
        if TARGET not in nodes:
            run("fdtput","-c",f,TARGET)
        run("fdtput","-t","s",f,TARGET,"compatible","ramoops")
        run("fdtput","-t","x",f,TARGET,"reg",*[hex(v) for v in PHYS])
        run("fdtput","-t","x",f,TARGET,"ecc-size","0x30")
        for k in ZONES:
            run("fdtput","-t","x",f,TARGET,k,"0x40000")
        info=validate(f)
        return f.read_bytes(),info

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--boot",type=Path,required=True)
    ap.add_argument("--output",type=Path)
    ap.add_argument("--report",type=Path)
    ap.add_argument("--check-only",action="store_true")
    a=ap.parse_args()
    blob=a.boot.read_bytes();image=parse(blob)
    if a.check_only:
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"dtb";path.write_bytes(image["dtb"])
            info=validate(path)
        print("P462 FINAL ECC48 CANONICAL PASS",json.dumps(info,sort_keys=True))
        return
    if not a.output or not a.report:
        ap.error("--output and --report required")
    new,info=patch(image["dtb"])
    out=repack(blob,image,new)
    info.update({"boot_sha256":hashlib.sha256(out).hexdigest(),
                 "dtb_sha256":hashlib.sha256(new).hexdigest(),
                 "boot_unchanged_except_embedded_dtb_and_id":True,
                 "live_dt_verified":False,
                 "dtbo_idx_1_verified":False,
                 "acceptance":"one live ramoops@B1B00000, ECC48, pstore: Registered"})
    a.output.write_bytes(out)
    a.report.write_text(json.dumps(info,indent=2,sort_keys=True)+"\n")
    print("P462 PACKAGED CANONICAL RAMOOPS (LIVE NOT VERIFIED)",json.dumps(info,sort_keys=True))
if __name__=="__main__":
    main()
