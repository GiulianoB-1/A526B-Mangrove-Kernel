# P471-D1b addendum: TG Qualcomm rmnet, Samsung formats, netfilter

Pin TG to 6bf351bdf18bdb228db79e66f14a7a9c0178e5d7 and
datarmnet to 1b77da7ced0ac746fca93df5c6c01528164ab6cc.

TG has CONFIG_RMNET, CONFIG_RMNET_SHS, CONFIG_RMNET_PERF,
CONFIG_QCOM_QMI_RMNET and CONFIG_QCOM_QMI_DFC built-in (all =y).
The stale vendor rmnet .ko modprobe failures also occur on TG.
They are NOT a reliable diagnostic and must not be suppressed,
spoofed, or treated as reason to force-load a 5.4 module.

RILD creates rmnet_data0..10 via rtnetlink on rmnet_ipa0. It supplies
0x80000071 and 0xC4000071: Qualcomm coalescing, MAPv5 checksum
and private-format bits. The pinned 5.10 donor accepts the Qualcomm
IFLA_RMNET_FLAGS, IFLA_RMNET_DFC_QOS and IFLA_RMNET_UL_AGG_PARAMS.
Its rmnet_core Kbuild includes qmi_rmnet.o, wda_qmi.o,
dfc_qmi.o and dfc_qmap.o. The source flags exist, but their runtime
mask and data negotiation need a real hardware trace.

The pinned 5.10 donor does NOT supply separate SHS or PERF acceleration
drivers. These are not silently asserted present. Cross-version ports
from TG 4.19 require a separate compatibility and init-order review,
after basic mux, IP addressing and packet transmission succeed.

P471-D1b checks the actual post-olddefconfig .config and diffs every
netfilter-family option with the pinned TG defconfig. It preserves the
full differences and identifies disabled features, built-in-to-module
downgrades and required NAT/conntrack/iptables coverage. This is a
source/config audit, not proof that NAT or mobile data works.
Different Kconfig symbols exist across 4.19 and 5.10.

Safety invariants: A6f/A6g and P469B fallback unchanged; IPA
disarmed by default; no EFS/NV writes, fake modules, SELinux
permissive or modem-configuration shortcuts. Real data packets,
browsing and 10-minute stability are still D2 acceptance criteria.
