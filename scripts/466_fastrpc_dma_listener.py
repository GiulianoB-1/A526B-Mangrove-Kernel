#!/usr/bin/env python3
"""P466: unconditionally map coherent ADSP CB DMA-BUFs and restore donor waits.

Apply ONLY after the pinned P461 source generator and P465 mmap guards.
No changes to P463, P460B, P457, Phase206, SCM/ADSP or P462 watchdog.
"""
import argparse
import json
import re
import runpy
import sys
from pathlib import Path

SRC=Path("drivers/char/adsprpc.c")
TAG="P466 FASTRPC DMA LISTENER V1"

def once(s,a,b,why):
    n=s.count(a)
    if n!=1:
        raise RuntimeError(f"P466 {why}: expected one anchor got {n}")
    return s.replace(a,b,1)

def func(s,name):
    pat=r"(?m)^static\s+(?:inline\s+)?(?:int|void|long)\s+"+re.escape(name)+r"\s*\([^;{}]*\)\s*\{"
    m=re.search(pat,s,re.S)
    if not m: raise RuntimeError("P466 missing "+name)
    depth=0
    for i in range(m.end()-1,len(s)):
        if s[i]=="{":depth+=1
        elif s[i]=="}":
            depth-=1
            if not depth: return m.start(),i+1
    raise RuntimeError("P466 unterminated "+name)

LOG_HELPER=r'''
/* P466: actual mapped IOVA, NOT map->phys (which packs a CB cookie). */
static void a52_p466_log_dma_map(struct fastrpc_session_ctx *sess,
                                 struct fastrpc_mmap *map, int fd,
                                 unsigned int flags)
{
    struct of_phandle_args iommu;
    dma_addr_t iova;
    u32 sid = 0;
    int ret;

    if (IS_ERR_OR_NULL(sess) || IS_ERR_OR_NULL(sess->smmu.dev) ||
        IS_ERR_OR_NULL(map) || IS_ERR_OR_NULL(map->table) ||
        !map->table->sgl || !map->table->nents) {
        pr_warn_ratelimited("P466 FASTRPC MAP_LOG_INVALID fd=%d flags=%#x errno=-EINVAL\n",
                            fd, flags);
        return;
    }
    iova = sg_dma_address(map->table->sgl);
    ret = of_parse_phandle_with_args(sess->smmu.dev->of_node, "iommus",
                                     "#iommu-cells", 0, &iommu);
    if (!ret) {
        if (iommu.args_count)
            sid = iommu.args[0];
        of_node_put(iommu.np);
    }
    pr_info_ratelimited("P466 FASTRPC DMA_MAP_OK fd=%d flags=%#x cb=%s sid=0x%x iova=%pad nents=%u size=%zu dma_coherent=%d sid_parse_rc=%d\n",
                        fd, flags, dev_name(sess->smmu.dev), sid,
                        &iova, map->table->nents, map->size,
                        sess->smmu.coherent, ret);
}
'''

WAIT=r'''static inline int fastrpc_wait_for_response(
        struct smq_invoke_ctx *ctx, uint32_t kernel)
{
    int interrupted = 0;
    unsigned long started = jiffies;
    unsigned long elapsed;

    if (kernel)
        wait_for_completion(&ctx->work);
    else
        interrupted = wait_for_completion_interruptible(&ctx->work);
    elapsed = jiffies - started;
    if (elapsed >= msecs_to_jiffies(5000))
        pr_info_ratelimited("P466 FASTRPC INVOKE_WAIT_LONG elapsed_ms=%u cid=%d handle=0x%x kernel=%u interrupted=%d no_timeout=1\n",
                            jiffies_to_msecs(elapsed),
                            ctx->fl ? ctx->fl->cid : -1,
                            ctx->handle, kernel, interrupted);
    return interrupted;
}'''

def patch(s):
    if TAG in s: raise RuntimeError("P466 duplicate")
    for key in ("P465 FASTRPC NULL_TABLE","P465 FASTRPC EMPTY_SG",
                "P461 FASTRPC RPMSG ADSP ACCEPT",
                "P461 FASTRPC SMMU ATTACH session="):
        if key not in s: raise RuntimeError("P466 missing baseline "+key)
    a,b=func(s,"fastrpc_mmap_create")
    f=s[a:b]
    old=("\t\t/*\n"
         "\t\t * Skip CPU sync if IO Cohernecy is not supported\n"
         "\t\t */\n"
         "\t\tif (!sess->smmu.coherent)\n\n\n"
         "\t\tVERIFY(err, !IS_ERR_OR_NULL(map->table =\n"
         "\t\t\tdma_buf_map_attachment(map->attach,\n"
         "\t\t\t\tDMA_BIDIRECTIONAL)));")
    new=("\t\t/* "+TAG+": coherent CB still requires DMA mapping. */\n"
         "\t\tVERIFY(err, !IS_ERR_OR_NULL(map->table =\n"
         "\t\t\tdma_buf_map_attachment(map->attach,\n"
         "\t\t\t\tDMA_BIDIRECTIONAL)));")
    f=once(f,old,new,"unguarded map for coherent CB")
    trace="\t\ttrace_fastrpc_dma_map(cid, fd, map->phys, map->size,\n"
    if f.count(trace)!=2: raise RuntimeError("P466 missing NOMAP/normal trace paths")
    f=f.replace(trace,"\t\ta52_p466_log_dma_map(fl->sctx, map, fd, mflags);\n"+trace,1)
    normal=("\t\t} else {\n"
            "\t\t\tmap->size = buf_page_size(len);\n"
            "\t\t}\n"
            "\t\ttrace_fastrpc_dma_map(cid, fd, map->phys, map->size,")
    replacement=("\t\t} else {\n"
                 "\t\t\tmap->size = buf_page_size(len);\n"
                 "\t\t}\n"
                 "\t\ta52_p466_log_dma_map(sess, map, fd, mflags);\n"
                 "\t\ttrace_fastrpc_dma_map(cid, fd, map->phys, map->size,")
    f=once(f,normal,replacement,"normal mapped IOVA log")
    if f.count("a52_p466_log_dma_map(")!=2: raise RuntimeError("P466 bad log count")
    s=s[:a]+f+s[b:]
    s=once(s,"static int fastrpc_mmap_create(struct fastrpc_file *fl,",
           LOG_HELPER+"\nstatic int fastrpc_mmap_create(struct fastrpc_file *fl,",
           "map helper")
    a,b=func(s,"fastrpc_wait_for_response")
    if "wait_for_completion_interruptible_timeout(" not in s[a:b] or "5000ms" not in s[a:b]:
        raise RuntimeError("P466 unexpected P461 invoke wait")
    s=s[:a]+WAIT+s[b:]
    return s

def check(s):
    if s.count(TAG)!=1:raise RuntimeError("P466 marker missing")
    a,b=func(s,"fastrpc_mmap_create")
    f=s[a:b]
    if "if (!sess->smmu.coherent)" in f:
        raise RuntimeError("P466 mapping is still skipped on coherent CB")
    if f.count("dma_buf_map_attachment(map->attach,")!=2:
        raise RuntimeError("P466 normal/NOMAP DMA map count drift")
    if f.count("a52_p466_log_dma_map(")!=2:
        raise RuntimeError("P466 expected two SID/IOVA logs")
    if not (f.index("dma_buf_attach(map->buf, sess->smmu.dev)") <
            f.rindex("dma_buf_map_attachment(map->attach,") <
            f.rindex("P465 FASTRPC NULL_TABLE") <
            f.rindex("P465 FASTRPC EMPTY_SG") <
            f.rindex("a52_p466_log_dma_map(sess, map, fd, mflags);")):
        raise RuntimeError("P466 normal CB attach/map/validation/log order drift")
    a,b=func(s,"fastrpc_wait_for_response")
    w=s[a:b]
    for x in ("wait_for_completion(&ctx->work);",
              "wait_for_completion_interruptible(&ctx->work);",
              "P466 FASTRPC INVOKE_WAIT_LONG","no_timeout=1"):
        if x not in w: raise RuntimeError("P466 donor listener contract missing "+x)
    if "wait_for_completion_timeout(" in w or "wait_for_completion_interruptible_timeout(" in w:
        raise RuntimeError("P466 invoke wait still bounded")
    if s.count("P461 FASTRPC PD_START cid=")!=1:
        raise RuntimeError("P466 default/sensors PD markers modified")
    return {"dma_buf":"CB attach + unconditional DMA_BIDIRECTIONAL map",
            "sid_iova_logging":True,"coherent_CB_maps":True,
            "listener_wait":"user interruptible unbounded; kernel unbounded",
            "long_wait_report_on_completion":True,
            "default_and_sensors_PD_unchanged":True,
            "hardware_validated":False}

def main():
    if "--selftest" in sys.argv:
        donor=Path("vendor/p461/a52-5.10-port/drivers/char/adsprpc.c")
        p461=runpy.run_path("scripts/461_enable_sensors_fastrpc.py",run_name="p466_p461")
        p465=runpy.run_path("scripts/465_fastrpc_mmap_guard.py",run_name="p466_p465")
        first=p461["transform"](donor.read_text())
        second=p465["patch"](first)
        p465["check"](second)
        check(patch(second))
        print("P466 PINNED DONOR P461 -> P465 -> P466 SELFTEST PASS")
        return
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    f=args.root/"drivers/char/adsprpc.c"
    src=f.read_text()
    if not args.check_only:
        src=patch(src)
        f.write_text(src)
    result=check(src)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P466 FASTRPC DMA/LISTENER SOURCE PASS "+json.dumps(result))

if __name__=="__main__":
    main()
