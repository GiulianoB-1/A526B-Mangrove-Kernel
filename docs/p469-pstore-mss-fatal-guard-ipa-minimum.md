# P469: preserve P468b modem RIL, cap MSS fatal restart loops, repair ramoops discovery

## Verified starting point

P468b Actions [#596](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/40845490517), SHA `e3e322a9837fb44a98b64bdd6ec2dddae291a1b9`. Hardware Oct 29 09:35:56: `/dev/subsys_modem` **504:2** registered, `pm_proxy_helper` opens and boots MSS, PerMgrSrv adds modem, Samsung RIL registers, reads SIM apps and LTE serving cell (RSRP -98.9 dBm; signal level 3). No EFS writes. Data configuration failed on missing `rmnet_ipa0` EP pair before modem `EX:kernel:0x0:ps_rm:0xb9`, repeated fatal/restart cycles, recovery #5 PAS timed out -110. No kernel Oops. P468b is the untouched rollback.

## P469 code changes (no IPA in this build)

**1. Pstore**: P461's extra OF/platform population fallback previously required `np->full_name == "/reserved-memory/ramoops@B1B00000"`. GKI 5.10 can report the basename only, so the matcher incorrectly rejects the correct node. P469 checks (a) `np->parent` is named `reserved-memory`, (b) case-insensitive `kbasename(np->full_name)` matches `ramoops@B1B00000`, (c) translated physical `reg` spans exactly **0xB1B00000 + 0x00100000**. It retains the P461 checks for an already registered platform device and `OF_POPULATED` bookkeeping. No DTB change, no second ramoops device or region. Hardware confirmation still required: one live ramoops, ECC48, `pstore: Registered`, and persistent records across reboot.

**2. MSS crash-loop guard**: 5.10 Q6v5 fatal IRQ passes `RPROC_FATAL_ERROR` to `rproc_report_crash`; watchdog reports `RPROC_WATCHDOG`. P469 records fatal notification with an atomic, consumes at most one fatal **per handled crash episode** within `rproc_crash_handler_work`, and applies a 5-minute window to the SM6350 MSS parent only. After two fatal episodes in the current window: `recovery_disabled=true`, `P469 MSS CRASHLOOP_STOP fatals=2 window_ms=300000 ...` and **no automatic** `rproc_trigger_recovery`. Other remoteprocs are unchanged. The modem remains offline/crashed and Android RIL may become unavailable; that is intentional to avoid endless fatal resets.

**3. Recovery and stale power**: Upstream `rproc_trigger_recovery` calls `rproc_stop` (sets OFFLINE), then `rproc_start`. If PAS times out, the existing subsystem-open reference remains positive but the processor is OFFLINE. A subsequent sysfs `state=start` invokes `rproc_boot`, which skips the boot on `power>1` and returns success. P469 **only for SM6350 MSS** makes sysfs `state=start` return `-EBUSY` with `P469 MSS START_BLOCKED` when OFFLINE or CRASHED with outstanding power. Manual `echo recover > /sys/class/remoteproc/remoteprocN/recovery` is supported: with CRASHED, normal `rproc_stop` + firmware/start; with OFFLINE and positive power after failed recovery, reload firmware and retry `rproc_start` **without a second rproc_stop or refcount modification**. Manual result codes are returned to userspace and logged; `RPROC_RUNNING` is set only by the real successful start path. This is a deliberate controlled attempt, not automatic recovery. A failure leaves the modem offline; do not repeat blindly when hardware is unhealthy.

The MSS/ADSP PAS register, modem `stop` ownership, RMTFS, FastRPC, ECC48 topology, no-IPA policy, charger safety, and default P460B suspend veto remain unchanged.

## Hardware acceptance / diagnostics

- `dmesg | grep -E 'P469 MSS|P469 PSTORE|P461 PSTORE|pstore: Registered|remoteproc|PAS_AUTH'`.
- Confirm `P469 PSTORE NODE_MATCH`, `P461 PSTORE CREATE_OK` or `EXISTING`, actual `RAMOOPS_PROBE`, `RAMOOPS_REGISTER`, `pstore: Registered`; inspect live OF `/proc/device-tree` for one region 0xB1B00000/0x100000 and ECC48.
- Confirm two `RPROC_FATAL_ERROR` crashes inside 300 s produce `P469 MSS CRASHLOOP_STOP` and *no third automatic* PAS boot.
- Find actual MSS remoteproc index by its sysfs `name`; do not assume remoteproc0. Explicitly `echo recover > /sys/class/remoteproc/remoteprocN/recovery` to attempt one manual recovery. Confirm `P469 MSS MANUAL_RECOVER rc=...`, `P469 MSS MANUAL_RESTART` if offline. Before flashing or issuing writes keep a known-good boot image.
- `echo start > .../state` with stale positive power must now **fail** `EBUSY`, logging `START_BLOCKED` instead of claiming success. Do not automate the manual retry; enable no ESOC or IPA mock.

## IPA minimum downstream audit (NOT enabled in P469)

Pinned TouchGrass kernel SHA `6bf351bdf18bdb228db79e66f14a7a9c0178e5d7`:

| Required layer | TG source / dependency | Why EP pair requires it |
|---|---|---|
| Real GSI controller | `drivers/platform/msm/gsi/{gsi.c,gsi_reg*.h}`, `CONFIG_GSI` | IPA pipe/ring transport and FW activation |
| Downstream IPA3 core | `drivers/platform/msm/ipa/ipa_v3/Makefile` `ipat.o`, `ipahal/`, `ipa_{client,dp,rt,flt,utils,interrupts,...}.c`, `CONFIG_IPA3` | Real IPA endpoint mapping, routing, filters, SSR lifecycle |
| GSI/IPA firmware | TG `ipa.c` `ipa3_load_ipa_fw` around L6190–6220, `ipa3_pil_load_ipa_fws("ipa_fws")`, or guarded manual `ipa3_manual_load_ipa_fws` | Firmware state must be valid **before** configuring pipes; PAS 0xF is a suggested target and **must be verified against TG DTS and SCM**, not guessed into a live boot |
| Modem WAN netdev | `drivers/platform/msm/ipa/ipa_v3/rmnet_ipa.c` `CONFIG_RMNET_IPA3` | Creates real `rmnet_ipa0`, supports netdev private ioctls |
| Samsung RIL endpoint ABI | `rmnet_ipa.c` L1732–1905; `RMNET_IOCTL_EXTENDED` / `RMNET_IOCTL_GET_EP_PAIR` | `IPA_CLIENT_APPS_WAN_CONS` and `_PROD` mapping must be allocated. Missing mapping returns `-EFAULT`; no hardcoded or invented endpoint IDs |
| Data service plumbing | `ipa_qmi_service.c`, `ipa_qmi_service_v01.c`, `rmnet_ipa_fd_ioctl.c`, common `ipa_api.c`, `ipa_rm*.c`, `include/uapi/linux/msm_ipa.h`, `rmnet_data.h`, `rmnet_ipa_fd_ioctl.h` | QMI rules, route/filter and ioctl structs, SSR/data-up coordination |

The **minimum** to address the observed `GetEpPair` failure is not an ioctl stub; it is a **real** initialized IPA/GSI pair plus the `rmnet_ipa0` private ioctl returning actual mapped `WAN_CONS/WAN_PROD` endpoints, with the downstream UAPI sizes and `CAP_NET_ADMIN` behavior intact. Correct endpoint mapping is a necessary condition but might not be sufficient for `ps_rm`; Samsung's packet-data stack may also depend on QMI, IPA firmware and SSR handshake. Therefore port IPA3, GSI, compatible IPA firmware loading, SMMU and clocks, `rmnet_ipa0`, and the required UAPI closure as an **independent future phase**. Gate firmware PAS ID 0xF on verified DT/SCM evidence, and stage one-by-one (hardware probe => firmware/GSI => real pipes => netdev ABI => data call). Do not activate IPA on a build whose charger/suspend/ramoops control plane is being repaired.

### Rollback

The exact known-good P468b build is #596, not an older P468 branch head. Flash its known-good artifact if any P469 runtime regression appears. No EFS write or modem partition change is part of this work.
