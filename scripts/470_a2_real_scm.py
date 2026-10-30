#!/usr/bin/env python3
"""P470-A2: add the two genuine pinned Qualcomm 5.10 SCM calls to GKI.

No mock call, no success fallback, no auto PAS owner and no change to
existing UFS ICE, SMMU, ADSP, MSS or P458 manual SCM registration.
The commands are copied from the pinned f438c918 Qualcomm 5.10 ABI.
"""
import argparse
import json
from pathlib import Path

PUBLIC = Path("include/linux/qcom_scm.h")
PRIVATE = Path("drivers/firmware/qcom_scm.h")
IMPL = Path("drivers/firmware/qcom_scm.c")
TAG = "P470_A2_REAL_SCM_IPA_V1"


def once(s, before, after, label):
    n = s.count(before)
    if n != 1:
        raise RuntimeError(f"P470-A2 {label}: anchor count {n}, expected 1")
    return s.replace(before, after, 1)


def patch_public(s):
    if TAG in s:
        raise RuntimeError("P470-A2 SCM public header already patched")
    sig = "extern int qcom_scm_mem_protect_video_var(u32 cp_start, u32 cp_size,"
    if s.count(sig) != 1:
        raise RuntimeError("P470-A2 vendor SCM API public declaration drift")
    s = once(s, sig,
        "/* " + TAG + ": real pinned Qualcomm IPA secure-world ABI. */\n"
        "extern int qcom_scm_get_sec_dump_state(u32 *dump_state);\n"
        "extern int qcom_scm_mem_protect_region_id(phys_addr_t paddr, size_t size);\n"
        + sig, "public CONFIG_QCOM_SCM=y declarations")
    # Preserve -ENODEV if SCM itself is not compiled in; never claim success.
    fall = "static inline int qcom_scm_mem_protect_video_var(u32 cp_start,"
    s = once(s, fall,
        "static inline int qcom_scm_get_sec_dump_state(u32 *dump_state)\n"
        "{ return -ENODEV; }\n"
        "static inline int qcom_scm_mem_protect_region_id(phys_addr_t paddr, size_t size)\n"
        "{ return -ENODEV; }\n" + fall,
        "public disabled-SCM fail-closed declarations")
    return s


def patch_private(s):
    if TAG in s:
        raise RuntimeError("P470-A2 SCM private header already patched")
    s = once(s, "#define QCOM_SCM_SVC_MP",
        "/* " + TAG + ": exact vendor 5.10 SCM service/cmd IDs. */\n"
        "#define QCOM_SCM_SVC_UTIL 0x03\n"
        "#define QCOM_SCM_UTIL_GET_SEC_DUMP_STATE 0x10\n"
        "#define QCOM_SCM_MP_MEM_PROTECT_REGION_ID 0x10\n"
        "#define QCOM_SCM_SVC_MP", "Qualcomm service IDs")
    return s


def patch_impl(s):
    if TAG in s:
        raise RuntimeError("P470-A2 SCM implementation already patched")
    insert = r'''/* P470_A2_REAL_SCM_IPA_V1
 * Qualcomm kernel 5.10 donor f438c918: util 0x03/0x10 and
 * memory-protection 0x0c/0x10. No fake successful SCM fallback.
 * The Lagoon 4.7 DT does not request ipa-tz-unlock-reg; the memory
 * protection call is retained only for a genuinely configured device.
 */
int qcom_scm_get_sec_dump_state(u32 *dump_state)
{
    struct qcom_scm_desc desc = {
        .svc = QCOM_SCM_SVC_UTIL,
        .cmd = QCOM_SCM_UTIL_GET_SEC_DUMP_STATE,
        .owner = ARM_SMCCC_OWNER_SIP,
    };
    struct qcom_scm_res res = {};
    int ret;

    if (!dump_state)
        return -EINVAL;
    *dump_state = 0; /* fail closed if firmware rejects secure dump query */
    if (!__scm)
        return -EPROBE_DEFER;
    ret = qcom_scm_call(__scm->dev, &desc, &res);
    if (!ret)
        *dump_state = res.result[0];
    return ret;
}
EXPORT_SYMBOL(qcom_scm_get_sec_dump_state);

int qcom_scm_mem_protect_region_id(phys_addr_t paddr, size_t size)
{
    struct qcom_scm_desc desc = {
        .svc = QCOM_SCM_SVC_MP,
        .cmd = QCOM_SCM_MP_MEM_PROTECT_REGION_ID,
        .owner = ARM_SMCCC_OWNER_SIP,
        .args[0] = paddr,
        .args[1] = size,
        .arginfo = QCOM_SCM_ARGS(2),
    };

    if (!__scm)
        return -EPROBE_DEFER;
    if (!paddr || !size)
        return -EINVAL;
    return qcom_scm_call(__scm->dev, &desc, NULL);
}
EXPORT_SYMBOL(qcom_scm_mem_protect_region_id);

'''
    anchor = "static int __qcom_scm_assign_mem("
    return once(s, anchor, insert + anchor, "real SCM call insertion")


def check(root):
    public = (root / PUBLIC).read_text()
    priv = (root / PRIVATE).read_text()
    impl = (root / IMPL).read_text()
    assert public.count("extern int qcom_scm_get_sec_dump_state(") == 1
    assert public.count("extern int qcom_scm_mem_protect_region_id(") == 1
    for token in ("QCOM_SCM_SVC_UTIL 0x03", "QCOM_SCM_UTIL_GET_SEC_DUMP_STATE 0x10",
                  "QCOM_SCM_MP_MEM_PROTECT_REGION_ID 0x10"):
        if token not in priv:
            raise RuntimeError("P470-A2 secure service ID missing: " + token)
    for token in ("P470_A2_REAL_SCM_IPA_V1",
                  "EXPORT_SYMBOL(qcom_scm_get_sec_dump_state);",
                  "EXPORT_SYMBOL(qcom_scm_mem_protect_region_id);",
                  "return qcom_scm_call(__scm->dev, &desc, NULL);"):
        if token not in impl:
            raise RuntimeError("P470-A2 actual SCM implementation missing: " + token)
    return {"phase": "P470-A2-REAL-SCM", "implemented": True,
            "secure_dump": "real Qualcomm 5.10 command, disabled on query error",
            "mem_protect": "real Qualcomm 5.10 command, only when requested",
            "ipa_ready": False, "flashable": False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    if not a.check_only:
        for name, fn in ((PUBLIC, patch_public),
                         (PRIVATE, patch_private), (IMPL, patch_impl)):
            f = a.root / name
            f.write_text(fn(f.read_text()))
    result = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(result, indent=2) + "\n")
    print("P470-A2 REAL SCM PASS: util dump and MP region provider integrated (IPA not ready)")


if __name__ == "__main__":
    main()
