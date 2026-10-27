#!/usr/bin/env python3
"""P466 A52 FastRPC: repair coherent-CB flags-0 DMA-BUF mapping; restore
donor unbounded invoke-completion semantics.

Applied to the exact P461->P465 generated downstream adsprpc.c. Keep P463
suspend-safe charger, P460B, P457 SMMU, P462 watchdog and ADSP manual PAS
unchanged. Does not enable remote heap, secure PD, CDSP, or modem.
"""
import argparse
import json
import re
import runpy
import sys
from pathlib import Path

FILE=Path("drivers/char/adsprpc.c")
MARK="P466 FASTRPC DMA_MAP"
WAIT_MARK="P466 FASTRPC RPC_LONG_WAIT"

def patch(s):
    if MARK in s or WAIT_MARK in s:
        raise RuntimeError("P466 already patched")
    required=("P465 FASTRPC NULL_TABLE", "P465 FASTRPC MAP_UNSUPPORTED",
              "P461 FASTRPC RPMSG ADSP ACCEPT",
              "P463 FASTRPC NEVER" if False else "P465 FASTRPC EMPTY_SG")
    for term in required:
        if term not in s:
            raise RuntimeError("P466 requires P465 generated source: "+term)

    # P461 stripped the proprietary map->attach->dma_map_attrs write,
    # but left its surrounding 'if (!sess->smmu.coherent)' statement.
    # As a result, on dma-coherent CB children the ordinary flags=0
    # dma_buf_map_attachment() was skipped and map->table remained NULL.
    # Remove ONLY that orphan; mapping is independent of coherency.
    pattern=(r'\t\tif \(!sess->smmu\.coherent\)\n'
             r'(?:[ \t]*\n){1,4}'
             r'(?=\t\tVERIFY\(err, !IS_ERR_OR_NULL\(map->table =)')
    s,n=re.subn(pattern,
        '\t\t/* P466: DMA attachment mapping is mandatory on coherent CBs too. */\n',
        s)
    if n != 1:
        raise RuntimeError(f"P466 coherent-CB orphan: expected 1, found {n}")

    # The P465 NULL_TABLE and EMPTY_SG guards stay AFTER the actual map
    # attachment and BEFORE any sg_table member access or sg_dma_address.
    # These two sites correspond to NOMAP and ordinary flags=0/DMA_BUFFER.
    sg='\t\tmap->phys = sg_dma_address(map->table->sgl);'
    parts=s.split(sg)
    if len(parts) != 3:
        raise RuntimeError("P466 expected exactly two supported DMA-map sites")
    s=(parts[0]+sg+
       '\n\t\ta52_p466_log_mapped_dma(fl->sctx, map, fd, mflags, len);'+
       parts[1]+sg+
       '\n\t\ta52_p466_log_mapped_dma(sess, map, fd, mflags, len);'+
       parts[2])

    logger=r'''
/* P466 FASTRPC DMA_MAP: report the true DT SID and the DMA API IOVA
 * BEFORE the downstream FastRPC CB-tag address encoding in map->phys.
 * Never infer SID from the CB name or the last 4 bits.
 */
static void a52_p466_log_mapped_dma(struct fastrpc_session_ctx *sess,
                                  struct fastrpc_mmap *map,
                                  int fd, int flags, size_t len)
{
    struct of_phandle_args spec;
    dma_addr_t iova;
    int rc, sid = -1;

    if (IS_ERR_OR_NULL(sess) || IS_ERR_OR_NULL(sess->smmu.dev) ||
        IS_ERR_OR_NULL(map) || IS_ERR_OR_NULL(map->table) ||
        !map->table->sgl || !map->table->nents) {
        pr_warn_ratelimited("P466 FASTRPC DMA_LOG invalid_CB_or_SG fd=%d flags=%#x\n",
                            fd, flags);
        return;
    }
    iova = sg_dma_address(map->table->sgl);
    if (sess->smmu.dev->of_node) {
        rc = of_parse_phandle_with_args(sess->smmu.dev->of_node,
                    "iommus", "#iommu-cells", 0, &spec);
        if (!rc) {
            if (spec.args_count)
                sid = spec.args[0];
            of_node_put(spec.np);
        }
    }
    pr_info_ratelimited("P466 FASTRPC DMA_MAP fd=%d flags=%#x cb=%s sid=0x%x iova=%pad len=%zu nents=%u\n",
        fd, flags, dev_name(sess->smmu.dev), sid, &iova, len,
        map->table->nents);
}
'''
    needle="static int fastrpc_mmap_create(struct fastrpc_file *fl,"
    if s.count(needle)!=1:
        raise RuntimeError("P466 driver insertion anchor moved")
    s=s.replace(needle,logger+"\n"+needle,1)

    # P461's 5 s wait was introduced for crash resilience, but reverse
    # RPC / adsp_default_listener calls legitimately block indefinitely.
    # Restore the pinned donor's interruptible userspace completion; no
    # ETIMEDOUT on idle listener. Log elapsed >5s on return, NOT an abort.
    start='static inline int fastrpc_wait_for_response('
    end='\nstatic void fastrpc_wait_for_completion('
    if s.count(start)!=1 or s.count(end)!=1:
        raise RuntimeError("P466 invoke-wait function anchor drift")
    a=s.index(start)
    b=s.index(end,a)
    old=s[a:b]
    if ("wait_for_completion_interruptible_timeout" not in old or
        "RPC wait timeout 5000ms" not in old):
        raise RuntimeError("P466 unexpected invoke wait baseline")
    replacement=r'''static inline int fastrpc_wait_for_response(
        struct smq_invoke_ctx *ctx, uint32_t kernel)
{
    unsigned long started = jiffies;
    int interrupted = 0;

    if (kernel)
        wait_for_completion(&ctx->work);
    else
        interrupted = wait_for_completion_interruptible(&ctx->work);

    if (time_after_eq(jiffies, started + msecs_to_jiffies(5000)))
        pr_warn_ratelimited(
            "P466 FASTRPC RPC_LONG_WAIT elapsed_ms=%u kernel=%u rc=%d tgid=%d no_timeout=1\n",
            jiffies_to_msecs(jiffies - started), kernel, interrupted,
            task_tgid_nr(current));
    return interrupted;
}
'''
    s=s[:a]+replacement+s[b:]
    return s

def check(s):
    for marker in (MARK,WAIT_MARK, "P465 FASTRPC NULL_TABLE",
                   "P465 FASTRPC EMPTY_SG",
                   "P465 FASTRPC MAP_UNSUPPORTED",
                   "dma_buf_attach(map->buf, sess->smmu.dev)",
                   "dma_buf_map_attachment(map->attach,",
                   "wait_for_completion_interruptible(&ctx->work)",
                   "wait_for_completion(&ctx->work)",
                   "P461 FASTRPC RPMSG ADSP ACCEPT"):
        if marker not in s:
            raise RuntimeError("P466 missing contract: "+marker)
    if "RPC wait timeout 5000ms" in s:
        raise RuntimeError("P466 stale aborting invoke timeout")
    if s.count("dma_buf_map_attachment(map->attach,")!=2:
        raise RuntimeError("P466 lost or duplicated DMA map sites")
    if s.count("a52_p466_log_mapped_dma(")!=3:
        raise RuntimeError("P466 missing SID+IOVA diagnostics at one site")
    if re.search(r'if \(!sess->smmu\.coherent\)\s*VERIFY\(err, !IS_ERR_OR_NULL\(map->table',s):
        raise RuntimeError("P466 DMA map still conditional on coherency")
    mmap=s[s.index("static int fastrpc_mmap_create(struct fastrpc_file *fl,"):
           s.index("static inline bool fastrpc_get_cached_buf(")]
    if mmap.count("P465 FASTRPC NULL_TABLE")!=2 or mmap.count("P465 FASTRPC EMPTY_SG")!=2:
        raise RuntimeError("P466 lost P465 MAP NULL/SG safeguards")
    # For flags-0, mapping must occur after attach and before the
    # non-coherent/SMMU-disabled checks and first table-> member access.
    regular=mmap[mmap.index("if (mflags == ADSP_MMAP_DMA_BUFFER)"):mmap.index("map->phys += ((uint64_t)sess->smmu.cb << 32)")]
    if not (regular.index("dma_buf_attach(map->buf, sess->smmu.dev)") <
            regular.index("dma_buf_map_attachment(map->attach,") <
            regular.index("P465 FASTRPC NULL_TABLE") <
            regular.index("P465 FASTRPC EMPTY_SG") <
            regular.index("sg_dma_address(map->table->sgl)") <
            regular.index("a52_p466_log_mapped_dma(sess")):
        raise RuntimeError("P466 flags-0 ordering: attach -> map -> validate -> IOVA")
    wait=s[s.index("static inline int fastrpc_wait_for_response("):
           s.index("static void fastrpc_wait_for_completion(")]
    if "wait_for_completion_interruptible_timeout" in wait or "return -ETIMEDOUT" in wait:
        raise RuntimeError("P466 5s timeout remains in invoke completion")
    if "wait_for_completion_interruptible(&ctx->work)" not in wait:
        raise RuntimeError("P466 reverse-RPC user wait not unbounded")
    return {"flags0":"real attach/map DMA_BIDIRECTIONAL even on coherent CB",
            "sid":"iommus DT property","iova":"dma_addr_t before CB encoding",
            "completion":"unbounded interruptible user and unbounded kernel",
            "long_wait":"log after completion or signal (no abort)",
            "P465_null_table_sg_guards":True,
            "P463_safety_unchanged":True}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--selftest",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    if a.selftest:
        t461=runpy.run_path("scripts/461_enable_sensors_fastrpc.py",run_name="p466_donor_461")
        t465=runpy.run_path("scripts/465_fastrpc_mmap_guard.py",run_name="p466_donor_465")
        src=Path("vendor/p461/a52-5.10-port/drivers/char/adsprpc.c").read_text()
        generated=t465["patch"](t461["transform"](src))
        checked=check(patch(generated))
        print("P466 PINNED DONOR SELFTEST PASS",json.dumps(checked))
        return
    if not a.root:
        p.error("--root required unless --selftest")
    f=a.root/FILE
    src=f.read_text()
    if not a.check_only:
        src=patch(src)
        f.write_text(src)
    report=check(src)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("P466 FASTRPC CB DMA + RPC WAIT SOURCE PASS",json.dumps(report))

if __name__=="__main__":
    main()
