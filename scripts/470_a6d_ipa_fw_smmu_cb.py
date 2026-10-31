#!/usr/bin/env python3
"""P470-A6d: source-only IPA CB-count fallback and FW state-machine diagnostics.

Pinned donor: CodeLinaro dataipa c560cc3c (IPA_SMMU_CB_MAX=4).
Pinned GKI ABI source: CodeLinaro kernel f438c918 (dataipa not in-tree).
Lagoon TG DTS has AP/WLAN/UC CB SIBLINGS under the IPA node's parent.
No DT modification, no implicit IPA arm, no modem wait-policy change.
"""
import argparse
import json
import re
from pathlib import Path

IPA = Path("drivers/platform/msm/ipa/ipa_v3/ipa.c")
GSI = Path("drivers/platform/msm/gsi/gsi.c")
HEADER = Path("drivers/platform/msm/ipa/ipa_v3/ipa_i.h")
TAG = "P470_A6D_IPA_FW_CB_SIBLINGS_V1"
HELPER = r'''
/* P470_A6D_IPA_FW_CB_SIBLINGS_V1
 * Lagoon's AP/WLAN/UC context-bank nodes are siblings of the IPA master,
 * not children of it. Count only available, unique supported types under
 * the same parent. Preserve explicit qcom,max_num_smmu_cb if present.
 */
static u64 p470_a6d_fw_scheduled_ns;
static u64 p470_a6d_fw_work_start_ns;

static int p470_a6d_available_smmu_cbs(struct device_node *ipa_np)
{
	struct device_node *parent, *child;
	unsigned long seen = 0;
	int type, count = 0;

	parent = of_get_parent(ipa_np);
	if (!parent)
		return -EINVAL;
	for_each_available_child_of_node(parent, child) {
		type = -1;
		if (of_device_is_compatible(child, "qcom,ipa-smmu-ap-cb"))
			type = IPA_SMMU_CB_AP;
		else if (of_device_is_compatible(child, "qcom,ipa-smmu-wlan-cb"))
			type = IPA_SMMU_CB_WLAN;
		else if (of_device_is_compatible(child, "qcom,ipa-smmu-uc-cb"))
			type = IPA_SMMU_CB_UC;
		else if (of_device_is_compatible(child, "qcom,ipa-smmu-11ad-cb"))
			type = IPA_SMMU_CB_11AD;
		if (type < 0)
			continue;
		if (test_bit(type, &seen)) {
			pr_err("P470 IPA SMMU_CB duplicate type=%d node=%pOF\n",
			       type, child);
			of_node_put(child);
			of_node_put(parent);
			return -EINVAL;
		}
		set_bit(type, &seen);
		count++;
	}
	of_node_put(parent);
	return count;
}
'''

def once(s, old, new, name):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"P470-A6d {name}: source anchor matches={n}")
    return s.replace(old, new, 1)

def section(s, start, end):
    # The donor has an early ipa3_plat_drv_shutdown() prototype AND the
    # later definition. Bound the region by the FIRST match after start.
    # Never require the end anchor to be globally unique.
    if s.count(start) != 1:
        raise RuntimeError(f"P470-A6d ambiguous function {start}: "
                           f"matches={s.count(start)}")
    a = s.index(start)
    b = s.find(end, a + len(start))
    if b < 0:
        raise RuntimeError(f"P470-A6d missing definition after {start}: {end}")
    if s.find(end, b + len(end)) >= 0:
        raise RuntimeError(f"P470-A6d ambiguous function boundary after {start}")
    return s[a:b]

def patch(s):
    if TAG in s:
        raise RuntimeError("P470-A6d IPA already modified")
    # Must be the A6c source, not raw donor or older A6b.
    for required in ("P470 IPA ARM", "P470 IPA FW_LOAD",
                     "P470_A6_TG_LEGACY_RPMH_CLIENT_V1", "P470 IPA GSI READY"):
        if required not in s:
            raise RuntimeError("P470-A6d expected A6c source missing " + required)
    s = once(s, "#include <linux/of.h>", "#include <linux/of.h>\n#include <linux/ktime.h>\n#include <linux/math64.h>\n#include <linux/bitops.h>",
             "ktime and DT APIs")

    # Functions below follow static smmu_info/smmu_cb definitions and ipa_i.h.
    s = once(s, "#define IPA_SUSPEND_BUSY_TIMEOUT (msecs_to_jiffies(10))",
             "#define IPA_SUSPEND_BUSY_TIMEOUT (msecs_to_jiffies(10))\n" + HELPER,
             "CB sibling discovery and FW timing globals before use")
    before = '''\tresult = of_property_read_u32(pdev->dev.of_node,
\t\t"qcom,max_num_smmu_cb",
\t\t&ipa_drv_res->max_num_smmu_cb);
\tif (result)
\t\tIPADBG(": using default max number of cb = %d\\n",
\t\t\tipa_drv_res->max_num_smmu_cb);
\telse
\t\tIPADBG(": found ipa_drv_res->max_num_smmu_cb = %d\\n",
\t\t\tipa_drv_res->max_num_smmu_cb);'''
    after = '''\t/* P470-A6d: firmware loader waits for the number of real CB
\t * platform children, not all CB types supported by this donor.
\t * The AP/WLAN/UC nodes are siblings of the IPA master in Lagoon.
\t */
\tresult = of_property_read_u32(pdev->dev.of_node,
\t\t"qcom,max_num_smmu_cb",
\t\t&ipa_drv_res->max_num_smmu_cb);
\tif (!result) {
\t\tpr_info("P470 IPA SMMU_CB max=%u source=property platform=%u\\n",
\t\t\tipa_drv_res->max_num_smmu_cb,
\t\t\tipa_drv_res->platform_type);
\t} else if (of_machine_is_compatible("qcom,lagoon") &&\n\t\t   !of_find_property(pdev->dev.of_node,
\t\t\t\t     "qcom,max_num_smmu_cb", NULL) &&
\t\t   of_property_read_bool(pdev->dev.of_node, "qcom,arm-smmu")) {
\t\tint count = p470_a6d_available_smmu_cbs(pdev->dev.of_node);

\t\tif (count <= 0 || count > IPA_SMMU_CB_MAX) {
\t\t\tpr_err("P470 IPA SMMU_CB invalid DT count=%d\\n", count);
\t\t\treturn -EINVAL;
\t\t}
\t\tipa_drv_res->max_num_smmu_cb = count;
\t\tpr_info("P470 IPA SMMU_CB max=%u source=dt_nodes platform=%u\\n",
\t\t\tipa_drv_res->max_num_smmu_cb,
\t\t\tipa_drv_res->platform_type);
\t} else if (result && of_find_property(pdev->dev.of_node,
\t\t\t\t"qcom,max_num_smmu_cb", NULL)) {
\t\tpr_err("P470 IPA SMMU_CB malformed DT property rc=%d\\n",
\t\t\tresult);
\t\treturn result;
\t} else {
\t\tpr_info("P470 IPA SMMU_CB max=%u source=no_smmu\\n",
\t\t\tipa_drv_res->max_num_smmu_cb);
\t}'''
    s = once(s, before, after, "DT optional max CB property")
    # This branch is before the firmware loader's FW state machine.
    part=section(s,"static void ipa_smmu_update_fw_loader(void)","void ipa3_plat_drv_shutdown(")
    part=once(part,'''\
\tif (smmu_info.arm_smmu) {
\t\tIPADBG("smmu is enabled\\n");''','''\
\tif (smmu_info.arm_smmu) {
\t\tpr_info("P470 IPA SMMU_CB probed=%d/%d\\n",
\t\t\tipa3_ctx->num_smmu_cb_probed,
\t\t\tipa3_ctx->max_num_smmu_cb);
\t\tIPADBG("smmu is enabled\\n");''',"probe count log")
    s=s.replace(section(s,"static void ipa_smmu_update_fw_loader(void)","void ipa3_plat_drv_shutdown("),part,1)

    s=once(s, '''\tIPADBG("state=%d event=%d\\n", ipa3_ctx->fw_load_data.state, ev);''',
        '''\tpr_info("P470 IPA FW_SM event=%d state=%d\\n",
\t\tev, ipa3_ctx->fw_load_data.state);
\tIPADBG("state=%d event=%d\\n", ipa3_ctx->fw_load_data.state, ev);''', "FW state and event log")
    s=once(s, '''sched_fw_load:
\tIPADBG("Scheduled a work to load IPA FW\\n");
\tmutex_unlock(&ipa3_ctx->fw_load_data.lock);
\tqueue_work(ipa3_ctx->transport_power_mgmt_wq,
\t\t&ipa3_fw_loading_work);''',
        '''sched_fw_load:
\tWRITE_ONCE(p470_a6d_fw_scheduled_ns, ktime_get_ns());
\tpr_info("P470 IPA FW_SM schedule=1 event=%d state=%d\\n",
\t\tev, ipa3_ctx->fw_load_data.state);
\tIPADBG("Scheduled a work to load IPA FW\\n");
\tmutex_unlock(&ipa3_ctx->fw_load_data.lock);
\tqueue_work(ipa3_ctx->transport_power_mgmt_wq,
\t\t&ipa3_fw_loading_work);''', "FW work scheduling")

    # These timestamps let the hardware collector compare load duration to
    # the unchanged 15 s bounded MSS wait, without claiming a CI timing.
    s=once(s,'''static void ipa3_load_ipa_fw(struct work_struct *work)
{
\tint result;

\tIPADBG("Entry\\n");''',
       '''static void ipa3_load_ipa_fw(struct work_struct *work)
{
\tint result;
\tu64 now_ns, sched_ns;

\tnow_ns = ktime_get_ns();
\tWRITE_ONCE(p470_a6d_fw_work_start_ns, now_ns);
\tsched_ns = READ_ONCE(p470_a6d_fw_scheduled_ns);
\tpr_info("P470 IPA FW_SM work_start schedule_to_start_ms=%llu\\n",
\t\t(unsigned long long)(sched_ns ?
\t\tdiv_u64(now_ns - sched_ns, NSEC_PER_MSEC) : 0));
\tIPADBG("Entry\\n");''', "FW load work start")
    s=once(s, '''\tresult = ipa3_post_init(&ipa3_res, ipa3_ctx->cdev.dev);
\tif (result) {
\t\tIPAERR("IPA post init failed %d\\n", result);
\t\treturn;
\t}''','''\tresult = ipa3_post_init(&ipa3_res, ipa3_ctx->cdev.dev);
\tpr_info("P470 IPA FW_SM post_init_rc=%d fw_work_ms=%llu schedule_to_post_init_ms=%llu\\n",
\t\tresult,
\t\t(unsigned long long)div_u64(ktime_get_ns() -
\t\tREAD_ONCE(p470_a6d_fw_work_start_ns), NSEC_PER_MSEC),
\t\t(unsigned long long)div_u64(ktime_get_ns() -
\t\tREAD_ONCE(p470_a6d_fw_scheduled_ns), NSEC_PER_MSEC));
\tif (result) {
\t\tIPAERR("IPA post init failed %d\\n", result);
\t\treturn;
\t}''',"FW duration through post_init")

    # Match A4's real subsystem_get path without redefining its PAS15 gate.
    s=once(s, '''\tpr_info("P470 IPA FW_LOAD subsystem_get=%s\\n", sub_sys);
\tipa3_ctx->subsystem_get_retval = subsystem_get(sub_sys);''',
       '''\tpr_info("P470 IPA FW_LOAD subsystem_get=%s\\n", sub_sys);
\t{
\t\tu64 begin_ns = ktime_get_ns();

\t\tipa3_ctx->subsystem_get_retval = subsystem_get(sub_sys);
\t\tpr_info("P470 IPA FW_SM subsystem_get_ms=%llu success=%d\\n",
\t\t\t(unsigned long long)div_u64(ktime_get_ns() -
\t\t\tbegin_ns, NSEC_PER_MSEC),
\t\t\t!IS_ERR_OR_NULL(ipa3_ctx->subsystem_get_retval));
\t}''', "PAS15 acquisition elapsed time")
    return s

def check(root):
    s=(root / IPA).read_text()
    hdr=(root / HEADER).read_text()
    gsi=(root / GSI).read_text()
    if not re.search(r'enum ipa_smmu_cb_type\s*\{\s*IPA_SMMU_CB_AP,\s*IPA_SMMU_CB_WLAN,\s*IPA_SMMU_CB_UC,\s*IPA_SMMU_CB_11AD,\s*IPA_SMMU_CB_MAX',hdr):
        raise RuntimeError("A6d pinned donor CB enum not 4: stop")
    for key in (TAG, 'for_each_available_child_of_node(parent, child)',
                'of_get_parent(ipa_np)', 'source=dt_nodes', 'source=property',
                'P470 IPA SMMU_CB probed=%d/%d',
                'P470 IPA FW_SM event=%d state=%d',
                'P470 IPA FW_SM schedule=1',
                'P470 IPA FW_SM work_start',
                'schedule_to_post_init_ms=%llu',
                'P470 IPA FW_SM subsystem_get_ms=%llu',
                'P470 IPA FW_LOAD PAS15 acquisition OK'):
        if key not in s:
            raise RuntimeError("A6d source missing: "+key)
    if 'gsi_pending_irq_type(void)' not in gsi or \
       'GSIERR("no client registered\\n");\n\t\treturn 0;' not in gsi:
        raise RuntimeError("A6d GSI no-client warning isn't a harmless zero return")
    if 'IPA_PLAT_TYPE_MSM\t= 1' not in hdr:
        raise RuntimeError("A6d platform enum not MSM=1")
    return dict(phase="P470-A6d-IPA-SMMU-CB-FW-SM",
                donor_sha="c560cc3c2840fb0ebc55ceef5b27549c66143637",
                gki_abi_pin="f438c918a464b82d4a637b5327dd1ed6e8b625dc",
                smmu_cb_types=["AP", "WLAN", "UC", "11AD"],
                smmu_cb_max=4,
                expected_lagoon_available_cb_count=3,
                active_dt_count_runtime=True,
                property_precedence=True,
                dt_modified=False, ipa_default_disarmed=True,
                gsi_pre_registration_warn_return=0,
                gsi_pre_registration_warn_ignored=False,
                platform_type_msm_value=1,
                modem_wait_budget_ms=15000,
                firmware_load_duration_ms=None,
                firmware_load_duration_source="hardware P470 IPA FW_SM schedule_to_post_init_ms log",
                firmware_load_vs_15s="unmeasured pending next phone boot",
                runtime_verified=False)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    if not a.check_only:
        pth=a.root/IPA
        pth.write_text(patch(pth.read_text()))
    result=check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P470-A6d CB siblings fallback + FW state machine timings SOURCE PASS; hardware PENDING, IPA default DISARMED")

if __name__ == "__main__":
    main()
