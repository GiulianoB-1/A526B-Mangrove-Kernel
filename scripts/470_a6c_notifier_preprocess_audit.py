#!/usr/bin/env python3
"""P470-A6c: audit actual preprocessed notifier ABI in every built IPA/GSI TU.

Compare the COMPLETE expanded notif_data and subsys_notif_type, event
ordinals, and canonical notifier prototypes, not just source headers.
Inspect all compiled IPA/GSI object units, not only named IPA.c/RMNET.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

SOURCE_ROOT = Path("drivers/platform/msm")
REQUIRED = [
    "subsys_notif_register_notifier",
    "subsys_notif_unregister_notifier",
    "subsys_notif_add_subsys",
    "subsys_notif_queue_notification",
    "send_early_notifications",
]
REFERENCES = {
    "tg_notifier_provider": "drivers/a52_pil/subsystem_notif",
    "tg_ssr_provider": "drivers/a52_pil/subsystem_restart",
    "a4b_remoteproc_producer": "drivers/remoteproc/remoteproc_core",
    "pas_tg_ssr": "drivers/remoteproc/qcom_q6v5_pas",
}
TG_NOTIF = "a52-compat/include/soc/qcom/subsystem_notif.h"
TG_RESTART = "a52-compat/include/soc/qcom/subsystem_restart.h"
GKI_NOTIF = "include/soc/qcom/subsystem_notif.h"
GKI_RESTART = "include/soc/qcom/subsystem_restart.h"
CANONICAL_EVENTS = [
    "SUBSYS_BEFORE_SHUTDOWN",
    "SUBSYS_AFTER_SHUTDOWN",
    "SUBSYS_BEFORE_POWERUP",
    "SUBSYS_AFTER_POWERUP",
    "SUBSYS_BEFORE_AUTH_AND_RESET",
    "SUBSYS_RAMDUMP_NOTIFICATION",
    "SUBSYS_POWERUP_FAILURE",
    "SUBSYS_PROXY_VOTE",
    "SUBSYS_PROXY_UNVOTE",
    "SUBSYS_SOC_RESET",
    "SUBSYS_NOTIF_TYPE_COUNT",
]

def compact(s):
    return re.sub(r"\s+", " ", s).strip()

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def parse_enum(body):
    values = {}
    count = -1
    for field in body.split(","):
        field = compact(field)
        if not field:
            continue
        m = re.fullmatch(r"([A-Z_][A-Z0-9_]*)(?:\s*=\s*(\d+))?", field)
        if not m:
            raise RuntimeError("unsupported preprocessed notifier enum term: " + field[:160])
        if m[2] is not None:
            count = int(m[2])
        else:
            count += 1
        values[m[1]] = count
    return values

def extract(name, p):
    raw = p.read_text(errors="replace")
    # Do not discard #line provenance before asserting the headers which
    # actually emit the definitions. Include guards can suppress GKI's body.
    def section(pattern, label):
        matches = list(re.finditer(pattern, raw, re.S))
        if len(matches) != 1:
            raise RuntimeError(f"{p}: {label} definitions={len(matches)}")
        m = matches[0]
        prior = raw[:m.start()]
        line = re.findall(r'(?m)^#\s*\d+\s+"([^"]+)"', prior)
        origin = line[-1] if line else ""
        return m.group(1), origin
    data, data_origin = section(
        r"\bstruct\s+notif_data\s*\{(.*?)\n\s*\};",
        "struct notif_data")
    enum, enum_origin = section(
        r"\benum\s+subsys_notif_type\s*\{(.*?)\n\s*\};",
        "enum subsys_notif_type")
    data_compact = compact(data)
    fields = ("enum crash_status crashed;", "int enable_ramdump;",
              "int enable_mini_ramdumps;", "bool no_auth;",
              "struct platform_device *pdev;")
    if not all(f in data_compact for f in fields):
        raise RuntimeError(f"{p}: unexpected notif_data members: {data_compact}")
    vals = parse_enum(enum)
    if list(vals) != CANONICAL_EVENTS or any(vals[n] != i for i,n in enumerate(CANONICAL_EVENTS)):
        raise RuntimeError(f"{p}: notifier enum value/ordering discrepancy: {vals}")
    # Provenance must refer to the pinned header, not an accidental 5.10
    # definition. GKI #line entries may exist due to guard-skipped includes.
    if TG_RESTART not in data_origin.replace("\\", "/"):
        raise RuntimeError(f"{p}: notif_data came from {data_origin}, not pinned TG")
    if TG_NOTIF not in enum_origin.replace("\\", "/"):
        raise RuntimeError(f"{p}: notifier enum came from {enum_origin}, not pinned TG")
    flat = re.sub(r"(?m)^#.*\n", "", raw)
    types = {}
    for symbol in REQUIRED:
        # Match only function declarations; exclude definitions/call sites.
        pattern = r"\b(?:void\s*\*|int|void)\s*" + re.escape(symbol) + r"\s*\(([^{};]*)\)\s*;"
        decls = [compact(m.group(0)) for m in re.finditer(pattern, flat, re.S)]
        if len(decls) != 1:
            raise RuntimeError(f"{p}: {symbol} prototypes={len(decls)}")
        types[symbol] = decls[0]
    return {
        "notif_data_sha256": sha(data_compact),
        "notif_data_declaration": data_compact,
        "notif_data_origin": data_origin,
        "subsys_notif_type_sha256": sha(compact(enum)),
        "subsys_notif_type_values": vals,
        "enum_origin": enum_origin,
        "prototypes": types,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--build", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    root, build = a.root.resolve(), a.build.resolve()
    units = dict(REFERENCES)
    sources = set()
    for obj in sorted((build / SOURCE_ROOT).rglob("*.o")):
        rel = obj.relative_to(build).with_suffix("")
        if (root / rel.with_suffix(".c")).exists():
            sources.add(rel.as_posix())
    if len(sources) < 3:
        raise RuntimeError("P470-A6c expected built IPA/GSI/RMNET units")
    for s in sorted(sources):
        units["donor_" + s.replace("/", "_")] = s
    if "drivers/platform/msm/ipa/ipa_v3/rmnet_ipa" not in sources:
        raise RuntimeError("P470-A6c rmnet_ipa.o not linked; no notifier consumer")
    if "drivers/platform/msm/gsi/gsi" not in sources:
        raise RuntimeError("P470-A6c GSI.o not linked")
    checks = {}
    for label, rel in units.items():
        path = build / (rel + ".i")
        if not path.is_file():
            raise RuntimeError(f"P470-A6c missing actual preprocessed {path}")
        checks[label] = extract(label, path)
    unique_data = {v["notif_data_sha256"] for v in checks.values()}
    unique_enum = {v["subsys_notif_type_sha256"] for v in checks.values()}
    unique_proto = {json.dumps(v["prototypes"], sort_keys=True) for v in checks.values()}
    summary = {
        "phase": "P470-A6c-IPA-NOTIFIER-PREPROCESS-LINK-ABI",
        "all_built_ipa_gsi_units_audited": len(sources),
        "tg_provider_and_a4b_core_audited": True,
        "notifier_data_all_equal": len(unique_data) == 1,
        "notifier_enum_all_equal": len(unique_enum) == 1,
        "notifier_prototypes_all_equal": len(unique_proto) == 1,
        "event_ordinals": checks["tg_notifier_provider"]["subsys_notif_type_values"],
        "audited_preprocessed_units": sorted(units.values()),
        "unit_evidence": checks,
        "donor_registration_api": "subsys_notif_register_notifier",
        "donor_registration_name": "modem",
        "a4b_queue_api": "subsys_notif_queue_notification",
        "linked_provider": "drivers/a52_pil/subsystem_notif.o",
        "runtime_callback_delivery_proven": False,
        "ipa_arm_authorized": False,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if len(unique_data) != 1 or len(unique_enum) != 1 or len(unique_proto) != 1:
        raise RuntimeError("P470-A6c notifier ABI differs across one or more live TUs")
    print(f"P470-A6c NOTIFIER PREPROCESS ABI PASS units={len(units)} donor_units={len(sources)}")
    print("P470-A6c enum ordinals 0/1/2/3; all fields/prototypes identical; IPA hardware delivery PENDING")

if __name__ == "__main__":
    main()
