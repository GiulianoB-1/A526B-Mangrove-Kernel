# P470: Qualcomm IPA v4.7 source-audit stage and hardware bring-up gates

**STATUS: SOURCE AUDIT ONLY. IPA/GSI ARE NOT ENABLED. NO P470 BOOT IMAGE.**

## Proven baseline, donors and rollback

P469b G #605 succeeded in GitHub CI, commit 19ff2acfc334f42788b645f29b690c33b652d1eb. Hardware acceptance of P469b is a separate matter. Preserve P468b #596, P469 #598 and P469b #605 as rollback images. No changes to P469b's MSS clean OFFLINE, legacy counted power reference, manual sysfs start, RMTFS, FastRPC or ECC48.

TouchGrass hardware authority: micr0softstore/samsung_android_kernel_a52xq at 6bf351bdf18bdb228db79e66f14a7a9c0178e5d7, file arch/arm64/boot/dts/qcom/lagoon.dtsi.

Selected Qualcomm 5.10 real driver donor: https://github.com/CodeLinaro-mirror/la_platform_vendor_opensource_dataipa at c560cc3c2840fb0ebc55ceef5b27549c66143637 (branch LA.UM.10.9.1.r1). Contains GSI, IPA3, ipahal, IPA PM, IPA QMI, rmnet_ipa and wwan ioctl source. This techpack is not standalone: it relies on Qualcomm vendor/kernel headers, SSR/QMI and Kbuild integration.

## Hardware and functional contract from the work order

- IPA 4.7, hardware version 18; base 0x1e00000 length 0x84000; GSI base 0x1e04000 length 0x23000; SPIs 311 and 432 high.
- PAS 0xF firmware lagoon_ipa_fws; reserved FW memory 0x8b700000+0x10000 and GSI 0x8b710000+0x5400.
- AP/WLAN/uC CB SIDs 0x440/0x441/0x442, with fastmap/extra mappings, real RPMh/ICC bus votes, SMP2P ipa in/out.
- True ipa_qmi_service AP/modem handshake, INIT_MODEM_DRIVER and completion.
- /dev/ipa, /dev/wwan_ioctl, real rmnet_ipa0, real GET_EP_PAIR mappings and radio permission/SELinux.
- 5.10 rproc life cycle must deliver legacy subsys_notif BEFORE_SHUTDOWN, AFTER_SHUTDOWN, BEFORE_POWERUP and AFTER_POWERUP, including crashloop OFFLINE and manual restart, without holding locks that wedge QRTR.

The chosen 5.10 donor *does* map IPA_HW_v4_7 to GSI_VER_2_7. Its rmnet_ipa.c has ipa3_wwan_ioctl, RMNET_IOCTL_EXTENDED, CAP_NET_ADMIN, GET_EP_PAIR and both real IPA_CLIENT_APPS_WAN_CONS/PROD mappings, checking IPA_EP_NOT_ALLOCATED before reporting producer/consumer pipe numbers. It calls the exported ipa_get_ep_mapping wrapper (rather than the TouchGrass internal ipa3_get_ep_mapping); matching return semantics require validation against the integrated core. There are no made-up pipe IDs.

## Gates and current status

1. **A0 source audit (implemented here):** pinned vendor source and exact TG hardware tree checked against the composed GKI tree; output P470-A0-IPA-SOURCE-DEPENDENCY-AUDIT.json. Reports missing provider headers, source and SSR contracts. Leaves IPA3 and GSI disabled and does not claim a flashed image.
2. **A0 powered (NOT YET DONE):** integrate actual IPA/GSI translation units and UAPI; compile/link with a separate opt-in override, no wave3 default change; add clocks, five bandwidth paths, SMMU CB, IRQ and DT. Defer probe on missing SCM; check SMMU suspend/retention P460B interplay before testing with a modem.
3. **A1 firmware (NOT YET DONE):** investigate Phase263 legacy /dev/subsys_lagoon_ipa_fws and OFFLINING status. Select exactly one PAS 0xF owner (legacy PIL or verified 5.10 PAS). Load actual lagoon_ipa_fws and verify GSI firmware readiness; no second PAS owner.
4. **A2 modem stability (NOT YET DONE):** bound-gate P468 modem start until real IPA READY or retain P469b behavior on failure; QMI/SMP2P, real WAN endpoints, char nodes, ipacm, SSR notifications and cleanup, zero EP_PAIR failures, zero ps_rm:0xb9 for at least 5 minutes. Protect SensorService/QRTR even on failed IPA startup.
5. **B data calls (DEFERRED):** Qualcomm rmnet_core/ctl or a proven compatible replacement, rmnet_data* virtual links, NAT/CT, ODL, WDI/WLAN, tethering.

The reported modem ps_rm:0xb9 after RILD's EP_PAIR failures is strong prioritization evidence, not proof that IPA fixes every modem assert. GPS/QMI working in a short interval does not establish IPA readiness.

## On-device read-only collection

scripts/470_modem_ipa_health_android.sh, executed in a root Android shell, prints remoteproc status, IPA/wwan nodes, rmnet_ipa0, ipacm and fault counts. With --watch it samples for five minutes. No IMEI, EFS, NV or modem partitions are read or modified.

P470 source-audit success alone **does not authorize flashing**. A P470 image must contain linked real hardware drivers, pass strict build/DT/SSR gates and meet on-device acceptance independently.
