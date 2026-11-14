#!/usr/bin/env python3
"""P477 MGBATT_SHADOW stage 1-2. Check-only audit and exact-TG-DT bounds."""
import argparse
import json
import subprocess
from pathlib import Path
DONOR="6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
SRC=Path("drivers/a52_447/a52_sm5714_fg_ro.c")
MK=Path("drivers/a52_447/Makefile")
K=Path("drivers/a52_447/Kconfig")
SHADOW=Path("drivers/a52_447/mgbatt_shadow")
SOURCES=("mgbatt_shadow.c","mgbatt_cable.c","mgbatt_policy.c",
         "mgbatt_dt.c","mgbatt_write_gate.c","mgbatt_shadow.h","Makefile")
TAG="P477_MGBATT_SHADOW_DT_READ_ONLY_V1"
def once(s,a,b,label):
    n=s.count(a)
    if n!=1:raise RuntimeError(f"MGBATT {label} anchor count {n}")
    return s.replace(a,b,1)
def stage(root,tg,repo):
    pinned=subprocess.check_output(["git","-C",str(tg),"rev-parse","HEAD"],
                                  text=True).strip()
    if pinned!=DONOR:raise RuntimeError("MGBATT TG SHA drift: "+pinned)
    src=(tg/"drivers/battery/common/sec_battery_dt.c").read_text()
    if src.count("for (i = 0; i <= len; i++)")!=1:
        raise RuntimeError("MGBATT TG original DTS parser line 185 drift")
    dts=(tg/"arch/arm64/boot/dts/samsung/a52/a52xq/a52xq_eur_open_w00_r02.dts").read_text()
    for p in ("battery,chg_float_voltage = <0x111c>;",
              "battery,swelling_high_temp_block = <0x19a>;",
              "battery,swelling_high_temp_recov = <0x186>;",
              "battery,chg_high_temp = <0x226>;",
              "battery,chg_high_temp_recovery = <0x1e0>;",
              "default_input_current = <0x708>;",
              "default_charging_current = <0x834>;"):
        if dts.count(p)!=1:raise RuntimeError("MGBATT donor r02 policy drift "+p)
    dest=root/SHADOW
    if dest.exists():raise RuntimeError("MGBATT source already staged")
    dest.mkdir(parents=True)
    for p in SOURCES:
        (dest/p).write_text((repo/"vendor/p477/mgbatt_shadow"/p).read_text())
    s=(root/SRC).read_text()
    if TAG in s:raise RuntimeError("MGBATT duplicate source integration")
    s=once(s,"#include <linux/pm_wakeup.h>",
           "#include <linux/pm_wakeup.h>\n#if IS_ENABLED(CONFIG_MGBATT_SHADOW)\n"
           '#include "mgbatt_shadow/mgbatt_shadow.h"\n#endif',
           "owner header")
    # Native S2 and H2 code is already staged. H0's guard worker is still
    # the single observed path; call the read-only logger even when OFF.
    anchor=("    unsigned long now=jiffies;\n"
            "    mutex_lock(&fg->a52h0_lock);\n"
            "    p475_s2_log(fg);\n"
            "    /* Track ten consecutive seconds")
    replacement=("    unsigned long now=jiffies;\n"
                 "    mutex_lock(&fg->a52h0_lock);\n"
                 "    p475_s2_log(fg);\n"
                 "#if IS_ENABLED(CONFIG_MGBATT_SHADOW)\n"
                 "    {\n"
                 "        int dt1;\n"
                 "        const char *type=p475_s2_type(fg,&dt1);\n"
                 "        mgbatt_shadow_tick(fg->dev,type,dt1,\n"
                 "           a52g_ntc_temp(fg),a52h_chg_ntc_temp(fg));\n"
                 "    }\n"
                 "#endif\n"
                 "    /* Track ten consecutive seconds")
    s=once(s,anchor,replacement,"H0 read-only observability hook")
    s=once(s,"static void a52h0_tick(struct a52d_fg *fg)",
           "/* "+TAG+" */\nstatic void a52h0_tick(struct a52d_fg *fg)",
           "shadow marker unique")
    (root/SRC).write_text(s)
    mk=root/MK
    mk.write_text(once(mk.read_text(),"obj-$(CONFIG_A52_447D_SM5714_RO)",
                       "obj-$(CONFIG_MGBATT_SHADOW) += mgbatt_shadow/\n"
                       "obj-$(CONFIG_A52_447D_SM5714_RO)",
                       "isolated built-in shadow Kbuild"))
    kp=root/K
    k=kp.read_text()
    if "config MGBATT_SHADOW" in k:raise RuntimeError("already configured")
    kp.write_text(k+'''
config MGBATT_SHADOW
    bool "P477 Samsung battery read-only shadow stage 1-2"
    depends on A52_447D_SM5714_RO && P475_S2_CABLE
    default n
    help
      Observes the real H0 and S2 device; parses r02 live battery DT;
      no battery/usb/ac power_supply, no duplicate I2C client, no setter.
''')
    check(root)
def check(root):
    s=(root/SRC).read_text()
    k=(root/K).read_text()
    mk=(root/MK).read_text()
    if s.count(TAG)!=1 or s.count("mgbatt_shadow_tick(fg->dev,type,dt1,")!=1:
        raise RuntimeError("MGBATT owner hook count mismatch")
    if k.count("config MGBATT_SHADOW")!=1:
        raise RuntimeError("MGBATT separate Kconfig gate missing")
    cfg=k.split("config MGBATT_SHADOW",1)[1].split("config ",1)[0]
    if "default n" not in cfg or "depends on A52_447D_SM5714_RO && P475_S2_CABLE" not in cfg:
        raise RuntimeError("MGBATT Kconfig dependencies unsafe")
    if mk.count("obj-$(CONFIG_MGBATT_SHADOW) += mgbatt_shadow/")!=1:
        raise RuntimeError("MGBATT Kbuild owner missing")
    code="\n".join((root/SHADOW/f).read_text() for f in SOURCES)
    for line in ("MGBATT SHADOW PROBE ok=1 shadow=1 owner=H0",
                 "MGBATT SHADOW CABLE src=muic dev1=0x%02x",
                 "MGBATT SHADOW WOULD_SET cable=%s icl_ma=%u",
                 "MGBATT SHADOW WRITE_BASELINE shadow_hw_writes=0",
                 "for(i=0;i<len;i++)", "number>=MGBATT_MAX_CABLES",
                 "return -EPERM;", "battery,chg_float_voltage"):
        if line not in code:raise RuntimeError("MGBATT source gate missing "+line)
    # r02 shadow indexes: SDP=USB(4), DCP=TA(3), CDP=USB_CDP(5).
    cable=(root/SHADOW/"mgbatt_cable.c").read_text()
    shadow=(root/SHADOW/"mgbatt_shadow.c").read_text()
    for needle in ('if(!strcmp(type,"SDP")) return 4;',
                   'if(!strcmp(type,"DCP")) return 3;',
                   'if(!strcmp(type,"CDP")) return 5;'):
        if cable.count(needle)!=1:
            raise RuntimeError("MGBATT SEC_BATTERY cable index drift: "+needle)
    if ("if(index==3 &&" not in shadow or
        "policy.cable[3].icl_ma!=1800" not in shadow or
        "policy.cable[3].fcc_ma!=2100" not in shadow or
        "policy.cable[2].icl_ma" in shadow):
        raise RuntimeError("MGBATT DCP must validate TA index 3")
    for bad in ("i2c_smbus_write_", "i2c_transfer(", "regmap_write(",
                "regmap_update_bits(", "power_supply_register(",
                "devm_power_supply_register(", "i2c_new_client_device(",
                "of_platform_populate(", "platform_device_register(",
                "0x8e,", "0x8f,"):
        if bad in code:
            raise RuntimeError("MGBATT forbidden new setter/device "+bad)
    print("MGBATT SOURCE PASS: stage1/2, real DT, S2 only, denied writes, no psy")
def main():
    a=argparse.ArgumentParser()
    a.add_argument("--root",required=True,type=Path)
    a.add_argument("--tg",type=Path)
    a.add_argument("--repo",type=Path,default=Path("."))
    a.add_argument("--check-only",action="store_true")
    a.add_argument("--report",type=Path)
    x=a.parse_args()
    if not x.check_only:
        if not x.tg:raise RuntimeError("MGBATT requires TG donor")
        stage(x.root,x.tg,x.repo)
    else:check(x.root)
    if x.report:
        x.report.parent.mkdir(parents=True,exist_ok=True)
        x.report.write_text(json.dumps({"stage":"MGBATT_SHADOW_1_2","tg":DONOR,
          "source_pass":True,"writes":0,"android_psy":False,
          "runtime_verified":False},indent=2)+"\n")
if __name__=="__main__":main()
