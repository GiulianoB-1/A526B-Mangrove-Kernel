#!/usr/bin/env python3
"""P470-A6c: canonical TG notifier ABI for A4b producer and all staged IPA/GSI TUs.

This is applied ONLY to the disposable post-P470-A6b native IPA build.
P470-A6b #695 artifact stays unchanged. No IPA arming or device-tree edits.
"""
import argparse
import json
import os
import re
from pathlib import Path

CORE = Path("drivers/remoteproc/remoteproc_core.c")
PAS = Path("drivers/remoteproc/qcom_q6v5_pas.c")
TG_PROVIDER = Path("drivers/a52_pil/subsystem_notif.c")
RMNET = Path("drivers/platform/msm/ipa/ipa_v3/rmnet_ipa.c")
QMI_HEADER = Path("drivers/platform/msm/ipa/ipa_v3/ipa_qmi_service.h")
MAKE = Path("drivers/platform/msm/Makefile")
TG_NOTIF = "a52-compat/include/soc/qcom/subsystem_notif.h"
TG_RESTART = "a52-compat/include/soc/qcom/subsystem_restart.h"
MARKER = "P470_A6C_TG_NOTIFIER_ABI_CANONICAL_V1"
DIAGNOSTIC = r'''    pr_info("P470-A6c RMNET SSR callback event=%lu enabled=%d\n",
            code, ipa3_rmnet_ctx.ipa_rmnet_ssr);
'''
EXPECTED_PATH = r'''/*
 * P470_A6C_TG_NOTIFIER_ABI_CANONICAL_V1
 * Source-only proof: A4b queue_notification("modem") calls TG provider
 * srcu_notifier_call_chain, including rmnet_ipa local callback registered
 * for SUBSYS_LOCAL_MODEM ("modem"), when rmnet registration is active.
 * Hardware delivery is NOT proven without an event log.
 */'''


def once(s, old, new, label):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"A6c {label} anchor count={count}")
    return s.replace(old, new, 1)


def includes(root, relative_source):
    parent = (root / relative_source).parent
    result = []
    for path in (TG_NOTIF, TG_RESTART):
        absolute = (root / path).resolve()
        if not absolute.is_file():
            raise RuntimeError(f"A6c missing pinned TG header: {absolute}")
        result.append('#include "' + os.path.relpath(absolute, parent) + '"')
    return result


def apply(root):
    core = root / CORE
    raw = core.read_text()
    if MARKER in raw:
        raise RuntimeError("A6c core already patched")
    canonical = includes(root, CORE)
    raw = once(raw,
               '#include <soc/qcom/subsystem_notif.h>\n#include <soc/qcom/subsystem_restart.h>',
               '\n'.join(canonical) + '\n' + EXPECTED_PATH,
               "A4b producer canonical notifier headers")
    core.write_text(raw)

    # The notifier provider carries an opaque void *payload and normally
    # includes only subsystem_notif.h. PAS usually includes only restart.h.
    # Include BOTH pinned headers here to make the complete ABI testable in
    # every named translation unit; do not alter notifier behavior.
    provider = root / TG_PROVIDER
    provider_source = provider.read_text()
    provider_source = once(
        provider_source,
        '#include "../../a52-compat/include/soc/qcom/subsystem_notif.h"',
        '#include "../../a52-compat/include/soc/qcom/subsystem_restart.h"\n'
        '#include "../../a52-compat/include/soc/qcom/subsystem_notif.h"',
        "TG notifier provider has both canonical headers")
    provider.write_text(provider_source)
    pas = root / PAS
    pas_source = pas.read_text()
    pas_source = once(
        pas_source,
        '#include "../../a52-compat/include/soc/qcom/subsystem_restart.h"',
        '#include "../../a52-compat/include/soc/qcom/subsystem_notif.h"\n'
        '#include "../../a52-compat/include/soc/qcom/subsystem_restart.h"',
        "PAS has both canonical headers")
    pas.write_text(pas_source)

    makefile = root / MAKE
    m = makefile.read_text()
    if MARKER in m:
        raise RuntimeError("A6c IPA Makefile already patched")
    # Force the TG headers into every IPA/GSI/RMNET translation unit before
    # donor/local includes. Their conventional include guards then suppress
    # the different GKI headers, including those pulled transitively.
    m += ("\n# " + MARKER + "\n" +
          "subdir-ccflags-y += -include $(srctree)/" + TG_NOTIF + "\n" +
          "subdir-ccflags-y += -include $(srctree)/" + TG_RESTART + "\n")
    makefile.write_text(m)

    rmnet = root / RMNET
    s = rmnet.read_text()
    start = "static int ipa3_lcl_mdm_ssr_notifier_cb(struct notifier_block *this,"
    if s.count(start) != 2:
        raise RuntimeError("A6c expected exactly one declaration and one definition")
    target = start + '''
                           unsigned long code,
                           void *data)
{'''
    # Tabs differ between donor variants. Target the function definition by
    # matching the open brace after the second declaration, never a prototype.
    pattern = re.compile(
        r'(static int ipa3_lcl_mdm_ssr_notifier_cb\('
        r'struct notifier_block \*this,\s*unsigned long code,\s*'
        r'void \*data\)\s*\{\s*\n)')
    hits = list(pattern.finditer(s))
    if len(hits) != 1:
        raise RuntimeError(f"A6c RMNET local callback definition count={len(hits)}")
    match = hits[0]
    s = s[:match.end()] + DIAGNOSTIC + s[match.end():]
    rmnet.write_text(s)


def check(root):
    core = (root / CORE).read_text()
    rmnet = (root / RMNET).read_text()
    pas = (root / PAS).read_text()
    provider = (root / TG_PROVIDER).read_text()
    mk = (root / MAKE).read_text()
    canonical = includes(root, CORE)
    for other, name in ((pas, "PAS"), (provider, "TG notifier provider")):
        for header in (TG_NOTIF, TG_RESTART):
            if '#include "../../' + header + '"' not in other:
                raise RuntimeError(f"A6c {name} lacks explicit canonical {header}")
    for token in canonical + [
        "subsys_notif_add_subsys(\"modem\")",
        "subsys_notif_queue_notification(handle, task->type, &data)",
        "p470_mss_queue_notify(rproc, SUBSYS_BEFORE_SHUTDOWN, crashed)",
        "p470_mss_queue_notify(rproc, SUBSYS_AFTER_SHUTDOWN, crashed)",
        "p470_mss_queue_notify(rproc, SUBSYS_AFTER_POWERUP, false)",
        MARKER
    ]:
        if token not in core:
            raise RuntimeError(f"A6c A4b missing {token!r}")
    if '#include <soc/qcom/subsystem_notif.h>' in core or \
       '#include <soc/qcom/subsystem_restart.h>' in core:
        raise RuntimeError("A6c A4b still selects ambiguous GKI headers")
    for token in ("subdir-ccflags-y += -include $(srctree)/" + TG_NOTIF,
                  "subdir-ccflags-y += -include $(srctree)/" + TG_RESTART):
        if token not in mk:
            raise RuntimeError("A6c missing IPA/GSI forced canonical header " + token)
    if "P470-A6c RMNET SSR callback event=%lu enabled=%d" not in rmnet:
        raise RuntimeError("A6c RMNET runtime delivery marker absent")
    if "subsys_notif_register_notifier(SUBSYS_LOCAL_MODEM," not in rmnet:
        raise RuntimeError("A6c donor RMNET does not use TG notifier registration")
    header = (root / QMI_HEADER).read_text()
    if '#define SUBSYS_LOCAL_MODEM "modem"' not in header:
        raise RuntimeError("A6c mismatch between producer modem and RMNET registration")
    if "qcom_register_ssr_notifier(" in rmnet:
        raise RuntimeError("A6c unexpected alternate GKI SSR registrar")
    for token in ("void *subsys_notif_register_notifier(",
                  "srcu_notifier_chain_register(",
                  "void *subsys_notif_add_subsys(",
                  "int subsys_notif_queue_notification(",
                  "srcu_notifier_call_chain(&subsys->subsys_notif_rcvr_list,"):
        if token not in provider:
            raise RuntimeError("A6c TG provider queue/dispatch path missing: " + token)
    return {
        "phase": "P470-A6c-SSR-NOTIFIER-PRE-IPA-AUDIT",
        "canonical_tg_header_notif": TG_NOTIF,
        "canonical_tg_header_restart": TG_RESTART,
        "all_ipa_gsi_rmnets_force_include_tg": True,
        "a4b_producer_uses_tg_header": True,
        "donor_ipa_registration_api": "subsys_notif_register_notifier",
        "donor_registration_name": "modem",
        "donor_registration_name_macro": "SUBSYS_LOCAL_MODEM",
        "producer_queue_api": "subsys_notif_queue_notification",
        "provider_delivery": "srcu_notifier_call_chain",
        "rmnet_callback": "ipa3_lcl_mdm_ssr_notifier_cb",
        "registration_condition": "rmnet_ipa3_init; callback handles only if qcom,rmnet-ipa-ssr=true",
        "source_route_proven": True,
        "runtime_delivery_observed": False,
        "ipa_arm_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if not args.check_only:
        apply(root)
    result = check(root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("P470-A6c TG notifier canonical producer/consumer source path PASS; runtime IPA delivery PENDING; NO IPA ARM")


if __name__ == "__main__":
    main()
