#!/usr/bin/env python3
"""P470-A3: stage *real* pinned dataipa as in-tree, built-in GKI objects.

Intended only for the post-packaging, NO-FLASH CI experiment. No DT/PAS15
owner, SSR notifier, modem ready gate or live hardware support is added.
Refuse overwrite of any existing driver, header or build wiring.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

DONOR_SHA = "c560cc3c2840fb0ebc55ceef5b27549c66143637"
TAG = "P470_A3_BUILTIN_IPA_LINK_PROBE_V1"
CONFIG = """# P470-A3 source-only, built-in link experiment; no device-tree activation.
config GSI
    bool "Qualcomm GSI for Lagoon IPA 4.7"

config IPA3
    bool "Qualcomm IPA3 4.7 (P470-A3 preflight only)"
    depends on ARCH_QCOM && QCOM_SCM && IOMMU_SUPPORT && OF && NET
    depends on GSI
    help
      Built-in link experiment only. No PAS15, DTB or hardware permission.

config RMNET_IPA3
    bool "Qualcomm IPA RMNET endpoints"
    depends on IPA3 && INET
"""
IGNORE = shutil.ignore_patterns(
    "*.o", "*.ko", "*.mod", "*.mod.c", "*.mod.o", "*.cmd",
    "*.order", "*.symvers", ".*.cmd", "*.a", "*.d", ".*.d",
    ".tmp*", "*.gcno"
)


def exact_replace(s, old, new, label):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"P470-A3 {label}: expected exactly one pinned anchor, got {count}")
    return s.replace(old, new, 1)


def git_sha(folder):
    return subprocess.check_output(
        ["git", "-C", str(folder), "rev-parse", "HEAD"], text=True
    ).strip()


def check_guardrails(root, donor, headers, framework):
    if git_sha(donor) != DONOR_SHA:
        raise RuntimeError("P470-A3 donor commit mismatch")
    if not (root / "Makefile").is_file() or not (root / "drivers/Makefile").is_file():
        raise RuntimeError("P470-A3 composed kernel tree missing")
    if not (headers / "include").is_dir():
        raise RuntimeError("P470-A3 pinned kernel ABI headers not available")
    if (donor / "drivers/platform/msm/ipa_fmwk/ipa_fmwk.c").read_bytes() != framework.read_bytes():
        raise RuntimeError("P470-A3 IPA framework differs from pinned vendor copy")
    ipa = (donor / "drivers/platform/msm/ipa/ipa_v3/ipa.c").read_text()
    smmu = (root / "drivers/iommu/arm/arm-smmu/arm-smmu.c").read_text()
    for token in ("P470_A2_TRANSLATED_LAGOON_CB_V2",
                  "p470_a2_manual_map_guard", "mode=translated(tg=%s) bypass=0"):
        if token not in ipa:
            raise RuntimeError("P470-A3 A2 adapter missing: " + token)
    for token in ("P470_A2_LAGOON_IPA_DMA_POOL_COMPLEMENT_V2",
                  "p470_a2_ipa_reserve_complement",
                  "outside_reserved=1"):
        if token not in smmu:
            raise RuntimeError("P470-A3 allocator complement missing: " + token)
    if not (root / "include/linux/qcom_scm.h").is_file():
        raise RuntimeError("P470-A3 real SCM interface absent")
    if "P470_A2_REAL_SCM_IPA_V1" not in (root / "drivers/firmware/qcom_scm.c").read_text():
        raise RuntimeError("P470-A3 real SCM implementation absent")
    # Kbuild must not accidentally use compile-only paths.
    if "P470_A0_COMPILE_ONLY" not in ipa:
        raise RuntimeError("P470-A3 donor compatibility branch absent")
    if (root / "drivers/platform/msm").exists():
        raise RuntimeError("P470-A3 refuse overwrite of existing msm driver tree")
    if TAG in (root / "drivers/Makefile").read_text():
        raise RuntimeError("P470-A3 already staged")


def stage(root, donor, headers, framework):
    base = root / "drivers/platform/msm"
    for name in ("ipa", "gsi", "ipa_fmwk"):
        src = donor / "drivers/platform/msm" / name
        if not src.is_dir():
            raise RuntimeError("P470-A3 donor directory absent: " + name)
        shutil.copytree(src, base / name, ignore=IGNORE)
    # The A0 module probe re-rooted the donor Makefile with $(M); for a
    # true in-tree link it must use $(srctree), and the real framework y.
    upstream = (donor / "drivers/platform/msm/Makefile").read_text()
    upstream = exact_replace(
        upstream, "DATAIPADRVTOP = $(M)/drivers/platform/msm",
        "DATAIPADRVTOP = $(srctree)/drivers/platform/msm",
        "driver include root")
    upstream = exact_replace(
        upstream, "obj-m += ipa_fmwk/",
        "obj-$(CONFIG_IPA3) += ipa_fmwk/",
        "real provider built-in")
    upstream += "\n# " + TAG + "\n"
    upstream += "subdir-ccflags-y += -include $(srctree)/include/linux/p470_lagoon_dataipa_config.h\n"
    (base / "Makefile").write_text(upstream)
    fw = base / "ipa_fmwk/Makefile"
    fw.write_text(exact_replace(
        fw.read_text(), "obj-m += ipa_fmwk.o", "obj-y += ipa_fmwk.o",
        "framework object built-in"))
    # Define trace header location relative to include/trace/define_trace.h,
    # not the deleted out-of-tree donor path.
    trace = base / "ipa/ipa_v3/ipa_trace.h"
    raw = trace.read_text()
    match = re.findall(r"(?m)^#define TRACE_INCLUDE_PATH .*?$", raw)
    if len(match) != 1:
        raise RuntimeError("P470-A3 trace path anchor drift")
    trace.write_text(exact_replace(raw, match[0],
        "#define TRACE_INCLUDE_PATH ../../drivers/platform/msm/ipa/ipa_v3",
        "native trace include path"))
    # Import only genuinely absent, pinned ABI headers. No blanket
    # overwrite of platform APIs already supplied by the working kernel.
    imported = []
    for src in sorted((headers / "include").rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(headers)
        dest = root / rel
        if dest.exists():
            raise RuntimeError("P470-A3 ABI shadow collision: " + str(rel))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        imported.append(str(rel))
    conf = root / "include/linux/p470_lagoon_dataipa_config.h"
    if conf.exists():
        raise RuntimeError("P470-A3 Lagoon feature config already exists")
    # Feature header is passed explicitly from the repository, never
    # obtained from an unchecked donor configuration include.
    return imported, conf


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--donor", required=True, type=Path)
    p.add_argument("--headers", required=True, type=Path)
    p.add_argument("--framework", required=True, type=Path)
    p.add_argument("--features", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    a = p.parse_args()
    paths = [a.root, a.donor, a.headers, a.framework, a.features]
    root, donor, headers, framework, features = [x.resolve() for x in paths]
    check_guardrails(root, donor, headers, framework)
    imported, conf = stage(root, donor, headers, framework)
    if not features.is_file() or not features.read_bytes():
        raise RuntimeError("P470-A3 pinned feature header missing")
    conf.write_bytes(features.read_bytes())
    # Use native Kconfig; command line CONFIG_IPA3=y alone is NOT a proof.
    (root / "drivers/platform/msm/Kconfig").write_text(CONFIG)
    mk = root / "drivers/Makefile"
    mk.write_text(mk.read_text() + "\n# " + TAG + "\nobj-$(CONFIG_IPA3) += platform/msm/\n")
    kc = root / "drivers/Kconfig"
    kc.write_text(kc.read_text() + "\n# " + TAG + "\nsource \"drivers/platform/msm/Kconfig\"\n")
    assert (root / "drivers/platform/msm/ipa/ipa_v3/ipa.c").is_file()
    assert (root / "drivers/platform/msm/gsi/gsi.c").is_file()
    assert (root / "drivers/platform/msm/ipa_fmwk/ipa_fmwk.c").read_bytes() == framework.read_bytes()
    paths = ("drivers/platform/msm/ipa/ipa_v3/ipa.c",
             "drivers/platform/msm/gsi/gsi.c",
             "drivers/platform/msm/ipa_fmwk/ipa_fmwk.c",
             "drivers/platform/msm/Makefile",
             "drivers/platform/msm/Kconfig")
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
              for name in paths}
    report = {
        "phase": "P470-A3-REAL-BUILTIN-LINK-PREFLIGHT",
        "status": "SOURCE_STAGED_NOT_LINKED",
        "donor_sha": DONOR_SHA,
        "source_sha256": hashes,
        "imported_pinned_headers": imported,
        "compiled_gki_image": False,
        "pas15_owner": False,
        "final_dtb_audited": False,
        "mss_notifier": False,
        "modem_ipa_ready_gate": False,
        "hardware_verified": False,
        "flashable": False
    }
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("P470-A3 pinned real IPA/GSI/RMNET/framework staged for built-in link; NO FLASH")


if __name__ == "__main__":
    main()
