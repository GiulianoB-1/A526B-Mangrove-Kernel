#!/usr/bin/env python3
"""P467 exactly one downstream-TG ABI compatible UIO RMTFS device.
Do not substitute mainline qcom_rmtfs_mem or fake SCM assignment.
"""
import argparse,hashlib,json
from pathlib import Path
TAG="P467 RMTFS UIO"
FILE=Path("drivers/uio/a52_mss_rmtfs_uio.c")
SRC=Path("vendor/p467/a52_mss_rmtfs_uio.c")
MK=Path("drivers/uio/Makefile")
KC=Path("drivers/uio/Kconfig")

def patch(root):
    original=SRC.read_text()
    dest=root/FILE
    if dest.exists():raise RuntimeError("P467 RMTFS refusing existing UIO driver")
    mk=(root/MK).read_text()
    kc=(root/KC).read_text()
    if "A52_MSS_RMTFS_UIO" in mk or "A52_MSS_RMTFS_UIO" in kc:
        raise RuntimeError("P467 RMTFS duplicate build registration")
    dest.write_text(original)
    (root/MK).write_text(mk+"\n# P467 downstream /dev/uio0 rmt_storage ABI, not qcom_rmtfs_mem\nobj-$(CONFIG_A52_MSS_RMTFS_UIO) += a52_mss_rmtfs_uio.o\n")
    conf='''\nconfig A52_MSS_RMTFS_UIO
    bool "P467 SM6350 downstream RMTFS /dev/uio0 ABI (manual MSS)"
    depends on UIO && QCOM_SCM && OF
    default n
    help
      Exact qcom,sharedmem-uio, client 1, 0x280000 and guard pads;
      deferred until manual SCM registration; qcom_scm_assign_mem.
      Does not boot modem or expose a fake /dev/qcom_rmtfs_mem.
'''
    if "\nendmenu" in kc:
        kc=kc.replace("\nendmenu",conf+"\nendmenu",1)
    else:
        kc+=conf
    (root/KC).write_text(kc)

def check(root):
    text=(root/FILE).read_text()
    donor=SRC.read_text()
    if text!=donor:raise RuntimeError("P467 RMTFS generated C differs from pinned source")
    if (root/MK).read_text().count("obj-$(CONFIG_A52_MSS_RMTFS_UIO)")!=1:
        raise RuntimeError("P467 RMTFS Makefile mismatch")
    if (root/KC).read_text().count("config A52_MSS_RMTFS_UIO")!=1:
        raise RuntimeError("P467 RMTFS Kconfig duplicate")
    for token in (TAG, 'qcom,sharedmem-uio', 'qcom,client-id',
                  'qcom,guard-memory', 'P467_RMTFS_SIZE 0x280000U',
                  'P467_RMTFS_CLIENT_ID 1U',
                  'qcom_scm_is_available()', 'return -EPROBE_DEFER;',
                  'dma_alloc_coherent', 'dma_to_phys',
                  'qcom_scm_assign_mem', 'QCOM_SCM_VMID_MSS_MSA',
                  'UIO_MEM_PHYS', 'uio_register_device', 'uio_unregister_device',
                  'remap_pfn_range','P467 RMTFS UIO client='):
        if token not in text:raise RuntimeError("P467 RMTFS missing ABI/SCM "+token)
    if 'qcom,rmtfs-mem' in text or 'hyp_assign_phys' in text:
        raise RuntimeError("P467 RMTFS accidentally uses wrong mainline/legacy ABI")
    return {"compat":"qcom,sharedmem-uio", "device":"first available /dev/uioN (expect uio0)",
            "name":"rmtfs","size":0x280000,"client_id":1,
            "guard_bytes_each_side":4096,
            "scm":"real qcom_scm_assign_mem(HLOS,MSS_MSA) or fail",
            "scm_off":"EPROBE_DEFER","manual_pas":True,
            "driver_sha256":hashlib.sha256(text.encode()).hexdigest()}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    if not a.check_only:patch(a.root)
    result=check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2)+"\n")
    print("P467 RMTFS UIO SOURCE PASS "+json.dumps(result))
if __name__=="__main__":main()
