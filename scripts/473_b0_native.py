#!/usr/bin/env python3
"""P473 B0 native TG Bluetooth power + SE1 HS-UART 5.10 compilation attempt.

No fake /dev nodes, no BT firmware, no SE9 hijack. Refuse missing genuine
provider API rather than silently building no-op hardware shims.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

TG_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
UART_PATH = Path("drivers/tty/serial/msm_geni_serial_p473.c")
BT_PATH = Path("drivers/bluetooth/bluetooth_power_p473.c")
HEADER = Path("include/linux/bluetooth-power.h")
GENI = Path("include/linux/qcom-geni-se.h")
MARK = "P473_B0_TG_NATIVE_SE1_BTPOWER_V1"
UK = '''
config P473_TG_HSUART
\tbool "P473 TG GENI HS UART SE1 only, experimental"
\tdepends on SERIAL_CORE && OF && PM
\tdefault n
\thelp
\t  Real downstream TG HS UART, not an upstream ttyMSM symlink.
'''
BK = '''
config P473_TG_BTPOWER
\tbool "P473 TG WCN3990 Bluetooth power, experimental"
\tdepends on OF && GPIOLIB && REGULATOR
\tdefault n
\thelp
\t  Real TG Bluetooth ioctl power controller, no powered-on default.
'''

def replace_once(s, old, new, name):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"P473 {name}: TG anchor count={n}")
    return s.replace(old, new, 1)

def patch_uart(s):
    if MARK in s:
        raise RuntimeError("P473 UART already patched")
    anchor = ('\tuport->private_data = (void *)drv;\n'
              '\tplatform_set_drvdata(pdev, dev_port);\n'
              '\tif (is_console) {')
    new = r'''	/* P473_B0_TG_NATIVE_SE1_BTPOWER_V1
	 * Read-only hardware mode gate on live SE1 after resources_on;
	 * never access clock-gated MMIO, never bind GSI-only hardware.
	 */
	if (!is_console && uport->mapbase == 0x884000) {
		u32 fifo_disable;
		int off_rc;

		if (line != 0 || dev_port->wakeup_irq <= 0 ||
		    dev_port->wakeup_byte != 0xFD) {
			ret = -ENODEV;
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe bad wake/alias rc=%d\n", ret);
			goto exit_wakeup_unregister;
		}
		ret = se_geni_resources_on(&dev_port->serial_rsc);
		if (ret) {
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe resources_on rc=%d\n", ret);
			goto exit_wakeup_unregister;
		}
		fifo_disable = geni_read_reg_nolog(uport->membase,
						  GENI_IF_FIFO_DISABLE_RO);
		off_rc = se_geni_resources_off(&dev_port->serial_rsc);
		if (off_rc) {
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe resources_off rc=%d\n", off_rc);
			ret = off_rc;
			goto exit_wakeup_unregister;
		}
		ret = fifo_disable & FIFO_IF_DISABLE ? -ENODEV : 0;
		dev_info(&pdev->dev,
			 "P473 UART ttyHS0 probe mode=%s raw=0x%08x rc=%d\n",
			 ret ? "GSI" : "FIFO", fifo_disable, ret);
		if (ret)
			goto exit_wakeup_unregister;
	}

	uport->private_data = (void *)drv;
	platform_set_drvdata(pdev, dev_port);
	if (is_console) {'''
    return replace_once(s, anchor, new, "UART before tty registration")

def stage(root, tg):
    rev = subprocess.check_output(
        ["git", "-C", str(tg), "rev-parse", "HEAD"], text=True).strip()
    if rev != TG_SHA:
        raise RuntimeError("P473 TG source revision mismatch " + rev)
    for p in (UART_PATH, BT_PATH):
        if (root / p).exists():
            raise RuntimeError(f"P473 potential duplicate owner: {p}")
    bt_hdr = tg / HEADER
    if not bt_hdr.is_file():
        raise RuntimeError("P473 canonical TG BT ioctl ABI header absent")
    if (root / HEADER).exists():
        if (root / HEADER).read_bytes() != bt_hdr.read_bytes():
            raise RuntimeError("P473 unsafe existing BT power header differs from TG")
    else:
        shutil.copy2(bt_hdr, root / HEADER)

    target_geni = root / GENI
    tg_geni = tg / GENI
    if not target_geni.is_file() or not tg_geni.is_file():
        raise RuntimeError("P473 missing real QCOM GENI 5.10 header/provider")
    # In particular, don't overwrite the 5.10 header used by existing
    # UART/I2C/SPI controllers; failing compile is better than corrupting them.
    for needed in ("GENI_IF_FIFO_DISABLE_RO", "FIFO_IF_DISABLE",
                   "struct se_geni_rsc", "se_geni_resources_on",
                   "se_geni_resources_off"):
        if needed not in target_geni.read_text():
            raise RuntimeError("P473 real 5.10 GENI API missing " + needed)

    src = tg / "drivers/tty/serial/msm_geni_serial.c"
    bt = tg / "drivers/bluetooth/bluetooth-power.c"
    if not src.is_file() or not bt.is_file():
        raise RuntimeError("P473 TG driver input absent")
    for x in ("ttyHS", "qcom,msm-geni-serial-hs", "qcom,wakeup-byte"):
        if x not in src.read_text():
            raise RuntimeError("P473 actual TG HS UART source drift " + x)
    for x in ("BT_CMD_PWR_CTRL", "BT_CMD_CHIPSET_VERS",
              "BT_CMD_CHECK_SW_CTRL", "BT_CMD_GETVAL_POWER_SRCS",
              ".compat_ioctl = bt_ioctl"):
        if x not in bt.read_text():
            raise RuntimeError("P473 actual TG btpower source drift " + x)

    (root / UART_PATH).write_text(patch_uart(src.read_text()))
    (root / BT_PATH).write_bytes(bt.read_bytes())
    um, uk = root / "drivers/tty/serial/Makefile", root / "drivers/tty/serial/Kconfig"
    bm, bk = root / "drivers/bluetooth/Makefile", root / "drivers/bluetooth/Kconfig"
    for file in (um, uk, bm, bk):
        if not file.is_file():
            raise RuntimeError("P473 missing native Kbuild file " + str(file))
    um.write_text(um.read_text() + "\n# " + MARK +
                  "\nobj-$(CONFIG_P473_TG_HSUART) += msm_geni_serial_p473.o\n")
    uk.write_text(uk.read_text() + "\n" + UK)
    bm.write_text(bm.read_text() +
                  "\nobj-$(CONFIG_P473_TG_BTPOWER) += bluetooth_power_p473.o\n")
    bk.write_text(bk.read_text() + "\n" + BK)

def check(root):
    u = (root / UART_PATH).read_text()
    bt = (root / BT_PATH).read_text()
    if MARK not in u or not (root / HEADER).is_file():
        raise RuntimeError("P473 native sources absent")
    if not u.index("GENI_IF_FIFO_DISABLE_RO") < u.index("ret = uart_add_one_port(drv, uport);"):
        raise RuntimeError("P473 ttyHS registered before FIFO gate")
    for token in ("se_geni_resources_on(&dev_port->serial_rsc)",
                  "se_geni_resources_off(&dev_port->serial_rsc)",
                  "P473 UART ttyHS0 probe mode=%s",
                  "qcom,msm-geni-serial-hs"):
        if token not in u:
            raise RuntimeError("P473 UART native gate missing " + token)
    for token in ("BT_CMD_PWR_CTRL", "BT_CMD_CHIPSET_VERS",
                  "BT_CMD_GETVAL_POWER_SRCS", '"btpower"'):
        if token not in bt:
            raise RuntimeError("P473 BT native ioctl missing " + token)
    for path, expected in (
        ("drivers/tty/serial/Makefile", "obj-$(CONFIG_P473_TG_HSUART)"),
        ("drivers/bluetooth/Makefile", "obj-$(CONFIG_P473_TG_BTPOWER)"),
        ("drivers/tty/serial/Kconfig", "config P473_TG_HSUART"),
        ("drivers/bluetooth/Kconfig", "config P473_TG_BTPOWER")
    ):
        if expected not in (root / path).read_text():
            raise RuntimeError("P473 native Kbuild missing " + expected)
    return {
        "phase": "P473-B0-NATIVE",
        "tg_revision": TG_SHA,
        "btpower_real_tg": True, "uart_real_tg": True,
        "se1_fifo_guard_before_tty": True,
        "se9_console_untouched": True,
        "requested_device_nodes": ["/dev/btpower", "/dev/ttyHS0"],
        "kernel_image_link": "PENDING",
        "actual_se1_fifo_mode": "PENDING HARDWARE",
        "bluetooth_firmware": "B1 NOT IN SCOPE",
        "flash_authorized": False
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--tg", type=Path)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    o = p.parse_args()
    if not o.check_only:
        if not o.tg:
            p.error("--tg required for staging")
        stage(o.root, o.tg)
    rec = check(o.root)
    if o.report:
        o.report.parent.mkdir(parents=True, exist_ok=True)
        o.report.write_text(json.dumps(rec, indent=2, sort_keys=True)+"\n")
    print("P473 B0 genuine TG Bluetooth and SE1 HS UART native sources staged; link pending")

if __name__ == "__main__":
    main()
