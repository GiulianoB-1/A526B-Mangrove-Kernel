# P477 A3b + H3 + MGBATT SHADOW1, HLT-only candidate

## Proven parent and hard rules

- Hardware-proven parent: `7eef0129f4c685aabdc815cca3024c7125ec241c`, `MANGROVE-P472-A3A-Q6-HLT-H2-NO-ARM.boot.img`.
- This build MUST produce just `MANGROVE-P477-A3B-H3-SHADOW1-NO-ARM.boot.img` in its primary flash artifact. The internal `nohlt=1` comparison must never be uploaded.
- Keep the tested parent boot available for recovery. No automated flash or runtime charging ARM.
- TG @ `6bf351bdf18bdb228db79e66f14a7a9c0178e5d7`; Samsung SM7325 5.4 API donor @ `c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4`.

## A. Boot gates (before charger current changes)

1. Verify `cat /proc/cmdline` does NOT include `nohlt` or `nohlt=1`.
2. Verify `dmesg | grep -E 'P474 CMDLINE|P472 A3a Q6|Q6 is Up'`; expect `P474 CMDLINE nohlt=0 cpu_idle_force_poll=0`, four A3a Q6 registrations `rc=0`, actual DSP versions `afe=9 asm=2 adm=4`, and Q6 Up.
3. At ~2 min, type on lock-screen keyboard and unlock. Over first 10 min, BT power cycles <=2. Test Cellcom LTE mobile data with a real page load.
4. Examine `dmesg` for panic, kernel oops, APR timeouts, H0/H2 FAULT, unexpected I2C/chg writes.

## B. A3b real probe and enumeration

```sh
su -c "dmesg | grep -E 'P472 A3b (PART|SWR)'"
su -c "dmesg | grep -E 'P472 A3a Q6|Q6 is Up'"
```

Expected for real existing OF devices: `P472 A3b PART <name> probe rc=<actual errno>` for LPASS clock voters, WCD/LPI pinctrl, Bolero, RX/TX/VA, SoundWire and WCD938x. `-517` means real probe deferral, **not success**. For each actual SoundWire master look for `P472 A3b SWR <master> slaves=<n> enumerated`, with counts from live hardware status. Acceptance requires WCD938x SoundWire slave detection, not a compiled-in string. No ALSA sound card or TAS256x amp expected.

## C. Charger manual H0/H2/H3, DCP wall charger ONLY

First identify the real sysfs path; all attrs should share an owner directory:
```sh
su -c 'find /sys/devices -name a52_h0_enable -o -name a52_h2_enable -o -name a52_h2_ma -o -name a52_cable_type'
```

In a root shell (`su`), set `D` to the actual directory printed for `a52_h0_enable`. **Do not use these commands on a PC USB cable, unknown cable type, or unverified battery/NTC.**
```sh
D=/sys/devices/REPLACE_WITH_ACTUAL_DEVICE_DIRECTORY
cat "$D/a52_cable_type"            # Must report DCP dt1=4
cat "$D/a52_h0_enable"              # armed=0 active=0 initially
echo 1 > "$D/a52_h0_enable"         # ARM H0 once, 500mA
cat "$D/a52_h0_enable"              # Wait for active=1, CHARGING
echo 1 > "$D/a52_h0_enable"         # Regression test: must keep CHARGING
echo 1000 > "$D/a52_h2_ma"           # H3 request, default 1000
echo 1 > "$D/a52_h2_enable"         # H2/H3 manual arm
cat "$D/a52_h2_enable"
sleep 75                            # Verify safe, stable, cool and 1000mA
echo 1500 > "$D/a52_h2_ma"           # Next step only after 60s dwell
sleep 75
echo 2100 > "$D/a52_h2_ma"           # Only if real temps stable and safe
sleep 75
echo 0 > "$D/a52_h2_enable"         # Restore verified 500mA
```

Expected observed lines, when the real gates permit (measure battery current independently):
```text
P452 H0 STATE from=... to=CHARGING reason=enable
P477 H3 SET ma=1000 code=0x40 vbuscntl=0x44 type=DCP bat=... chg=...
P477 H3 SET ma=1500 code=0x60 vbuscntl=0x44 type=DCP bat=... chg=...
P477 H3 SET ma=2100 code=0x86 vbuscntl=0x44 type=DCP bat=... chg=...
P477 H3 LIMIT ma=... reason=...       # Only when capped or refused
P476 H2 ARM_REFUSED state=... active=... armed=... killed=... latch=... # only on rejection
```

Stop the test immediately for hot battery/charger, unstable/unknown thermistors, faults, falling voltage, charger or WDT readback error, or inconsistent cable class. No artificial heating, no PD/AFC override. In hot/uncertain conditions controller must demote to 500mA or stop charging if verified 500mA restore fails. Explicit disarm after testing.

## D. MGBATT SHADOW stage 1-2

```sh
su -c "dmesg | grep 'MGBATT SHADOW'"
```

Expect exactly real, not fabricated, probe success `MGBATT SHADOW PROBE ok=1 shadow=1 owner=H0` once the live r02 DT parses. `MGBATT SHADOW WRITE_BASELINE shadow_hw_writes=0` should remain zero across transitions. Read-only MUIC class must give:

| Real connection | Expected shadow CABLE and WOULD_SET |
|---|---|
| PC USB (SDP) | `type=SDP pd_valid=0`; normal-temperature base `icl_ma=475 fcc_ma=550` |
| Wall charger (DCP) | `type=DCP pd_valid=0`; normal-temperature base `icl_ma=1800 fcc_ma=2100` |
| Unplugged | `type=NONE pd_valid=0`; `icl_ma=0 fcc_ma=0` |
| PD/AFC/QC/unknown | Never infer from MUIC; no elevated current decision and `pd_valid=0` |

The shadow computes observed TG base cable and basic temperature caps but does not claim to run all Samsung age/voter logic. No battery/usb/ac power_supply gets created in this stage, no I2C clients are duplicated, and no new hardware writes are permitted.

## E. Failure policy

Hardware regression: stop, restore the tested `7eef012` parent. For the next build disable `CONFIG_MGBATT_SHADOW` first, then A3b B3/B2/B1, while preserving charger A fixes. Do not publish success until full native link, exact HLT packaging and real on-device boot/charger/codec tests pass.
