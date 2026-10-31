# P473 D0: TG btpower + SE1 GENI HS-UART, userspace QTI BT HAL ABI

**State: SOURCE AUDIT ONLY. No driver staged, no image built, no flash.**
Independent sibling of P472, based exactly on P471 mobile-data hardware working commit `4ea703414a90078232fbdece6f185df311dde8db`.
TG pin: `micr0softstore/samsung_android_kernel_a52xq@6bf351bdf18bdb228db79e66f14a7a9c0178e5d7`.
BT power and SE1 are **not** IPA, MSS, CDSP or ADSP dependencies for basic pairing. All P471 data code is out of scope.

## D0 btpower ioctl ABI (source inspected)

**Canonical reference is TG `drivers/bluetooth/bluetooth-power.c` and `include/linux/bluetooth-power.h`, not an assumed `drivers/bluetooth/btpower.c`.**

| TG number | Symbol | Exact TG semantics |
| --- | --- | --- |
| `0xbfac` | `BT_CMD_SLIM_TEST` | Optional btfm SLIM hardware test when configured. Do not invoke during D0. |
| `0xbfad` | `BT_CMD_PWR_CTRL` | `(int)arg` = requested power state; calls real `bluetooth_power` only if state changed, caches state only on success. |
| `0xbfae` | `BT_CMD_CHIPSET_VERS` | `(int)arg` sets `soc_id` (nonzero); certain IDs also disable ASD regulator. **Potential side effect; not a read-only getter.** |
| `0xbfb0` | `BT_CMD_CHECK_SW_CTRL` | Reads SW_CTRL GPIO, with direction input setup; errors for invalid/missing GPIO. |
| `0xbfb1` | `BT_CMD_GETVAL_POWER_SRCS` | Reads GPIO and regulator states; status data is maintained by TG driver. Validate userspace readback behavior before relying on it. |

TG reserves `0xbfaf` for a 5.4-era command, but it is **not handled** by the inspected `bt_ioctl()`. Unknown commands return `-EINVAL`. `get_chipset_version()` is a kernel function, not evidence of a matching GET ioctl. `bt_dev_fops` gives both `unlocked_ioctl` and `compat_ioctl` to `bt_ioctl`; `device_create(..., "btpower")` creates the exact devnode. TG `CONFIG_MSM_BT_POWER=y`. The char-device major is allocated by `register_chrdev(0, "bt", ...)`: do NOT hardcode a major for `/dev/btpower`.

**Provider recommendation:** preserve the **TG ioctl ABI and DT power sequencing**; use a Qualcomm 5.10 btpower donor only after pinning its commit and comparing exact ioctls, regulator names, error behavior, and ioctl compat behavior. No exact msm-5.10 donor revision or HAL binary is available in this audit, so donor parity is **NOT VERIFIED**. Do not invent aliases or report an unimplemented command as successful.

## D0 serial transport proof from TG

| Requirement | Evidence | Disposition |
| --- | --- | --- |
| HAL expects `/dev/ttyHS0` | Workorder TG runtime: `hci_attach_dev`, owner bluetooth:bluetooth, major 235 minor 0. `drivers/tty/serial/msm_geni_serial.c:3836-3841` explicitly registers HS uart driver `.dev_name="ttyHS"`. | Downstream `msm_geni_serial` is the correct ABI route. The **TG runtime major 235 is observed, not guaranteed after a re-port**. Verify actual major/minor and label; do not substitute `ttyMSM0`. |
| SE1 hardware and driver | `lagoon-qupv3.dtsi:94-114`: `qcom,qup_uart@884000`, `qcom,msm-geni-serial-hs`, clocks `GCC_QUPV3_WRAP0_S1_CLK`, 4-wire pinctrl, `qcom,wrapper-core=<&qupv3_0>`. | Map this node into **live merged** Mangrove FDT, not a fabricated overlay. |
| Wake protocol | `lagoon-qupv3.dtsi:109-112` second IRQ `<&tlmm 64 IRQ_TYPE_LEVEL_HIGH>`, `qcom,wakeup-byte=<0xFD>`. `msm_geni_serial.c:2197-2217` handles wake-byte insertion/interrupt, `:3382-3388` parses property and `:3433-3434` obtains IRQ. | Port real wake path and PM/clock unwind, not only tty naming. Verify IRQ level and suspend/resume on real hardware. |
| Enabled state | TG `lagoon.dtsi:3871-3874` sets `&qupv3_se1_4uart` `status="ok"`. | TG active, Mangrove final FDT not proven in D0. |
| SE9 isolation | `lagoon-qupv3.dtsi:293-307`: **SE9** @0x98c000 is `qcom,msm-geni-console`, wrapper 1, already status `ok`; `lagoon.dtsi:3866-3869` enables it. Work order identifies debug device `/dev/ttyHS8`. | Explicit SE1-only port and DT edits. Never take over SE9 console or overwrite UART aliases. |
| FIFO vs GSI | SE1 is on QUP wrapper 0. Source `msm_geni_serial.c` supports GENI mode selection; **no observed SE1 `GENI_IF_FIFO_DISABLE_RO` register value** supplied. | **OPEN HARDWARE GATE**. Read SE1 register safely before choosing FIFO or GSI path. If GSI-only, implement/check actual QUP0 DMA owner, IOMMU and channel setup. Do not assume FIFO just because TG source supports it. |
| Alternative upstream UART | Upstream `qcom_geni_serial` uses a different tty naming and does not by itself prove the TG HS wake/attach contract. | **Reject simple `ttyMSM` rename/symlink**. Exact downstream HS driver, with 5.10 API adaptation and ownership guards, is preferred. |

## Power DT, verified TG declarations, not live readback

`lagoon.dtsi:537-554`: `bt_wcn3990` compatible `qca,wcn3990` with SW_CTRL `TLMM GPIO69`; `bt-vdd-io=L11A` 1.7-1.9V, `bt-vdd-core=L2E` 1.304V, `bt-vdd-pa=L10E` 3.0-3.312V, `bt-vdd-xtal=L7A` 1.7-1.9V. These are **nominal DT constraints**, not measured voltages and not approval to energize rails in D0. The exact active power supplies, clocks and GPIO ownership must be confirmed from the live merged FDT and regulator state.

## QTI userspace contract and data gaps

Work order identifies `vendor.bluetooth-1-0-qti`, `android.hardware.bluetooth@1.0-service-qti` and property `persist.vendor.qcom.bluetooth.soc=cherokee`. Userspace opens `/dev/btpower` and `/dev/ttyHS0`; do **not** add a competing kernel `hci_qca` registration. TG permissions:
- `/dev/btpower`: bluetooth:system, `vendor_bt_device`, mode 0660.
- `/dev/ttyHS0`: bluetooth:bluetooth, `hci_attach_dev`, mode 0660.
- `/dev/ttyHS8`: debug UART, **not** BT.

**NOT VERIFIED in D0:** the exact HAL `open`, baud-rate and hardware-flow-control transitions; firmware filenames/paths among `apbtfw*.tlv` and `apnv*`; read-only BD-address source; vendor init RC and group setup; actual SE1 FIFO-disable register; merged FDT regulator parent handles; exact 5.10 donor code revision. Require the vendor refpack, HAL logs/strings, init scripts and live FDT evidence rather than guessing. Never write BT address storage or force firmware success.

## B0 source/build gate, after D0 is resolved

1. Stage TG-equivalent `bluetooth-power.c` plus matching `bluetooth-power.h` with verified 5.10 API adaptation. Keep true errno, compat ioctl and regulator sequencing; `P473 BTPOWER ioctl=%x rc=` **only for actual calls**. No dummy device nodes.
2. Port the **downstream HS** GENI UART for **SE1 only**, keep `ttyHS0` and existing SE9 console. Fail closed on unresolved wrapper/pinctrl/clock/IRQ, return `-EPROBE_DEFER` on missing providers. Probe `GENI_IF_FIFO_DISABLE_RO`, log `P473 UART ttyHS0 probe mode=FIFO|GSI rc=` only after a real hardware read.
3. Verify `/dev/btpower` and `/dev/ttyHS0` owner/group, major/minor **and SELinux contexts** using `ls -lZ`; no permissive SELinux. Do not power on the controller as part of D0.
4. Separate B1 firmware/HCI reset/pairing from B0 node/probe checks. B2 sleep/wake follows B1. BT audio must wait for P472 speaker-route readiness.
5. Before B0, verify required exact 5.10 donor pin, HAL userspace ABI evidence, actual merged FDT, SE1 mode and absence of duplicate serial/BT providers. One built Image only after source/compile gates pass.

## TG reference links

- [btpower ioctl implementation](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/drivers/bluetooth/bluetooth-power.c#L1118-L1239)
- [Exact BT ioctl numbers](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/include/linux/bluetooth-power.h#L92-L105)
- [SE1 and SE9 DT](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/arch/arm64/boot/dts/vendor/qcom/lagoon-qupv3.dtsi#L94-L114)
- [HS UART ttyHS and match](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/drivers/tty/serial/msm_geni_serial.c#L3825-L3841)

**D0 audit decision:** TG btpower ioctl semantics and downstream `msm_geni_serial` are the correct baseline contracts. Hardware SE1 mode, live DT and exact 5.10 donor + HAL parity remain **OPEN**. No flash authorized by this source-only report.
