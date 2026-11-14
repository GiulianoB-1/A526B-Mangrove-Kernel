#!/usr/bin/env python3
"""P478 A3c read-only TG Kona machine/ASoC provider readiness inventory.

A real A52 card cannot be claimed until all TG FE/BE PCM, compress and
DAI providers are native 5.10 built-ins. No stub device creation, no
fake ALSA PCM count, no TAS256x or voice path in this phase.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

TG = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
D54 = "c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4"
R02 = "arch/arm64/boot/dts/samsung/a52/a52xq/a52xq_eur_open_w00_r02.dts"
ROOT = Path("drivers/soc/qcom/p472_tg_audio/a3b")
PROVIDERS = {
    "msm-pcm-dsp.0": "msm-pcm-q6-v2.c",
    "msm-pcm-dsp.1": "msm-pcm-q6-v2.c",
    "msm-pcm-dsp.2": "msm-pcm-q6-v2.c",
    "msm-compress-dsp": "msm-compress-q6-v2.c",
    "msm-pcm-hostless": "msm-pcm-hostless.c",
    "msm-pcm-afe": "msm-pcm-afe-v2.c",
    "msm-pcm-routing": "msm-pcm-routing-v2.c",
    "msm-pcm-dsp-noirq": "msm-pcm-q6-noirq.c",
    "msm-compr-dsp": "msm-compress-q6-v2.c",
}
GOAL_COMPRESS = ("comprC0D7", "comprC0D11", "comprC0D25",
                 "comprC0D26", "comprC0D27", "comprC0D28", "comprC0D37")

def pin(path, sha, name):
    got = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"],
                                  text=True).strip()
    if got != sha:
        raise RuntimeError("P478 A3c %s SHA drift: %s" % (name, got))

def inspect(root, tg, d54):
    pin(tg, TG, "TouchGrass")
    pin(d54, D54, "SM7325")
    t = (tg / "techpack/audio/asoc/kona.c").read_text()
    d = (d54 / "techpack/audio/asoc/kona.c").read_text()
    d_links = (d54 / "techpack/audio/asoc/msm_dailink.h").read_text()
    dt = (tg / R02).read_text()
    for token in ("static struct snd_soc_dai_link msm_common_dai_links[]",
                  "devm_snd_soc_register_card(&pdev->dev, card);",
                  'snd_soc_of_parse_card_name(card, "qcom,model");'):
        if token not in t:
            raise RuntimeError("P478 TG Kona machine ABI drift: "+token)
    for token in ("struct snd_soc_dai_link_component",
                  "devm_snd_soc_register_card(&pdev->dev, card);",
                  '#include "msm_dailink.h"'):
        if token not in d:
            raise RuntimeError("P478 SM7325 Kona 5.4 API pattern drift: "+token)
    if "SND_SOC_DAILINK_DEFS(" not in d_links:
        raise RuntimeError("P478 5.4 real component-array FE/BE link definitions missing")
    model = re.findall(r'\bqcom,model\s*=\s*"([^"]+)"', dt)
    if model.count("lito-lagoonmtp-snd-card") != 1:
        raise RuntimeError("P478 r02 A52 sound card name drift: "+repr(model))
    platform_match = re.search(
        r'\basoc-platform-names\s*=\s*(.*?);',dt,re.S)
    if not platform_match:
        raise RuntimeError("P478 r02 asoc-platform-names missing")
    platforms = re.findall(r'"([^"]+)"',platform_match.group(1))
    source = (root / ROOT)
    observed = []
    for platform, filename in sorted(PROVIDERS.items()):
        # Neither a Q6 DSP service nor a codec by itself creates an
        # ASoC platform driver with these FE/BE names.
        active = list(source.rglob(filename))
        observed.append({"platform":platform,"TG_source":filename,
                         "staged_in_A3b":bool(active),
                         "staged_paths":[str(p.relative_to(source)) for p in active]})
    absent = [x for x in observed if not x["staged_in_A3b"]]
    if not absent:
        raise RuntimeError("P478 FE provider inventory changed; review readiness gate")
    a52_nodes = {
        "card_name": "lito-lagoonmtp-snd-card",
        "requested_pcm_count": 33,
        "requested_compress_nodes": list(GOAL_COMPRESS),
    }
    # Source provenance is not an enumeration of ALSA devices.
    return {
        "phase":"P478_A3C_TG_KONA_TOPOLOGY_PREFLIGHT",
        "tg":TG,"d54":D54,"r02":R02,
        "TG_kona_lines":len(t.splitlines()),
        "SM7325_kona_lines":len(d.splitlines()),
        "A52_r02_card":a52_nodes,
        "r02_platform_names":platforms,
        "audio_FE_provider_inventory":observed,
        "missing_A3c_providers":absent,
        "audio_card_registered":False,
        "pcm_count_verified":False,
        "compress_nodes_verified":False,
        "DT_property_gate_ready":False,
        "a3c_native_link_ready":False,
        "reason":"TG Kona depends on unported FE/BE PCM/compress/DAI providers and A52 link array conversions; no fake/stub card",
        "no_tas256x":True,
        "no_voice_audio":True,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True,type=Path)
    ap.add_argument("--tg",required=True,type=Path)
    ap.add_argument("--d54",required=True,type=Path)
    ap.add_argument("--report",required=True,type=Path)
    a=ap.parse_args()
    result=inspect(a.root,a.tg,a.d54)
    a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P478 A3c PRE-FLIGHT: native machine blocked by %d FE platform dependencies; no ALSA card claimed" %
          len(result["missing_A3c_providers"]))
if __name__=="__main__":main()
