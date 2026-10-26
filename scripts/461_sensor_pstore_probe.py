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
        f=change(f,
            'for_each_matching_node(node, reserved_mem_matches)\n\t\tof_platform_device_create(node, NULL, NULL);',
            '''for_each_matching_node(node, reserved_mem_matches) {
		struct platform_device *pdev;
		pdev = of_platform_device_create(node, NULL, NULL);
		if (of_device_is_compatible(node, "ramoops"))
			pr_info("P461 PSTORE OF_RAMOOPS node=%pOF available=%d pdev=%p\\n",
				node, of_device_is_available(node), pdev);
	}''',"OF reserved-memory population")
        g=change(g,
            'static int ramoops_probe(struct platform_device *pdev)\n{',
            'static int ramoops_probe(struct platform_device *pdev)\n{\n'
            '\tpr_info("P461 PSTORE RAMOOPS_PROBE node=%pOF\\n", pdev->dev.of_node);',
            "ramoops entry")
        g=change(g,
            '\terr = pstore_register(&cxt->pstore);',
            '\tpr_info("P461 PSTORE RAMOOPS_REGISTER attempt ecc=%u mem=%pa bytes=%zu\\n",\n'
            '\t\tpdata->ecc_info.ecc_size, &paddr, pdata->mem_size);\n'
            '\terr = pstore_register(&cxt->pstore);',
            "pstore register call")
        p.write_text(f);q.write_text(g)
    for required in (TAG,"of_platform_device_create(node, NULL, NULL)"):
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
