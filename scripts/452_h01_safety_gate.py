#!/usr/bin/env python3
"""P452 H0.1 source safety gate: verify only intended 0x44/IO changes.

No manual arm, no charger register writes, no hardware actions.
"""
import argparse
import json
from pathlib import Path

SRC = Path("drivers/a52_447/a52_sm5714_fg_ro.c")

def check(root):
    s = (root / SRC).read_text()
    begin = s.index("/* A52_PHASE452_H0_MANUAL_SAFE_CHARGER_V1 */")
    end = s.index("static void a52g_poll(struct work_struct *work)", begin)
    h = s[begin:end]
    exact = (
        "#define A52H01_MAX_BOOTLOADER_VBUSCNTL 0x44",
        "input>A52H01_MAX_BOOTLOADER_VBUSCNTL",
        "P452 H0.1 VERIFY_FAIL rc=%d st1=%d st2=%d factory1=%d batreg=%d vbuscntl=%d id=%d cntl1=%d vcell=%d",
        "fg->a52h0_verify_io_streak++;",
        'a52h0_off(fg,"VERIFY_IO",',
        'a52h0_off(fg,"VERIFY_IO_3",true);',
        "fg->a52h0_verify_io_streak>=3",
        "a52h0_verify(fg,false,&vb,&mv,&st2,",
        "#define A52H0_CHG_FAST_500MA 0x20",
        "#define A52H0_FLOAT_4380_CODE 0x27",
        "#define A52H0_90S_WDT 0x04",
        "A52H0_MAX_TICKS (14400UL*HZ)",
        "A52H0_KICK_MIN_MS 10000",
        "if(for_enable && (ctrl&A52G_CHG_ENQ4FET))",
        "fg->a52h0_rearm=true;",
        "A52H0_CHGCNTL2,0xff,A52H0_CHG_FAST_500MA",
        "if ((reg!=A52H0_CHGCNTL2 && reg!=A52H0_WDTCNTL &&",
    )
    for a in exact:
        if a not in h:
            raise RuntimeError("P452 H0.1 missing safety contract " + a)
    # Only the original masked write callsite; no new register writer.
    if h.count("i2c_smbus_write_byte_data(") != 1:
        raise RuntimeError("P452 H0.1 charger write callsite count changed")
    for prohibited in ("a52h0_write_masked(fg,A52H0_VBUSCNTL",
                       "i2c_smbus_write_byte_data(fg->a52g_chg,A52H0_VBUSCNTL",
                       "a52h0_write_masked(fg,A52H0_FACTORY1"):
        if prohibited in h:
            raise RuntimeError("P452 H0.1 forbidden write: " + prohibited)
    if s.count("A52_PHASE452_H01_VBUS44_VERIFY_IO_V1") != 1:
        raise RuntimeError("P452 H0.1 marker duplication or missing")
    if "P463 CHG_GUARD SUSPEND_PREPARE" not in s:
        raise RuntimeError("P452 H0.1 lost original P463 PM safety gate")
    return {"phase": "P452-H0.1",
            "max_read_only_inherited_vbuscntl": "0x44",
            "h0_charge_current_ma": 500,
            "transient_verify_io_disarm": True,
            "persistent_io_latch_after_checks": 3,
            "all_verify_registers_logged_on_failure": True,
            "new_register_writes": 0,
            "auto_arm": False,
            "p449_p463_pm_guards_kept": True,
            "native_compilation": "PENDING",
            "hardware": "PENDING",
            "flash_authorized": False}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    data = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("P452 H0.1 SOURCE SAFETY GATE PASS; native compile/hardware unverified")

if __name__ == "__main__":
    main()
