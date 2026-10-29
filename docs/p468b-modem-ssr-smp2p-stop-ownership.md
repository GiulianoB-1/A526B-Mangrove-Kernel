# P468b: MSS SSR `qcom,force-stop` ownership fix

## Provenance

- Built on the successful P468 [run #594](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/40836392709), commit `d592d857ee2ef6ff30d9984ff8d922671ce38568`.
- P468 itself is based on P467 [run #582](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/40749455719), commit `2a832c024021d34c26fee40a5a00b629bb2bef51`.
- TouchGrass subsystem restart reference: `micr0softstore/samsung_android_kernel_a52xq`, commit `6bf351bdf18bdb228db79e66f14a7a9c0178e5d7`, `drivers/soc/qcom/subsystem_restart.c`.

## Hardware diagnosis (P468 #2, October 29, 2026)

P468 PAS boots MSS and preserves the modem remoteproc. However, `subsys_register("modem")` failed with `-61` (`-ENODATA`). Legacy SSR `__get_smem_state(desc, "qcom,force-stop")` found a `qcom,smem-states` property on the 5.10 PAS OF node, then unsuccessfully requested the named legacy state. The 5.10 PAS node names the state `stop`, not `qcom,force-stop`. The SSR registration consequently aborted and did not expose a working `/dev/subsys_modem`.

## Minimal change

Only `scripts/468b_modem_ssr_smem.py` changes the *generated* `drivers/a52_pil/subsystem_restart.c`, after the successful P468 source patch:

1. `__get_smem_state`: when `desc->name == "modem"`, log `P468B MSS SSR SMEM_SKIP name=modem owner=q6v5_pas rc=-ENOENT` and return `-ENOENT` **before** any `desc->state` acquisition or use of the SMP2P bit. The existing `subsys_parse_devicetree` treats this result as optional and continues registration. Every other SSR device retains the original lookup.
2. At the successful end of `subsys_register` (after character device, devicetree parser, notifier, and IRQ setup), log `P468B MSS SUBSYS REGISTER name=modem dev=subsys_modem major=<N> minor=<N> rc=0`. Values come from the allocated `subsys->dev_no`, **not fabricated or hardcoded**.

No DT properties or aliases are added. The upstream 5.10 PAS alone owns the SMP2P `stop` state. P468 `rproc_boot` and `rproc_shutdown` power references, ADSP, FastRPC, charging safety, watchdog, suspend veto, ECC48, RMTFS, and the IPA-off policy remain unchanged. No ESOC stub is introduced.

## CI gates

- Patch is idempotence-guarded and refuses to apply without P468 SSR markers.
- A self-test verifies the modem-only early return, the untouched legacy provider path, accepted `-ENOENT`, and the success-only dynamic major/minor log.
- Kernel build must include both P468b log format strings, proved by searching the final linked `Image`.
- The existing P468 final DTB and boot-image audits remain active.
- CI success is **not** proof of device-node visibility, successful open, or RIL functionality.

## Hardware acceptance

1. Confirm `P468B MSS SSR SMEM_SKIP name=modem owner=q6v5_pas rc=-ENOENT`.
2. Confirm `P468B MSS SUBSYS REGISTER name=modem dev=subsys_modem major=N minor=M rc=0`, `/dev/subsys_modem` exists, and `/sys/bus/msm_subsys/devices/.../name` is `modem`.
3. Compare `stat -c '%t:%T' /dev/subsys_modem` with its actual sysfs `dev` (major:minor). Never assume a fixed major.
4. Open device and confirm power ref and real MSS state: `P468 MSS SUBSYS OPEN boot_rc=0 rproc=RUNNING`, and closing it balances the reference.
5. Watch `pm_proxy_helper`, `PerMgrSrv`, and Samsung RIL for the expected progression: peripheral found, `Adding entry for modem`, `SEM-RIL successfully registered for modem`. Existing TG logs support the device-node dependency; actual P468b hardware acceptance still required.
6. Verify no duplicate `qcom,force-stop` acquisition, no modem fatal, no duplicate PAS auth from a refcount-only open, no charger/USB/suspend regression.

**Rollback**: flash the successfully tested P468 #594 artifact or P467 #582 image if P468b runtime regresses.