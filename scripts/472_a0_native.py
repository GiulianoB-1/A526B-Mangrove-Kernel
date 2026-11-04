#!/usr/bin/env python3
"""Stage P472 A0 real APRv2/Q6CORE diagnostic in the native GKI 5.10 build.

This is intentionally NOT the full TG audio service dispatcher or sound card.
The separate pinned TG apr_tal_rpmsg.c source adaptation remains reviewable.
"""
import argparse
import json
import shutil
from pathlib import Path

MARK = "P472_A0_NATIVE_APRV2_Q6CORE_V1"
KCONFIG = '''
# P472 A0 native APR version query. No audio card or calibration.
config P472_A0_APR_Q6CORE
\tbool "P472 experimental native APRv2 Q6CORE version query"
\tdepends on RPMSG && OF && !QCOM_APR
\tdefault n
\thelp
\t  Real ADSP APRv2 get-framework-version transaction over RPMSG.
\t  This is not the full TouchGrass APR/audio ABI.
'''
MAKEFILE = '\n# P472_A0_NATIVE_APRV2_Q6CORE_V1\nobj-$(CONFIG_P472_A0_APR_Q6CORE) += p472_apr_q6core.o\n'
REL = Path("drivers/rpmsg/p472_apr_q6core.c")

def stage(root, donor):
    src = donor / "vendor/p472/p472_apr_q6core.c"
    if not src.is_file():
        raise RuntimeError("P472 local audited driver missing")
    s = src.read_text()
    for t in ("AVCS_CMDRSP_GET_FWK_VERSION", "rpmsg_send(rpdev->ept",
              "P472 A0 APR_READY", "P472 A0 Q6CORE ver=",
              "P472 A0 APR_TIMEOUT", "remote_pid != 2",
              "requested_count=%u requested_size=%u"):
        if t not in s:
            raise RuntimeError("P472 native driver missing " + t)
    k, m = root / "drivers/rpmsg/Kconfig", root / "drivers/rpmsg/Makefile"
    if not k.is_file() or not m.is_file():
        raise RuntimeError("P472 GKI RPMSG subsystem absent")
    if MARK in m.read_text() or "config P472_A0_APR_Q6CORE" in k.read_text():
        raise RuntimeError("P472 repeated staging prohibited")
    if (root / REL).exists():
        raise RuntimeError("P472 target exists, possible owner duplication")
    # Upstream APR providers are excluded by Kconfig, not hidden behind aliases.
    (root / REL).write_text(s)
    k.write_text(k.read_text() + KCONFIG)
    m.write_text(m.read_text() + MAKEFILE)

def check(root):
    k = (root / "drivers/rpmsg/Kconfig").read_text()
    m = (root / "drivers/rpmsg/Makefile").read_text()
    c = (root / REL).read_text()
    for val in (MARK, "obj-$(CONFIG_P472_A0_APR_Q6CORE)"):
        if val not in m:
            raise RuntimeError("P472 build link missing " + val)
    if "depends on RPMSG && OF && !QCOM_APR" not in k:
        raise RuntimeError("P472 duplicate APR gate missing")
    for val in ("P472 A0 APR_TAL dest=adsp", "P472 A0 APR_INTENTS",
                "P472 A0 APR_READY", "P472 A0 Q6CORE ver=",
                "P472 A0 APR_TIMEOUT", "rpmsg_send(rpdev->ept",
                "P472_APR_SVC_CORE", "P472_REQ_TIMEOUT_MS"):
        if val not in c:
            raise RuntimeError("P472 wrong native source " + val)
    return {
      "phase": "P472-A0-NATIVE-Q6CORE",
      "marker": MARK,
      "real_aprv2_version_transaction": True,
      "upstream_apr_provider_kconfig_excluded": True,
      "native_link": "to be verified from Image and System.map",
      "dt_intent_allocation": "runtime unverified",
      "tg_apr_complete_dispatcher": False,
      "asoc_sound_card": False,
      "modem_data_changed": False,
      "flash_authorized": False
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    if not a.check_only:
        stage(a.root, a.repo)
    rec = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(rec, sort_keys=True, indent=2)+"\n")
    print("P472 A0 native APRv2 Q6CORE staged; full Image compile + real reply pending")

if __name__ == "__main__":
    main()
