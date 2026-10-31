#!/usr/bin/env python3
"""P473 B0 native 5.10 SE1 HS-UART binding + TG Bluetooth power.

The original TG UART implementation depends on a 4.19 se_geni_rsc and
downstream qcom-geni-se resource provider. Reusing its private ABI
against GKI 5.10 is incorrect. Instead adapt the ACTUAL pinned 5.10
GENI UART driver with a hardware mode gate. It already supplies ttyHS.
Only the legacy SE1 compatible is added. No second UART owner or
global upstream GENI header replacement; SE9 console is untouched.
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

TG_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
UART = Path("drivers/tty/serial/qcom_geni_serial.c")
BT = Path("drivers/bluetooth/bluetooth_power_p473.c")
HEADER = Path("include/linux/bluetooth-power.h")
MARK = "P473_B0_NATIVE_SE1_FIFO_GUARD_V2"
BT_KCONFIG = '''
config P473_TG_BTPOWER
\tbool "P473 TG WCN3990 Bluetooth power, experimental"
\tdepends on OF && GPIOLIB && REGULATOR
\tdefault n
\thelp
\t  Real TG Bluetooth power ioctl driver, with default power off.
'''

def replace_once(s, old, new, why):
    n = s.count(old)
    if n != 1:
        raise RuntimeError("P473 native " + why + ": anchor count " + str(n))
    return s.replace(old, new, 1)

def patch_uart(s):
    if MARK in s:
        raise RuntimeError("P473 duplicate source stage")
    # Don't extend the generic compat: only bind Samsung's actual SE1 HS.
    match = re.search(r'(^\s*\{\s*\.compatible\s*=\s*"qcom,geni-uart"\s*,?\s*\},)', s, re.M)
    if not match or s.count('"qcom,geni-uart"') != 1:
        raise RuntimeError("P473 5.10 UART compatible drift: no single generic UART entry")
    if '"qcom,msm-geni-serial-hs"' in s:
        raise RuntimeError("P473 existing Samsung compatible owner, cannot duplicate")
    s = s[:match.end()] + '\n\t{ .compatible = "qcom,msm-geni-serial-hs", }, /* P473 SE1 only */' + s[match.end():]

    # Do not request/remap the MMIO resource twice after the early probe
    # hardware-mode read, which would otherwise return EBUSY in config_port.
    pat = r'(?P<ind>^\s*)uport->membase\s*=\s*devm_platform_ioremap_resource\(pdev,\s*0\);'
    m = re.search(pat, s, re.M)
    if not m or s.count("devm_platform_ioremap_resource(pdev, 0)") != 1:
        raise RuntimeError("P473 native UART MMIO reservation function changed")
    indent = m.group('ind')
    new = (indent + "if (!uport->membase)\n" + indent +
           "\tuport->membase = devm_platform_ioremap_resource(pdev, 0);")
    s = s[:m.start()] + new + s[m.end():]

    # Inject at a point after device, clocks, interconnect, IRQ, OPP and
    # line setup are valid but strictly before uart_add_one_port().
    anchor = "\tport->private_data.drv = drv;\n\tuport->private_data = &port->private_data;"
    gate = r'''	/* P473_B0_NATIVE_SE1_FIFO_GUARD_V2.
	 * DO NOT bind the legacy Samsung UART to GSI-only SE1.
	 * In 5.10, GENI_IF_DISABLE_RO is register offset 0x64.
	 * Make no writes to SE1; balance GENI clocks and ICC votes.
	 */
	if (of_device_is_compatible(pdev->dev.of_node,
				    "qcom,msm-geni-serial-hs")) {
		u32 wake_byte;
		u32 fifo_disable;
		int off_rc, icc_rc;

		if (line != 0 || uport->mapbase != 0x884000 ||
		    port->wakeup_irq <= 0 ||
		    of_property_read_u32(pdev->dev.of_node,
					 "qcom,wakeup-byte", &wake_byte) ||
		    wake_byte != 0xfd) {
			ret = -ENODEV;
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe invalid SE1 DT/IRQ/alias rc=%d\n",
				ret);
			goto err;
		}
		uport->membase = devm_platform_ioremap_resource(pdev, 0);
		if (IS_ERR(uport->membase)) {
			ret = PTR_ERR(uport->membase);
			uport->membase = NULL;
			goto err;
		}
		port->se.base = uport->membase;

		ret = geni_icc_enable(&port->se);
		if (ret) {
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe icc_on rc=%d\n", ret);
			goto err;
		}
		ret = geni_se_resources_on(&port->se);
		if (ret) {
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe resources_on rc=%d\n", ret);
			geni_icc_disable(&port->se);
			goto err;
		}
		/* TG GENI_IF_FIFO_DISABLE_RO == 0x64; bit 0 = GSI-only. */
		fifo_disable = readl_relaxed(uport->membase + 0x64);
		off_rc = geni_se_resources_off(&port->se);
		icc_rc = geni_icc_disable(&port->se);
		ret = off_rc ? off_rc : icc_rc;
		if (!ret && (fifo_disable & BIT(0)))
			ret = -ENODEV;
		dev_info(&pdev->dev,
			 "P473 UART ttyHS0 probe mode=%s raw=0x%08x resources_off=%d icc_off=%d rc=%d\n",
			 (fifo_disable & BIT(0)) ? "GSI" : "FIFO",
			 fifo_disable, off_rc, icc_rc, ret);
		if (ret)
			goto err;
		dev_info(&pdev->dev,
			 "P473 UART ttyHS0 ready source=real-5.10-uart wake_irq=%d wake_byte=0x%02x rc=0\n",
			 port->wakeup_irq, wake_byte);
	}

'''
    s = replace_once(s, anchor, gate + anchor, "UART pre-registration gate")
    p = s.index("static int qcom_geni_serial_probe(")
    nextfn = s.index("static int qcom_geni_serial_remove(", p)
    seg = s[p:nextfn]
    if not seg.index("P473_B0_NATIVE_SE1_FIFO_GUARD_V2") < seg.index("uart_add_one_port("):
        raise RuntimeError("P473 native hardware gate is after TTY registration")
    if '"ttyHS"' not in s:
        raise RuntimeError("P473 5.10 real ttyHS UART device name missing")
    return s

def stage(root, tg):
    rev = subprocess.check_output(["git", "-C", str(tg), "rev-parse", "HEAD"], text=True).strip()
    if rev != TG_SHA:
        raise RuntimeError("P473 TG source revision mismatch: " + rev)
    uart = root / UART
    if not uart.is_file():
        raise RuntimeError("P473 GKI 5.10 UART provider absent")
    btsrc = tg / "drivers/bluetooth/bluetooth-power.c"
    hdr = tg / HEADER
    if not btsrc.is_file() or not hdr.is_file():
        raise RuntimeError("P473 pinned TG btpower ABI missing")
    if (root / BT).exists():
        raise RuntimeError("P473 duplicate BTPOWER provider")
    if (root / HEADER).exists():
        if (root / HEADER).read_bytes() != hdr.read_bytes():
            raise RuntimeError("P473 BT power ioctl header already differs from pinned TG")
    else:
        shutil.copy2(hdr, root / HEADER)
    bt = btsrc.read_text()
    for name in ("BT_CMD_PWR_CTRL", "BT_CMD_CHIPSET_VERS",
                 "BT_CMD_GETVAL_POWER_SRCS", ".compat_ioctl = bt_ioctl"):
        if name not in bt:
            raise RuntimeError("P473 TG ioctl ABI drift " + name)

    uart.write_text(patch_uart(uart.read_text()))
    (root / BT).write_text(bt)
    km, kc = root / "drivers/bluetooth/Makefile", root / "drivers/bluetooth/Kconfig"
    if "config P473_TG_BTPOWER" in kc.read_text():
        raise RuntimeError("P473 double Kconfig stage")
    km.write_text(km.read_text() + "\n# " + MARK +
                  "\nobj-$(CONFIG_P473_TG_BTPOWER) += bluetooth_power_p473.o\n")
    kc.write_text(kc.read_text() + "\n" + BT_KCONFIG)

def check(root):
    s = (root / UART).read_text()
    bt = (root / BT).read_text()
    a = s.index("static int qcom_geni_serial_probe(")
    b = s.index("static int qcom_geni_serial_remove(", a)
    seg = s[a:b]
    if s.count(MARK) != 1:
        raise RuntimeError("P473 native mode gate missing or duplicated")
    if not seg.index(MARK) < seg.index("uart_add_one_port("):
        raise RuntimeError("P473 native TTY created before FIFO gate")
    for name in ("geni_icc_enable(&port->se)", "geni_se_resources_on(&port->se)",
                 "geni_se_resources_off(&port->se)", "geni_icc_disable(&port->se)",
                 "readl_relaxed(uport->membase + 0x64)",
                 "P473 UART ttyHS0 probe mode=%s", "wake_byte != 0xfd",
                 "P473 UART ttyHS0 ready"):
        if name not in seg:
            raise RuntimeError("P473 missing actual 5.10 hardware operation " + name)
    if 'dev_name = "ttyHS"' not in s or s.count('"qcom,msm-geni-serial-hs"') != 2:
        raise RuntimeError("P473 5.10 ttyHS or legacy DT binding not established")
    if "config P473_TG_BTPOWER" not in (root / "drivers/bluetooth/Kconfig").read_text():
        raise RuntimeError("P473 true Bluetooth power not configured")
    if "obj-$(CONFIG_P473_TG_BTPOWER) += bluetooth_power_p473.o" not in (root / "drivers/bluetooth/Makefile").read_text():
        raise RuntimeError("P473 Bluetooth power not linked")
    for name in ("BT_CMD_PWR_CTRL", "BT_CMD_CHIPSET_VERS",
                 "BT_CMD_GETVAL_POWER_SRCS", '"btpower"'):
        if name not in bt:
            raise RuntimeError("P473 real BTPOWER missing " + name)
    return {
        "phase": "P473-B0-NATIVE-V2", "TG_revision": TG_SHA,
        "btpower": "unchanged pinned TouchGrass vendor source",
        "uart": "actual 5.10 qcom_geni_serial.c plus SE1-only hardware gate",
        "owner": "existing ttyHS UART, no duplicate driver",
        "fifo_reg": "MMIO 0x64 bit0, read only after ICC/clock enable",
        "safety": "SE1 0x884000 alias0 wake byte 0xfd and wake IRQ required; SE9 untouched",
        "native_link": "PENDING",
        "HAL_runtime": "UNVERIFIED",
        "flash_authorized": False
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--tg", type=Path)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    if not args.check_only:
        if not args.tg:
            p.error("--tg required for staging")
        stage(args.root, args.tg)
    data = check(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(data, sort_keys=True, indent=2)+"\n")
    print("P473 B0: existing GKI ttyHS real UART + strict SE1 FIFO gate, TG btpower staged")

if __name__ == "__main__":
    main()
