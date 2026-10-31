#!/usr/bin/env python3
"""P470-A6g: Lagoon IPA 4.7 boot stats isolation for endp=23 modem assert.

The exact pinned TG and donor have byte-identical hw_stats_init, quota, teth,
FnR and drop payload implementations. TG does NOT call ipa_drop_stats_init()
in ipa3_post_init(); both versions DO call FnR inside ipa_hw_stats_init().
Therefore the FnR skip is explicitly an A6g diagnostic experiment, NOT TG
parity. All other IPA hardware revisions retain the donor behavior.

No new SRAM writes, no artificial QMI success, no modem auto-arm.
"""
import argparse
import difflib
import json
from pathlib import Path

IPA = Path("drivers/platform/msm/ipa/ipa_v3/ipa.c")
HW = Path("drivers/platform/msm/ipa/ipa_v3/ipa_hw_stats.c")
MARKER = "P470_A6G_LAGOON47_STATS_NO_DROP_NO_FNR_V1"

FN_HEADERS = {
    "hw": ("int ipa_hw_stats_init(void)", "static void ipa_close_coal_frame("),
    "quota": ("int ipa_init_quota_stats(u32 pipe_bitmask)", "int ipa_get_quota_stats("),
    "teth": ("int ipa_init_teth_stats(struct ipa_teth_stats_endpoints *in)", "int ipa_get_teth_stats("),
    "fnr": ("int ipa_init_flt_rt_stats(void)", "int ipa_get_flt_rt_stats("),
    "drop": ("int ipa_init_drop_stats(u32 pipe_bitmask)", "int ipa_get_drop_stats("),
}


def once(s, old, new, label):
    count = s.count(old)
    if count != 1:
        raise RuntimeError("P470-A6g %s anchor count=%d" % (label, count))
    return s.replace(old, new, 1)


def region(s, start, end, label):
    a = s.find(start)
    b = s.find(end, a + len(start))
    if a < 0 or b <= a:
        raise RuntimeError("P470-A6g missing/ambiguous region: " + label)
    if s.find(start, a + len(start)) >= 0:
        raise RuntimeError("P470-A6g duplicate start: " + label)
    return a, b, s[a:b]


def function(s, name):
    start, end = FN_HEADERS[name]
    return region(s, start, end, name)[2]


def replace_function(s, name, transform):
    a, b, body = region(s, *FN_HEADERS[name], name)
    return s[:a] + transform(body) + s[b:]


FNR_OLD = (
    '\tif (ipa3_ctx->ipa_hw_type >= IPA_HW_v4_5) {\n'
    '\t\tret = ipa_init_flt_rt_stats();\n'
    '\t\tif (ret != 0)\n'
    '\t\t\tIPAERR("init flt rt stats fails\\n");\n'
    '\t}\n'
)
FNR_NEW = (
    '\t/* ' + MARKER + ': FnR skip is a diagnostic deviation from TG. */\n'
    '\tif (ipa3_ctx->ipa_hw_type == IPA_HW_v4_7 &&\n'
    '\t    ipa3_ctx->platform_type == IPA_PLAT_TYPE_MSM) {\n'
    '\t\tpr_info("P470 IPA STATS fnr_init=skipped(a6g-test,not-tg) hw=4.7\\n");\n'
    '\t} else if (ipa3_ctx->ipa_hw_type >= IPA_HW_v4_5) {\n'
    '\t\tret = ipa_init_flt_rt_stats();\n'
    '\t\tif (ret != 0)\n'
    '\t\t\tIPAERR("init flt rt stats fails\\n");\n'
    '\t}\n'
)
SEND_OLD = '\tret = ipa3_send_cmd(num_cmd, desc);\n'
QUOTA_SEND_NEW = (
    '\tret = ipa3_send_cmd(num_cmd, desc);\n'
    '\tif (ipa3_ctx->ipa_hw_type == IPA_HW_v4_7 &&\n'
    '\t    ipa3_ctx->platform_type == IPA_PLAT_TYPE_MSM)\n'
    '\t\tpr_info("P470 IPA STATS QUOTA_WRITE ee=%u reg_mask_ofst=0x%x '
    'mask=0x%08x reg_base_ofst=0x%x base=0x%x sram_ofst=0x%x '
    'sram_len=%u rc=%d\\n",\n'
    '\t\t\tipa3_ctx->ee, quota_mask.offset, quota_mask.value,\n'
    '\t\t\tquota_base.offset, quota_base.value, cmd.local_addr,\n'
    '\t\t\tcmd.size, ret);\n'
)
TETH_SEND_NEW = (
    '\tret = ipa3_send_cmd(num_cmd, desc);\n'
    '\tif (ipa3_ctx->ipa_hw_type == IPA_HW_v4_7 &&\n'
    '\t    ipa3_ctx->platform_type == IPA_PLAT_TYPE_MSM) {\n'
    '\t\tpr_info("P470 IPA STATS TETH_WRITE ee=%u reg_mask_ofst=0x%x '
    'prod_mask=0x%08x reg_base_ofst=0x%x base=0x%x '
    'sram_ofst=0x%x sram_len=%u rc=%d\\n",\n'
    '\t\t\tipa3_ctx->ee, teth_mask.offset, teth_mask.value,\n'
    '\t\t\tteth_base.offset, teth_base.value, cmd.local_addr,\n'
    '\t\t\tcmd.size, ret);\n'
    '\t\tfor (i = 0; i < IPA_STATS_MAX_PIPE_BIT; i++) {\n'
    '\t\t\tif (in->prod_mask & (1U << i))\n'
    '\t\t\t\tpr_info("P470 IPA STATS TETH_CONS ee=%u '
    'prod_ep=%d cons_mask=0x%08x\\n",\n'
    '\t\t\t\t\tipa3_ctx->ee, i, in->dst_ep_mask[i]);\n'
    '\t\t}\n'
    '\t}\n'
)
DROP_OLD = (
    '\tresult = ipa_drop_stats_init();\n'
    '\tpr_info("P470 IPA STATS drop_init rc=%d\\n", result);\n'
    '\tif (result)\n'
    '\t\tIPAERR("fail to init stats %d\\n", result);\n'
    '\telse\n'
    '\t\tIPADBG(":stats init ok\\n");\n'
)
DROP_NEW = (
    '\t/* ' + MARKER + ': leave TG Q6-shared drop SRAM untouched at boot. */\n'
    '\tif (ipa3_ctx->ipa_hw_type == IPA_HW_v4_7 &&\n'
    '\t    ipa3_ctx->platform_type == IPA_PLAT_TYPE_MSM) {\n'
    '\t\tpr_info("P470 IPA STATS boot drop_init=skipped(tg) '
    'fnr_init=skipped(a6g-test,not-tg) hw_stats_init rc=%d '
    'quota_boot_mask=0x00000000\\n", result);\n'
    '\t} else {\n'
    '\t\tresult = ipa_drop_stats_init();\n'
    '\t\tpr_info("P470 IPA STATS drop_init rc=%d\\n", result);\n'
    '\t\tif (result)\n'
    '\t\t\tIPAERR("fail to init stats %d\\n", result);\n'
    '\t\telse\n'
    '\t\t\tIPADBG(":stats init ok\\n");\n'
    '\t}\n'
)


def hw_transform(name, text):
    if name == "hw":
        return once(text, FNR_OLD, FNR_NEW, "FnR hw_stats_init")
    if name == "quota":
        return once(text, SEND_OLD, QUOTA_SEND_NEW, "quota send")
    if name == "teth":
        return once(text, SEND_OLD, TETH_SEND_NEW, "teth send")
    return text


def verify_base(hw, tg):
    for name in FN_HEADERS:
        a, b = function(hw, name), function(tg, name)
        if a != b:
            diff = "".join(difflib.unified_diff(
                b.splitlines(keepends=True), a.splitlines(keepends=True),
                fromfile="TouchGrass:" + name, tofile="pinned donor:" + name))
            raise RuntimeError("P470-A6g TG function mismatch %s:\n%s" %
                               (name, diff[:10000]))


def verify_patched(hw, tg):
    for name in FN_HEADERS:
        expected = hw_transform(name, function(tg, name))
        actual = function(hw, name)
        if actual != expected:
            diff = "".join(difflib.unified_diff(
                expected.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile="expected:" + name, tofile="actual:" + name))
            raise RuntimeError("P470-A6g modified function differs from TG "
                               "baseline + diagnostic delta %s:\n%s" %
                               (name, diff[:10000]))


def verify_ipa(ipa):
    # Use explicit body delimiters: post-init is followed by a named function.
    start = ipa.find("static int ipa3_post_init(")
    if start < 0 or ipa.find("static int ipa3_post_init(", start + 1) >= 0:
        raise RuntimeError("P470-A6g post_init start drift")
    post = ipa[start:]
    if MARKER not in post:
        raise RuntimeError("P470-A6g post_init marker absent")
    if post.count(DROP_NEW) != 1:
        raise RuntimeError("P470-A6g guarded drop init drift")
    if "P470 IPA STATS hw_init rc=%d" not in post:
        raise RuntimeError("P470-A6g previous A6e stats audit missing")
    if "ipa_spearhead_stats_init(" in post[:post.find("ipa3_register_panic_hdlr();")]:
        raise RuntimeError("P470-A6g new spearhead writer in post_init")


def patch(root, tg_root):
    ipa_path, hw_path = root / IPA, root / HW
    tgh = (tg_root / HW).read_text()
    hw = hw_path.read_text()
    ipa = ipa_path.read_text()
    verify_base(hw, tgh)
    if "P470 IPA STATS hw_init rc=%d" not in ipa:
        raise RuntimeError("P470-A6g A6e post_init prerequisite missing")
    if MARKER in ipa or MARKER in hw:
        raise RuntimeError("P470-A6g already applied")
    for name in ("hw", "quota", "teth"):
        hw = replace_function(hw, name, lambda body, name=name:
                              hw_transform(name, body))
    start = ipa.find("static int ipa3_post_init(")
    end = ipa.find("ipa3_register_panic_hdlr();", start)
    if start < 0 or end <= start:
        raise RuntimeError("P470-A6g post_init bounds absent")
    seg = ipa[start:end]
    seg = once(seg, DROP_OLD, DROP_NEW, "post_init drop")
    ipa = ipa[:start] + seg + ipa[end:]
    hw_path.write_text(hw)
    ipa_path.write_text(ipa)
    return check(root, tg_root)


def check(root, tg_root):
    ipa = (root / IPA).read_text()
    hw = (root / HW).read_text()
    tgh = (tg_root / HW).read_text()
    verify_patched(hw, tgh)
    verify_ipa(ipa)
    return {
        "phase": "P470-A6g-LAGOON47-BOOT-STATS",
        "tg_hw_stats_init_base_identical": True,
        "tg_quota_teth_fnr_drop_functions_base_identical": True,
        "tg_post_init_drop_writes": False,
        "lagoon47_boot_drop": "skipped TG parity",
        "lagoon47_boot_fnr": "skipped experimentally; TG itself calls FnR",
        "lagoon47_boot_hw_stats_init": "retained (except FnR subcall)",
        "lagoon47_tethering_stats_sram": "unchanged TG partition and payload",
        "lagoon47_quota_boot_mask": "no automatic quota init",
        "lagoon47_teth_quota_masks": "per EE register and per producer/consumer logged on command submit",
        "other_hardware_revisions": "existing donor path unchanged",
        "other_post_init_stats_writer": "no ipa_spearhead_stats_init in pinned ipa3_post_init",
        "qmi_a6f": "untouched",
        "ipa_disarmed_by_default": True,
        "p469b_fallback_unchanged": True,
        "hardware_modem_assert_fixed": False,
        "modem_init_success_observed": False,
        "ipa_5min_verified": False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--tg", required=True, type=Path)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    result = check(args.root, args.tg) if args.check_only else patch(
        args.root, args.tg)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("P470-A6g Lagoon IPA47 drop boot TG-skip, FnR diagnostic skip, "
          "quota/teth register mask trace SOURCE PASS; modem hardware PENDING")


if __name__ == "__main__":
    main()
