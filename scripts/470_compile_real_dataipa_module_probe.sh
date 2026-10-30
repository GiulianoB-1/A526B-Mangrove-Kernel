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
export ROOT
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
# The Android 5.10 debugfs_create_u32 API returns void. Keep the
# vendor's debugfs_create_file dentry checks, but stop assigning/testing
# the seven create_u32 results. Check the exact old shape before editing.
import re
debugfs = p / "drivers/platform/msm/ipa/ipa_v3/ipa_debugfs.c"
d = debugfs.read_text()
pattern = re.compile(
    r"(?m)^(?P<indent>\s*)file = debugfs_create_u32\((?P<args>[^;]+)\);\n"
    r"(?P=indent)if \(!file\) \{\n"
    r"(?P<error>.*?)(?P=indent)\}\n",
    re.S,
)
def migrate_create_u32(m):
    body = m.group("error")
    if "goto fail;" not in body or "IPAERR(" not in body:
        raise RuntimeError("P470 debugfs u32 failure shape drift")
    return m.group("indent") + "debugfs_create_u32(" + m.group("args") + ");\n"
d, n = pattern.subn(migrate_create_u32, d)
if n != 7 or "file = debugfs_create_u32(" in d:
    raise RuntimeError(f"P470 debugfs u32 site count={n}, expected seven")
debugfs.write_text(d)
print("P470 A0 DEBUGFS 5.10 COMPAT: seven create_u32 void-return sites")

# TRACE_INCLUDE_PATH is resolved from the kernel's include/trace/
# define_trace.h, not from the donor's ipa_trace.h. Calculate the path
# to the real, pinned donor header in this private workspace only.
trace = p / "drivers/platform/msm/ipa/ipa_v3/ipa_trace.h"
t = trace.read_text()
old = "#define TRACE_INCLUDE_PATH ../../techpack/dataipa/drivers/platform/msm/ipa/ipa_v3"
relative_trace = os.path.relpath(trace.parent.resolve(),
                                 Path(os.environ["ROOT"]).resolve() / "include/trace")
new = "#define TRACE_INCLUDE_PATH " + relative_trace
if t.count(old) != 1 or not (trace.parent / "ipa_trace.h").is_file():
    raise RuntimeError("P470 trace include source drift")
t = t.replace(old, new)
trace.write_text(t)
print("P470 A0 TRACE 5.10 COMPAT: " + new)

# P470 A0 compatibility is compile-only. Production needs actual Qualcomm
# SCM and SMMU implementations. Never invent a successful secure-world call
# or identity-map the modem's SMMU streams to get a green compiler result.
ipa = p / "drivers/platform/msm/ipa/ipa_v3/ipa.c"
c = ipa.read_text()
def exact(old, new, n=1):
    global c
    count = c.count(old)
    if count != n:
        raise RuntimeError(f"P470 A0 ipa.c API drift: {old!r} count={count} expected={n}")
    c = c.replace(old, new)

# Fixed vendor-array bug: compare the allocated first element, not the
# compile-time array object address.
exact("ipa3_ctx->ipa3_active_clients_logging.log_buffer == NULL",
      "ipa3_ctx->ipa3_active_clients_logging.log_buffer[0] == NULL")

# Vendor UAPI header of this Qualcomm kernel branch has no feature query.
# Do not invent an ioctl number that would collide with userspace.
exact("case IPA_IOC_GET_HW_FEATURE_SUPPORT:",
      "#if defined(IPA_IOC_GET_HW_FEATURE_SUPPORT) && defined(ETH_BRIDGING_SUPPORT)\n"
      "\tcase IPA_IOC_GET_HW_FEATURE_SUPPORT:")
exact("\t\tbreak;\n\tdefault:\n\t\tIPA_ACTIVE_CLIENTS_DEC_SIMPLE();",
      "\t\tbreak;\n#endif /* optional extension missing from pinned UAPI */\n"
      "\tdefault:\n\t\tIPA_ACTIVE_CLIENTS_DEC_SIMPLE();")

# Linux 5.10's DMA_BIT_MASK(64) macro expands a non-selected 1ULL << 64
# branch that Clang diagnoses as shift-count-overflow. ~0ULL is its exact
# 64-bit result; this does not change device DMA-mapping permissions.
exact("DMA_BIT_MASK(64)", "~0ULL", n=6)

# If secure-world operations are unavailable, explicitly fail them closed.
# These are compile-only donor transformations, not implementations.
exact("ret = qcom_scm_mem_protect_region_id(\n"
      "\t\t\tvirt_to_phys((void *)ipa_tz_unlock_vec),\n"
      "\t\t\tsize);",
      "#if defined(P470_A0_COMPILE_ONLY)\n"
      "\tIPAERR(\"P470 A0 SCM BLOCKED: region protection unavailable\\n\");\n"
      "\tret = -EOPNOTSUPP;\n"
      "#else\n"
      "\tret = qcom_scm_mem_protect_region_id(\n"
      "\t\t\tvirt_to_phys((void *)ipa_tz_unlock_vec),\n"
      "\t\t\tsize);\n"
      "#endif")
exact("ret = qcom_scm_get_sec_dump_state(&dump_state);",
      "#if defined(P470_A0_COMPILE_ONLY)\n"
      "\t/* Never enable secure dumps without a real SCM confirmation. */\n"
      "\tdump_state = 0;\n"
      "\tret = -EOPNOTSUPP;\n"
      "#else\n"
      "\tret = qcom_scm_get_sec_dump_state(&dump_state);\n"
      "#endif")

# Qualcomm's S1_BYPASS/FAST domain attributes are vendor-only. A generic
# iommu_domain must NOT be assumed to be equivalent. Abort the CB probe
# until real armsmmu attributes + fastmap handling have been ported.
both = ("\tiommu_domain_get_attr(cb->iommu_domain, DOMAIN_ATTR_S1_BYPASS, &bypass);\n"
        "\tiommu_domain_get_attr(cb->iommu_domain, DOMAIN_ATTR_FAST, &fast);")
blocked = ("#if defined(P470_A0_COMPILE_ONLY)\n"
           "\tIPAERR(\"P470 A0 SMMU BLOCKED: missing vendor bypass/fast attributes\\n\");\n"
           "\treturn -EOPNOTSUPP;\n"
           "#else\n" + both + "\n#endif")
exact(both, blocked, n=3)
single = "\tiommu_domain_get_attr(cb->iommu_domain, DOMAIN_ATTR_S1_BYPASS, &bypass);"
exact(single, ("#if defined(P470_A0_COMPILE_ONLY)\n"
               "\tIPAERR(\"P470 A0 11AD SMMU BLOCKED: missing bypass attribute\\n\");\n"
               "\treturn -EOPNOTSUPP;\n"
               "#else\n" + single + "\n#endif"), n=4)

# The feature ioctl is excluded with the missing pinned UAPI, so its
# local value must also be guarded. Do not disable Werror to hide this.
exact("\tu32 hw_feature_support = 0;",
      "#if defined(IPA_IOC_GET_HW_FEATURE_SUPPORT) && defined(ETH_BRIDGING_SUPPORT)\n"
      "\tu32 hw_feature_support = 0;\n#endif")
ipa.write_text(c)
print("P470 A0 IPA CORE COMPILE COMPAT: allocation check, optional UAPI, 64-bit DMA mask")
print("P470 A0 HARD BLOCK: SCM protection/dump and SMMU CB fast/bypass not implemented")
# ipa_nat.c uses dma_alloc_coherent and dma_free_coherent, whose header
# in Linux 5.10 is dma-mapping.h. The removed dma-noncoherent.h import
# has no other uses in this particular pinned source file.
nat = p / "drivers/platform/msm/ipa/ipa_v3/ipa_nat.c"
nat_src = nat.read_text()
old_nat = "#include <linux/dma-noncoherent.h>"
if nat_src.count(old_nat) != 1:
    raise RuntimeError("P470 A0 NAT obsolete header anchor drift")
nat.write_text(nat_src.replace(old_nat, "#include <linux/dma-mapping.h>", 1))
print("P470 A0 NAT 5.10 COMPAT: coherent DMA header")

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
  KCFLAGS="-DP470_A0_COMPILE_ONLY=1 -DCONFIG_IPA3 -I$HEADERS/include -I$HEADERS/include/uapi -include $DONOR/config/dataipa.h" \
  -j"$(nproc)" modules
echo "P470 A0 MODULE SOURCE COMPILE PASS (NOT A HARDWARE/IPA READY PASS)"
