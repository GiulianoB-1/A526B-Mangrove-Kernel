# P476 H2-only (A2a-HLT + S2 read-only prerequisite + H2 manual OFF)

## Image provenance and exact flash file

- **Base:** hardware-proven A2a-HLT `23ca01ab33ed93c5c32c0ab2fba476d792641b69`.
- **Branch:** `agent/p476-h2-only-a2a-hlt-no-arm`. No A3 sound-card driver is built or registered.
- **Exact candidate image file (only from a green run):** `phase447b-variants/MANGROVE-P476-H2-1000MA-NO-ARM.boot.img`
- **Actions:** https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions?query=branch%3Aagent%2Fp476-h2-only-a2a-hlt-no-arm
- **Recovery image:** `phase447b-variants/MANGROVE-P472-A2A-HLT-Q6CORE-CAL-ION-NOHEAPS-NO-ARM.boot.img` from https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/43235805656
- Only the candidate HLT boot image must be shipped in the flash artifact; the NORMAL/nohlt comparison stays in internal inventory. Verify SHA256 of the **exact file** before any manual flash.

## Required build-time checks

- P474 `nohlt=0` and all command-line/boot-section identity checks PASS.
- `CONFIG_P472_TG_APR=y`, `CONFIG_P472_TG_Q6CORE=y`, `CONFIG_ION=y`, `CONFIG_ION_SYSTEM_HEAP=y`, `# CONFIG_DMABUF_HEAPS is not set`.
- P475 S2 and P476 H2 are separately gated in Kconfig; `CONFIG_P475_S2_CABLE=y`, `CONFIG_P476_H2=y`; **H2 sysfs remains 0 until deliberately armed**.
- `CONFIG_P472_A3_SOUND_CARD` must NOT be enabled; no A3 source audit, card registration, TAS256x, or amp energizing.
- No SELinux permissive, fake MUIC clients, charger OTP/FACTORY1/VBUSCNTL/BATREG writes, PDIC updates, EFS/RPMB/NV writes.
- Marker strings originate from linked real source: `P475 S2 CABLE type=`, `P476 H2 ON cur=1000 vbuscntl=`, `P476 H2 OFF reason=`. Presence in the binary is not proof the action happened.

## Hardware test sheet (requires deliberate flash authorization)

1. Flash only `MANGROVE-P476-H2-1000MA-NO-ARM.boot.img`, with the working A2a-HLT recovery image available.
2. At boot verify `P474 CMDLINE nohlt=0 cpu_idle_force_poll=0`, `P472 A2A TG Q6CORE_CAL_ION_LINKED real_ion=1 heaps=0`, TG `Q6 is Up`, and no APR timeout/drop.
3. At about 2 minutes test that Gboard opens, accepts every password character promptly, and unlocks. Type another sentence in a regular text field.
4. Count BT power cycles across the **first 10 minutes**, target **2 or fewer**. Confirm LTE/mobile data still works. Compare ~0.2 A idle current to A2a-HLT.
5. Keep `a52_h2_enable=0` for the initial boot and for PC USB cable testing. Verify S2 reports real type and that H0 still charges at no more than 500 mA if it is manually armed.
6. Plug in a PC cable, a wall charger, then a fast charger if available. Record the exact `P475 S2 CABLE type=...`, read-only `VBUSCNTL`, thermal status, and H0 state. Never use TYPE guessing to force charging.
7. **Only after explicit manual H2 authorization and H0 reporting CHARGING**, set `a52_h2_enable=1` using the exposed sysfs node. The controller must require S2 DCP AND VBUSCNTL exactly 0x44 (H0.1 maximum) AND float 4380 mV AND safe battery/charger thermistors, before its only permitted fast-current CHGCNTL2 write. Verify `P476 H2 ON cur=1000 vbuscntl=0x44 type=DCP`. On PC SDP/CDP or mismatch, no H2 ON may appear.
8. Check **battery >=39 C or charger NTC >=45 C** causes `P476 H2 OFF reason=...` and CHGCNTL2 readback **500 mA**. Do not artificially heat batteries or disable NTCs to force this test. Any read/write failure must drop to 500 mA or stop H0 charging if restoration cannot be verified.
9. Confirm H0.1 WDT kicks remain every 10 s, P449 rule remains in force, no FAULT_VERIFY, charging float still 4380 mV, no unauthorized register or calibration writes. Disarm H2 when finished.
10. Stop, recover to the exact A2a-HLT image, and do not merge if keyboard lags, BT cycles exceed target, data fails, cmdline poll=1, or H2 current fallback fails.

**Hardware status:** NOT YET TESTED. **NO ARM** and **NO AUTOMATIC FLASH**.
