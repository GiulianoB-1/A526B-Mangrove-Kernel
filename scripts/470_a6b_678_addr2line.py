#!/usr/bin/env python3
"""P470-A6b: exact pre-A6b #678 source-basis vmlinux symbol disassembly.

Build the A6-only Image first, BEFORE applying A6b. This gives the
closest reproducible symbol/image for b710980d on the same pinned tree.
Emit the whole faulting instruction range, not a guessed offset from
the ECC-damaged pmsg, and preserve vmlinux for independent adjudication.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

def tool(*names):
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise RuntimeError("P470-A6b missing tool: " + "/".join(names))

def run(argv):
    p = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(f"Command {argv} failed rc={p.returncode}: {p.stderr[-1000:]}")
    return p.stdout

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--vmlinux", type=Path, required=True)
    p.add_argument("--system-map", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    vm, sm = a.vmlinux, a.system_map
    nm = {}
    for line in sm.read_text().splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] in ("adsp_probe", "__dev_printk"):
            nm[fields[2]] = int(fields[0], 16)
    if set(nm) != {"adsp_probe", "__dev_printk"}:
        raise RuntimeError("P470-A6b expected exact adsp_probe and __dev_printk symbols " + repr(nm))
    objdump = tool("llvm-objdump", "aarch64-linux-gnu-objdump")
    addr2line = tool("llvm-addr2line", "aarch64-linux-gnu-addr2line")
    readelf = tool("llvm-readelf", "readelf")
    sec = run([readelf, "-SW", str(vm)])
    if ".debug_info" not in sec:
        raise RuntimeError("P470-A6b missing DWARF .debug_info in preserved original vmlinux")
    reports = {}
    for symbol, offsets in (
        ("adsp_probe", list(range(0x370, 0x3b4, 4))),
        ("__dev_printk", list(range(0x20, 0x34, 4))),
    ):
        addresses = [hex(nm[symbol] + off) for off in offsets]
        locs = run([addr2line, "-fip", "-e", str(vm)] + addresses)
        # Decode every 4-byte instruction within a window broad enough to
        # contain the damaged offset, with neighbouring source lines.
        lo = nm[symbol] + min(offsets) - 0x10
        hi = nm[symbol] + max(offsets) + 0x10
        disasm = run([objdump, "-d", "-S",
                     "--start-address=" + hex(lo),
                     "--stop-address=" + hex(hi), str(vm)])
        out = a.out / (symbol + "-#678-disassembly.txt")
        out.write_text(disasm)
        report = a.out / (symbol + "-#678-addr2line.txt")
        report.write_text("symbol=" + symbol + " base=" + hex(nm[symbol]) +
                          "\n" + "\n".join(f"{off:#x} {loc}" for off, loc in
                          zip(offsets, locs.splitlines())) + "\n")
        reports[symbol] = {
            "symbol_address": hex(nm[symbol]),
            "offsets": [hex(o) for o in offsets],
            "disassembly_file": str(out),
            "addr2line_file": str(report),
        }
    a.out.mkdir(parents=True, exist_ok=True)
    digest = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
    data = {
        "phase": "P470-A6B-#678-B710980D-SOURCE-FORENSICS",
        "compiled_source_basis": "the pinned A6 transformer sequence identical to #678; before any A6b change",
        "recovered_exact_678_binary": False,
        "source_equivalent_rebuild": True,
        "build_id_bit_identical_to_678": "NOT_PROVEN",
        "crash_offset_note": "ECC damage obscures one nibble: present all offset candidates",
        "vmlinux_sha256": digest(vm),
        "system_map_sha256": digest(sm),
        "debug_info_present": True,
        "symbols": reports,
        "first_flash_authorized": False,
    }
    (a.out / "P470-A6B-678-FORENSICS.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("P470-A6b PRE-A6b A6 #678 SOURCE-EQUIVALENT DWARF addr2line and objdump PASS; exact #678 binary hash UNPROVEN")

if __name__ == "__main__":
    main()
