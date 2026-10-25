#!/usr/bin/env python3
"""P461: ONLY IF THE DOWNSTREAM DRIVER COMPILED, put ADSP-only FDT into boot-v2.
The output is UNVALIDATED on device. Preserve kernel, ramdisk, cmdline and all
other boot components and fail if any CDSP FastRPC SID remains.
"""
import argparse, hashlib, json, runpy, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
base=runpy.run_path("scripts/458_pstore_ecc48_dtb.py")
boot=runpy.run_path("scripts/38_repack_a52_p1_boot.py")
parse=boot["parse_boot"];repack=base["repack"];ramoops=base["inspect"]
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--boot",type=Path,required=True)
    p.add_argument("--dtb",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    original=a.boot.read_bytes();data=parse(original)
    candidate=a.dtb.read_bytes()
    if not candidate.startswith(b"\xd0\x0d\xfe\xed"):
        raise RuntimeError("P461 FDT header missing")
    with tempfile.TemporaryDirectory() as d:
        f=Path(d)/"staged.dtb";f.write_bytes(candidate)
        if ramoops(f,True)["ecc_size"]!=[48]:
            raise RuntimeError("P461 staged FDT lost ECC48")
        st=runpy.run_path("scripts/461_stage_adsp_fastrpc_dtb.py")
        parents=[n for n in st["nodes"](f) if
                 st["prop"](f,n,"compatible")=="qcom,msm-fastrpc-compute"]
        if len(parents)!=1:raise RuntimeError("P461 compute parent not unique")
        names=st["children"](f,parents[0])
        expected=["qcom,msm_fastrpc_compute_cb"+str(i) for i in (10,11,12)]
        if sorted(names)!=sorted(expected):
            raise RuntimeError("P461 CDSP CBs still present: "+repr(names))
        _,smmu=st["unique_apps_smmu"](f)
        for i in (10,11,12):
            st["check_cb"](f,parents[0]+"/"+expected[i-10],i,smmu)
    result=repack(original,data,candidate)
    final=parse(result)
    if final["dtb"]!=candidate:
        raise RuntimeError("P461 wrong FDT in repacked boot")
    a.output.write_bytes(result)
    report={
      "tag":"P461 ADSPRPC UNVALIDATED BOOT-V2",
      "original_boot_sha256":sha(original),
      "output_boot_sha256":sha(result),
      "source_dtb_sha256":sha(data["dtb"]),
      "output_dtb_sha256":sha(candidate),
      "original_kernel_sha256":sha(data["kernel"]),
      "unchanged_components":["kernel","ramdisk","second","recovery_dtbo","cmdline"],
      "only_ADSP_fastRPC_SIDs":["0x1003","0x1004","0x1005"],
      "downstream_adsprpc_linked":"MUST VERIFY SEPARATELY BEFORE UPLOAD",
      "runtime_result":"NOT TESTED; DO NOT FLASH"
    }
    a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("P461 ADSP-ONLY BOOT IMAGE PACKAGED BUT NOT VALIDATED",sha(result))
if __name__=="__main__":main()
