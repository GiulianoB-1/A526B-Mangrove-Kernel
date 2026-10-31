#!/usr/bin/env python3
"""Preprocess ALL actual built C translation units from Kbuild's .<obj>.o.cmd.

Kbuild 5.10 does not reliably export nested IPA/GSI 'foo.i' goals from the
top-level make entry. Instead replay the EXACT successful compiler argv,
including the same forced TG headers, with only -c -> -E and -o -> .i.
Never substitute guessed flags or silently skip an object with C source.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

ROOTS = (
    "drivers/remoteproc/remoteproc_core.c",
    "drivers/remoteproc/qcom_q6v5_pas.c",
    "drivers/a52_pil/subsystem_notif.c",
    "drivers/a52_pil/subsystem_restart.c",
)
IPA_ROOT = Path("drivers/platform/msm")

def replay(root, build, source):
    obj = build / source.with_suffix(".o")
    cmdfile = obj.parent / ("." + obj.name + ".cmd")
    if not obj.is_file():
        raise RuntimeError(f"A6c no linked C object for {source}")
    if not cmdfile.is_file():
        raise RuntimeError(f"A6c Kbuild compile command missing for {source}: {cmdfile}")
    raw = cmdfile.read_text(errors="replace")
    # Compilation commands are a single expanded shell line; the rest of .cmd
    # is the make dependency rule and must NEVER be executed.
    lines = [m.group(1).strip() for m in
             re.finditer(r"(?m)^cmd_[^\n]+?\s*:=\s*(.+)$", raw)]
    if len(lines) != 1:
        raise RuntimeError(f"A6c expected one Kbuild compile command for {source}, got {len(lines)}")
    command = lines[0]
    if "\n" in command or re.search(r"(?:^|\s)(?:&&|\|\||;|\|)(?:\s|$)", command):
        raise RuntimeError(f"A6c unsafe multi-stage compile command for {source}")
    argv = shlex.split(command)
    # No shell, and no make variable expansion in the emitted command allowed.
    if any("$(" in word or "\x00" in word for word in argv):
        raise RuntimeError(f"A6c unexpanded shell/make expression in {source}")
    if argv.count("-c") != 1 or argv.count("-o") != 1:
        raise RuntimeError(f"A6c unusual C compilation shape for {source}")
    if not any(word.endswith(source.as_posix()) for word in argv):
        raise RuntimeError(f"A6c Kbuild argv does not compile expected {source}")
    out = build / source.with_suffix(".i")
    out.parent.mkdir(parents=True, exist_ok=True)
    argv[argv.index("-c")] = "-E"
    argv[argv.index("-o") + 1] = str(out)
    # -P would discard #line provenance and defeat the header-origin gate.
    p = subprocess.run(argv, cwd=build, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, check=False)
    if p.returncode:
        raise RuntimeError(f"A6c compiler preprocessing failed for {source}: "
                           f"exit={p.returncode}\n{p.stderr[-12000:]}")
    if not out.is_file() or out.stat().st_size < 200:
        raise RuntimeError(f"A6c preprocessed output absent/empty: {out}")
    return {"tu": source.as_posix(), "object": str(obj.relative_to(build)),
            "kbuild_cmd": str(cmdfile.relative_to(build)),
            "preprocessed_file": str(out.relative_to(build)),
            "preprocessed_bytes": out.stat().st_size,
            "compiler": argv[0],
            "compile_argv_preserved_except_c_to_E_and_output": True}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--build", required=True, type=Path)
    p.add_argument("--manifest", required=True, type=Path)
    a = p.parse_args()
    root = a.root.resolve()
    build = a.build.resolve()
    sources = {Path(p) for p in ROOTS}
    all_ipa_c_objects = []
    for obj in sorted((build / IPA_ROOT).rglob("*.o")):
        rel = obj.relative_to(build)
        src = rel.with_suffix(".c")
        if (root / src).is_file():
            sources.add(src)
            all_ipa_c_objects.append(src)
    for needle in ("drivers/platform/msm/gsi/gsi.c",
                   "drivers/platform/msm/ipa/ipa_v3/rmnet_ipa.c",
                   "drivers/platform/msm/ipa/ipa_v3/ipa.c"):
        if Path(needle) not in sources:
            raise RuntimeError("A6c missing linked IPA/GSI object: " + needle)
    if len(all_ipa_c_objects) < 3:
        raise RuntimeError("A6c IPA/GSI too few compiled C objects")
    items = []
    for src in sorted(sources):
        if not (root / src).is_file():
            raise RuntimeError("A6c expected source missing: " + str(src))
        print("P470-A6c CPP recorded real compiler flags: " + str(src), flush=True)
        items.append(replay(root, build, src))
    report = {
        "phase": "P470-A6c-ACTUAL-KBUILD-COMPILER-CPP-REPLAY",
        "method": "exact .o.cmd compiler argv; -c => -E; -o <object> => <preprocessed>",
        "did_not_use_nested_kbuild_i_targets": True,
        "all_compiled_ipa_gsi_c_units_count": len(all_ipa_c_objects),
        "all_preprocessed_units_count": len(items),
        "actual_compiler_flags_preserved": True,
        "files": items,
    }
    a.manifest.parent.mkdir(parents=True, exist_ok=True)
    a.manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"P470-A6c CPP COMPLETE items={len(items)} ipa_gsi_units={len(all_ipa_c_objects)}")

if __name__ == "__main__":
    main()
