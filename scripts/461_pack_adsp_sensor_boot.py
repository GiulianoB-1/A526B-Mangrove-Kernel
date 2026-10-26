#!/usr/bin/env python3
"""P461 package actual G boot with only ADSP FastRPC context-bank nodes.

This is a *real* boot image modification to accompany enabled downstream
FastRPC source, rather than the previous non-flashable prebuild DTB.
No kernel/ramdisk/cmdline/SCM/ADSP knob changes. ECC48 canonical preserved.
"""
import argparse,hashlib,json,runpy,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
P=runpy.run_path("scripts/458_pstore_ecc48_dtb.py")
parse=P["parse"];repack=P["repack"]
import importlib.util
spec=importlib.util.spec_from_file_location("p461audit","scripts/461_dtbo_live_audit.py")
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
def check(dtb):
    tree=module.fdt(dtb)
    parents=[p for p,v in tree.items() if b"qcom,msm-fastrpc-compute" in
            v.get("compatible",b"").split(b"\0")]
    if len(parents)!=1:raise RuntimeError("P461 wrong compute parent count "+str(parents))
    parent=parents[0]
    children=[p for p in tree if p.startswith(parent+"/") and p.count("/")==parent.count("/")+1]
    expected={parent+"/qcom,msm_fastrpc_compute_cb"+str(k) for k in (10,11,12)}
    if set(children)!=expected:raise RuntimeError("P461 CDSP/extra context bank present: "+str(children))
    expected_sids={10:0x1003,11:0x1004,12:0x1005}
    for num,sid in expected_sids.items():
        n=tree[parent+"/qcom,msm_fastrpc_compute_cb"+str(num)]
        val=n.get("iommus",b"")
        if len(val)!=12 or int.from_bytes(val[4:8],"big")!=sid:
            raise RuntimeError("P461 SID ownership wrong cb "+str(num))
    ramoops=module.suspicious(tree)
    if len(ramoops)!=1 or ramoops[0]["ecc-size"]!=["0x30"]:
        raise RuntimeError("P461 canonical ramoops ECC48 lost "+str(ramoops))
    r=ramoops[0]
    if r["path"]!="/reserved-memory/ramoops@B1B00000":
        raise RuntimeError("P461 unexpected ramoops identity "+str(r))
    edges=[p for p,v in tree.items()
           if b"qcom,msm-fastrpc-rpmsg" in v.get("compatible",b"").split(b"\0")]
    # TG's actual ADSP edge is named qcom,lpass@3000000, not "adsp".
    # Require that exact parent and channel, excluding modem/CDSP edges.
    adsp=[p for p in edges if
          p.startswith("/soc/qcom,lpass@3000000/glink-edge/") and
          module.strings(tree[p].get("qcom,glink-channels",b""))==["fastrpcglink-apps-dsp"]]
    if len(adsp)!=1:
        raise RuntimeError("P461 ADSP FastRPC RPMSG missing/ambiguous: "+str(edges))
    return {"adsp_sids":[hex(x) for x in expected_sids.values()],
            "context_bank_paths":sorted(expected),"adsp_rpmsg":adsp[0],
            "ramoops":r}
def main():
    a=argparse.ArgumentParser()
    a.add_argument("--boot",type=Path,required=True)
    a.add_argument("--dtb",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    a.add_argument("--report",type=Path,required=True)
    x=a.parse_args()
    boot=x.boot.read_bytes();d=parse(boot)
    new=x.dtb.read_bytes()
    checkdata=check(new)
    result=repack(boot,d,new)
    reparsed=parse(result)
    if reparsed["dtb"]!=new:raise RuntimeError("P461 final image used stale DTB")
    for k in ("kernel","ramdisk","cmdline","recovery_dtbo","second"):
        if d[k]!=reparsed[k]:raise RuntimeError("P461 repack changed "+k)
    x.output.write_bytes(result)
    report=dict(checkdata,boot_sha256=hashlib.sha256(result).hexdigest(),
                dtb_sha256=hashlib.sha256(new).hexdigest(),
                source_boot_sha256=hashlib.sha256(boot).hexdigest(),
                pstore_registered_runtime=False,
                fastrpc_sensors_runtime=False,
                status="packaged for actual hardware acceptance; not yet proven")
    x.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("P461 ADSP SENSOR BOOT PACKAGED",json.dumps(report,sort_keys=True))
if __name__=="__main__":main()
