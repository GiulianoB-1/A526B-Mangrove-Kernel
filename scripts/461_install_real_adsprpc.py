#!/usr/bin/env python3
"""P461 experimental native downstream adsprpc source port.

Donor (immutable):
LineageOS/android_kernel_qcom_sm8450@952aa00564cbb2cc788378c97e08958c4b889758
This is NOT a renaming of upstream drivers/misc/fastrpc.c.
Fail closed on unexpected donor changes. Compile/link and runtime MUST pass
before any generated boot.img may be considered suitable for flashing.
"""
import argparse, re, shutil
from pathlib import Path

TAG="A52_P461_DOWNSTREAM_ADSPRPC_5_10_SOURCE_PORT_V1"
FILES=("drivers/char/adsprpc.c","drivers/char/adsprpc_shared.h",
       "drivers/char/adsprpc_compat.c","drivers/char/adsprpc_compat.h",
       "include/linux/fastrpc.h","include/trace/events/fastrpc.h",
       "include/linux/qcom-dma-mapping.h",
       "include/linux/msm_dma_iommu_mapping.h",
       "include/soc/qcom/secure_buffer.h","include/uapi/linux/msm_ion.h",
       "include/linux/mem-buf.h","include/soc/qcom/ramdump.h",
       "include/soc/qcom/qcom_ramdump.h",
       "include/linux/remoteproc/qcom_rproc.h",
       "include/soc/qcom/socinfo.h","include/soc/qcom/minidump.h",
       "include/uapi/linux/msm_ion_ids.h")
ROOT=Path("vendor/p461/qualcomm-5.10")
REQUIRED_ABI=[
 "FASTRPC_IOCTL_INVOKE","FASTRPC_IOCTL_MMAP","FASTRPC_IOCTL_MUNMAP",
 "FASTRPC_IOCTL_INVOKE_FD","FASTRPC_IOCTL_SETMODE",
 "FASTRPC_IOCTL_INIT","FASTRPC_IOCTL_INVOKE_ATTRS",
 "FASTRPC_IOCTL_GETINFO","FASTRPC_IOCTL_INIT_ATTRS",
 "FASTRPC_IOCTL_INVOKE_CRC","FASTRPC_IOCTL_CONTROL",
 "FASTRPC_IOCTL_MUNMAP_FD","FASTRPC_IOCTL_MMAP_64",
 "FASTRPC_IOCTL_MUNMAP_64","FASTRPC_IOCTL_GET_DSP_INFO"]
def replace1(s,old,new,reason):
    if s.count(old)!=1:
        raise RuntimeError("P461 donor anchor drift "+reason+" count="+str(s.count(old)))
    return s.replace(old,new,1)
def edit_c(s):
    if TAG in s:return s
    # No eager child device creation on probe. These devices own the 3 SIDs:
    # of_platform_populate() itself can trigger IOMMU DMA configure/attach.
    # Delay ALL CB children until first ADSP GETINFO with live RPMSG.
    c=r'''
/* A52_P461_DOWNSTREAM_ADSPRPC_5_10_SOURCE_PORT_V1
 * P457 apps-SMMU, Phase206 suspend veto and P460b remain unchanged.
 * CB child OF platform devices are created ONLY at first ADSP session.
 */
static const struct of_device_id fastrpc_match_table[];
static DEFINE_MUTEX(a52_p461_cb_mutex);
static struct device *a52_p461_parent_dev;
static bool a52_p461_cb_populated;

static int a52_p461_lazy_cbs(void)
{
    int ret;
    if (!of_machine_is_compatible("qcom,lagoon"))
        return 0;
    if (!READ_ONCE(gcinfo[ADSP_DOMAIN_ID].rpdev))
        return -ENOTCONN;
    mutex_lock(&a52_p461_cb_mutex);
    if (!a52_p461_cb_populated) {
        if (!a52_p461_parent_dev) {
            ret = -ENODEV;
            goto done;
        }
        ret = of_platform_populate(a52_p461_parent_dev->of_node,
                                   fastrpc_match_table, NULL,
                                   a52_p461_parent_dev);
        if (ret)
            goto done;
        if (gcinfo[ADSP_DOMAIN_ID].sesscount < 3) {
            ret = -ENODEV;
            goto done;
        }
        a52_p461_cb_populated = true;
        pr_info("P461 FASTRPC SMMU ATTACH first-session cb-count=%d (child-owned)\n",
                gcinfo[ADSP_DOMAIN_ID].sesscount);
    }
    ret = 0;
done:
    mutex_unlock(&a52_p461_cb_mutex);
    return ret;
}
'''
    # Place this helper after gcinfo's definition and before fastrpc_get_info
    # to avoid global incomplete types and forward-reference errors.
    anchor="static int fastrpc_get_info(struct fastrpc_file *fl, uint32_t *info)"
    s=replace1(s,anchor,c+"\n"+anchor,"insert lazy helper")
    # GETINFO already declares err; no declarations after statements.
    needle="\tVERIFY(err, fl != NULL);\n"
    if needle not in s:raise RuntimeError("missing get_info verification")
    start=s.index(anchor)
    at=s.index(needle,start)
    s=s[:at]+'''    if (of_machine_is_compatible("qcom,lagoon")) {
        if (cid != ADSP_DOMAIN_ID) {
            err = -ENODEV;
            goto bail;
        }
        err = a52_p461_lazy_cbs();
        if (err)
            goto bail;
    }
'''+s[at:]
    # Prevent parent probe from instantiating child devices before session.
    patt=r'(\terr = of_platform_populate\(pdev->dev.of_node,\s+fastrpc_match_table,\s+NULL, &pdev->dev\);)'
    m=list(re.finditer(patt,s))
    if len(m)!=1:raise RuntimeError("P461 missing unique of_platform_populate: "+str(len(m)))
    original=m[0].group(1)
    s=s.replace(original,'''    if (of_machine_is_compatible("qcom,lagoon")) {
        a52_p461_parent_dev = &pdev->dev;
        pr_info("P461 FASTRPC PROBE ADSP-only; CB attach deferred until first session\\n");
        err = 0;
    } else {
'''+original+'''
    }''',1)
    # Existing original cb driver is retained. Log each real SID as it binds.
    anchor="\tsess->smmu.enabled = 1;"
    s=replace1(s,anchor,anchor+'''
    if (of_machine_is_compatible("qcom,lagoon")) {
        if (cid != ADSP_DOMAIN_ID ||
            iommuspec.args_count != 2 ||
            iommuspec.args[0] < 0x1003 ||
            iommuspec.args[0] > 0x1005) {
            pr_err("P461 FASTRPC SMMU ATTACH rejected cid=%d sid=%#x\\n",
                   cid, iommuspec.args[0]);
            return -EINVAL;
        }
        pr_info("P461 FASTRPC SMMU ATTACH child=%s SID=%#x\\n",
                dev_name(dev), iommuspec.args[0]);
        if (!me->dev)
            me->dev = dev; /* never global apps-SMMU parent */
    }
''',"child SID guard")
    # At open time do not keep sscrpcd stuck while ADSP is down.
    start=s.index("static int fastrpc_device_open(struct inode *inode, struct file *filp)")
    anchor="\tVERIFY(err, ((dev_minor == MINOR_NUM_DEV) ||"
    at=s.index(anchor,start)
    s=s[:at]+'''    if (of_machine_is_compatible("qcom,lagoon") &&
        !READ_ONCE(gcinfo[ADSP_DOMAIN_ID].rpdev))
        return -ENOTCONN;
    if (of_machine_is_compatible("qcom,lagoon"))
        pr_info("P461 FASTRPC OPEN pid=%d minor=%d\\n", current->pid, dev_minor);
'''+s[at:]
    # RPMSG channel is selected by actual A52 ADSP GLINK label.
    anchor="\tgcinfo[cid].rpdev = rpdev;"
    s=replace1(s,anchor,'''    if (of_machine_is_compatible("qcom,lagoon") &&
        cid != ADSP_DOMAIN_ID) {
        mutex_unlock(&gcinfo[cid].rpmsg_mutex);
        return -ENODEV;
    }
'''+anchor+'''
    if (of_machine_is_compatible("qcom,lagoon"))
        pr_info("P461 FASTRPC RPMSG UP cid=%d name=%s\\n",
                cid, rpdev->id.name);''',"ADSP RPMSG only")
    # No unconditional static PD PDR startup. Vendor first sensors attach
    # still sends a *real* FastRPC process-group invoke after this log-only
    # PDR check. Explicitly reject when channel has disappeared.
    anchor="static int fastrpc_check_pd_status(struct fastrpc_file *fl, char *sloc_name)\n{"
    s=replace1(s,anchor,anchor+'''
    if (of_machine_is_compatible("qcom,lagoon")) {
        bool up=(fl->cid==ADSP_DOMAIN_ID &&
                 READ_ONCE(gcinfo[ADSP_DOMAIN_ID].rpdev)!=NULL);
        pr_info("P461 FASTRPC PDR-STUB log-only service=%s up=%d\\n",
                sloc_name ? sloc_name : "none", up);
        return up ? 0 : -ENOTCONN;
    }
''',"PDR log only")
    # Same internal_invoke call appears elsewhere in the donor; only
    # annotate the actual ATTACH_SENSORS function, not unrelated invocations.
    anchor="err = fastrpc_internal_invoke(fl, FASTRPC_MODE_PARALLEL, KERNEL_MSG_WITH_ZERO_PID, &ioctl);"
    first=s.index("static int fastrpc_init_attach_process(")
    last=s.index("static int fastrpc_init_create_dynamic_process(",first)
    block=s[first:last]
    block=replace1(block,anchor,'''if (of_machine_is_compatible("qcom,lagoon") &&
        init->flags==FASTRPC_INIT_ATTACH_SENSORS)
        pr_info("P461 FASTRPC PD_START begin cid=%d\\n", fl->cid);
    '''+anchor+'''
    if (of_machine_is_compatible("qcom,lagoon") &&
        init->flags==FASTRPC_INIT_ATTACH_SENSORS)
        pr_info("P461 FASTRPC PD_START result=%d\\n", err);''',
                   "sensors PD outcome")
    s=s[:first]+block+s[last:]
    # P461 scope explicitly excludes CDSP CMA/minidump allocation at init.
    s=replace1(s,"if (i == CDSP_DOMAIN_ID) {",
       'if (i == CDSP_DOMAIN_ID && !of_machine_is_compatible("qcom,lagoon")) {',
       "no CDSP CMA allocation")
    # This path uses GLOBAL me->dev rather than the CB child's DMA owner.
    # On lagoon it must not be permitted to map user DMA buffers.
    anchor="} else if (mflags == FASTRPC_MAP_FD_NOMAP) {"
    s=replace1(s,anchor,''' } else if (mflags == FASTRPC_MAP_FD_NOMAP &&
                  of_machine_is_compatible("qcom,lagoon")) {
        err=-EOPNOTSUPP; /* unsupported global-device DMA path */
        goto bail;
    '''+anchor,"reject unsafe global NOMAP path")
    return s

def do(root):
    if not ROOT.is_dir():raise RuntimeError("P461 missing pinned donor files")
    for rel in FILES:
        source=ROOT/rel;target=root/rel
        if not source.is_file():raise RuntimeError("missing donor "+rel)
        if rel=="drivers/char/adsprpc.c":
            data=edit_c(source.read_text())
        else:
            data=source.read_text()
        if rel=="include/linux/qcom-dma-mapping.h":
            # Common 5.10 already defines these with platform-owned bit
            # assignments. Keep the GKI definitions instead of redefining
            # DMA attributes with potentially incompatible Qualcomm bits.
            for attr in ("DMA_ATTR_DELAYED_UNMAP",
                         "DMA_ATTR_IOMMU_USE_UPSTREAM_HINT",
                         "DMA_ATTR_IOMMU_USE_LLC_NWA"):
                pattern=r"(?m)^(#define "+attr+r"\\s+[^\\n]+)$"
                data,n=re.subn(pattern,
                    lambda m:"#ifndef "+attr+"\\n"+m.group(1)+"\\n#endif",
                    data)
                if n != 1:
                    raise RuntimeError("P461 DMA attribute anchor drift "+attr)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(data)
    mk=root/"drivers/char/Makefile"
    m=mk.read_text()
    line="obj-$(CONFIG_MSM_ADSPRPC)\t+= a52-frpc-adsprpc.o\n"
    objs="a52-frpc-adsprpc-objs := adsprpc.o adsprpc_compat.o\n"
    if line not in m:mk.write_text(m+"\n"+objs+line)
    k=root/"drivers/char/Kconfig";s=k.read_text()
    block='''\nconfig MSM_ADSPRPC
    bool "A52 experimental downstream FastRPC (no CDSP/audio/remoteheap)"
    depends on ARM64 && RPMSG && IOMMU_SUPPORT
    default n
    help
      Qualcomm 5.10 downstream adsprpc ioctls and ADSP-only GLINK.
      Experimental P461; requires kernel compile, ABI and runtime checks.
'''
    if "config MSM_ADSPRPC" not in s:k.write_text(s+block)
    print("P461 DOWNSTREAM SOURCE INSTALLED",TAG,
          "driver=drivers/char/adsprpc.c","unverified_compile=true")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--check-only",action="store_true")
    a=p.parse_args()
    if a.check_only:
        s=(a.root/"drivers/char/adsprpc.c").read_text()
        for marker in ("P461 FASTRPC PROBE","P461 FASTRPC OPEN",
                       "P461 FASTRPC RPMSG UP",
                       "P461 FASTRPC SMMU ATTACH",
                       "P461 FASTRPC PD_START"):
            if marker not in s:raise RuntimeError("P461 compiled source lacks "+marker)
        if "FASTRPC_IOCTL_GETPERF" in (a.root/"drivers/char/adsprpc_shared.h").read_text():
            print("P461 ABI WARNING: check donor GETPERF commented-out, not supported")
        print("P461 ADSPRPC SOURCE GATE PASS (NOT kernel compile/runtime)")
    else:do(a.root)
if __name__=="__main__":
    main()
