#!/usr/bin/env python3
"""P461 downstream Qualcomm 5.10 adsprpc source graft, disabled by default.

THIS IS NOT A CLAIM OF A FUNCTIONAL PORT. The exact donor driver and compat
sources are real Qualcomm code. An explicit --enable will graft it into the
5.10 source and enable CONFIG_MSM_ADSPRPC, but only after --preflight proves
required platform interfaces are present; never build a fake stub or ioctl.
"""
import argparse,hashlib,json,shutil,sys
from pathlib import Path

FILES=("adsprpc.c","adsprpc_compat.c","adsprpc_compat.h","adsprpc_shared.h")
HEADERS=(
    "include/linux/msm_ion.h",
    "include/linux/qcom-dma-mapping.h",
    "include/linux/mem-buf.h",
    "include/linux/fastrpc.h",
    "include/linux/ipc_logging.h",
    "include/linux/msm_dma_iommu_mapping.h",
    "include/soc/qcom/secure_buffer.h",
    "include/soc/qcom/qcom_ramdump.h",
    "include/trace/events/fastrpc.h",
)
PROVIDERS=(
    "drivers/staging/android/ion/Makefile",
    "drivers/soc/qcom/Makefile",
    "drivers/iommu/Makefile",
    "drivers/rpmsg/Makefile",
)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    a=argparse.ArgumentParser()
    a.add_argument("--root",required=True,type=Path)
    a.add_argument("--vendor",type=Path,default=Path("vendor/p461/a52-5.10-port/drivers/char"))
    a.add_argument("--enable",action="store_true")
    a.add_argument("--report",type=Path)
    o=a.parse_args()
    if not o.root.is_dir() or not (o.root/"Makefile").is_file():
        raise RuntimeError("P461 missing GKI source")
    if not all((o.vendor/f).is_file() for f in FILES):
        raise RuntimeError("P461 pinned downstream 5.10 donor import missing")
    driver=(o.vendor/"adsprpc.c").read_text()
    compat=(o.vendor/"adsprpc_compat.c").read_text()
    shared=(o.vendor/"adsprpc_shared.h").read_text()
    required=("A52_FASTRPC_IOCTL_GET_DSP_INFO_LEGACY",
              "a52_fastrpc_legacy_get_dsp_info",
              "fastrpc_get_info_from_kernel",
              "FASTRPC_GLINK_GUID",
              "qcom,msm-fastrpc-compute-cb")
    if not all(v in driver+shared for v in required):
        raise RuntimeError("P461 missing genuine downstream ABI functions")
    if "A52_FASTRPC_IOCTL_GET_DSP_INFO_LEGACY" not in compat:
        raise RuntimeError("P461 missing legacy ioctl16 32-bit compat")
    missing=[str(p) for p in HEADERS+PROVIDERS if not (o.root/p).is_file()]
    audit={
        "marker":"P461 FASTRPC DONOR SOURCE AUDIT",
        "source":"LineageOS/android_kernel_qcom_sm8450@952aa00564cbb2cc788378c97e08958c4b889758",
        "driver_bytes":(o.vendor/"adsprpc.c").stat().st_size,
        "driver_sha256":sha(o.vendor/"adsprpc.c"),
        "compat_sha256":sha(o.vendor/"adsprpc_compat.c"),
        "vendor_legacy_ioctl_16":True,
        "vendor_legacy_ioctl_9_getperf":"MISSING: cannot report full ABI support",
        "missing_headers_and_providers":missing,
        "enabled":False,
        "functional_fast_rpc":False,
        "notes":"No fake downstream headers, missing memory-mapping/assignment operations or fake /dev devices permitted"
    }
    if o.report:
        o.report.parent.mkdir(parents=True,exist_ok=True)
        o.report.write_text(json.dumps(audit,indent=2,sort_keys=True)+"\n")
    if not o.enable:
        print(json.dumps(audit,indent=2,sort_keys=True))
        return
    if missing:
        raise RuntimeError("P461 unsafe to enable real 5.10 adsprpc: absent mandatory interfaces: "+
                           ", ".join(missing))
    target=o.root/"drivers/char"
    for f in FILES:
        shutil.copy2(o.vendor/f,target/f)
    k=target/"Kconfig"; mk=target/"Makefile"
    kc=k.read_text()
    if "config MSM_ADSPRPC" not in kc:
        kc += """
config MSM_ADSPRPC
\tbool "Qualcomm downstream 5.10 FastRPC (P461 experimental)"
\tdepends on RPMSG && IOMMU_SUPPORT && DMA_SHARED_BUFFER && OF
\tdefault n
\thelp
\t  Downstream adsprpc ABI, must use actual ADSP context-bank SIDs.

"""
        k.write_text(kc)
    mf=mk.read_text()
    if "CONFIG_MSM_ADSPRPC" not in mf:
        mk.write_text(mf+"""
frpc-adsprpc-y := adsprpc.o
frpc-adsprpc-$(CONFIG_COMPAT) += adsprpc_compat.o
obj-$(CONFIG_MSM_ADSPRPC) += frpc-adsprpc.o
""")
    print("P461 FASTRPC SOURCE GRAFTED: hardware acceptance NOT VERIFIED")
if __name__=="__main__":main()
