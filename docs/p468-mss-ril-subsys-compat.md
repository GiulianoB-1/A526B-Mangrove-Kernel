# P468 MSS legacy RIL subsystem compatibility on proven P467

## Proven starting point
- Exact baseline: [Actions run 40749455719](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/actions/runs/40749455719), SHA 2a832c024021d34c26fee40a5a00b629bb2bef51, P467 artifact MANGROVE-P467-MSS-MANUAL-RMTFS-G-582.
- Hardware: MSS PAS_AUTH rc=0, GLINK modem PID=1, IPCRTR and glink_ssr, RMTFS /dev/uio0 + three modem partitions opened/read, a complete 2,621,440-byte write; >60 s without modem fatal.
- Userspace: RILD "There's no valid ESOC node" and "Modem boot failure", SIM state empty. This is *not* evidence that the modem PAS failed.
- The stated collector v1.24 modem_userspace_hints.txt was not present when P468 was authored. Proprietary Samsung RIL and per_mgr exact ESOC checks, path, ioctl flags, retries and failure attribution remain unverified. Do not claim RIL will work just because /dev/subsys_modem exists.

## TG pinned source facts
TG source: https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/drivers/soc/qcom/subsystem_restart.c

- Lines 1489-1508: /dev/subsys_NAME .open maps minor to subsystem and calls subsystem_get_with_fwname(desc->name, desc->fw_name); errno bubbles up. It does not carry user data.
- Lines 1511-1532: .release calls subsystem_put; no TG subsystem-specific ioctl or read/write operation.
- Lines 1557-1589: alloc_chrdev_region("subsys") and device_create("subsys_%s") with cdev.
- Lines 237-251 and 386-401: msm_subsys bus exposes name/state, and other core attrs. Stock TG "state" tracks its local SSR state, which must not be used as a fake signal of the actual remoteproc.
- Lines 952-1033: first legacy power reference invokes the registered powerup callback; nested opens refcount. Last put invokes shutdown.
- TG modem supplies PAS firmware called modem; P467 rproc firmware remains modem.mdt. No vendor modem image is renamed or copied.

## P468 solution and invariants
- Keep TG subsystem_restart core responsible for registering the real class, /dev/subsys_modem and msm_subsys bus; do not install a second independent char class.
- After rproc_add() succeeds for only the P467 MSS descriptor, register an SSR desc with name "modem" and callbacks to rproc_boot()/rproc_shutdown(). Keep a single remoteproc power ref across all opens; existing TG subsystem_get/put counts legacy FDs. rproc_boot increments an existing running rproc ref but does not reboot PAS, so manual sysfs stays independent.
- If rproc_boot() fails, propagate its errno; do not claim ONLINE. If state is not RPROC_RUNNING after a successful boot, fail the open. In a crash state, return -EPIPE instead of pretending it is healthy.
- P468 makes msm_subsys 'modem' state show only RPROC_RUNNING as ONLINE; any other state or missing phandle is OFFLINE, regardless of TG bookkeeping. This is limited strictly to the modem name. All other subsystem states remain unchanged.
- P468 makes sure the existing P467 MSS PAS parent has an OF phandle; no new powered device, interrupt, mbox, regulator, Q6 or region edits.
- Add '/vendor/firmware-modem/image' to the direct firmware_class search, after its explicit path parameter but before standard locations. Existing paths remain.
- The P467 PAS retains auto_boot=false, PAS4, modem.mdt, 421, AOSS modem load_state, two level-384 regulators, IPCRTR/glink_ssr, RMTFS UIO+SCM, and only the currently supported remoteproc callbacks.
- The existing P466/P463/P460B/P457/P462, Phase206 default suspend veto and ADSP are unmodified. No IPA, cellular data, WLAN, voice or ESOC stub is introduced.
- Failure registering the SSR compat node is logged and does not suppress an otherwise working P467 PAS.

## CI acceptance
1. Validate P468 Python scripts at preflight.
2. Patch only after P467 PASS source checks and preserve P467 src marker gates.
3. Require CONFIG_MSM_SUBSYSTEM_RESTART=y; no unrelated fallback if TG core unavailable.
4. Require source gates on state mirror and new direct firmware path.
5. Require linked Image strings for P468 modem registration/open and firmware directory.
6. Check original P467 staged DTB unchanged; on its copy, assign phandle if needed, and re-run P467 check for PAS, rails, RMTFS, IPCRTR/glink_ssr and ECC48.
7. Package a distinct P468 G boot image. Never overwrite the known-good run 40749455719 artifact.

## First read-only hardware collection
After testing **only after** successful G artifact CI, collect:
- /dev/subsys_modem node, major/minor, SELinux label and uevent permissions; /sys/class/subsys/subsys_modem/uevent.
- /sys/bus/msm_subsys/devices/*/name and state, matching modem dynamically, and remoteproc name/state. States must match. Also inspect them before RIL starts, if feasible, without manually forcing boot.
- dmesg P468 MSS SUBSYS REGISTER/OPEN/RELEASE + P467 PAS_AUTH and GLINK + firmware loader fallback messages. Expect no second PAS_AUTH if the MSS is already running and RIL merely opens the device.
- logcat -b radio and -b all filtered for RILD/per_mgr/ESOC/modem boot QMI/QRTR/NETMGR.
- Collector v1.24 modem_userspace_hints.txt: exact strings and any referenced /dev/esocX, /sys/bus/esoc, /dev/subsys_modem, /sys/bus/msm_subsys/device state, process open modes; compare to TG before implementing any additional contract.
- SIM and registration read-only (dumpsys telephony.registry); do not force cellular data, reboot modem or trigger SSR.

## Stop conditions
- No claim of working RIL/SIM until modem_userspace_hints and actual live logs show progress.
- Fail the build if TG SSR core, P467 downstream PAS anchor, or phandle check drifts.
- Abort hardware trial if P467 MSS first boot or RMTFS regresses, kernel panic, modem crash, repeated PAS reloads, broken charger/SMMU PM, or unexpected IPA.
