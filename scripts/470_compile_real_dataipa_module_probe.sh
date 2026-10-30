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
  include/linux/ipa_mhi.h \
  include/linux/ipa_uc_offload.h \
  include/linux/ipa_wdi3.h \
  include/linux/ipa_wigig.h \
  include/linux/ipa_usb.h \
  include/linux/ipa_fmwk.h \
  include/linux/ipa_qdss.h \
  include/linux/ipa_odu_bridge.h \
  include/linux/ipa_eth.h \
  include/linux/ipc_logging.h \
  include/linux/mailbox/qmp.h \
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
# Linux 5.10 no longer exports the old uncached ioremap aliases. On ARM64,
# ioremap()/devm_ioremap() use normal device mapping for MMIO, preserving
# the Qualcomm driver's intended device-register access semantics.
# This is strictly a donor-workspace source compatibility transform.
gsi = p / "drivers/platform/msm/gsi/gsi.c"
g = gsi.read_text()
for old, new in (("devm_ioremap_nocache(", "devm_ioremap("),
                 ("ioremap_nocache(", "ioremap(")):
    num = g.count(old)
    if num != 1:
        raise RuntimeError(f"P470 A0 legacy {old} site count={num}, expected one")
    g = g.replace(old, new, 1)
gsi.write_text(g)
print("P470 A0 GSI 5.10 MMIO COMPAT: devm_ioremap + ioremap (unique anchors)")
print("P470 A0 external-module Kbuild wiring staged outside GKI")
PY

# This now runs before the full Image compile: prepare genuine generated
# headers and scripts without linking/repacking any production kernel.
make -C "$ROOT" O="$BUILD" ARCH=arm64 \
  CROSS_COMPILE=aarch64-linux-gnu- CLANG_TRIPLE=aarch64-linux-gnu- \
  LLVM=1 LLVM_IAS=1 modules_prepare
echo "P470 A0 MODULES_PREPARE PASS (no Image linked)"
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
