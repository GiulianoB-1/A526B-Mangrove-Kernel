#!/usr/bin/env python3
"""P473 B3 SE1 only: real GENI clock-table selection, OPP/RFR diagnostics."""
import argparse
import json
from pathlib import Path

UART = Path("drivers/tty/serial/qcom_geni_serial.c")
CORE = Path("drivers/soc/qcom/qcom-geni-se.c")
HEADER = Path("include/linux/qcom-geni-se.h")
MARK = "P473_B3_SE1_CLOCK_TG_PARITY_V1"

def replace_once(s, a, b, label):
    n = s.count(a)
    if n != 1:
        raise RuntimeError("P473 B3 anchor %s count=%d" % (label, n))
    return s.replace(a, b, 1)

def stage(root):
    p = root / UART
    s = p.read_text()
    core = (root / CORE).read_text()
    h = (root / HEADER).read_text()
    if MARK in s:
        raise RuntimeError("P473 B3 already staged")
    for name in ("geni_se_clk_freq_match(", "geni_se_clk_tbl_get("):
        if name not in core or name not in h:
            raise RuntimeError("P473 B3 missing exported GENI clock helper " + name)
    if "P473_B2_SE1_DEVPINS_ACTIVE_V1" not in s:
        raise RuntimeError("P473 B2 required")
    head = "static void qcom_geni_serial_set_termios(struct uart_port *uport,"
    helper = """/* P473_B3_SE1_CLOCK_TG_PARITY_V1 */
static bool p473_b3_is_se1(struct uart_port *uport)
{
    return uport->dev && uport->dev->of_node &&
           of_device_is_compatible(uport->dev->of_node,
                                   "qcom,msm-geni-serial-hs") &&
           uport->mapbase == 0x884000;
}

static void p473_b3_log_clk_table(struct qcom_geni_serial_port *port,
                                  struct uart_port *uport)
{
    static bool logged;
    unsigned long *tbl;
    int n, i;

    if (logged)
        return;
    n = geni_se_clk_tbl_get(&port->se, &tbl);
    if (n <= 0) {
        dev_err(uport->dev, "P473 B3 CLK_TBL n=%d\\n", n);
        return;
    }
    logged = true;
    dev_info(uport->dev, "P473 B3 CLK_TBL n=%d\\n", n);
    for (i = 0; i < n; i++)
        dev_info(uport->dev, "P473 B3 CLK_TBL idx=%d rate=%lu\\n",
                 i, tbl[i]);
}

"""
    s = replace_once(s, head, helper + head, "set_termios declaration")
    start = s.index(head)
    end = s.find("\nstatic ", start + len(head))
    if end < 0:
        raise RuntimeError("P473 B3 cannot bound set_termios")
    body = s[start:end]
    body = replace_once(body, "\tu32 ver, sampling_rate;",
                        "\tu32 ver, sampling_rate;\n\tu32 p473_rfr_before = 0;\n\tint p473_opp_rc = 0;", "local declarations")
    body = replace_once(body, "\tqcom_geni_serial_stop_rx(uport);",
                        "\tif (p473_b3_is_se1(uport)) {\n"
                        "\t\tp473_b3_log_clk_table(port, uport);\n"
                        "\t\tp473_rfr_before = readl(uport->membase + SE_UART_MANUAL_RFR);\n"
                        "\t}\n\tqcom_geni_serial_stop_rx(uport);", "RFR pre stop_rx")
    old = "\tclk_rate = get_clk_div_rate(baud, sampling_rate, &clk_div);"
    replacement = """    if (p473_b3_is_se1(uport)) {
        unsigned long desired = (unsigned long)baud * sampling_rate;
        unsigned long src = 0;
        unsigned int idx = 0;
        long err_ppm = 0;
        int mrc;

        if (!desired) {
            dev_err(uport->dev, "P473 B3 BAUD desired=0 rc=-22\\n");
            clk_rate = 0;
        } else {
            mrc = geni_se_clk_freq_match(&port->se, desired,
                                         &idx, &src, false);
            if (mrc || !src) {
                dev_err(uport->dev,
                        "P473 B3 BAUD match rc=%d baud=%u\\n",
                        mrc, baud);
                clk_rate = 0;
            } else {
                clk_div = DIV_ROUND_UP(src, desired);
                if (!clk_div) {
                    clk_rate = 0;
                } else {
                    err_ppm = ((long)(src / clk_div) -
                               (long)desired) * 1000000L / (long)desired;
                    clk_rate = (err_ppm > 10000 || err_ppm < -10000) ?
                               0 : src;
                    if (!clk_rate)
                        dev_err(uport->dev,
                                "P473 B3 BAUD err_ppm=%ld too large rc=-22\\n",
                                err_ppm);
                }
                dev_info(uport->dev,
                         "P473 B3 BAUD baud=%u qup_ver=0x%x samp=%u desired=%lu src=%lu idx=%u div=%u err_ppm=%ld\\n",
                         baud, ver, sampling_rate, desired, src, idx,
                         clk_div, err_ppm);
            }
        }
    } else {
        clk_rate = get_clk_div_rate(baud, sampling_rate, &clk_div);
    }"""
    body = replace_once(body, old, replacement, "clock selection")
    body = replace_once(body, "\tdev_pm_opp_set_rate(uport->dev, clk_rate);",
                        "\tp473_opp_rc = dev_pm_opp_set_rate(uport->dev, clk_rate);\n"
                        "\tif (p473_b3_is_se1(uport)) {\n"
                        "\t\tdev_info(uport->dev, \"P473 B3 BAUD set opp_rc=%d actual=%lu\\n\",\n"
                        "\t\t\t p473_opp_rc, clk_get_rate(port->se.clk));\n"
                        "\t\tif (p473_opp_rc || clk_get_rate(port->se.clk) != clk_rate)\n"
                        "\t\t\tdev_err(uport->dev, \"P473 B3 BAUD OPP mismatch rc=%d\\n\", p473_opp_rc);\n"
                        "\t}", "OPP rc")
    body = replace_once(body, "out_restart_rx:\n\tqcom_geni_serial_start_rx(uport);",
                        "out_restart_rx:\n\tqcom_geni_serial_start_rx(uport);\n"
                        "\tif (p473_b3_is_se1(uport))\n"
                        "\t\tdev_info(uport->dev, \"P473 B3 RFR before=%x after=%x\\n\",\n"
                        "\t\t\t p473_rfr_before,\n"
                        "\t\t\t readl(uport->membase + SE_UART_MANUAL_RFR));",
                        "RFR post start_rx")
    s = s[:start] + body + s[end:]
    p.write_text(s)

def check(root):
    s = (root / UART).read_text()
    for marker in (MARK, "P473 B3 BAUD baud=%u",
                   "P473 B3 BAUD set opp_rc=%d actual=%lu",
                   "P473 B3 RFR before=%x after=%x"):
        if s.count(marker) != 1:
            raise RuntimeError("P473 B3 marker drift " + marker)
    if s.count("P473 B3 CLK_TBL n=%d") != 2:
        raise RuntimeError("P473 B3 clock table success/error marker drift")
    if "geni_se_clk_freq_match(&port->se, desired" not in s:
        raise RuntimeError("P473 B3 clock match absent")
    return {"phase":"P473-B3", "se1_only":True, "core_modified":False,
            "baud_clock":"geni_se_clk_freq_match", "opp_rc_logged":True,
            "rfr_report_only":True, "runtime":"UNVERIFIED",
            "flash_authorized":False}

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
    print("P473 B3 source contract PASS; native build and hardware unverified")

if __name__ == "__main__":
    main()
