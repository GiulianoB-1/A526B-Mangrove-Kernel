#!/usr/bin/env python3
"""P479 H4: opt-in automatic 5V SDP/CDP/DCP charging via H0 sole writer.

Retains H0/P449 thermal guard, H2/H3 manual mode, S2 MUIC, and no flash
writes outside the existing H0 masked-write/readback allowlist. No PD/AFC.
"""
import argparse
import json
import subprocess
from pathlib import Path

TG_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
SRC = Path("drivers/a52_447/a52_sm5714_fg_ro.c")
K = Path("drivers/a52_447/Kconfig")
MARK = "P479_H4_AUTO_5V_SOLE_WRITER_V1"

def one(source, before, after, label):
    count = source.count(before)
    if count != 1:
        raise RuntimeError("P479 H4 %s anchor drift: %d" % (label, count))
    return source.replace(before, after, 1)

def icl_code(ma):
    return 0 if ma < 100 else ((ma - 100) // 25) & 0x7f

def fcc_code(ma):
    ua = ma * 1000
    return 0x07 if ua < 109375 else (0xe0 if ua > 3500000 else
                                     (7 + ((ua - 109375) // 15625)) & 0xff)

H4 = r'''
/* P479_H4_AUTO_5V_SOLE_WRITER_V1
 * S2 MUIC plus real VBUS; no QC/AFC/PD negotiation, no shadow writes.
 * All H4 changes use a52h0_write_masked() with its allowlist/ceilings.
 * Existing H0/P449 41C/50C hard stops remain stronger than TG's 55C cap.
 */
#if IS_ENABLED(CONFIG_P479_H4)
static int p479_h4_icl_code(int ma)
{
    if (ma == 475 || ma == 500 || ma == 1000 ||
        ma == 1500 || ma == 1800)
        return (ma - 100) / 25;
    return -EINVAL;
}
static int p479_h4_fcc_code(int ma)
{
    int ua = ma * 1000;
    if (ma != 500 && ma != 550 && ma != 1000 &&
        ma != 1400 && ma != 1500 && ma != 2100)
        return -EINVAL;
    return 7 + (ua - 109375) / 15625;
}
static int p479_h4_one_write(struct a52d_fg *fg, bool input, int ma)
{
    int code = input ? p479_h4_icl_code(ma) : p479_h4_fcc_code(ma);
    int reg = input ? A52H0_VBUSCNTL : A52H0_CHGCNTL2;
    int mask = input ? 0x7f : 0xff;
    int rc, rb;
    if (code < 0)
        return -EINVAL;
    rc = a52h0_write_masked(fg, reg, mask, (u8)code);
    rb = a52h0_regread(fg, reg);
    if (!rc && rb < 0)
        rc = rb;
    if (!rc && (rb & mask) != code)
        rc = -EIO;
    if (input)
        dev_info_ratelimited(fg->dev,
          "P479 H4 ICL_SET ma=%d code=0x%02x readback=0x%02x rc=%d\n",
          ma, code, rb & 0xff, rc);
    else
        dev_info_ratelimited(fg->dev,
          "P479 H4 FCC_SET ma=%d code=0x%02x readback=0x%02x rc=%d\n",
          ma, code, rb & 0xff, rc);
    return rc;
}
/* Cross-direction transitions are handled safely: first lower FCC,
 * then lower ICL, then raise ICL, then raise FCC.
 */
static int p479_h4_apply(struct a52d_fg *fg, int icl, int fcc)
{
    int old_icl = a52h0_regread(fg,A52H0_VBUSCNTL);
    int old_fcc = a52h0_regread(fg,A52H0_CHGCNTL2);
    int in = p479_h4_icl_code(icl), ch = p479_h4_fcc_code(fcc);
    int rc;
    if (old_icl < 0 || old_fcc < 0 || in < 0 || ch < 0 ||
        old_icl > 0x44 || old_fcc > 0x86)
        return -EUCLEAN;
    old_icl &= 0x7f;
    if (ch < old_fcc) {
        rc = p479_h4_one_write(fg,false,fcc);
        if (rc) return rc;
    }
    if (in != old_icl) {
        rc = p479_h4_one_write(fg,true,icl);
        if (rc) return rc;
    }
    if (ch > old_fcc) {
        rc = p479_h4_one_write(fg,false,fcc);
        if (rc) return rc;
    }
    fg->p479_h4_applied_icl = icl;
    fg->p479_h4_applied_fcc = fcc;
    return 0;
}
/* Must never call a52h0_off from here; H0 owns the shutdown path. */
static int p479_h4_restore(struct a52d_fg *fg, const char *why)
{
    int rc1,rc2,old_fcc,old_icl;
    if (!fg->p479_h4_auto)
        return 0;
    old_fcc = a52h0_regread(fg,A52H0_CHGCNTL2);
    old_icl = a52h0_regread(fg,A52H0_VBUSCNTL);
    if (old_fcc == 0x20 && old_icl == 0x10) {
        fg->p479_h4_applied_fcc = 500;
        fg->p479_h4_applied_icl = 500;
        return 0;
    }
    /* Force FCC first on unplug, regardless of register read errors. */
    rc1 = p479_h4_one_write(fg,false,500);
    rc2 = p479_h4_one_write(fg,true,500);
    if (rc1 || rc2) {
        dev_err_ratelimited(fg->dev,
            "P479 H4 FAULT reason=RESTORE_500_FAILED\n");
        fg->a52h0_killed = true;
        fg->a52h0_armed = false;
        return rc1 ? rc1 : rc2;
    }
    fg->p479_h4_applied_icl = 500;
    fg->p479_h4_applied_fcc = 500;
    dev_info_ratelimited(fg->dev,"P479 H4 LIMIT ma=500 reason=%s\n",why);
    return 0;
}
static void p479_h4_fault(struct a52d_fg *fg, const char *reason)
{
    dev_err_ratelimited(fg->dev,"P479 H4 FAULT reason=%s\n",reason);
    if (p479_h4_restore(fg,"FAULT_RECOVERY")) {
        fg->a52h0_killed = true;
        fg->a52h0_armed = false;
    }
    /* No silent retry to higher current after a write/readback fault. */
    fg->p479_h4_auto = false;
    fg->p479_h4_faulted = true;
}
static void p479_h4_pre_tick(struct a52d_fg *fg)
{
    const char *type, *reason = "CABLE_TABLE";
    int dt1,bt,ct;
    unsigned long now = jiffies;
    if (!fg->p479_h4_auto)
        return;
    type = p475_s2_type(fg,&dt1);
    if (!fg->p479_h4_pending || strcmp(type,fg->p479_h4_pending)) {
        fg->p479_h4_pending = type;
        fg->p479_h4_ready = false;
        fg->p479_h4_seen = now;
        /* A changed/untrusted cable immediately loses any old high vote. */
        if (p479_h4_restore(fg,"CABLE_CHANGE")) {
            p479_h4_fault(fg,"CABLE_CHANGE_RESTORE");
            return;
        }
    }
    if (!fg->p479_h4_ready &&
        time_after_eq(now,fg->p479_h4_seen+HZ)) {
        fg->p479_h4_ready=true;
        fg->p479_h4_type=type;
        fg->p477_h3_actual_ma=500;
        fg->p477_h3_last_step=now;
        p477_h3_reset_stable(fg,a52g_ntc_temp(fg),a52h_chg_ntc_temp(fg));
        dev_info_ratelimited(fg->dev,
           "P479 H4 CABLE type=%s icl=%d fcc_target=%d reason=%s\n",
           type,!strcmp(type,"DCP")?1800:!strcmp(type,"CDP")?1500:
                 !strcmp(type,"SDP")?475:500,
           !strcmp(type,"DCP")?2100:!strcmp(type,"CDP")?1500:
                 !strcmp(type,"SDP")?550:500,reason);
    }
    if (!fg->p479_h4_ready)
        return;
    if (!strcmp(type,"NONE")) {
        /* H0's original worker stops charging on VBUS loss.
         * A fully sampled unplug permits one rearm on a later insert.
         */
        fg->p479_h4_saw_unplug=true;
        fg->a52h0_armed=false;
        return;
    }
    if (fg->p479_h4_saw_unplug) {
        fg->p479_h4_rearm_allowed=true;
        fg->p479_h4_saw_unplug=false;
    }
    /* Never arm from a stale/failed MUIC read without real VBUS. */
    {
        int st=a52h0_regread(fg,A52G_CHG_STATUS1);
        if (st<0 || !(st&BIT(0)))
            return;
    }
    /* The permanent H0 kill and the original P449 thermal latch prevail. */
    if (fg->a52h0_killed || fg->a52h0_active || fg->a52h0_armed ||
        !fg->p479_h4_rearm_allowed || fg->a52h0_verify_io_streak)
        return;
    bt=a52g_ntc_temp(fg);
    ct=a52h_chg_ntc_temp(fg);
    if (!fg->a52h0_ntc_valid ||
        !time_after_eq(now,fg->a52h0_ntc_since+10*HZ) ||
        bt<150 || bt>410 || ct< -200 || ct>=500)
        return;
    if ((fg->a52h0_rearm || fg->a52g_inhibit_latched) &&
        (bt<170 || bt>390 || ct>450))
        return;
    fg->a52g_inhibit_latched=false;
    fg->a52h0_rearm=false;
    fg->a52h0_armed=true;
    fg->p479_h4_rearm_allowed=false;
    a52h0_state(fg,"ARMED","P479_H4_CABLE_REARM");
}
/* Invoked after H0 verification and only inside its 2s guard worker. */
static void p479_h4_tick(struct a52d_fg *fg, int bat, int chg)
{
    int icl=500,fcc=500,actual,target,step,rc;
    const char *type = fg->p479_h4_type;
    const char *why = "CABLE_TABLE";
    unsigned long now=jiffies;
    if (!fg->p479_h4_ready || !type)
        return;
    if (!fg->a52h0_active || !fg->a52h0_armed ||
        fg->a52h0_killed || fg->a52g_inhibit_latched ||
        !fg->a52h0_state || strcmp(fg->a52h0_state,"CHARGING"))
        return;
    if (!strcmp(type,"DCP")) { icl=1800; fcc=2100; }
    else if (!strcmp(type,"CDP")) { icl=1500; fcc=1500; }
    else if (!strcmp(type,"SDP")) { icl=475; fcc=550; }
    /* Unknown, PDIC, AFC, QC remain 500/500, no negotiation. */
    if (bat<150 || bat>900 || chg< -200 || chg>900) {
        icl=500; fcc=500; why="NTC_INVALID";
    } else {
        if(bat>=410) fg->p477_h3_bat_hot=true;
        if(fg->p477_h3_bat_hot && bat<=390)
            fg->p477_h3_bat_hot=false;
        if (fg->p477_h3_bat_hot) {
            icl=500; fcc=500; why="BAT_41C_HOLD_39C_RECOVER";
        } else if (chg>=550) {
            icl=500; fcc=500; why="CHARGER_55C";
        } else if (chg>=480) {
            icl=min(icl,1000); fcc=min(fcc,1400);
            why="CHARGER_48C_CAP";
        }
    }
    actual = fg->p477_h3_actual_ma;
    target = fcc;
    if (!strcmp(type,"DCP") && target>actual) {
        if (abs(bat-fg->p477_h3_bat_anchor)>10 ||
            abs(chg-fg->p477_h3_chg_anchor)>10) {
            p477_h3_reset_stable(fg,bat,chg);
            target=actual; why="TEMPERATURE_MOVING";
        } else if (time_before(now,fg->p477_h3_last_step+P477_H3_STEP_INTERVAL) ||
                   time_before(now,fg->p477_h3_stable_since+P477_H3_STEP_INTERVAL)) {
            target=actual; why="H3_STABLE_DWELL";
        } else {
            if(actual==500) step=1000;
            else if(actual==1000) step=1500;
            else if(actual==1400) step=1500;
            else if(actual==1500) step=2100;
            else { p479_h4_fault(fg,"H3_STEPPER_INVALID"); return; }
            target=min(target,step);
        }
    }
    if (target<500 || target>2100 || icl>1800) {
        p479_h4_fault(fg,"REQUEST_ABOVE_CEILING");
        return;
    }
    rc=p479_h4_apply(fg,icl,target);
    if (rc) {
        p479_h4_fault(fg,"SET_OR_READBACK");
        return;
    }
    if (target!=actual) {
        fg->p477_h3_actual_ma=target;
        fg->p477_h3_last_step=now;
        p477_h3_reset_stable(fg,bat,chg);
    }
    if (strcmp(why,"CABLE_TABLE"))
        dev_info_ratelimited(fg->dev,"P479 H4 LIMIT ma=%d reason=%s\n",
                             min(icl,target),why);
}
static ssize_t a52_h4_auto_show(struct device *dev,
             struct device_attribute *attr,char *buf)
{
    struct a52d_fg *fg=dev_get_drvdata(dev);
    return scnprintf(buf,PAGE_SIZE,"%d\n",fg->p479_h4_auto);
}
static ssize_t a52_h4_auto_store(struct device *dev,
             struct device_attribute *attr,const char *buf,size_t len)
{
    struct a52d_fg *fg=dev_get_drvdata(dev);
    bool enable;
    int rc=0;
    if (!fg || kstrtobool(buf,&enable))
        return -EINVAL;
    mutex_lock(&fg->a52h0_lock);
    if (enable) {
        if (fg->a52h0_killed) {
            rc=-EPERM;
        } else if (!fg->p479_h4_auto) {
            if (fg->p476_h2_fast || fg->p476_h2_enabled)
                rc=p476_h2_off(fg,"H4_TAKES_CONTROL");
            if (!rc) {
                fg->p479_h4_auto=true;
                fg->p479_h4_rearm_allowed=true;
                fg->p479_h4_saw_unplug=false;
                fg->p479_h4_faulted=false;
                fg->p479_h4_pending=NULL;
                fg->p479_h4_type=NULL;
                fg->p479_h4_ready=false;
            }
        }
    } else if (fg->p479_h4_auto) {
        rc=p479_h4_restore(fg,"AUTO_DISARM");
        fg->p479_h4_auto=false;
        if (!fg->a52h0_active)
            fg->a52h0_armed=false;
        if (rc)
            a52h0_off(fg,"P479_H4_RESTORE_FAILED",true);
    }
    mutex_unlock(&fg->a52h0_lock);
    return rc?rc:len;
}
static DEVICE_ATTR(a52_h4_auto,0600,a52_h4_auto_show,a52_h4_auto_store);
static void p479_h4_remove(void *arg)
{
    struct a52d_fg *fg=arg;
    device_remove_file(fg->dev,&dev_attr_a52_h4_auto);
}
static void p479_h4_setup(struct a52d_fg *fg)
{
    int rc;
    fg->p479_h4_auto=false; /* P479 runtime default OFF */
    fg->p479_h4_applied_icl=500;
    fg->p479_h4_applied_fcc=500;
    rc=device_create_file(fg->dev,&dev_attr_a52_h4_auto);
    if (!rc) rc=devm_add_action_or_reset(fg->dev,p479_h4_remove,fg);
    if (rc) dev_err(fg->dev,"P479 H4 FAULT reason=SYSFS_UNAVAILABLE\n");
}
#else
static void p479_h4_pre_tick(struct a52d_fg *fg) {}
static void p479_h4_tick(struct a52d_fg *fg,int bat,int chg) {}
static void p479_h4_setup(struct a52d_fg *fg) {}
#endif
'''

def stage(root, tg):
    donor = subprocess.check_output(
        ["git","-C",str(tg),"rev-parse","HEAD"],text=True).strip()
    if donor != TG_SHA:
        raise RuntimeError("P479 TG donor SHA mismatch: "+donor)
    text = (tg/"drivers/battery/charger/sm5714_charger/sm5714_charger.c").read_text()
    for marker in (
        "offset = ((mA - 100) / 25) & 0x7F;",
        "return ((reg & 0x7F) * 25) + 100;",
        "offset = (7 + ((uA - 109375) / 15625)) & 0xFF;",
    ):
        if marker not in text:
            raise RuntimeError("P479 TG SM5714 setter drift: "+marker)
    for ma, code in ((1800,0x44),(1500,0x38),(500,0x10),(475,0x0f),
                     (1000,0x24)):
        if icl_code(ma) != code:
            raise RuntimeError("P479 ICL formula failed at %d" % ma)
    for ma,code in ((550,0x23),(500,0x20),(1400,0x59),
                    (1500,0x60),(2100,0x86)):
        if fcc_code(ma) != code:
            raise RuntimeError("P479 FCC formula failed at %d" % ma)

    p=root/SRC
    s=p.read_text()
    if MARK in s:
        raise RuntimeError("P479 H4 duplicate staging")
    for dependency in ("P477_H3_SINGLE_WRITER_STEPPED_DCP_ONLY_V1",
                       "P477_MGBATT_SHADOW_DT_READ_ONLY_V1"):
        if dependency not in s:
            raise RuntimeError("P479 H4 dependency absent "+dependency)
    # The sole H0 writer is allowed to access exactly one additional reg.
    s=one(s,
      "    if ((reg!=A52H0_CHGCNTL2 && reg!=A52H0_WDTCNTL &&\n"
      "         reg!=A52G_CHG_CNTL1) ||",
      "    if ((reg!=A52H0_CHGCNTL2 && reg!=A52H0_WDTCNTL &&\n"
      "         reg!=A52G_CHG_CNTL1 && reg!=A52H0_VBUSCNTL) ||\n"
      "        (reg==A52H0_VBUSCNTL && mask!=0x7f) ||",
      "H0 register allowlist")
    s=one(s,
      "    if(reg==A52H0_CHGCNTL2 && val>0x86)return -EPERM;",
      "    if(reg==A52H0_CHGCNTL2 && val>0x86)return -EPERM;\n"
      "#if IS_ENABLED(CONFIG_P479_H4)\n"
      "    if(reg==A52H0_VBUSCNTL &&\n"
      "       (!fg->p479_h4_auto || val>0x44))return -EPERM;\n"
      "#else\n"
      "    if(reg==A52H0_VBUSCNTL)return -EPERM;\n"
      "#endif",
      "hard ceiling inside sole writer")
    s=one(s,
      "    if(old<0)return old;\n"
      "    rc=i2c_smbus_write_byte_data",
      "    if(old<0)return old;\n"
      "    if(reg==A52H0_VBUSCNTL && ((old&~mask)|(val&mask))>0x44)\n"
      "        return -EPERM;\n"
      "    rc=i2c_smbus_write_byte_data",
      "whole-register VBUS ceiling before write")
    s=one(s,
      "    bool p476_h2_enabled, p476_h2_fast;",
      "    bool p476_h2_enabled, p476_h2_fast;\n"
      "#if IS_ENABLED(CONFIG_P479_H4)\n"
      "    bool p479_h4_auto,p479_h4_ready,p479_h4_faulted;
    bool p479_h4_rearm_allowed,p479_h4_saw_unplug;\n"
      "    const char *p479_h4_pending,*p479_h4_type;\n"
      "    unsigned long p479_h4_seen;\n"
      "    int p479_h4_applied_icl,p479_h4_applied_fcc;\n"
      "#endif",
      "H4 per-device state")
    s=one(s,
      "static void a52h0_off(struct a52d_fg *fg,const char *why,bool permanent)",
      "#if IS_ENABLED(CONFIG_P479_H4)\n"
      "static int p479_h4_restore(struct a52d_fg *fg,const char *why);\n"
      "#endif\n"
      "static void a52h0_off(struct a52d_fg *fg,const char *why,bool permanent)",
      "restore forward declaration")
    s=one(s,
      "    int ctrl=a52h0_regread(fg,A52G_CHG_CNTL1);\n    int rc=0;",
      "    int ctrl=a52h0_regread(fg,A52G_CHG_CNTL1);\n    int rc=0;\n"
      "#if IS_ENABLED(CONFIG_P479_H4)\n"
      "    if(fg->p479_h4_auto && p479_h4_restore(fg,why))\n"
      "        permanent=true;\n"
      "#endif",
      "H0 stop restores 500/500 first")
    s=one(s,
      "static void p476_h2_tick(struct a52d_fg *fg,int bat,int chg)",
      H4+"\nstatic void p476_h2_tick(struct a52d_fg *fg,int bat,int chg)",
      "H4 clock+current controller before H2")
    s=one(s,
      "\t/* A 2-second H0 guard pass and H0 CHARGING status are prerequisites. */",
      "#if IS_ENABLED(CONFIG_P479_H4)\n"
      "    if (fg->p479_h4_auto) {\n"
      "        p479_h4_tick(fg,bat,chg);\n"
      "        return;\n"
      "    }\n"
      "#endif\n"
      "\t/* A 2-second H0 guard pass and H0 CHARGING status are prerequisites. */",
      "H2 manual preserved when auto off")
    s=one(s,
      "    /* Track ten consecutive seconds of both real physical NTCs valid. */",
      "    p479_h4_pre_tick(fg);\n"
      "    /* Track ten consecutive seconds of both real physical NTCs valid. */",
      "H4 2s guard polling")
    s=one(s,
      "    p476_h2_setup(fg);",
      "    p476_h2_setup(fg);\n    p479_h4_setup(fg);",
      "H4 default-off sysfs")
    # H2/H3 manual sysfs cannot race or queue a new request while H4 owns ICL.
    s=one(s,
      'mutex_lock(&fg->a52h0_lock);\n\tif (enable) {',
      'mutex_lock(&fg->a52h0_lock);\n'
      '#if IS_ENABLED(CONFIG_P479_H4)\n'
      '\tif (fg->p479_h4_auto) {\n'
      '\t\tmutex_unlock(&fg->a52h0_lock);\n'
      '\t\treturn -EBUSY;\n'
      '\t}\n'
      '#endif\n'
      '\tif (enable) {',
      "exclusive manual H2 sysfs")
    p.write_text(s)
    k=root/K
    ks=k.read_text()
    if "config P479_H4" in ks:
        raise RuntimeError("P479 H4 Kconfig duplicate")
    k.write_text(ks+'''
config P479_H4
    bool "P479 opt-in 5V MUIC cable auto ICL/FCC through H0"
    depends on P477_H3 && P475_S2_CABLE && MGBATT_SHADOW
    default n
    help
      Kernel follows twice-sampled S2 SDP/CDP/DCP while sysfs auto=1.
      Default OFF. H0 sole writer gains only VBUSCNTL<=0x44; all
      existing thermal/killed/NTC/dwell/IRQ constraints remain.
''')
    check(root)

def check(root):
    s=(root/SRC).read_text()
    k=(root/K).read_text()
    for needle in (MARK, "DEVICE_ATTR(a52_h4_auto,0600",
                   "P479 H4 CABLE type=%s icl=%d fcc_target=%d reason=%s",
                   "P479 H4 ICL_SET ma=%d code=0x%02x readback=0x%02x rc=%d",
                   "P479 H4 FCC_SET ma=%d code=0x%02x readback=0x%02x rc=%d",
                   "P479 H4 LIMIT ma=%d reason=%s",
                   "P479 H4 FAULT reason=%s",
                   "reg==A52H0_VBUSCNTL && mask!=0x7f",
                   "val>0x44", "p479_h4_pre_tick(fg)",
                   "p479_h4_setup(fg)",
                   "p479_h4_rearm_allowed",
                   "P479_H4_CABLE_REARM"):
        if needle not in s:
            raise RuntimeError("P479 H4 source gate missing "+needle)
    if s.count("i2c_smbus_write_byte_data(") != 2:
        raise RuntimeError("P479 H4 added a second raw I2C write callsite")
    cfg=k.split("config P479_H4",1)[1].split("config ",1)[0]
    if "default n" not in cfg or "depends on P477_H3" not in cfg:
        raise RuntimeError("P479 H4 must remain gated default n")
    h4=s.split("/* "+MARK,1)[1].split("static void p476_h2_tick",1)[0]
    for forbidden in ("i2c_smbus_write_byte_data(", "regmap_write(",
                      "A52H0_BATREG,0xff", "A52H0_FACTORY1,0xff"):
        if forbidden in h4:
            raise RuntimeError("P479 H4 forbidden direct write "+forbidden)
    for ma,code in ((1800,0x44),(1500,0x38),(500,0x10),(475,0x0f)):
        assert icl_code(ma)==code
    for ma,code in ((550,0x23),(500,0x20),(1500,0x60),(2100,0x86)):
        assert fcc_code(ma)==code
    print("P479 H4 SOURCE PASS: strict 5V table, two-sample, H0 sole-writer, 500 fallback, default OFF")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True)
    ap.add_argument("--tg",type=Path)
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    if args.check_only:
        check(args.root)
    else:
        if not args.tg: raise RuntimeError("P479 H4 needs pinned TG")
        stage(args.root,args.tg)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps({
            "phase":"P479_H4","tg":TG_SHA,"default_auto":False,
            "icl_codes":{"475":"0x0f","500":"0x10","1500":"0x38","1800":"0x44"},
            "fcc_codes":{"550":"0x23","1500":"0x60","2100":"0x86"},
            "safety":"H0 sole writer; float/OTP/FACTORY1/FG/PDIC forbidden",
            "hardware_tested":False},indent=2)+"\n")
if __name__=="__main__":main()
