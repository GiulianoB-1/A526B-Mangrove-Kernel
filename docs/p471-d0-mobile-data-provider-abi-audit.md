# P471 D0: mobile-data source ABI and provider audit (no flash)

Pinned inputs:
- TG: [6bf351bdf18bdb228db79e66f14a7a9c0178e5d7](https://github.com/micr0softstore/samsung_android_kernel_a52xq/tree/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7)
- Mangrove A6g: [e8b7668eff8f257cca9a050ddd0db922a04885a2](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/commit/e8b7668eff8f257cca9a050ddd0db922a04885a2)
- dataipa (unchanged): [c560cc3c2840fb0ebc55ceef5b27549c66143637](https://github.com/CodeLinaro-mirror/la_platform_vendor_opensource_dataipa/tree/c560cc3c2840fb0ebc55ceef5b27549c66143637)
- datarmnet (D1 candidate): [1b77da7ced0ac746fca93df5c6c01528164ab6cc](https://github.com/CodeLinaro-mirror/la_platform_vendor_qcom_opensource_datarmnet/tree/1b77da7ced0ac746fca93df5c6c01528164ab6cc)

## D0 findings and evidence

| Item | Result | Evidence |
| --- | --- | --- |
| TG rmnet | **CONFIRMED** built-in: `CONFIG_RMNET=y`. | TG `arch/arm64/configs/a52xq_defconfig`, also `vendor/a52xq_eur_open_defconfig` |
| TG IPA | **CONFIRMED** `CONFIG_GSI=y CONFIG_IPA3=y CONFIG_RMNET_IPA3=y`. | Same TG config |
| TG QMI/DPC | **CONFIRMED** `CONFIG_QCOM_QMI_RMNET=y CONFIG_QCOM_QMI_DFC=y CONFIG_QCOM_QMI_POWER_COLLAPSE=y`. | Same TG config |
| TG perf/shs | **CONFIRMED** `CONFIG_RMNET_PERF=y CONFIG_RMNET_SHS=y` but these are separate optional acceleration code paths; not fundamental to MAP mux link creation. | TG `drivers/net/ethernet/qualcomm/rmnet/Makefile` |
| TG rmnet_ctl | **CONFIRMED** `# CONFIG_RMNET_CTL is not set`. Thus a failed `rmnet_ctl` modprobe does not *by itself* prove a fatal missing boot requirement. | TG `arch/arm64/configs/a52xq_defconfig`, `drivers/soc/qcom/rmnet_ctl/Kconfig` requires MHI_BUS |
| TG logical rmnet | **CONFIRMED** `rtnl_link_ops.kind="rmnet"`, `IFLA_LINK` physical parent, `IFLA_RMNET_MUX_ID` u16, `IFLA_RMNET_FLAGS` struct, vendor `IFLA_RMNET_DFC_QOS` and `IFLA_RMNET_UL_AGG_PARAMS`. | TG `drivers/net/ethernet/qualcomm/rmnet/rmnet_config.c` lines 43-61, 170-228 |
| TG runtime | **USER-PROVIDED** `rmnet_data0..10@rmnet_ipa0`; exact per-link mux IDs not provided. Do not infer mux IDs from the names. | P471 workorder TG_ABI_20261030_151137 |
| Mangrove existing | **CONFIRMED source** A6g adds IPA3/GSI/RMNET_IPA3 built-in after the base GKI Image; base `CONFIG_RMNET` and rtnl feature state must be audited from rebuilt final `.config`, NOT assumed from source. | `.github/workflows/446wx-build.yml` stage P470-A3 |
| 5.10 Qualcomm datarmnet | **CONFIRMED** donor Kbuild defines `rmnet_core.o` (including QMI/WDA/DFC) and `rmnet_ctl.o` (IPA transport). Donor core accepts the TG extension attributes. | `core/Kbuild`, `core/rmnet_config.c` lines 58-74, 181-234, 489-498; `core/rmnet_ctl_ipa.c` |
| IPA netdev IOCTL | **CONFIRMED** `ndo_do_ioctl=ipa3_wwan_ioctl` handles `RMNET_IOCTL_EXTENDED`, `GET_EP_PAIR`, `ADD_MUX_CHANNEL`, ingress and egress QMAP format. | dataipa `rmnet_ipa.c` lines 1759-2189 |
| IPA character IOCTL | **CONFIRMED** `/dev/wwan_ioctl` path implements `WAN_IOC_ADD_FLT_RULE` and others. Separate from netdev ioctl. | dataipa `rmnet_ipa_fd_ioctl.c` lines 67-505 |
| IPA data pipes | **CONFIRMED** `handle3_ingress_format` configures APPS_WAN_CONS or COAL_CONS and `ipa_setup_sys_pipe`; `handle3_egress_format` configures APPS_WAN_PROD. | dataipa `rmnet_ipa.c` lines 1484-1590, 1620-1710 |
| Data pipes risk | **SUSPECTED until first packets**: `ipa_setup_sys_pipe` can fail on SSR, endpoint mismatch, GSI setup, SMMU mapping, irq/NAPI; WDA data-format mismatch can yield silent no-traffic. | P471 workorder; actual rc/IOVA must come from D1 trace |
| Optional modules | **CONFIRMED** existing vendor `rmnet_perf` and `rmnet_shs` fail `module_layout` mismatch: not usable across this kernel ABI. Do not fake success, suppress or force load. | P471 hardware workorder |
| DPM/WDA | **SOURCE** dataipa negotiates QMAP flags on ingress/egress; datarmnet donor includes `wda_qmi.c`. **RUNTIME UNVERIFIED** exact modem negotiated v4/v5. | dataipa `rmnet_ipa.c` and datarmnet `core/wda_qmi.c` |
| Vendor userspace netmgr contract | **NOT VERIFIED** without A6g netmgr logcat/strace and supplied ROM refpack. Specifically unknown exact netlink attr masks, ioctl sequences/rc, fatality of `rmnet_core/ctl` modprobe, and `/dev/rmnet_ctrl` policy. | Await user-provided runtime evidence |
| SELinux | **UNCHANGED**. No permissive mode or new /dev node. Verify existing policies for `/dev/wwan_ioctl`, optional `/dev/rmnet_ctrl`, /sys/class/net path from ROM report. | P471 workorder |

## Recommendation and D1 scope

**Choose the pinned Qualcomm datarmnet core**, with IPA-aware ctl built-in as the separately requested D1 experiment. Its rtnetlink extension attrs (`IFLA_RMNET_DFC_QOS`, `IFLA_RMNET_UL_AGG_PARAMS`) match TG; upstream ACK rmnet might reject vendor attrs. The pinned 5.10 datarmnet QMI/WDA/DFC integration is closer to the working 5.10 dataipa than a blind 4.19 transplant. Build as a separate, opt-in source transform replacing only the rmnet provider, never link two `kind="rmnet"` handlers simultaneously.

**Safety**: separate perf, shs and offload stay out; no userspace modprobe spoofing, no SELinux permissive, no modem autostart or forced success, no EFS writes. A6f, A6g and the P469b fallback remain unchanged. An absent /dev/rmnet_ctrl is not proof that data can never work (TG has CONFIG_RMNET_CTL disabled).

## D2: on-phone proof needed

Record `ip -d link show rmnet_data0`, `ip addr show rmnet_data0`, `ip route`, netmgr/RILD logcat showing data-format and rtnetlink return codes, `/sys/class/net/rmnet_ipa0/statistics/{rx_packets,tx_packets,rx_bytes,tx_bytes}`, `dmesg | grep -E 'P471|ipa|gsi|rmnet|SMMU|IOMMU'`. Require a real IP, ping/browsing, and 10-minute stability before accepting P471.


D1b addendum: see docs/p471-d1b-tg-flags-netfilter-addendum.md. TG SHS/PERF and QMI/DFC are built-in, stale vendor module-load errors also happen on TG. The pinned 5.10 donor contains DFC/QMI but not SHS/PERF. The new CI audit records both Qualcomm flag patterns and an exact TG-vs-5.10 netfilter delta. Do not claim hardware data success or enable IPA autostart from a source-only result.
