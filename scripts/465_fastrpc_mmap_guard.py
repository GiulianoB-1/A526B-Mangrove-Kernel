#!/usr/bin/env python3
"""P465 sensors-only adsprpc mmap Oops fix, applied after the P461 generator.

No changes to INIT/ATTACH_SENSORS, DMA context banks, SMMU, PAS, SCM,
the P463 charger guard or P462 watchdog. Never allocate remote heaps.
"""
import argparse
import json
import re
from pathlib import Path

FILE = Path("drivers/char/adsprpc.c")
TAG = "P465 FASTRPC MMAP SAFETY V1"

def once(s, a, b, what):
    n = s.count(a)
    if n != 1:
        raise RuntimeError(f"P465 {what}: expected 1 anchor, got {n}")
    return s.replace(a, b, 1)

def edit_function(s, name, a, b, what):
    m = re.search(r"(?m)^static (?:inline )?(?:int|void|long)\s+" +
                  re.escape(name) + r"\s*\([^;{}]*\)\s*\{", s, re.S)
    if not m:
        raise RuntimeError("P465 missing function " + name)
    level = 0
    for end in range(m.end()-1, len(s)):
        if s[end] == "{":
            level += 1
        elif s[end] == "}":
            level -= 1
            if level == 0:
                return s[:m.start()] + once(s[m.start():end+1], a, b, what) + s[end+1:]
    raise RuntimeError("P465 unterminated function " + name)

def patch(s):
    if TAG in s:
        raise RuntimeError("P465 patch already applied")
    for marker in ("P461 FASTRPC SMMU ATTACH session=",
                   "P461 FASTRPC RPMSG ADSP ACCEPT",
                   "static int fastrpc_mmap_create("):
        if marker not in s:
            raise RuntimeError("P465 wrong donor baseline " + marker)

    guard = r'''
/* P465 FASTRPC MMAP SAFETY V1: reject unsupported remote heap BEFORE
 * allocating or importing a DMA-BUF; validate the actual ADSP CB child.
 */
static int a52_p465_validate_map(struct fastrpc_file *fl,
                                 unsigned int flags, const char *operation)
{
    if (IS_ERR_OR_NULL(fl) || IS_ERR_OR_NULL(fl->apps)) {
        pr_warn_ratelimited("P465 FASTRPC MAP_REJECT op=%s flags=%#x errno=-EBADF\n",
                            operation, flags);
        return -EBADF;
    }
    if (flags == ADSP_MMAP_HEAP_ADDR ||
        flags == ADSP_MMAP_REMOTE_HEAP_ADDR) {
        pr_warn_ratelimited("P465 FASTRPC MAP_UNSUPPORTED op=%s flags=%#x errno=-EOPNOTSUPP remote_heap_compiled_out\n",
                            operation, flags);
        return -EOPNOTSUPP;
    }
    if (!VALID_FASTRPC_CID(fl->cid)) {
        pr_warn_ratelimited("P465 FASTRPC MAP_REJECT op=%s flags=%#x cid=%d errno=-ECHRNG\n",
                            operation, flags, fl->cid);
        return -ECHRNG;
    }
    if (IS_ERR_OR_NULL(fl->sctx) ||
        IS_ERR_OR_NULL(fl->sctx->smmu.dev)) {
        pr_warn_ratelimited("P465 FASTRPC MAP_REJECT op=%s flags=%#x cid=%d errno=-ENODEV no_CB_device\n",
                            operation, flags, fl->cid);
        return -ENODEV;
    }
    return 0;
}
'''
    s = once(s, "static int fastrpc_mmap_create(struct fastrpc_file *fl,",
             guard + "\nstatic int fastrpc_mmap_create(struct fastrpc_file *fl,",
             "map validator definition")
    intro = r'''
    err = a52_p465_validate_map(fl, mflags, "mmap_create");
    if (err)
        return err;
    if (!ppmap || !len) {
        pr_warn_ratelimited("P465 FASTRPC MAP_REJECT op=create fd=%d flags=%#x len=%zu errno=-EINVAL\n",
                            fd, mflags, len);
        return -EINVAL;
    }
    pr_info_ratelimited("P465 FASTRPC MAP_CREATE fd=%d flags=%#x attr=%#x len=%zu cb=%s cid=%d\n",
                        fd, mflags, attr, len,
                        dev_name(fl->sctx->smmu.dev), fl->cid);
'''
    s = edit_function(s, "fastrpc_mmap_create",
                      "\tif (!fl) {\n", intro + "\n\tif (!fl) {\n",
                      "validate first before malloc and dma_buf_get")
    # Proven P464 NULL dereference risk: NOMAP error log used me->dev=NULL.
    s = edit_function(s, "fastrpc_mmap_create",
                      "fd, len, dev_name(me->dev), PTR_ERR(map->table));",
                      "fd, len, dev_name(fl->sctx->smmu.dev), PTR_ERR(map->table));",
                      "NOMAP DMA attach-map failure log")
    # With IOMMU enabled the 5.10 donor did not reject empty scatterlists.
    sg = "\t\tmap->phys = sg_dma_address(map->table->sgl);"
    if s.count(sg) != 2:
        raise RuntimeError("P465 expected exactly two scatterlist lookups")
    check_sg = (
        "\t\tif (!map->table->sgl || !map->table->nents) {\n"
        "\t\t\tpr_warn_ratelimited(\"P465 FASTRPC EMPTY_SG fd=%d flags=%#x errno=-EIO\\n\",\n"
        "\t\t\t\tfd, mflags);\n"
        "\t\t\terr = -EIO;\n"
        "\t\t\tgoto bail;\n"
        "\t\t}\n"
    )
    s = s.replace(sg, check_sg + sg)

    # The exact original P464 DWARF maps +0x3a4/0x79c to
    # drivers/char/adsprpc.c:1591:
    #     map->phys = sg_dma_address(map->table->sgl);
    # Protect map->table ITSELF before any ->nents or ->sgl access.
    # A later !map->table->sgl check is insufficient for NULL table.
    null_table_guard = (
        "\t\tif (IS_ERR_OR_NULL(map->table)) {\n"
        "\t\t\terr = IS_ERR(map->table) ? PTR_ERR(map->table) : -EIO;\n"
        "\t\t\tpr_warn_ratelimited(\"P465 FASTRPC NULL_TABLE fd=%d flags=%#x errno=%d\\n\",\n"
        "\t\t\t\tfd, mflags, err);\n"
        "\t\t\tgoto bail;\n"
        "\t\t}\n"
    )
    s = edit_function(s, "fastrpc_mmap_create",
                      "\t\tVERIFY(err, map->table->nents == 1);",
                      null_table_guard +
                      "\t\tVERIFY(err, map->table->nents == 1);",
                      "NOMAP NULL table before nents")
    s = edit_function(s, "fastrpc_mmap_create",
                      "\t\tif (!sess->smmu.enabled) {",
                      null_table_guard +
                      "\t\tif (!sess->smmu.enabled) {",
                      "ordinary DMA_BUF NULL table before nents/sgl")

    # Catch both user mmap ioctls before dereferencing fl or ud. Flags
    # are printed in decimal-independent hex at every test round.
    for name, field, fd, size, op in (
        ("fastrpc_internal_mmap", "ud->flags", "ud->fd", "ud->size", "MMAP"),
        ("fastrpc_internal_mem_map", "ud->m.flags", "ud->m.fd",
         "ud->m.length", "MEM_MAP"),
    ):
        pre = (
            f"\tif (!fl || !ud) {{\n"
            f"\t\tpr_warn_ratelimited(\"P465 FASTRPC {op} null_ioctl errno=-EINVAL\\n\");\n"
            f"\t\treturn -EINVAL;\n"
            f"\t}}\n"
            f"\tpr_info_ratelimited(\"P465 FASTRPC {op} fd=%d flags=%#x size=%zu cid=%d\\n\",\n"
            f"\t\t\t\t{fd}, {field}, (size_t){size}, fl->cid);\n"
            f"\terr = a52_p465_validate_map(fl, {field}, \"{op}\");\n"
            f"\tif (err)\n"
            f"\t\treturn err;\n"
        )
        s = edit_function(s, name, "\tmutex_lock(&fl->internal_map_mutex);",
                          pre + "\tmutex_lock(&fl->internal_map_mutex);",
                          op + " entry guard")

    # ADD_PAGES and invocation buffers use the same CB-owned dma_alloc_attrs.
    s = edit_function(s, "fastrpc_buf_alloc",
                      "VERIFY(err, fl && fl->sctx != NULL);",
                      "VERIFY(err, fl && fl->apps && fl->sctx &&\n"
                      "\t       !IS_ERR_OR_NULL(fl->sctx->smmu.dev) && obuf);",
                      "dma allocation missing CB device")

    # Reject malformed unmap ioctls before dereferencing fl->dsp_proc_init.
    s = edit_function(s, "fastrpc_internal_munmap",
                      "\tVERIFY(err, fl->dsp_proc_init == 1);",
                      "\tif (!fl || !ud || !fl->apps) {\n"
                      "\t\tpr_warn_ratelimited(\"P465 FASTRPC MUNMAP invalid_ioctl errno=-EINVAL\\n\");\n"
                      "\t\treturn -EINVAL;\n"
                      "\t}\n"
                      "\tVERIFY(err, fl->dsp_proc_init == 1);",
                      "MUNMAP pointer guard")
    s = edit_function(s, "fastrpc_internal_munmap_fd",
                      "\tVERIFY(err, (fl && ud));",
                      "\tVERIFY(err, (fl && ud && fl->apps));",
                      "MUNMAP_FD pointer guard")
    s = edit_function(s, "fastrpc_internal_mem_unmap",
                      "\tmutex_lock(&fl->internal_map_mutex);",
                      "\tif (!fl || !ud || !fl->apps) {\n"
                      "\t\tpr_warn_ratelimited(\"P465 FASTRPC MEM_UNMAP invalid_ioctl errno=-EINVAL\\n\");\n"
                      "\t\treturn -EINVAL;\n"
                      "\t}\n"
                      "\tmutex_lock(&fl->internal_map_mutex);",
                      "MEM_UNMAP pointer guard")

    # Old heap-error cleanup returned without kfree when me->dev was NULL.
    s = edit_function(s, "fastrpc_mmap_free",
                      '\t\tif (me->dev == NULL) {\n'
                      '\t\t\tADSPRPC_ERR(\n'
                      '\t\t\t\t"failed to free remote heap allocation, device is not initialized\\n");\n'
                      '\t\t\treturn;\n'
                      '\t\t}',
                      '\t\tif (me->dev == NULL) {\n'
                      '            pr_warn_ratelimited("P465 FASTRPC FREE_HEAP no_device errno=-ENODEV\\n");\n'
                      '            goto bail;\n'
                      '\t\t}',
                      "heap NULL cleanup without leak")
    s = edit_function(s, "fastrpc_mmap_free",
                      "\t\tvmid = fl->apps->channel[cid].vmid;",
                      "        if (!fl->apps || !VALID_FASTRPC_CID(cid))\n"
                      "            pr_warn_ratelimited(\"P465 FASTRPC FREE_MAP missing_apps errno=-ENODEV\\n\");\n"
                      "        vmid = (fl->apps && VALID_FASTRPC_CID(cid)) ?\n"
                      "               fl->apps->channel[cid].vmid : 0;",
                      "free map guard without dropping DMA cleanup")
    return s

def check(s):
    for x in (
        TAG, "P465 FASTRPC MAP_UNSUPPORTED op=%s flags=%#x errno=-EOPNOTSUPP",
        "P465 FASTRPC MAP_CREATE fd=%d flags=%#x",
        "P465 FASTRPC MMAP fd=%d flags=%#x",
        "P465 FASTRPC MEM_MAP fd=%d flags=%#x",
        "P465 FASTRPC EMPTY_SG fd=%d flags=%#x",
        "P465 FASTRPC NULL_TABLE fd=%d flags=%#x errno=%d",
        "P465 FASTRPC MUNMAP invalid_ioctl",
        "P465 FASTRPC MEM_UNMAP invalid_ioctl",
        "fd, len, dev_name(fl->sctx->smmu.dev), PTR_ERR(map->table));",
        "P461 FASTRPC RPMSG ADSP ACCEPT",
        "P461 FASTRPC SMMU ATTACH session=",
    ):
        if x not in s:
            raise RuntimeError("P465 generated source missing "+x)
    if "dev_name(me->dev)" in s:
        raise RuntimeError("P465 NULL diagnostics still possible")
    if s.count("a52_p465_validate_map(fl,") != 3:
        raise RuntimeError("P465 changed map validator invocation count")
    if s.count("dma_buf_attach(") != 2:
        raise RuntimeError("P465 changed CB DMA attach callsites")
    if s.count("P465 FASTRPC EMPTY_SG fd=") != 2:
        raise RuntimeError("P465 SG entries not guarded on both mmap branches")
    if s.count("P465 FASTRPC NULL_TABLE fd=") != 2:
        raise RuntimeError("P465 missing NULL table guard on one mmap branch")
    create=s[s.index("static int fastrpc_mmap_create("):
             s.index("static inline bool fastrpc_get_cached_buf(")]
    if create.count("sg_dma_address(map->table->sgl)") != 2:
        raise RuntimeError("P465 mapping site changed or missing")
    if not (create.index("P465 FASTRPC NULL_TABLE fd=") <
            create.index("VERIFY(err, map->table->nents == 1)") <
            create.index("sg_dma_address(map->table->sgl)") <
            create.rindex("P465 FASTRPC NULL_TABLE fd=") <
            create.index("if (!sess->smmu.enabled)") <
            create.rindex("sg_dma_address(map->table->sgl)")):
        raise RuntimeError("P465 NULL-table guards must PRECEDE both nents/sgl uses")
    free=s[s.index("static void fastrpc_mmap_free("):
           s.index("static int fastrpc_session_alloc(")]
    if not (free.index("if (me->dev == NULL)") <
            free.index("goto bail;",free.index("if (me->dev == NULL)")) <
            free.rindex("bail:") < free.rindex("kfree(map);")):
        raise RuntimeError("P465 remoteheap free must jump directly to kfree")
    return {"heap_flags":"EOPNOTSUPP before any map allocation",
            "DMA_device":"fl->sctx->smmu.dev",
            "supported_maps":"DMA_BUF / NOMAP / ADD_PAGES with CB validation",
            "mmap_flags_logged":True,"sensor_INIT_unchanged":True,
            "hardware_validated":False}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True,type=Path)
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--report",type=Path)
    a=ap.parse_args()
    f=a.root/FILE
    s=f.read_text()
    if not a.check_only:
        s=patch(s)
        f.write_text(s)
    result=check(s)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P465 MMAP SAFETY SOURCE PASS",json.dumps(result))

if __name__=="__main__":
    main()
