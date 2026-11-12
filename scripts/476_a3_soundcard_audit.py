#!/usr/bin/env python3
"""P472 A3 native sound card source-closure gate. NO fake card/PCM/APR markers.

This checks required pinned TG 4.19 donor sources and the native 5.10 ASoC
API barrier. A3 is blocked until the actual Q6 + LPASS + macro + codec +
kona drivers are PORTED and linked. It does not synthesize success.
"""
import argparse
import json
import subprocess
from pathlib import Path

DONOR="6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
FILES=(
    "dsp/q6afe.c",
    "dsp/q6asm.c",
    "dsp/q6adm.c",
    "dsp/q6lsm.c",
    "dsp/audio_pdr.c",
    "dsp/audio_ssr.c",
    "asoc/kona.c",
    "asoc/codecs/bolero/bolero-cdc.c",
    "asoc/codecs/bolero/rx-macro.c",
    "asoc/codecs/bolero/tx-macro.c",
    "asoc/codecs/bolero/va-macro.c",
    "asoc/codecs/wcd938x/wcd938x.c",
    "asoc/codecs/wcd938x/wcd938x-mbhc.c",
    "soc/soundwire.c",
)
K=Path("drivers/soc/qcom/Kconfig")
GATE='''\nconfig P472_A3_SOUND_CARD
    bool "P472 A3 TG A52 Kona sound card, no speaker amplifier"
    depends on P472_TG_APR && P472_TG_Q6CORE && SND_SOC
    default n
    help
      Full Q6 AFE/ASM/ADM/LSM, LPASS macros, WCD938x and Kona card
      only after 5.10 API and live-DT closure. No dummy card/PCM.
'''
CARD="lito-lagoonmtp-snd-card"
Q6_MARK="P472 A3 Q6 afe/asm/adm/lsm up"

def pinned(tg):
    actual=subprocess.check_output(
        ["git","-C",str(tg),"rev-parse","HEAD"],text=True).strip()
    if actual != DONOR:
        raise RuntimeError("P472 A3 donor SHA mismatch: "+actual)

def read(root,p):return (root/p).read_text()

def stage(root):
    p=root/K
    s=p.read_text()
    if s.count("config P472_TG_APR")!=1 or s.count("config P472_TG_Q6CORE")!=1:
        raise RuntimeError("P472 A3 TG q6core/APR Kconfig pin drift")
    if "config P472_A3_SOUND_CARD" in s:
        raise RuntimeError("P472 A3 Kconfig already staged")
    p.write_text(s+GATE)

def check(root,tg,require_linked=False,system_map=None,image=None):
    pinned(tg)
    audio=tg/"techpack/audio"
    missing=[p for p in FILES if not (audio/p).is_file()]
    if missing:raise RuntimeError("P472 A3 pinned sources missing: "+",".join(missing))
    kona=read(audio,"asoc/kona.c")
    if "snd_soc_register_card" not in kona and "devm_snd_soc_register_card" not in kona:
        raise RuntimeError("P472 A3 donor lacks genuine ASoC card registration")
    if "msm_kona_dai_links" not in kona:
        raise RuntimeError("P472 A3 TG Kona link topology missing")
    # TG techpack/audio/asoc/kona.c:8247-8311 uses deprecated
    # .cpu_dai_name/.codec_name/.platform_name members on 4.19.
    if "dai_link[i].cpu_dai_name" not in kona or "dai_link[i].codec_name" not in kona:
        raise RuntimeError("P472 A3 4.19 ABI observation drift")
    soc=read(root,"include/sound/soc.h")
    # ACK common 5.10 include/sound/soc.h:744-783 and 940-952
    # requires component arrays; old direct members are no longer present.
    for k in ("struct snd_soc_dai_link_component","SND_SOC_DAILINK_DEFS",
              "struct snd_soc_dai_link {"):
        if k not in soc:
            raise RuntimeError("P472 A3 5.10 ASoC contract changed: "+k)
    kconfig=read(root,K)
    if kconfig.count("config P472_A3_SOUND_CARD")!=1:
        raise RuntimeError("P472 A3 Kconfig must be independently gated")
    if "default n" not in kconfig.split("config P472_A3_SOUND_CARD")[1]:
        raise RuntimeError("P472 A3 gate default must be n")
    generated=root/"drivers/soc/qcom/p472_tg_audio"
    symbols=[]
    if system_map and system_map.is_file():
        symbols=system_map.read_text().splitlines()
    linked_q6=all(any(line.endswith(" "+sym) for line in symbols)
                  for sym in ("afe_init","asm_init","adm_init","lsm_init"))
    staged_kona=(generated/"asoc/kona.c").is_file()
    staged_card=staged_kona and CARD in read(generated,"asoc/kona.c")
    linked_marker=bool(image and image.is_file() and
                       Q6_MARK.encode() in image.read_bytes())
    checks={
        "tg_sha_pinned":True,
        "donor_audio_files_present":True,
        "ack_5_10_dailink_component_api_verified":True,
        "TG_4_19_to_5_10_dai_link_conversion_required":True,
        "actual_kona_source_ported":staged_card,
        "q6afe_asm_adm_lsm_native_symbols":linked_q6,
        "real_q6_service_marker_linked":linked_marker,
    }
    result={"phase":"P472-A3-SOUNDCARD",
       "status":"NATIVE_LINK_PASS" if (staged_card and linked_q6 and linked_marker)
                 else "BLOCKED_FULL_ASOC_PORT",
       "donor_sha":DONOR,"card":CARD,"expected_pcm_count":33,
       "markers":Q6_MARK,"checks":checks,
       "source_4_19_compat":["techpack/audio/asoc/kona.c:8247-8311 direct dai_link names",
           "techpack/audio/dsp/q6afe.c:1-60 donor APR includes",
           "techpack/audio/dsp/audio_pdr.c:1-60 donor PDR dependency"],
       "source_5_10_compat":["include/sound/soc.h:744-783 component link arrays",
           "include/sound/soc.h:940-952 SND_SOC_DAILINK_DEFS"],
       "no_speaker_amp":True,"no_arm":True,
       "no_fake_card":True}
    if require_linked and result["status"]!="NATIVE_LINK_PASS":
        raise RuntimeError(
            "P472 A3 genuinely ported sound card not linked: "
            "TG 4.19 Kona 9551-line DAI component conversion, "
            "bolero/SDW/WCD938x/LPASS and Q6 services outstanding. "
            "Fail closed: NO P476 flash image.")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--tg",type=Path,required=True)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--require-linked",action="store_true")
    p.add_argument("--system-map",type=Path)
    p.add_argument("--image",type=Path)
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    if not a.check_only:stage(a.root)
    result=check(a.root,a.tg,require_linked=a.require_linked,
                 system_map=a.system_map,image=a.image)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P472 A3 source audit "+result["status"]+
          "; sound card not invented, no flash unless real native link")

if __name__=="__main__":
    main()
