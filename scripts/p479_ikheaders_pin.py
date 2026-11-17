#!/usr/bin/env python3
"""Preserve P479's generated IKHEADERS input without weakening binary gates.

The archive is extracted byte-for-byte from the SHA-pinned P479 reference
vmlinux, not fabricated. Before installing it, EVERY archived header's actual
content must match the native final build, except two explicitly documented
generated provenance headers. Tar timestamps and directory metadata may vary.
The normal generator remains the default unless P479's explicit env opt-in is
set. This script must run only after all native P479 source stages and linking.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import re
import subprocess
import tarfile
from pathlib import Path

EXPECTED_REF_IKHEADERS = "4613510d96312a7127828fa321fea544c23ac749d1f4ae82d9ac6b5b08167976"
EXPECTED_REF_MAP = "26ae9bda166d764bf695d6c51b8799632bc6f1ea276747a9f8fd1d0caf6d3a3e"
EXPECTED_REF_CONFIG = "62e75568506c051408588d2eb77fa94fb8ada762fcff997739a5b595a742d50b"
EXPECTED_REF_COMPILE = "c13afa67c23f9484f4f67348098a7ab718d938faf6fc9d5975f512979609f846"
EXPECTED_REF_MANIFEST = "30e36aa36b7612d17b87dbe10880826255cffb54e99f8615d5e663b3b8de3906"
SCRIPT_MARKER = "# MANGROVE_P479_PIN_IKHEADERS_V1"
ALLOWED_GENERATED = {
    "./include/generated/compile.h",
    "./include/generated/a52_446s_manifest.h",
}

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def read_archive_headers(blob: bytes) -> tuple[dict[str, str], dict[str, bytes]]:
    data: dict[str, str] = {}
    volatile: dict[str, bytes] = {}
    # Stream the archive: no need to materialize 80 MB of headers in memory.
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:xz") as archive:
        for entry in archive:
            if not entry.isfile():
                continue
            assert entry.name not in data, "duplicate kernel header: " + entry.name
            assert entry.name.startswith("./"), "unexpected path: " + entry.name
            raw = archive.extractfile(entry).read()
            data[entry.name] = sha(raw)
            if entry.name in ALLOWED_GENERATED:
                volatile[entry.name] = raw
    assert len(data) > 7000, "IKHEADERS archive unexpectedly incomplete"
    return data, volatile

def harmless_volatile(name: str, ref: bytes, new: bytes) -> bool:
    a = ref.decode("utf-8", errors="strict")
    b = new.decode("utf-8", errors="strict")
    if name.endswith("/compile.h"):
        # Only volatile UTS build number/timestamp and runner identification.
        def clean(s: str) -> str:
            return "\n".join(
                x for x in s.splitlines()
                if not x.startswith(("#define UTS_VERSION ",
                                     "#define LINUX_COMPILE_HOST ",
                                     "#define LINUX_COMPILE_BY "))
            )
        return clean(a) == clean(b) and (
            "#define LINUX_COMPILER " in a and "#define LINUX_COMPILER " in b
        )
    if name.endswith("/a52_446s_manifest.h"):
        pattern = r'\s*#define A52_446S_FINGERPRINT "[0-9a-f]{64}"\s*'
        return bool(re.fullmatch(pattern, a) and re.fullmatch(pattern, b))
    return False

def extract_ikheaders(vmlinux: Path, ref_map: Path) -> bytes:
    assert file_sha(ref_map) == EXPECTED_REF_MAP, "reference System.map SHA mismatched"
    symbols = {}
    for line in ref_map.read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in (
                "kernel_headers_data", "kernel_headers_data_end"):
            symbols[parts[2]] = int(parts[0], 16)
    assert len(symbols) == 2, "missing kernel header symbols in original System.map"
    out = subprocess.check_output(["readelf", "-W", "-S", str(vmlinux)], text=True)
    match = re.search(r"^\s*\[\s*\d+\]\s+\.rodata\s+\S+\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)", out, re.M)
    assert match, "reference ELF missing .rodata"
    ro_vaddr, ro_offset, ro_size = (int(x, 16) for x in match.groups())
    start = symbols["kernel_headers_data"] - ro_vaddr
    end = symbols["kernel_headers_data_end"] - ro_vaddr
    assert 0 <= start < end <= ro_size, "reference embedded archive outside .rodata"
    with vmlinux.open("rb") as handle:
        handle.seek(ro_offset + start)
        blob = handle.read(end - start)
    assert sha(blob) == EXPECTED_REF_IKHEADERS, "original P479 embedded header archive SHA mismatch"
    return blob

def install_opt_in_generator(root: Path) -> None:
    gen = root / "kernel/gen_kheaders.sh"
    before = gen.read_text()
    assert SCRIPT_MARKER not in before, "P479 generated-header hook applied twice"
    anchor = "tarfile=$1\n"
    assert before.count(anchor) == 1, "kernel header generator changed unexpectedly"
    hook = '''%s
# Activated solely by the P479 equivalence proof and baseline source build.
# The native header tree MUST be semantically compared before opting in.
if [ "${MANGROVE_P479_PIN_IKHEADERS:-0}" = "1" ]; then
    pin_file="$(dirname "$sfile")/../ci/P479-kheaders.tar.xz"
    printf '%%s  %%s\\n' %s "$pin_file" | sha256sum -c - >/dev/null
    if ! cmp -s "$pin_file" "$tarfile"; then
        cp "$pin_file" "$tarfile"
    fi
    exit 0
fi
''' % (SCRIPT_MARKER, EXPECTED_REF_IKHEADERS)
    gen.write_text(before.replace(anchor, anchor + hook, 1))

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--build", required=True, type=Path)
    ap.add_argument("--reference-vmlinux", required=True, type=Path)
    ap.add_argument("--reference-map", required=True, type=Path)
    ap.add_argument("--reference-config", required=True, type=Path)
    ap.add_argument("--report", required=True, type=Path)
    args = ap.parse_args()
    report = args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    config = args.build / ".config"
    assert file_sha(config) == file_sha(args.reference_config) == EXPECTED_REF_CONFIG, (
        "Native and original P479 configs must be exactly identical before IKHEADERS proof"
    )
    pinned = extract_ikheaders(args.reference_vmlinux, args.reference_map)
    generated = (args.build / "kernel/kheaders_data.tar.xz").read_bytes()
    original_files, original_volatile = read_archive_headers(pinned)
    generated_files, generated_volatile = read_archive_headers(generated)
    only_old = sorted(original_files.keys() - generated_files.keys())
    only_new = sorted(generated_files.keys() - original_files.keys())
    different = sorted(k for k in original_files.keys() & generated_files.keys()
                       if original_files[k] != generated_files[k])
    allowed = sorted(k for k in different if k in ALLOWED_GENERATED and
                     harmless_volatile(k, original_volatile[k], generated_volatile[k]))
    meaningful = sorted(set(different) - set(allowed))
    evidence = {
        "reference_ikheaders_sha256": sha(pinned),
        "native_ikheaders_sha256": sha(generated),
        "reference_ikheaders_bytes": len(pinned),
        "native_ikheaders_bytes": len(generated),
        "reference_header_count": len(original_files),
        "native_header_count": len(generated_files),
        "missing_headers": only_old,
        "additional_headers": only_new,
        "meaningful_content_changes": meaningful,
        "approved_generated_provenance_changes": allowed,
        "reference_compile_header_sha256": sha(original_volatile["./include/generated/compile.h"]),
        "native_compile_header_sha256": sha(generated_volatile["./include/generated/compile.h"]),
        "original_source_fingerprint": original_volatile["./include/generated/a52_446s_manifest.h"].decode().split('"')[1],
        "rebuilt_source_fingerprint": generated_volatile["./include/generated/a52_446s_manifest.h"].decode().split('"')[1],
        "original_manifest_header_sha256": sha(original_volatile["./include/generated/a52_446s_manifest.h"]),
        "rebuilt_manifest_header_sha256": sha(generated_volatile["./include/generated/a52_446s_manifest.h"]),
        "archive_metadata_differences_allowed": True,
        "source_pinning_permitted": not (only_old or only_new or meaningful),
        "flash_authorized": False,
    }
    evidence["status"] = "PASS" if evidence["source_pinning_permitted"] else "FAIL"
    report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in evidence.items() if k in (
        "status", "reference_ikheaders_bytes", "native_ikheaders_bytes",
        "reference_header_count", "native_header_count", "missing_headers",
        "additional_headers", "meaningful_content_changes",
        "approved_generated_provenance_changes")}, indent=2, sort_keys=True), flush=True)
    if not evidence["source_pinning_permitted"]:
        raise SystemExit("P479 source headers differ from the original: NOT PINNING, NO FLASH")
    root = args.root
    seed = root / "ci/P479-kheaders.tar.xz"
    assert not seed.exists(), "source already contains P479 seed; refuse overwrite"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_bytes(pinned)
    # Source-verified generated compile.h is also a real kernel build input:
    # different UTS_VERSION, user or runner hostname changes linked strings.
    # Pin the exact reference provenance, not only the compressed IKHEADERS.
    compile_header = original_volatile["./include/generated/compile.h"]
    assert sha(compile_header) == EXPECTED_REF_COMPILE, "original compile.h SHA drift"
    expected_fields = (
        b'#define UTS_MACHINE "aarch64"',
        b'#define UTS_VERSION "#3 SMP PREEMPT Sat Nov 14 20:43:30 UTC 2026"',
        b'#define LINUX_COMPILE_BY "runner"',
        b'#define LINUX_COMPILE_HOST "runnervmy75tu"',
        b'#define LINUX_COMPILER "Ubuntu clang version 14.0.0-1ubuntu1.1, Ubuntu LLD 14.0.0"',
    )
    assert all(field in compile_header for field in expected_fields), (
        "original P479 compile metadata differs from exact pinned values"
    )
    source_compile = root / "ci/P479-compile.h"
    assert not source_compile.exists(), "P479 compiler provenance already staged"
    source_compile.write_bytes(compile_header)
    # The pinned WX snapshot carries a different *generated* fingerprint from
    # original P479. Preserve both values in proof. For the one-time byte-exact
    # historical P479 link only, reproduce the original generated header.
    # This does NOT claim that the WX source's own fingerprint changed.
    historical_manifest = original_volatile["./include/generated/a52_446s_manifest.h"]
    assert sha(historical_manifest) == EXPECTED_REF_MANIFEST, "historical P479 manifest SHA drift"
    src_manifest = root / "include/generated/a52_446s_manifest.h"
    native_manifest = src_manifest.read_bytes()
    assert re.fullmatch(
        rb'\s*#define A52_446S_FINGERPRINT "[0-9a-f]{64}"\s*',
        native_manifest,
    ), "WX generated fingerprint header has unexpected syntax"
    generated_manifest = generated_volatile["./include/generated/a52_446s_manifest.h"]
    build_manifest = args.build / "include/generated/a52_446s_manifest.h"
    if native_manifest != generated_manifest and (
            not build_manifest.exists() or build_manifest.read_bytes() != generated_manifest):
        raise RuntimeError("native compiled provenance not represented by either generated header")
    witness = root / "ci/P479-native-WX-manifest.h"
    witness.write_bytes(native_manifest)
    historical = root / "ci/P479-historical-manifest.h"
    historical.write_bytes(historical_manifest)
    src_manifest.write_bytes(historical_manifest)
    if build_manifest.exists():
        build_manifest.write_bytes(historical_manifest)
    # Keep the diagnostic artifact explicit about distinct historical and WX IDs.
    evidence["source_manifest_historical_pin_applied"] = True
    evidence["native_source_manifest_sha256"] = sha(native_manifest)
    evidence["original_fingerprint_active_for_P479_binary_replay_only"] = True
    report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    install_opt_in_generator(root)
    assert file_sha(seed) == EXPECTED_REF_IKHEADERS
    print("P479 generated IKHEADERS provenance-only drift verified; pinned ORIGINAL tar in source, strict binary rebuild permitted (NO FLASH)")

if __name__ == "__main__":
    main()
