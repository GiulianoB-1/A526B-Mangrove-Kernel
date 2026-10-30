# P470-A6: real Lagoon IPA 5x5 TG RPMh bus client

## Corrected premise

Phase 252 already imports the real TouchGrass legacy MSM bus RPMh
driver and enables `CONFIG_QCOM_BUS_SCALING=y` and
`CONFIG_QCOM_BUS_CONFIG_RPMH=y`. Existing GKI drivers (UFS, USB,
I2C, KGSL) use that same fabric. P470-A5 was correct to refuse
**fake** ICC votes, but its assumption that Mangrove lacks a real
voting backend was incorrect.

P470-A6 uses the same TG API as the original IPA v3 implementation:
- `msm_bus_cl_get_pdata(ipa3_ctx->master_pdev)`
- `msm_bus_scale_register_client(pdata)`
- `msm_bus_scale_client_update_request(hdl, case)`
- `msm_bus_scale_unregister_client(hdl)`
- `msm_bus_cl_clear_pdata(pdata)`

No new DT nodes, no new ICC provider, and no second PAS15 owner.

## Exact bus paths in the real Lagoon DT

| # | Master | Slave |
| --- | --- | --- |
| 0 | 0x5a IPA | 0x302 LLCC |
| 1 | 0x81 LLCC | 0x200 EBI |
| 2 | 0x5a IPA | 0x249 IMEM |
| 3 | 0x01 APPS | 0x2a4 IPA_CFG |
| 4 | 0x8f IPA_CORE_MASTER | 0x309 IPA_CORE_SLAVE |

Every one of the five usecases must contain these same five pairs.
Case 0 (MIN) must be all-zero AB/IB; cases 1 through 4 come directly
from `qcom,msm-bus,vectors-KBps`. Native TG handles unit conversion.

The native dataipa 5.10 `get_ipa_dts_pm_info()` parses the same
`qcom,throughput-threshold` and scaling exception values, but for
Lagoon it **does not** attempt `of_icc_get()`. A6 obtains a real
TG legacy bus client, records `P470 IPA BUS register client=%u
cases=5 paths=5`, and takes an initial SVS2 vote before touching
IPA MMIO. Enable, off, and performance transitions vote using
the actual client API, with rate-limited `case` and `rc` logs.

If client registration returns zero or the initial vote fails,
the driver fails probe and releases the client and pdata.
Nonzero runtime errors latch failure and prevent the MSS IPA-ready
barrier from reporting a successful startup.

A5 retains its strict 5x5 raw DT verification and now accepts the
existing TG RPMh backend only when both Kconfig symbols are built in.

## Candidate boot image, controlled first flash

The CI output is a full Android boot-v2 image rebuilt from the
**unchanged** P469b baseline boot and the freshly linked A6 native
kernel Image, gzip-compressed with reproducible gzip headers.
The repacker preserves:
- the complete ramdisk
- the exact embedded DTB (bootloader merges installed DTBO idx 1)
- bootargs/cmdline, board and load addresses
- second and recovery-DTBO sections
- total boot partition length
- correctly regenerated boot image ID

The independent `470_a6_candidate_gate.py` verifies the
decompressed Image matches the native output exactly, all
required linked markers, and all four real MSM bus symbols.

### Separation of build proof from live-device proof

A successful CI build produces **a physically packaged review
candidate**, not an independently proven functioning IPA device.
No false runtime claims are made: IPA/SMMU/GSI/MSM bus votes
and firmware reception must be observed after the test.

**Do not arm IPA automatically on the first diagnostic boot.**
Before first-boot review, disable or configure `a52adspauto v2`
so `/sys/kernel/a52_ipa/enable` is not written automatically at
post-fs-data. Verify boot stability with IPA disarmed and P469b
modem behavior first. Only then deliberately arm once with the
collector already attached, once the review gates are accepted.

Phone evidence from P469b confirms the existing IPA/PAS/SMMU
Device Tree is enabled. However the sanitized live DTB and raw
DTBO bytes were not available in this repository for independent
CI verification. The live-FDT audit remains a separate input.

Mandatory first-run records:
- `P470 IPA ARM initialized disarmed=1` and authorized one-shot
- `P470 IPA BUS register client=...` and nonzero case votes rc=0
- exact AP/WLAN/uC SID/domain mappings and DIRECT translations
- `P470 IPA FW_LOAD`, `P470 IPA GSI READY`, DMA IOVA samples
- `P470 MSS NOTIF` events without duplicate legacy callbacks
- 15 s maximum armed wait; disarmed MSS first-open unchanged
- no modem `ps_rm:0xb9` fatal loop, QRTR deadlock or SMMU fault
- recovery path and P469b baseline image available unchanged

Hardware state is **not proven** by build success.
