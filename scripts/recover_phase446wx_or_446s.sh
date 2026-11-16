#!/usr/bin/env bash
# P479 equivalence recovery. Default WX, explicit 446s mode preserves ORIGINAL legacy restore logic.
# Never flash or publish a P480 candidate from this transitional path.
set -Eeuo pipefail
MODE="${MANGROVE_RESTORE_MODE:-wx}"
case "$MODE" in
  wx)
    set -Eeuo pipefail
    mkdir -p workspace/phase446s-inputs workspace/phase446s-boot gki/common
    gh release download phase446wx-source-backup --repo "$GITHUB_REPOSITORY" --pattern phase446wx-artifact-12271681215.zip --dir workspace
    printf '%s  %s\n' 4a67e19ed23935ea6596a76cfc5f28d434cd37b7061ab7bc520a7a0ce8137a6b workspace/phase446wx-artifact-12271681215.zip | sha256sum -c -
    unzip -q workspace/phase446wx-artifact-12271681215.zip -d workspace/phase446s-inputs
    printf '%s  %s\n' d57c5c82bc938a6d582f0d676eddc3fdb9c6d0689bf2de6c7b5cd9e8538e13a8 workspace/phase446s-inputs/final-patched-gki-source.tar.zst | sha256sum -c -
    printf '%s  %s\n' 26f64921f357bd66469f04fc7fcaea4e60a47f8ce49980e3923f4c91cf28a737 workspace/phase446s-inputs/final.config | sha256sum -c -
    python3 - <<'PY'
    from pathlib import Path
    import hashlib,json,os
    base=Path('workspace/phase446s-inputs')
    manifest=json.loads((base/'final-tree-manifest.json').read_text())
    assert manifest['strict'] is True and not manifest['missing_required']
    assert manifest['source_fingerprint_sha256']=='fb330e2da844e7b8b8b3043f7de3fdad5c6c2f9c3caae7c58ce6ad10a47eca8e'
    assert manifest['kernel_config_sha256']=='26f64921f357bd66469f04fc7fcaea4e60a47f8ce49980e3923f4c91cf28a737'
    assert manifest['workflow_id']=='39431575680'
    assert manifest['workflow_commit_sha']=='9314c6da8c4bc47b56e3539e5f5afc1d42bd4c9e'
    assert manifest['gki_common_pinned_sha']==os.environ['GKI_COMMON_SHA']
    ident=json.loads((base/'FINAL-BUILD-INPUTS.json').read_text())
    assert ident['schema']=='a52-final-build-inputs-v1' and ident['phase']=='446S'
    assert ident['pinned_gki_git_head']==os.environ['GKI_COMMON_SHA']
    for name,info in ident['files'].items():
        p=base/name
        assert p.is_file(),name
        assert p.stat().st_size==info['bytes'],name
        assert hashlib.sha256(p.read_bytes()).hexdigest()==info['sha256'],name
    print('PINNED WX SOURCE ZIP / TAR / CONFIG / TREE FINGERPRINT / PRODUCER PASS')
    PY
    tar --use-compress-program=zstd -xf workspace/phase446s-inputs/final-patched-gki-source.tar.zst -C gki/common
    test -s gki/common/Makefile
    git -C gki/common init -q
    git -C gki/common remote add origin https://android.googlesource.com/kernel/common
    if ! git -C gki/common -c protocol.version=2 fetch --depth=1 --filter=blob:none --no-tags origin "refs/tags/$GKI_COMMON_TAG"; then
      git -C gki/common fetch --depth=1 --no-tags origin "refs/tags/$GKI_COMMON_TAG"
    fi
    test "$(git -C gki/common rev-parse 'FETCH_HEAD^{commit}')" = "$GKI_COMMON_SHA"
    git -C gki/common reset --mixed "$GKI_COMMON_SHA"
    test "$(git -C gki/common rev-parse HEAD)" = "$GKI_COMMON_SHA"
    grep -Fq 'A52_PHASE446R_COMMIT_GEM_LIFETIME_V1' gki/common/drivers/a52_display/msm/msm_atomic.c
    gh release download phase446wx-source-backup --repo "$GITHUB_REPOSITORY" --pattern phase446wx-boot-template-12272271056.zip --dir workspace
    printf '%s  %s\n' 9586df44718ae3a84178ea43e4632db3c988c1652564c4586ed217e84c918efe workspace/phase446wx-boot-template-12272271056.zip | sha256sum -c -
    unzip -q workspace/phase446wx-boot-template-12272271056.zip -d workspace/phase446s-boot
    test "$(find workspace/phase446s-boot -name boot-f0bisect-gki-p6-v1.img -type f | wc -l)" -eq 1
    SOURCE="$(find workspace/phase446s-boot -name boot-f0bisect-gki-p6-v1.img -type f -print -quit)"
    printf '%s  %s\n' ef0f35ad261a072f301c6f52521c4ff33c59595dd09f4c42df55e7642bbc7b09 "$SOURCE" | sha256sum -c -
    test "$(stat -c %s "$SOURCE")" -eq 100663296
    python3 - "$SOURCE" <<'PY'
    import runpy,hashlib,json,sys
    parse=runpy.run_path('scripts/38_repack_a52_p1_boot.py')['parse_boot']
    dtb=parse(open(sys.argv[1],'rb').read())['dtb']
    ident=json.load(open('workspace/phase446s-inputs/FINAL-BUILD-INPUTS.json'))
    assert hashlib.sha256(dtb).hexdigest()==ident['files']['boot-final.dtb']['sha256']
    print('PINNED WX BOOT DTB PASS')
    PY
    mkdir -p phase429-gki-out/{package,compile,config} workspace/gki-phase199-out
    cp "$SOURCE" phase429-gki-out/package/boot-phase429-apex-sf-focused-census-v1.img
    cp workspace/phase446s-inputs/final.config workspace/gki-phase199-out/.config
    cp workspace/phase446s-inputs/final.config phase429-gki-out/config/final.config
    make -C "$PWD/gki/common" O="$PWD/workspace/gki-phase199-out" ARCH=arm64 \
      CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu- LLVM=1 LLVM_IAS=1 olddefconfig
    cmp workspace/phase446s-inputs/final.config workspace/gki-phase199-out/.config
    printf 'MANGROVE_RESTORE_BASE=wx\n' >> "$GITHUB_ENV"
    echo 'P479 equivalent restore: exact WX full source and matching boot SHA pins PASS' >> "$GITHUB_STEP_SUMMARY"
    ;;
  446s)
    echo "Original Phase446S SHA-pinned restore (requires archived inputs + boot)"
    set -Eeuo pipefail
    mkdir -p workspace/phase446s-inputs workspace/phase446s-boot gki/common
    API="https://api.github.com/repos/$GITHUB_REPOSITORY/actions/artifacts"
    curl --fail --location --retry 3 --retry-all-errors --silent --show-error \
      -H "Authorization: Bearer $GH_TOKEN" -H 'Accept: application/vnd.github+json' \
      "$API/12106509365/zip" -o workspace/phase446s-inputs.zip
    printf '%s  %s\n' 2c7e02b424df29f17ef16087864dacd2068293fb70d6be823de0c85ab7715533 workspace/phase446s-inputs.zip | sha256sum -c -
    unzip -q workspace/phase446s-inputs.zip -d workspace/phase446s-inputs
    python3 - <<'PY'
    from pathlib import Path
    import hashlib,json,os
    base=Path('workspace/phase446s-inputs')
    ident=json.loads((base/'FINAL-BUILD-INPUTS.json').read_text())
    assert ident['phase']=='446S' and ident['schema']=='a52-final-build-inputs-v1'
    print('Phase446S exported git HEAD:',ident['pinned_gki_git_head'])
    assert ident['boot_image_sha256']=='e69d7d9d676a2419a92683a5ee5c9bbf091b2a744d92381dbab3e89a661f646b'
    assert 'final-patched-gki-source.tar.zst' in ident['files']
    for name,expect in ident['files'].items():
        p=base/name
        assert p.is_file(),name
        h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
        assert p.stat().st_size==expect['bytes'] and h.hexdigest()==expect['sha256'],name
    manifest=json.loads((base/'final-tree-manifest.json').read_text())
    assert manifest['strict'] is True and not manifest['missing_required']
    assert manifest['gki_common_pinned_sha']==os.environ['GKI_COMMON_SHA']
    assert manifest['gki_common_actual_git_head']==ident['pinned_gki_git_head']
    assert manifest['source_fingerprint_sha256']=='21664e4ad870aa8b68bf2e54fd4aa4d8fb321120f8b2712d8663d240e933e48c'
    print('P446T PHASE446S COMPLETE SOURCE VERIFIED')
    PY
    tar --use-compress-program=zstd -xf workspace/phase446s-inputs/final-patched-gki-source.tar.zst -C gki/common
    test -s gki/common/Makefile
    git -C gki/common init -q
    git -C gki/common remote add origin https://android.googlesource.com/kernel/common
    if ! git -C gki/common -c protocol.version=2 fetch --depth=1 --filter=blob:none --no-tags origin "refs/tags/$GKI_COMMON_TAG"; then
      git -C gki/common fetch --depth=1 --no-tags origin "refs/tags/$GKI_COMMON_TAG"
    fi
    test "$(git -C gki/common rev-parse 'FETCH_HEAD^{commit}')" = "$GKI_COMMON_SHA"
    git -C gki/common reset --mixed "$GKI_COMMON_SHA"
    test "$(git -C gki/common rev-parse HEAD)" = "$GKI_COMMON_SHA"
    grep -Fq 'A52_PHASE446R_COMMIT_GEM_LIFETIME_V1' gki/common/drivers/a52_display/msm/msm_atomic.c
    curl --fail --location --retry 3 --retry-all-errors --silent --show-error \
      -H "Authorization: Bearer $GH_TOKEN" -H 'Accept: application/vnd.github+json' \
      "$API/12106519108/zip" -o workspace/phase446s-boot.zip
    printf '%s  %s\n' 406a9c65e1d6550869b4628f7bd06694b03dd486982831bc8a6790c3a1bdc383 workspace/phase446s-boot.zip | sha256sum -c -
    unzip -q workspace/phase446s-boot.zip -d workspace/phase446s-boot
    test "$(find workspace/phase446s-boot -name 'boot-f0bisect-gki-p6-v1.img' -type f | wc -l)" -eq 1
    SOURCE="$(find workspace/phase446s-boot -name 'boot-f0bisect-gki-p6-v1.img' -type f -print -quit)"
    printf '%s  %s\n' e69d7d9d676a2419a92683a5ee5c9bbf091b2a744d92381dbab3e89a661f646b "$SOURCE" | sha256sum -c -
    test "$(stat -c '%s' "$SOURCE")" -eq 100663296
    python3 - "$SOURCE" <<'PY'
    import runpy,hashlib,json,sys
    parse=runpy.run_path('scripts/38_repack_a52_p1_boot.py')['parse_boot']
    dtb=parse(open(sys.argv[1],'rb').read())['dtb']
    manifest=json.load(open('workspace/phase446s-inputs/FINAL-BUILD-INPUTS.json'))
    assert hashlib.sha256(dtb).hexdigest()==manifest['files']['boot-final.dtb']['sha256']
    print('P446T BOOT DTB VERIFIED')
    PY
    mkdir -p phase429-gki-out/{package,compile,config} workspace/gki-phase199-out
    cp "$SOURCE" phase429-gki-out/package/boot-phase429-apex-sf-focused-census-v1.img
    cp workspace/phase446s-inputs/final.config workspace/gki-phase199-out/.config
    cp workspace/phase446s-inputs/final.config phase429-gki-out/config/final.config
    make -C "$PWD/gki/common" O="$PWD/workspace/gki-phase199-out" ARCH=arm64 \
      CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu- \
      LLVM=1 LLVM_IAS=1 olddefconfig
    cmp workspace/phase446s-inputs/final.config workspace/gki-phase199-out/.config
    echo 'P446T exact Phase446S source recovery PASS' >> "$GITHUB_STEP_SUMMARY"
    
    printf 'MANGROVE_RESTORE_BASE=446s\n' >> "$GITHUB_ENV"
    ;;
  *)
    echo "::error::Invalid restore mode: $MODE"; exit 1
    ;;
esac
