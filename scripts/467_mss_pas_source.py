#!/usr/bin/env python3
"""P467 MSS first boot based on P466. 5.10 PAS: one SM6350 MSS
descriptor, manual-only, TG CX/MSS 384 level rails, AOSS load_state modem;
fix existing PAS parent wakeup registration for ADSP and MSS.

Changes ONLY qcom_q6v5_pas.c after P451, and drivers/uio integration. The
separate boot FDT and UIO driver have their own exact gates.
"""
import argparse
import json
import re
from pathlib import Path

PAS=Path("drivers/remoteproc/qcom_q6v5_pas.c")
TAG="P467 MSS PROBE"

def once(s,a,b,why):
    n=s.count(a)
    if n!=1:raise RuntimeError("P467 MSS "+why+" anchor count "+str(n))
    return s.replace(a,b,1)

def func(s,name):
    m=re.search(r"(?m)^static\s+(?:int|void)\s+"+re.escape(name)+r"\s*\([^;{}]*\)\s*\{",s,re.S)
    if not m:raise RuntimeError("P467 MSS missing function "+name)
    depth=0
    for i in range(m.end()-1,len(s)):
        if s[i]=="{":depth+=1
        elif s[i]=="}":
            depth-=1
            if not depth:return m.start(),i+1
    raise RuntimeError("P467 MSS unbalanced "+name)

def in_func(s,name,old,new,why):
    a,b=func(s,name)
    return s[:a]+once(s[a:b],old,new,why)+s[b:]

def patch(s):
    if TAG in s:raise RuntimeError("P467 MSS applied twice")
    for k in ("A52_PHASE451_SM6350_ADSP_PAS_V1","a52_sm6350_adsp_resource",
              ".auto_boot = false","rproc->auto_boot = desc->auto_boot;",
              "device_wakeup_enable(adsp->dev);"):
        if k not in s:raise RuntimeError("P467 MSS requires P451 PAS "+k)
    s=once(s,"\tbool a52_level_rails;\n\n\tchar **active_pd_names;",
             "\tbool a52_level_rails;\n\tbool a52_mss_rails;\n\n\tchar **active_pd_names;",
             "descriptor MSS flag")
    s=once(s,"\tbool a52_level_rails;\n\tconst char *info_name;",
             "\tbool a52_level_rails;\n\tbool a52_mss_rails;\n\tconst char *info_name;",
             "runtime MSS flag")
    s=once(s,"adsp->a52_level_rails = desc->a52_level_rails;",
             "adsp->a52_level_rails = desc->a52_level_rails;\n"
             "\tadsp->a52_mss_rails = desc->a52_mss_rails;",
             "propagate MSS rail selector")
    desc=r'''/* P467 MSS PROBE: manual SM6350 MPSS (TG qcom,mss@4080000).
 * No IPA, modem FastRPC, glinkpkt DATA or ICNSS is enabled.
 * AOSS load_state domain = modem; separate PM6150A S1/S6 level rails.
 */
static const struct adsp_data a52_sm6350_mss_resource = {
    .crash_reason_smem = 421,
    .firmware_name = "modem.mdt",
    .pas_id = 4,
    .has_aggre2_clk = false,
    .auto_boot = false,
    .a52_mss_rails = true,
    .active_pd_names = (char*[]){ "load_state", NULL },
    .ssr_name = "mpss",
    .sysmon_name = "modem",
    .ssctl_id = 0x12,
};

'''
    s=once(s,"static const struct adsp_data sm8250_adsp_resource = {",
           desc+"static const struct adsp_data sm8250_adsp_resource = {",
           "MSS descriptor insertion")
    anchor='\t{ .compatible = "qcom,sm8250-adsp-pas", .data = &sm8250_adsp_resource},'
    s=once(s,anchor,
           '\t{ .compatible = "qcom,sm6350-mss-pas", .data = &a52_sm6350_mss_resource},\n'+anchor,
           "MSS match insertion")
    # The P451 ADSP voltage votes are already balanced on start failure and
    # handover. Reuse THAT EXACT code for MSS but keep ADSP output unchanged.
    old="if (adsp->a52_level_rails) {"
    if s.count(old)!=3:raise RuntimeError("P467 MSS expected 3 balanced P451 rail vote sites")
    s=s.replace(old,"if (adsp->a52_level_rails || adsp->a52_mss_rails) {")
    start=s.index("static int adsp_start(")
    handover=s.index("static void qcom_pas_handover(",start)
    seg=s[start:handover]
    seg=once(seg,
        'dev_info(adsp->dev,"P451 ADSP RAILS lcx=384 lmx=384 rc=0\\n");',
        '''if (adsp->a52_mss_rails)
            dev_info(adsp->dev,"P467 MSS RAILS cx=384 mss=384 rc=0\\n");
        else
            dev_info(adsp->dev,"P451 ADSP RAILS lcx=384 lmx=384 rc=0\\n");''',
        "rail marker split")
    seg=once(seg,
        '''dev_info(adsp->dev,"P451 ADSP PAS_AUTH rc=0 pas_id=%d fw=%s\\n",
             adsp->pas_id,rproc->firmware);''',
        '''if (adsp->a52_mss_rails)
        dev_info(adsp->dev,"P467 MSS PAS_AUTH rc=0 pas_id=%d fw=%s\\n",
                 adsp->pas_id,rproc->firmware);
    else
        dev_info(adsp->dev,"P451 ADSP PAS_AUTH rc=0 pas_id=%d fw=%s\\n",
                 adsp->pas_id,rproc->firmware);''',
        "PAS auth marker split")
    s=s[:start]+seg+s[handover:]
    s=in_func(s,"qcom_pas_handover",
              'dev_info(adsp->dev,"P451 ADSP RAILS released handover\\n");',
              '''if (adsp->a52_mss_rails)
            dev_info(adsp->dev,"P467 MSS RAILS released handover\\n");
        else
            dev_info(adsp->dev,"P451 ADSP RAILS released handover\\n");''',
              "handover rail marker")
    s=in_func(s,"adsp_probe",
              "rproc->auto_boot = desc->auto_boot;",
              '''rproc->auto_boot = desc->auto_boot;
    if (desc->a52_mss_rails)
        dev_info(&pdev->dev,
          "P467 MSS PROBE manual_start=1 auto_boot=0 pas=4 smem=421 sysmon=modem ssctl=0x12 shutdown_ack_bit7=UNHANDLED\\n");''',
              "manual probe log")
    s=in_func(s,"adsp_probe",
              "device_wakeup_enable(adsp->dev);",
              r'''/* P467 MSS + ADSP: the original 5.10 probe called
     * device_wakeup_enable() without device_init_wakeup(). Register the
     * actual rproc parent so rproc_report_crash/pm_stay_awake works.
     */
    ret = device_init_wakeup(adsp->dev, true);
    if (ret) {
        dev_err(adsp->dev,
            "P467 PAS parent wakeup init failed rc=%d\n", ret);
        goto free_rproc;
    }
    dev_info(adsp->dev,
        "P467 PAS PARENT_WAKE enabled=%d pas=%d name=%s\n",
        device_may_wakeup(adsp->dev), adsp->pas_id, dev_name(adsp->dev));''',
              "ADSP+MSS parent wakeup")
    s=in_func(s,"adsp_probe",
              "qcom_add_glink_subdev(rproc, &adsp->glink_subdev, desc->ssr_name);",
              '''if (desc->a52_mss_rails)
        dev_info(adsp->dev,
          "P467 MSS GLINK REGISTER edge=glink-edge remote_pid=1 ipcc_client=2 channels=IPCRTR,glink_ssr\\n");
    qcom_add_glink_subdev(rproc, &adsp->glink_subdev, desc->ssr_name);''',
              "glink subdev log")
    return s

def check(s):
    for k in (TAG,'qcom,sm6350-mss-pas','a52_sm6350_mss_resource',
              '.auto_boot = false', '.firmware_name = "modem.mdt"',
              '.pas_id = 4', '.crash_reason_smem = 421',
              '.sysmon_name = "modem"', '.ssctl_id = 0x12',
              'P467 MSS RAILS cx=384 mss=384',
              'P467 MSS PAS_AUTH rc=0','P467 MSS GLINK REGISTER',
              'P467 PAS PARENT_WAKE enabled=',
              'P451 ADSP RAILS lcx=384', 'P451 ADSP PAS_AUTH'):
        if k not in s:raise RuntimeError("P467 MSS source contract missing "+k)
    if "device_wakeup_enable(adsp->dev);" in s:
        raise RuntimeError("P467 MSS bare parent wakeup still present")
    if s.count("device_init_wakeup(adsp->dev, true)")!=1:
        raise RuntimeError("P467 MSS PAS parent must initialize once at common probe")
    if s.count("if (adsp->a52_level_rails || adsp->a52_mss_rails) {") !=3:
        raise RuntimeError("P467 MSS rails must balance on start/unwind/handover")
    p=s[s.index("static const struct adsp_data a52_sm6350_mss_resource"):s.index("static const struct adsp_data sm8250_adsp_resource")]
    if ".auto_boot = true" in p:
        raise RuntimeError("P467 MSS unexpectedly autobooting")
    return dict(mss_pas=4,fw="modem.mdt",smem=421,sysmon="modem",
                ssctl=18,rails=["pm6150a S1","pm6150a S6"],
                rail_level=384,manual=True,shutdown_ack_bit7="not wired in 5.10 q6v5",
                parent_wakeup="both ADSP and MSS",
                ipa=False,modem_fastrpc=False,glinkpkt=False,icnss=False)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    f=a.root/PAS;s=f.read_text()
    if not a.check_only:s=patch(s);f.write_text(s)
    result=check(s)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(result,indent=2)+"\n")
    print("P467 MSS PAS SOURCE PASS",json.dumps(result))
if __name__=="__main__":main()
