#!/usr/bin/env python3
"""P472 A1 pinned TG donor inventory and independently gated scope report.

This is source evidence only. No donor is copied into the live kernel until
its native 5.10 interfaces, duplicate providers, DT ownership and ABI pass.
"""
import argparse
import json
from pathlib import Path

ROOT = Path("techpack/audio")
FAMILIES = {
    "apr_dispatcher": ["ipc/apr.c"],
    "q6core": ["dsp/q6core.c"],
    "q6afe": ["dsp/q6afe.c"],
    "q6asm": ["dsp/q6asm.c"],
    "q6adm": ["dsp/q6adm.c"],
    "q6lsm": ["dsp/q6lsm.c"],
    "msm_audio_ion": ["dsp/msm_audio_ion.c"],
    "audio_notifier": ["*audio_notifier*.c"],
    "lpass_clocks_pinctrl": ["*lpass*.c", "*lpass*.h"],
    "bolero_rx_tx_va": ["*bolero*.c"],
    "soundwire": ["*swr*.c", "*soundwire*.c"],
    "wcd938x_mbhc": ["*wcd938*.c", "*mbhc*.c"],
    "kona_asoc": ["asoc/kona.c"],
    "audio_cal": ["*audio_cal*.c"],
    "msm_rtac": ["*rtac*.c"],
}
RUNTIME_ABI = {
    "card": "lito-lagoonmtp-snd-card",
    "pcm_count": 33,
    "compress_count": 7,
    "hwdep_count": 54,
    "mixer_controls": "batch 9 exact-name comparison required",
}
DISABLED = ["tas256x_speaker", "wsa", "wcd937x", "fsa4480",
            "calibration_writes", "automatic_charger_arm"]

def audit(tg):
    root = tg / ROOT
    if not root.is_dir():
        raise RuntimeError("P472 A1 pinned TG audio donor directory missing")
    families = {}
    for name, patterns in FAMILIES.items():
        hits = []
        for pattern in patterns:
            if "*" in pattern:
                hits.extend(p.relative_to(root).as_posix()
                            for p in root.rglob(pattern) if p.is_file())
            else:
                p = root / pattern
                if p.is_file():
                    hits.append(pattern)
        hits = sorted(set(hits))
        families[name] = {
            "present": bool(hits),
            "sources": hits[:40],
            "native_510_port": "NOT_STAGED",
            "compiled_gate": "PENDING",
            "runtime_gate": "PENDING",
        }
    for required in ("apr_dispatcher", "q6core", "q6afe", "q6asm",
                     "q6adm", "q6lsm", "msm_audio_ion", "kona_asoc"):
        if not families[required]["present"]:
            raise RuntimeError("P472 A1 pinned TG donor missing " + required)
    return {
        "phase": "P472-A1",
        "mode": "TG_DONOR_PROVENANCE_ONLY",
        "tg_audio_root": str(ROOT),
        "families": families,
        "runtime_abi_target_only_not_observed": RUNTIME_ABI,
        "intentionally_disabled": DISABLED,
        "ready_to_flash": False,
        "sound_card_registered": False,
        "audio_calibration_writes": False,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tg", required=True, type=Path)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    record = audit(a.tg)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print("P472 A1 TG donor inventory PASS; 5.10 ASoC/ION/audio port NOT_STAGED")
    for name, data in record["families"].items():
        print("P472 A1 DONOR %s present=%d staged=0" % (name, data["present"]))

if __name__ == "__main__":
    main()
