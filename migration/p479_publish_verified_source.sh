#!/usr/bin/env bash
# Publish verified P479 full-source Actions fallback artifact as a permanent
# release, without building or flashing. Only a single pinned producer is allowed.
set -Eeuo pipefail
: "${GH_TOKEN:?GitHub release contents:write token required}"
: "${GITHUB_REPOSITORY:?GitHub repository required}"
P479_SOURCE_RUN_ID=44038773282
test "$GITHUB_REPOSITORY" = "GiulianoB-1/A526B-Mangrove-Kernel"
EXPECTED_BUILD_SHA=5e6fb4713022f22b417a9e6581cf3c5d9c2b16f5
EXPECTED_BRANCH=agent/p479-wx-archive-fallback-no-flash
ARCHIVE="P479-VERIFIED-FULL-SOURCE-FALLBACK-${P479_SOURCE_RUN_ID}"
META="$(gh api "repos/${GITHUB_REPOSITORY}/actions/runs/${P479_SOURCE_RUN_ID}")"
export META EXPECTED_BUILD_SHA EXPECTED_BRANCH
python3 - <<'PY'
import json,os
j=json.loads(os.environ["META"])
assert j["status"]=="completed", "Source-producing runner not yet complete"
assert j["head_sha"]==os.environ["EXPECTED_BUILD_SHA"], "Unreviewed source producer commit"
assert j["head_branch"]==os.environ["EXPECTED_BRANCH"], "Wrong source recovery branch"
assert j["event"]=="push", "Unexpected source workflow trigger"
print("P479 verified source producer:",j["id"],j["head_sha"],j["conclusion"])
PY
ROOT="${RUNNER_TEMP:-$PWD}/p479-permanent-publish"
test ! -e "$ROOT" || { echo "::error::Refusing unverified staging"; exit 1; }
mkdir -p "$ROOT"
gh run download "$P479_SOURCE_RUN_ID" --repo "$GITHUB_REPOSITORY" \
  --name "$ARCHIVE" --dir "$ROOT"
SUMS="$(find "$ROOT" -type f -name SHA256SUMS -print)"
test "$(printf '%s\n' "$SUMS" | wc -l)" -eq 1 || {
  echo "::error::Missing or duplicate source checksum manifest"; exit 1;
}
ASSETS="$(dirname "$SUMS")"
cd "$ASSETS"
for item in P479-verified-full-source.tar.zst P479.config \
            P479-equivalence-proof.json P479-final-tree-manifest.json SHA256SUMS; do
  test -s "$item" || { echo "::error::Missing P479 source file: $item"; exit 1; }
done
sha256sum -c SHA256SUMS
python3 - <<'PY'
from pathlib import Path
import json,hashlib
p=json.loads(Path("P479-equivalence-proof.json").read_text())
assert p["status"]=="PASS" and p["errors"]==[]
assert p["baseline_run"]==43638159300
assert p["baseline_sha"]=="e2e9f3fad600489deb8fa0816245a87cef6b9b95"
assert p["source_restore"]=="phase446wx-source-backup/12271681215"
checks=p["checks"]
for key in ("reference_config_sha","reference_system_map_sha","config_exact",
    "system_map_symbols_and_addresses_exact",
    "image_allocated_elf_section_sizes_identical","native_h4_linked"):
    assert checks[key]["pass"] is True,key
for key,value in checks.items():
    if key.startswith(("marker:","config:")):
        assert value["pass"] is True,key
assert checks["config_exact"]["details"]["built_sha256"]=="62e75568506c051408588d2eb77fa94fb8ada762fcff997739a5b595a742d50b"
assert checks["system_map_symbols_and_addresses_exact"]["details"]["built_sha256"]=="26ae9bda166d764bf695d6c51b8799632bc6f1ea276747a9f8fd1d0caf6d3a3e"
assert hashlib.sha256(Path("P479.config").read_bytes()).hexdigest()=="62e75568506c051408588d2eb77fa94fb8ada762fcff997739a5b595a742d50b"
assert p["built_image"]["sha256"]=="2b094dc42cd6079ab5dd2092a69a68b2ae6a3676ffe8da7215db84f78a8c1070"
assert p["original_image_sha256"]=="c1e29a64f611f402cdc8e5db1f42fea5b6ec9f48b19df60d5b9aa6da2d8585ae"
assert p["image_hash_identical"] is False, "Never claim byte-identical Image"
m=json.loads(Path("P479-final-tree-manifest.json").read_text())
assert m["strict"] is True and not m["missing_required"]
print("P479 release proof PASS; raw Image is NOT byte-identical")
PY
tar --use-compress-program=zstd -tf P479-verified-full-source.tar.zst > filelist.txt
for path in ./Makefile ./KernelSU/kernel/Kbuild ./ci/P479-kheaders.tar.xz \
            ./ci/P479-compile.h ./ci/P479-historical-manifest.h \
            ./ci/P479-native-WX-manifest.h ./include/generated/a52_446s_manifest.h; do
  grep -Fxq "$path" filelist.txt || {
    echo "::error::Full source backup missing $path"; exit 1;
  }
done
if grep -Eq '(^|/)\.git(/|$)' filelist.txt; then
  echo "::error::Nested .git in source backup"; exit 1;
fi
# GitHub's release API protects commits that modify .github/workflows
# relative to the default branch. GITHUB_TOKEN cannot have Workflows:write,
# so a release tag targeting the SOURCE producer SHA gets HTTP 403. Anchor
# only the release TAG to the current default HEAD, while cryptographically
# and explicitly pinning the actual P479 source producer SHA and all assets.
DEFAULT_BRANCH="$(gh api "repos/$GITHUB_REPOSITORY" --jq .default_branch)"
test "$DEFAULT_BRANCH" = main || {
  echo "::error::Unexpected default release anchor: $DEFAULT_BRANCH"; exit 1;
}
DEFAULT_SHA="$(gh api "repos/$GITHUB_REPOSITORY/branches/$DEFAULT_BRANCH" --jq .commit.sha)"
printf 'Release tag will point to default branch %s %s; exact P479 source producer remains %s\n' \
  "$DEFAULT_BRANCH" "$DEFAULT_SHA" "$EXPECTED_BUILD_SHA"
if gh release view p479-verified-source-baseline --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  # Treat duplicate publication as success only if the immutable release
  # already contains byte-for-byte the exact proven archive and all evidence.
  mkdir -p previous
  gh release download p479-verified-source-baseline --repo "$GITHUB_REPOSITORY" \
    --dir previous --pattern 'P479*' --pattern SHA256SUMS
  (cd previous && sha256sum -c SHA256SUMS)
  for item in P479-verified-full-source.tar.zst P479.config \
              P479-equivalence-proof.json P479-final-tree-manifest.json SHA256SUMS; do
    cmp "previous/$item" "$item" || {
      echo "::error::Existing permanent P479 release differs; no overwrite"; exit 1;
    }
  done
  echo "P479 permanent source release already exists with identical audited assets, no overwrite"
  exit 0
fi
cat > README.txt <<'NOTES'
P479 equivalent complete kernel source (with KernelSU), produced by a
compiled and strict-gated restoration of Phase446WX.
Source run 44038773282; reference P479 run 43638159300.
The GitHub RELEASE TAG points at the repository main branch HEAD for GitHub
Actions release permissions only. It is NOT the P479 source snapshot. The exact
P479 source producer commit is 5e6fb4713022f22b417a9e6581cf3c5d9c2b16f5,
with all source and binary evidence pinned in the SHA256-verified release assets.

Strict equivalence: exact config, exact System.map symbols and addresses,
identical allocated ELF section sizes, and compiled safety markers.

IMPORTANT: Rebuilt and original Image SHA256 differ. NOT bit-identical.
Proof JSON preserves both hashes. NO FLASH or P480 authorization.
Original legacy releases and archives are preserved.
NOTES
gh release create p479-verified-source-baseline \
  --repo "$GITHUB_REPOSITORY" --target "$DEFAULT_SHA" \
  --title "P479 strict equivalence, complete verified source (NO FLASH)" \
  --notes-file README.txt --latest=false \
  P479-verified-full-source.tar.zst P479.config \
  P479-equivalence-proof.json P479-final-tree-manifest.json SHA256SUMS
echo "P479 source release publication PASS (no flash authorization)"
