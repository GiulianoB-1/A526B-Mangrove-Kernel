# P470-A2 run #629: true unstubbed ABI blockers, NO FLASH

Run: https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/41052330363
Commit: 1510afa003505c2aa5a5be2504d5437f57711cbc
Failed step: P470-A2 STRICT UNSTUBBED IPA ABI.
Previous A1 module ABI closure @ #628 remained PASS because it compiled with
-DP470_A0_COMPILE_ONLY. The fresh A2 compilation **correctly failed** when
these guards were removed. Do not reintroduce the guards to claim A2 success.

## Nine compiler diagnostics in ipa_v3/ipa.c

- 2 missing SCM functions: qcom_scm_mem_protect_region_id,
  qcom_scm_get_sec_dump_state.
- 4 absent DOMAIN_ATTR_S1_BYPASS references (WLAN, uC, AP, 11ad CB).
- 3 absent DOMAIN_ATTR_FAST references (WLAN, uC, AP CB).
- No strict A2 post-link modpost result is available: ipa.o could not compile.
  A1 post-link closure cannot be inherited by A2.

## Source authority and priority

The pinned CodeLinaro 5.10 kernel
f438c918a464b82d4a637b5327dd1ed6e8b625dc carries:
- include/linux/iommu.h: genuine vendor DOMAIN_ATTR_S1_BYPASS/FAST.
- drivers/iommu/arm/arm-smmu/arm-smmu.c:
  sets S1_BYPASS before domain attachment; S1_BYPASS changes
  context SCTLR.M semantics; parses qcom,iommu-dma="fastmap",
  sets DOMAIN_ATTR_ATOMIC and only selects FAST when
  CONFIG_IOMMU_IO_PGTABLE_FAST is enabled; FAST chooses ARM_V8L_FAST
  and the vendor fast-I/O pagetable/DMA cookie.
- drivers/iommu/io-pgtable-fast.c, dma-mapping-fast.c,
  qcom-dma-iommu-generic.c: genuine fastmap implementation.
- drivers/firmware/qcom_scm.c: exports both actual missing SCM calls.
  include/linux/qcom_scm.h declares them.

These are not just header mismatches. The current Mangrove GKI tree
has neither complete vendor fastmap semantics nor the two SCM services.
Never add only enum values, KBUILD_EXTRA_SYMBOLS, always-success hooks,
or set FAST=0 while claiming TouchGrass fastmap parity.

## Next implementation order

1. Preserve Phase206 apps-SMMU suspend veto, the P460B root-only
   opt-in, and SME/S2CR checksum evidence.
2. Port or reimplement **real** vendor IPA CB mapping semantics on
   the composed GKI kernel: SIDs 0x440, 0x441, 0x442, real
   bypass/FAST state, 5.10 fast-I/O page tables and DMA cookie,
   IPA AP additional map 0x146a8000 + 0x2000, WLAN extra map
   0x1ea0000 + 0x80000. Do not modify unrelated GPU or ADSP streams.
3. The TouchGrass Lagoon IPA node **does not contain**
   qcom,ipa-tz-unlock-reg. This makes mem_protect_region_id
   secondary, not the first milestone. Verify the **final effective**
   DTB lacks it and ensure a future unexpected property fails closed
   until a real SCM implementation is present.
4. Secure-dump state only gates optional diagnostics. If it cannot
   be queried, leave secure dumps disabled. Never turn dump permission
   on or report a fake secure-world response.
5. Use only one firmware PAS15 owner
   (soc:qcom,ipa_fws, lagoon_ipa_fws) and genuine subsystem_get.
6. Add MSS remoteproc notifier producer plus bounded modem startup
   gate, with P469b no-IPA behavior preserved on failure.
7. After every step, fresh compile of **all A2 objects** with
   NO P470_A0_COMPILE_ONLY and real vmlinux/Module.symvers modpost;
   after actual built-in IPA, verify linked Image/System.map and
   final DTB, not just an external .ko.

## CI interpretation

- A1 strict module ABI: PASS (compile-only).
- A2 unstubbed compilation: BLOCKED at ipa.o; no post-link proof.
- A2 hardware/DT/firmware/runtime: NOT IMPLEMENTED.
- Flashable IPA artifact: NO. Keep IPA=0, P469b rollback unchanged.

A green status cannot be obtained safely by ignoring these diagnostics.
