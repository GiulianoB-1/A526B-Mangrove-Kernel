#!/usr/bin/env python3
"""Fail-closed P479 binary/config/symbol/section equivalence proof.
Never authorize flashing from this report alone.
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

REFERENCE_CONFIG = "62e75568506c051408588d2eb77fa94fb8ada762fcff997739a5b595a742d50b"
REFERENCE_MAP = "26ae9bda166d764bf695d6c51b8799632bc6f1ea276747a9f8fd1d0caf6d3a3e"
REFERENCE_IMAGE = "c1e29a64f611f402cdc8e5db1f42fea5b6ec9f48b19df60d5b9aa6da2d8585ae"
REQUIRED_IMAGE_MARKERS = (
    b"P479 H4 CABLE type=%s icl=%d fcc_target=%d reason=%s",
    b"P479 H4 ICL_SET ma=%d code=0x%02x readback=0x%02x rc=%d",
    b"P479 H4 FCC_SET ma=%d code=0x%02x readback=0x%02x rc=%d",
    b"MGBATT SHADOW COMPARE would_icl=%u would_fcc=%u",
    b"MGBATT SHADOW WRITE_BASELINE shadow_hw_writes=0",
    b"P472 A3a Q6 afe registered rc=0",
    b"P472 A3b CDC_TLMM_WAKE pin=%d gpio=%d irq=%d en=%d rc=%d",
    b"P478 LPI gpio debugfs:",
    b"P478 WCD gpio debugfs:",
)
REQUIRED_CONFIG = (b"CONFIG_P479_H4=y\n", b"CONFIG_SECURITY_SELINUX=y\n")

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def alloc_sections(path: Path) -> dict:
    out = subprocess.check_output(["readelf", "-W", "-S", str(path)], text=True)
    sections = {}
    pattern = re.compile(r"^\s*\[\s*\d+\]\s+(\S+)\s+\S+\s+[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+(\S+)")
    for line in out.splitlines():
        m=pattern.match(line)
        if not m or 'A' not in m.group(3):
            continue
        assert m.group(1) not in sections, f"Duplicate alloc section: {m.group(1)}"
        sections[m.group(1)]=int(m.group(2),16)
    assert ".text" in sections and ".rodata" in sections and ".bss" in sections
    return sections

def compare_exact(ref: Path, got: Path) -> tuple[bool,list[str]]:
    if digest(ref)==digest(got):
        return True,[]
    ref_lines=ref.read_text(errors="replace").splitlines(keepends=True)
    got_lines=got.read_text(errors="replace").splitlines(keepends=True)
    diff=difflib.unified_diff(ref_lines,got_lines,fromfile="P479-original",tofile="P479-restored")
    return False,[line.rstrip("\n") for _,line in zip(range(100),diff)]

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--build",type=Path,required=True)
    ap.add_argument("--reference",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    args=ap.parse_args()
    build=args.build
    ref=args.reference
    config=build/".config"
    sym=build/"System.map"
    image=build/"arch/arm64/boot/Image"
    binary=build/"vmlinux"
    rc=ref/"phase447-inventory/P471-D1-COMPILED.config"
    rs=ref/"phase447b-variants/P471-D1-DATARMNET-CANDIDATE.System.map"
    rv=ref/"phase447b-variants/P471-D1-DATARMNET-CANDIDATE.vmlinux"
    evidence={"baseline_run":43638159300,
              "baseline_sha":"e2e9f3fad600489deb8fa0816245a87cef6b9b95",
              "source_restore":"phase446wx-source-backup/12271681215",
              "checks":{}, "errors":[]}
    errors=evidence["errors"]
    def gate(label,good,details=None):
        evidence["checks"][label]={"pass":bool(good),"details":details}
        if not good: errors.append(label)
    for path in (config,sym,image,binary,rc,rs,rv):
        assert path.is_file() and path.stat().st_size>0, f"missing proof input {path}"
    gate("reference_config_sha",digest(rc)==REFERENCE_CONFIG,digest(rc))
    gate("reference_system_map_sha",digest(rs)==REFERENCE_MAP,digest(rs))
    config_ok,config_diff=compare_exact(rc,config)
    sym_ok,sym_diff=compare_exact(rs,sym)
    gate("config_exact",config_ok,{"built_sha256":digest(config),"difference_excerpt":config_diff})
    gate("system_map_symbols_and_addresses_exact",sym_ok,{"built_sha256":digest(sym),"difference_excerpt":sym_diff})
    reference_sections=alloc_sections(rv)
    new_sections=alloc_sections(binary)
    differences={name:{"original":reference_sections.get(name),"rebuilt":new_sections.get(name)}
                 for name in sorted(set(reference_sections)|set(new_sections))
                 if reference_sections.get(name)!=new_sections.get(name)}
    gate("image_allocated_elf_section_sizes_identical",not differences,{"reference":reference_sections,"rebuilt":new_sections,"differences":differences})
    raw=image.read_bytes()
    for marker in REQUIRED_IMAGE_MARKERS:
        gate("marker:"+marker.decode(),marker in raw)
    for option in REQUIRED_CONFIG:
        gate("config:"+option.decode().strip(),option in config.read_bytes())
    gate("native_h4_linked","p479_h4_tick" in sym.read_text())
    evidence["built_image"]={"bytes":image.stat().st_size,"sha256":digest(image)}
    evidence["original_image_sha256"]=REFERENCE_IMAGE
    evidence["image_hash_identical"]=(digest(image)==REFERENCE_IMAGE)
    # Different image bytes can arise despite matching sections and map. The exact
    # binary hash remains recorded for human investigation, not silently "explained".
    evidence["status"]="PASS" if not errors else "FAIL"
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"status":evidence["status"],"errors":errors,
        "config_identical":config_ok,"symbols_identical":sym_ok,
        "allocated_section_sizes_identical":not differences,
        "raw_image_hash_identical":evidence["image_hash_identical"]},indent=2),flush=True)
    if errors:
        raise SystemExit("P479 equivalence FAILED: "+", ".join(errors))
    print("P479 EQUIVALENCE PROOF PASS. This does not authorize flashing or P480 until reviewed.")

if __name__=="__main__":
    main()
