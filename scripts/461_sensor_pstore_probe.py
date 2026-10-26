#!/usr/bin/env python3
"""P461 sensors boot: make existing live ECC48 ramoops platform probe auditable.

No synthetic reserved-memory device and no duplicate resource. The 5.10 OF
core already instantiates /reserved-memory children with compatible="ramoops".
This instruments its original allocation and the driver probe to distinguish
CONFIG_PSTORE_RAM unset, unavailable OF node, and actual probe failures.
"""
import argparse,json
from pathlib import Path
TAG="P461 PSTORE OF_RAMOOPS"
def change(s,old,new,what):
    n=s.count(old)
    if n!=1:raise RuntimeError(f"P461 {what}: expected unique anchor, found {n}")
    return s.replace(old,new,1)
def run(root,check=False):
    p=root/"drivers/of/platform.c";q=root/"fs/pstore/ram.c"
    f=p.read_text();g=q.read_text()
    if not check:
        # Some Android 5.10 trees do NOT include ramoops in
        # reserved_mem_matches, so the ordinary platform population can
        # completely skip it. Add an OF_POPULATED-safe late arch initcall:
        # of_platform_device_create() checks the node's OF_POPULATED bit,
        # preventing duplicate platform devices even if original OF logic
        # created the same node first.
        marker="P461 PSTORE OF_RAMOOPS"
        if marker in f:
            raise RuntimeError("P461 duplicate fallback instrumentation")
        # OF_POPULATED is an allocation flag, NOT a registered pdev.
        # If already set, first search for the existing platform device.
        # Only clear a genuinely stale flag for this exact reserved-memory
        # consumer, and only after verifying no registered pdev by node.
        # Never create a second DT node/resource or clear an active device.
        f+="""

static int __init a52_p461_ramoops_populate(void)
{
    struct device_node *np;
    struct platform_device *pdev;
    bool was_populated;
    int found = 0;

    for_each_compatible_node(np, NULL, "ramoops") {
        if (!of_device_is_available(np))
            continue;
        if (strcmp(np->full_name,
                   "/reserved-memory/ramoops@B1B00000")) {
            pr_err("P461 PSTORE unexpected RAMOOPS node=%pOF; refuse second device\\n",
                   np);
            continue;
        }
        found++;
        was_populated = of_node_check_flag(np, OF_POPULATED);
        pdev = of_find_device_by_node(np);
        if (pdev) {
            pr_info("P461 PSTORE EXISTING node=%pOF pdev=%s bound_driver=%s populated=%d\\n",
                    np, dev_name(&pdev->dev),
                    pdev->dev.driver ? pdev->dev.driver->name : "<none>",
                    was_populated);
            of_dev_put(pdev);
            continue;
        }
        if (was_populated) {
            pr_warn("P461 PSTORE STALE_OF_POPULATED node=%pOF no_platform_device=1 reset_to_retry\\n",
                    np);
            of_node_clear_flag(np, OF_POPULATED);
        }
        pdev = of_platform_device_create(np, NULL, NULL);
        if (!pdev) {
            pr_err("P461 PSTORE CREATE_FAIL node=%pOF was_populated=%d now_populated=%d\\n",
                   np, was_populated,
                   of_node_check_flag(np, OF_POPULATED));
        } else {
            pr_info("P461 PSTORE CREATE_OK node=%pOF pdev=%s was_populated=%d bound_driver=%s\\n",
                    np, dev_name(&pdev->dev), was_populated,
                    pdev->dev.driver ? pdev->dev.driver->name : "<unbound>");
        }
    }
    if (found != 1)
        pr_err("P461 PSTORE OF_RAMOOPS count=%d expected=1\\n", found);
    return 0;
}
arch_initcall_sync(a52_p461_ramoops_populate);
"""
        # Preserve kernel C89 declaration order: insert marker after all
        # existing locals, not between opening brace and first declaration.
        g=change(g,
            '\tint err = -EINVAL;\n',
            '\tint err = -EINVAL;\n'
            '\tpr_info("P461 PSTORE RAMOOPS_PROBE node=%pOF\\n", pdev->dev.of_node);\n',
            "ramoops entry after local declarations")
        g=change(g,
            '\terr = pstore_register(&cxt->pstore);',
            '\tpr_info("P461 PSTORE RAMOOPS_REGISTER attempt ecc=%u mem=%pa bytes=%zu\\n",\n'
            '\t\tpdata->ecc_info.ecc_size, &paddr, pdata->mem_size);\n'
            '\terr = pstore_register(&cxt->pstore);',
            "pstore register call")
        p.write_text(f);q.write_text(g)
    for required in (TAG,"of_platform_device_create(np, NULL, NULL)",
                     "of_find_device_by_node(np)","STALE_OF_POPULATED",
                     "of_node_clear_flag(np, OF_POPULATED)"):
        if required not in p.read_text():raise RuntimeError("P461 missing OF audit "+required)
    for required in ("P461 PSTORE RAMOOPS_PROBE","P461 PSTORE RAMOOPS_REGISTER"):
        if required not in q.read_text():raise RuntimeError("P461 missing pstore probe marker "+required)
    return {"driver":"fs/pstore/ram.c","OF_population":"drivers/of/platform.c",
            "duplicate_ram_resource":False,"live_registration":"requires hardware collector proof"}
def main():
    a=argparse.ArgumentParser()
    a.add_argument("--root",type=Path,required=True)
    a.add_argument("--check-only",action="store_true")
    a.add_argument("--report",type=Path)
    x=a.parse_args()
    result=run(x.root,x.check_only)
    if x.report:
        x.report.parent.mkdir(parents=True,exist_ok=True)
        x.report.write_text(json.dumps(result,indent=2)+"\n")
    print("P461 PSTORE PLATFORM AUDIT PASS",json.dumps(result))
if __name__=="__main__":main()
