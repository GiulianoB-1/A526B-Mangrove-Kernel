#!/usr/bin/env python3
"""P470-A6: real TG msm_bus client for legacy-only Lagoon IPA DT.

Runs AFTER A5; uses Phase252's real CONFIG_QCOM_BUS_SCALING RPMh stack.
No new DT or ICC provider, no fake client or update function. All changes
are strictly scoped to Lagoon, only when interconnects is absent.
"""
import argparse
import json
import re
from pathlib import Path

IPA = Path("drivers/platform/msm/ipa/ipa_v3/ipa.c")
TAG = "P470_A6_TG_LEGACY_RPMH_CLIENT_V1"
HELPER = r'''
/* P470_A6_TG_LEGACY_RPMH_CLIENT_V1
 * Both config symbols are required: msm-bus.h has UNSAFE no-op stubs
 * if CONFIG_QCOM_BUS_SCALING is off. Do not compile a fake bus voter.
 */
#if !defined(CONFIG_QCOM_BUS_SCALING) || !defined(CONFIG_QCOM_BUS_CONFIG_RPMH)
#error "P470-A6 Lagoon IPA requires the real Phase252 msm_bus RPMh backend"
#endif
static struct msm_bus_scale_pdata *p470_a6_bus_pdata;
static u32 p470_a6_bus_handle;
static bool p470_a6_bus_legacy;
static atomic_t p470_a6_vote_failed = ATOMIC_INIT(0);

static bool p470_a6_legacy_dt(struct device_node *np)
{
    return of_machine_is_compatible("qcom,lagoon") &&
        of_device_is_compatible(np, "qcom,ipa") &&
        of_find_property(np, "qcom,msm-bus,name", NULL) &&
        !of_find_property(np, "interconnects", NULL);
}

static int p470_a6_vote(unsigned int state)
{
    int rc;

    if (!p470_a6_bus_legacy)
        return 0;
    if (!p470_a6_bus_handle || state >= 5) {
        atomic_set(&p470_a6_vote_failed, 1);
        return -ENODEV;
    }
    rc = msm_bus_scale_client_update_request(p470_a6_bus_handle, state);
    pr_info_ratelimited("P470 IPA BUS vote case=%d rc=%d\n", state, rc);
    if (rc) {
        atomic_set(&p470_a6_vote_failed, 1);
        pr_err_ratelimited("P470 IPA BUS VOTE_FAILED case=%d rc=%d\n",
                           state, rc);
    }
    return rc;
}

static void p470_a6_bus_cleanup(void)
{
    if (p470_a6_bus_handle) {
        int rc = msm_bus_scale_client_update_request(p470_a6_bus_handle, 0);

        pr_info("P470 IPA BUS cleanup MIN case=0 rc=%d\n", rc);
        msm_bus_scale_unregister_client(p470_a6_bus_handle);
        p470_a6_bus_handle = 0;
    }
    if (p470_a6_bus_pdata) {
        msm_bus_cl_clear_pdata(p470_a6_bus_pdata);
        p470_a6_bus_pdata = NULL;
    }
    p470_a6_bus_legacy = false;
}

static int p470_a6_bus_register(struct platform_device *pdev)
{
    static const int mas[5] = {0x5a, 0x81, 0x5a, 0x01, 0x8f};
    static const int slv[5] = {0x302, 0x200, 0x249, 0x2a4, 0x309};
    struct msm_bus_scale_pdata *pdata;
    unsigned int state, path;
    int rc;

    pdata = msm_bus_cl_get_pdata(pdev);
    if (!pdata) {
        dev_err(&pdev->dev, "P470 IPA BUS pdata=NULL rc=-EPROBE_DEFER\n");
        return -EPROBE_DEFER;
    }
    p470_a6_bus_pdata = pdata;
    if (pdata->num_usecases != 5 || !pdata->usecase) {
        rc = -EINVAL;
        goto bad_pdata;
    }
    for (state = 0; state < 5; ++state) {
        struct msm_bus_paths *case_data = &pdata->usecase[state];

        if (case_data->num_paths != 5 || !case_data->vectors) {
            rc = -EINVAL;
            goto bad_pdata;
        }
        for (path = 0; path < 5; ++path) {
            struct msm_bus_vectors *v = &case_data->vectors[path];

            if (v->src != mas[path] || v->dst != slv[path] ||
                (state == 0 && (v->ab || v->ib))) {
                dev_err(&pdev->dev,
                        "P470 IPA BUS INVALID case=%u path=%u src=%d dst=%d ab=%llu ib=%llu\n",
                        state, path, v->src, v->dst,
                        (unsigned long long)v->ab,
                        (unsigned long long)v->ib);
                rc = -EINVAL;
                goto bad_pdata;
            }
        }
    }
    p470_a6_bus_handle = msm_bus_scale_register_client(pdata);
    if (!p470_a6_bus_handle) {
        dev_err(&pdev->dev, "P470 IPA BUS register FAILED client=0\n");
        rc = -EPROBE_DEFER;
        goto bad_pdata;
    }
    p470_a6_bus_legacy = true;
    dev_info(&pdev->dev, "P470 IPA BUS register client=%u cases=5 paths=5\n",
             p470_a6_bus_handle);
    /* Real nonzero RPMh vote before IPA init touches any IPA registers.
     * If the fabric cannot commit the request, abort hardware init.
     */
    rc = p470_a6_vote(1);
    if (rc) {
        dev_err(&pdev->dev, "P470 IPA BUS initial SVS2 vote failed rc=%d\n", rc);
        goto bad_pdata;
    }
    return 0;

bad_pdata:
    p470_a6_bus_cleanup();
    return rc;
}
'''


def once(s, old, new, label):
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"P470-A6 {label} pinned anchor count={n}")
    return s.replace(old, new, 1)


def wrap_vote_loop(s, fn_begin, fn_end, indent, vote_expression):
    start = s.index(fn_begin)
    end = s.index(fn_end, start)
    part = s[start:end]
    pattern = (re.escape(indent) +
               r'for \(i = 0; i < ipa3_ctx->icc_num_paths; i\+\+\) \{\n' +
               r'(?:(?!\n' + re.escape(indent) + r'\}).)*\n' +
               re.escape(indent) + r'\}')
    matches = list(re.finditer(pattern, part, re.S))
    if len(matches) != 1:
        raise RuntimeError(f"P470-A6 ICC loop in {fn_begin}: found {len(matches)}")
    old = matches[0].group()
    # Keep the original ICC implementation for all non-Lagoon platforms.
    new = (indent + "if (p470_a6_bus_legacy) {\n" +
           indent + "\t" + vote_expression + ";\n" +
           indent + "} else {\n" +
           "\n".join(indent + "\t" + line if line else line
                     for line in old.split("\n")) +
           "\n" + indent + "}")
    part = part.replace(old, new, 1)
    return s[:start] + part + s[end:]


def patch(s):
    if TAG in s:
        raise RuntimeError("P470-A6 already installed")
    if "P470_A5_LEGACY_BUS_NO_SILENT_VOTE_V1" not in s:
        raise RuntimeError("P470-A6 requires A5 early-bus prearm verification")
    s = once(s, "#include <linux/interconnect.h>",
             "#include <linux/interconnect.h>\n#include <linux/msm-bus.h>",
             "real TG bus API include")
    s = once(s, "static int p470_a5_require_bus_backend(struct device *dev)",
             HELPER + "\nstatic int p470_a5_require_bus_backend(struct device *dev)",
             "real bus client implementation")
    # The A5 validation remains in place, but only rejects missing
    # BOTH provider choices. Real TG bus client registration is mandatory.
    old = '''    if (!of_find_property(np, "interconnects", NULL)) {
        dev_err(dev,
                "P470 IPA BUS BLOCKED legacy_vectors=5x5 interconnects=absent real_msm_bus_backend=not_ported rc=-EOPNOTSUPP\\n");
        return -EOPNOTSUPP;
    }'''
    new = '''    if (!of_find_property(np, "interconnects", NULL)) {
        if (!p470_a6_legacy_dt(np)) {
            dev_err(dev, "P470 IPA BUS BLOCKED legacy_vectors=5x5 no_backend\\n");
            return -EOPNOTSUPP;
        }
        dev_info(dev, "P470 IPA BUS backend=TG_RPMH pending_real_registration\\n");
        return 0;
    }'''
    s = once(s, old, new, "A5 preserves no-fake-vote gate")

    # Preserve IPA PM thresholds/exceptions parsing; set zero ICC handles
    # only on the verified legacy path, then parse the shared thresholds.
    old = '''\t/* this interconnects entry must be presented */
\tif (!of_find_property(pdev->dev.of_node,
\t\t\t"interconnects", NULL)) {
\t\tIPAERR("No interconnect info\\n");
\t\treturn -EFAULT;
\t}'''
    new = '''\t/* P470-A6 Lagoon: real TG RPMh MSM bus client, no fake ICC path. */
\tif (p470_a6_legacy_dt(pdev->dev.of_node)) {
\t\tipa_drv_res->icc_num_cases = 5;
\t\tipa_drv_res->icc_num_paths = 0;
\t\tipa_drv_res->pm_init.threshold_size = 3;
\t\tgoto p470_a6_shared_thresholds;
\t}
\tif (!of_find_property(pdev->dev.of_node,
\t\t\t"interconnects", NULL)) {
\t\tIPAERR("No interconnect info\\n");
\t\treturn -EFAULT;
\t}'''
    s = once(s, old, new, "legacy PM DT cases")
    s = once(s, '''\tresult = of_property_read_u32_array(pdev->dev.of_node,
\t\t"qcom,throughput-threshold",''',
    '''p470_a6_shared_thresholds:
\tresult = of_property_read_u32_array(pdev->dev.of_node,
\t\t"qcom,throughput-threshold",''',
    "PM shared threshold label")
    # The actual client must be acquired before the first clock-enable vote.
    anchor = '''\t/* get IPA clocks */
\tresult = ipa3_get_clks(&ipa3_ctx->master_pdev->dev);'''
    replacement = '''\tif (p470_a6_legacy_dt(ipa3_ctx->master_pdev->dev.of_node)) {
\t\tresult = p470_a6_bus_register(ipa3_ctx->master_pdev);
\t\tif (result)
\t\t\tgoto fail_bus_reg;
\t}

''' + anchor
    s = once(s, anchor, replacement, "client register before clocks")

    # All four original ICC set_bw sites stay untouched on non-Lagoon.
    s = wrap_vote_loop(s, "void ipa3_enable_clks(void)", "void _ipa_disable_clks_v3_0(void)",
                       "\t", "p470_a6_vote(idx)")
    s = wrap_vote_loop(s, "void ipa3_disable_clks(void)", "void ipa3_start_tag_process(",
                       "\t", "p470_a6_vote(0)")
    s = wrap_vote_loop(s, "int ipa3_set_clock_plan_from_pm(int idx)", "int ipa3_set_required_perf_profile(",
                       "\t\t", "p470_a6_vote(idx)")
    s = wrap_vote_loop(s, "int ipa3_set_required_perf_profile(", "static void ipa3_process_irq_schedule_rel(",
                       "\t\t", "p470_a6_vote(idx)")
    s = once(s, '''fail_bus_reg:
\tfor (i = 0; i < ipa3_ctx->icc_num_paths; i++)''',
             '''fail_bus_reg:
\tp470_a6_bus_cleanup();
\tfor (i = 0; i < ipa3_ctx->icc_num_paths; i++)''',
             "failure unwind client and pdata")

    # Do not expose IPA READY to the MSS waiter after any failed vote,
    # including a later scaling transition. The ARM bit stays one-shot.
    s = once(s, '''\t\tcomplete_all(&p470_a4_ipa_ready);''',
             '''\t\tif (atomic_read(&p470_a6_vote_failed)) {
\t\t\tpr_err("P470 IPA GSI READY blocked: real bus vote failed\\n");
\t\t\treturn -EIO;
\t\t}
\t\tcomplete_all(&p470_a4_ipa_ready);''',
             "actual readiness excludes failed vote")
    s = once(s, '''    if (!atomic_read(&p470_a4_armed) ||
        !atomic_read(&p470_a4_pas15_loaded)) {''',
             '''    if (atomic_read(&p470_a6_vote_failed)) {
        pr_err("P470 MSS IPA_WAIT reject: IPA bus vote failed\\n");
        return -EIO;
    }
    if (!atomic_read(&p470_a4_armed) ||
        !atomic_read(&p470_a4_pas15_loaded)) {''',
             "MSS blocked on late bus failures")
    return s


def check(root):
    s = (root / IPA).read_text()
    must = (TAG, "#include <linux/msm-bus.h>",
            "CONFIG_QCOM_BUS_SCALING", "CONFIG_QCOM_BUS_CONFIG_RPMH",
            "msm_bus_cl_get_pdata(pdev)",
            "msm_bus_scale_register_client(pdata)",
            "msm_bus_scale_client_update_request(p470_a6_bus_handle, state)",
            "msm_bus_scale_unregister_client(p470_a6_bus_handle)",
            "msm_bus_cl_clear_pdata(p470_a6_bus_pdata)",
            "P470 IPA BUS register client=%u cases=5 paths=5",
            "P470 IPA BUS vote case=%d rc=%d", "P470 IPA BUS VOTE_FAILED",
            "p470_a6_vote(0)", "p470_a6_vote(idx)",
            "p470_a6_shared_thresholds:",
            "P470 IPA BUS backend=TG_RPMH",
            "P470 IPA GSI READY blocked: real bus vote failed",
            "P470 MSS IPA_WAIT reject: IPA bus vote failed")
    for token in must:
        if token not in s:
            raise RuntimeError("P470-A6 missing " + token)
    if s.count("p470_a6_vote(idx);") != 3:
        raise RuntimeError("P470-A6 missing an actual active rate vote")
    if s.count("p470_a6_vote(0);") != 1:
        raise RuntimeError("P470-A6 missing clock-off MIN vote")
    if s.index("p470_a6_bus_register(ipa3_ctx->master_pdev)") >= s.index(
            "result = ipa3_get_clks(&ipa3_ctx->master_pdev->dev)"):
        raise RuntimeError("P470-A6 registration must precede clock setup")
    return {"phase": "P470-A6-LEGACY-RPMH-REAL-BUS-VOTES",
            "status": "SOURCE_REAL_BUS_CLIENT_ENABLED",
            "exact_path_pairs": 5, "usecases": 5, "no_fake_compat_api": True,
            "registration_fail_closed": True, "first_svs2_vote_before_clock": True,
            "clock_off_MIN": True, "runtime_verified": False, "flashable": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.check_only:
        f = args.root / IPA
        f.write_text(patch(f.read_text()))
    data = check(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print("P470-A6 real TG RPMh msm_bus IPA client source PASS; hardware PENDING")


if __name__ == "__main__":
    main()
