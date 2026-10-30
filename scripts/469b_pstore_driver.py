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
    # The P82 direct A52 console occupies 0xB1B40000+0x40000, inside
    # the live 0xB1B00000+0x100000 ramoops area. Enabling both would
    # permit two independent persistent writers to corrupt each other.
    if "#define A52_DIAG_CONSOLE_PHYS 0xB1B40000ULL" not in s:
        raise RuntimeError("P469b unexpected A52 early diagnostic address")
    if "static int __init __maybe_unused ramoops_init(void)" not in s:
        raise RuntimeError("P469b expected intentionally disabled ramoops_init")
    if "/* A52 diagnostic build owns the console quarter directly. */" not in s:
        raise RuntimeError("P469b missing P82 diagnostic ownership comment")
    if "postcore_initcall(ramoops_init);" in s:
        raise RuntimeError("P469b refuses duplicate ramoops initcall")
    s=once(s,
        "int __init a52_persistent_diag_init(void)\n"
        "{\n"
        "\tstruct persistent_ram_ecc_info ecc = { };\n"
        "\tint prz_ret;\n",
        "int __init a52_persistent_diag_init(void)\n"
        "{\n"
        "\tstruct persistent_ram_ecc_info ecc = { };\n"
        "\tint prz_ret;\n"
        "\t/* P469B PSTORE EARLY_DIAG_DISABLED: A52's 256KiB console\n"
        "\t * is inside ramoops' 1MiB; do not map/clear/write it.\n"
        "\t * Kernel main.c calls this early, before ramoops initcall.\n"
        "\t */\n"
        "\tpr_info(\"P469B PSTORE EARLY_DIAG_DISABLED overlap=0xb1b40000+0x40000\\n\");\n"
        "\treturn 0;\n",
        "disable overlapping early A52 writer")
    s=once(s,
        "static int __init __maybe_unused ramoops_init(void)\n",
        "static int __init ramoops_init(void)\n",
        "restore normal ramoops init function")
    s=once(s,
        "/* A52 diagnostic build owns the console quarter directly. */\n",
        "/* P469B PSTORE: ramoops owns 0xB1B00000+1MiB exclusively.\n"
        " * A52 early breadcrumb allocations are disabled in P469b.\n"
        " */\n"
        "postcore_initcall(ramoops_init);\n",
        "register ramoops driver initcall")
    # This file uses OF helpers in the injected dummy-device guard.
    # The exact restored kernel can differ in existing include ordering.
    for header in ("#include <linux/of.h>", "#include <linux/of_address.h>"):
        if header not in s:
            i = s.find("#include ")
            if i < 0:
                raise RuntimeError("P469b pstore: no C include block")
            s = s[:i] + header + "\n" + s[i:]
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
    # The two unique anchors above establish the actual dummy registration
    # and platform-driver registration in the restored source. No dependency
    # on a particular init function name or initcall macro is justified.
    return s


def check(s):
    for token in ("P469B PSTORE INIT enter", "P469B PSTORE INIT register_rc=",
                  "P469B PSTORE DT_OWNER", "P461 PSTORE RAMOOPS_PROBE",
                  "platform_driver_register(&ramoops_driver);",
                  "postcore_initcall(ramoops_init);",
                  "P469B PSTORE EARLY_DIAG_DISABLED",
                  "#include <linux/of_address.h>", "#include <linux/of.h>",
                  'of_device_is_available(np)',
                  "resource_size(&res) != 0x00100000"):
        if token not in s:
            raise RuntimeError("P469b pstore missing %s" % token)
    return {"baseline_run":40871537827,"config":"CONFIG_PSTORE_RAM=y already built",
            "driver":"fs/pstore/ram.o built-in",
            "init":"postcore_initcall restored; phase82 overlapping A52 writer disabled",
            "probe":"P461 instrumentation preserved",
            "legacy_dummy":"skip if the exact available reserved-memory DT region exists",
            "preserve_ecc":48,"duplicate_memory":False,
            "exclusive_ram":"0xB1B00000+0x100000",
            "legacy_early_diag":"0xB1B40000+0x40000 disabled for G"}


def self_test():
    # Mimic the restored P82 A52 diagnostic ownership, not upstream 5.10.
    sample = """
#include <linux/platform_device.h>
static int fake_ramoops_probe(void)
{
    /* P461 PSTORE RAMOOPS_PROBE */
    return 0;
}
#define A52_DIAG_CONSOLE_PHYS 0xB1B40000ULL
int __init a52_persistent_diag_init(void)
{
\tstruct persistent_ram_ecc_info ecc = { };
\tint prz_ret;
\treturn prz_ret;
}
static void __init ramoops_register_dummy(void)
{
\tstruct ramoops_platform_data pdata;
}
static int __init __maybe_unused ramoops_init(void)
{
\tint ret;
\tramoops_register_dummy();
\tret = platform_driver_register(&ramoops_driver);
\treturn ret;
}
/* A52 diagnostic build owns the console quarter directly. */
"""
    result = patch(sample)
    check(result)
    assert result.count("postcore_initcall(ramoops_init);") == 1
    assert "P469B PSTORE EARLY_DIAG_DISABLED" in result
    assert "static int __init __maybe_unused ramoops_init" not in result
    assert "#include <linux/of_address.h>" in result
    assert "#include <linux/of.h>" in result
    try:
        patch(result)
    except RuntimeError as e:
        assert "already applied" in str(e)
    else:
        raise AssertionError("P469b duplicate pstore patch accepted")
    print("P469B PSTORE EXCLUSIVE-OWNER INITCALL SELF-TEST PASS")


def main():
    pa=argparse.ArgumentParser()
    pa.add_argument("--root",type=Path)
    pa.add_argument("--self-test",action="store_true")
    pa.add_argument("--check-only",action="store_true")
    pa.add_argument("--report",type=Path)
    a=pa.parse_args()
    if a.self_test:
        self_test()
        return
    if a.root is None:
        pa.error("--root required unless --self-test")
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
