# P470-A5: live DT accepted by report, legacy bus voting unresolved

P469b live DT evidence reported from the actual handset:
- `/sys/firmware/fdt` reflects bootloader-applied boot DTB + DTBO index 1.
- `/chosen/bootargs` and `/chosen/kaslr-seed` sanitized.
- IPA, PAS15, AP/WLAN/uC CBs, RMNET, GSI, both SMP2P IPA children,
  PAS/GSI reserved memory, and apps-smmu with seven TBU children are active.
- IPA MMIO 0x01e00000+0x84000, GSI 0x01e04000+0x23000, SPI311/432.
- PAS15 is **one existing** qcom,pil-tz-generic owner named lagoon_ipa_fws.
- AP/WLAN/uC SIDs are 0x440/0x441/0x442, translated.
- The DT contains *no* interconnects property. Instead, its IPA node
  contains qcom,msm-bus,num-cases=5, num-paths=5, and 100 u32 vectors.

These facts have been reported from phone evidence; as of this commit,
the sanitized binary DTB and raw DTBO partition dump are not checked
into this repo, and the GitHub runner has neither one. The new
`scripts/470_a5_live_ipa_audit.py` validates the effective live FDT
directly, including SMMU TBU count and unique PAS15, once the sanitized
bytes become available to CI. The script does not compare /chosen,
does not write DT or DTBO, and does not add any provider.

## The real blocker is the bus voter, not Device Tree geometry

TouchGrass Lagoon uses five paths in each of five power/performance
states (MIN, SVS2, SVS, NOMINAL, TURBO):

1. IPA -> LLCC
2. LLCC -> EBI_CH0
3. IPA -> OCIMEM
4. AMPSS_M0 -> IPA_CFG
5. IPA_CORE -> IPA_CORE

Each legacy vector has `master, slave, AB_kBps, IB_kBps`. The
numeric identifiers are **legacy MSM_BUS identifiers**, not a
verified mapping to Linux ICC provider node IDs.

The pinned 5.10 dataipa donor:
- requires an `interconnects` property and `qcom,interconnect,*
  ` bandwidth tables in `get_ipa_dts_pm_info()`;
- acquires five handles with `of_icc_get()`;
- votes with `icc_set_bw()` on enable, disable and clock-rate changes;
- on `qcom,bandwidth-vote-for-ipa`, disables the separate core clock
  handle. No bus vote is therefore an unsafe omission.

Simply translating numbers into `icc_clk` without a registered ICC
provider **does not vote hardware**. Creating a dummy/NULL path,
printing invented successful votes, directly using old MSM_BUS IDs as
ICC path IDs, or returning success from a missing bus voter is forbidden.

## Current A5 safety patch

`scripts/470_a5_bus_prearm_gate.py` applies a fail-closed bus check
before hardware resources are probed. It:

1. Validates the 5x5x4 legacy tuples and stable path endpoint ordering.
2. Logs each source, destination, AB, IB with `APPLIED=0` to distinguish
   observed DT policy from hardware writes.
3. If the target is legacy-only without a validated backend, logs
   `P470 IPA BUS BLOCKED ... rc=-EOPNOTSUPP` and refuses IPA probe.
4. Does not affect unarmed P469b modem start or reference counts.

**This is not a completed voter.** It deliberately makes the first
IPA-armed boot unavailable until the real MSM-bus service or a fully
mapped SM6350 ICC provider is installed, compiled, and validated.
The earlier `scripts/59_probe_a52xq_sm6350_interconnect.py` is an
interconnect compile *probe*, not evidence that the actual live Lagoon
legacy sources/destinations can already vote through GKI. Nothing in A5
silently skips five paths.

## Next implementation acceptance (before first flash)

- Port a real five-path voter, bound to all five live legacy routes.
  Keep source-destination mapping explicit and validated, with proper
  unit conversion; log each real operation, return code, state and
  master/slave identity.
- Enforce nonzero enable votes and zero disable votes. Audit cleanup
  on partial five-path registration, probe unwind, shutdown and SSR.
- Confirm no dummy backend (return-success without writing) is used.
- Verify root-only ARM default off, disarmed modem == P469b, armed modem
  timeout <=15 seconds with no `rproc_boot()` and no leaked ref.
- Verify no duplicate legacy MSS SSR events on /dev/subsys_modem open,
  manual remoteproc state changes, fatal/offline recovery.
- Confirm AP/WLAN/uC IOMMU runtime domain mode translated, exact SID,
  DIRECT 1:1 mappings, DMA first-eight IOVAs inside allocator pools,
  no IOVA alias, no TBU/SMMU fault.
- Only after those source/runtime safety prerequisites, assemble a
  **separately gated** first-boot diagnostic image; never repurpose the
  intact P469b fallback as an experimental IPA boot.

Current state: **A5 source compile experiment only, NO FLASH**.
