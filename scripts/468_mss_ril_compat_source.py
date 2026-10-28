#!/usr/bin/env python3
"""P468: TG subsys_modem char+sysfs ABI on the real P467 5.10 MSS rproc.
Run only after scripts/467_mss_pas_source.py; do not alter P467 control plane.
"""
import argparse, json, re
from pathlib import Path

PAS=Path("drivers/remoteproc/qcom_q6v5_pas.c")
SSR=Path("drivers/soc/qcom/subsystem_restart.c")
FW=Path("drivers/base/firmware_loader/main.c")
TAG="P468 MSS SUBSYS"

def replace_once(s,old,new,why):
    n=s.count(old)
    if n!=1:
        raise RuntimeError("P468 "+why+" anchor count "+str(n))
    return s.replace(old,new,1)

def func_bounds(s,name):
    m=re.search(r"(?m)^static\s+ssize_t\s+"+re.escape(name)+r"\s*\([^;]*?\)\s*\{",s,re.S)
    if not m:raise RuntimeError("P468 cannot locate "+name)
    depth=0
    for k in range(m.end()-1,len(s)):
        if s[k]=="{":depth+=1
        elif s[k]=="}":
            depth-=1
            if not depth:return m.start(),k+1
    raise RuntimeError("P468 unbalanced "+name)

def patch_pas(s):
    if TAG in s:raise RuntimeError("P468 PAS already applied")
    for required in ("P467 MSS PROBE", "a52_mss_rails", "rproc->auto_boot = desc->auto_boot;"):
        if required not in s:raise RuntimeError("P468 requires P467 PAS "+required)
    s=replace_once(s,'#include <linux/remoteproc.h>',
                   '#include <linux/remoteproc.h>\n#include <soc/qcom/subsystem_restart.h>',
                   "PAS include")
    s=replace_once(s,'struct qcom_adsp {\n',
                   'struct qcom_adsp {\n'
                   '\tstruct subsys_desc a52_modem_ssr_desc;\n'
                   '\tstruct subsys_device *a52_modem_ssr;\n',
                   "PAS private context")
    helper=r'''
/* P468 MSS SUBSYS: TG char ABI. Own ONE rproc power reference for
 * the first legacy subsys_get/open; TG's subsystem_put on the last
 * close balances it. rproc_boot itself detects an already-running rproc
 * and increments its power reference WITHOUT another PAS boot.
 */
static int a52_modem_subsys_powerup(const struct subsys_desc *desc)
{
    struct qcom_adsp *adsp = container_of(desc, struct qcom_adsp,
                                         a52_modem_ssr_desc);
    int ret;

    if (READ_ONCE(adsp->rproc->state) == RPROC_CRASHED)
        return -EPIPE;
    ret = rproc_boot(adsp->rproc);
    if (ret) {
        dev_err(adsp->dev, "P468 MSS SUBSYS OPEN boot_rc=%d\n", ret);
        return ret;
    }
    /* Never report a successful powerup while the PAS is not running. */
    if (READ_ONCE(adsp->rproc->state) != RPROC_RUNNING) {
        dev_err(adsp->dev, "P468 MSS SUBSYS OPEN state_not_running=%d\n",
                READ_ONCE(adsp->rproc->state));
        rproc_shutdown(adsp->rproc); /* undo this open's power ref */
        return -EIO;
    }
    dev_info(adsp->dev, "P468 MSS SUBSYS OPEN boot_rc=0 rproc=RUNNING\n");
    return 0;
}

static int a52_modem_subsys_shutdown(const struct subsys_desc *desc,
                                    bool force_stop)
{
    struct qcom_adsp *adsp = container_of(desc, struct qcom_adsp,
                                         a52_modem_ssr_desc);

    /* The SSR core invokes shutdown only on the last subsys put.
     * If manual sysfs still owns a power ref, the MSS remains running.
     */
    rproc_shutdown(adsp->rproc);
    dev_info(adsp->dev, "P468 MSS SUBSYS RELEASE rproc_state=%d force=%d\n",
             READ_ONCE(adsp->rproc->state), force_stop);
    return 0;
}

'''
    s=replace_once(s,"static int adsp_probe(struct platform_device *pdev)\n{",
                   helper+"static int adsp_probe(struct platform_device *pdev)\n{",
                   "callbacks")
    original='''\tret = rproc_add(rproc);
\tif (ret)
\t\tgoto detach_proxy_pds;

\treturn 0;'''
    updated='''\tret = rproc_add(rproc);
\tif (ret)
\t\tgoto detach_proxy_pds;

    if (desc->a52_mss_rails) {
        struct subsys_desc *ssr = &adsp->a52_modem_ssr_desc;

        ssr->name = "modem";
        ssr->dev = adsp->dev;
        ssr->owner = THIS_MODULE;
        ssr->powerup = a52_modem_subsys_powerup;
        ssr->shutdown = a52_modem_subsys_shutdown;
        /* Do not set is_not_loadable: real rproc_boot must succeed. */
        adsp->a52_modem_ssr = subsys_register(ssr);
        if (IS_ERR_OR_NULL(adsp->a52_modem_ssr)) {
            int err = IS_ERR(adsp->a52_modem_ssr) ?
                      PTR_ERR(adsp->a52_modem_ssr) : -ENODEV;
            adsp->a52_modem_ssr = NULL;
            /* Preserve the proven P467 PAS even if optional RIL ABI fails. */
            dev_err(adsp->dev,
              "P468 MSS SUBSYS REGISTER failed=%d P467_PAS_PRESERVED\\n", err);
        } else {
            dev_info(adsp->dev,
              "P468 MSS SUBSYS REGISTER name=modem dev=subsys_modem rproc=%s rc=0\\n",
              rproc->name);
        }
    }
\treturn 0;'''
    # The desired C strings need literal \n escapes, not backslash-backslash-n.
    updated=updated.replace('P467_PAS_PRESERVED\\\\n','P467_PAS_PRESERVED\\n').replace('rc=0\\\\n','rc=0\\n')
    s=replace_once(s,original,updated,"rproc registration")
    s=replace_once(s,
                   '\trproc_del(adsp->rproc);\n\n\tqcom_remove_glink_subdev',
                   '''    if (adsp->a52_modem_ssr)
        subsys_unregister(adsp->a52_modem_ssr);
\trproc_del(adsp->rproc);

\tqcom_remove_glink_subdev''',"remove ownership")
    return s

def patch_ssr(s):
    if "P468 MSS SUBSYS STATE" in s:raise RuntimeError("P468 SSR already applied")
    s=replace_once(s,'#include <linux/cdev.h>',
                   '#include <linux/cdev.h>\n#include <linux/remoteproc.h>',
                   "SSR include")
    a,b=func_bounds(s,"state_show")
    part=s[a:b]
    marker=re.search(r'\)\s*\{',part)
    if not marker:raise RuntimeError("P468 state_show signature")
    check=r'''
    /* P468 MSS SUBSYS STATE: TG bus/sysfs ABI, but the *real* PAS rproc
     * is the sole authority. No legacy track.state ONLINE fabrication.
     * The P468 boot DTB ensures the MSS PAS parent has a phandle.
     */
    if (!strcmp(to_subsys(dev)->desc->name, "modem")) {
        struct device *parent = to_subsys(dev)->desc->dev;
        struct rproc *r;
        bool online = false;

        if (parent && parent->of_node && parent->of_node->phandle) {
            r = rproc_get_by_phandle(parent->of_node->phandle);
            if (r) {
                online = READ_ONCE(r->state) == RPROC_RUNNING;
                rproc_put(r);
            }
        }
        return scnprintf(buf, PAGE_SIZE, "%s\n",
                         online ? "ONLINE" : "OFFLINE");
    }
'''
    part=part[:marker.end()]+check+part[marker.end():]
    return s[:a]+part+s[b:]

def patch_fw(s):
    if 'P468 MSS FIRMWARE PATH' in s:raise RuntimeError("P468 firmware already applied")
    if 'static const char * const fw_path[]' not in s:
        raise RuntimeError("P468 firmware search array absent")
    return replace_once(s,'\tfw_path_para,\n',
                        '\tfw_path_para,\n'
                        '\t/* P468 MSS FIRMWARE PATH: retain all existing search dirs. */\n'
                        '\t"/vendor/firmware-modem/image",\n',
                        "firmware path insertion")

def check(root):
    pas=(root/PAS).read_text()
    ssr=(root/SSR).read_text()
    fw=(root/FW).read_text()
    for k in (TAG,"a52_modem_subsys_powerup","a52_modem_subsys_shutdown",
              'ssr->name = "modem";','subsys_register(ssr)',
              'subsys_unregister(adsp->a52_modem_ssr);',
              "P467 MSS PAS_AUTH rc=0"):
        if k not in pas:raise RuntimeError("P468 PAS missing "+k)
    for k in ("P468 MSS SUBSYS STATE", "rproc_get_by_phandle",
              "RPROC_RUNNING", 'online ? "ONLINE" : "OFFLINE"'):
        if k not in ssr:raise RuntimeError("P468 state mirror missing "+k)
    for k in ("P468 MSS FIRMWARE PATH", '"/vendor/firmware-modem/image"'):
        if k not in fw:raise RuntimeError("P468 firmware path missing "+k)
    return {"device":"subsys_modem","sysfs_bus":"msm_subsys",
            "open":"legacy subsystem_get then refcounted rproc_boot",
            "last_close":"subsystem_put then rproc_shutdown",
            "state":"RPROC_RUNNING only, otherwise OFFLINE",
            "no_fake_online":True,"firmware_path":"/vendor/firmware-modem/image",
            "p467_pas_auto_boot":False,"other_patches":"unchanged"}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True,type=Path)
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    if not args.check_only:
        for path,fn in [(PAS,patch_pas),(SSR,patch_ssr),(FW,patch_fw)]:
            p=args.root/path
            text=p.read_text()
            patched=fn(text)
            if patched==text:raise RuntimeError("P468 no-op "+str(path))
            p.write_text(patched)
    data=check(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(data,indent=2)+"\n")
    print("P468 MSS RIL COMPAT SOURCE PASS",json.dumps(data))
if __name__=="__main__":main()
