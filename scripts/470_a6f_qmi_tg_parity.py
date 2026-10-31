#!/usr/bin/env python3
"""P470-A6f: pinned TouchGrass 4.19 IPA 4.7 parity, INIT_MODEM audit, no BUG.

Keeps all other hardware versions intact. Refuses donor drift. This is a
diagnostic candidate and deliberately does not auto-arm IPA.
"""
import argparse
import json
import re
from pathlib import Path

TG_COMMIT = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
DONOR_COMMIT = "c560cc3c2840fb0ebc55ceef5b27549c66143637"
UTILS = Path("drivers/platform/msm/ipa/ipa_v3/ipa_utils.c")
QMI = Path("drivers/platform/msm/ipa/ipa_v3/ipa_qmi_service.c")
QMI_CODEC = Path("drivers/platform/msm/ipa/ipa_v3/ipa_qmi_service_v01.c")
STATS = Path("drivers/platform/msm/ipa/ipa_v3/ipa_hw_stats.c")
MARKER = "P470_A6F_TG_IPA47_QMI_NO_BUG_V1"

# Every field in each pinned IPA 4.7 partition, not just the QMI subset.

TG_PART = {
    "uc_info_ofst": "0x80",
    "uc_info_size": "0x200",
    "ofst_start": "0x280",
    "v4_flt_hash_ofst": "0x288",
    "v4_flt_hash_size": "0x78",
    "v4_flt_hash_size_ddr": "0x4000",
    "v4_flt_nhash_ofst": "0x308",
    "v4_flt_nhash_size": "0x78",
    "v4_flt_nhash_size_ddr": "0x4000",
    "v6_flt_hash_ofst": "0x388",
    "v6_flt_hash_size": "0x78",
    "v6_flt_hash_size_ddr": "0x4000",
    "v6_flt_nhash_ofst": "0x408",
    "v6_flt_nhash_size": "0x78",
    "v6_flt_nhash_size_ddr": "0x4000",
    "v4_rt_num_index": "0xf",
    "v4_modem_rt_index_lo": "0x0",
    "v4_modem_rt_index_hi": "0x7",
    "v4_apps_rt_index_lo": "0x8",
    "v4_apps_rt_index_hi": "0xe",
    "v4_rt_hash_ofst": "0x488",
    "v4_rt_hash_size": "0x78",
    "v4_rt_hash_size_ddr": "0x4000",
    "v4_rt_nhash_ofst": "0x508",
    "v4_rt_nhash_size": "0x78",
    "v4_rt_nhash_size_ddr": "0x4000",
    "v6_rt_num_index": "0xf",
    "v6_modem_rt_index_lo": "0x0",
    "v6_modem_rt_index_hi": "0x7",
    "v6_apps_rt_index_lo": "0x8",
    "v6_apps_rt_index_hi": "0xe",
    "v6_rt_hash_ofst": "0x588",
    "v6_rt_hash_size": "0x78",
    "v6_rt_hash_size_ddr": "0x4000",
    "v6_rt_nhash_ofst": "0x608",
    "v6_rt_nhash_size": "0x78",
    "v6_rt_nhash_size_ddr": "0x4000",
    "modem_hdr_ofst": "0x688",
    "modem_hdr_size": "0x240",
    "apps_hdr_ofst": "0x8c8",
    "apps_hdr_size": "0x200",
    "apps_hdr_size_ddr": "0x800",
    "modem_hdr_proc_ctx_ofst": "0xad0",
    "modem_hdr_proc_ctx_size": "0xAC0",
    "apps_hdr_proc_ctx_ofst": "0x1590",
    "apps_hdr_proc_ctx_size": "0x200",
    "apps_hdr_proc_ctx_size_ddr": "0x0",
    "nat_tbl_ofst": "0x17A0",
    "nat_tbl_size": "0xd00",
    "pdn_config_ofst": "0x24A8",
    "pdn_config_size": "0x50",
    "stats_quota_q6_ofst": "0x2500",
    "stats_quota_q6_size": "0x30",
    "stats_quota_ap_ofst": "0x2530",
    "stats_quota_ap_size": "0x48",
    "stats_tethering_ofst": "0x2578",
    "stats_tethering_size": "0x238",
    "stats_flt_v4_ofst": "0",
    "stats_flt_v4_size": "0",
    "stats_flt_v6_ofst": "0",
    "stats_flt_v6_size": "0",
    "stats_rt_v4_ofst": "0",
    "stats_rt_v4_size": "0",
    "stats_rt_v6_ofst": "0",
    "stats_rt_v6_size": "0",
    "stats_fnr_ofst": "0x27B0",
    "stats_fnr_size": "0x0",
    "stats_drop_ofst": "0x27B0",
    "stats_drop_size": "0x20",
    "modem_comp_decomp_ofst": "0x0",
    "modem_comp_decomp_size": "0x0",
    "modem_ofst": "0x27D8",
    "modem_size": "0x800",
    "apps_v4_flt_hash_ofst": "0x27B0",
    "apps_v4_flt_hash_size": "0x0",
    "apps_v4_flt_nhash_ofst": "0x27B0",
    "apps_v4_flt_nhash_size": "0x0",
    "apps_v6_flt_hash_ofst": "0x27B0",
    "apps_v6_flt_hash_size": "0x0",
    "apps_v6_flt_nhash_ofst": "0x27B0",
    "apps_v6_flt_nhash_size": "0x0",
    "apps_v4_rt_hash_ofst": "0x27B0",
    "apps_v4_rt_hash_size": "0x0",
    "apps_v4_rt_nhash_ofst": "0x27B0",
    "apps_v4_rt_nhash_size": "0x0",
    "apps_v6_rt_hash_ofst": "0x27B0",
    "apps_v6_rt_hash_size": "0x0",
    "apps_v6_rt_nhash_ofst": "0x27B0",
    "apps_v6_rt_nhash_size": "0x0",
    "uc_descriptor_ram_ofst": "0x3000",
    "uc_descriptor_ram_size": "0x0000",
    "end_ofst": "0x3000"
}
DONOR_PART = {
    "uc_info_ofst": "0x80",
    "uc_info_size": "0x200",
    "ofst_start": "0x280",
    "v4_flt_hash_ofst": "0x288",
    "v4_flt_hash_size": "0x78",
    "v4_flt_hash_size_ddr": "0x4000",
    "v4_flt_nhash_ofst": "0x308",
    "v4_flt_nhash_size": "0x78",
    "v4_flt_nhash_size_ddr": "0x4000",
    "v6_flt_hash_ofst": "0x388",
    "v6_flt_hash_size": "0x78",
    "v6_flt_hash_size_ddr": "0x4000",
    "v6_flt_nhash_ofst": "0x408",
    "v6_flt_nhash_size": "0x78",
    "v6_flt_nhash_size_ddr": "0x4000",
    "v4_rt_num_index": "0xf",
    "v4_modem_rt_index_lo": "0x0",
    "v4_modem_rt_index_hi": "0x7",
    "v4_apps_rt_index_lo": "0x8",
    "v4_apps_rt_index_hi": "0xe",
    "v4_rt_hash_ofst": "0x488",
    "v4_rt_hash_size": "0x78",
    "v4_rt_hash_size_ddr": "0x4000",
    "v4_rt_nhash_ofst": "0x508",
    "v4_rt_nhash_size": "0x78",
    "v4_rt_nhash_size_ddr": "0x4000",
    "v6_rt_num_index": "0xf",
    "v6_modem_rt_index_lo": "0x0",
    "v6_modem_rt_index_hi": "0x7",
    "v6_apps_rt_index_lo": "0x8",
    "v6_apps_rt_index_hi": "0xe",
    "v6_rt_hash_ofst": "0x588",
    "v6_rt_hash_size": "0x78",
    "v6_rt_hash_size_ddr": "0x4000",
    "v6_rt_nhash_ofst": "0x608",
    "v6_rt_nhash_size": "0x78",
    "v6_rt_nhash_size_ddr": "0x4000",
    "modem_hdr_ofst": "0x688",
    "modem_hdr_size": "0x240",
    "apps_hdr_ofst": "0x8c8",
    "apps_hdr_size": "0x200",
    "apps_hdr_size_ddr": "0x800",
    "modem_hdr_proc_ctx_ofst": "0xad0",
    "modem_hdr_proc_ctx_size": "0x200",
    "apps_hdr_proc_ctx_ofst": "0xcd0",
    "apps_hdr_proc_ctx_size": "0x200",
    "apps_hdr_proc_ctx_size_ddr": "0x0",
    "nat_tbl_ofst": "0xee0",
    "nat_tbl_size": "0xd00",
    "pdn_config_ofst": "0x1be8",
    "pdn_config_size": "0x50",
    "stats_quota_q6_ofst": "0x1c40",
    "stats_quota_q6_size": "0x30",
    "stats_quota_ap_ofst": "0x1c70",
    "stats_quota_ap_size": "0x48",
    "stats_tethering_ofst": "0x1cb8",
    "stats_tethering_size": "0x238",
    "stats_flt_v4_ofst": "0",
    "stats_flt_v4_size": "0",
    "stats_flt_v6_ofst": "0",
    "stats_flt_v6_size": "0",
    "stats_rt_v4_ofst": "0",
    "stats_rt_v4_size": "0",
    "stats_rt_v6_ofst": "0",
    "stats_rt_v6_size": "0",
    "stats_fnr_ofst": "0x1ef0",
    "stats_fnr_size": "0x0",
    "stats_drop_ofst": "0x1ef0",
    "stats_drop_size": "0x20",
    "modem_comp_decomp_ofst": "0x0",
    "modem_comp_decomp_size": "0x0",
    "modem_ofst": "0x1f18",
    "modem_size": "0x100c",
    "apps_v4_flt_hash_ofst": "0x1f18",
    "apps_v4_flt_hash_size": "0x0",
    "apps_v4_flt_nhash_ofst": "0x1f18",
    "apps_v4_flt_nhash_size": "0x0",
    "apps_v6_flt_hash_ofst": "0x1f18",
    "apps_v6_flt_hash_size": "0x0",
    "apps_v6_flt_nhash_ofst": "0x1f18",
    "apps_v6_flt_nhash_size": "0x0",
    "apps_v4_rt_hash_ofst": "0x1f18",
    "apps_v4_rt_hash_size": "0x0",
    "apps_v4_rt_nhash_ofst": "0x1f18",
    "apps_v4_rt_nhash_size": "0x0",
    "apps_v6_rt_hash_ofst": "0x1f18",
    "apps_v6_rt_hash_size": "0x0",
    "apps_v6_rt_nhash_ofst": "0x1f18",
    "apps_v6_rt_nhash_size": "0x0",
    "uc_descriptor_ram_ofst": "0x3000",
    "uc_descriptor_ram_size": "0x0000",
    "end_ofst": "0x3000"
}

PART_RE = re.compile(
    r"static struct ipa3_mem_partition ipa_4_7_mem_part = \{(?P<body>[\s\S]*?)\n\};")
PART_FIELD_RE = re.compile(r"\.([A-Za-z0-9_]+)\s*=\s*(0x[0-9a-fA-F]+|[0-9]+)\s*,")
# Actual fields present in the pinned donor request. Log validity bits too.
REQUEST_FIELDS = (
    "platform_type_valid", "platform_type",
    "hdr_tbl_info_valid", "hdr_tbl_info.modem_offset_start",
    "hdr_tbl_info.modem_offset_end",
    "v4_route_tbl_info_valid", "v4_route_tbl_info.route_tbl_start_addr",
    "v4_route_tbl_info.num_indices",
    "v6_route_tbl_info_valid", "v6_route_tbl_info.route_tbl_start_addr",
    "v6_route_tbl_info.num_indices",
    "v4_filter_tbl_start_addr_valid", "v4_filter_tbl_start_addr",
    "v6_filter_tbl_start_addr_valid", "v6_filter_tbl_start_addr",
    "modem_mem_info_valid", "modem_mem_info.block_start_addr",
    "modem_mem_info.size",
    "ctrl_comm_dest_end_pt_valid", "ctrl_comm_dest_end_pt",
    "hdr_proc_ctx_tbl_info_valid",
    "hdr_proc_ctx_tbl_info.modem_offset_start",
    "hdr_proc_ctx_tbl_info.modem_offset_end",
    "zip_tbl_info_valid", "zip_tbl_info.modem_offset_start",
    "zip_tbl_info.modem_offset_end",
    "v4_hash_route_tbl_info_valid",
    "v4_hash_route_tbl_info.route_tbl_start_addr",
    "v4_hash_route_tbl_info.num_indices",
    "v6_hash_route_tbl_info_valid",
    "v6_hash_route_tbl_info.route_tbl_start_addr",
    "v6_hash_route_tbl_info.num_indices",
    "v4_hash_filter_tbl_start_addr_valid", "v4_hash_filter_tbl_start_addr",
    "v6_hash_filter_tbl_start_addr_valid", "v6_hash_filter_tbl_start_addr",
    "hw_stats_quota_base_addr_valid", "hw_stats_quota_base_addr",
    "hw_stats_quota_size_valid", "hw_stats_quota_size",
    "hw_drop_stats_base_addr_valid", "hw_drop_stats_base_addr",
    "hw_drop_stats_table_size_valid", "hw_drop_stats_table_size",
    "is_ssr_bootup_valid", "is_ssr_bootup",
)

def once(s, old, new, label):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"P470-A6f {label}: anchor count={count}")
    return s.replace(old, new, 1)

def get_partition(s):
    m = PART_RE.search(s)
    if not m:
        raise RuntimeError("P470-A6f IPA 4.7 partition missing")
    entries = PART_FIELD_RE.findall(m.group("body"))
    part = dict(entries)
    if len(entries) != 92 or len(part) != 92:
        raise RuntimeError(f"P470-A6f IPA 4.7 partition size={len(entries)}")
    return m, part

def legacy_qmi_contract(s, codec):
    start = s.find("static int ipa3_qmi_init_modem_send_sync_msg(void)")
    end = s.find("/* sending filter-install-request to modem*/", start)
    if start < 0 or end <= start:
        raise RuntimeError("P470-A6f QMI function boundary changed")
    function = s[start:end]
    if "memset(&req, 0, sizeof(struct ipa_init_modem_driver_req_msg_v01));" not in function:
        raise RuntimeError("P470-A6f QMI optional TLV zero-init missing")
    extra = ("per_stats_smem_info", "hw_fiter_stats_info", "smem_info_valid")
    if any(name in codec for name in extra):
        raise RuntimeError("P470-A6f QMI encoder is no longer TG legacy field set")
    if any("req." + name in function for name in extra):
        raise RuntimeError("P470-A6f QMI builder now sets incompatible stats TLV")
    return function

def make_full_request_log():
    logs = [
        "\t/* P470_A6F_TG_IPA47_QMI_NO_BUG_V1: every legacy field and validity bit. */",
        "\tpr_info(\"P470 QMI INIT_MODEM smem_restr_bytes=%u ipa_hw=%u pipes=%u\\n\",",
        "\t\tsmem_restr_bytes, ipa3_ctx->ipa_hw_type, ipa3_ctx->ipa_num_pipes);",
        "\tpr_info(\"P470 QMI INIT_MODEM legacy_optional per_stats_smem_info_valid=0 hw_fiter_stats_info_valid=0 smem_info_valid=0\\n\");",
    ]
    for i in range(0, len(REQUEST_FIELDS), 3):
        batch = REQUEST_FIELDS[i:i+3]
        fmt = " ".join(name.replace(".", "_") + "=%llu" for name in batch)
        args = ", ".join("(unsigned long long)req." + name for name in batch)
        logs.extend((
            f'\tpr_info("P470 QMI INIT_MODEM {fmt}\\n",',
            f"\t\t{args});",
        ))
    return "\n".join(logs) + "\n\n"

def patch(root):
    util_path = root / UTILS
    u = util_path.read_text()
    m, current = get_partition(u)
    if current != DONOR_PART:
        different = {k: (current.get(k), v) for k, v in DONOR_PART.items()
                     if current.get(k) != v}
        raise RuntimeError("P470-A6f donor 4.7 partition drift " + str(different))
    changed = m.group(0)
    for field, value in TG_PART.items():
        if current[field].lower() == value.lower():
            continue
        pattern = re.compile(r"(\." + re.escape(field) + r"\s*=\s*)"
                             + re.escape(current[field]) + r"(\s*,)")
        changed, count = pattern.subn(lambda x: x.group(1) + value + x.group(2),
                                      changed)
        if count != 1:
            raise RuntimeError("P470-A6f IPA47 map field count " + field)
    u = u[:m.start()] + changed + u[m.end():]
    marker = (
        '\tcase IPA_HW_v4_7:\n'
        '\t\tipa3_ctx->ctrl->mem_partition = &ipa_4_7_mem_part;\n'
        '\t\tbreak;'
    )
    replacement = (
        '\tcase IPA_HW_v4_7:\n'
        '\t\tipa3_ctx->ctrl->mem_partition = &ipa_4_7_mem_part;\n'
        '\t\tpr_info("P470 IPA47 TG SRAM ctx_size=0x%x quota_q6=0x%x drop=0x%x modem_ofst=0x%x modem_size=0x%x\\n",\n'
        '\t\t\tIPA_MEM_PART(modem_hdr_proc_ctx_size),\n'
        '\t\t\tIPA_MEM_PART(stats_quota_q6_ofst),\n'
        '\t\t\tIPA_MEM_PART(stats_drop_ofst),\n'
        '\t\t\tIPA_MEM_PART(modem_ofst), IPA_MEM_PART(modem_size));\n'
        '\t\tbreak;'
    )
    u = once(u, marker, replacement, "4.7 runtime table audit")
    util_path.write_text(u)

    path = root / QMI
    s = path.read_text()
    codec = (root / QMI_CODEC).read_text()
    legacy_qmi_contract(s, codec)
    # Pinned IPA4.7 modem has pipes 0..22 and APPS_WAN_CONS=16.
    s = once(s,
        '\treq.hdr_proc_ctx_tbl_info_valid =\n',
        '\tif (ipa3_ctx->ipa_hw_type == IPA_HW_v4_7 &&\n'
        '\t    (ipa3_ctx->ipa_num_pipes != 23 ||\n'
        '\t     !req.ctrl_comm_dest_end_pt_valid ||\n'
        '\t     req.ctrl_comm_dest_end_pt != 16)) {\n'
        '\t\tpr_err("P470 QMI INIT_MODEM TG47 endpoint guard: pipes=%u ctrl_valid=%u ctrl_ep=%u rc=-22\\n",\n'
        '\t\t\tipa3_ctx->ipa_num_pipes,\n'
        '\t\t\treq.ctrl_comm_dest_end_pt_valid,\n'
        '\t\t\treq.ctrl_comm_dest_end_pt);\n'
        '\t\treturn -EINVAL;\n'
        '\t}\n\n'
        '\treq.hdr_proc_ctx_tbl_info_valid =\n',
        "IPA47 endpoint guard")
    s = once(s,
        '\treq_desc.max_msg_len = QMI_IPA_INIT_MODEM_DRIVER_REQ_MAX_MSG_LEN_V01;\n',
        make_full_request_log() +
        '\treq_desc.max_msg_len = QMI_IPA_INIT_MODEM_DRIVER_REQ_MAX_MSG_LEN_V01;\n',
        "full QMI request log")
    s = once(s,
        '\tif (unlikely(!ipa_q6_clnt))\n\t\treturn -ETIMEDOUT;',
        '\tif (unlikely(!ipa_q6_clnt)) {\n'
        '\t\tpr_err("P470 QMI INIT_MODEM no Q6 client rc=%d\\n", -ETIMEDOUT);\n'
        '\t\treturn -ETIMEDOUT;\n'
        '\t}',
        "missing QMI client")
    s = once(s,
        '\tif (rc < 0) {\n\t\tIPAWANERR("QMI send Req %d failed, rc= %d\\n",',
        '\tpr_info("P470 QMI INIT_MODEM response transport_rc=%d result=%u error=%u\\n",\n'
        '\t\trc, resp.resp.result, resp.resp.error);\n'
        '\tif (rc < 0) {\n\t\tIPAWANERR("QMI send Req %d failed, rc= %d\\n",',
        "transport response report")
    s = once(s,
        '\tpr_info("QMI_IPA_INIT_MODEM_DRIVER_REQ_V01 response received\\n");\n'
        '\treturn ipa3_check_qmi_response(rc,\n'
        '\t\tQMI_IPA_INIT_MODEM_DRIVER_REQ_V01, resp.resp.result,\n'
        '\t\tresp.resp.error, "ipa_init_modem_driver_resp_msg_v01");',
        '\tpr_info("QMI_IPA_INIT_MODEM_DRIVER_REQ_V01 response received\\n");\n'
        '\trc = ipa3_check_qmi_response(rc,\n'
        '\t\tQMI_IPA_INIT_MODEM_DRIVER_REQ_V01, resp.resp.result,\n'
        '\t\tresp.resp.error, "ipa_init_modem_driver_resp_msg_v01");\n'
        '\tpr_info("P470 QMI INIT_MODEM checked_rc=%d result=%u error=%u\\n",\n'
        '\t\trc, resp.resp.result, resp.resp.error);\n'
        '\treturn rc;',
        "checked response")
    s = once(s,
        '\tif (rc != 0) {\n'
        '\t\tIPAWANERR("ipa3_qmi_init_modem_send_sync_msg failed\\n");\n'
        '\t\t/*\n'
        '\t\t * Hardware not responding.\n'
        '\t\t * This is a very unexpected scenario\n'
        '\t\t * which requires a kernel panic in\n'
        '\t\t * order to force dumps for QMI/Q6 side analysis.\n'
        '\t\t */\n'
        '\t\tBUG();\n'
        '\t}',
        '\tif (rc != 0) {\n'
        '\t\t/* P470-A6f: fail closed, do not claim Q6 IPA readiness. */\n'
        '\t\tpr_err("P470 RMNET QMI INIT_MODEM failed rc=%d (A52 test: no BUG)\\n", rc);\n'
        '\t\tipa3_qmi_modem_init_fin = false;\n'
        '\t\treturn;\n'
        '\t}',
        "Q6 service-arrive BUG fail-closed")
    path.write_text(s)
    return check(root)

def check(root):
    u = (root / UTILS).read_text()
    q = (root / QMI).read_text()
    codec = (root / QMI_CODEC).read_text()
    hw = (root / STATS).read_text()
    _, actual = get_partition(u)
    if actual != TG_PART:
        different = {k: (actual.get(k), v) for k, v in TG_PART.items()
                     if actual.get(k) != v}
        raise RuntimeError("P470-A6f IPA47 != TG: " + str(different))
    body = legacy_qmi_contract(q, codec)
    if MARKER not in body:
        raise RuntimeError("P470-A6f full QMI field logging not compiled")
    for f in REQUEST_FIELDS:
        if f"req.{f}" not in body:
            raise RuntimeError("P470-A6f missing QMI field " + f)
    for need in (
        "P470 IPA47 TG SRAM", "stats_quota_q6_ofst",
        "modem_hdr_proc_ctx_size",
    ):
        if need not in u:
            raise RuntimeError("P470-A6f missing IPA47 layout marker " + need)
    for need in (
        "P470 QMI INIT_MODEM legacy_optional",
        "P470 QMI INIT_MODEM response transport_rc=",
        "P470 QMI INIT_MODEM checked_rc=",
        "P470 QMI INIT_MODEM TG47 endpoint guard:",
        "P470 RMNET QMI INIT_MODEM failed rc=%d (A52 test: no BUG)",
    ):
        if need not in q:
            raise RuntimeError("P470-A6f missing request or fail-closed marker " + need)
    svc_start = q.find("static void ipa3_q6_clnt_svc_arrive(struct work_struct *work)",
                       q.find("static int ipa3_qmi_init_modem_send_sync_msg(void)"))
    svc_end = q.find("static void ipa3_q6_clnt_svc_exit(struct work_struct *work)", svc_start)
    if svc_start < 0 or svc_end <= svc_start:
        raise RuntimeError("P470-A6f svc_arrive audit boundaries missing")
    svc_body = q[svc_start:svc_end]
    if "BUG();" in svc_body:
        raise RuntimeError("P470-A6f svc_arrive still contains BUG()")
    if not re.search(r'if \(rc != 0\) \{\s*/\* P470-A6f: fail closed,[\s\S]*?ipa3_qmi_modem_init_fin = false;\s*return;\s*\}', svc_body):
        raise RuntimeError("P470-A6f service-arrive failure is not fail-closed")
    # TG's 4.7 IPA HW stats setup, including the >=4.5 FnR call, is kept.
    for need in ("int ipa_hw_stats_init(void)", "ipa_init_flt_rt_stats();",
                 "ipa_init_teth_stats(teth_stats_init);"):
        if need not in hw:
            raise RuntimeError("P470-A6f missing HW stats parity guard " + need)
    difference = {k: {"tg": TG_PART[k], "donor": DONOR_PART[k]}
                  for k in TG_PART if TG_PART[k].lower() != DONOR_PART[k].lower()}
    if len(difference) != 19:
        raise RuntimeError("P470-A6f expected 19 IPA47 partition differences")
    return {
        "phase": "P470-A6f-INIT-MODEM-TG47-FAILCLOSED",
        "donor_commit": DONOR_COMMIT, "tg_commit": TG_COMMIT,
        "ipa47_partition_fields_audited": len(TG_PART),
        "ipa47_partition_differences_corrected": difference,
        "ipa47_partition_tg_parity": True,
        "legacy_three_stats_tlvs_absent_in_pinned_encoder": True,
        "legacy_qmi_request_fields_logged": list(REQUEST_FIELDS),
        "endpoint_guard_pipe_count": 23, "ctrl_comm_dest_end_pt": 16,
        "init_modem_response_result_and_error_logged": True,
        "svc_arrive_non_ssr_failure_returns_without_bug": True,
        "no_synthetic_modem_success": True,
        "ipa_default_disarmed": True, "p469b_fallback_unchanged": True,
        "runtime_modem_assert_fixed": False, "hardware_5min_stability_verified": False,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--report", type=Path)
    opts = ap.parse_args()
    result = check(opts.root) if opts.check_only else patch(opts.root)
    if opts.report:
        opts.report.parent.mkdir(parents=True, exist_ok=True)
        opts.report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(f"P470-A6f TG IPA47 memory parity PASS: {len(TG_PART)} fields, 19 corrected; "
          "full QMI request/response audit and fail-closed svc_arrive PASS; hardware PENDING")

if __name__ == "__main__":
    main()
