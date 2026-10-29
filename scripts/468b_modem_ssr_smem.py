#!/usr/bin/env python3
"""P468b: let the 5.10 MSS PAS exclusively own the SMP2P 'stop' state.

The TG SSR /dev/subsys_modem compatibility descriptor is registered against
the real 5.10 PAS OF node. That node supplies 'stop' (not 'qcom,force-stop').
TG's __get_smem_state() erroneously treats the missing legacy alias as fatal
-ENODATA. Bypass the legacy lookup ONLY for the modem descriptor and let
subsys_parse_devicetree() consume -ENOENT as it already does.

Must run AFTER scripts/468_mss_ril_compat_source.py. No DTB modification.
"""
import argparse
import json
from pathlib import Path

SSR = Path("drivers/a52_pil/subsystem_restart.c")
SKIP = "P468B MSS SSR SMEM_SKIP"
REGISTER = "P468B MSS SUBSYS REGISTER"


def replace_once(s, old, new, label):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"P468b {label}: anchor count={count}, expected 1")
    return s.replace(old, new, 1)


def segment(s, start, finish, label):
    if s.count(start) != 1 or s.count(finish) != 1:
        raise RuntimeError(f"P468b {label}: function boundaries drifted")
    i = s.index(start)
    j = s.index(finish, i + len(start))
    return i, j, s[i:j]


def patch(s):
    if SKIP in s or REGISTER in s:
        raise RuntimeError("P468b already applied")
    if "P468 MSS SUBSYS STATE" not in s or "P468 MSS SUBSYS STOP" not in s:
        raise RuntimeError("P468b requires the successful P468 legacy SSR patch")

    begin, end, getter = segment(
        s,
        "static int __get_smem_state(struct subsys_desc *desc, const char *prop,",
        "static int subsys_parse_devicetree(struct subsys_desc *desc)",
        "__get_smem_state",
    )
    if "desc->state = qcom_smem_state_get(desc->dev, prop, smem_bit);" not in getter:
        raise RuntimeError("P468b TG smem lookup provider differs from reference")
    hook = "\tstruct device_node *dnode = desc->dev->of_node;\n\n"
    replacement = r'''	struct device_node *dnode = desc->dev->of_node;

	/* P468B MSS SSR SMEM_SKIP: 5.10 q6v5 PAS owns the SMP2P 'stop'
	 * state. This legacy wrapper must not request qcom,force-stop.
	 * -ENOENT is explicitly nonfatal to subsys_parse_devicetree().
	 * No desc->state or smem_bit writes occur in this modem path.
	 */
	if (!strcmp(desc->name, "modem")) {
		dev_info(desc->dev,
			 "P468B MSS SSR SMEM_SKIP name=modem owner=q6v5_pas rc=-ENOENT\n");
		return -ENOENT;
	}

'''
    getter = replace_once(getter, hook, replacement, "modem-only smem bypass")
    s = s[:begin] + getter + s[end:]

    begin, end, register = segment(
        s,
        "struct subsys_device *subsys_register(struct subsys_desc *desc)",
        "EXPORT_SYMBOL(subsys_register);",
        "subsys_register",
    )
    # Log success only after cdev_add, all OF parser work, notifiers and
    # IRQ setup have succeeded. The SSR subsystem owns the actual dev_t.
    tail = "\treturn subsys;\nerr_setup_irqs:"
    added = r'''	/* P468B MSS SUBSYS REGISTER: log the *actual* allocated dev_t,
	 * only after successful char device and full SSR registration.
	 */
	if (!strcmp(desc->name, "modem"))
		dev_info(desc->dev,
			 "P468B MSS SUBSYS REGISTER name=modem dev=subsys_modem major=%u minor=%u rc=0\n",
			 MAJOR(subsys->dev_no), MINOR(subsys->dev_no));
	return subsys;
err_setup_irqs:'''
    register = replace_once(register, tail, added, "successful registration log")
    s = s[:begin] + register + s[end:]
    return s


def check(s):
    if s.count(SKIP) < 1 or s.count(REGISTER) < 1:
        raise RuntimeError("P468b missing diagnostics")
    _, _, getter = segment(
        s,
        "static int __get_smem_state(struct subsys_desc *desc, const char *prop,",
        "static int subsys_parse_devicetree(struct subsys_desc *desc)",
        "__get_smem_state",
    )
    if not (getter.index('if (!strcmp(desc->name, "modem"))') <
            getter.index('return -ENOENT;') <
            getter.index("desc->state = qcom_smem_state_get")):
        raise RuntimeError("P468b modem-only skip no longer precedes legacy acquisition")
    if getter.count("desc->state = qcom_smem_state_get") != 1:
        raise RuntimeError("P468b legacy smem provider mutated")
    _, _, parse = segment(
        s,
        "static int subsys_parse_devicetree(struct subsys_desc *desc)",
        "static int subsys_setup_irqs(struct subsys_device *subsys)",
        "subsys_parse_devicetree",
    )
    if ('ret = __get_smem_state(desc, "qcom,force-stop", &desc->force_stop_bit);'
            not in parse or 'if (ret && ret != -ENOENT)' not in parse):
        raise RuntimeError("P468b legacy parser -ENOENT contract drifted")
    _, _, reg = segment(
        s,
        "struct subsys_device *subsys_register(struct subsys_desc *desc)",
        "EXPORT_SYMBOL(subsys_register);",
        "subsys_register",
    )
    pos = reg.index("P468B MSS SUBSYS REGISTER")
    if not (reg.index("ret = subsys_char_device_add(subsys);") < pos and
            reg.index("ret = subsys_setup_irqs(subsys);") < pos and
            pos < reg.index("\treturn subsys;")):
        raise RuntimeError("P468b registration diagnostics before full success")
    for token in ("MAJOR(subsys->dev_no)", "MINOR(subsys->dev_no)", "rc=0"):
        if token not in reg:
            raise RuntimeError("P468b missing major/minor/rc reporting: " + token)
    return {
        "phase": "P468b", "ssr_device": "/dev/subsys_modem",
        "modem_only_skip": True, "legacy_smem_request": "qcom,force-stop",
        "modem_skip_errno": "-ENOENT", "pas_smem_owner": "5.10 q6v5",
        "pas_smem_state_name": "stop", "changes_to_dtb": False,
        "other_ssr_devices": "original TG logic", "registration_diagnostics":
        "actual major/minor, rc=0 after complete subsystem registration",
        "P468_pas_and_rproc": "unchanged",
    }


def self_test():
    base = """/* P468 MSS SUBSYS STATE */
/* P468 MSS SUBSYS STOP */
static int __get_smem_state(struct subsys_desc *desc, const char *prop,
                           int *smem_bit)
{
\tstruct device_node *dnode = desc->dev->of_node;

\tif (of_find_property(dnode, "qcom,smem-states", NULL)) {
\t\tdesc->state = qcom_smem_state_get(desc->dev, prop, smem_bit);
\t}
\treturn -ENOENT;
}
static int subsys_parse_devicetree(struct subsys_desc *desc)
{
\tret = __get_smem_state(desc, "qcom,force-stop", &desc->force_stop_bit);
\tif (ret && ret != -ENOENT)
\t\treturn ret;
}
static int subsys_setup_irqs(struct subsys_device *subsys)
{
}
struct subsys_device *subsys_register(struct subsys_desc *desc)
{
\tret = subsys_char_device_add(subsys);
\tret = subsys_setup_irqs(subsys);
\tif (ret < 0)
\t\tgoto err_setup_irqs;
\treturn subsys;
err_setup_irqs:
\treturn ERR_PTR(ret);
}
EXPORT_SYMBOL(subsys_register);
"""
    result = patch(base)
    assert "P468B MSS SSR SMEM_SKIP" in result
    assert "P468B MSS SUBSYS REGISTER" in result
    check(result)
    try:
        patch(result)
    except RuntimeError:
        pass
    else:
        raise AssertionError("P468b should fail closed on repeated application")
    print("P468b SELF-TEST PASS: exclusive MSS smem state; other TG SSR untouched")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.root:
        p.error("--root is required unless --self-test")
    path = args.root / SSR
    code = path.read_text()
    if not args.check_only:
        code = patch(code)
        path.write_text(code)
    data = check(code)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("P468b MODEM SSR OWNERSHIP SOURCE PASS", json.dumps(data, sort_keys=True))


if __name__ == "__main__":
    main()
