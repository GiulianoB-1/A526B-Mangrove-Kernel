#!/usr/bin/env bash
# Migrate to a one-commit P479 kernel source repository ONLY after P479 equivalence PASS.
# No old patch-generator chain, no flashing, no overwrite of an existing repo.
set -Eeuo pipefail
: "${P479_SOURCE_ROOT:?verified P479 source directory required}"
: "${P479_CONFIG:?final P479 .config required}"
: "${P479_FINAL_TREE_MANIFEST:?P479 final-tree.json required}"
: "${P479_EQUIVALENCE_REPORT:?successful proof JSON required}"
: "${SOURCE_PUSH_TOKEN:?token with repo create/push permissions required}"
TARGET="GiulianoB-1/A526B-Mangrove-Source"
SOURCE="$(realpath "$P479_SOURCE_ROOT")"
CONFIG="$(realpath "$P479_CONFIG")"
MANIFEST="$(realpath "$P479_FINAL_TREE_MANIFEST")"
PROOF="$(realpath "$P479_EQUIVALENCE_REPORT")"
test -s "$SOURCE/Makefile"
test -d "$SOURCE/KernelSU"
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
assert m['kernel_config_sha256']==actual, 'manifest config identity differs'
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
cp "$CONFIG" "$STAGING/ci/P479.config"
cp "$MANIFEST" "$STAGING/ci/P479-final-tree-manifest.json"
cp "$PROOF" "$STAGING/ci/P479-equivalence-proof.json"
cp migration/source-ci/direct-source-build.yml "$STAGING/.github/workflows/direct-source-build.yml"
cp migration/source-ci/source-safety-audit.yml "$STAGING/.github/workflows/source-safety-audit.yml"
cat > "$STAGING/ci/BASELINE-PROVENANCE.md" <<'NOTES'
# P479 verified Mangrove baseline

Complete source: Phase446WX artifact 12271681215 and the subsequent proven P447
through P479 source changes. Original run: 43638159300 at
e2e9f3fad600489deb8fa0816245a87cef6b9b95.
Evidence: ci/P479-equivalence-proof.json, with exact .config, System.map
symbols/addresses and allocated ELF section sizes plus compiled feature markers.
Source archive: legacy release phase446wx-source-backup.
Reference binaries: legacy release p479-equivalence-reference.

The entire kernel source, including KernelSU, is stored as one ordinary Git
commit and tagged p479-baseline. Future changes such as P480 A3c must be direct
source commits. No generated patch chains are used at build time.
NO FLASHING without separate authorization.
NOTES
export GH_TOKEN="$SOURCE_PUSH_TOKEN"
if ! gh repo view "$TARGET" --json name >/dev/null 2>&1; then
  gh repo create "$TARGET" --public
fi
gh auth setup-git
cd "$STAGING"
git init -b main
git config user.name "Mangrove Source Baseline CI"
git config user.email "67099534+GiulianoB-1@users.noreply.github.com"
git add --all
if git diff --cached --quiet; then echo "error: empty source commit"; exit 1; fi
git commit -m "baseline(P479): complete equivalent kernel tree, direct-source builds"
git tag -a p479-baseline -m "Proven P479 source equivalent to run 43638159300 (NO FLASH)"
git remote add origin "https://github.com/$TARGET.git"
if [ -n "$(git ls-remote --heads --tags origin)" ]; then
  echo "error: destination has refs, refusing to overwrite"; exit 1
fi
git push origin HEAD:refs/heads/main refs/tags/p479-baseline
git ls-remote origin refs/heads/main refs/tags/p479-baseline
echo "Source baseline committed and tagged in $TARGET"
