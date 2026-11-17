#!/usr/bin/env bash
# Migrate to a one-commit P479 kernel source repository ONLY after P479 equivalence PASS.
# No old patch-generator chain, no flashing, no overwrite of an existing repo.
set -Eeuo pipefail
: "${P479_SOURCE_ROOT:?verified P479 source directory required}"
: "${P479_CONFIG:?final P479 .config required}"
: "${P479_FINAL_TREE_MANIFEST:?P479 final-tree.json required}"
: "${P479_EQUIVALENCE_REPORT:?successful proof JSON required}"
# Dry-run mode validates the full source commit locally and cannot create
# or push a repository. Only mode 0 may consume SOURCE_PUSH_TOKEN.
P479_MIGRATION_DRY_RUN="${P479_MIGRATION_DRY_RUN:-0}"
case "$P479_MIGRATION_DRY_RUN" in 0|1) ;; *) echo "::error::Unknown migration mode"; exit 1;; esac
if [ "$P479_MIGRATION_DRY_RUN" = 0 ]; then
  : "${SOURCE_PUSH_TOKEN:?token with repo create/push permissions required}"
fi
TARGET="GiulianoB-1/A526B-Mangrove-Source"
SOURCE="$(realpath "$P479_SOURCE_ROOT")"
CONFIG="$(realpath "$P479_CONFIG")"
MANIFEST="$(realpath "$P479_FINAL_TREE_MANIFEST")"
PROOF="$(realpath "$P479_EQUIVALENCE_REPORT")"
test -s "$SOURCE/Makefile"
test -d "$SOURCE/KernelSU"
# Provenance is explicit: the historical P479 generated header is used only
# for binary replay, while the original WX source fingerprint is preserved.
for rel in ci/P479-kheaders.tar.xz ci/P479-compile.h \
           ci/P479-native-WX-manifest.h ci/P479-historical-manifest.h; do
  test -s "$SOURCE/$rel" || { echo "missing proven source metadata: $rel"; exit 1; }
done
printf '%s  %s\n' 4613510d96312a7127828fa321fea544c23ac749d1f4ae82d9ac6b5b08167976 "$SOURCE/ci/P479-kheaders.tar.xz" | sha256sum -c -
printf '%s  %s\n' c13afa67c23f9484f4f67348098a7ab718d938faf6fc9d5975f512979609f846 "$SOURCE/ci/P479-compile.h" | sha256sum -c -
printf '%s  %s\n' 30e36aa36b7612d17b87dbe10880826255cffb54e99f8615d5e663b3b8de3906 "$SOURCE/ci/P479-historical-manifest.h" | sha256sum -c -
cmp "$SOURCE/ci/P479-historical-manifest.h" "$SOURCE/include/generated/a52_446s_manifest.h"
! cmp -s "$SOURCE/ci/P479-native-WX-manifest.h" "$SOURCE/ci/P479-historical-manifest.h" || {
  echo "missing preserved WX historical fingerprint difference"; exit 1
}
python3 - "$CONFIG" "$MANIFEST" "$PROOF" <<'PY'
import hashlib,json,sys
from pathlib import Path
config,manifest,proof=(Path(x) for x in sys.argv[1:])
p=json.loads(proof.read_text())
assert p['status']=='PASS' and not p['errors'], 'equivalence not proven'
assert p['baseline_run']==43638159300
assert p['baseline_sha']=='e2e9f3fad600489deb8fa0816245a87cef6b9b95'
for key in ('config_exact','system_map_symbols_and_addresses_exact',
            'image_allocated_elf_section_sizes_identical','native_h4_linked'):
    assert p['checks'][key]['pass'] is True,key
actual=hashlib.sha256(config.read_bytes()).hexdigest()
assert actual==p['checks']['config_exact']['details']['built_sha256']
m=json.loads(manifest.read_text())
assert m['strict'] is True and not m['missing_required']
# This is the preserved Phase446S/WX ANCESTRY manifest, not the P479 build.
# Phase446S final.config differs from the native P479 final.config by design.
# The native P479 config has already been compared byte-for-byte to reference.
assert len(m['kernel_config_sha256']) == 64, 'missing historical config digest'
assert len(m['source_fingerprint_sha256']) == 64, 'missing source ancestry digest'
assert m['kernel_config_sha256'] != actual, (
    'unexpected ancestry/final config identity; audit independently before migration'
)
print('P479 equivalence config:', actual)
print('Earlier 446S/WX ancestry config:', m['kernel_config_sha256'])
print('P479 source migration proof gate PASS')
PY
STAGING="${RUNNER_TEMP:-/tmp}/p479-source-baseline"
test ! -e "$STAGING" || { echo "error: staging exists, refusing overwrite"; exit 1; }
mkdir -p "$STAGING"
# Preserve all source files; remove nested Git metadata such as KernelSU/.git
# so the new source repository has exactly ONE initial commit, no submodule.
rsync -a --exclude='.git' "$SOURCE/" "$STAGING/"
rsync -a -n -c --delete --exclude='.git' "$SOURCE/" "$STAGING/" > "$STAGING.source-compare.txt"
test ! -s "$STAGING.source-compare.txt" || {
  cat "$STAGING.source-compare.txt"; echo "error: staged tree mismatch"; exit 1;
}
test ! -e "$STAGING/KernelSU/.git"
mkdir -p "$STAGING/ci" "$STAGING/.github/workflows"
# ReSukiSU's archived Kbuild explicitly crashes without its own .git.
# Since the requested repo contains one ordinary full-source commit, preserve
# the archived Kbuild as evidence and make its historical version constants
# explicit in a direct source Kbuild. All other source stays unchanged.
python3 migration/p479_kernelsu_direct.py --root "$STAGING" --mode stage \
  --report "$STAGING/ci/P479-KernelSU-direct-source.json"
cp migration/p479_kernelsu_direct.py "$STAGING/ci/p479_kernelsu_direct.py"
python3 "$STAGING/ci/p479_kernelsu_direct.py" --root "$STAGING" --mode verify
! grep -Fq 'LOCAL_GIT_EXISTS' "$STAGING/KernelSU/kernel/Kbuild"
test -s "$STAGING/ci/P479-original-KernelSU.Kbuild"
cp "$CONFIG" "$STAGING/ci/P479.config"
cp "$CONFIG" "$STAGING/ci/build.config"
cp "$MANIFEST" "$STAGING/ci/P479-final-tree-manifest.json"
cp "$MANIFEST" "$STAGING/ci/build-manifest.json"
cp "$PROOF" "$STAGING/ci/P479-equivalence-proof.json"
cp migration/source-ci/direct-source-build.yml "$STAGING/.github/workflows/direct-source-build.yml"
cp migration/source-ci/source-safety-audit.yml "$STAGING/.github/workflows/source-safety-audit.yml"
# Record the frozen source-generation ancestry separately from P479 final
# .config; never present the Phase446S manifest as a P479 config manifest.
python3 - "$STAGING/ci/P479.config" "$STAGING/ci/P479-final-tree-manifest.json" "$STAGING/ci/build-manifest.json" <<'PY'
import hashlib,json,sys
from pathlib import Path
config,ancestor,output=map(Path,sys.argv[1:])
a=json.loads(ancestor.read_text())
out={
    "schema":"mangrove-p479-source-ancestry-v1",
    "stage":"P479-equivalent-source",
    "kernel_config_sha256":hashlib.sha256(config.read_bytes()).hexdigest(),
    "phase446wx_ancestry_manifest_sha256":hashlib.sha256(ancestor.read_bytes()).hexdigest(),
    "source_fingerprint_sha256":a["source_fingerprint_sha256"],
    "strict":a["strict"],
    "missing_required":a["missing_required"],
    "ancestry_strict_only":True,
    "flash_authorized":False,
}
output.write_text(json.dumps(out,sort_keys=True,indent=2)+"\n")
PY
cat > "$STAGING/ci/BASELINE-PROVENANCE.md" <<'NOTES'
# P479 verified Mangrove baseline

Complete source: Phase446WX artifact 12271681215 and the subsequent proven P447
through P479 source changes. Original run: 43638159300 at
e2e9f3fad600489deb8fa0816245a87cef6b9b95.
Evidence: ci/P479-equivalence-proof.json, with exact .config, System.map
symbols/addresses and allocated ELF section sizes plus compiled feature markers.
Source archive: legacy release phase446wx-source-backup.
Reference binaries: legacy release p479-equivalence-reference.

Permanent comparison proof: release p479-equivalence-evidence-44026270014.
Original P479 proof run: 44026270014 (source producer commit
5e5db938a24068ae5a804b003e5cbe16d7f31438).

IMPORTANT: strict equivalence proves exact .config, System.map symbol/addresses,
allocated ELF section sizes and required kernel Image markers, but the original
and rebuilt raw Image SHA256 differ. Original c1e29a64f611f402cdc8e5db1f42fea5b6ec9f48b19df60d5b9aa6da2d8585ae;
rebuilt 04bec126c1ae6d06e4ac43f417d1a7dfd22fa82638f995d41721f27a056a1bc7
from the authenticated full-source producer run 44038773282. The previous
strict-PASS build 44026270014 had a different rebuilt Image SHA256
2b094dc42cd6079ab5dd2092a69a68b2ae6a3676ffe8da7215db84f78a8c1070.
Do NOT report byte-for-byte Image identity, or infer flash authorization.
The verified source release tag points at main HEAD solely for GitHub workflow
file permissions; the actual source archive and proof identify its producer.
Verified source release producer: 44038773282, commit
5e6fb4713022f22b417a9e6581cf3c5d9c2b16f5.
Full source archive SHA256:
43ecd5698f319328290721c4f79d1dddfe7e8acb30f4ba1c3a47629f2115d9e3.


The archived ReSukiSU/KernelSU Kbuild originally required a separate nested
.git submodule and computed version 35171 from 4471 commits. Its exact original
Kbuild is preserved in ci/P479-original-KernelSU.Kbuild (SHA256 pinned).
The direct-source adaptation removes that prerequisite and retains the exact
compiled historical full version v4.2.0-rc3-239e1e88-dirty@ReSukiSU.
The adaptation report is ci/P479-KernelSU-direct-source.json. Future KernelSU
version changes require ordinary direct Git source commits, not .git submodules.

P479 generated build provenance is deliberately fixed using ci/P479-compile.h,
ci/P479-historical-manifest.h, and ci/P479-kheaders.tar.xz. The distinct real
Phase446WX fingerprint is separately preserved in ci/P479-native-WX-manifest.h.
The two fingerprint values are not interchangeable and MUST remain documented.

The entire kernel source, including KernelSU, is stored as one ordinary Git
commit and tagged p479-baseline. Future changes such as P480 A3c must be direct
source commits. No generated patch chains are used at build time.
The preserved ci/P479.config + ci/P479-final-tree-manifest.json record the
baseline. The active ci/build.config + ci/build-manifest.json may change in
future direct source commits, starting with P480 A3c.
NO FLASHING without separate authorization.
NOTES
if [ "$P479_MIGRATION_DRY_RUN" = 1 ]; then
  echo 'P479 dry run: no external repo creation, no credential and no push.'
else
  export GH_TOKEN="$SOURCE_PUSH_TOKEN"
  if ! gh repo view "$TARGET" --json name >/dev/null 2>&1; then
    gh repo create "$TARGET" --public
  fi
  gh auth setup-git
fi
cd "$STAGING"
git init -b main
git config user.name "Mangrove Source Baseline CI"
git config user.email "67099534+GiulianoB-1@users.noreply.github.com"
# A kernel tree legitimately has .gitignore rules for generated sources, headers
# and Android/KernelSU manager assets. An initial full-source baseline must not
# silently omit those files. The nested .git directories were excluded by rsync.
git add --all --force
python3 - <<'PY'
import subprocess
from pathlib import Path
root=Path('.')
tracked={
    p.decode('utf-8','surrogateescape')
    for p in subprocess.check_output(['git','ls-files','-z']).split(b'\0')
    if p
}
on_disk={
    str(p)
    for p in root.rglob('*')
    if '.git' not in p.parts and (p.is_file() or p.is_symlink())
}
missing=sorted(on_disk-tracked)
extra=sorted(tracked-on_disk)
assert not missing and not extra, (
    f'P479 source Git staging is incomplete: missing={missing[:15]} extra={extra[:15]}'
)
assert len(tracked)>60000, f'kernel source unexpectedly sparse: {len(tracked)} files'
assert 'include/generated/a52_446s_manifest.h' in tracked
assert 'ci/P479-native-WX-manifest.h' in tracked
assert 'ci/P479-historical-manifest.h' in tracked
assert 'KernelSU/.gitignore' in tracked
assert 'KernelSU/.gitattributes' in tracked
print('P479 full-source Git completeness verified:',len(tracked),'tracked files')
PY
if git diff --cached --quiet; then echo "error: empty source commit"; exit 1; fi
git commit -m "baseline(P479): complete equivalent kernel tree, direct-source builds"
git tag -a p479-baseline -m "Proven P479 source equivalent to run 43638159300 (NO FLASH)"
test "$(git rev-list --count HEAD)" -eq 1 || { echo '::error::Expected exactly one P479 baseline commit'; exit 1; }
test "$(git rev-parse p479-baseline^{commit})" = "$(git rev-parse HEAD)" || {
  echo '::error::Baseline tag not at the initial commit'; exit 1;
}
if [ "$P479_MIGRATION_DRY_RUN" = 1 ]; then
  printf 'P479 source-only cutover dry-run PASS, commit %s tracked files %s\n' \
    "$(git rev-parse HEAD)" "$(git ls-files | wc -l)"
  printf 'No new remote repo created. No source pushed. NO FLASH.\n'
  exit 0
fi
git remote add origin "https://github.com/$TARGET.git"
if [ -n "$(git ls-remote --heads --tags origin)" ]; then
  echo "error: destination has refs, refusing to overwrite"; exit 1
fi
git push origin HEAD:refs/heads/main refs/tags/p479-baseline
git ls-remote origin refs/heads/main refs/tags/p479-baseline
echo "Source baseline committed and tagged in $TARGET"
