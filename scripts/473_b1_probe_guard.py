#!/usr/bin/env python3
"""P473 B1 hardware-safety amendments to already-staged P473 B0 native sources.

This is applied AFTER 473_b0_native.py in the pinned GKI native build.
It never modifies the DT, P471 IPA/rmnet/P469B, or the SE9 console.
All source anchors must match exactly or staging aborts.
"""
import argparse
import json
import re
from pathlib import Path

UART = Path("drivers/tty/serial/qcom_geni_serial.c")
BT = Path("drivers/bluetooth/bluetooth_power_p473.c")
MARK = "P473_B1_SE1_WRAPPER0_BUS_ALIAS_FAILCLOSED_V1"

INCLUDES = """#include <linux/msm-bus.h> /* P473 B1: legacy RPMh interconnect */\n#include <linux/of_address.h>\n"""

HELPER = r'''
/* P473_B1_SE1_WRAPPER0_BUS_ALIAS_FAILCLOSED_V1
 * SE1 is a child of /soc, not a child of upstream geni-se.  The Samsung
 * qcom,wrapper-core phandle resolves to wrapper0 at 0x8c0000, whose
 * platform device has no upstream struct geni_wrapper drvdata.
 * Locally supply the two AHB clocks using the SE1 node; never dereference
 * dev_get_drvdata(/soc).  No global wrapper-provider changes.
 */
struct p473_b1_ctx {
	struct geni_wrapper wrapper;
	struct msm_bus_scale_pdata pdata;
	struct msm_bus_paths paths[2];
	struct msm_bus_vectors vectors[2][2];
	u32 bus_client;
	bool bus_active;
};

static void p473_b1_bus_release(void *arg)
{
	struct p473_b1_ctx *ctx = arg;

	if (!ctx->bus_client)
		return;
	if (ctx->bus_active)
		msm_bus_scale_client_update_request(ctx->bus_client, 0);
	msm_bus_scale_unregister_client(ctx->bus_client);
	ctx->bus_client = 0;
	ctx->bus_active = false;
}

static int p473_b1_prepare_se1(struct platform_device *pdev,
			      struct qcom_geni_serial_port *port)
{
	struct device *dev = &pdev->dev;
	struct device_node *node;
	struct resource wr;
	struct p473_b1_ctx *ctx;
	u32 ids[4], paths;
	int ret, i;

	/* Only the SE1 reg-matched caller is permitted. */
	if (port->uport.mapbase != 0x884000)
		return -ENODEV;

	node = of_parse_phandle(dev->of_node, "qcom,wrapper-core", 0);
	if (!node) {
		dev_err(dev, "P473 B1 wrapper missing phandle rc=-19\n");
		return -ENODEV;
	}
	ret = of_address_to_resource(node, 0, &wr);
	if (ret || wr.start != 0x8c0000 ||
	    !of_device_is_compatible(node, "qcom,qupv3-geni-se")) {
		dev_err(dev, "P473 B1 wrapper wrong base/compatible rc=-19\n");
		of_node_put(node);
		return -ENODEV;
	}
	ret = of_property_read_u32(node, "qcom,msm-bus,num-paths", &paths);
	if (ret || paths != 2 ||
	    of_property_count_u32_elems(node,
					"qcom,msm-bus,vectors-bus-ids") != 4) {
		dev_err(dev, "P473 B1 wrapper bus schema rc=-19\n");
		of_node_put(node);
		return -ENODEV;
	}
	ret = of_property_read_u32_array(node,
			"qcom,msm-bus,vectors-bus-ids", ids, 4);
	of_node_put(node);
	if (ret || ids[0] != 0xb0 || ids[1] != 0x337 ||
	    ids[2] != 0x97 || ids[3] != 0x200) {
		dev_err(dev, "P473 B1 wrapper bus IDs mismatch rc=-19\n");
		return -ENODEV;
	}
	ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->wrapper.dev = dev;
	ctx->wrapper.ahb_clks[0].id = "m-ahb";
	ctx->wrapper.ahb_clks[1].id = "s-ahb";
	ret = devm_clk_bulk_get(dev, 2, ctx->wrapper.ahb_clks);
	if (ret) {
		dev_err(dev, "P473 B1 wrapper m-ahb/s-ahb rc=%d\n", ret);
		return ret;
	}
	/* Mapping the phandle resource does not claim its ownership or
	 * access any register.  GENI helper functions may need base.
	 */
	ctx->wrapper.base = devm_ioremap(dev, wr.start, resource_size(&wr));
	if (!ctx->wrapper.base)
		return -ENOMEM;
	for (i = 0; i < 2; i++) {
		ctx->paths[i].num_paths = 2;
		ctx->paths[i].vectors = ctx->vectors[i];
		ctx->vectors[i][0].src = ids[0];
		ctx->vectors[i][0].dst = ids[1];
		ctx->vectors[i][1].src = ids[2];
		ctx->vectors[i][1].dst = ids[3];
	}
	/* P446Z parity: core 960kB/s, memory 1kB/s (MSM bus B/s). */
	ctx->vectors[1][0].ab = 960000ULL;
	ctx->vectors[1][0].ib = 960000ULL;
	ctx->vectors[1][1].ab = 1000ULL;
	ctx->vectors[1][1].ib = 1000ULL;
	ctx->pdata.usecase = ctx->paths;
	ctx->pdata.num_usecases = 2;
	ctx->pdata.name = "P473_SE1_QUP_CORE0";
	ctx->pdata.active_only = 0;
	ctx->bus_client = msm_bus_scale_register_client(&ctx->pdata);
	if (!ctx->bus_client) {
		dev_err(dev, "P473 B1 bus register deferred rc=-517\n");
		return -EPROBE_DEFER;
	}
	ret = devm_add_action_or_reset(dev, p473_b1_bus_release, ctx);
	if (ret)
		return ret;
	ret = msm_bus_scale_client_update_request(ctx->bus_client, 1);
	dev_info(dev,
		 "P473 B1 BUS_VOTE wrapper=0x8c0000 core=176->823 mem=151->512 active=1 rc=%d\n",
		 ret);
	if (ret)
		return ret; /* devres releases the client on probe failure */
	ctx->bus_active = true;
	port->se.wrapper = &ctx->wrapper;
	dev_info(dev, "P473 B1 WRAPPER synthetic=1 se-clk=SE1 m-ahb=1 s-ahb=1 rc=0\n");
	return 0;
}

'''

def replace_once(src, old, new, why):
    count = src.count(old)
    if count != 1:
        raise RuntimeError("P473 B1 anchor drift: " + why + " count=" + str(count))
    return src.replace(old, new, 1)

def patch_uart(s):
    if MARK in s:
        raise RuntimeError("P473 B1 already applied")
    if "P473_B0_NATIVE_SE1_FIFO_GUARD_V2" not in s:
        raise RuntimeError("P473 B0 UART gate missing")
    s = replace_once(s, "#include <linux/qcom-geni-se.h>\n",
                     "#include <linux/qcom-geni-se.h>\n" + INCLUDES,
                     "UART include")
    # 'res' is already declared by the pinned probe. Before any port
    # allocation, override the absent SE1 hsuart alias by REG, not by DT.
    entry = "\tport = get_port_from_line(line, console);"
    if entry not in s:
        entry = "\tport = get_port_from_line(line, data->console);"
    if entry not in s:
        raise RuntimeError("P473 B1 missing line selection anchor")
    reg_gate = r'''	/* P473 B1: Samsung compatible also matches SE9.  Reject it
	 * before accessing any resources, and never edit DT aliases.
	 */
	if (of_device_is_compatible(pdev->dev.of_node,
				    "qcom,msm-geni-serial-hs")) {
		res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
		if (!res || res->start != 0x884000) {
			dev_info(&pdev->dev,
				 "P473 B1 SE1_ONLY reject non-SE1 reg rc=-19\n");
			return -ENODEV;
		}
		line = 0; /* real ttyHS0, independent of hsuart aliases */
		dev_info(&pdev->dev,
			 "P473 B1 SE1_ONLY reg=0x884000 line=0 rc=0\n");
	}

'''
    s = replace_once(s, entry, reg_gate + entry, "SE1 line registration")
    # The B0 source intentionally supplies a real upstream GENI UART.
    # Its parent is /soc; upstream parent driver-data is NULL.
    old = "\tport->se.wrapper = dev_get_drvdata(pdev->dev.parent);"
    new = r'''	if (of_device_is_compatible(pdev->dev.of_node,
				    "qcom,msm-geni-serial-hs")) {
		/* Before GENI clock/ICC/MMIO setup, bind the wrapper context
		 * and perform the mandatory legacy RPMh msm-bus vote.
		 */
		struct resource *b1res = platform_get_resource(pdev,
							       IORESOURCE_MEM, 0);
		if (!b1res || b1res->start != 0x884000)
			return -ENODEV;
		uport->mapbase = b1res->start;
		ret = p473_b1_prepare_se1(pdev, port);
		if (ret)
			return ret;
	} else {
		port->se.wrapper = dev_get_drvdata(pdev->dev.parent);
	}'''
    s = replace_once(s, old, new, "null /soc wrapper")
    # SE1's clock is "se-clk"; the OPP helper must not re-select "se".
    # No SE1 OPP table is needed for the guarded FIFO probe.
    pat = (r'\tret = devm_pm_opp_set_clkname\(&pdev->dev, "se"\);'
           r'\s*if \(ret\)\s*return ret;\s*'
           r'/\* OPP table is optional \*/\s*'
           r'ret = devm_pm_opp_of_add_table\(&pdev->dev\);'
           r'\s*if \(ret && ret != -ENODEV\) \{'
           r'[^{}]*?'
           r'\n\t\}')
    matches = list(re.finditer(pat, s))
    if len(matches) != 1:
        raise RuntimeError("P473 B1 OPP anchor count " + str(len(matches)))
    m = matches[0]
    s = s[:m.start()] + (
        '\tif (!of_device_is_compatible(pdev->dev.of_node,\n'
        '\t\t\t\t\t"qcom,msm-geni-serial-hs")) {\n' +
        '\n'.join('\t' + l if l else '' for l in m.group().splitlines()) +
        '\n\t} else {\n'
        '\t\tdev_info(&pdev->dev, "P473 B1 SE1 OPP skipped se-clk used rc=0\\n");\n'
        '\t}\n'
    ) + s[m.end():]
    s = replace_once(s, "static int qcom_geni_serial_probe(",
                     HELPER + "static int qcom_geni_serial_probe(",
                     "native helper")
    return s

def patch_bt(s):
    start = s.index("static long bt_ioctl(")
    end = s.index("\nstatic struct platform_driver bt_power_driver", start)
    fn = s[start:end]
    if fn.count("return ret;") != 1:
        raise RuntimeError("P473 B1 BTPOWER ioctl return anchor drift")
    fn = fn.replace("return -EINVAL;", "ret = -EINVAL; goto p473_b1_ioctl_out;")
    fn = replace_once(fn, "\treturn ret;",
                      '\tp473_b1_ioctl_out:\n'
                      '\tpr_info("P473 BTPOWER ioctl=%x rc=%d\\n", cmd, ret);\n'
                      '\treturn ret;', "BTPOWER ioctl completion")
    # No ioctl returns may bypass the single trace.
    if re.search(r'\breturn\b', fn[:fn.index("p473_b1_ioctl_out:")]):
        raise RuntimeError("P473 B1 BTPOWER early return bypasses trace")
    return s[:start] + fn + s[end:]

def rate_limit(src):
    # Change only diagnostic statements carrying existing phase labels.
    out = src
    for phase in ("P446M", "P461 FASTRPC"):
        out = re.sub(r'\bpr_warn\("' + phase,
                     'pr_warn_ratelimited("' + phase, out)
        out = re.sub(r'\bpr_info\("' + phase,
                     'pr_info_ratelimited("' + phase, out)
    return out

def stage(root):
    uart = root / UART
    bt = root / BT
    if not uart.is_file() or not bt.is_file():
        raise RuntimeError("P473 B1 sources missing")
    patched_uart = patch_uart(uart.read_text())
    patched_bt = patch_bt(bt.read_text())
    # Rate-limit only exact phase-labelled instrumentation in known
    # subsystems. Avoid modifying driver behavior or global printk config.
    targets = []
    for folder in ("drivers/clk/qcom", "drivers/gpu/drm/msm",
                   "drivers/char/adsprpc", "drivers/misc",
                   "drivers/soc/qcom"):
        base = root / folder
        if not base.is_dir():
            continue
        for p in base.rglob("*.c"):
            if p in (uart, bt):
                continue
            c = p.read_text(errors="replace")
            if 'P446M' not in c and 'P461 FASTRPC' not in c:
                continue
            new = rate_limit(c)
            if new != c:
                targets.append((p, new))
    # No file is modified until all mandatory source gates pass.
    uart.write_text(patched_uart)
    bt.write_text(patched_bt)
    for p, c in targets:
        p.write_text(c)
    print("P473 B1 rate-limited diagnostic files: " + str(len(targets)))

def check(root):
    u = (root / UART).read_text()
    b = (root / BT).read_text()
    for marker in (MARK, "P473 B1 SE1_ONLY reg=0x884000 line=0",
                   "P473 B1 SE1_ONLY reject non-SE1",
                   "P473 B1 WRAPPER synthetic=1",
                   "P473 B1 BUS_VOTE wrapper=0x8c0000",
                   "P473 B1 SE1 OPP skipped"):
        if marker not in u:
            raise RuntimeError("P473 B1 UART marker missing " + marker)
    if 'P473 BTPOWER ioctl=%x rc=%d' not in b:
        raise RuntimeError("P473 B1 BTPOWER marker missing")
    probe = u[u.index("static int qcom_geni_serial_probe("):
              u.index("static int qcom_geni_serial_remove(")]
    if not (probe.index("P473 B1 SE1_ONLY") <
            probe.index("get_port_from_line(") <
            probe.index("p473_b1_prepare_se1(") <
            probe.index("P473_B0_NATIVE_SE1_FIFO_GUARD_V2") <
            probe.index("uart_add_one_port(")):
        raise RuntimeError("P473 B1 SE1 probe ordering unsafe")
    if "port->se.wrapper = dev_get_drvdata(pdev->dev.parent);" not in probe:
        raise RuntimeError("P473 B1 non-SE1 upstream path changed")
    return {"phase": "P473-B1-SOURCE-GUARDS", "SE1_reg": "0x884000",
            "SE9": "reject before TTY selection", "wrapper": "DT phandle wrapper0 0x8c0000",
            "bus_ids": ["0xb0", "0x337", "0x97", "0x200"],
            "bus": "P446Z style vote active before MMIO",
            "HAL_TIOCPMGET_PUT_ACT": "TG implemented; upstream lacks; not emulated",
            "runtime": "UNVERIFIED", "flash_authorized": False}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    if not args.check_only:
        stage(args.root)
    data = check(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(data, indent=2) + "\n")
    print("P473 B1: SE1 alias/wrapper0/msm-bus fail-closed SOURCE PASS; runtime UNVERIFIED")

if __name__ == "__main__":
    main()
