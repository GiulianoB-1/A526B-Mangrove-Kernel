# P472 A2a-HLT hardware test: exact flash file and acceptance gate

**Disposition:** CI/review candidate only until build and safety checks pass. **Never flash NORMAL/nohlt.** Do not merge without hardware acceptance.

## Proven HLT baseline (recovery)

- Hardware-proven commit: `4baefab273f408dfbe18e97112d11d3b1a2f15af`
- Run: https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/42279174259
- Artifact: https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/42279174259/artifacts/13535699350
- **Exact baseline file to flash:** `phase447b-variants/MANGROVE-P474-HLT-NO-ARM.boot.img`
- Hardware: `P474 CMDLINE nohlt=0 cpu_idle_force_poll=0`, Q6 Up at 14.7 s, keyboard unlock immediate, battery ~0.2 A, BT restarts 1/715 s.

## A2a-HLT candidate

- Branch: `agent/p472-a2a-hlt-q6core-cal-ion-noheaps-no-arm`
- Base commit: `4baefab273f408dfbe18e97112d11d3b1a2f15af` (not rejected A2 or nohlt A2a).
- Audio source staging must be byte-identical to the A2a `scripts/472_a2a_q6core_existing_ion.py` blob `23e26f9bbef6584775008fed3fef905cc5f54d9a`.
- Actions for this branch: https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions?query=branch%3Aagent%2Fp472-a2a-hlt-q6core-cal-ion-noheaps-no-arm
- **Exact A2a-HLT file to flash (only after CI succeeds):** `phase447b-variants/MANGROVE-P472-A2A-HLT-Q6CORE-CAL-ION-NOHEAPS-NO-ARM.boot.img`.
- The intermediate NORMAL/nohlt image is **not** a test candidate and must **not** be uploaded as a flash image.
- Require artifact `P474-CMDLINE-PAIR.json` with `hlt_nohlt=0`, `normal_nohlt=1` and all byte invariants true.
- Require `CONFIG_P472_TG_Q6CORE=y`, `CONFIG_ION=y`, `CONFIG_ION_SYSTEM_HEAP=y`, `# CONFIG_DMABUF_HEAPS is not set`; no AFE/ASM/ADM. Archive exact candidate SHA256, config, System.map, and full Actions run/commit.

## Hardware acceptance, measured on the exact A2a-HLT file

1. Boot with a working HLT recovery image available. Collect boot-time kernel log: `P474 CMDLINE nohlt=0 cpu_idle_force_poll=0`. Any `nohlt=1` is a hard stop.
2. Confirm `apr_adsp_up: Q6 is Up`, TG APR `ADSP_READY state=1`, GET_STATE `permit_LOADED=1`, and `P472 A2A TG Q6CORE_CAL_ION_LINKED real_ion=1 heaps=0`. Record error/drop counts and timestamps.
3. At **about 2 minutes** after boot, while the phone is still locked, open Gboard and type the unlock password. Verify each key enters promptly, then unlock and type a sentence in another text box. Touch events arriving at the kernel alone do not qualify.
4. Record Bluetooth service restarts continuously over the **first 10 minutes**. **Target: 2 or fewer**. Compare to the good P474 HLT baseline (1 in 715 s) and rejected nohlt A2a (82 in 473 s). Preserve collector v1.29 Android logs covering actual typing.
5. Record idle battery current, modem/data status, and unexpected SSR/ION faults. Do not claim a root cause based solely on BT restart correlations.
6. **Stop and revert to P474 HLT** if keyboard lags or unlock fails, BT restart count worsens, polling is forced on, or modem/data regress. Do not merge.
7. **If keyboard still lags:** next isolation build must keep the same HLT baseline and all other A2a changes, but **omit `audio_calibration`**. Do not add DMA-BUF HEAPS in this bisect.

**Pass requires all gates, not just a successful kernel build.**
