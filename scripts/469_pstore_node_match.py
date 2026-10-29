#!/usr/bin/env python3
"""P469: validate the *live* ramoops reserved-memory OF node by parent/name/reg.

P461 had compared np->full_name to an absolute path. On Android 5.10 OF,
full_name may be a base name, e.g. ramoops@B1B00000. Keep the P461
OF_POPULATED-safe / of_find_device_by_node logic unchanged.
Apply after P461, before the kernel final-tree manifest and compilation.
"""
import argparse
import json
from pathlib import Path

SOURCE = Path("drivers/of/platform.c")
ORIGINAL = '''        if (strcmp(np->full_name,
                   "/reserved-memory/ramoops@B1B00000")) {
            pr_err("P461 PSTORE unexpected RAMOOPS node=%pOF; refuse second device\\n",
                   np);
            continue;
        }'''
REPLACEMENT = r'''        /* P469 PSTORE NODE_MATCH: full_name can be only the OF basename
         * on 5.10, never require a leading /reserved-memory path.
         * Validate parent AND the exact reserved-memory resource to
         * avoid instantiating some other compatible="ramoops" node.
         */
        {
            struct resource res;
            int rc;

            rc = of_address_to_resource(np, 0, &res);
            if (!np->parent ||
                !of_node_name_eq(np->parent, "reserved-memory") ||
                strcasecmp(kbasename(np->full_name),
                           "ramoops@B1B00000") ||
                rc ||
                res.start != 0xb1b00000ULL ||
                resource_size(&res) != 0x00100000) {
                pr_err("P469 PSTORE NODE_REJECT node=%pOF parent=%pOF rc=%d\n",
                       np, np->parent, rc);
                continue;
            }
            pr_info("P469 PSTORE NODE_MATCH node=%pOF start=%pa bytes=%pa\n",
                    np, &res.start, &res.end);
        }'''


def replace_once(s, old, new):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"P469 pstore expected one P461 strcmp, got {n}")
    return s.replace(old, new, 1)


def patch(s):
    if "P469 PSTORE NODE_MATCH" in s:
        raise RuntimeError("P469 pstore already patched")
    if "P461 PSTORE OF_RAMOOPS" not in s:
        raise RuntimeError("P469 pstore requires P461 initcall/OF audit")
    # Explicit declaration: kbasename() is provided by linux/string.h.
    if "#include <linux/of_address.h>" not in s:
        raise RuntimeError("P469 pstore requires OF address header")
    s = replace_once(s, ORIGINAL, REPLACEMENT)
    return s


def check(s):
    for key in ("P469 PSTORE NODE_MATCH", "P469 PSTORE NODE_REJECT",
                'of_node_name_eq(np->parent, "reserved-memory")',
                'strcasecmp(kbasename(np->full_name),',
                'res.start != 0xb1b00000ULL',
                "resource_size(&res) != 0x00100000",
                "of_find_device_by_node(np)",
                "of_node_clear_flag(np, OF_POPULATED)",
                "of_platform_device_create(np, NULL, NULL)"):
        if key not in s:
            raise RuntimeError("P469 pstore missing guard " + key)
    if ORIGINAL in s:
        raise RuntimeError("P469 stale absolute full_name match")
    return {"phase": "P469", "ramoops_parent": "reserved-memory",
            "ramoops_basename": "ramoops@B1B00000",
            "ramoops_reg": ["0xb1b00000", "0x00100000"],
            "duplicates": "P461 OF_POPULATED and registered device gates retained",
            "device_count": "still requires one unique OF node"}


def self_test():
    sample = '#include <linux/of_address.h>\n/* P461 PSTORE OF_RAMOOPS */\n' + ORIGINAL + '''
        was_populated = of_node_check_flag(np, OF_POPULATED);
        pdev = of_find_device_by_node(np);
        of_node_clear_flag(np, OF_POPULATED);
        pdev = of_platform_device_create(np, NULL, NULL);
'''
    done = patch(sample)
    assert check(done)
    try:
        patch(done)
    except RuntimeError:
        pass
    else:
        raise AssertionError("P469 duplicate pstore patch accepted")
    print("P469 PSTORE BASENAME+PARENT+REG SELFTEST PASS")


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
    if args.root is None:
        p.error("--root is required")
    path = args.root / SOURCE
    code = path.read_text()
    if not args.check_only:
        code = patch(code)
        path.write_text(code)
    result = check(code)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("P469 PSTORE NODE NAME SOURCE PASS", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
