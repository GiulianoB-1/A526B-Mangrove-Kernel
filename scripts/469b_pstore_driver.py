#!/usr/bin/env python3
"""P469b: prove initcall/driver binding and avoid duplicate legacy dummy.

The authoritative run #598 already built CONFIG_PSTORE_RAM=y and compiled
fs/pstore/ram.o. Its boot command line additionally supplies ramoops.mem_size,
which makes postcore_initcall(ramoops_init) register a *second* legacy dummy
device even though the live DT has ramoops@B1B00000. Prefer that exact
reserved-memory DT node. Do not allocate/create another RAM resource.
"""
import argparse
import json
from pathlib import Path

FILE = Path("fs/pstore/ram.c")


def once(s, old, new, what):
    count = s.count(old)
    if count != 1:
        raise RuntimeError("P469b pstore %s anchor count=%d" % (what,count))
    return s.replace(old,new,1)


def patch(s):
    if "P469B PSTORE INIT" in s:
        raise RuntimeError("P469b pstore already applied")
    if "P461 PSTORE RAMOOPS_PROBE" not in s:
        raise RuntimeError("P461 ramoops probe marker missing")
    s=once(s,
        "static void __init ramoops_register_dummy(void)\n"
        "{\n"
        "\tstruct ramoops_platform_data pdata;\n",
        "static void __init ramoops_register_dummy(void)\n"
        "{\n"
        "\tstruct ramoops_platform_data pdata;\n"
        "\tstruct device_node *np;\n"
        "\tstruct resource res;\n"
        "\n"
        "\t/* P469B PSTORE DT_OWNER: CONFIG_PSTORE_RAM=y in P469, but\n"
        "\t * ramoops.mem_size on the boot cmdline otherwise creates\n"
        "\t * a competing platform device. Keep the DT authoritative.\n"
        "\t * The node must really be the exact live ECC48 region.\n"
        "\t */\n"
        "\tfor_each_compatible_node(np, NULL, \"ramoops\") {\n"
        "\t\tif (!of_device_is_available(np) || !np->parent ||\n"
        "\t\t    !of_node_name_eq(np->parent, \"reserved-memory\") ||\n"
        "\t\t    of_address_to_resource(np, 0, &res) ||\n"
        "\t\t    res.start != 0xb1b00000ULL ||\n"
        "\t\t    resource_size(&res) != 0x00100000)\n"
        "\t\t\tcontinue;\n"
        "\t\tpr_info(\"P469B PSTORE DT_OWNER node=%pOF legacy_dummy=skipped\\n\", np);\n"
        "\t\tof_node_put(np);\n"
        "\t\treturn;\n"
        "\t}\n",
        "dummy policy")
    s=once(s,
        "\tramoops_register_dummy();\n"
        "\tret = platform_driver_register(&ramoops_driver);\n",
        "\tpr_info(\"P469B PSTORE INIT enter ramoops_driver_register\\n\");\n"
        "\tramoops_register_dummy();\n"
        "\tret = platform_driver_register(&ramoops_driver);\n"
        "\tpr_info(\"P469B PSTORE INIT register_rc=%d\\n\", ret);\n",
        "initcall trace")
    if "postcore_initcall(ramoops_init);" not in s:
        raise RuntimeError("missing postcore_initcall; no silent fallback")
    return s


def check(s):
    for token in ("P469B PSTORE INIT enter", "P469B PSTORE INIT register_rc=",
                  "P469B PSTORE DT_OWNER", "postcore_initcall(ramoops_init);",
                  "P461 PSTORE RAMOOPS_PROBE", 'of_device_is_available(np)',
                  "resource_size(&res) != 0x00100000"):
        if token not in s:
            raise RuntimeError("P469b pstore missing %s" % token)
    return {"baseline_run":40871537827,"config":"CONFIG_PSTORE_RAM=y already built",
            "driver":"fs/pstore/ram.o built-in",
            "init":"postcore_initcall(ramoops_init) instrumented",
            "probe":"P461 instrumentation preserved",
            "legacy_dummy":"skip if the exact available reserved-memory DT region exists",
            "preserve_ecc":48,"duplicate_memory":False}


def main():
    pa=argparse.ArgumentParser()
    pa.add_argument("--root",type=Path,required=True)
    pa.add_argument("--check-only",action="store_true")
    pa.add_argument("--report",type=Path)
    a=pa.parse_args()
    f=a.root/FILE
    s=f.read_text()
    if not a.check_only:
        s=patch(s)
        f.write_text(s)
    result=check(s)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("P469B PSTORE SOURCE PASS "+json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
