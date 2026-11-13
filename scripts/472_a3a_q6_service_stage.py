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
COMPRESS_COMPAT = r'''/* SPDX-License-Identifier: GPL-2.0-only */
/* P472 A3a: Q6ASM-only compatibility with pinned TG 4.19 compressed ABI.
 * Do not alter GKI's global include/uapi/sound/compress_params.h.
 * Source: TG 6bf351bd include/uapi/sound/compress_params.h.
 */
#ifndef P472_A3A_Q6ASM_COMPRESS_COMPAT_H
#define P472_A3A_Q6ASM_COMPRESS_COMPAT_H

#include <linux/types.h>
#include <linux/build_bug.h>

/* Preserve TouchGrass codec IDs sent to the userspace event callback. */
#define SND_AUDIOCODEC_AC3    ((__u32) 0x00000015)
#define SND_AUDIOCODEC_DTS    ((__u32) 0x00000018)
#define SND_AUDIOCODEC_EAC3   ((__u32) 0x00000019)
#define SND_AUDIOCODEC_TRUEHD ((__u32) 0x00000024)

/* Preserve the 32-byte metadata prefix used for physical buffer mapping. */
#define COMPRESSED_TIMESTAMP_FLAG 0x0001
struct snd_codec_metadata {
    __u32 length;
    __u32 offset;
    __u64 timestamp;
    __u32 reserved[4];
};
static_assert(sizeof(struct snd_codec_metadata) == 32);

#endif
'''

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
#include <linux/kobject.h>
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

    # Stage pinned headers before adapting q6lsm.h below. A2a may already
    # have 5.10-adjusted headers; copy only missing files, never overwrite.
    for relative in ("include/dsp", "include/ipc", "include/uapi"):
        droot = donor / relative
        if not droot.is_dir():
            raise RuntimeError("P472 A3a donor header path unavailable "+relative)
        for path in sorted(droot.rglob("*.h")):
            target = dest / path.relative_to(donor)
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)

    # TG q6adm uses the real msm_audio_ion allocator and high-address
    # helper, but does not directly include their declaration header.
    # A2a already stages the real 5.10-adapted ION header/provider.
    # Add only the missing include, never a stub or alternate allocator.
    adm = dest / "dsp/q6adm.c"
    adm_source = adm.read_text()
    if "#include <dsp/msm_audio_ion.h>" in adm_source:
        raise RuntimeError("P472 A3a TG q6adm include provenance changed")
    adm.write_text(one(
        adm_source,
        "#include <dsp/audio_cal_utils.h>\\n".replace("\\n", "\n"),
        "#include <dsp/audio_cal_utils.h>\\n#include <dsp/msm_audio_ion.h>\\n".replace("\\n", "\n"),
        "real A2a msm_audio_ion prototypes for q6adm",
    ))
    # TG's q6asm debugfs latency timestamps use 4.19 timeval/timespec.
    # Linux 5.10 uses timespec64; retain the original sec/usec readout
    # using a private debugfs-only struct and a real monotonic timestamp.
    asm = dest / "dsp/q6asm.c"
    asm_source = asm.read_text()
    if asm_source.count("static struct timeval") != 6:
        raise RuntimeError("P472 A3a TG q6asm timeval sites changed")
    asm_source = one(
        asm_source, "#include <linux/time.h>\\n".replace("\\n", "\n"),
        "#include <linux/time.h>\\n#include <linux/ktime.h>\\n".replace("\\n", "\n"),
        "5.10 kernel monotonic time declarations",
    )
    asm_source = one(
        asm_source, "#define IN_BUFFER_SIZE 24\\n".replace("\\n", "\n"),
        ("#define IN_BUFFER_SIZE 24\\n"
         "/* Debugfs timestamps retain TG's seconds/microseconds output. */\\n"
         "struct p472_a3a_latency_timeval {\\n"
         "\\tlong tv_sec;\\n"
         "\\tlong tv_usec;\\n"
         "};\\n").replace("\\n", "\n").replace("\\t", "\t"),
        "private latency timestamp structure",
    )
    asm_source = asm_source.replace("static struct timeval",
                                    "static struct p472_a3a_latency_timeval")
    asm_source = one(
        asm_source,
        "struct timespec temp_tspec = ktime_to_timespec(kTimeNsec);",
        "struct timespec64 temp_tspec = ktime_to_timespec64(kTimeNsec);",
        "5.10 monotonic timespec64 conversion",
    )
    # GKI 5.10's generic sound/compress_params.h intentionally lacks
    # Qualcomm's extra codec IDs, timestamp flag and metadata prefix.
    # Keep these pinned TG definitions private to q6asm.c, not global UAPI.
    donor_compress = (tg / "include/uapi/sound/compress_params.h").read_text()
    for definition in (
        "#define SND_AUDIOCODEC_AC3                   ((__u32) 0x00000015)",
        "#define SND_AUDIOCODEC_DTS                   ((__u32) 0x00000018)",
        "#define SND_AUDIOCODEC_EAC3                  ((__u32) 0x00000019)",
        "#define SND_AUDIOCODEC_TRUEHD                ((__u32) 0x00000024)",
        "#define COMPRESSED_TIMESTAMP_FLAG 0x0001",
    ):
        if donor_compress.count(definition) != 1:
            raise RuntimeError("P472 A3a pinned TG compress ABI drift: " + definition)
    metadata = (
        "struct snd_codec_metadata {\n"
        "\t__u32 length;\n"
        "\t__u32 offset;\n"
        "\t__u64 timestamp;\n"
        "\t__u32 reserved[4];\n"
        "};"
    )
    if donor_compress.count(metadata) != 1:
        raise RuntimeError("P472 A3a pinned TG compressed metadata layout drift")
    asm_source = one(
        asm_source,
        "#include <sound/compress_params.h>\n",
        "#include <sound/compress_params.h>\n"
        "#include \"p472_a3a_q6asm_compress_compat.h\"\n",
        "Q6ASM private TouchGrass compressed ABI include",
    )
    # Pinned TG marks these three file-private Q6ASM helpers static but
    # also EXPORT_SYMBOLs them. 5.10 modpost rejects exporting static
    # functions. Keep the static definitions and in-file callers intact.
    # No exported external ABI is removed: static symbols cannot be linked
    # from another translation unit.
    for symbol in ("q6asm_memory_map_regions",
                   "q6asm_memory_unmap_regions",
                   "q6asm_enc_cfg_blk_pcm_v5"):
        declaration = "static int " + symbol + "("
        export = "EXPORT_SYMBOL(" + symbol + ");\n"
        if asm_source.count(declaration) < 1 or asm_source.count(export) != 1:
            raise RuntimeError("P472 A3a static Q6ASM symbol donor drift: " +
                               symbol)
        asm_source = asm_source.replace(export, "", 1)
    asm.write_text(asm_source)
    (dest / "dsp/p472_a3a_q6asm_compress_compat.h").write_text(COMPRESS_COMPAT)

    # A2a already adapted the pinned TG allocator to ACK's real 5.10
    # legacy ION provider. q6lsm.h only needs the correct public header.
    lsm_header = dest / "include/dsp/q6lsm.h"
    lsm_header.write_text(one(
        lsm_header.read_text(), "#include <linux/msm_ion.h>",
        "#include <linux/ion.h>", "LSM real ACK ION header",
    ))
    # TG q6voice.c includes the 4.19 private socinfo header even though
    # it calls none of that header's functions/macros. Do not copy a
    # misleading 4.19 SOCINFO API or provide a fake implementation.
    voice = dest / "dsp/q6voice.c"
    voice_source = voice.read_text()
    for symbol in ("socinfo_", "SOCINFO_", "of_board_is_",
                   "early_machine_is_", "machine_is_"):
        if symbol in voice_source.replace("#include <soc/qcom/socinfo.h>", ""):
            raise RuntimeError("P472 A3a voice requires real SOCINFO port: " + symbol)
    voice.write_text(one(
        voice_source, "#include <soc/qcom/socinfo.h>\n", "",
        "remove unused TG-only socinfo include",
    ))

    # q6voice.h uses the same genuine DMA-BUF/ION type definitions as
    # the already adapted A2a headers. No heap IDs or allocation API
    # is changed here.
    voice_header = dest / "include/dsp/q6voice.h"
    voice_header.write_text(one(
        voice_header.read_text(), "#include <linux/msm_ion.h>",
        "#include <linux/ion.h>", "voice real ACK ION header",
    ))

    # The real TG notifier implementation is built by CONFIG_P472_A3A_Q6.
    # TG's public header gates its extern declarations on an older
    # SND_SOC_MSM_QDSP6V2_INTF config, so without this selection it emits
    # -ENOSYS static-inline stubs which conflict with the real functions.
    # Keep both legacy selectors and add the actual 5.10 Kconfig owner.
    notify_header = dest / "include/dsp/msm-audio-event-notify.h"
    notify_source = notify_header.read_text()
    notify_source = one(
        notify_source, "IS_ENABLED(CONFIG_SND_SOC_MSM_QDSP6V2_INTF)",
        "IS_ENABLED(CONFIG_P472_A3A_Q6) || \\\n\t"
        "IS_ENABLED(CONFIG_SND_SOC_MSM_QDSP6V2_INTF)",
        "real notifier header declarations selected by A3a",
    )
    notify_header.write_text(notify_source)

    # Linux 5.10 renamed zero-before-free kzfree() to kfree_sensitive().
    # Preserve RTAC's wipe-before-release behavior at all 14 donor sites.
    rtac = dest / "dsp/rtac.c"
    rtac_source = rtac.read_text()
    if rtac_source.count("kzfree(") != 14 or "kfree_sensitive(" in rtac_source:
        raise RuntimeError("P472 A3a pinned TG RTAC free API drift")
    rtac.write_text(rtac_source.replace("kzfree(", "kfree_sensitive("))

    # TG avtimer uses removed 4.19 timespec/timekeeping APIs.
    # Convert its clock-offset calculation to the equivalent 5.10
    # timespec64 accessors without changing clock IDs or microsecond units.
    avtimer = dest / "dsp/avtimer.c"
    av_source = avtimer.read_text()
    for old, new, expected in (
        ("#include <linux/io.h>\n",
         "#include <linux/io.h>\n#include <linux/timekeeping.h>\n", 1),
        ("struct timespec ts;", "struct timespec64 ts;", 1),
        ("sizeof(struct timespec)", "sizeof(ts)", 1),
        ("getrawmonotonic(&ts);", "ktime_get_raw_ts64(&ts);", 1),
        ("get_monotonic_boottime(&ts);",
         "ktime_get_boottime_ts64(&ts);", 1),
        ("ktime_get_ts(&ts);", "ktime_get_ts64(&ts);", 1),
        ("ktime_get_real_ts(&ts);", "ktime_get_real_ts64(&ts);", 1),
        # On arm64, devm_ioremap() retains the device-register mapping
        # semantics of the removed 4.19 devm_ioremap_nocache().
        ("devm_ioremap_nocache(", "devm_ioremap(", 2),
    ):
        found = av_source.count(old)
        if found != expected:
            raise RuntimeError("P472 A3a avtimer donor API drift: " +
                               old + " count=" + str(found))
        av_source = av_source.replace(old, new)
    avtimer.write_text(av_source)
    for srcname in HELPERS:
        source = donor / "dsp" / srcname
        target = dest / "dsp" / srcname
        if not target.exists():
            shutil.copy2(source, target)
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
    # Preserve TG debugfs output units without restoring removed 4.19
    # kernel types, and require the actual ACK ION header for LSM.
    asm = (d / "dsp/q6asm.c").read_text()
    lsm_header = (d / "include/dsp/q6lsm.h").read_text()
    if asm.count("static struct p472_a3a_latency_timeval") != 6:
        raise RuntimeError("P472 A3a 5.10 debugfs timestamp adaptation missing")
    if ("struct timespec64 temp_tspec = ktime_to_timespec64(kTimeNsec);"
            not in asm or "#include <linux/ktime.h>" not in asm):
        raise RuntimeError("P472 A3a monotonic time 5.10 API missing")
    if ("static struct timeval" in asm or
            "ktime_to_timespec(kTimeNsec)" in asm):
        raise RuntimeError("P472 A3a legacy timespec API still used")
    if ("#include <linux/ion.h>" not in lsm_header or
            "#include <linux/msm_ion.h>" in lsm_header):
        raise RuntimeError("P472 A3a LSM must use real 5.10 ACK ION")
    voice = (d / "dsp/q6voice.c").read_text()
    voice_header = (d / "include/dsp/q6voice.h").read_text()
    if "#include <soc/qcom/socinfo.h>" in voice:
        raise RuntimeError("P472 A3a unused TG SOCINFO include remains")
    if ("#include <linux/ion.h>" not in voice_header or
            "#include <linux/msm_ion.h>" in voice_header):
        raise RuntimeError("P472 A3a voice must use real 5.10 ACK ION")
    notify_header = (d / "include/dsp/msm-audio-event-notify.h").read_text()
    if notify_header.count("IS_ENABLED(CONFIG_P472_A3A_Q6)") != 1:
        raise RuntimeError("P472 A3a real notifier Kconfig gate missing")
    if ("IS_ENABLED(CONFIG_SND_SOC_MSM_QDSP6V2_INTF)" not in notify_header or
            "IS_ENABLED(CONFIG_SND_SOC_MSM_QDSP6V2_VM)" not in notify_header):
        raise RuntimeError("P472 A3a TG notifier legacy alternatives lost")
    rtac = (d / "dsp/rtac.c").read_text()
    if ("kzfree(" in rtac or rtac.count("kfree_sensitive(") != 14):
        raise RuntimeError("P472 A3a RTAC must securely free all 14 TG buffers")
    # New A3a init includes q6core.h with its embedded kobject types.
    if "#include <linux/kobject.h>" not in init:
        raise RuntimeError("P472 A3a Q6 init missing 5.10 kobject types")
    avtimer = (d / "dsp/avtimer.c").read_text()
    for old in ("struct timespec ts;", "sizeof(struct timespec)",
                "getrawmonotonic(&ts);", "get_monotonic_boottime(&ts);",
                "ktime_get_ts(&ts);", "ktime_get_real_ts(&ts);",
                "devm_ioremap_nocache("):
        if old in avtimer:
            raise RuntimeError("P472 A3a legacy avtimer time/MMIO API " + old)
    for new in ("#include <linux/timekeeping.h>", "struct timespec64 ts;",
                "ktime_get_raw_ts64(&ts);",
                "ktime_get_boottime_ts64(&ts);",
                "ktime_get_ts64(&ts);", "ktime_get_real_ts64(&ts);",
                "sys_time = ts.tv_sec * 1000000LL + div64_u64(ts.tv_nsec, 1000);"):
        if new not in avtimer:
            raise RuntimeError("P472 A3a avtimer 5.10 offset semantics missing " + new)
    if avtimer.count("devm_ioremap(") != 2:
        raise RuntimeError("P472 A3a avtimer must map both real timer registers")
    # Missing in generic ACK 5.10, these TG ABI definitions are scoped
    # only to Q6ASM. Prove the old userspace buffer prefix remains 32 bytes.
    compat = (d / "dsp/p472_a3a_q6asm_compress_compat.h").read_text()
    if asm.count('#include "p472_a3a_q6asm_compress_compat.h"') != 1:
        raise RuntimeError("P472 A3a Q6ASM private compressed ABI include missing")
    # 5.10 modpost rejects static exports; keep all three helpers
    # file-local while removing only the invalid TG EXPORT_SYMBOL entries.
    for symbol in ("q6asm_memory_map_regions",
                   "q6asm_memory_unmap_regions",
                   "q6asm_enc_cfg_blk_pcm_v5"):
        if "static int " + symbol + "(" not in asm:
            raise RuntimeError("P472 A3a Q6ASM helper no longer static: " + symbol)
        if "EXPORT_SYMBOL(" + symbol + ");" in asm:
            raise RuntimeError("P472 A3a invalid Q6ASM static export: " + symbol)
    for item in ("SND_AUDIOCODEC_AC3", "SND_AUDIOCODEC_EAC3",
                 "SND_AUDIOCODEC_DTS", "SND_AUDIOCODEC_TRUEHD",
                 "COMPRESSED_TIMESTAMP_FLAG",
                 "struct snd_codec_metadata", "static_assert(sizeof(struct snd_codec_metadata) == 32)"):
        if item not in compat:
            raise RuntimeError("P472 A3a compressed ABI missing " + item)

    # q6adm must call the real, already-linked A2a ION implementation
    # using TG's exact header prototypes, not undeclared externs.
    adm = (d / "dsp/q6adm.c").read_text()
    ion_header = (d / "include/dsp/msm_audio_ion.h").read_text()
    if adm.count("#include <dsp/msm_audio_ion.h>") != 1:
        raise RuntimeError("P472 A3a q6adm must include real ION prototypes")
    for prototype in ("msm_audio_ion_alloc(", "msm_audio_ion_free(",
                      "msm_audio_populate_upper_32_bits("):
        if prototype not in ion_header or prototype not in adm:
            raise RuntimeError("P472 A3a missing real ION API " + prototype)
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
