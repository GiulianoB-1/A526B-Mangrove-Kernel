#!/usr/bin/env python3
"""P472 A2: native TG q6core + real calibration and DMA-HEAP port, NO ARM.

This is a separate experimental branch. It does not replace the proven A1
APR source, provide dummy ION implementations or enable any audio routing.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

DONOR_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
REL = Path("drivers/soc/qcom/p472_tg_audio")
COPIES = (
    "dsp/audio_cal_utils.c",
    "dsp/audio_calibration.c",
    "dsp/msm_audio_ion.c",
    "dsp/adsp_err.c",
    "include/dsp/q6asm-v2.h",
    "include/dsp/rtac.h",
)
INIT = r'''// SPDX-License-Identifier: GPL-2.0-only
/* P472 A2: only the native TG q6core, calibration and allocator init chain. */
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/errno.h>

extern int adsp_err_init(void);
extern void adsp_err_exit(void);
extern int audio_cal_init(void);
extern void audio_cal_exit(void);
extern int core_init(void);
extern void core_exit(void);
extern int msm_audio_ion_init(void);
extern void msm_audio_ion_exit(void);

static int __init p472_a2_q6core_init(void)
{
	int rc;

	rc = adsp_err_init();
	if (rc)
		return rc;
	rc = audio_cal_init();
	if (rc)
		goto err_cal;
	rc = core_init();
	if (rc)
		goto err_core;
	rc = msm_audio_ion_init();
	if (rc)
		goto err_ion;
	pr_info("P472 A2 TG Q6CORE_LINKED cal=1 ion_dma_heap=1 init_rc=0\n");
	return 0;

err_ion:
	core_exit();
err_core:
	audio_cal_exit();
err_cal:
	adsp_err_exit();
	pr_err("P472 A2 TG Q6CORE_INIT_FAILED rc=%d\n", rc);
	return rc;
}
late_initcall(p472_a2_q6core_init);
'''

ALLOC = r'''
/* GKI 5.10 DMA-HEAP replaces ION_HEAP(ION_SYSTEM_HEAP_ID).
 * For non-IOMMU operation require an actual audio carveout heap. Never
 * substitute a generic system heap for hardware needing physical memory.
 */
static struct dma_buf *p472_a2_heap_alloc(size_t len, bool smmu)
{
	struct dma_heap *heap;
	struct dma_buf *buf;
	const char *name = smmu ? "system" : "audio";

	heap = dma_heap_find(name);
	if (!heap) {
		pr_err("P472 A2 AUDIO_HEAP_MISSING name=%s\n", name);
		return ERR_PTR(-ENODEV);
	}
	buf = dma_heap_buffer_alloc(heap, len, O_RDWR | O_CLOEXEC, 0);
	dma_heap_put(heap);
	return buf;
}

'''
CACHES = r'''int msm_audio_ion_cache_operations(struct audio_buffer *abuff, int cache_op)
{
	int rc;

	if (!abuff || !abuff->dma_buf)
		return -EINVAL;
	if (cache_op != MSM_AUDIO_ION_INV_CACHES &&
	    cache_op != MSM_AUDIO_ION_CLEAN_CACHES)
		return -EINVAL;
	/* DMA-BUF exporters own the cache coherency protocol. Always
	 * synchronize; never treat an unknown heap as uncached. */
	rc = dma_buf_begin_cpu_access(abuff->dma_buf, DMA_BIDIRECTIONAL);
	if (rc)
		return rc;
	return dma_buf_end_cpu_access(abuff->dma_buf, DMA_BIDIRECTIONAL);
}
'''

def one(txt, old, new, name):
    if txt.count(old) != 1:
        raise RuntimeError("P472 A2 donor ABI site changed: " + name + " count=" + str(txt.count(old)))
    return txt.replace(old, new, 1)

def stage(root, tg):
    head = subprocess.check_output(["git", "-C", str(tg), "rev-parse", "HEAD"], text=True).strip()
    if head != DONOR_SHA:
        raise RuntimeError("P472 A2 donor SHA changed: " + head)
    dest = root / REL
    if not (dest / "dsp/q6core.c").is_file():
        raise RuntimeError("P472 A1 TG APR must stage before A2")
    if (dest / "dsp/msm_audio_ion.c").exists():
        raise RuntimeError("P472 A2 attempted double staging")
    for rel in COPIES:
        src = tg / "techpack/audio" / rel
        if not src.is_file():
            raise RuntimeError("P472 A2 TG donor source missing: " + rel)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    q6asm = dest / "include/dsp/q6asm-v2.h"
    q6asm.write_text(one(q6asm.read_text(), "#include <linux/msm_ion.h>",
                           "#include <linux/dma-buf.h>",
                           "q6asm legacy ion include"))
    audio_ion_h = dest / "include/dsp/msm_audio_ion.h"
    audio_ion_h.write_text(one(audio_ion_h.read_text(),
                               "#include <linux/msm_ion.h>",
                               "#include <linux/dma-buf.h>",
                               "msm_audio_ion.h legacy ion include"))
    cal_h = dest / "include/dsp/audio_cal_utils.h"
    cal_h.write_text(one(cal_h.read_text(),
                         "#include <linux/mutex.h>\n",
                         "#include <linux/mutex.h>\n#include <dsp/msm_audio_ion.h>\n",
                         "audio calibration real allocator API"))
    cal = dest / "dsp/audio_calibration.c"
    cal.write_text(one(cal.read_text(),
                       "#include <linux/msm_ion.h>\n", "",
                       "calibration legacy ion include"))
    ion = dest / "dsp/msm_audio_ion.c"
    src = ion.read_text()
    src = one(src, "#include <linux/ion_kernel.h>",
              "#include <linux/dma-heap.h>\n#include <dsp/q6asm-v2.h>",
              "native DMA heap API and struct audio_buffer")
    src = one(src, "\tunsigned long ionflag = 0;\n", "",
              "legacy mapping cache flags")
    old_sync = '''\t/* For uncached buffers, avoid cache maintanance */
\trc = dma_buf_get_flags(alloc_data->dma_buf, &ionflag);
\tif (rc) {
\t\tdev_err(cb_dev, "%s: dma_buf_get_flags failed: %d\\n",
\t\t\t__func__, rc);
\t\tgoto detach_dma_buf;
\t}

\tif (!(ionflag & ION_FLAG_CACHED))
\t\talloc_data->attach->dma_map_attrs |= DMA_ATTR_SKIP_CPU_SYNC;
'''
    src = one(src, old_sync,
              "\t/* Keep CPU/DMA synchronization for all DMA-BUF heaps. */\n",
              "ION_FLAG_CACHED map-attrs optimization")
    src = one(src, "/**\n * msm_audio_ion_alloc -", ALLOC + "/**\n * msm_audio_ion_alloc -",
              "real heap allocator insert")
    src = one(src, "ion_alloc(bufsz, ION_HEAP(ION_SYSTEM_HEAP_ID), 0)",
              "p472_a2_heap_alloc(bufsz, true)", "system heap allocation")
    src = one(src, "ion_alloc(bufsz, ION_HEAP(ION_AUDIO_HEAP_ID), 0)",
              "p472_a2_heap_alloc(bufsz, false)", "audio heap allocation")
    start = src.index("int msm_audio_ion_cache_operations(struct audio_buffer *abuff, int cache_op)")
    end = src.index("EXPORT_SYMBOL(msm_audio_ion_cache_operations);", start)
    old_cache = src[start:end]
    if old_cache.count("ION_FLAG_CACHED") != 1 or old_cache.count("dma_buf_begin_cpu_access") != 1:
        raise RuntimeError("P472 A2 cache operation donor body changed")
    src = src[:start] + CACHES + src[end:]
    ion.write_text(src)
    init = dest / "dsp/p472_a2_q6core_boot.c"
    init.write_text(INIT)
    makefile = dest / "dsp/Makefile"
    makefile.write_text(makefile.read_text() +
                       "\n# P472 A2 real TG calibration and DMA-BUF heap driver\n" +
                       "obj-$(CONFIG_P472_TG_Q6CORE) += audio_calibration.o audio_cal_utils.o msm_audio_ion.o adsp_err.o p472_a2_q6core_boot.o\n")

def validate(root):
    dest = root / REL
    ion = (dest / "dsp/msm_audio_ion.c").read_text()
    mk = (dest / "dsp/Makefile").read_text()
    tests = {
        "real_native_dma_heap_allocator": "dma_heap_buffer_alloc(" in ion,
        "no_legacy_ion_alloc": "ion_alloc(bufsz, ION_HEAP(" not in ion,
        "no_legacy_ion_header": "#include <linux/ion_kernel.h>" not in ion,
        "smmu_requires_system_heap": 'smmu ? "system" : "audio"' in ion,
        "audio_carveout_fail_closed": "AUDIO_HEAP_MISSING name=%s" in ion,
        "tg_dma_buffer_map": "dma_buf_map_attachment(" in ion,
        "tg_dma_buffer_import": "dma_buf_get(fd)" in ion,
        "tg_dma_buffer_unmap": "dma_buf_unmap_attachment(" in ion,
        "tg_smmu_sid": "MSM_AUDIO_SMMU_SID_OFFSET" in ion,
        "tg_calibration_link": "audio_calibration.o audio_cal_utils.o" in mk,
        "q6core_linked_source": "obj-$(CONFIG_P472_TG_Q6CORE) += q6core.o" in mk,
        "adsp_error_and_init": "adsp_err.o p472_a2_q6core_boot.o" in mk,
        "no_private_apr": "P472_A0" not in mk,
    }
    failed = [k for k,v in tests.items() if not v]
    if failed:
        raise RuntimeError("P472 A2 source gate failed: " + ", ".join(failed))
    return {"phase":"P472-A2-NATIVE-Q6CORE","status":"SOURCE_PASS",
            "touchgrass":DONOR_SHA,"tests":tests,
            "hardware_verified":False,"no_arm":True}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--tg", type=Path)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    a=p.parse_args()
    if not a.check_only:
        if a.tg is None:
            raise SystemExit("P472 A2 donor --tg required")
        stage(a.root, a.tg)
    data=validate(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(data, indent=2, sort_keys=True)+"\n")
    print("P472 A2 real TG q6core + audio calibration + DMA-HEAP source gate PASS; NO ARM")

if __name__ == "__main__":
    main()
