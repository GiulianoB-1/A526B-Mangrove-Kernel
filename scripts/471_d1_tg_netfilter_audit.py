#!/usr/bin/env python3
"""P471: read-only final-config parity audit; never arms IPA or modem."""
import argparse
import json
import re
from pathlib import Path

TG_RMNET = ("RMNET", "RMNET_SHS", "RMNET_PERF", "QCOM_QMI_RMNET", "QCOM_QMI_DFC")
OBJS = ("rmnet_config.o", "rmnet_map_data.o", "rmnet_vnd.o",
        "qmi_rmnet.o", "wda_qmi.o", "dfc_qmi.o", "dfc_qmap.o")
FLAGS = ("RMNET_EGRESS_FORMAT_AGGREGATION", "RMNET_INGRESS_FORMAT_DL_MARKER_V1",
         "RMNET_FORMAT_PS_NOTIF", "RMNET_FLAGS_INGRESS_COALESCE",
         "RMNET_FLAGS_INGRESS_MAP_CKSUMV5", "RMNET_FLAGS_EGRESS_MAP_CKSUMV5")
ESSENTIAL = ("NETFILTER", "NF_CONNTRACK", "NF_NAT", "NETFILTER_XTABLES",
             "IP_NF_IPTABLES", "IP6_NF_IPTABLES", "IP_NF_NAT",
             "IP_NF_TARGET_MASQUERADE")
NFPAT = re.compile(r"^CONFIG_(?:NETFILTER|NF_|NFT_|IP_NF_|IP6_NF_|"
                   r"BRIDGE_NF_|IP_SET|XT_|IP_VS)")

def read_config(path):
    out = {}
    for ln in path.read_text().splitlines():
        if ln.startswith("CONFIG_") and "=" in ln:
            k, v = ln.split("=", 1)
            out[k] = v
        elif ln.startswith("# CONFIG_") and ln.endswith(" is not set"):
            out[ln[2:-len(" is not set")]] = "n"
    return out

def must(ok, reason):
    if not ok:
        raise RuntimeError("P471-D1b: " + reason)

def main():
    a = argparse.ArgumentParser()
    for key in ("root", "tg-config", "candidate-config", "report", "summary"):
        a.add_argument("--" + key, type=Path, required=(key != "summary"))
    args = a.parse_args()
    tg = read_config(args.tg_config)
    gki = read_config(args.candidate_config)
    core = args.root / "drivers/net/ethernet/qualcomm/rmnet_p471"
    mk = (core / "Makefile").read_text()
    private = (core / "rmnet_private.h").read_text()
    config_c = (core / "rmnet_config.c").read_text()
    for k in TG_RMNET:
        must(tg.get("CONFIG_" + k) == "y", "TG " + k + " not built-in")
    for k in ("P471_RMNET_CORE", "P471_RMNET_CTL"):
        must(gki.get("CONFIG_" + k) == "y", k + " not built-in")
    must(gki.get("CONFIG_RMNET", "n") == "n", "duplicate ACK rtnl rmnet")
    for obj in OBJS:
        must(re.search(r"\b" + re.escape(obj) + r"\b", mk), "missing " + obj)
    for flag in FLAGS:
        must(flag in private, "donor lacks " + flag)
    for attr in ("IFLA_RMNET_FLAGS", "IFLA_RMNET_DFC_QOS",
                 "IFLA_RMNET_UL_AGG_PARAMS", "flags->flags & flags->mask"):
        must(attr in config_c, "missing vendor rtnetlink " + attr)
    keys = sorted(k for k in (tg.keys() | gki.keys()) if NFPAT.match(k))
    delta = [{"config": k, "TG": tg.get(k, "n"), "GKI": gki.get(k, "n")}
             for k in keys if tg.get(k, "n") != gki.get(k, "n")]
    missing = [x for x in delta if x["TG"] in ("y", "m") and x["GKI"] == "n"]
    downgraded = [x for x in delta if x["TG"] == "y" and x["GKI"] == "m"]
    essentials = {k: {"TG": tg.get("CONFIG_" + k, "n"),
                       "GKI": gki.get("CONFIG_" + k, "n")}
                  for k in ESSENTIAL}
    ready = all(v["GKI"] == "y" for v in essentials.values())
    report = {
        "phase": "P471-D1b-TG-ABI-NETFILTER",
        "tg_rmnet_builtin": list(TG_RMNET),
        "candidate_builtins": ["P471_RMNET_CORE", "P471_RMNET_CTL"],
        "core_qmi_wda_dfc_objects": list(OBJS),
        "vendor_flags": {
            "0x80000071": "aggregation(31), MAPv5 csum(6,5), coalesce(4), base(0)",
            "0xC4000071": "aggregation(31), DL marker(30), PS notify(26), MAPv5 csum(6,5), coalesce(4), base(0)",
        },
        "flag_mask_runtime_unverified": True,
        "shs_perf": "TG builtin, not in pinned 5.10 donor, deferred",
        "vendor_modprobe_failures": "also on TG; not a gating signal",
        "netfilter": {
            "TG_option_count": sum(bool(NFPAT.match(k)) for k in tg),
            "GKI_option_count": sum(bool(NFPAT.match(k)) for k in gki),
            "full_differences": delta,
            "TG_enabled_GKI_disabled": missing,
            "TG_builtin_GKI_module": downgraded,
            "essential": essentials, "essential_all_builtin": ready,
            "note": "TG is Linux 4.19; GKI is 5.10. Option renames need review, do not blindly enable old symbols.",
        },
        "no_arm": True, "mobile_data_hardware_verified": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary = ("### P471-D1b TG rmnet/DFC netfilter audit\n"
               "- Pinned Qualcomm rmnet core+ctl built-in with QMI/WDA/DFC; ACK provider off.\n"
               "- Samsung flags 0x80000071 / 0xC4000071 recognized by source. Runtime rc/mask pending.\n"
               "- SHS/PERF: TG built-in, 5.10 donor lacks them; acceleration not ported in D1b.\n"
               "- Netfilter: %d differences; TG present/GKI absent %d; TG y/GKI m %d.\n"
               "- Essential netfilter all built-in: **%s**. Full option delta in JSON.\n"
               "- NO ARM; mobile data unverified.\n"
               % (len(delta), len(missing), len(downgraded), ready))
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(summary)
    print(summary)

if __name__ == "__main__":
    main()
