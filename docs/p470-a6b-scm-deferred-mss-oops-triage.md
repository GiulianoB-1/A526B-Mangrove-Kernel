# P470-A6b: SCM-enabled deferred MSS adsp_probe Oops

## Device evidence (2026-10-31)

Source: user-provided `capture-20261031-p470-a6-scm-enable-oops-mss-adsp-probe-dev-info.md` prepared by Claude. Original PuTTY log and pmsg files were described in that work order, but their raw bytes and the exact build #678 `vmlinux` were not provided here.

- Kernel: 5.10.252-Mangrove #5, workflow #678, commit `b710980d`.
- Enabling SCM at ~11.936 s probes `firmware:scm` successfully (~11.951 s), then re-runs deferred drivers, including MSS.
- `P468B MSS SUBSYS REGISTER name=modem dev=subsys_modem ... rc=0` followed ~11.963 s by a kernel DABT `ESR=0x96000005`, fault address near null (corrupted bits).
- Affected stack: `__dev_printk` <- `_dev_info` <- `adsp_probe` <- `platform_drv_probe` <- `deferred_probe_work_func`.
- Workqueue `events_unbound`, CPU 3, `kworker/u16:...`.
- One observed crash occurred before IPA auto-arm. With SCM skipped, ADSP remains up for minutes; P469b succeeds through the same modem SSR char registration.
- This is NOT evidence that IPA hardware, DMA mapping or RPMh bus voting caused the crash.

## Original P468 risk

P468 source transformer inserts these members at the head of `struct qcom_adsp`:

```c
struct subsys_desc a52_modem_ssr_desc;
struct subsys_device *a52_modem_ssr;
```

It registers `&adsp->a52_modem_ssr_desc` through the TG `subsys_register` implementation, which parses DT and writes descriptor IRQ/SMEM fields. Afterwards, a `dev_info(adsp->dev,...)` prints. The last known successful log is inside the registration implementation, where `desc->dev` is accessible.

**Hypothesis:** difference in the compiled `struct subsys_desc` representation across q6v5 PAS and TG SSR leads to overwriting the following `adsp->dev` pointer. The TG header has optional `CONFIG_SETUP_SSR_NOTIF_TIMEOUTS` and `CONFIG_SENSORS_SSC` members, so inspect actual preprocessed translation units. This hypothesis remains **unproven** until the compiler evidence, fault instruction and phone retest are checked.

## A6b bounded source fix

Implemented in `scripts/470_a6b_mss_ssr_abi_guard.py` and applied ONLY after A6 source staging, preserving the prebuilt P469b fallback:

1. PAS `qcom_adsp` stores `struct subsys_desc *` rather than embedding the TG descriptor first.
2. Allocate `struct subsys_desc` in the TG `subsystem_restart.c` compilation unit; compare PAS expected `sizeof` plus offsets for `name`, `dev`, `owner`, `powerup`, `shutdown`, `state`, `force_stop_bit`, `err_fatal_irq` before returning it. Reject an ABI mismatch with `ERR_PTR(-EPROTO)`.
3. `adsp_probe` uses `dev_info(&pdev->dev,...)` instead of dereferencing potentially corrupted `adsp->dev` after registration.
4. The SSR callbacks use guarded `dev_get_drvdata(desc->dev)` and verify descriptor identity instead of `container_of(desc, struct qcom_adsp, a52_modem_ssr_desc)`.
5. Free on failed registration and after unregister, and keep PAS online even when the optional char-device shim cannot be registered.
6. No changes to IPA HW gates, A6 real RPMh client, DT, PAS15, Q6v5 power policy, or P469b image.

## Compiler and runtime evidence boundaries

`scripts/470_a6b_ssr_preprocessed_audit.py` compares the exact preprocessed `struct subsys_desc` declarations from P469b PAS/SSR and A6b PAS/SSR. A matching declaration hash does **not** prove matching `sizeof` on all compiler options; the A6b runtime ABI report logs the actual sizes and offsets from both object units before calling `subsys_register`. If declarations differ, CI fails; if runtime layouts differ, the shim refuses registration.

The source report is **not a hardware PASS**. The #678 `vmlinux` (with DWARF) is not available in the existing GitHub Actions artifacts, so `addr2line -fip -e vmlinux` and `objdump -dS` cannot yet identify the exact fault instruction. Do not invent a source line from the damaged offset.

## Phone acceptance sequence

First boot A6b with `a52adspauto v3.2` in **ADSP-only** mode. Do not arm IPA.

- `A52STEP SCM_BEGIN` -> `P458 SCM RUNTIME_ENABLE rc=0`.
- `SCM_PLUS_1S_ALIVE` appears with no Oops, and at least several minutes of stability.
- ADSP `START state=running`, `BOOT_OK`, `SENSORS count=32`.
- `P470-A6b SSR ABI PAS...` and `P470-A6b SSR ABI TG...` report matching field sizes/offsets; `P468B MSS SUBSYS REGISTER` proceeds without Oops.
- Disarmed modem first open logs `P470 MSS IPA_WAIT disarmed=1 P469b_passthrough=1` and RIL/SIM/LTE return as on P469b.
- The unmodified P469b fallback boot remains available.

Only if that is observed, intentionally switch to **ADSP+IPA** collector mode for first IPA arm; verify real five-path bus votes, PAS15, GSI, translated SMMU mappings, IOVA traces, and no modem ps_rm fatal. Pstore ECC48 remains vulnerable to A52-specific bit-clearing, so the streamed kmsg-to-pmsg and file catcher are more reliable for this test.

**CI build success never substitutes for the phone hardware results.**
