#!/usr/bin/env bash
# P470-A2: REAL, unstubbed Qualcomm 5.10 IPA/GSI ABI probe. NO FLASH.
# Run after the A1 post-Image strict gate, using the same linked kernel
# Module.symvers, but force a rebuild WITHOUT P470_A0_COMPILE_ONLY.
set -Eeuo pipefail
if [[ $# -ne 5 ]]; then
  echo "usage: $0 GKI_ROOT KBUILD_OUT PINNED_DATAIPA VENDOR_HEADERS REPORT_DIR" >&2
  exit 2
fi
ROOT="$(realpath "$1")"
BUILD="$(realpath "$2")"
DONOR="$(realpath "$3")"
HEADERS="$(realpath "$4")"
mkdir -p "$5"
REPORT="$(realpath "$5")"
LOG="$REPORT/P470-A2-REAL-ABI-MODPOST.log"
ERRORS="$REPORT/P470-A2-REAL-ABI-ERRORS.txt"
: > "$LOG"
: > "$ERRORS"
test -s "$BUILD/Module.symvers"
test -s "$BUILD/vmlinux"
test -s "$BUILD/arch/arm64/boot/Image"
test -s "$DONOR/drivers/platform/msm/ipa_fmwk/ipa_fmwk.c"
cmp "$PWD/vendor/p470/ipa_fmwk.c" "$DONOR/drivers/platform/msm/ipa_fmwk/ipa_fmwk.c"
test "$(git -C "$DONOR" rev-parse HEAD)" = c560cc3c2840fb0ebc55ceef5b27549c66143637
# Check A0 really compiled out these hazardous operations, and A2 must
# compile the corresponding unguarded branches, not silently accept stubs.
grep -Fq 'qcom_scm_mem_protect_region_id(' "$DONOR/drivers/platform/msm/ipa/ipa_v3/ipa.c"
grep -Fq 'qcom_scm_get_sec_dump_state(' "$DONOR/drivers/platform/msm/ipa/ipa_v3/ipa.c"
# Replace the seven ABI-incompatible vendor get_attr calls with an accurate,
# fail-closed GKI domain-type query. A Lagoon "fastmap" DT request remains
# unsupported and MUST fail on hardware: this is a no-flash ABI discovery step.
python3 scripts/470_a2_smmu_abi_preflight.py --donor "$DONOR" \
    --report "$REPORT/P470-A2-IOMMU-ABI-PREFLIGHT.json" 2>&1 | tee -a "$LOG"
grep -Fq 'P470_A2_IOMMU_UNSUPPORTED_FASTMAP_V1' "$DONOR/drivers/platform/msm/ipa/ipa_v3/ipa.c"
grep -Fq 'return -EOPNOTSUPP;' "$DONOR/drivers/platform/msm/ipa/ipa_v3/ipa.c"
unset KBUILD_MODPOST_WARN KBUILD_MODPOST_NOFINAL KBUILD_MODPOST_NOERROR KBUILD_EXTRA_SYMBOLS
echo 'P470-A2 UNSTUBBED START: NO P470_A0_COMPILE_ONLY; genuine SCM and SMMU compilation is mandatory' | tee -a "$LOG"
# A1 produced .o files with P470_A0_COMPILE_ONLY. Drop every cached donor
# .o/.ko/.cmd first; only rebuilding with a different KCFLAGS is insufficient
# proof when cross-directory Kbuild caches are involved.
make -C "$ROOT" O="$BUILD" ARCH=arm64 \
    CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu- \
    LLVM=1 LLVM_IAS=1 M="$DONOR" clean 2>&1 | tee -a "$LOG"
# Separate A2 objects must be checked against the post-link kernel symbol
# exports. Preserve errors, no fake qcom_scm returns, no SMMU bypass.
set +e
make -C "$ROOT" O="$BUILD" ARCH=arm64 \
    CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu- \
    LLVM=1 LLVM_IAS=1 \
    M="$DONOR" CONFIG_GSI=m CONFIG_IPA3=m CONFIG_RMNET_IPA3=y \
    KCFLAGS="-DP470_A2_UNSTUBBED=1 -DCONFIG_IPA3 -I$HEADERS/include -I$HEADERS/include/uapi -include $PWD/scripts/470_a1_lagoon_dataipa_config.h" \
    -k -j"$(nproc)" modules 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e
grep -Ei '(^|[[:space:]])(error:|ERROR: modpost:)|undefined!|no member named|use of undeclared identifier' "$LOG" \
    | sort -u > "$ERRORS" || true
if [[ $rc -ne 0 ]]; then
  echo "P470-A2 BLOCKED: real, unstubbed module compilation/modpost rc=$rc; NO FLASH" | tee -a "$LOG"
  exit "$rc"
fi
if grep -Eq 'Symbol info of vmlinux is missing|Unresolved symbol check will be entirely skipped|WARNING: modpost:.*undefined' "$LOG"; then
  echo 'P470-A2 REFUSE: kernel export closure was not checked' | tee -a "$LOG"
  exit 1
fi
for mod in "$DONOR/drivers/platform/msm/ipa/ipam.ko" \
           "$DONOR/drivers/platform/msm/gsi/gsim.ko" \
           "$DONOR/drivers/platform/msm/ipa_fmwk/ipa_fmwk.ko"; do
  test -s "$mod" || { echo "P470-A2 REFUSE: missing real module $mod" | tee -a "$LOG"; exit 1; }
done
echo 'P470-A2 UNSTUBBED ABI PASS: real SCM, truthful translated DMA, vendor fastmap REFUSED; NOT hardware-ready; NO FLASH' | tee -a "$LOG"
