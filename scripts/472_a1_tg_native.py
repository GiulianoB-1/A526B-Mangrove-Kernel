#!/usr/bin/env python3
"""P472 native TG APR trio port; q6core compile probe; NO ARM."""
import argparse, json, shutil
from pathlib import Path
MARK="P472_TG_APR_TRIO_NATIVE_A0B_V1"
REL=Path("drivers/soc/qcom/p472_tg_audio")
CFG="""
config P472_TG_APR
    bool "P472 TG native APRv2 dispatcher"
    depends on RPMSG && OF && !QCOM_APR && MSM_SUBSYSTEM_RESTART
    default n
    help
      Preserves TG APR API, remote-pid=2, A0b GET_STATE, deferred RX.

config P472_TG_Q6CORE
    bool "P472 TG q6core after calibration/ION native link"
    depends on P472_TG_APR
    default n
"""
MK={
"Makefile":"""# P472_TG_APR_TRIO_NATIVE_A0B_V1
subdir-ccflags-y += -I$(src)/include -I$(src)/include/uapi -I$(src)/dsp
obj-y += dsp/ soc/ ipc/
""",
"dsp/Makefile":"""ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include/uapi -I$(srctree)/drivers/soc/qcom/p472_tg_audio/dsp
obj-y += audio_ssr.o audio_notifier.o
# Kbuild extra-y compiles q6core.o but does NOT link it into built-in.a.
# Required for the native probe while P472_TG_Q6CORE remains disabled.
extra-y += q6core.o
obj-$(CONFIG_P472_TG_Q6CORE) += q6core.o
""",
"ipc/Makefile":"""ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include/uapi -I$(srctree)/drivers/soc/qcom/p472_tg_audio/dsp
obj-y += apr_v2.o apr_tal_rpmsg.o apr.o
""",
"soc/Makefile":"""ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include/uapi
obj-y += snd_event.o
"""}
def validate(root):
    d=root/REL
    apr=(d/"ipc/apr.c").read_text()
    tal=(d/"ipc/apr_tal_rpmsg.c").read_text()
    q6=(d/"dsp/q6core.c").read_text()
    api=(d/"include/ipc/apr.h").read_text()
    if not (d/"ipc/apr_v2.c").is_file():
        raise RuntimeError("apr_v2 missing")
    for x in ("apr_register(", "apr_send_pkt(", "apr_get_q6_state(",
              "apr_set_q6_state(", "struct apr_client_data"):
        if x not in api and x not in apr: raise RuntimeError("TG API missing "+x)
    for x in ("P472_A1_TG_APR_A0B_READY_GATE_V1",
              "P472 TG APR LOADED blocked=GET_STATE_PENDING",
              "p472_tg_apr_a0b_ready"):
        if x not in apr: raise RuntimeError("GET_STATE gate missing "+x)
    for x in ("remote_pid != 2", "P472_TG_APR_RX_MAX 8192",
              "P472_TG_APR_GET_STATE_RSP", "GFP_ATOMIC",
              "P472_TG_APR_RX_BOUND 256", "P472 TG APR_RX_DROP count=",
              "module_param_named(sync_rx_experimental",
              "P472 TG APR_SYNC_FALLBACK atomic_or_queued=1",
              "spin_lock_irqsave(&ch->r_lock",
              "srcu_read_lock(",
              "synchronize_srcu(", "queue_work(ctx->rx_wq"):
        if x not in tal: raise RuntimeError("TG transport missing "+x)
    if "DEFINE_STATIC_SRCU(p472_tg_rx_srcu);" not in tal or (
        "static DEFINE_SRCU(p472_tg_rx_srcu);" in tal):
        raise RuntimeError("P472 GKI 5.10 SRCU declaration must use DEFINE_STATIC_SRCU")
    rx=tal.split("static int apr_tal_rpmsg_callback(",1)[1].split(
        "\nstatic int apr_tal_rpmsg_probe(",1)[0]
    for x in ("down_read(", "down_write(", "mutex_lock(", "wait_event(",
              "msleep(", "synchronize_srcu("):
        if x in rx: raise RuntimeError("sleeping in RPMsg RX "+x)
    # Private A0/A1 RPMsg source must never coexist with TG's sole
    # apr_audio_svc binding owner in the staged target kernel tree.
    if (root/"drivers/rpmsg/p472_apr_q6core.c").exists():
        raise RuntimeError("P472 private APR RPMsg transport still staged")
    if tal.count('{ "apr_audio_svc" }') != 1:
        raise RuntimeError("P472 TG apr_audio_svc match table not unique")
    if "module_rpmsg_driver(p472_driver)" in tal:
        raise RuntimeError("P472 private RPMsg driver leaked into TG source")
    if "cal_utils_create_cal_types" not in q6 or "core_init(" not in q6:
        raise RuntimeError("TG q6core incomplete")
    if q6.count("u32 msm_audio_populate_upper_32_bits(dma_addr_t pa);") != 1:
        raise RuntimeError("P472 q6core must retain TG ION helper declaration only")
    if "u32 msm_audio_populate_upper_32_bits(dma_addr_t pa) {" in q6:
        raise RuntimeError("P472 q6core fake ION helper implementation forbidden")
    for rel in ("dsp/audio_ssr.h", "include/dsp/audio_notifier.h",
                "include/soc/snd_event.h"):
        if "CONFIG_P472_TG_APR" not in (d/rel).read_text():
            raise RuntimeError("P472 native TG audio provider not selected: " + rel)
    staged_notifier = (d/"dsp/audio_notifier.c").read_text()
    if '#include <soc/qcom/service-notifier.h>' in staged_notifier:
        raise RuntimeError("P472 TG disabled PDR header leaked into GKI")
    if staged_notifier.count("#ifndef CONFIG_MSM_QDSP6_PDR") != 1:
        raise RuntimeError("P472 PDR-only registration path not disabled")
    if staged_notifier.count("#ifdef CONFIG_MSM_QDSP6_PDR") < 3:
        raise RuntimeError("P472 PDR-only opcode guards incomplete")
    cal_header = (d/"include/dsp/audio_cal_utils.h").read_text()
    for required in ("#include <linux/dma-buf.h>",
                     "#include <linux/list.h>",
                     "#include <linux/mutex.h>",
                     "#include <linux/msm_audio_calibration.h>"):
        if required not in cal_header:
            raise RuntimeError("P472 q6core cal header required: " + required)
    for excluded in ("#include <linux/msm_ion.h>",
                     "#include <dsp/msm_audio_ion.h>"):
        if excluded in cal_header:
            raise RuntimeError("P472 q6core compile-only header pulls legacy ION: " + excluded)
    dsp_make = (d/"dsp/Makefile").read_text()
    if "audio_pdr.o" in dsp_make or "audio_ssr.o audio_notifier.o" not in dsp_make:
        raise RuntimeError("P472 PDR no-arm gate or real SSR provider missing")
    if dsp_make.count("extra-y += q6core.o") != 1:
        raise RuntimeError("P472 q6core object-only probe missing Kbuild extra-y")
    if "obj-y += q6core.o" in dsp_make:
        raise RuntimeError("P472 q6core must not link before calibration closure")
    if (root/"drivers/soc/qcom/Makefile").read_text().count(MARK)!=1:
        raise RuntimeError("Makefile ownership invalid")
    if (root/"drivers/soc/qcom/Kconfig").read_text().count("config P472_TG_APR")!=1:
        raise RuntimeError("Kconfig ownership invalid")
    return {"stage":"P472-TG-APR-TRIO","api":"TG unchanged",
        "packet_max":8192,"remote_pid":2,
        "ready":"A0b_GET_STATE_before_APR_SUBSYS_LOADED",
        "rx":"256 packet bounded deferred ordered workqueue SRCU, counted drops",
        "sync":"root-only experimental, default off, atomic/IRQ fallback",
        "audio_ssr":"real TG SSR implementation on P472 config",
        "audio_notifier":"real TG notifier implementation on P472 config",
        "snd_event":"real TG sound event implementation on P472 config",
        "audio_pdr":"off; PDR-only header and opcode paths guarded in staged copy",
        "q6core":"compile-only; calibration types retained; legacy ION transitive header excluded; not linked",
        "afe_asm_adm_msm_audio_ion":"not staged",
        "legacy_p472_private_api":"disabled in config",
        "no_arm":True,"flash_authorized":False}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--repo",type=Path,default=Path("."))
    p.add_argument("--report",type=Path)
    p.add_argument("--check-only",action="store_true")
    a=p.parse_args()
    if not a.check_only:
        source=a.repo/"vendor/p472/tg_apr"
        dest=a.root/REL
        if dest.exists() or not source.is_dir():
            raise RuntimeError("Target exists or source missing")
        for file in source.rglob("*"):
            if file.is_file() and "config" not in file.relative_to(source).parts:
                out=dest/file.relative_to(source)
                out.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(file,out)
        # GKI has no original TG audio Kconfig symbols. Bind these
        # internal provider guards to the one compiled P472 TG APR owner,
        # without changing the upstream TG public APR API or donor copies.
        for rel, old, new in (
            ("dsp/audio_ssr.h",
             "#ifdef CONFIG_MSM_QDSP6_SSR",
             "#ifdef CONFIG_P472_TG_APR"),
            ("include/dsp/audio_notifier.h",
             "#if IS_ENABLED(CONFIG_MSM_QDSP6_NOTIFIER)",
             "#if IS_ENABLED(CONFIG_P472_TG_APR)"),
            ("include/soc/snd_event.h",
             "#ifdef CONFIG_SND_EVENT",
             "#ifdef CONFIG_P472_TG_APR"),
        ):
            file = dest / rel
            body = file.read_text()
            if body.count(old) != 1:
                raise RuntimeError("P472 native TG provider guard changed: " + rel)
            file.write_text(body.replace(old, new))
        # This 5.10 stage intentionally excludes TG PDR. Its service-
        # notifier header belongs to the absent legacy PDR framework,
        # and audio_notifier.c uses no types/macros from that header.
        # Apply only to the staged copy, preserving the pinned donor.
        notifier = dest/"dsp/audio_notifier.c"
        content = notifier.read_text()
        legacy = "#include <soc/qcom/service-notifier.h>\\n".replace("\\n", "\n")
        if content.count(legacy) != 1:
            raise RuntimeError("P472 TG notifier PDR-only include differs")
        content = content.replace(legacy, "", 1)
        # SERVICE_STATE_* constants are defined by the removed QMI PDR
        # notifier header, not by SSR. Preserve the original TG code
        # only under CONFIG_MSM_QDSP6_PDR and fail closed otherwise.
        pdr_case = """\tcase AUDIO_NOTIFIER_PDR_SERVICE:
\t\thandle = audio_pdr_service_register("""
        if content.count(pdr_case) != 1:
            raise RuntimeError("P472 notifier PDR registration site changed")
        content = content.replace(
            pdr_case,
            """\tcase AUDIO_NOTIFIER_PDR_SERVICE:
#ifndef CONFIG_MSM_QDSP6_PDR
\t\treturn -EOPNOTSUPP;
#else
\t\thandle = audio_pdr_service_register(""",
            1,
        )
        pdr_end = """\t\telse
\t\t\tcurr_state = AUDIO_NOTIFIER_SERVICE_DOWN;
\t\tbreak;"""
        if content.count(pdr_end) != 1:
            raise RuntimeError("P472 notifier PDR registration end changed")
        content = content.replace(
            pdr_end, pdr_end.replace("\t\tbreak;", "#endif\n\t\tbreak;"), 1
        )
        for macro in (
            "SERVREG_NOTIF_SERVICE_STATE_DOWN_V01",
            "SERVREG_NOTIF_SERVICE_STATE_UP_V01",
        ):
            case = "\tcase " + macro + ":"
            if content.count(case) != 1:
                raise RuntimeError("P472 notifier PDR-only opcode changed: " + macro)
            content = content.replace(
                case, "#ifdef CONFIG_MSM_QDSP6_PDR\n" + case + "\n#endif", 1
            )
        notifier.write_text(content)
        # The q6core object-only probe needs calibration STRUCTURES, not
        # the 4.19 ION allocator implementation. Audio calibration uses
        # dma_buf pointers, a mutex and a list. Do not invent ION APIs.
        # When the actual cal_utils driver is linked, it must include
        # the separately ported msm_audio_ion interface directly.
        cal_header = dest/"include/dsp/audio_cal_utils.h"
        cal_text = cal_header.read_text()
        old_headers = ("#include <linux/msm_ion.h>\\n"
                       "#include <linux/msm_audio_calibration.h>\\n"
                       "#include <dsp/msm_audio_ion.h>\\n"
                       "#include <dsp/audio_calibration.h>\\n").replace("\\n", "\n")
        new_headers = ("#include <linux/dma-buf.h>\\n"
                       "#include <linux/list.h>\\n"
                       "#include <linux/mutex.h>\\n"
                       "#include <linux/msm_audio_calibration.h>\\n"
                       "#include <dsp/audio_calibration.h>\\n").replace("\\n", "\n")
        if cal_text.count(old_headers) != 1:
            raise RuntimeError("P472 TG calibration header include closure changed")
        cal_header.write_text(cal_text.replace(old_headers, new_headers, 1))
        # TG msm_audio_ion.h also declared this q6core dependency.
        # Keep the exact prototype for an object-only compile without
        # pulling in missing 4.19 ION internals or supplying a fake body.
        # This symbol MUST be resolved from a real allocator before link.
        ion_proto = "u32 msm_audio_populate_upper_32_bits(dma_addr_t pa);"
        donor_ion_header = source/"include/dsp/msm_audio_ion.h"
        if donor_ion_header.read_text().count(ion_proto) != 1:
            raise RuntimeError("P472 TG donor ION prototype changed")
        staged_core = dest/"dsp/q6core.c"
        core_src = staged_core.read_text()
        anchor = '#include "adsp_err.h"\\n'.replace("\\n", "\n")
        if core_src.count(anchor) != 1 or ion_proto in core_src:
            raise RuntimeError("P472 TG q6core prototype insertion site changed")
        core_src = core_src.replace(
            anchor, anchor + "\n/* Compile-only: implemented by real msm_audio_ion, not staged. */\n" + ion_proto + "\n", 1
        )
        staged_core.write_text(core_src)
        for path,content in MK.items(): (dest/path).write_text(content)
        k=a.root/"drivers/soc/qcom/Kconfig"
        m=a.root/"drivers/soc/qcom/Makefile"
        if "config P472_TG_APR" in k.read_text() or MARK in m.read_text():
            raise RuntimeError("Repeated config")
        k.write_text(k.read_text()+CFG)
        m.write_text(m.read_text()+"\n# "+MARK+"\nobj-$(CONFIG_P472_TG_APR) += p472_tg_audio/\n")
    result=validate(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P472 TG APR source contract PASS, q6core object probe only, NO ARM")
if __name__=="__main__": main()
