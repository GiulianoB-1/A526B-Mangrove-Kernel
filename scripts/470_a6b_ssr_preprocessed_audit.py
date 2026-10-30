#!/usr/bin/env python3
"""Compare ACTUAL preprocessed subsys_desc in both compilation units.

A6b forensic evidence: compare P469b staged sources vs A6b staged sources,
PAS vs the downstream SSR provider. The parser removes line directives,
never assumes matching source header names guarantee matching #ifdef layout.
This checks field declarations but NOT sizeof, which runtime compares.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

def extract(path):
    s = path.read_text(errors="replace")
    s = re.sub(r"(?m)^#\s*\d+.*\n", "", s)
    hits = list(re.finditer(r"\bstruct\s+subsys_desc\s*\{(.*?)\n\s*\};",
                           s, flags=re.S))
    if len(hits) != 1:
        raise RuntimeError(f"{path}: preprocessed subsys_desc definitions={len(hits)}")
    body = re.sub(r"\s+", " ", hits[0].group(1)).strip()
    for term in ("struct device *dev;", "struct module *owner;",
                 "struct qcom_smem_state *state;", "int force_stop_bit;"):
        if term not in body:
            raise RuntimeError(f"{path}: missing field {term}")
    return body

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-pas", type=Path, required=True)
    p.add_argument("--baseline-ssr", type=Path, required=True)
    p.add_argument("--a6b-pas", type=Path, required=True)
    p.add_argument("--a6b-ssr", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    roots = {
        "p469b_pas": args.baseline_pas,
        "p469b_ssr": args.baseline_ssr,
        "a6b_pas": args.a6b_pas,
        "a6b_ssr": args.a6b_ssr,
    }
    raw = {name: extract(path) for name, path in roots.items()}
    hashes = {name: hashlib.sha256(val.encode()).hexdigest()
              for name, val in raw.items()}
    all_same = len(set(hashes.values())) == 1
    out = {
        "phase": "P470-A6b-TG-SSR-ABI-PREPROCESS-COMPARE",
        "preprocessed_struct_hashes": hashes,
        "all_four_struct_declarations_match": all_same,
        "p469b_pas_equals_ssr": hashes["p469b_pas"] == hashes["p469b_ssr"],
        "a6b_pas_equals_ssr": hashes["a6b_pas"] == hashes["a6b_ssr"],
        "a6b_equals_p469b": hashes["p469b_pas"] == hashes["a6b_pas"],
        "p469b_vs_a6b_desc_layout_changed": hashes["p469b_pas"] != hashes["a6b_pas"],
        "sizeof_proved_by_preprocess": False,
        "runtime_size_offset_check_embedded": True,
        "safety_status": "FAIL_CLOSED" if not all_same else "DECLARATIONS_EQUAL_RUNTIME_SIZE_CHECK_PENDING",
        "hardware_oops_resolved": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print("P470-A6b ABI PREPROCESS comparison all_equal=" + str(all_same))
    for key, digest in hashes.items():
        print(f"P470-A6b ABI PREPROCESS {key} SHA256={digest}")
    if not all_same:
        raise SystemExit("P470-A6b ABI mismatch: preprocessed struct changes across PAS/SSR or builds")

if __name__ == "__main__":
    main()
