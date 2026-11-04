#!/usr/bin/env python3
"""P473 B2: SE1-only dev->pins state substitution and TG SW_CTRL diagnostics.
Applied after B0 and B1, never changes qcom-geni-se.c or P471.
"""
import argparse
import json
from pathlib import Path

UART = Path("drivers/tty/serial/qcom_geni_serial.c")
CORE = Path("drivers/soc/qcom/qcom-geni-se.c")
BT = Path("drivers/bluetooth/bluetooth_power_p473.c")
MARK = "P473_B2_SE1_DEVPINS_ACTIVE_V1"

def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise RuntimeError("P473 B2 anchor drift %s count=%d" % (label, n))
    return s.replace(old, new, 1)

def stage(root):
    u = (root / UART).read_text()
    c = (root / CORE).read_text()
    b = (root / BT).read_text()
    if MARK in u:
        raise RuntimeError("P473 B2 already applied")
    for call in ("pinctrl_pm_select_default_state(se->dev)",
                 "pinctrl_pm_select_sleep_state(se->dev)"):
        if c.count(call) != 1:
            raise RuntimeError("P473 B2 upstream GENI core semantic drift: " + call)
    if "P473_B1_SE1_WRAPPER0_BUS_ALIAS_FAILCLOSED_V1" not in u:
        raise RuntimeError("P473 B1 missing")
    u = once(u, "#include <linux/qcom-geni-se.h>\n",
             "#include <linux/qcom-geni-se.h>\n"
             "#include <linux/pinctrl/consumer.h>\n"
             "#include <linux/pinctrl/devinfo.h>\n", "pinctrl includes")
    anchor = "\tctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);"
    inject = """\t/* P473_B2_SE1_DEVPINS_ACTIVE_V1: SE1 0x884000 only.
\t * The upstream GENI resource helper selects dev->pins->default_state.
\t * Samsung DT names the QUP01 mux 'active', while 'default' parks GPIO.
\t * Substitute the driver's core-owned state before the first B0 gate.
\t */
\tif (!dev->pins || !dev->pins->p || !dev->pins->sleep_state) {
\t\tdev_err(dev, "P473 B2 PINCTRL missing core/sleep state rc=-19\\n");
\t\treturn -ENODEV;
\t}
\t{
\t\tstruct pinctrl_state *act;
\t\tact = pinctrl_lookup_state(dev->pins->p, "active");
\t\tif (IS_ERR(act)) {
\t\t\tret = PTR_ERR(act);
\t\t\tdev_err(dev, "P473 B2 PINCTRL active lookup rc=%d\\n", ret);
\t\t\treturn ret;
\t\t}
\t\tdev->pins->default_state = act;
\t\tdev_info(dev, "P473 B2 PINCTRL default->active(qup01) rc=0\\n");
\t}
"""
    u = once(u, anchor, inject + anchor, "B1 SE1 helper before bus init")
    gpio = ('\t\tbt_power_pdata->bt_gpio_sw_ctrl  =\n'
            '\t\t\tof_get_named_gpio(pdev->dev.of_node,\n'
            '\t\t\t\t\t\t"qca,bt-sw-ctrl-gpio",  0);\n')
    addition = ('\t\tdev_info(&pdev->dev, "P473 B2 BTPOWER sw_ctrl gpio=%d\\n",\n'
                '\t\t\t bt_power_pdata->bt_gpio_sw_ctrl);\n'
                '\t\tif (bt_power_pdata->bt_gpio_sw_ctrl == -EPROBE_DEFER) {\n'
                '\t\t\trc = -EPROBE_DEFER;\n'
                '\t\t\tgoto err;\n'
                '\t\t}\n')
    b = once(b, gpio, gpio + addition, "pinned TG SW_CTRL")
    if "ret = bt_power_populate_dt_pinfo(pdev);" not in b or "goto free_pdata;" not in b:
        raise RuntimeError("P473 B2 TG probe defer propagation anchor drift")
    (root / UART).write_text(u)
    (root / BT).write_text(b)

def check(root):
    u = (root / UART).read_text()
    c = (root / CORE).read_text()
    b = (root / BT).read_text()
    for call in ("pinctrl_pm_select_default_state(se->dev)",
                 "pinctrl_pm_select_sleep_state(se->dev)"):
        if c.count(call) != 1:
            raise RuntimeError("P473 B2 GENI core PM contract missing")
    if u.count(MARK) != 1 or u.count("dev->pins->default_state = act;") != 1:
        raise RuntimeError("P473 B2 pinctrl state substitution missing")
    helper = u[u.index("static int p473_b1_prepare_se1("):
               u.index("static int qcom_geni_serial_probe(")]
    if not (helper.index("port->uport.mapbase != 0x884000") <
            helper.index("dev->pins->default_state = act;") <
            helper.index("ctx = devm_kzalloc(")):
        raise RuntimeError("P473 B2 SE1 pinctrl ordering drift")
    if b.count("P473 B2 BTPOWER sw_ctrl gpio=%d") != 1 or b.count("rc = -EPROBE_DEFER;") < 1:
        raise RuntimeError("P473 B2 SW_CTRL diagnostics missing")
    return {"phase":"P473-B2-SE1-DEVPINS", "core_edited":False,
            "pinctrl":"SE1 default_state replaced by active; sleep unchanged",
            "btpower":"SW_CTRL errno logged, EPROBE_DEFER propagated",
            "flash_authorized":False, "runtime":"UNVERIFIED"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    if not a.check_only:
        stage(a.root)
    result = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(result, indent=2) + "\n")
    print("P473 B2 SE1 dev-pins active and SW_CTRL defer SOURCE PASS; runtime UNVERIFIED")

if __name__ == "__main__":
    main()
