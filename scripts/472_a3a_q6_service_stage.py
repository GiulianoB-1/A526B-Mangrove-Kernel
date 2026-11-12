#!/usr/bin/env python3
"""P472 A3a real TG Q6 services, separate Kconfig, fail-closed native link.

Donor micr0softstore/a52xq @ 6bf351bd; dsp/Kbuild:114-130.
This copies actual donor sources into the 5.10 tree. No synthetic APR,
audio devices, ADSP version replies, ASoC card, or amplifier.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

DONOR = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
AUDIO = Path("drivers/soc/qcom/p472_tg_audio")
K = Path("drivers/soc/qcom/Kconfig")
SOURCE = (
    "q6audio-v2.c", "q6common.c", "q6adm.c", "q6afe.c",
    "q6asm.c", "q6lsm.c", "q6voice.c", "rtac.c",
    "msm-audio-event-notify.c", "avtimer.c",
)
HELPERS = ("q6afecal-hwdep.h", "q6_init.h")
KCONFIG = """
config P472_A3A_Q6
    bool "P472 A3a real TG Q6 AFE ASM ADM LSM, no ASoC"
    depends on P472_TG_APR && P472_TG_Q6CORE
    default n
    help
      Link the actual TG q6audio/Q6 services and register through the
      existing TG APR. No sound card, speaker, new APR implementation.
"""
LINK = """
# A3a: TG DSP Kbuild:114-130, excluding already-linked A2a and
# original q6_init.c (would reinitialize A2a cal/q6core/ION).
obj-$(CONFIG_P472_A3A_Q6) += q6audio-v2.o q6common.o q6adm.o q6afe.o q6asm.o q6lsm.o
obj-$(CONFIG_P472_A3A_Q6) += q6voice.o rtac.o msm-audio-event-notify.o avtimer.o p472_a3a_q6_init.o
"""
BOOT = r'''// SPDX-License-Identifier: GPL-2.0-only
/* P472 A3a: real TG services only. No ASoC machine, no speaker routes.
 * TG 4.19 dsp/q6_init.c:10-29 reinitializes q6core/cal/ION.
 * In 5.10 A2a those providers are ALREADY linked and initialized.
 * Defer only version verification, never fabricate a DSP success reply.
 */
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/workqueue.h>
#include <linux/jiffies.h>
#include <dsp/q6core.h>

extern int rtac_init(void);
extern void rtac_exit(void);
extern int adm_init(void);
extern void adm_exit(void);
extern int afe_init(void);
extern void afe_exit(void);
extern int q6asm_init(void);
extern void q6asm_exit(void);
extern int q6lsm_init(void);
extern void q6lsm_exit(void);

static unsigned int p472_a3a_checks;

static void p472_a3a_version_work(struct work_struct *work);
static DECLARE_DELAYED_WORK(p472_a3a_version_job, p472_a3a_version_work);

static void p472_a3a_version_work(struct work_struct *work)
{
	int afe, asm_ver, adm;
	if (!q6core_is_adsp_ready()) {
		if (p472_a3a_checks++ < 9)
			schedule_delayed_work(&p472_a3a_version_job, 10 * HZ);
		else
			pr_err("P472 A3a Q6 VERSION_FAIL adsp_not_ready\n");
		return;
	}
	/* Actual AVCS_GET_FWK_VERSION through the proven TG APR. */
	afe = q6core_get_avcs_api_version_per_service(
			APRV2_IDS_SERVICE_ID_ADSP_AFE_V);
	asm_ver = q6core_get_avcs_api_version_per_service(
			APRV2_IDS_SERVICE_ID_ADSP_ASM_V);
	adm = q6core_get_avcs_api_version_per_service(
			APRV2_IDS_SERVICE_ID_ADSP_ADM_V);
	pr_info("P472 A3a Q6 ADSP_VERSION_REPLY afe=%d asm=%d adm=%d\n",
		afe, asm_ver, adm);
	if (afe != 9 || asm_ver != 2 || adm != 4)
		pr_err("P472 A3a Q6 VERSION_FAIL afe=%d asm=%d adm=%d\n",
		       afe, asm_ver, adm);
}

static int __init p472_a3a_start(void)
{
	int rc;

	/* TG q6_init.c:12-21, but A2a already owns adsp_err/cal/core/ION. */
	rc = rtac_init();
	if (rc)
		goto failed;
	rc = adm_init();
	if (rc)
		goto undo_rtac;
	pr_info("P472 A3a Q6 adm registered rc=0\n");
	rc = afe_init();
	if (rc)
		goto undo_adm;
	pr_info("P472 A3a Q6 afe registered rc=0\n");
	rc = q6asm_init();
	if (rc)
		goto undo_afe;
	pr_info("P472 A3a Q6 asm registered rc=0\n");
	rc = q6lsm_init();
	if (rc)
		goto undo_asm;
	pr_info("P472 A3a Q6 lsm registered rc=0\n");

	/* Only log versions returned by the actual ADSP. */
	schedule_delayed_work(&p472_a3a_version_job, 10 * HZ);
	return 0;
undo_asm:
	q6asm_exit();
undo_afe:
	afe_exit();
undo_adm:
	adm_exit();
undo_rtac:
	rtac_exit();
failed:
	pr_err("P472 A3a Q6 REGISTER_FAIL rc=%d\n", rc);
	return rc;
}
late_initcall_sync(p472_a3a_start);
'''

def one(src, old, new, name):
    n = src.count(old)
    if n != 1:
        raise RuntimeError(f"P472 A3a {name}: anchor={n}, expected 1")
    return src.replace(old, new, 1)

def pin(tg):
    sha = subprocess.check_output(["git", "-C", str(tg),
                                   "rev-parse", "HEAD"], text=True).strip()
    if sha != DONOR:
        raise RuntimeError("P472 A3a pinned TG SHA drift " + sha)
    return tg / "techpack/audio"

def stage(root, tg):
    donor = pin(tg)
    kb = (donor / "dsp/Kbuild").read_text()
    section = kb.split("ifdef CONFIG_SND_SOC_MSM_QDSP6V2_INTF")
    if len(section) != 2:
        raise RuntimeError("P472 A3a TG QDSP6V2 Kbuild section changed")
    section = section[1].split("endif", 1)[0]
    needed = tuple(x.replace(".c", ".o") for x in SOURCE)
    for obj in needed:
        if section.count("Q6_OBJS += " + obj) != 1:
            raise RuntimeError("P472 A3a Kbuild donor dependency not unique: " + obj)
    for obj in ("audio_calibration.o", "audio_cal_utils.o", "q6core.o",
                "adsp_err.o", "msm_audio_ion.o", "q6_init.o"):
        if section.count("Q6_OBJS += " + obj) != 1:
            raise RuntimeError("P472 A3a existing A2a or TG init dependency changed " + obj)
    dest = root / AUDIO
    if not (dest / "dsp/q6core.c").is_file() or not (dest / "dsp/msm_audio_ion.c").is_file():
        raise RuntimeError("P472 A3a requires staged A2a-HLT providers")
    for srcname in SOURCE:
        source = donor / "dsp" / srcname
        if not source.is_file():
            raise RuntimeError("P472 A3a source unavailable " + srcname)
        target = dest / "dsp" / srcname
        if target.exists():
            raise RuntimeError("P472 A3a duplicate staging: " + srcname)
        shutil.copy2(source, target)
    for srcname in HELPERS:
        source = donor / "dsp" / srcname
        target = dest / "dsp" / srcname
        if not target.exists():
            shutil.copy2(source, target)
    # Preserve the existing A2a ION/ABI adaptations; copy only missing
    # pinned donor headers, never replace adjusted 5.10 definitions.
    for relative in ("include/dsp", "include/ipc", "include/uapi"):
        droot = donor / relative
        if not droot.is_dir():
            raise RuntimeError("P472 A3a donor header path unavailable "+relative)
        for path in sorted(droot.rglob("*.h")):
            target = dest / path.relative_to(donor)
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    init = dest / "dsp/p472_a3a_q6_init.c"
    if init.exists():
        raise RuntimeError("P472 A3a init collision")
    init.write_text(BOOT)
    mk = dest / "dsp/Makefile"
    mk.write_text(one(mk.read_text(),
                      "obj-$(CONFIG_P472_TG_Q6CORE) += q6core.o\n",
                      "obj-$(CONFIG_P472_TG_Q6CORE) += q6core.o\n" + LINK,
                      "real Q6 service object linkage"))
    k = root / K
    k.write_text(one(k.read_text(), "config P472_TG_Q6CORE\n",
                     KCONFIG + "\nconfig P472_TG_Q6CORE\n",
                     "independent Kconfig definition"))

def check(root):
    d = root / AUDIO
    mk = (d / "dsp/Makefile").read_text()
    k = (root / K).read_text()
    init = (d / "dsp/p472_a3a_q6_init.c").read_text()
    for s in SOURCE:
        if not (d / "dsp" / s).is_file():
            raise RuntimeError("P472 A3a missing donor "+s)
    if k.count("config P472_A3A_Q6") != 1 or "default n" not in k.split("config P472_A3A_Q6")[1].split("config ")[0]:
        raise RuntimeError("P472 A3a must have independent default-OFF Kconfig")
    required_objects = ("q6audio-v2.o", "q6common.o", "q6adm.o", "q6afe.o",
                        "q6asm.o", "q6lsm.o", "q6voice.o", "rtac.o",
                        "msm-audio-event-notify.o", "avtimer.o",
                        "p472_a3a_q6_init.o")
    for item in required_objects:
        if item not in mk:
            raise RuntimeError("P472 A3a missing linked object "+item)
    for service in ("adm", "afe", "asm", "lsm"):
        if f"P472 A3a Q6 {service} registered rc=0" not in init:
            raise RuntimeError("P472 A3a true service marker absent "+service)
    for marker in ("q6core_get_avcs_api_version_per_service(",
                   "APRV2_IDS_SERVICE_ID_ADSP_AFE_V",
                   "APRV2_IDS_SERVICE_ID_ADSP_ASM_V",
                   "APRV2_IDS_SERVICE_ID_ADSP_ADM_V",
                   "afe != 9 || asm_ver != 2 || adm != 4",
                   "late_initcall_sync(p472_a3a_start)"):
        if marker not in init:
            raise RuntimeError("P472 A3a version/real-init gate missing "+marker)
    # A comment in LINK intentionally describes why q6_init.c is excluded.
    # Inspect real Kbuild assignments, not a raw substring in comments.
    def linked_q6_init(makefile):
        for line in makefile.splitlines():
            line = line.partition("#")[0].strip()
            if not line or not line.startswith(("obj-", "p472_")):
                continue
            if any(op in line for op in ("+=", ":=", "=")):
                if "q6_init.o" in line.split():
                    return True
        return False

    # Regression check: comments are documentation; an object assignment
    # is a real duplicate-init risk and must still abort A3a.
    if linked_q6_init("# original q6_init.o is excluded\n"):
        raise RuntimeError("P472 A3a Kbuild audit rejects comment text")
    if not linked_q6_init("obj-$(CONFIG_P472_A3A_Q6) += q6_init.o\n"):
        raise RuntimeError("P472 A3a Kbuild audit missed a linked initializer")
    if linked_q6_init(mk):
        raise RuntimeError("P472 A3a would double-init A2a q6core/cal/ION")
    if (d / "asoc/kona.c").exists():
        raise RuntimeError("P472 A3a must not register any ASoC machine card")
    if (root / "drivers/soc/qcom/Kconfig").read_text().count("config P472_A3_SOUND_CARD"):
        raise RuntimeError("P472 A3a must not silently enable incomplete full A3")
    return {"stage":"P472-A3A","status":"SOURCE_PASS",
            "donor":DONOR,"services":["AFE","ASM","ADM","LSM"],
            "real_version_query":True,"expected_api_versions":{"AFE":9,"ASM":2,"ADM":4},
            "no_asoc":True,"no_arm":True,"no_fake_device":True,
            "hardware_verified":False}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--tg", type=Path)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    if not args.check_only:
        if not args.tg:
            raise SystemExit("P472 A3a pinned TG source required")
        stage(args.root,args.tg)
    report = check(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("P472 A3a pinned TG Q6 dependency source audit PASS; real native link required; NO ARM")

if __name__ == "__main__":
    main()
