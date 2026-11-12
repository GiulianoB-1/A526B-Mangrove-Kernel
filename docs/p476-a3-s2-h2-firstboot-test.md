# P476 A3 + S2 + H2, combined native build and hardware test sheet

**Status:** P476 source/preflight only until **real** A3 card is ported, all CI gates pass and the unique HLT image exists. Do not flash source-only or failed-run artifacts.

## Baseline and exact files

- Hardware-proven A2a-HLT branch: `agent/p472-a2a-hlt-q6core-cal-ion-noheaps-no-arm`; commit `23ca01ab33ed93c5c32c0ab2fba476d792641b69`.
- A2a-HLT action: https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/43235805656
- **Recovery image from hardware-proven A2a-HLT:** `phase447b-variants/MANGROVE-P472-A2A-HLT-Q6CORE-CAL-ION-NOHEAPS-NO-ARM.boot.img`, from the action's artifact.
- **P476 candidate filename, ONLY after native A3+S2+H2 pass CI:** `phase447b-variants/MANGROVE-P476-A3-SNDCARD-S2-CABLE-H2-NO-ARM.boot.img`.
- P476 must publish **one** `.boot.img` in its final artifact. The internal NORMAL intermediate must not be distributed.

## Boot and regression gate

1. Verify `P474 CMDLINE nohlt=0 cpu_idle_force_poll=0` from boot, `P472 A2A TG Q6CORE_CAL_ION_LINKED real_ion=1 heaps=0`, `apr_adsp_up: Q6 is Up`. Any `nohlt=1` or missing A2a markers fails.
2. At about **2 minutes**, open the lock-screen keyboard, enter the PIN/password normally, then unlock and type in another app. Collect Android logs with v1.29 covering actual keystrokes.
3. Bluetooth power cycles **at most 2 in the first 10 minutes**. Compare A2a-HLT hardware baseline of 1/477 s.
4. LTE mobile data, Wi-Fi, touch, thermal guard, H0/H0.1 charger WDT and P449 guard still work. No SELinux permissive.
5. No APR RX drop, APR timeout or new modem/BT SSR loops.

## Track A: A3 sound card (not speaker amp)

1. Real Q6 `q6afe/q6asm/q6adm/q6lsm` on existing TG APR, with logs `P472 A3 Q6 afe/asm/adm/lsm up` **only after genuine registration and readiness**.
2. Notifier SSR/PDR from real ADSP events or a clearly logged GET_STATE-proven fallback. Never generate fake `PDR_UP`.
3. Check LPASS clocks, LPI, CDC pinctrl, bolero RX/TX/VA, SoundWire, WCD938x/MBHC, and TG Kona native 5.10 DAI-link conversion.
4. `/proc/asound/cards` must report **`lito-lagoonmtp-snd-card`**. Compare the **33 expected PCMs** with TouchGrass. No WSA amp, speaker route, DAC energization or speaker test.
5. Check `/dev/msm_audio_cal` and `/dev/msm_rtac` only if real implementations are linked. **Never write calibration, /efs/tas25xx, ACDB, EFS, RPMB or modem NV.**

## Track B: S2 read-only cable classification

Check `P475 S2 CABLE` and read `a52_cable_type` for **PC/USB SDP**, **wall charger DCP**, and **fast AFC/QC** if available. Record actual `dt1` and any read error. No fake devices. The collector may classify `UNKNOWN` when hardware/PDIC does not expose a definitive cable type; never claim DCP by current alone. Check unchanged H0 watchdog.

## H2 (independently gated, manual only)

- Kernel Kconfig `P476_H2` **default n**; CI may explicitly build it for audit. Runtime `a52_h2_enable` **default 0**, mode 0600, and must remain 0 on ordinary first boot.
- The only possible fast-charge step is real H0 CHARGING, 4380mV float readback, intact WDT/guard, charger `VBUSCNTL=0x44` already set by bootloader, real S2 type `DCP`, battery **below 39°C**, charger NTC **below 45°C**, and explicit manual enable.
- Require log `P476 H2 ON cur=1000 vbuscntl=0x44 type=DCP` only after actual write and readback. Any mismatch requires `P476 H2 OFF reason=...` and a verified return to 500mA; a failed fallback must inhibit H0 charging.
- Never write VBUSCNTL, BATREG float, FACTORY1, OTP, bypass, PDIC firmware, charger calibration or protected storage.
- **Do not arm H2 during the initial boot/keyboard/BT regression test.** A separate, attended thermal and charging safety session is needed before anyone considers manual arming.

## Failure bisect

If the combined image regresses, the next reviewed build disables A3 first, leaving read-only S2 and runtime-disabled H2 intact. If H2's manual test fails, disable H2 and revert to the hardware-proven A2a-HLT image. Stop at any overtemperature, unexpected charger register or unstable power behavior.

## Donor and 5.10 API references

- TG 4.19 pin: `micr0softstore/samsung_android_kernel_a52xq@6bf351bdf18bdb228db79e66f14a7a9c0178e5d7`.
- TG `drivers/battery/charger/sm5714_charger/sm5714_charger.c:243-264,301-307`: CHGCNTL2 and VBUSCNTL current encoding; H2 uses the existing ACK 5.10 H0 write helper.
- TG `include/linux/mfd/sm/sm5714/sm5714-private.h:19,38`: MUIC address and device type register; S2 uses ACK 5.10 read-only `i2c_smbus_xfer`.
- TG `include/linux/muic/sm/sm5714/sm5714-muic.h:68-81`: SDP, CDP, DCP, AFC, QC bits.
- TG `techpack/audio/asoc/kona.c:8247-8311`: old direct DAI-link fields; ACK 5.10 `include/sound/soc.h:744-783,940-952` requires components and `SND_SOC_DAILINK_DEFS`.

**No hardware approval or merge is implied by CI success alone.**
