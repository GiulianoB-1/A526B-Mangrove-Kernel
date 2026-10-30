#!/usr/bin/env bash
# P470-A0 EXPERIMENTAL real Qualcomm dataipa compile probe against exact G kernel.
# This does NOT modify the composed Mangrove tree and produces NO boot image.
set -Eeuo pipefail

if [ "$#" -ne 4 ]; then
  echo "usage: $0 COMPOSED_GKI_ROOT KBUILD_OUTPUT PINNED_DATAIPA_DONOR OUTPUT_VENDOR_HEADERS" >&2
  exit 2
fi
ROOT="$1"
BUILD="$2"
DONOR="$3"
HEADERS="$4"
export DONOR
EXPECTED_DATAIPA=c560cc3c2840fb0ebc55ceef5b27549c66143637
KERNEL_VENDOR_SHA=f438c918a464b82d4a637b5327dd1ed6e8b625dc
test -s "$ROOT/Makefile"
test -s "$BUILD/.config"
test "$(git -C "$DONOR" rev-parse HEAD)" = "$EXPECTED_DATAIPA"
grep -Fxq 'CONFIG_MODULES=y' "$BUILD/.config" || {
  echo "P470 A0 COMPILE BLOCKED: no module build support" >&2; exit 1;
}
if grep -Fxq 'CONFIG_IPA3=y' "$BUILD/.config"; then
  echo "P470 A0 REFUSE: production IPA already enabled in baseline" >&2
  exit 1
fi
mkdir -p "$HEADERS"
# Pin only vendor UAPI headers from the same Qualcomm kernel 5.10 line.
# Never import an entire, mutable donor branch into the baseline kernel.
for path in \
  include/linux/ipa.h \
  include/linux/msm_gsi.h \
  include/uapi/linux/msm_ipa.h \
  include/uapi/linux/msm_rmnet.h \
  include/uapi/linux/rmnet_ipa_fd_ioctl.h \
  include/uapi/linux/ipa_qmi_service_v01.h \
  include/soc/qcom/subsystem_notif.h \
  include/soc/qcom/subsystem_restart.h; do
  if [ ! -s "$ROOT/$path" ]; then
    mkdir -p "$HEADERS/$(dirname "$path")"
    curl --fail --location --retry 3 --silent --show-error \
      "https://raw.githubusercontent.com/CodeLinaro-mirror/la_kernel_msm-5.10/$KERNEL_VENDOR_SHA/$path" \
      -o "$HEADERS/$path"
    test -s "$HEADERS/$path"
  fi
done
# Adapt only the private donor workspace's Kbuild path for this out-of-tree
# compile experiment. No files in $ROOT, $BUILD/.config, or the boot are changed.
python3 - <<'PY'
import os
from pathlib import Path
p = Path(os.environ["DONOR"])
root = p / "Makefile"
s = root.read_text()
old = "obj-$(CONFIG_ARCH_QCOM) += drivers/platform/msm/"
assert s.count(old) == 1, "donor root Makefile drift"
root.write_text(s.replace(old, "obj-m += drivers/platform/msm/", 1))
nested = p / "drivers/platform/msm/Makefile"
s = nested.read_text()
old = "DATAIPADRVTOP = $(srctree)/techpack/dataipa/drivers/platform/msm"
assert s.count(old) == 1, "donor nested Makefile drift"
nested.write_text(s.replace(old, "DATAIPADRVTOP = $(M)/drivers/platform/msm", 1))
print("P470 A0 external-module Kbuild wiring staged outside GKI")
PY

echo "P470 A0 MODULE PROBE: real GSI + IPA3 + RMNET_IPA3 (NO BOOT)"
echo "P470 A0 DATAIPA_SHA=$EXPECTED_DATAIPA vendor_abi_sha=$KERNEL_VENDOR_SHA"
# The 5.10 techpack normally uses config/dataipa.h under ARCH_LAHAINA.
# This is an API-compatibility *compile probe*, not a deployable Kconfig
# replacement. Undefined exports and vendor-only APIs must fail the probe.
make -C "$ROOT" O="$BUILD" ARCH=arm64 \
  CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu- \
  LLVM=1 LLVM_IAS=1 \
  M="$DONOR" \
  CONFIG_GSI=m CONFIG_IPA3=m CONFIG_RMNET_IPA3=y \
  KCFLAGS="-DCONFIG_IPA3 -I$HEADERS/include -I$HEADERS/include/uapi -include $DONOR/config/dataipa.h" \
  -j"$(nproc)" modules
echo "P470 A0 MODULE SOURCE COMPILE PASS (NOT A HARDWARE/IPA READY PASS)"
