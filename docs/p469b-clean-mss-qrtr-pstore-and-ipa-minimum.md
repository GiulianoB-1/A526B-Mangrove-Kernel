# P469b: clean crashloop stop, pstore and IPA minimum

## Exact baseline

P469 G Actions run #598 https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/40871537827, commit cde98b81a921bb237bdcf1e4e369cfed4951801e and artifact MANGROVE-P469-MSS-GUARD-PSTORE-G-598.

No IPA port in P469b. Maintain P468b #596 and P469 #598 as rollback images. Preserve charger, ADSP, FastRPC, DTB, and RMTFS paths.

## MSS lifecycle

On the second fatal within 300 s, P469 disables automatic recovery but leaves the modem CRASHED with live GLINK and QRTR endpoints. The D-state QRTR consumers (sensors@2.0, rmt_storage, 271_see) suggest the dead endpoint holds kernel clients and stalls SensorService.

P469b calls rproc_stop(rproc, true) inside the crash handler under the core mutex, only for the targeted MSS crashloop-stop. This stops GLINK subdevices, calls Qualcomm PAS stop, unprepares subdevices, and sets OFFLINE on success. Do not start again automatically. If shutdown fails, emit STOP_FAILED with its errno, do not fabricate OFFLINE.

The P468 subsys_modem shim owns a counted remoteproc reference. Do not clear that reference. A manual sysfs state/start with OFFLINE and positive power uses the already supported rproc_trigger_recovery OFFLINE path, calling rproc_start without a new reference. With power zero, normal rproc_boot loads firmware. The P468 wrapper blocks automatic subsys_get after the crashloop threshold when OFFLINE and recovery_disabled; the final subsys_put cleans resources without redundant PAS stop. Keep automatic recovery disabled after an explicit manual restart to avoid continued crash loops before IPA exists.

### Hardware acceptance

Determine remoteprocN from sysfs name rather than assuming its number. Require second fatal then P469B MSS STOP_OFFLINE rc=0 and state OFFLINE, and no third automatic PAS_AUTH. Confirm both /sys/class/remoteproc/.../state and /sys/class/subsystem/subsys_modem/state read offline, no orphan GLINK edge or new QRTR intent timeouts, and no D-state QRTR blocking in SensorService. A controlled sysfs state/start must issue a real PAS start and preserve the P468 power reference. No EFS writes.

## Pstore correction

The #598 Actions build log explicitly confirms CONFIG_PSTORE_RAM=y, compiles fs/pstore/ram.o, and checks for P461 PSTORE RAMOOPS_PROBE in the linked Image. Therefore the observed missing initcall/probe at runtime does NOT establish a missing built-in Kconfig symbol.

The boot command line includes ramoops.mem_size=0x00100000, which can register an additional legacy dummy platform device. The DT already owns reserved-memory ramoops@B1B00000. The P469b transformer keeps the exact live 0xB1B00000 + 0x100000 DT region and ECC48, suppresses dummy registration only if that available DT resource exists, and instruments ramoops_init entry/driver registration result. It does not make any new DT node or memory reservation.

Require P469B PSTORE INIT enter and register_rc=0, P469B PSTORE DT_OWNER, P461 PSTORE RAMOOPS_PROBE, P461 PSTORE RAMOOPS_REGISTER, and pstore: Registered ramoops. Check binding in /sys/bus/platform/drivers/ramoops, inspect any probe failure errno, verify ECC48 and records across reboot. If no initcall message appears despite Image linkage, capture actual running boot identity plus initcall_debug and init section evidence before modifying config again.

## Minimum true IPA port (separate phase)

Pinned TouchGrass 4.19 source SHA 6bf351bdf18bdb228db79e66f14a7a9c0178e5d7:

1. Real GSI device/channel/ring support from drivers/platform/msm/gsi (CONFIG_GSI).
2. Full downstream drivers/platform/msm/ipa/ipa_v3 and ipahal (CONFIG_IPA3), clocks, regulator, SMMU, memory, interrupts, endpoint configuration, filters and routing. IPA firmware ipa_fws and PAS 0xF only after checking the real DT/SCM/firmware contract.
3. rmnet_ipa.c (CONFIG_RMNET_IPA3) must register real rmnet_ipa0 and the netdev ioctl function ipa3_wwan_ioctl.
4. The Samsung RIL extended ioctl ABI is RMNET_IOCTL_EXTENDED, which checks CAP_NET_ADMIN and decodes rmnet_ioctl_extended_s. The GET_EP_PAIR subcommand calls ipa3_get_ep_mapping(IPA_CLIENT_APPS_WAN_CONS) and ipa3_get_ep_mapping(IPA_CLIENT_APPS_WAN_PROD). Either missing mapping returns -EFAULT. Return actual mapped IDs in the correct producer_pipe_num/consumer_pipe_num UAPI fields, not fabricated endpoint IDs.
5. Extended format/mux ABI: RMNET_IOCTL_SET_EGRESS_DATA_FORMAT, RMNET_IOCTL_SET_INGRESS_DATA_FORMAT, RMNET_IOCTL_ADD_MUX_CHANNEL, RMNET_IOCTL_GET_SUPPORTED_FEATURES. Include relevant UAPI headers (msm_ipa.h, rmnet_data.h), /dev/ipa, /dev/wwan_ioctl, ipa_qmi_service*.c, rmnet_ipa_fd_ioctl.c, ipa_api.c, ipa_rm*.c, firmware and SSR lifecycle.
6. Validate hardware in order: probe, IPA firmware, GSI pipes, real endpoint mappings, rmnet_ipa0 registration, GET_EP_PAIR, extended data-format ioctls, QMI/SSR behavior, no immediate ps_rm:0xb9, and greater than five minutes MSS stability. Mobile data OFF is not a valid bypass: RIL configures these endpoints on initialization.

Passing GetEpPair alone is necessary but not sufficient proof of modem stability. P469b intentionally retains IPA=0; do not enable it merely by adding a fake ioctl or creating a dummy netdev.
