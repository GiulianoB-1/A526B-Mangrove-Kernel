#!/usr/bin/env python3
"""P472 A2a: link TG q6core/cal against ACK 5.10 legacy ION, NO DMABUF_HEAPS.

Separate from rejected A2. Base must be hardware-proven A1 f3a4cbb8;
no A2 DMA-HEAP patch, no fake ION shim, no AFE/ASM/ADM, NO ARM.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

DONOR = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
ROOT_REL = Path("drivers/soc/qcom/p472_tg_audio")
COPY = (
    "dsp/adsp_err.c",
    "dsp/audio_calibration.c",
    "dsp/audio_cal_utils.c",
    "dsp/msm_audio_ion.c",
    "include/dsp/q6asm-v2.h",
    "include/dsp/rtac.h",
)
INIT = r'''// SPDX-License-Identifier: GPL-2.0-only
/* P472 A2a: donor q6core + cal/real legacy ION, no routing or DAC. */
#include <linux/init.h>
#include <linux/kernel.h>

extern int adsp_err_init(void);
extern void adsp_err_exit(void);
extern int audio_cal_init(void);
extern void audio_cal_exit(void);
extern int core_init(void);
extern void core_exit(void);
extern int msm_audio_ion_init(void);
extern void msm_audio_ion_exit(void);

static int __init p472_a2a_init(void)
{
	int rc;

	rc = adsp_err_init();
	if (rc)
		goto fail;
	rc = audio_cal_init();
	if (rc)
		goto err_cal;
	rc = core_init();
	if (rc)
		goto err_core;
	rc = msm_audio_ion_init();
	if (rc)
		goto err_ion;
	pr_info("P472 A2A TG Q6CORE_CAL_ION_LINKED real_ion=1 heaps=0\n");
	return 0;
err_ion:
	core_exit();
err_core:
	audio_cal_exit();
err_cal:
	adsp_err_exit();
fail:
	pr_err("P472 A2A Q6CORE_INIT_FAILED rc=%d\n", rc);
	return rc;
}
late_initcall(p472_a2a_init);
'''
HEAP_LOOKUP = r'''
/*
 * TG 4.19 named system heap ID=25 and audio heap ID=28.
 * ACK 5.10 ION allocates the system heap using ION_HEAP_SYSTEM=BIT(0),
 * while custom heap ids are runtime-assigned. Never use TG's fixed mask.
 * Preserve the separate audio heap and fail closed when absent.
 */
static struct dma_buf *p472_a2a_ion_alloc(size_t len, bool smmu)
{
	struct ion_heap_data *heaps;
	struct dma_buf *buf;
	size_t count, found, i;
	unsigned int mask = 0;

	if (smmu)
		return ion_alloc(len, ION_HEAP_SYSTEM, 0);

	count = ion_query_heaps_kernel(NULL, 0);
	if (!count || count > ION_NUM_MAX_HEAPS)
		return ERR_PTR(-ENODEV);
	heaps = kcalloc(count, sizeof(*heaps), GFP_KERNEL);
	if (!heaps)
		return ERR_PTR(-ENOMEM);
	found = ion_query_heaps_kernel(heaps, count);
	for (i = 0; i < found; ++i) {
		if (!strcmp(heaps[i].name, "audio") &&
		    heaps[i].heap_id < 32) {
			mask = BIT(heaps[i].heap_id);
			break;
		}
	}
	kfree(heaps);
	if (!mask) {
		pr_err("P472 A2A ION_AUDIO_HEAP_MISSING fail_closed=1\n");
		return ERR_PTR(-ENODEV);
	}
	buf = ion_alloc(len, mask, 0);
	return buf;
}

'''

def single(src, old, new, label):
    occurrences = src.count(old)
    if occurrences != 1:
        raise RuntimeError("P472 A2a changed TG donor anchor: " +
                           label + " count=" + str(occurrences))
    return src.replace(old, new, 1)

def read(root, relative):
    return (root / relative).read_text()

def stage(root, donor_dir):
    actual = subprocess.check_output(
        ["git", "-C", str(donor_dir), "rev-parse", "HEAD"], text=True
    ).strip()
    if actual != DONOR:
        raise RuntimeError("P472 A2a donor pin mismatch " + actual)
    d = root / ROOT_REL
    if not (d / "ipc/apr.c").is_file() or not (d / "dsp/q6core.c").is_file():
        raise RuntimeError("P472 A2a requires staged hardware-good A1")
    if (d / "dsp/msm_audio_ion.c").exists():
        raise RuntimeError("P472 A2a refuses duplicate ION staging")
    # ACK native ION is a real registered provider, not the DMA-HEAP wrapper.
    ack_ion = read(root, "drivers/staging/android/ion/ion.c")
    ack_h = read(root, "include/linux/ion.h")
    for marker in ("struct dma_buf *ion_alloc(size_t len",
                   "ion_query_heaps_kernel("):
        if marker not in ack_ion:
            raise RuntimeError("P472 A2a existing ACK ION API missing " + marker)
    for marker in ("ION_HEAP_SYSTEM", "ION_NUM_MAX_HEAPS"):
        if marker not in ack_h and marker not in read(root, "include/uapi/linux/ion.h"):
            raise RuntimeError("P472 A2a existing ACK ION constant missing " + marker)
    for rel in COPY:
        src = donor_dir / "techpack/audio" / rel
        if not src.is_file():
            raise RuntimeError("P472 A2a pinned donor file missing: " + rel)
        target = d / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)

    asm = d / "include/dsp/q6asm-v2.h"
    asm.write_text(single(asm.read_text(), "#include <linux/msm_ion.h>",
                          "#include <linux/ion.h>",
                          "q6asm ABI forward header"))

    ion_hdr = d / "include/dsp/msm_audio_ion.h"
    ion_hdr.write_text(single(ion_hdr.read_text(), "#include <linux/msm_ion.h>",
                              "#include <linux/ion.h>",
                              "TG ion header uses real ACK ION types"))

    cal = d / "dsp/audio_calibration.c"
    cal.write_text(single(cal.read_text(),
                          "#include <linux/msm_ion.h>",
                          "#include <linux/compat.h>",
                          "native compat_ptr declaration"))

    utils = d / "dsp/audio_cal_utils.c"
    utils.write_text(single(utils.read_text(),
                            "#include <dsp/audio_cal_utils.h>",
                            "#include <dsp/audio_cal_utils.h>\n#include <dsp/msm_audio_ion.h>",
                            "real ION function prototypes for cal utils"))

    ion = d / "dsp/msm_audio_ion.c"
    body = ion.read_text()
    body = single(body, "#include <linux/ion_kernel.h>",
                  "#include <linux/ion.h>", "ACK ION native kernel header")
    body = single(body, "/**\n * msm_audio_ion_alloc -",
                  HEAP_LOOKUP + "/**\n * msm_audio_ion_alloc -",
                  "ION native heap policy")
    body = single(body,
                  "ion_alloc(bufsz, ION_HEAP(ION_SYSTEM_HEAP_ID), 0)",
                  "p472_a2a_ion_alloc(bufsz, true)",
                  "SMMU system heap id parity")
    body = single(body,
                  "ion_alloc(bufsz, ION_HEAP(ION_AUDIO_HEAP_ID), 0)",
                  "p472_a2a_ion_alloc(bufsz, false)",
                  "non-SMMU exact audio heap policy")
    # The non-SMMU path needs initialized locks/lists before any allocation.
    ion_init = '''int __init msm_audio_ion_init(void)
{
	return platform_driver_register(&msm_audio_ion_driver);'''
    correct_init = '''int __init msm_audio_ion_init(void)
{
	INIT_LIST_HEAD(&msm_audio_ion_data.alloc_list);
	mutex_init(&msm_audio_ion_data.list_mutex);
	return platform_driver_register(&msm_audio_ion_driver);'''
    body = single(body, ion_init, correct_init, "non-SMMU list init")
    ion.write_text(body)

    (d / "dsp/p472_a2a_core_init.c").write_text(INIT)
    makefile = d / "dsp/Makefile"
    makefile.write_text(
        makefile.read_text() +
        "\n# A2a: link real TG q6core/calibration via existing 5.10 ION\n" +
        "obj-$(CONFIG_P472_TG_Q6CORE) += adsp_err.o audio_calibration.o " +
        "audio_cal_utils.o msm_audio_ion.o p472_a2a_core_init.o\n"
    )

def check(root):
    d = root / ROOT_REL
    ion = read(d, "dsp/msm_audio_ion.c")
    cal = read(d, "dsp/audio_calibration.c")
    mk = read(d, "dsp/Makefile")
    asm = read(d, "include/dsp/q6asm-v2.h")
    checks = {
        "native_ack_ion_alloc": "return ion_alloc(len, ION_HEAP_SYSTEM, 0);" in ion,
        "native_ack_ion_header": "#include <linux/ion.h>" in ion,
        "real_audio_heap_discovery": 'ion_query_heaps_kernel(heaps, count)' in ion,
        "non_smmu_audio_fail_closed": "ION_AUDIO_HEAP_MISSING fail_closed=1" in ion,
        "donor_dma_buffer_attachment_preserved": "dma_buf_map_attachment(" in ion,
        "donor_dma_buffer_import_preserved": "dma_buf_get(fd)" in ion,
        "donor_cached_ion_flags_preserved": "ION_FLAG_CACHED" in ion,
        "donor_ion_get_flags_preserved": "dma_buf_get_flags(" in ion,
        "no_dma_heap_alloc": not any(
            s in ion for s in ("dma_heap_find(", "dma_heap_buffer_alloc(",
                             "p472_a2_heap_alloc", "CONFIG_DMABUF_HEAPS")),
        "no_android_4_19_heap_masks": "ION_HEAP(ION_AUDIO_HEAP_ID)" not in ion,
        "compat_ioctl_header": "#include <linux/compat.h>" in cal,
        "calibration_compiled": all(x in mk for x in (
            "audio_calibration.o", "audio_cal_utils.o", "msm_audio_ion.o")),
        "q6core_selected_for_link": "obj-$(CONFIG_P472_TG_Q6CORE) += q6core.o" in mk,
        "real_core_init": "p472_a2a_core_init.o" in mk,
        "no_fake_ion": "static int msm_audio_ion_alloc" not in ion,
        "no_legacy_q6asm_include": "#include <linux/msm_ion.h>" not in asm,
    }
    failed = [k for k,v in checks.items() if not v]
    if failed:
        raise RuntimeError("P472 A2a source gate failed: " + ", ".join(failed))
    return {
        "phase":"P472-A2A-Q6CORE-CAL-ACK-ION",
        "base":"hardware-good f3a4cbb8326a35a4b9c9f5ff9873b2f79a014b31",
        "donor":DONOR,
        "status":"SOURCE_PASS",
        "checks":checks,
        "ion":"pinned ACK 5.10 ion_alloc + heap-query, NOT DMA-BUF HEAPS",
        "q6core":"native link with TG calibration and real msm_audio_ion",
        "no_arm":True, "hardware_verified":False, "keyboard_verified":False,
        "bt_restart_regression_resolved":False,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--tg",type=Path)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    if not a.check_only:
        if a.tg is None:
            raise SystemExit("P472 A2a requires pinned TG --tg")
        stage(a.root, a.tg)
    result=check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P472 A2A: linked q6core/cal with real ACK legacy ION, no DMA-BUF heaps, NO ARM")

if __name__=="__main__":
    main()
