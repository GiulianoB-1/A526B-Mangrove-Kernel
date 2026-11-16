#!/usr/bin/env bash
# Executed ONLY after the verified P479 equivalence gate has returned PASS.
# Captures the complete rebuilt P479 kernel SOURCE as a permanent release,
# independent of GitHub Actions' expiring artifacts.
# The original 446S restore path, legacy workflows and hardware policy stay untouched.
set -Eeuo pipefail
: "${GH_TOKEN:?GitHub release token required}"
: "${GITHUB_REPOSITORY:?repository required}"
PROOF="$PWD/phase447-inventory/P479-WX-EQUIVALENCE-PROOF.json"
ROOT="$PWD/gki/common"
BUILD="$PWD/workspace/gki-phase199-out"
MANIFEST="$PWD/phase446r2-manifest/final-tree.json"
ASSETS="$PWD/p479-verified-source-release"
test -s "$ROOT/Makefile" && test -d "$ROOT/KernelSU"
test -s "$BUILD/.config" && test -s "$PROOF" && test -s "$MANIFEST"
python3 - "$PROOF" "$BUILD/.config" "$MANIFEST" <<'PY'
from pathlib import Path
import hashlib,json,sys
p,c,m=map(Path,sys.argv[1:])
proof=json.loads(p.read_text())
assert proof["status"]=="PASS" and not proof["errors"]
assert proof["baseline_run"]==43638159300
assert proof["baseline_sha"]=="e2e9f3fad600489deb8fa0816245a87cef6b9b95"
for key in ("config_exact","system_map_symbols_and_addresses_exact",
            "image_allocated_elf_section_sizes_identical","native_h4_linked"):
    assert proof["checks"][key]["pass"],key
actual=hashlib.sha256(c.read_bytes()).hexdigest()
assert actual==proof["checks"]["config_exact"]["details"]["built_sha256"]
manifest=json.loads(m.read_text())
assert manifest["strict"] is True and not manifest["missing_required"]
print("P479 verified source release permission gate PASS")
PY
test ! -e "$ASSETS" || { echo "::error::Refusing to overwrite verified source release staging"; exit 1; }
mkdir -p "$ASSETS"
# Exclude *all* nested .git metadata: KernelSU/.git is present in the WX source
# archive and must become regular tracked files in the future one-commit repo.
# Kernel objects reside in external O= and are not part of this source.
tar -C "$ROOT" --exclude-vcs --use-compress-program='zstd -5 -T0' \
  -cf "$ASSETS/P479-verified-full-source.tar.zst" .
cp "$BUILD/.config" "$ASSETS/P479.config"
cp "$PROOF" "$ASSETS/P479-equivalence-proof.json"
cp "$MANIFEST" "$ASSETS/P479-final-tree-manifest.json"
(cd "$ASSETS" && sha256sum P479-verified-full-source.tar.zst P479.config \
  P479-equivalence-proof.json P479-final-tree-manifest.json > SHA256SUMS && \
  sha256sum -c SHA256SUMS)
# Check archived source is structurally complete and excludes nested Git data.
tar --use-compress-program=zstd -tf "$ASSETS/P479-verified-full-source.tar.zst" > "$RUNNER_TEMP/P479-ARCHIVE-FILELIST.txt"
grep -Fxq './Makefile' "$RUNNER_TEMP/P479-ARCHIVE-FILELIST.txt"
grep -Fxq './KernelSU/Makefile' "$RUNNER_TEMP/P479-ARCHIVE-FILELIST.txt" || \
  grep -Fxq './KernelSU/kernel/Makefile' "$RUNNER_TEMP/P479-ARCHIVE-FILELIST.txt" || \
  grep -Fxq './KernelSU/Kbuild' "$RUNNER_TEMP/P479-ARCHIVE-FILELIST.txt"
if grep -E '(^|/)\.git(/|$)' "$RUNNER_TEMP/P479-ARCHIVE-FILELIST.txt"; then
  echo "::error::Nested Git metadata in source backup"; exit 1
fi
if gh release view p479-verified-source-baseline --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  echo "::error::Verified P479 release exists, refusing overwrite"; exit 1
fi
cat > "$ASSETS/README.txt" <<'NOTES'
P479 equivalent full source, backup for migration to
GiulianoB-1/A526B-Mangrove-Source.

Generated only after P479 SHA-pinned WX source rebuild passes
exact .config, System.map symbols/addresses, ELF allocated section sizes
and compiled safety marker checks vs original run 43638159300.

No boot image is included. THIS RELEASE DOES NOT AUTHORIZE FLASHING.
Future P480 A3c must be committed directly in new source repo.
Original 446S and WX restore releases remain available for historical audit.
NOTES
gh release create p479-verified-source-baseline \
  --repo "$GITHUB_REPOSITORY" \
  --target "$GITHUB_SHA" \
  --title "P479 verified full kernel source baseline (NO FLASH)" \
  --notes-file "$ASSETS/README.txt" --latest=false \
  "$ASSETS/P479-verified-full-source.tar.zst" \
  "$ASSETS/P479.config" "$ASSETS/P479-equivalence-proof.json" \
  "$ASSETS/P479-final-tree-manifest.json" "$ASSETS/SHA256SUMS"
echo 'P479 equivalent full kernel source archived in permanent release p479-verified-source-baseline, NOT flashable' >> "$GITHUB_STEP_SUMMARY"
