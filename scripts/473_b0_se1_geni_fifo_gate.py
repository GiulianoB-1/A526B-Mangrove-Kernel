#!/usr/bin/env python3
"""P473 B0: guarded TG GENI UART SE1 read-only FIFO-mode probe.

Source adaptation to pinned TG msm_geni_serial.c. Does NOT implement the
full 5.10 driver port, missing regulator providers or Bluetooth firmware.
Never binds the SE9 console or powers Bluetooth.
"""
import argparse
import json
from pathlib import Path

TG_REL = "drivers/tty/serial/msm_geni_serial.c"
MARKER = "P473_B0_SE1_GENI_FIFO_RO_V1"
BEFORE = '''	uport->private_data = (void *)drv;
	platform_set_drvdata(pdev, dev_port);
	if (is_console) {'''
AFTER = r'''	/* P473_B0_SE1_GENI_FIFO_RO_V1: SE1 at 0x884000 only.
	 * Required before uart_add_one_port: no ttyHS0 on GSI-only SE1.
	 * Resource-on provides clocks and interconnect, resource-off is
	 * mandatory even when the read finds a GSI-only engine.
	 * Do not probe SE9 (console, 0x98c000) or any other QUP serial SE.
	 */
	if (!is_console && uport->mapbase == 0x884000) {
		u32 fifo_disable;
		int off_rc;

		if (line != 0 || dev_port->wakeup_irq <= 0 ||
		    dev_port->wakeup_byte != 0xFD) {
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe invalid line=%d wake_irq=%d wake_byte=0x%x rc=%d\n",
				line, dev_port->wakeup_irq,
				dev_port->wakeup_byte, -ENODEV);
			ret = -ENODEV;
			goto exit_wakeup_unregister;
		}
		ret = se_geni_resources_on(&dev_port->serial_rsc);
		if (ret) {
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe resources_on rc=%d\n",
				ret);
			goto exit_wakeup_unregister;
		}
		/* GENI_IF_FIFO_DISABLE_RO is 0x64, bit0=FIFO_IF_DISABLE.
		 * No writes to SE registers, no GSI enablement.
		 */
		fifo_disable = geni_read_reg_nolog(uport->membase,
						  GENI_IF_FIFO_DISABLE_RO);
		off_rc = se_geni_resources_off(&dev_port->serial_rsc);
		if (off_rc) {
			dev_err(&pdev->dev,
				"P473 UART ttyHS0 probe resources_off rc=%d raw=0x%x\n",
				off_rc, fifo_disable);
			ret = off_rc;
			goto exit_wakeup_unregister;
		}
		ret = (fifo_disable & FIFO_IF_DISABLE) ? -ENODEV : 0;
		dev_info(&pdev->dev,
			 "P473 UART ttyHS0 probe mode=%s raw=0x%08x rc=%d\n",
			 (fifo_disable & FIFO_IF_DISABLE) ? "GSI" : "FIFO",
			 fifo_disable, ret);
		if (ret)
			goto exit_wakeup_unregister;
	}

	uport->private_data = (void *)drv;
	platform_set_drvdata(pdev, dev_port);
	if (is_console) {'''

def once(s, old, new):
    hits = s.count(old)
    if hits != 1:
        raise RuntimeError(f"P473 TG SE1 probe anchor mismatch ({hits})")
    return s.replace(old, new, 1)

def patch(s):
    if MARKER in s or "P473 UART ttyHS0 probe" in s:
        raise RuntimeError("P473 already staged")
    for x in ('"qcom,msm-geni-serial-hs"',
              'GENI_UART_NR_PORTS', 'se_geni_resources_on(',
              'se_geni_resources_off(', 'geni_read_reg_nolog(',
              'ret = uart_add_one_port(drv, uport);',
              'goto exit_wakeup_unregister;',
              'msm_geni_serial_get_ver_info(uport);'):
        if x not in s:
            raise RuntimeError("P473 TG source drift: " + x)
    return once(s, BEFORE, AFTER)

def check(s):
    for key in (MARKER, 'uport->mapbase == 0x884000',
                'GENI_IF_FIFO_DISABLE_RO', 'FIFO_IF_DISABLE',
                'se_geni_resources_on(&dev_port->serial_rsc)',
                'se_geni_resources_off(&dev_port->serial_rsc)',
                'if (line != 0 || dev_port->wakeup_irq <= 0',
                'dev_port->wakeup_byte != 0xFD',
                '"P473 UART ttyHS0 probe mode=%s raw=0x%08x rc=%d',
                'goto exit_wakeup_unregister',
                'ret = uart_add_one_port(drv, uport);'):
        if key not in s:
            raise RuntimeError("P473 missing B0 guard: " + key)
    if not s.index('GENI_IF_FIFO_DISABLE_RO') < s.index('ret = uart_add_one_port(drv, uport);'):
        raise RuntimeError("P473 hardware read happens after tty registration")
    return {
        "phase": "P473-B0-SE1-RO-FIFO-GATE",
        "marker": MARKER,
        "se1_phys": "0x884000",
        "register_offset": "0x64",
        "fifo_disable_mask": "BIT(0)",
        "mode_detection": "REAL register read after resources_on",
        "gsi_only_behavior": "-ENODEV before tty registration",
        "uart_se9_modified": False,
        "btpower_driver_ported": False,
        "bluetooth_fw_downloaded": False,
        "runtime_verified": False,
        "flash_authorized": False,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tg", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    if args.check_only:
        s = args.out.read_text()
    else:
        s = patch((args.tg / TG_REL).read_text())
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(s)
    report = check(s)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("P473 B0 SE1 read-only FIFO/GSI fail-closed guard SOURCE PASS; 5.10 UART/BTPOWER not yet linked")

if __name__ == "__main__":
    main()
