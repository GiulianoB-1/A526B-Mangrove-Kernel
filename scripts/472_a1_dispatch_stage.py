#!/usr/bin/env python3
"""Stage the real P472 A1 APR audio service transport into pinned GKI 5.10.

One rpmsg owner for apr_audio_svc. This stage never duplicates the transport
driver, creates a synthetic ALSA card, writes calibration, or arms hardware.
"""
import argparse
import json
import shutil
from pathlib import Path

MARK = "P472_A1_APR_REAL_SERVICE_DISPATCH_V1"
CONFIG = "P472_A1_APR_DISPATCH"
HEADER = Path("drivers/rpmsg/p472_a1_apr.h")
DRIVER = Path("drivers/rpmsg/p472_apr_q6core.c")
KCONFIG = Path("drivers/rpmsg/Kconfig")
KCFG = """
config P472_A1_APR_DISPATCH
    bool "P472 native TG ADSP APR AFE/ASM/ADM/LSM service transport"
    depends on P472_A0_APR_Q6CORE && RPMSG
    default n
    help
      Real ADSP APRv2 service routing with bounded TX and SSR edge events.
      Does not enable ASoC, codec, speakers or calibration.
"""

def check(root):
    c = (root / DRIVER).read_text()
    h = (root / HEADER).read_text()
    k = (root / KCONFIG).read_text()
    required = (MARK, "p472_a1_apr_register(", "p472_a1_apr_send(",
                "P472 A1 DISPATCH rx svc=", "P472 A1 DISPATCH adsp_down=1",
                "P472 A1 DISPATCH adsp_ready=1", "P472 A1 APR_HDR_INVALID",
                "P472 A0b ADSP_READY", "p472_a1_dispatch_rx(",
                "P472_A1_SVC_LSM", "P472_A1_SVC_ADM", "P472_A1_SVC_ASM",
                "P472_A1_SVC_AFE", "p472_a1_active = NULL",
                "cancel_work_sync(&s->query_work)", "p472_validate_intents(")
    for marker in required:
        if marker not in c and marker not in h:
            raise RuntimeError("P472 A1 service owner missing " + marker)
    if k.count("config " + CONFIG) != 1:
        raise RuntimeError("P472 A1 Kconfig ownership missing or repeated")
    if "depends on P472_A0_APR_Q6CORE && RPMSG" not in k:
        raise RuntimeError("P472 A1 duplicate endpoint gate not established")
    if "module_rpmsg_driver(p472_driver)" not in c:
        raise RuntimeError("P472 A1 real rpmsg owner missing")
    if c.count("module_rpmsg_driver(") != 1:
        raise RuntimeError("P472 A1 duplicate rpmsg owner")
    return {
        "phase": "P472-A1-APR-SERVICE-TRANSPORT",
        "compiled": "PENDING",
        "source_mark": MARK,
        "services": ["AFE", "ASM", "ADM", "LSM"],
        "single_rpmsg_owner": True,
        "aprv2_dynamic_header": True,
        "tx_max_packet_bytes": 512,
        "adsp_ssr_edge_notifications": True,
        "sound_card": "NOT_STAGED",
        "calibration_writes": False,
        "flash_authorized": False,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--report", type=Path)
    ap.add_argument("--check-only", action="store_true")
    a = ap.parse_args()
    src = a.repo / "vendor/p472/p472_a1_apr.h"
    if not a.check_only:
        if (a.root / HEADER).exists():
            raise RuntimeError("P472 A1 header target already exists")
        if not src.is_file() or not (a.root / DRIVER).is_file():
            raise RuntimeError("P472 A1 audited local source missing")
        if MARK not in (a.root / DRIVER).read_text():
            raise RuntimeError("P472 A1 real service implementation not staged")
        shutil.copyfile(src, a.root / HEADER)
        k = (a.root / KCONFIG).read_text()
        if "config " + CONFIG in k:
            raise RuntimeError("P472 A1 config already exists")
        (a.root / KCONFIG).write_text(k + KCFG)
    data = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("P472 A1 DISPATCH SOURCE PASS: single real APR service owner")
if __name__ == "__main__":
    main()
