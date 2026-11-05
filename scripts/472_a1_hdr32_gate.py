#!/usr/bin/env python3
"""P472 A1 gate 0: strict TG APR variable-header ABI preflight.

Source-only. The full A1 sound card, mixers, audio ION and calibration
passthrough are deliberately NOT staged or claimed by this gate.
"""
import argparse
import json
from pathlib import Path

REL = Path("drivers/rpmsg/p472_apr_q6core.c")
TG_APR = Path("techpack/audio/ipc/apr.c")
TG_CORE = Path("techpack/audio/dsp/q6core.c")
TG_CARD = Path("techpack/audio/asoc/kona.c")
MARK = "P472_A1_APR_VARIABLE_HEADER_V1"

def hdr_bytes(field):
    return ((field >> 4) & 0x0f) * 4

def selftest():
    assert hdr_bytes(0x250) == 20
    assert hdr_bytes(0x280) == 32
    assert hdr_bytes(0x200) == 0
    assert hdr_bytes(0x2f0) == 60
    print("P472 A1 TG APR hdr_field dwords tests PASS")

def gate(root, tg):
    p = root / REL
    if not p.is_file():
        raise RuntimeError("P472 A1 gated native APR driver absent")
    s = p.read_text()
    for v in (
        MARK,
        "P472 A1 APR_HDR_INVALID",
        "P472 A1 APR_HDR hdr_field=",
        "hdr_size = ((hdr_field >> 4) & 0x0f) * 4;",
        "payload = (const u8 *)data + hdr_size;",
        "words = (const __le32 *)payload;",
        "v = (const struct p472_fw_ver *)payload;",
        "expected = hdr_size + sizeof(*v) +",
        "len < hdr_size + sizeof(*v)",
        "len < hdr_size + sizeof(__le32)",
        "len != hdr_size + 2 * sizeof(__le32)",
        "P472 A0b ADSP_READY",
        "P472 A0b APR_SEND",
        "remote_pid != 2",
        "P472_RX_RAW_MAX_PACKETS        32",
    ):
        if v not in s:
            raise RuntimeError("P472 A1 APR parity anchor missing: " + v)
    if "(h + 1)" in s or "expected = sizeof(*h)" in s:
        raise RuntimeError("P472 A1 fixed 20-byte response payload survives")
    t = (tg / TG_APR).read_text()
    if "((hdr_size & 0x00F0) >> 0x4) * 4" not in t:
        raise RuntimeError("P472 A1 pinned TG dynamic-header decode changed")
    if not (tg / TG_CORE).is_file() or not (tg / TG_CARD).is_file():
        raise RuntimeError("P472 A1 pinned TG core or machine donor missing")
    kconfig = (root / "drivers/rpmsg/Kconfig").read_text()
    if "depends on RPMSG && OF && !QCOM_APR" not in kconfig:
        raise RuntimeError("P472 A1 upstream APR duplicate provider veto missing")
    return {
        "phase": "P472-A1-GATE0",
        "status": "SOURCE_ONLY",
        "dynamic_hdr_bytes_supported": [20, 32],
        "tg_apr_reference": str(TG_APR),
        "native_source": str(REL),
        "dispatched_services": ["CORE diagnostic only"],
        "audio_notifier_ssr": "NOT_STAGED",
        "ion_sid_0x1001": "NOT_STAGED",
        "bolero_soundwire_wcd938x": "NOT_STAGED",
        "machine_card_lito_lagoonmtp": "NOT_STAGED",
        "card_pcm_count": "UNVERIFIED",
        "card_compress_count": "UNVERIFIED",
        "card_hwdep_count": "UNVERIFIED",
        "calibration_pass_through": "NOT_STAGED",
        "p471_bt_unchanged": True,
        "no_arm": True,
        "flash_authorized": False,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--tg", required=True, type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args()
    selftest()
    rec = gate(a.root, a.tg)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    print("P472 A1 GATE0 TG variable APR header SOURCE PASS; full sound card NOT STAGED")

if __name__ == "__main__":
    main()
