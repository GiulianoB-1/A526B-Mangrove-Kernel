# P470-A2: first hardware-capable IPA build (IN PROGRESS, NO FLASH)

Base: P470-A1 #628 @ 4fcf2e3, P469b G modem recovery unchanged.
Current A2 branch is **preflight only**. Nothing on this branch is a
flashable IPA image until all gates below pass. Never present a
no-IPA P469b artifact as an A2 IPA image.

## Order and ownership

1. Lock ABI: vendor/p470/ipa_fmwk.c is a byte-for-byte copy of
   CodeLinaro-mirror/la_kernel_msm-5.10 @
   f438c918a464b82d4a637b5327dd1ed6e8b625dc,
   drivers/platform/msm/ipa_fmwk/ipa_fmwk.c.
   Dataipa remains pinned @ c560cc3c2840fb0ebc55ceef5b27549c66143637.
   The private A1 external-module build and A2 full module build use the
   vendored real provider, no fabricated exports.
2. A2 **un-stubbed ABI**: fresh rebuild after the Image link, **without**
   -DP470_A0_COMPILE_ONLY. The P470-A0 compatibility transformer retains
   original SCM and IOMMU code in the !P470_A0_COMPILE_ONLY branch;
   the A2 gate compiles it and fails closed on nonexistent vendor APIs.
   No warning downgrades and no KBUILD_EXTRA_SYMBOLS.
3. **SMMU first**, not mem_protect_region: map Lagoon AP/WLAN/uC
   SIDs 0x440/0x441/0x442. Implement genuine S1_BYPASS and FAST/fastmap
   semantics with verified DT context bank and extra fixed mappings
   0x146a8000/0x2000 (AP) and 0x1ea0000/0x80000 (WLAN).
   Do not replace fastmap by an ordinary unmanaged domain or blanket
   identity mappings. Protect Phase206 system-suspend veto.
4. **Single PAS15 owner**: the legacy PIL subsystem
   soc:qcom,ipa_fws, firmware lagoon_ipa_fws, reserved
   0x8b700000+0x10000 and GSI 0x8b710000+0x5400.
   The IPA driver calls subsystem_get("ipa_fws") and defers or stops
   cleanly if the provider is not ready. Only one loader may call
   SCM PAS auth/reset for PAS id 0xf.
5. **DT + power**: exact TG IPA 4.7 MMIO 0x1e00000+0x84000,
   GSI 0x1e04000+0x23000, SPI311/432, SMP2P ipa in/out,
   all five interconnect paths/cases, rmnet-ipa and msm_gsi
   compatible nodes, correct clocks and rails.
   The final *packed* boot DTB/DTBO must be decoded and audited.
6. **Built-in, not external .ko**: final CONFIG_GSI=y,
   CONFIG_IPA3=y, CONFIG_RMNET_IPA3=y and matching real
   ipa_fmwk built in. The temporary external modules are *only* ABI
   tests, not a substitute for a linked vmlinux with actual IPA.
   Verify that IPA is ready before P468 /dev/subsys_modem first open
   (observed at about 11 seconds). Prefer an explicit bounded
   ready completion at the modem open boundary; a timeout must return
   failure without booting the modem, mutating power refs, faking
   endpoints, or changing the P469b recovery policy.
7. **MSS notifications are currently missing**: implement a real
   producer tied to 5.10 remoteproc PAS lifecycle including manual
   restart and P469b fatal-stop/clean OFFLINE.
   Deliver SUBSYS_BEFORE_SHUTDOWN, AFTER_SHUTDOWN,
   BEFORE_POWERUP, AFTER_POWERUP to existing legacy notifier
   consumers in correct order. Log `P470 MSS NOTIF event=`.
   Do not call sleeping QRTR consumers while holding a lock
   that can deadlock the stopped transport. Never treat the
   existing TG notifier **consumer** as proof of a producer.
8. **Instrumentation**: linked, reachable IPA/GSI source emits
   `P470 IPA PROBE`, `P470 IPA SMMU`,
   `P470 IPA FW_LOAD`, `P470 IPA GSI READY`.
   Capture actual /dev/ipa and rmnet_ipa0 registration and the
   `RMNET_IOCTL_GET_EP_PAIR` return with real WAN endpoints.
9. **Fall back**: any missing SMMU/PAS/ICC/SMP2P/SSR dependency
   blocks IPA activation, records an explicit error, and leaves
   P469b manual modem startup / crashloop cleanup untouched.
   No fabricated netdev, endpoint, PAS auth, SMMU bypass,
   or success messages. No flash artifact until CI and
   hardware acceptance.

## Current readiness status

- A1 strict post-Image ABI: PASS (#628), but with A0 compile-only gates.
- A2 un-stubbed source+ABI: running as a new strict CI stage.
- Final built-in linkage: NOT IMPLEMENTED.
- Real S1_BYPASS/FAST/fastmap: NOT IMPLEMENTED.
- PAS15 legacy PIL driver/node and firmware: NOT IMPLEMENTED.
- Final DT, SMP2P and 5-path ICC: NOT IMPLEMENTED.
- MSS lifecycle notifier producer: NOT IMPLEMENTED.
- Bounded modem-ready gate: NOT IMPLEMENTED.
- Flashable IPA image: **NO**.

## Required acceptance evidence

A) Unstubbed strict post-Image compile and symbol closure, all real providers.
B) Byte-pinned source, same source in built-in IPA, no userland fake device.
C) Final DTB and live FDT verify IRQ/SID/PAS/ICC/MSS ownership,
   no duplicate PAS owner or memory overlap.
D) Phase206 veto intact; P460B experimental knob still opt-in,
   SME/S2CR checksum unchanged after suspend/resume in IPA-active testing.
E) Live firmware auth PAS15, GSI ready, QMI modem init, valid EP_PAIR.
F) P468 first open waits boundedly for actual IPA readiness;
   failure remains safe and P469b cleanup remains effective.
G) MSS notif before/after transitions visible on normal shutdown,
   manual restart, fatal and crashloop stop; no QRTR D-state stalls.
H) Five-minute modem session with no ps_rm:0xb9 and no
   `glink-edge: intent request timed out` after clean OFFLINE.
