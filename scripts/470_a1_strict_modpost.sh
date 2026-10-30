#!/usr/bin/env bash
# P470-A1: *actual* kernel export-resolution probe, NO FLASH.
# Must run AFTER the final G Image/vmlinux link against its Module.symvers.
# A successful P470-A0 pre-link modpost lacked vmlinux symbol information.
set -Eeuo pipefail
if [ "$#" -ne 5 ]; then
  echo "usage: $0 COMPOSED_GKI_ROOT KBUILD_OUTPUT PINNED_DATAIPA_DONOR VENDOR_HEADERS REPORT_DIR" >&2
  exit 2
fi
ROOT="$(realpath "$1")"
BUILD="$(realpath "$2")"
DONOR="$(realpath "$3")"
HEADERS="$(realpath "$4")"
REPORT="$5"
mkdir -p "$REPORT"
REPORT="$(realpath "$REPORT")"
UNDEFINED="$REPORT/P470-A0-UNDEFINED-SYMBOLS.txt"
LOG="$REPORT/P470-A1-STRICT-MODPOST.log"
: > "$UNDEFINED"
: > "$LOG"
EXPECTED_DATAIPA=c560cc3c2840fb0ebc55ceef5b27549c66143637
test "$(git -C "$DONOR" rev-parse HEAD)" = "$EXPECTED_DATAIPA"
test -s "$BUILD/vmlinux"
test -s "$BUILD/arch/arm64/boot/Image"
test -s "$BUILD/vmlinux.symvers" || {
  echo "P470-A1 REFUSE: no linked vmlinux.symvers" | tee -a "$LOG"
  exit 1
}
test -s "$HEADERS/include/linux/ipa.h"
test -s "$PWD/scripts/470_a1_lagoon_dataipa_config.h"
# The linked Image and vmlinux must be present, not just modules_prepare.
# Kbuild's in-tree modules target produces Module.symvers containing the
# vmlinux exports. No synthesized symbols or vendor-only fake providers.
echo "P470-A1 building real in-tree modules/Module.symvers after Image link" | tee -a "$LOG"
make -C "$ROOT" O="$BUILD" ARCH=arm64 \
  CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu- \
  LLVM=1 LLVM_IAS=1 -j"$(nproc)" modules 2>&1 | tee -a "$LOG"
test -s "$BUILD/Module.symvers" || {
  echo "P470-A1 REFUSE: real Module.symvers missing after make modules" | tee -a "$LOG"
  exit 1
}
# Assert real core exports are present: a nonempty but unrelated symvers
# file must never accidentally satisfy the API-closure test.
grep -Eq '[[:space:]]module_layout[[:space:]]' "$BUILD/Module.symvers" || {
  echo "P470-A1 REFUSE: Module.symvers lacks module_layout kernel export" | tee -a "$LOG"
  exit 1
}
# Do not allow a clean cached .ko to bypass modpost. Force actual modpost
# to resolve the modules' symbols against the real linked kernel exports.
rm -f "$DONOR/Module.symvers"
unset KBUILD_MODPOST_WARN KBUILD_MODPOST_NOFINAL KBUILD_MODPOST_NOERROR
echo "P470-A1 strict external IPA/GSI modpost: no WARN downgrades" | tee -a "$LOG"
set +e
make -C "$ROOT" O="$BUILD" ARCH=arm64 \
  CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu- \
  LLVM=1 LLVM_IAS=1 \
  M="$DONOR" \
  CONFIG_GSI=m CONFIG_IPA3=m CONFIG_RMNET_IPA3=y \
  KCFLAGS="-DP470_A0_COMPILE_ONLY=1 -DCONFIG_IPA3 -I$HEADERS/include -I$HEADERS/include/uapi -include $PWD/scripts/470_a1_lagoon_dataipa_config.h" \
  -k -j"$(nproc)" modules 2>&1 | tee -a "$LOG"
rc=${PIPESTATUS[0]}
set -e
# Capture every modpost undefined line, preserving the original symbol
# spelling and source object. Do not claim a successful probe if modpost
# errors out for another reason.
grep -Ei '(^|[[:space:]])(ERROR|WARNING): modpost:.*undefined!|undefined symbol' "$LOG" \
  | sort -u > "$UNDEFINED" || true
if [ "$rc" -ne 0 ]; then
  echo "P470-A1 STRICT MODPOST FAILED rc=$rc undefined_lines=$(wc -l < "$UNDEFINED")" | tee -a "$LOG"
  if [ ! -s "$UNDEFINED" ]; then
    echo "P470-A1: modpost/compile error without an undefined! diagnostic; inspect full log" >> "$UNDEFINED"
  fi
  exit "$rc"
fi
if grep -Eq 'Symbol info of vmlinux is missing|Unresolved symbol check will be entirely skipped' "$LOG"; then
  echo "P470-A1 REFUSE: modpost skipped vmlinux export checks" | tee -a "$LOG"
  exit 1
fi
if [ -s "$UNDEFINED" ]; then
  echo "P470-A1 REFUSE: modpost emitted unresolved symbols despite exit 0" | tee -a "$LOG"
  exit 1
fi
# Verify each originally missing IPA public API comes from the actual
# pinned 5.10 ipa_fmwk.ko provider, NOT from a shim, fake KBUILD_EXTRA_SYMBOLS
# file, warning downgrade, or exported placeholder in the base kernel.
test -s "$DONOR/drivers/platform/msm/ipa_fmwk/ipa_fmwk.ko" || {
  echo "P470-A1 REFUSE: pinned IPA framework module was not built" | tee -a "$LOG"
  exit 1
}
for sym in \
    ipa_mhi_handle_ipa_config_req ipa_setup_sys_pipe \
    ipa_register_ipa_ready_cb ipa_send_msg ipa_get_ep_mapping \
    ipa_get_hw_type ipa_wigig_save_regs ipa_fmwk_register_ipa; do
  if ! awk -F '\t' -v symbol="$sym" \
      '$2 == symbol && $3 ~ /\/ipa_fmwk\/ipa_fmwk$/ {found=1} END {exit !found}' \
      "$DONOR/Module.symvers"; then
    echo "P470-A1 REFUSE: $sym not exported by real ipa_fmwk module" | tee -a "$LOG"
    exit 1
  fi
done
echo "P470-A1 REAL IPA FRAMEWORK: all eight missing APIs resolved by pinned 5.10 provider" | tee -a "$LOG"
echo "P470-A1 STRICT MODPOST PASS: actual linked-kernel exports checked; hardware still blocked" | tee -a "$LOG"
