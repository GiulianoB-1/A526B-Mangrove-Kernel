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
obj-y += audio_ssr.o audio_pdr.o audio_notifier.o
obj-$(CONFIG_P472_TG_Q6CORE) += q6core.o
""",
"ipc/Makefile":"""ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include/uapi -I$(srctree)/drivers/soc/qcom/p472_tg_audio/dsp
obj-y += apr_v2.o apr_tal_rpmsg.o apr.o
""",
"soc/Makefile":"obj-y += snd_event.o\n"}
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
              "P472_TG_APR_RX_BOUND", "srcu_read_lock(",
              "synchronize_srcu(", "queue_work(ctx->rx_wq"):
        if x not in tal: raise RuntimeError("TG transport missing "+x)
    rx=tal.split("static int apr_tal_rpmsg_callback(",1)[1].split(
        "\nstatic int apr_tal_rpmsg_probe(",1)[0]
    for x in ("down_read(", "down_write(", "mutex_lock(", "wait_event(",
              "msleep(", "synchronize_srcu("):
        if x in rx: raise RuntimeError("sleeping in RPMsg RX "+x)
    if "cal_utils_create_cal_types" not in q6 or "core_init(" not in q6:
        raise RuntimeError("TG q6core incomplete")
    if (root/"drivers/soc/qcom/Makefile").read_text().count(MARK)!=1:
        raise RuntimeError("Makefile ownership invalid")
    if (root/"drivers/soc/qcom/Kconfig").read_text().count("config P472_TG_APR")!=1:
        raise RuntimeError("Kconfig ownership invalid")
    return {"stage":"P472-TG-APR-TRIO","api":"TG unchanged",
        "packet_max":8192,"remote_pid":2,
        "ready":"A0b_GET_STATE_before_APR_SUBSYS_LOADED",
        "rx":"bounded deferred workqueue SRCU",
        "q6core":"object-only; not linked",
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
