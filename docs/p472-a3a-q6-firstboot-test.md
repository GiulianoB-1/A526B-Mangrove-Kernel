# P472 A3a Q6-service hardware test sheet (conditional CI pass)

**Stage:** A3a only. Parent: P476 H2-only (`agent/p476-h2-only-a2a-hlt-no-arm`). A3b codecs, A3c machine card and TAS256x speaker amplifier remain OUT.

- **Exact proposed A3a HLT flash filename:** `phase447b-variants/MANGROVE-P472-A3A-Q6-HLT-H2-NO-ARM.boot.img`
- **A3a branch:** `agent/p472-a3a-q6-services-from-p476-h2-hlt-no-arm`
- **Actions:** https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions?query=branch%3Aagent%2Fp472-a3a-q6-services-from-p476-h2-hlt-no-arm
- **Test only after P476 H2-only has passed the boot/keyboard/BT/mobile-data hardware gate.** Green CI is never sufficient for hardware approval.
- **Recovery:** verified `MANGROVE-P472-A2A-HLT-Q6CORE-CAL-ION-NOHEAPS-NO-ARM.boot.img` from run https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/43235805656; preferably preserve the eventually verified H2 parent image too.

## Before flashing

1. Verify the complete Actions run SHA and this **exact** A3a file SHA256. Require `CONFIG_P472_A3A_Q6=y`, `CONFIG_P472_TG_APR=y`, `CONFIG_P472_TG_Q6CORE=y`, `CONFIG_ION=y`, `# CONFIG_DMABUF_HEAPS is not set`, `# CONFIG_P472_A3_SOUND_CARD is not set`.
2. Require native kernel linking of the actual TG `afe_init`, `q6asm_init`, `adm_init`, `q6lsm_init`, `q6common`, `q6audio`, and real APR symbols. No dummy endpoints or version responses.
3. P474 boot-pair report must prove `nohlt=0`, with identical Image/DTB/ramdisk outside cmdline and exactly one HLT boot file in the artifact.
4. No automatic ARM of H2, no changes to P449/H0/H0.1, P471, Thermal Guard, B3 Bluetooth or SELinux. No ASoC machine driver, WCD938x, speaker amp or calibration/NV writes.

## Hardware acceptance

1. Boot: `P474 CMDLINE nohlt=0 cpu_idle_force_poll=0`, existing `P472 A2A TG Q6CORE_CAL_ION_LINKED real_ion=1 heaps=0`, existing `apr_adsp_up: Q6 is Up`, no APR_RX_DROP/APR_TIMEOUT.
2. Verify four *actual* service-return markers: `P472 A3a Q6 adm registered rc=0`, `P472 A3a Q6 afe registered rc=0`, `P472 A3a Q6 asm registered rc=0`, `P472 A3a Q6 lsm registered rc=0`.
3. Confirm an **ADSP response**, not a compiled string, `P472 A3a Q6 ADSP_VERSION_REPLY afe=9 asm=2 adm=4`. Any negative/unsupported version or `VERSION_FAIL` is NOT a pass.
4. Lock-screen keyboard must open and accept input immediately at ~2 minutes after boot. Enter the unlock password, then type into a second app. Capture Android collector v1.29 logs at the typing time.
5. BT power cycles in first 10 minutes must be **<=2**; mobile data/LTE still works; idle current should stay consistent with HLT ~0.2 A (measurement context recorded).
6. Test S2 read-only cable classification and H0 charger state, keeping `a52_h2_enable=0` unless separately manually approved. No new audio card is expected at A3a; `/proc/asound/cards` must not be falsely claimed.
7. Any keyboard/BT/data regression or missing versions: revert to hardware-tested parent, do not proceed to A3b.

**Current disposition:** Stage audit and native link are pending. NO ARM. No automatic flash.
