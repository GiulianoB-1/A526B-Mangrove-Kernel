#!/usr/bin/env python3
"""P470-A6e: enable REAL pinned IPA clients manager after ipam.o.

No synthetic IPA ready notification, no modem timeout change, no DT change.
All new messages are observations of actual callsites and return codes.
"""
import argparse
import json
import re
from pathlib import Path

MARKER = "P470_A6E_REAL_CLIENTS_MANAGER_V1"
IPA = Path("drivers/platform/msm/ipa/ipa_v3/ipa.c")
RMNET = Path("drivers/platform/msm/ipa/ipa_v3/rmnet_ipa.c")
QMI = Path("drivers/platform/msm/ipa/ipa_v3/ipa_qmi_service.c")
MHI = Path("drivers/platform/msm/ipa/ipa_clients/ipa_mhi_client.c")
MANAGER = Path("drivers/platform/msm/ipa/ipa_clients/ipa_clients_manager.c")
CM_MAKE = Path("drivers/platform/msm/ipa/ipa_clients/Makefile")
IPA_MAKE = Path("drivers/platform/msm/ipa/Makefile")
KCONFIG = Path("drivers/platform/msm/Kconfig")
COMPOSITE = ("ipa_clients_manager.o ipa_usb.o ipa_wdi3.o ipa_gsb.o "
             "ipa_uc_offload.o ipa_wigig.o ipa_mhi_client.o")

def once(src, before, after, label):
    n = src.count(before)
    if n != 1:
        raise RuntimeError(f"P470-A6e {label} anchor count={n}")
    return src.replace(before, after, 1)

def donor_check(root):
    mk = (root / IPA_MAKE).read_text()
    cm = (root / CM_MAKE).read_text()
    mgr = (root / MANAGER).read_text()
    src = (root / IPA).read_text()
    if "obj-$(CONFIG_IPA3) += ipam.o" not in mk or \
       "obj-y += ipa_v3/ ipa_clients/" not in mk or \
       mk.index("obj-$(CONFIG_IPA3) += ipam.o") > mk.index("obj-y += ipa_v3/ ipa_clients/"):
        raise RuntimeError("P470-A6e: donor IPA make order changed")
    if "obj-$(CONFIG_IPA_CLIENTS_MANAGER) += ipa_clientsm.o" not in cm or \
       "ipa_clientsm-objs := " + COMPOSITE not in cm:
        raise RuntimeError("P470-A6e: donor composite IPA clientsm.o changed")
    for name in ("ipa_clients_manager.o", "ipa_usb.o", "ipa_wdi3.o", "ipa_gsb.o",
                 "ipa_uc_offload.o", "ipa_wigig.o", "ipa_mhi_client.o"):
        if not (root / MANAGER.parent / name.replace(".o", ".c")).is_file():
            raise RuntimeError("P470-A6e: missing required client source " + name)
    for t in ("subsys_initcall(ipa_clients_manager_init);",
              "ipa3_notify_clients_registered();",
              "ipa3_usb_init();", "ipa_wdi3_register();", "ipa_gsb_register();",
              "ipa_uc_offload_register();", "ipa_mhi_register();", "ipa_wigig_register();"):
        if t not in mgr:
            raise RuntimeError("P470-A6e: donor manager missing " + t)
    if "subsys_initcall(ipa_module_init);" not in src or \
       "P470 IPA GSI READY" not in src or \
       "P470 IPA FW_SM event=" not in src:
        raise RuntimeError("P470-A6e: missing A6d IPA baseline")

def patch(root):
    donor_check(root)
    cfg = root / KCONFIG
    if MARKER in cfg.read_text():
        raise RuntimeError("P470-A6e already applied")
    cfg.write_text(cfg.read_text() + """
# P470_A6E_REAL_CLIENTS_MANAGER_V1
config IPA_CLIENTS_MANAGER
    bool "Real dataipa clients manager (P470-A6e)"
    depends on IPA3
    default n
    help
      Build the complete pinned donor ipa_clientsm.o, after ipam.o.
      This does not enable IPA hardware by default.
""")
    f = root / IPA
    s = f.read_text()
    s = once(s, '''\tif (ipa_fmwk_register_ipa(&data)) {
\t\tIPAERR("couldn't register to IPA framework\\n");
\t}''', '''\t{
\t\tint rc = ipa_fmwk_register_ipa(&data);

\t\tpr_info("P470 IPA FMWK register rc=%d clients_registered=%d\\n",
\t\t\trc, ipa3_ctx->clients_registered);
\t\tif (rc)
\t\t\tIPAERR("couldn't register to IPA framework\\n");
\t}''', "framework registration result")
    s = once(s, '''\tipa3_ctx->clients_registered = true;
\tmutex_unlock(&ipa3_ctx->lock);

\tif (reg) {''', '''\tipa3_ctx->clients_registered = true;
\tmutex_unlock(&ipa3_ctx->lock);
\tpr_info("P470 IPA CLIENTS notified initialized=%d\\n", reg);

\tif (reg) {''', "client notification")
    s = once(s, '''\tif (ipa3_ctx->clients_registered)
\t\treg = true;
\tmutex_unlock(&ipa3_ctx->lock);
\tipa3_enable_napi_lan_rx();''', '''\tif (ipa3_ctx->clients_registered)
\t\treg = true;
\tmutex_unlock(&ipa3_ctx->lock);
\tpr_info("P470 IPA FMWK post_init clients_registered=%d register_now=%d\\n",
\t\tipa3_ctx->clients_registered, reg);
\tipa3_enable_napi_lan_rx();''', "post-init framework gate")
    s = once(s, '''\tresult = ipa_hw_stats_init();
\tif (result)
\t\tIPAERR("fail to init stats %d\\n", result);''', '''\tresult = ipa_hw_stats_init();
\tpr_info("P470 IPA STATS hw_init rc=%d\\n", result);
\tif (result)
\t\tIPAERR("fail to init stats %d\\n", result);''', "hardware stats")
    s = once(s, '''\tresult = ipa_drop_stats_init();
\tif (result)
\t\tIPAERR("fail to init stats %d\\n", result);''', '''\tresult = ipa_drop_stats_init();
\tpr_info("P470 IPA STATS drop_init rc=%d\\n", result);
\tif (result)
\t\tIPAERR("fail to init stats %d\\n", result);''', "drop stats")
    f.write_text(s)
    f = root / RMNET
    s = f.read_text()
    s = once(s, '''\tIPAWANDBG("IPA ready callback has been triggered\\n");

\tschedule_work(&ipa3_scheduled_probe);''', '''\tpr_info("P470 IPA READY_CB fired pdev=%s\\n", dev_name(&pdev->dev));
\tIPAWANDBG("IPA ready callback has been triggered\\n");

\tschedule_work(&ipa3_scheduled_probe);''', "RMNET ready callback")
    s = once(s, '''\tif (!ipa3_is_ready()) {
\t\tIPAWANDBG("IPA driver not ready, registering callback\\n");''', '''\tif (!ipa3_is_ready()) {
\t\tpr_info("P470 RMNET PROBE stage=deferred ipa_ready=0\\n");
\t\tIPAWANDBG("IPA driver not ready, registering callback\\n");''', "RMNET deferred probe")
    s = once(s, '''\twan_cons_ep = ipa_get_ep_mapping(IPA_CLIENT_APPS_WAN_CONS);''', '''\tpr_info("P470 RMNET PROBE stage=full ipa_ready=%d\\n",
\t\tipa3_is_ready());
\twan_cons_ep = ipa_get_ep_mapping(IPA_CLIENT_APPS_WAN_CONS);''', "RMNET full probe")
    # All branches must report the async qmi worker scheduling, not success.
    for expr, label in (
        ("QMI_IPA_PLATFORM_TYPE_MSM_ANDROID_V01", "MSM"),
        ("QMI_IPA_PLATFORM_TYPE_LE_MHI_V01", "LE_MHI"),
        ("QMI_IPA_PLATFORM_TYPE_LE_V01", "LE")):
        s = once(s, f'\t\tipa3_qmi_service_init({expr});',
                 f'''\t\t{{
\t\t\tret = ipa3_qmi_service_init({expr});
\t\t\tpr_info("P470 RMNET QMI service_init queued platform={label} rc=%d\\n", ret);
\t\t}}''', "RMNET QMI "+label)
    s = once(s, '''\t\tret = ipa3_wan_ioctl_init();
\t\tif (ret)
\t\t\tgoto wan_ioctl_init_err;''', '''\t\tret = ipa3_wan_ioctl_init();
\t\tpr_info("P470 RMNET WAN_IOCTL rc=%d\\n", ret);
\t\tif (ret)
\t\t\tgoto wan_ioctl_init_err;''', "WAN IOCTL")
    s = once(s, '''\tret = register_netdev(dev);
\tif (ret) {''', '''\tret = register_netdev(dev);
\tpr_info("P470 RMNET NETDEV %s rc=%d\\n", dev->name, ret);
\tif (ret) {''', "RMNET netdev")
    f.write_text(s)
    f = root / QMI
    s = f.read_text()
    s = once(s, '''\trc = qmi_add_server(ipa3_svc_handle,
\t\tIPA_A5_SERVICE_SVC_ID,
\t\tIPA_A5_SVC_VERS,
\t\tIPA_A5_SERVICE_INS_ID);

\tif (rc < 0) {''', '''\trc = qmi_add_server(ipa3_svc_handle,
\t\tIPA_A5_SERVICE_SVC_ID,
\t\tIPA_A5_SVC_VERS,
\t\tIPA_A5_SERVICE_INS_ID);
\tpr_info("P470 RMNET QMI server_register rc=%d\\n", rc);

\tif (rc < 0) {''', "actual async QMI server result")
    f.write_text(s)
    # P470-A6e: the pinned donor expects a struct dentry return from
    # debugfs_create_u32(), but the target 5.10 GKI API returns void.
    # Call the helper directly; never fake success or cast its return type.
    f = root / MHI
    s = f.read_text()
    s = once(s, '''\tfile = debugfs_create_u32("use_ipadma", read_write_mode, dent,
\t\t&ipa_mhi_client_ctx->use_ipadma);
\tif (!file || IS_ERR(file)) {
\t\tIPA_MHI_ERR("fail to create file use_ipadma\\n");
\t\tgoto fail;
\t}''', '''\t/* P470-A6e: GKI 5.10 debugfs_create_u32 returns void. */
\tdebugfs_create_u32("use_ipadma", read_write_mode, dent,
\t\t&ipa_mhi_client_ctx->use_ipadma);''', "MHI debugfs_create_u32 void API")
    f.write_text(s)

def check(root):
    donor_check(root)
    cfg = (root / KCONFIG).read_text()
    ipa = (root / IPA).read_text()
    rmnet = (root / RMNET).read_text()
    qmi = (root / QMI).read_text()
    mhi = (root / MHI).read_text()
    for marker, src in (
        (MARKER,cfg),
        ("config IPA_CLIENTS_MANAGER", cfg),
        ("P470 IPA FMWK register rc=", ipa),
        ("P470 IPA CLIENTS notified initialized=", ipa),
        ("P470 IPA FMWK post_init clients_registered=", ipa),
        ("P470 IPA STATS hw_init rc=", ipa),
        ("P470 IPA STATS drop_init rc=", ipa),
        ("P470 IPA READY_CB fired", rmnet),
        ("P470 RMNET PROBE stage=deferred", rmnet),
        ("P470 RMNET PROBE stage=full", rmnet),
        ("P470 RMNET QMI service_init queued", rmnet),
        ("P470 RMNET WAN_IOCTL rc=", rmnet),
        ("P470 RMNET NETDEV %s rc=", rmnet),
        ("P470 RMNET QMI server_register rc=", qmi),
        ("P470-A6e: GKI 5.10 debugfs_create_u32 returns void.", mhi),
    ):
        if marker not in src:
            raise RuntimeError("P470-A6e missing diagnostic: "+marker)
    if "file = debugfs_create_u32(" in mhi:
        raise RuntimeError("P470-A6e stale MHI debugfs_create_u32 void assignment")
    return {"phase":"P470-A6e-REAL-IPA-CLIENTS-MANAGER",
            "donor_sha":"c560cc3c2840fb0ebc55ceef5b27549c66143637",
            "manager_aggregate":"ipa_clientsm.o",
            "manager_members":COMPOSITE.split(),
            "kbuild_ipa_before_clients":True,
            "initcall_level":"subsys",
            "no_synthetic_ready":True,
            "ipa_default_disarmed":True,
            "p469b_unchanged":True,
            "modem_15s_wait_unchanged":True,
            "runtime_ipa_qmi_registered":False,
            "runtime_5min_stable":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",required=True,type=Path)
    parser.add_argument("--check-only",action="store_true")
    parser.add_argument("--report",type=Path)
    a=parser.parse_args()
    if not a.check_only:
        patch(a.root)
    result=check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print("P470-A6e real IPA clients manager source + framework/ready/RMNET/QMI markers PASS; hardware PENDING")

if __name__=="__main__":
    main()
