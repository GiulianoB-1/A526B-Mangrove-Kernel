# P470-A4b: merged Device Tree provenance and disarmed modem parity

Baseline: accepted P470-A4 #663 @ `4ccbb491`.

**NO FLASH.** A4b is a disposable native Image build experiment. The
known-good P469b boot artifact continues to be uploaded unchanged.

## Correct PAS15 ownership

P469b hardware already showed:
- `subsys-pil-tz soc:qcom,ipa_fws` with firmware name `lagoon_ipa_fws`.
- `/dev/subsys_lagoon_ipa_fws` (503:0), `msm_subsys/subsys0`.
- PAS15 is therefore a **present kernel provider on that boot**, even
  though the prior staged-only A4 audit could not find its node.

A4b must **not** synthesize or duplicate `qcom,ipa_fws`. Its exact
identity is `qcom,firmware-name="lagoon_ipa_fws"` and PAS ID 15.

The remaining IPA, AP/WLAN/uC context banks, SMP2P in/out, GSI,
RMNET and 5-path interconnect contract must be inspected on the
**effective** Device Tree. Missing from the boot image alone is
insufficient proof of absence.

## P447 IPA=0 does not delete DT nodes

`scripts/447_stage_control.py` creates a compiled gate
`a52_447_enabled(A52_447_IPA)`, optionally overridden by the
`a52.ipa` kernel boot parameter. It has no FDT edits and does not
automatically remove IPA nodes. Presence, status, and overlay
provenance are separate questions.

## Merged-DT audit

Use an **exact** final P469b boot.img and an actual read-only dump of
the phone's flashed DTBO partition. Extract index 1 from the Android
DTBO table and simulate the bootloader's overlay with `fdtoverlay`.
Then compare the result against the collector's live
`/sys/firmware/fdt` to detect bootloader fixups or wrong partition inputs.

The script does not construct a fake DTBO, assume all missing nodes
need duplication, or enable an otherwise dormant node. It reports
missing, disabled, added, duplicated, path-changed, and absent-proof.

Run:

```bash
python3 scripts/470_a4b_merged_dtb_audit.py \
  --boot MANGROVE-P469B-MSS-OFFLINE-PSTORE-NO-IPA.boot.img \
  --dtbo flashed-dtbo.img --dtbo-index 1 \
  --live-fdt live.dtb --enforce \
  --report P470-A4B-MERGED-DTB-PROVENANCE.json \
  --merged-out P470-A4B-RECONSTRUCTED-MERGED.dtb
```

**No phone DTBO dump was available to the current GitHub CI.**
That CI reports `ACTUAL_FLASHED_DTBO_PARTITION_NOT_SUPPLIED`
and `NO_RECONSTRUCTED_MERGED_FDT`; a green compile is not a
green DTB audit. Collector v1.25's live tree will help classify the
remaining hardware nodes but cannot replace the exact DTBO bytes
for an offline merged-tree simulation.

## Modem behavior

- Disarmed IPA: the A4b readiness helper returns 0 immediately and
  P468 `rproc_boot()` proceeds exactly as in P469b.
- Armed IPA: P468's first legacy /dev/subsys_modem powerup waits
  no longer than 15000ms for genuine IPA_READY. Timeout returns
  `-ETIMEDOUT`, prints `P470 MSS WAIT_TIMEOUT modem_not_started`,
  and does not call `rproc_boot()`, take a power reference, or fake state.
- The explicit manual remoteproc sysfs start remains unaffected.
- The new remoteproc notifier producer uses an ordered workqueue and
  suppresses duplicate notifications during the existing P468 legacy
  SSR wrapper calls. It is scoped to SM6350 MSS only, and cannot
  replace live validation of SUBSYS events across crash/recovery.

## Flash blocker status

Hardware enablement remains blocked until a matching flashed DTBO
capture and live collector observations allow the merged-DT audit
to PASS. Passing compilation does not prove that the node is active,
that PAS15 firmware loads, or that the IPA parent/SMMU/IRQ/ICC
providers are operational.

Do not release a P470-A4b flashable image until the future image
gate also checks:
- exact final boot DTB and overlay provenance, unique PAS15 owner
- no unarmed IPA hardware activation, and true P469b modem parity
- SMMU/first-eight DMA and actual DIRECT iova-to-phys evidence
- correct ordered real SSR lifecycle notifications
- `/dev/ipa`, `/dev/wwan_ioctl`, `rmnet_ipa0`, RILD EP_PAIR,
  LTE for >=5min without ps_rm:0xb9, sensors32, real suspend
- KSU failed-attempt suppression and ECC48 pstore for asserts.

A4b deliberately only produces *diagnostics and a native test Image
that is NOT uploaded*. The known-good P469b image is retained.
