# P461 ADSP FastRPC — downstream ABI donor audit / integration gate

**Status:** ABI/source review and final-boot ECC48 gate only. **No FastRPC
driver, device nodes, or ADSP session support is present in this branch.**
Do not call the unchanged P460b boot image "P461 FastRPC".

## Source pins

* Target: Mangrove P460b success \`cc85e8a1581d287f3214d234736fd4f24eebe386\`.
* Vendor reference: TouchGrass \`micr0softstore/samsung_android_kernel_a52xq\`
  \`6bf351bdf18bdb228db79e66f14a7a9c0178e5d7\`;
  \`drivers/char/adsprpc_shared.h\`,
  \`drivers/char/adsprpc.c\`, \`arch/arm64/boot/dts/vendor/qcom/lagoon.dtsi\`.
* Candidate genuine kernel-5.10 downstream donor: 
  \`LineageOS/android_kernel_qcom_sm8450\`,
  \`952aa00564cbb2cc788378c97e08958c4b889758\`
  (lineage-20), \`drivers/char/adsprpc.c\` (8458 lines),
  \`adsprpc_shared.h\`, \`adsprpc_compat.c\`, \`adsprpc_compat.h\`.
* **Not** \`drivers/misc/fastrpc.c\`: upstream uses incompatible command
  numbers and creates different nodes.

## ABI evidence, source headers (not yet a vendor binary trace)

| ioctl number, magic 'R' | TouchGrass 4.19 | 5.10 donor | Required action |
|---|---|---|---|
| 1 | INVOKE | INVOKE | present |
| 2 | MMAP | MMAP | present |
| 3 | MUNMAP | MUNMAP | present |
| 4 | INVOKE_FD | INVOKE_FD | present |
| 5 | SETMODE | SETMODE | present |
| 6 | INIT | INIT | present |
| 7 | INVOKE_ATTRS | INVOKE_ATTRS | present |
| 8 | GETINFO | GETINFO | present |
| 9 | GETPERF | **not defined/dispatched** | **ABI GAP**: cannot claim full vendor compatibility |
| 10 | INIT_ATTRS | INIT_ATTRS | present |
| 11 | INVOKE_CRC | INVOKE_CRC | present |
| 12 | CONTROL | CONTROL | present |
| 13 | MUNMAP_FD | MUNMAP_FD | present |
| 14 | MMAP_64 | MMAP_64 | present |
| 15 | MUNMAP_64 | MUNMAP_64 | present |
| 17 | GET_DSP_INFO | GET_DSP_INFO | present |

Donor additionally supports INVOKE2 (18), MEM_MAP (19),
MEM_UNMAP (20), INVOKE_PERF (21), and NOTIF_RSP (22 in UAPI).
The donor's \`FASTRPC_INIT_ATTACH_SENSORS=3\` path is present.
**Presence of same names and numbering alone is not full ABI proof:**
compare 32-bit/64-bit ioctl request sizes, structures, \`CONFIG_COMPAT\`,
and actual \`libadsprpc.so\` calls for this ROM. The binary/library was not
available for inspection, so no claim is made that *all actually used*
vendor ioctls are supported.

Donor registers exactly \`adsprpc-smd\` and \`adsprpc-smd-secure\`
and binds \`qcom,msm-fastrpc-rpmsg\` over
\`fastrpcglink-apps-dsp\`. Do not create \`cdsprpc-smd\` or
\`/dev/fastrpc-*\`.

## Narrow DT requirement, from TG lagoon.dtsi

Parent: \`qcom,msm-fastrpc-compute\`.
Only these three child nodes should be eligible in P461:

| CB | SMMU SID/flags | DMA pool | Extra |
|---|---|---|---|
| cb10 | 0x1003 / 0 | 0x80000000 0x78000000 | dma-coherent |
| cb11 | 0x1004 / 0 | 0x80000000 0x78000000 | dma-coherent |
| cb12 | 0x1005 / 0 | 0x80000000 0x78000000 | shared-cb=<5>; dma-coherent |

All three carry \`qcom,iommu-faults = "stall-disable", "HUPCF"\`.
RPMSG child must be in the LIVE ADSP GLINK-edge (not the disabled legacy
GLINK transport); current P451 DTB code copies this channel.

No CDSP SIDs 0x1401..0x1409; no audio PD remote heap, hyp-assign,
PDR service subscription, or global SMMU changes.

## Driver blockers before enabling CONFIG_MSM_ADSPRPC

The real downstream donor source uses headers and services absent from
the generic 5.10 common baseline, including:

* \`linux/qcom-dma-mapping.h\`, \`linux/msm_ion.h\`,
  \`soc/qcom/secure_buffer.h\`, \`linux/mem-buf.h\`,
  and \`soc/qcom/qcom_ramdump.h\`;
* downstream \`qcom_rproc\` and PDR/QMI service hooks,
  tracepoints and IPC logging;
* downstream ION and DMA-buffer attach/map, SCM ownership and
  memory assignment APIs. **Never shim DMA onto the apps-SMMU parent**.
  Use the *specific* child context-bank device that owns each SID.
* modern donor includes optional audio remote-heap and hyp-assign calls;
  they must be compiled out with tested behavior, not replaced with
  unconditional success.

Importing \`adsprpc.c\` verbatim or simply renaming mainline FastRPC
would produce an untrustworthy build or unsafe buffer mapping.

## P461 required functional acceptance (NOT MET)

1. Driver is real downstream adsprpc; full ioctl ABI incl. compat
   is audited against the vendor library, and GETPERF disposition resolved.
2. \`P461 FASTRPC PROBE\` shows ADSP-only child enumeration, no eager SID attach.
3. \`P461 FASTRPC RPMSG UP\` appears only on live ADSP channel. Before ADSP
   is running, \`open\`/ioctl returns bounded \`-ENODEV\` / \`-ENOTCONN\`,
   not minutes of retry/wait.
4. \`/dev/adsprpc-smd\` and \`/dev/adsprpc-smd-secure\` exist with vendor
   SELinux labels \`vendor_qdsp_device\` and \`vendor_xdsp_device\`.
5. \`P461 FASTRPC OPEN\` reports domain/session; \`P461 FASTRPC SMMU ATTACH\`
   records SID 0x1003/4/5 at first session and reports the actual **child**
   owning the DMA/IOMMU mapping.
6. \`P461 FASTRPC PD_START\` confirms an actual sensors PD start, not
   merely a successful character-device open. \`sscrpcd\` survives and
   \`dumpsys sensorservice\` lists SSC sensors.
7. P457 \`arm-smmu-qcom.c\`, Phase206 veto, P460b and DSP knob are
   unchanged; no CDSP, forced PDR or audio remote heap.

## ECC48 on packaged boot image

P460b success log reports that P458's final disabled-SCM repack already
had \`ecc_size=[48]\` in the ramoops DT node. The missing step is independent
verification **after all repacks**. This branch adds
\`scripts/461_final_boot_ecc48_gate.py\` and copies the EXACT final DTB
(\`P461-FINAL-BOOT-ECC48.dtb\`) alongside a manifest with boot and DTB
SHA256. This is a **packaging** proof only; runtime
\`pstore: Registered ramoops\` must still be observed on-device.
