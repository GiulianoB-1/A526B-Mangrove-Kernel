#!/usr/bin/env python3
"""P471-D1: exact pinned Qualcomm datarmnet core/ctl, IPA pipe/ioctl trace.

Source stage only, applied AFTER P470-A6f/A6g on disposable GKI source.
Never arms IPA or touches P469B. Never pretends user-space modules loaded.
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

DONOR_SHA = "1b77da7ced0ac746fca93df5c6c01528164ab6cc"
CORE = Path("drivers/net/ethernet/qualcomm/rmnet_p471")
ETH_K = Path("drivers/net/ethernet/qualcomm/Kconfig")
ETH_M = Path("drivers/net/ethernet/qualcomm/Makefile")
RMNET = Path("drivers/platform/msm/ipa/ipa_v3/rmnet_ipa.c")
WAN = Path("drivers/platform/msm/ipa/ipa_v3/rmnet_ipa_fd_ioctl.c")
P471 = "P471_D1_QCOM_DATARMNET_CORE_CTL_NO_ARM_V1"

def once(s, old, new, name):
    n = s.count(old)
    if n != 1:
        raise RuntimeError("P471 %s anchor count=%d" % (name, n))
    return s.replace(old, new, 1)

def gitsha(p):
    return subprocess.check_output(
        ["git", "-C", str(p), "rev-parse", "HEAD"], text=True).strip()

def files_from_donor(donor, target):
    if target.exists():
        raise RuntimeError("P471 core already staged")
    if gitsha(donor) != DONOR_SHA:
        raise RuntimeError("P471 donor SHA mismatch")
    src = donor / "core"
    mk = (src / "Kbuild").read_text()
    for v in ("obj-m += rmnet_core.o", "obj-m += rmnet_ctl.o",
              "rmnet_core-y :=", "rmnet_ctl-y :=",
              "rmnet_ctl_ipa.o", "wda_qmi.o", "dfc_qmap.o"):
        if v not in mk:
            raise RuntimeError("P471 donor Kbuild drift: " + v)
    shutil.copytree(src, target)
    # This is not an external module: both objects must link into vmlinux.
    mk = mk.replace("obj-m += rmnet_core.o",
                    "obj-$(CONFIG_P471_RMNET_CORE) += rmnet_core.o")
    mk = mk.replace("obj-m += rmnet_ctl.o",
                    "obj-$(CONFIG_P471_RMNET_CTL) += rmnet_ctl.o")
    (target / "Makefile").write_text(mk)
    (target / "Kconfig").write_text(
        'config P471_RMNET_CORE\n'
        '\tbool "P471 Qualcomm 5.10 MAP vendor netlink core"\n'
        '\tdepends on NET && INET\n'
        '\tselect GRO_CELLS\n'
        '\thelp\n'
        '\t  Pinned datarmnet core, built into the opt-in P471 candidate.\n\n'
        'config P471_RMNET_CTL\n'
        '\tbool "P471 Qualcomm rmnet ctl IPA transport"\n'
        '\tdepends on P471_RMNET_CORE && IPA3\n'
        '\thelp\n'
        '\t  Build the pinned rmnet ctl IPA transport, no fake modules.\n')
    for f in ("rmnet_config.c", "rmnet_ctl_ipa.c", "rmnet_ctl_client.c"):
        if not (target / f).is_file():
            raise RuntimeError("P471 donor file absent: " + f)

LINK_WRAPPER = r"""
/* P471_D1_QCOM_DATARMNET_CORE_CTL_NO_ARM_V1: netmgr RTM_NEWLINK proof.
 * Preserve original rc and report the real physical parent and wire mux.
 */
static int rmnet_newlink(struct net *src_net, struct net_device *dev,
                        struct nlattr *tb[], struct nlattr *data[],
                        struct netlink_ext_ack *extack)
{
    const struct net_device *real_dev = NULL;
    const struct ifla_rmnet_flags *fmt = NULL;
    u16 mux = 0xffff;
    u32 flags = 0;
    int rc;

    if (tb && tb[IFLA_LINK])
        real_dev = __dev_get_by_index(src_net, nla_get_u32(tb[IFLA_LINK]));
    if (data && data[IFLA_RMNET_MUX_ID])
        mux = nla_get_u16(data[IFLA_RMNET_MUX_ID]);
    if (data && data[IFLA_RMNET_FLAGS]) {
        fmt = nla_data(data[IFLA_RMNET_FLAGS]);
        flags = fmt->flags & fmt->mask;
    }
    rc = p471_rmnet_newlink_impl(src_net, dev, tb, data, extack);
    pr_info("P471 RMNET LINK add name=%s parent=%s mux=%u flags=0x%x rc=%d\n",
            dev ? dev->name : "NULL",
            real_dev ? real_dev->name : "NULL", mux, flags, rc);
    return rc;
}

"""

NETDEV_WRAPPER = r"""
/* P471: report real ioctl outcome; no altered QMAP or QMI behavior. */
static const char *p471_rmnet_ioctl_name(int cmd)
{
    switch (cmd) {
    case RMNET_IOCTL_EXTENDED: return "RMNET_IOCTL_EXTENDED";
    case RMNET_IOCTL_OPEN: return "RMNET_IOCTL_OPEN";
    case RMNET_IOCTL_CLOSE: return "RMNET_IOCTL_CLOSE";
    default: return "RMNET_IOCTL_OTHER";
    }
}

static int p471_wwan_ioctl_trace(struct net_device *dev,
                                struct ifreq *ifr, int cmd)
{
    int rc = ipa3_wwan_ioctl(dev, ifr, cmd);

    pr_info("P471 WWAN_IOCTL cmd=%s rc=%d raw=0x%x dev=%s\n",
            p471_rmnet_ioctl_name(cmd), rc, cmd, dev->name);
    return rc;
}

"""

WAN_WRAPPER = r"""
/* P471: log ioctl from the existing /dev/wwan_ioctl ABI. */
static const char *p471_wan_cmd_name(unsigned int cmd)
{
    switch (cmd) {
    case WAN_IOC_ADD_FLT_RULE: return "WAN_IOC_ADD_FLT_RULE";
    case WAN_IOC_ADD_FLT_RULE_EX: return "WAN_IOC_ADD_FLT_RULE_EX";
    case WAN_IOC_ADD_FLT_RULE_INDEX: return "WAN_IOC_ADD_FLT_RULE_INDEX";
    case WAN_IOC_NOTIFY_WAN_STATE: return "WAN_IOC_NOTIFY_WAN_STATE";
    default: return "WAN_IOC_OTHER";
    }
}

static long ipa3_wan_ioctl(struct file *filp,
                          unsigned int cmd, unsigned long arg)
{
    long rc = p471_wan_ioctl_impl(filp, cmd, arg);

    pr_info("P471 WWAN_IOCTL cmd=%s rc=%ld raw=0x%x\n",
            p471_wan_cmd_name(cmd), rc, cmd);
    return rc;
}

"""

PIPE_HELPER = r"""
/* P471: real hardware endpoint and pinned GSI channel; never synthetic. */
static void p471_ipa_pipe_trace(enum ipa_client_type client, int rc)
{
    const struct ipa_gsi_ep_config *cfg = ipa3_get_gsi_ep_info(client);
    const char *name;
    int ep = ipa_get_ep_mapping(client);

    if (client == IPA_CLIENT_APPS_WAN_PROD)
        name = "APPS_WAN_PROD";
    else if (client == IPA_CLIENT_APPS_WAN_COAL_CONS)
        name = "APPS_WAN_COAL_CONS";
    else
        name = "APPS_WAN_CONS";
    pr_info("P471 IPA PIPE setup client=%s ep=%d gsi_ch=%d rc=%d\n",
            name, ep, cfg ? cfg->ipa_gsi_chan_num : -1, rc);
}

"""

def patch_core(target):
    file = target / "rmnet_config.c"
    s = file.read_text()
    s = once(s, "static int rmnet_newlink(", "static int p471_rmnet_newlink_impl(",
             "core newlink name")
    s = once(s, "static void rmnet_dellink(", LINK_WRAPPER + "static void rmnet_dellink(",
             "core newlink wrapper")
    # Qualcomm extension attrs stay at precisely the donor numbers.
    for token in ("IFLA_RMNET_DFC_QOS", "IFLA_RMNET_UL_AGG_PARAMS",
                  ".kind", "rmnet_link_ops"):
        if token not in s:
            raise RuntimeError("P471 lost donor netlink ABI: " + token)
    file.write_text(s)

def patch_ipa(root):
    p = root / RMNET
    s = p.read_text()
    for prerequisite in ("P470 RMNET NETDEV", "P470 RMNET WAN_IOCTL"):
        if prerequisite not in s:
            raise RuntimeError("P471 missing A6e baseline: " + prerequisite)
    if P471 in s:
        raise RuntimeError("P471 duplicate IPA instrumentation")
    s = once(s, '#include "ipa_qmi_service.h"',
             '#include "ipa_qmi_service.h"\n#include "ipa_i.h"', "ipa_i internal GSI config")
    s = once(s, "static int handle3_ingress_format(",
             PIPE_HELPER + "static int handle3_ingress_format(", "IPA GSI helper")
    s = once(s,
             'ret = ipa_setup_sys_pipe(&rmnet_ipa3_ctx->ipa_to_apps_ep_cfg,\n'
             '\t\t&rmnet_ipa3_ctx->ipa3_to_apps_hdl);',
             'ret = ipa_setup_sys_pipe(&rmnet_ipa3_ctx->ipa_to_apps_ep_cfg,\n'
             '\t\t&rmnet_ipa3_ctx->ipa3_to_apps_hdl);\n'
             '\tp471_ipa_pipe_trace(ipa_wan_ep_cfg->client, ret);',
             "ingress GSI result")
    s = once(s,
             'rc = ipa_setup_sys_pipe(\n'
             '\t\tipa_wan_ep_cfg, &rmnet_ipa3_ctx->apps_to_ipa3_hdl);',
             'rc = ipa_setup_sys_pipe(\n'
             '\t\tipa_wan_ep_cfg, &rmnet_ipa3_ctx->apps_to_ipa3_hdl);\n'
             '\tp471_ipa_pipe_trace(ipa_wan_ep_cfg->client, rc);',
             "egress GSI result")
    # Extended IOCTL subtype must be logged with the actual return code.
    # Initialize the subtype so a failed usercopy never logs stack garbage.
    s = once(s,
             "struct rmnet_ioctl_extended_s ext_ioctl_data;",
             "struct rmnet_ioctl_extended_s ext_ioctl_data = { 0 };",
             "extended ioctl zero-init")
    s = once(s,
             "\treturn rc;\n}\n\nstatic const struct net_device_ops ipa3_wwan_ops_ip = {",
             '\tif (cmd == RMNET_IOCTL_EXTENDED)\n'
             '\t\tpr_info("P471 WWAN_IOCTL cmd=EXTENDED/%u rc=%d\\n",\n'
             '\t\t\text_ioctl_data.extended_ioctl, rc);\n'
             '\treturn rc;\n}\n\n'
             + NETDEV_WRAPPER + "static const struct net_device_ops ipa3_wwan_ops_ip = {",
             "extended ioctl subtype with rc")
    s = once(s, "\t.ndo_do_ioctl = ipa3_wwan_ioctl,",
             "\t.ndo_do_ioctl = p471_wwan_ioctl_trace,", "netdev ioctl trace hook")
    s = once(s, "\tdev->stats.tx_packets++;\n\tdev->stats.tx_bytes += skb->len;",
             '\tdev->stats.tx_packets++;\n'
             '\tdev->stats.tx_bytes += skb->len;\n'
             '\tif (dev->stats.tx_packets == 1)\n'
             '\t\tpr_info("P471 RMNET PACKET first_tx dev=%s tx_packets=%lu tx_bytes=%lu\\n",\n'
             '\t\t\tdev->name, dev->stats.tx_packets, dev->stats.tx_bytes);',
             "first TX")
    s = once(s, "\t\tdev->stats.rx_packets++;\n\t\tdev->stats.rx_bytes += packet_len;",
             '\t\tdev->stats.rx_packets++;\n'
             '\t\tdev->stats.rx_bytes += packet_len;\n'
             '\t\tif (dev->stats.rx_packets == 1)\n'
             '\t\t\tpr_info("P471 RMNET PACKET first_rx dev=%s rx_packets=%lu rx_bytes=%lu\\n",\n'
             '\t\t\t\tdev->name, dev->stats.rx_packets, dev->stats.rx_bytes);',
             "first RX")
    p.write_text(s)

    p = root / WAN
    s = p.read_text()
    s = once(s, "static long ipa3_wan_ioctl(struct file *filp,",
             "static long p471_wan_ioctl_impl(struct file *filp,", "wan fd impl")
    s = once(s, "#ifdef CONFIG_COMPAT\nlong ipa3_compat_wan_ioctl(",
             WAN_WRAPPER + "#ifdef CONFIG_COMPAT\nlong ipa3_compat_wan_ioctl(",
             "wan fd wrapper")
    p.write_text(s)

def integrate(root):
    p = root / ETH_K
    k = p.read_text()
    # Do not take another link type ownership if upstream rmnet is enabled.
    k = once(k, 'source "drivers/net/ethernet/qualcomm/rmnet/Kconfig"',
             'source "drivers/net/ethernet/qualcomm/rmnet/Kconfig"\n'
             'source "drivers/net/ethernet/qualcomm/rmnet_p471/Kconfig"',
             "Qualcomm Kconfig")
    p.write_text(k)
    p = root / ETH_M
    mk = p.read_text()
    if 'rmnet_p471/' in mk:
        raise RuntimeError("P471 duplicate Qualcomm Makefile link")
    mk += '\n# P471 vendor MAP provider (separate from upstream CONFIG_RMNET).\n'
    mk += 'obj-$(CONFIG_P471_RMNET_CORE) += rmnet_p471/\n'
    p.write_text(mk)

def check(root):
    core = root / CORE
    cfg = (root / ETH_K).read_text()
    mk = (root / ETH_M).read_text()
    ip = (root / RMNET).read_text()
    fd = (root / WAN).read_text()
    c = (core / "rmnet_config.c").read_text()
    for need in ("P471 RMNET LINK add name=", "parent=%s mux=%u flags=0x%x rc=%d",
                 "IFLA_RMNET_DFC_QOS", "IFLA_RMNET_UL_AGG_PARAMS",
                 "p471_rmnet_newlink_impl"):
        if need not in c:
            raise RuntimeError("P471 netlink check failed: " + need)
    for need in ("P471 IPA PIPE setup client=", "P471 WWAN_IOCTL cmd=",
                 "P471 RMNET PACKET first_tx", "P471 RMNET PACKET first_rx",
                 "p471_wwan_ioctl_trace", "P470 RMNET NETDEV"):
        if need not in ip:
            raise RuntimeError("P471 IPA trace missing: " + need)
    for need in ("P471 WWAN_IOCTL cmd=", "p471_wan_ioctl_impl",
                 "WAN_IOC_ADD_FLT_RULE"):
        if need not in fd:
            raise RuntimeError("P471 WWAN trace missing: " + need)
    if 'source "drivers/net/ethernet/qualcomm/rmnet_p471/Kconfig"' not in cfg:
        raise RuntimeError("P471 Kconfig not reachable")
    if 'obj-$(CONFIG_P471_RMNET_CORE) += rmnet_p471/' not in mk:
        raise RuntimeError("P471 core not linked")
    if "obj-$(CONFIG_P471_RMNET_CTL) += rmnet_ctl.o" not in (core / "Makefile").read_text():
        raise RuntimeError("P471 ctl link missing")
    return {
        "phase": "P471-D1-DATARMNET",
        "donor_sha": DONOR_SHA, "donor_provider": "Qualcomm datarmnet core+ctl",
        "vendor_rtnetlink": ["MUX_ID", "FLAGS", "DFC_QOS", "UL_AGG_PARAMS"],
        "real_rtnetlink_rc": True, "wan_ioctl_rc": True,
        "actual_gsi_channel_in_trace": True,
        "first_rx_tx_counters": True,
        "perf_shs_offload": "not built", "selinux": "unchanged",
        "p470_a6f_a6g": "untouched", "p469b_fallback": "unchanged",
        "ipa_default_armed": False, "modprobe_alias_fake": False,
        "hardware_mobile_data_verified": False,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--donor", type=Path)
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--report", type=Path)
    a = ap.parse_args()
    if a.check_only:
        result = check(a.root)
    else:
        if a.donor is None:
            ap.error("--donor required when staging")
        files_from_donor(a.donor, a.root / CORE)
        integrate(a.root)
        patch_core(a.root / CORE)
        patch_ipa(a.root)
        result = check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("P471-D1 pinned datarmnet core+ctl, netlink/WWAN/pipe/packet source PASS; "
          "NO ARM, mobile data hardware PENDING")
if __name__ == "__main__":
    main()
