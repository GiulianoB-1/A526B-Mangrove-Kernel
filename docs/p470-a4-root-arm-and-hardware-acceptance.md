# P470-A4: Root-only IPA ARM and native hardware acceptance (in progress)

Base: P470-A3 / #656 @ `55ca666e` (built-in IPA/GSI/RMNET/framework link PASS).

**Current status: NO FLASH.** These scripts run against a *disposable* native
GKI tree after the known-good P469b boot artifact has been packaged. Even a
green A4 compile means only linked source, not a qualified IPA image.

## Boot safety and permission

- Every boot: `/sys/kernel/a52_ipa/enable` defaults disabled. Mode 0200,
  requires CAP_SYS_ADMIN, accepts exactly `1`, and is one-shot. No auto-arm.
- All Lagoon IPA master and child probes return `-EPROBE_DEFER` until ARM and
  `qcom_scm_is_available()`. No IPA resource access before the ARM check.
- SCM registration is still the independent, root-only P458 operation.
- The IPA donor's `ipa_assert()` still calls `BUG()`, and GSI has `BUG()`
  paths. Root-only ARM reduces the exposure window but **cannot prevent**
  a crash after it is armed. Preserve pstore, crash marker and the P469b
  recovery image.
- A privileged KSU module must create and fsync a persistent attempt marker
  **before** writing ARM=1, and clear it only after the defined successful
  validation checkpoint. On the next boot, a pending attempt marker must
  suppress ARM. Verify this behavior with a controlled nonfatal abort first.
- Never auto-arm in kernel initcalls, DTS, module params or vendor userspace.

## Ownership/order

1. The manual P458 SCM knob registers the real SCM provider.
2. Root-only A4 ARM triggers a reprobe of the already deferred IPA master.
3. Pinned IPA obtains the **single** legacy PAS15 firmware owner using
   `subsystem_get("lagoon_ipa_fws")`. This is the exact TouchGrass
   `qcom,firmware-name` value for `qcom,ipa_fws`; `ipa_fws` itself is the
   DT node label, **not** the registered subsystem name.
4. Only after the real `ipa3_post_init()` success, after successful
   PAS15 acquisition, is A4 IPA_READY completion signaled.
5. The P468 legacy `/dev/subsys_modem` powerup waits up to 15 seconds for
   readiness **before** `rproc_boot()`. Timeout returns an error and never
   fabricates PAS, endpoints, ONLINE state or a new power reference. P469b's
   manual remoteproc sysfs/recovery path remains unmodified.

## Offline diagnostics and missing runtime proof

- `scripts/470_a4_dtb_audit.py` examines the *actual staged P468-MSS DTB*.
  It verifies the exact IPA/GSI MMIO, SPI311/432, IPAv4.7, PAS15 and its
  unique `lagoon_ipa_fws` owner, 0x8b700000/0x8b710000 reservations,
  three unmasked IPA SIDs, the AP/uC DMA allocator windows, two DIRECT
  windows, SMP2P in/out and five interconnect vote paths. Any blocker is
  recorded, never silently corrected in the boot partition.
- The existing A2c SMMU callback logs reserved complement, SID, aperture.
  The A2c IPA CB adapter validates every 4K DIRECT IOVA mapping using
  `iommu_iova_to_phys()`; A4 logs a positive mapping and domain type/aperture.
- `scripts/470_a4_dma_iova_trace.py` logs the first eight successful
  IPA AP/uC DMA page/SG IOVA mappings, their domain type/aperture and whether
  the resulting IOVA is within the TouchGrass allocator-owned window.
  It does not alter the allocator, change S2CR, or use a fake FAST domain.
- **Still to prove**: P470 PAS15 legacy PIL provider binds after P458 SCM;
  P470-SMMU callback runs with correct DMA domain/aperture and actually
  reserves outside the pool; GSI firmware handshakes, full live DMA tests,
  and the missing MSS remoteproc/SSR notifier producer.
- Do not remove Phase206/P460B default apps-SMMU suspend veto or accept
  a "success" from `rproc_boot` if IPA is not actually ready.

## Hardware acceptance required before calling an A4 image flashable

1. A4 strict built-in Image compile/ABI and complete static packed DTB
   ownership/binding audit PASS, with no extra firmware PAS owner.
2. KSU crash marker/next-boot suppression and ECC48 pstore capture proved.
3. Real boot traces, in this order: `P470 IPA ARM`,
   `P470 IPA PROBE`, `P470 IPA SMMU`, `P470 IPA FW_LOAD`,
   `P470 IPA GSI READY`, `P470 MSS IPA_WAIT ready=1`.
4. `/dev/ipa`, `/dev/wwan_ioctl`, and `rmnet_ipa0` genuinely registered.
   `RMNET_IOCTL_GET_EP_PAIR` returns real WAN endpoints.
5. At least five minutes after SIM READY and signal bars, **no**
   `ps_rm:0xb9` fatal, `RILD GetEpPair: Failed`, or QRTR D-state hangs.
6. All 32 sensors still work, real s2idle/suspend does not regress,
   and pstore captures any asserted condition.
7. Preserve the original known-good P469b recovery boot and modems EFS.
   Never interpret a CI kernel link, a source-only PAS marker, or an
   unverified DTB as proof of hardware flashability.

A4 remains intentionally no-flash until the remaining implementations and
acceptance checks above are completed.
