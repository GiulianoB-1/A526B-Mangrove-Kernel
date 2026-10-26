#!/usr/bin/env python3
"""P461 SENSOR-FIRST actual Qualcomm 5.10 downstream adsprpc C port.

Port 5.10 donor source, NOT upstream drivers/misc/fastrpc.c. Fail closed
for unsupported optional features; all DMA-BUF imports use the ADSP CB child.
This is not runtime acceptance: CI must compile Image and hardware must
exercise /dev/adsprpc-smd[_secure], RPMSG and ATTACH_SENSORS.
"""
import argparse,hashlib,json,re,shutil
from pathlib import Path

DONOR=Path("vendor/p461/a52-5.10-port/drivers/char")
FILES=("adsprpc.c","adsprpc_compat.c","adsprpc_compat.h","adsprpc_shared.h")
MARK="P461_SENSORS_DOWNSTREAM_5_10_V1"

def replace_once(s,old,new,why):
    n=s.count(old)
    if n!=1: raise RuntimeError(f"P461 {why}: expected one anchor, got {n}")
    return s.replace(old,new,1)

def func(s,name):
    # Function definitions, not prototypes: match '{' on declaration.
    pat=r"(?m)^(?:static\s+)?(?:(?:inline|__always_inline|__maybe_unused|__init)\s+)*(?:int|void|long|bool|ssize_t|irqreturn_t)\s+(?:__\w+\s+)?"+re.escape(name)+r"\s*\([^;{}]*?\)\s*\{"
    m=re.search(pat,s,re.S)
    if m is None:raise RuntimeError(f"P461 function absent: {name}")
    depth=0;start=m.end()-1;i=start
    while i<len(s):
        if s[i]=='{':depth+=1
        elif s[i]=='}':
            depth-=1
            if depth==0:return m.start(),i+1
        i+=1
    raise RuntimeError("P461 unterminated "+name)

def body_replace(s,name,fn):
    a,b=func(s,name)
    return s[:a]+fn(s[a:b])+s[b:]

def reject_func(s,name,signature,what,ret):
    def build(old):
        return signature+""" {
\tpr_warn_once("P461 FASTRPC UNSUPPORTED """+what+""" rc=-EOPNOTSUPP\\n");
\treturn """+ret+""";
}"""
    return body_replace(s,name,build)

def transform(s):
    removed_headers=(
        "linux/qcom-dma-mapping.h",
        "linux/msm_ion.h",
        "linux/remoteproc/qcom_rproc.h",
        "linux/msm_dma_iommu_mapping.h",
        "soc/qcom/ramdump.h",
        "soc/qcom/qcom_ramdump.h",
        "soc/qcom/minidump.h",
        "linux/soc/qcom/pdr.h",
        "linux/soc/qcom/qmi.h",
        "linux/mem-buf.h",
        "linux/dma-iommu.h",
        "soc/qcom/socinfo.h",
        "trace/events/rproc_qcom.h",
    )
    for h in removed_headers:
        s=replace_once(s,"#include <"+h+">\n","","drop downstream-only header "+h)

    # Real secure_buffer.h is used ONLY for VMID/PERM enum constants.
    # Hyp assignment is deliberately blocked: no implementation or VM vote
    # is manufactured by this port. VMID 0 (ADSP normal) does not use it.
    inject=String="".join([]) if False else r'''
/* P461_SENSORS_DOWNSTREAM_5_10_V1: no qcom-specific dma_map attrs/ION.
 * Optional out-of-scope VM assignment always rejects, never succeeds.
 */
static int a52_fastrpc_unsupported(const char *feature)
{
    pr_warn_ratelimited("P461 FASTRPC UNSUPPORTED feature=%s rc=-EOPNOTSUPP\n",
                        feature);
    return -EOPNOTSUPP;
}
#define hyp_assign_phys(...) a52_fastrpc_unsupported("hyp-assign")
#define msm_minidump_enabled() false
#define dump_enabled() false
'''
    s=replace_once(s,'#define FASTRPC_ENOSUCH 39',inject+'\n#define FASTRPC_ENOSUCH 39',"safe feature contract")

    # Full source is downstream; optional minidump must not compile vendor
    # platform hooks. No fake storage success; reject if ever requested.
    s=body_replace(s,"fastrpc_minidump_add_region",
        lambda _:'''static int fastrpc_minidump_add_region(struct fastrpc_mmap *map)
{
    return a52_fastrpc_unsupported("minidump-add");
}''')
    s=body_replace(s,"fastrpc_minidump_remove_region",
        lambda _:'''static int fastrpc_minidump_remove_region(struct fastrpc_mmap *map)
{
    return a52_fastrpc_unsupported("minidump-remove");
}''')
    s=body_replace(s,"fastrpc_ramdump_collection",
        lambda _:'''static void fastrpc_ramdump_collection(int cid)
{
    pr_warn_once("P461 FASTRPC UNSUPPORTED ramdump rc=-EOPNOTSUPP\\n");
}''')
    # Remote heap / hyp shared memory not needed for ATTACH_SENSORS.
    s=body_replace(s,"fastrpc_mmap_create_remote_heap",
        lambda _:'''static int fastrpc_mmap_create_remote_heap(struct fastrpc_file *fl,
        struct fastrpc_mmap *map, size_t len, int mflags)
{
    return a52_fastrpc_unsupported("remote-heap");
}''')
    s=body_replace(s,"fastrpc_setup_service_locator",
        lambda _:'''static int fastrpc_setup_service_locator(struct device *dev,
        const char *propname, char *client_name, char *service_name,
        char *service_path)
{
    return a52_fastrpc_unsupported("PDR");
}''')
    # PDR is LOG-ONLY. Do not let disabled PDR prevent platform probe.
    a=s.index('\terr = fastrpc_setup_service_locator(dev, AUDIO_PDR_ADSP_DTSI_PROPERTY_NAME,')
    b=s.index('\terr = of_platform_populate(',a)
    s=s[:a]+'''    pr_info("P461 FASTRPC PDR disabled rc=-EOPNOTSUPP (log only, no subscription)\\n");
'''+s[b:]

    # no remoteheap reserved memory; no device should appear as a driver
    # for audio memory-region unless separate wave ports it.
    a=s.index('\tif (of_device_is_compatible(dev->of_node,\n\t\t\t\t\t"qcom,msm-adsprpc-mem-region")) {')
    b=s.index('\tme->legacy_remote_heap =',a)
    s=s[:a]+'''    if (of_device_is_compatible(dev->of_node,
                    "qcom,msm-adsprpc-mem-region"))
        return a52_fastrpc_unsupported("audio-remote-heap");

'''+s[b:]
    # Use normal DMA-BUF API, NOT mem-buf ownership heuristics.
    s=s.replace('map->secure = (mem_buf_dma_buf_exclusive_owner(map->buf)) ? 0 : 1;',
                'map->secure = 0; /* Nonsecure ADSP DMA-BUF only */')
    if 'mem_buf_dma_buf_exclusive_owner' in s:
        raise RuntimeError("P461 mem-buf ownership path not eliminated")
    # The special NOMAP path also MUST use per-session CB child, never
    # me->dev (a remoteheap device or central apps-SMMU parent).
    s=replace_once(s,'dma_buf_attach(map->buf, me->dev)',
                   'dma_buf_attach(map->buf, fl->sctx->smmu.dev)',
                   'NOMAP ADSP context-bank attach')
    s=replace_once(s,'dev_name(me->dev), PTR_ERR(map->attach)',
                   'dev_name(fl->sctx->smmu.dev), PTR_ERR(map->attach)',
                   'NOMAP attach diagnostics')
    # No hidden qcom dma_map attrs.
    s=re.sub(r'^\s*map->attach->dma_map_attrs\s*\|=\s*DMA_ATTR_[A-Z_]+;\n','\n',s,flags=re.M)
    s=s.replace('map->attach->dma_map_attrs', '0 /* P461 plain DMA-BUF */')
    if 'dma_map_attrs' in s:
        raise RuntimeError("P461 downstream dma-map-attrs leaked")
    # Unknown secure/import FD is mapped only to nonsecure CB device;
    # no software decision to create/enter secure SMMU context.

    # Explicit no-peer error, rather than waiting 5 seconds/timeout loops
    # for ADSP that has not been started via manual PAS knob.
    needle='p.inv.job = NULL;'
    s=replace_once(s,needle,needle+'''
    if (_IOC_TYPE(ioctl_num) == 'R' && _IOC_NR(ioctl_num) == 9) {
        pr_warn_once("P461 FASTRPC ioctl GETPERF(9) unsupported rc=-ENOTTY\\n");
        return -ENOTTY;
    }
    if (!READ_ONCE(gcinfo[ADSP_DOMAIN_ID].rpdev)) {
        pr_warn_ratelimited("P461 FASTRPC ioctl=0x%x rc=-ENOTCONN ADSP_DOWN\\n",
                            ioctl_num);
        return -ENOTCONN;
    }
''',"ioctl early peer/GETPERF gate")

    # Native ioctl error marker for every failure: include number/errno.
    s=body_replace(s,"fastrpc_device_ioctl",lambda f:replace_once(
        f, " bail:\n\treturn err;", ''' bail:
    if (err)
        pr_warn_ratelimited("P461 FASTRPC ioctl=0x%x errno=%d\\n",
                            ioctl_num, err);
\treturn err;''',"native per-ioctl failure logging"))

    # No global SRAM/SMMU-parent fallback for missing ADSP CB.
    s=body_replace(s,"fastrpc_session_alloc_locked",lambda f:replace_once(
        f,"\t\tVERIFY(err, me->dev != NULL);",
        '\t\tVERIFY(err, false); /* P461 no remoteheap/global SMMU DMA fallback */',
        "fail closed without CB"))
    # Upstream platform bus driver performs the default attach as each CB
    # is probed; Fastrpc owns DMA mapping only upon first session/import.
    s=replace_once(s,
        '\tiommu_dma_enable_best_fit_algo(dev);',
        '\t/* P461: no Qualcomm-specific iommu DMA policy mutation. */',
        'drop proprietary best-fit SMMU operation')
    s=replace_once(s,
        '\tpr_info("P461 FASTRPC PROBE CB dev=%s sid=0x%x args=%d\\n",',
        '\tpr_info("P461 FASTRPC PROBE CB dev=%s sid=0x%x args=%d\\n",',
        "retain SID marker")
    # Explicit real first-session marker after allocation selection.
    s=body_replace(s,"fastrpc_session_alloc_locked",lambda f:replace_once(
        f,"\t*session = &chan->session[idx];",
        '''    if (chan == &gcinfo[ADSP_DOMAIN_ID]) {
        struct device *cbdev = chan->session[idx].smmu.dev;
        if (!cbdev)
            return -ENODEV;
        pr_info("P461 FASTRPC SMMU ATTACH session=%llu cb=%s sid=0x%04x\\n",
                idx, dev_name(cbdev), 0x1003 + (chan->session[idx].smmu.cb - 3));
    }
\t*session = &chan->session[idx];''',"SMMU session mapping marker"))

    # Secure CB sessions stay unimplemented; their existence must not
    # accidentally select a high-security context bank.
    s=body_replace(s,"fastrpc_session_alloc_locked",lambda f:replace_once(
        f,"\tif (chan->sesscount) {",
        '''    if (secure)
        return a52_fastrpc_unsupported("secure-CB-session");
\tif (chan->sesscount) {''',"secure CB fail-closed"))

    # Platform app boot should not pre-provision CDSP or SSR/PDR services.
    start=s.index('\tfor (i = 0; i < NUM_CHANNELS; i++) {\n\t\tme->jobid[i] = 1;',s.index('static int __init fastrpc_device_init'))
    end=s.index('\n\terr = register_rpmsg_driver(',start)
    s=s[:start]+'''    for (i = 0; i < NUM_CHANNELS; i++) {
        me->jobid[i] = 1;
        me->channel[i].dev = me->non_secure_dev;
        me->channel[i].ssrcount = 0;
        me->channel[i].in_hib = 0;
        me->channel[i].prevssrcount = 0;
        me->channel[i].subsystemstate = SUBSYSTEM_UP;
        me->channel[i].ramdumpenabled = 0;
        me->channel[i].rh_dump_dev = NULL;
        me->channel[i].handle = NULL; /* PDR/SSR disabled */
    }
    pr_info("P461 FASTRPC PROBE ADSP-only, external SSR/PDR disabled\\n");
'''+s[end:]
    # Strip notifier unregistration loops (no notifier was registered).
    a=s.index('device_create_bail:\n')
    b=s.index('\tif (!IS_ERR_OR_NULL(me->non_secure_dev))',a)
    s=s[:a]+'''device_create_bail:
    /* P461: no SSR notifier registered */
'''+s[b:]
    a=s.index('\tfor (i = 0; i < NUM_CHANNELS; i++) {',s.index('static void __exit fastrpc_device_exit'))
    b=s.index('\n\t/* Destroy the secure and non secure devices */',a)
    s=s[:a]+'''    /* P461: no CDSP ramdump buffer and no SSR notifier */
'''+s[b:]
    s=replace_once(s,'\tof_reserved_mem_device_release(me->dev);',
                   '\tif (me->dev)\n\t\tof_reserved_mem_device_release(me->dev);',
                   "no remoteheap release NULL")

    # Remove ramdump SSR heap collection, never silently skip ownership.
    s=body_replace(s,"fastrpc_mmap_remove_ssr",lambda f:re.sub(
        r'\tstruct qcom_dump_segment ramdump_segments_rh;\n|\tstruct list_head head;\n|\tINIT_LIST_HEAD\(&head\);\n','',f))
    s=body_replace(s,"fastrpc_mmap_remove_ssr",lambda f:re.sub(
        r'\t\t\tmemset\(&ramdump_segments_rh, 0, sizeof\(ramdump_segments_rh\)\);.*?(?=\t\t\tif \(!locked && fl\))',
        '\t\t\tpr_warn_once("P461 FASTRPC SSR remote heap dump disabled rc=-EOPNOTSUPP\\\\n");\n',
        f,flags=re.S))

    # The PDR service locator is deliberately absent. Its status probe is
    # skipped only for the ADSP sensors PD; the *real DSP RPC* below must
    # still return success, or INIT fails with its actual errno.
    s=body_replace(s,"fastrpc_check_pd_status",lambda _:'''static int fastrpc_check_pd_status(struct fastrpc_file *fl,
        char *sloc_name)
{
    if (fl && fl->cid == ADSP_DOMAIN_ID && sloc_name &&
        !strcmp(sloc_name, SENSORS_PDR_ADSP_SERVICE_LOCATION_CLIENT_NAME)) {
        pr_info_once("P461 FASTRPC PDR STATUS bypassed for ADSP sensor RPC; real INIT RPC required\\n");
        return 0;
    }
    return a52_fastrpc_unsupported("PDR status");
}''')
    s=body_replace(s,"fastrpc_device_ioctl",lambda f:replace_once(
        f,'''    if (fl->servloc_name) {''',
        '''    if (fl->servloc_name && fl->cid != ADSP_DOMAIN_ID) {''',
        "PDR disabled for sensor-only ioctls"))
    s=body_replace(s,"fastrpc_init_create_dynamic_process",
        lambda _:'''static int fastrpc_init_create_dynamic_process(
        struct fastrpc_file *fl, struct fastrpc_ioctl_init_attrs *uproc)
{
    return a52_fastrpc_unsupported("dynamic-PD-CDSP");
}''')
    s=body_replace(s,"fastrpc_init_create_static_process",
        lambda _:'''static int fastrpc_init_create_static_process(
        struct fastrpc_file *fl, struct fastrpc_ioctl_init *init)
{
    return a52_fastrpc_unsupported("audio-PD-remote-heap");
}''')
    s=body_replace(s,"fastrpc_get_cdsp_status",
        lambda _:'''static void fastrpc_get_cdsp_status(struct fastrpc_apps *me)
{
    me->fastrpc_cdsp_status = 0;
    pr_info_once("P461 FASTRPC CDSP unsupported rc=-EOPNOTSUPP\\n");
}''')
    # No PDR/SSR registration means no callback. RPMSG remove is the
    # only signal that the ADSP peer is gone. Do not build notifier code
    # referencing unavailable downstream QCOM notifier APIs.
    s=body_replace(s,"fastrpc_restart_notifier_cb",
        lambda _:"/* P461 no external SSR notifier; RPMSG removal owns shutdown */")
    s=body_replace(s,"fastrpc_pdr_cb",
        lambda _:"/* P461 PDR callback compiled out: not registered */")
    s=body_replace(s,"fastrpc_setup_service_locator",
        lambda _:"/* P461 PDR service locator intentionally not registered */")
    # Remove proprietary mapping flags everywhere; no flag is emulated as
    # a success and no delayed-unmap lifecycle is retained.
    for obsolete in ("DMA_ATTR_EXEC_MAPPING","DMA_ATTR_DELAYED_UNMAP",
                     "DMA_ATTR_SYS_CACHE_ONLY","DMA_ATTR_SKIP_ZEROING"):
        s=s.replace(obsolete,"0 /* P461 no proprietary DMA attr */")
    if any(flag in s for flag in ("DMA_ATTR_EXEC_MAPPING","DMA_ATTR_DELAYED_UNMAP",
                                 "DMA_ATTR_SYS_CACHE_ONLY","DMA_ATTR_SKIP_ZEROING")):
        raise RuntimeError("P461 proprietary DMA attributes remain")
    s=body_replace(s,"fastrpc_mmap_remove_ssr",
        lambda f:replace_once(f,"int err = 0, ret = 0;","int err = 0;",
                              "SSR dump unused ret"))
    # No early/automatic context-bank IOMMU attachments: create ADSP
    # CB platform child devices only upon the first GETINFO session and
    # only after RPMSG is UP. The parent is probed without CB population.
    helper=r'''
static const struct of_device_id fastrpc_match_table[];
static DEFINE_MUTEX(a52_fastrpc_cb_lock);
static struct device *a52_fastrpc_compute_dev;
static bool a52_fastrpc_cb_populated;

static int a52_fastrpc_populate_on_first_session(void)
{
    int ret = 0;

    mutex_lock(&a52_fastrpc_cb_lock);
    if (!a52_fastrpc_compute_dev ||
        !READ_ONCE(gcinfo[ADSP_DOMAIN_ID].rpdev)) {
        ret = -ENOTCONN;
        goto unlock;
    }
    if (a52_fastrpc_cb_populated)
        goto unlock;
    ret = of_platform_populate(a52_fastrpc_compute_dev->of_node,
                               fastrpc_match_table, NULL,
                               a52_fastrpc_compute_dev);
    if (!ret) {
        a52_fastrpc_cb_populated = true;
        pr_info("P461 FASTRPC SMMU CB_CREATE lazy_first_session=1 count=%llu\n",
                gcinfo[ADSP_DOMAIN_ID].sesscount);
    }
unlock:
    mutex_unlock(&a52_fastrpc_cb_lock);
    return ret;
}

'''
    sig='static int fastrpc_get_info(struct fastrpc_file *fl, uint32_t *info)'
    s=replace_once(s,sig,helper+sig,"lazy CB helper placement")
    s=body_replace(s,"fastrpc_get_info",
        lambda f:replace_once(f,
            '\tfastrpc_get_process_gids(&fl->gidlist);',
            '''    if (cid != ADSP_DOMAIN_ID)
        return a52_fastrpc_unsupported("non-ADSP-domain");
    err = a52_fastrpc_populate_on_first_session();
    if (err)
        goto bail;
\tfastrpc_get_process_gids(&fl->gidlist);''',
            "first-session attach setup"))
    # Parent platform probe must not instantiate CB children at boot.
    s=body_replace(s,"fastrpc_probe",
        lambda f:replace_once(f,
            '''\terr = of_platform_populate(pdev->dev.of_node,
\t\t\t\t\t  fastrpc_match_table,
\t\t\t\t\t  NULL, &pdev->dev);
\tif (err)
\t\tgoto bail;''',
            '''    if (of_device_is_compatible(dev->of_node,
               "qcom,msm-fastrpc-compute")) {
        a52_fastrpc_compute_dev = dev;
        pr_info("P461 FASTRPC PROBE parent=%s ADSP CB attach deferred\\n",
                dev_name(dev));
    }''',
            "defer SMMU child population"))
    # Fast bounded no-peer open, BEFORE any file state is allocated.
    s=body_replace(s,"fastrpc_device_open",lambda f:replace_once(
        f,'\tVERIFY(err, ((dev_minor == MINOR_NUM_DEV) ||',
        '''    if (!READ_ONCE(gcinfo[ADSP_DOMAIN_ID].rpdev)) {
        pr_warn_ratelimited("P461 FASTRPC OPEN rc=-ENOTCONN ADSP_DOWN\\n");
        return -ENOTCONN;
    }
\tVERIFY(err, ((dev_minor == MINOR_NUM_DEV) ||''',
        "ADSP-off open refusal"))
    # Wait for actual remote response with a bounded timeout, even after
    # an unexpected ADSP crash. No infinite kernel-side wait.
    s=body_replace(s,"fastrpc_wait_for_response",
        lambda _:'''static inline int fastrpc_wait_for_response(
        struct smq_invoke_ctx *ctx, uint32_t kernel)
{
    long ret;

    if (kernel)
        ret = wait_for_completion_timeout(&ctx->work, msecs_to_jiffies(5000));
    else
        ret = wait_for_completion_interruptible_timeout(
            &ctx->work, msecs_to_jiffies(5000));
    if (ret == 0) {
        pr_warn_ratelimited("P461 FASTRPC RPC wait timeout 5000ms rc=-ETIMEDOUT\\n");
        return -ETIMEDOUT;
    }
    return ret < 0 ? (int)ret : 0;
}''')
    # Proprietary audio/CDSP RAMDUMP startup was removed. Drop its
    # now-unused stack locals rather than weakening Clang -Werror.
    s=body_replace(s,"fastrpc_device_init",lambda f:replace_once(
        f,
        "\tuintptr_t attr = 0;\n\tdma_addr_t region_phys = 0;\n\tvoid *region_vaddr = NULL;\n\tstruct fastrpc_buf *buf = NULL;\n",
        "",
        "drop unused CDSP RAMDUMP initialization locals"))
    s=body_replace(s,"fastrpc_device_exit",lambda f:replace_once(
        f,"\tint i;\n","","drop unused SSR teardown loop index"))
    s=body_replace(s,"fastrpc_probe",lambda f:replace_once(
        f,"\tint ret = 0;\n","","drop unused audio remoteheap ret variable"))

    # ADSP is the *only* supported peer. Registered RPMSG devices for CDSP
    # or modem are explicitly rejected rather than being treated as ready.
    s=body_replace(s,"fastrpc_rpmsg_probe",lambda f:replace_once(
        f,
        "\tcid = get_cid_from_rpdev(rpdev);",
        """    cid = get_cid_from_rpdev(rpdev);
    if (cid != ADSP_DOMAIN_ID)
        return a52_fastrpc_unsupported("CDSP/modem RPMSG");
""",
        "reject non-ADSP transport channels"))
    # All initialization must be sensors-first, with no automatic PAS.
    s=s.replace('create_ramdump_device(', 'a52_fastrpc_unsupported("ramdump",')
    # Foreign API must never be called in generated driver:
    forbidden=['mem_buf_dma_buf_exclusive_owner','qcom_register_ssr_notifier(',
              'qcom_unregister_ssr_notifier(','qcom_elf_dump(','iommu_dma_enable_best_fit_algo(']
    left=[word for word in forbidden if word in s]
    if left:
        raise RuntimeError("P461 unported optional native symbols "+str(left))
    return s

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--config",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    ap.add_argument("--check-only",action="store_true")
    a=ap.parse_args()
    target=a.root/"drivers/char"
    donor=Path("vendor/p461/a52-5.10-port/drivers/char")
    for x in FILES:
        if not (donor/x).is_file():raise RuntimeError("P461 donor missing "+x)
    # Keep exact, reviewable pristine donor in vendor/p461; transform into
    # generated common/ only for G variant.
    driver=transform((donor/"adsprpc.c").read_text())
    compat=(donor/"adsprpc_compat.c").read_text().replace(
        "#include <linux/msm_ion.h>\n","")
    if compat.count("long compat_fastrpc_device_ioctl(")!=1:
        raise RuntimeError("P461 compat original ioctl dispatch anchor drift")
    compat=compat.replace("long compat_fastrpc_device_ioctl(",
                          "static long a52_fastrpc_compat_ioctl_inner(",1)
    compat+='''
long compat_fastrpc_device_ioctl(struct file *filp, unsigned int cmd,
                                unsigned long arg)
{
    long rc;

    if (_IOC_TYPE(cmd) == 'R' && _IOC_NR(cmd) == 9) {
        pr_warn_once("P461 FASTRPC GETPERF compat cmd=0x%x errno=-ENOTTY\\n", cmd);
        return -ENOTTY;
    }
    rc = a52_fastrpc_compat_ioctl_inner(filp, cmd, arg);
    if (rc)
        pr_warn_ratelimited("P461 FASTRPC compat ioctl=0x%x errno=%ld\\n",
                            cmd, rc);
    return rc;
}
'''
    mk=target/"Makefile";kc=target/"Kconfig"
    m=mk.read_text();k=kc.read_text()
    if "CONFIG_MSM_ADSPRPC" not in m:
        m+="\nfrpc-adsprpc-y := adsprpc.o\nfrpc-adsprpc-$(CONFIG_COMPAT) += adsprpc_compat.o\nobj-$(CONFIG_MSM_ADSPRPC) += frpc-adsprpc.o\n"
    if "config MSM_ADSPRPC" not in k:
        k+='''\nconfig MSM_ADSPRPC
    bool "P461 A52 downstream Qualcomm FastRPC (ADSP sensors-only)"
    depends on RPMSG && IOMMU_SUPPORT && DMA_SHARED_BUFFER && OF
    default n
'''
    manifest={"marker":MARK,"donor":"LineageOS sm8450 5.10 pinned",
        "original_sha256":hashlib.sha256((donor/"adsprpc.c").read_bytes()).hexdigest(),
        "generated_sha256":hashlib.sha256(driver.encode()).hexdigest(),
        "user_abi":"Qualcomm downstream, includes compat + legacy ioctl16",
        "unsupported":["audio-remote-heap","ramdump","PDR","hyp-assign",
                       "secure-CB-sessions","CDSP","modem","GETPERF(9)"],
        "dma_buf":"dma_buf_get / attach to per-session ADSP CB child / map_attachment",
        "runtime_accepted":False}
    if not a.check_only:
        for name,data in {"adsprpc.c":driver,"adsprpc_compat.c":compat,
                          "adsprpc_compat.h":(donor/"adsprpc_compat.h").read_text(),
                          "adsprpc_shared.h":(donor/"adsprpc_shared.h").read_text()}.items():
            (target/name).write_text(data)
        mk.write_text(m);kc.write_text(k)
        # Exact pinned donor UAPI + trace + VMID declarations, not fabricated.
        for h in ("include/linux/fastrpc.h",
                  "include/trace/events/fastrpc.h",
                  "include/soc/qcom/secure_buffer.h"):
            src=Path("vendor/p461/a52-5.10-port")/h
            if not src.is_file():
                raise RuntimeError("P461 missing pinned donor header "+str(src))
            dst=a.root/h
            dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.is_file() and dst.read_bytes()!=src.read_bytes():
                if h=="include/soc/qcom/secure_buffer.h":
                    # A52 secure baseline already carries this QCOM ABI.
                    # Respect it: do not overwrite an unrelated subsystem
                    # header. Required symbols are the known VMID/PERM
                    # constants, not a live hyp_assign implementation.
                    old=dst.read_text()
                    required=("VMID_HLOS","PERM_READ","PERM_WRITE","PERM_EXEC")
                    if not all(token in old for token in required):
                        raise RuntimeError("P461 A52 native secure_buffer lacks VMID/PERM constants")
                    continue
                raise RuntimeError("P461 existing header incompatible: "+str(dst))
            dst.write_bytes(src.read_bytes())
    else:
        for name,expected in {"adsprpc.c":driver,"adsprpc_compat.c":compat}.items():
            if (target/name).read_text()!=expected:
                raise RuntimeError("P461 generated "+name+" drift")
        if "CONFIG_MSM_ADSPRPC" not in mk.read_text():
            raise RuntimeError("P461 Makefile missing")
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    print("P461 REAL DONOR GENERATED (hardware UNVERIFIED)",manifest)
if __name__=="__main__":main()
