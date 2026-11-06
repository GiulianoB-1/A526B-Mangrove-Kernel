# P472 A2a, first-boot review gate (NOT authorized to flash)

## Test P474 HLT before any audio test

- **P474 run:** https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/42279174259
- **P474 artifact:** https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/42279174259/artifacts/13535699350
- **Exact P474 HLT file to flash:** `phase447b-variants/MANGROVE-P474-HLT-NO-ARM.boot.img`
- **Expected boot log:** `P474 CMDLINE nohlt=0 cpu_idle_force_poll=0`
- Compare with NORMAL's `P474 CMDLINE nohlt=1 cpu_idle_force_poll=1`. Do not use an audio image for this A/B experiment.

## P472 A2a boot gate, only after review approval

- **Source baseline:** f3a4cbb8326a35a4b9c9f5ff9873b2f79a014b31, hardware-proven TG APR.
- **Branch:** `agent/p472-a2a-q6core-cal-existing-ion-no-heaps-no-arm`
- **Exact A2a candidate file (only if native build and source gates pass):**
  `phase447b-variants/MANGROVE-P472-A2A-Q6CORE-CAL-ION-NOHEAPS-NO-ARM.boot.img`
- A2a is **NOT** the rejected A2 `31b73e2c`. Reject any artifact with `DMABUF_HEAPS` enabled, wrong full commit, a missing `System.map`, or an absent real ION allocator.
- No AFE, ASM, ADM, TAS speaker or audio card activation is included. No automatic ARM.

## Acceptance checks on exact candidate

1. Before flashing, archive SHA256 of that **exact** `.boot.img` file, the `System.map`, and the `.config`. Verify `CONFIG_P472_TG_Q6CORE=y`, `CONFIG_ION=y`, `CONFIG_ION_SYSTEM_HEAP=y`, and `# CONFIG_DMABUF_HEAPS is not set`.
2. Keep a verified working boot image available for recovery.
3. After boot, check `dmesg` for `P472 A2A TG Q6CORE_CAL_ION_LINKED real_ion=1 heaps=0`, APR ADSP_READY/GET_STATE and absence of `APR_RX_DROP`, ION allocation errors, or SSR regressions.
4. **Critical:** interact with the lock screen, bring up Gboard, type the complete password, unlock the phone, then type in a normal text box. Log touchscreen dispatch and Android keyboard logs at the actual typing moment. Ten low-level taps alone are insufficient.
5. Record Bluetooth restart count and elapsed uptime; compare with the hardware-good A1 reference, 10 restarts over 358 seconds, and rejected A2, 62 restarts over 302 seconds. Do not assert an audio root cause without Android logs.
6. Stop and restore the known-good image if typing/unlock fails, BT restart rate significantly worsens, or a modem/data/audio regression appears. Do not merge or proceed to DMA-BUF HEAPS.

**Current disposition:** CI build/review only, no hardware flash authorization.
