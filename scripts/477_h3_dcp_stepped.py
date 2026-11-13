#!/usr/bin/env python3
"""P477 H0 active re-arm fix + opt-in H3, based on verified P476 H2.

Source: TG 6bf351bdf18bdb228db79e66f14a7a9c0178e5d7
drivers/battery/charger/sm5714_charger/sm5714_charger.c:243-264
1500 mA = 0x60, 2100 mA = 0x86, battery-charge FCC not VBUS ICL.
No new register writer; only existing H0 masked-write-with-readback.
No boot auto-arm. A3b audio remains separately gated.
"""
import argparse
import json
import subprocess
from pathlib import Path

DONOR = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
SRC = Path("drivers/a52_447/a52_sm5714_fg_ro.c")
K = Path("drivers/a52_447/Kconfig")
MARK = "P477_H3_SINGLE_WRITER_STEPPED_DCP_ONLY_V1"

# Insert inside the existing #if CONFIG_P476_H2 block, following H2's
# original p476_h2_off() function and preceding p476_h2_tick().
H3 = r'''
/* P477_H3_SINGLE_WRITER_STEPPED_DCP_ONLY_V1
 * TG sm5714_charger.c:243-264 maps FCC to CHGCNTL2 0x18.
 * The live A52 TA DT specifies input 1800 / battery FCC 2100 mA.
 * H0 remains the only writer. Do not alter VBUSCNTL/BATREG/FACTORY1.
 */
#if IS_ENABLED(CONFIG_P477_H3)
#define P477_H3_CODE_500 0x20
#define P477_H3_CODE_1000 0x40
#define P477_H3_CODE_1400 0x59
#define P477_H3_CODE_1500 0x60
#define P477_H3_CODE_2100 0x86
#define P477_H3_STEP_INTERVAL (60 * HZ)
static int p477_h3_code(int ma)
{
    switch (ma) {
    case 500: return P477_H3_CODE_500;
    case 1000: return P477_H3_CODE_1000;
    case 1400: return P477_H3_CODE_1400;
    case 1500: return P477_H3_CODE_1500;
    case 2100: return P477_H3_CODE_2100;
    default: return -EINVAL;
    }
}
static void p477_h3_reset_stable(struct a52d_fg *fg, int bat, int chg)
{
    fg->p477_h3_stable_since = jiffies;
    fg->p477_h3_bat_anchor = bat;
    fg->p477_h3_chg_anchor = chg;
}
static void p477_h3_limit(struct a52d_fg *fg, int ma, const char *reason)
{
    dev_warn(fg->dev,"P477 H3 LIMIT ma=%d reason=%s\n",ma,reason);
}
/* Always entered with the H0 mutex, after H0's original guard pass. */
static void p477_h3_tick(struct a52d_fg *fg, int bat, int chg)
{
    int vbus, fc, fl, st1, ctrl, wdt, cur, dt1, rc, limit;
    int actual = fg->p477_h3_actual_ma;
    int target = fg->p477_h3_target_ma;
    int next;
    const char *type, *reason = NULL;
    unsigned long now = jiffies;

    if (!fg->p476_h2_enabled && !fg->p476_h2_fast)
        return;

    if (!fg->a52h0_active || !fg->a52h0_armed ||
        fg->a52h0_killed || fg->a52g_inhibit_latched ||
        !fg->a52h0_state ||
        strcmp(fg->a52h0_state,"CHARGING")) {
        reason = "H0_NOT_CHARGING";
        goto off;
    }
    /* Both independent physical NTCs must be valid; fail to 500 on doubt.
     * Existing H0 stronger 41C/50C shutdown stays in effect.
     */
    if (bat < 150 || bat > 900 || chg < -200 || chg > 900) {
        reason = "NTC_INVALID";
        goto off;
    }
    if (bat >= 410)
        fg->p477_h3_bat_hot = true;
    if (fg->p477_h3_bat_hot && bat <= 390)
        fg->p477_h3_bat_hot = false;
    if (fg->p477_h3_bat_hot) {
        reason = "BAT_41C_HYSTERESIS_39C";
        goto off;
    }
    if (chg >= 550) {
        reason = "CHARGER_55C";
        goto off;
    }

    vbus = a52h0_regread(fg,A52H0_VBUSCNTL);
    fc = a52h0_regread(fg,A52H0_FACTORY1);
    fl = a52h0_regread(fg,A52H0_BATREG);
    st1 = a52h0_regread(fg,A52G_CHG_STATUS1);
    ctrl = a52h0_regread(fg,A52G_CHG_CNTL1);
    wdt = a52h0_regread(fg,A52H0_WDTCNTL);
    cur = a52h0_regread(fg,A52H0_CHGCNTL2);
    if (vbus<0 || fc<0 || fl<0 || st1<0 || ctrl<0 ||
        wdt<0 || cur<0) {
        reason = "READ_ERROR";
        goto off;
    }
    if (vbus != 0x44 || vbus > A52H01_MAX_BOOTLOADER_VBUSCNTL) {
        reason = "VBUS_NOT_0X44";
        goto off;
    }
    if ((fc & (BIT(0)|BIT(1))) ||
        (fl & 0x3f) != A52H0_FLOAT_4380_CODE ||
        !(st1 & BIT(0)) || !(ctrl & A52G_CHG_ENQ4FET) ||
        (wdt & 0x07) != (A52H0_90S_WDT|BIT(0))) {
        reason = "FACTORY_FLOAT_WDT_OR_ENABLE";
        goto off;
    }
    type = p475_s2_type(fg,&dt1);
    if (strcmp(type,"DCP")) {
        reason = "NOT_DCP";
        goto off;
    }
    if (cur != p477_h3_code(actual)) {
        reason = "CHGCNTL2_DRIFT";
        goto off;
    }

    /* Clamp on charger NTC without changing the accepted user values. */
    limit = chg >= 480 ? 1400 : 2100;
    if (target > limit) {
        p477_h3_limit(fg,limit,"CHARGER_48C_CAP");
        target=limit;
    }
    if (target < actual) {
        /* Immediate demotion, including directly to 500 on a hot NTC. */
        next = target;
    } else if (target == actual) {
        return;
    } else {
        /* Refuse escalation until a full 60 s at stable temperatures.
         * >1C drift in either NTC restarts the stability window.
         */
        if (abs(bat-fg->p477_h3_bat_anchor)>10 ||
            abs(chg-fg->p477_h3_chg_anchor)>10) {
            p477_h3_reset_stable(fg,bat,chg);
            p477_h3_limit(fg,actual,"TEMPERATURE_MOVING");
            return;
        }
        if (time_before(now,fg->p477_h3_last_step+P477_H3_STEP_INTERVAL) ||
            time_before(now,fg->p477_h3_stable_since+P477_H3_STEP_INTERVAL))
            return;
        /* Even when user requests 2100 directly, climb one step only. */
        if (actual==500) next=1000;
        else if (actual==1000) next=1500;
        else if (actual==1400) next=1500;
        else if (actual==1500) next=2100;
        else {
            reason="UNEXPECTED_ACTUAL_CURRENT";
            goto off;
        }
        if (next>target)next=target;
        if (next>limit)next=limit;
    }
    if (next>2100 || next<500 || p477_h3_code(next)<0) {
        reason="INVALID_CURRENT";
        goto off;
    }
    rc=a52h0_write_masked(fg,A52H0_CHGCNTL2,0xff,
                          (u8)p477_h3_code(next));
    if (rc) {
        reason="CURRENT_WRITE_OR_READBACK";
        goto off;
    }
    fg->p477_h3_actual_ma=next;
    fg->p476_h2_fast=(next>500);
    fg->p477_h3_last_step=now;
    p477_h3_reset_stable(fg,bat,chg);
    dev_info(fg->dev,
      "P477 H3 SET ma=%d code=0x%02x vbuscntl=0x44 type=DCP bat=%d chg=%d\n",
      next,p477_h3_code(next),bat,chg);
    if(next==1000)
        dev_info(fg->dev,
          "P476 H2 ON cur=1000 vbuscntl=0x%02x type=%s\n",vbus,type);
    return;
off:
    p477_h3_limit(fg,500,reason?reason:"UNKNOWN");
    rc=p476_h2_off(fg,reason?reason:"P477_H3_SAFETY");
    if(rc) {
        dev_err(fg->dev,"P477 H3 RESTORE_500_FAILED rc=%d inhibit=1\n",rc);
        /* Existing H0 tick sees killed flag and executes OFF. */
        fg->a52h0_killed=true;
        fg->a52h0_armed=false;
    }
    fg->p477_h3_actual_ma=500;
}
static ssize_t a52_h2_ma_show(struct device *dev,
       struct device_attribute *attr,char *buf)
{
    struct a52d_fg *fg=dev_get_drvdata(dev);
    return scnprintf(buf,PAGE_SIZE,"%d\n",fg->p477_h3_target_ma);
}
static ssize_t a52_h2_ma_store(struct device *dev,
       struct device_attribute *attr,const char *buf,size_t len)
{
    struct a52d_fg *fg=dev_get_drvdata(dev);
    int ma;
    if(kstrtoint(buf,10,&ma))return -EINVAL;
    if(ma!=500 && ma!=1000 && ma!=1500 && ma!=2100)return -EINVAL;
    mutex_lock(&fg->a52h0_lock);
    /* Only a request; no direct register write in sysfs context. */
    fg->p477_h3_target_ma=ma;
    mutex_unlock(&fg->a52h0_lock);
    return len;
}
static DEVICE_ATTR(a52_h2_ma,0600,a52_h2_ma_show,a52_h2_ma_store);
static void p477_h3_remove(void *arg)
{
    struct a52d_fg *fg=arg;
    device_remove_file(fg->dev,&dev_attr_a52_h2_ma);
}
static void p477_h3_setup(struct a52d_fg *fg)
{
    int rc;
    fg->p477_h3_target_ma=1000;
    fg->p477_h3_actual_ma=500;
    fg->p477_h3_last_step=jiffies;
    p477_h3_reset_stable(fg,a52g_ntc_temp(fg),a52h_chg_ntc_temp(fg));
    rc=device_create_file(fg->dev,&dev_attr_a52_h2_ma);
    if(!rc)
        rc=devm_add_action_or_reset(fg->dev,p477_h3_remove,fg);
    if(rc)dev_err(fg->dev,"P477 H3 LIMIT ma=500 reason=SYSFS_ERROR rc=%d\n",rc);
}
#endif /* CONFIG_P477_H3 */
'''

def once(s, before, after, label):
    n=s.count(before)
    if n!=1:
        raise RuntimeError("P477 "+label+" anchor count="+str(n))
    return s.replace(before,after,1)

def check(root):
    s=(root/SRC).read_text()
    k=(root/K).read_text()
    assert s.count("P477_H3_SINGLE_WRITER_STEPPED_DCP_ONLY_V1")==1
    assert s.count("config P477_H3")==1
    scope=k.split("config P477_H3",1)[1].split("config ",1)[0]
    assert "depends on P476_H2 && P475_S2_CABLE" in scope and "default n" in scope
    for piece in ('DEVICE_ATTR(a52_h2_ma,0600', 'P477 H3 SET ma=%d code=0x%02x',
                  'P477 H3 LIMIT ma=%d reason=%s',
                  'P476 H2 ARM_REFUSED state=%s active=%d armed=%d killed=%d latch=%d',
                  'if(arm && fg->a52h0_active)',
                  'P477_H3_CODE_1500 0x60','P477_H3_CODE_2100 0x86',
                  'time_before(now,fg->p477_h3_last_step+P477_H3_STEP_INTERVAL)',
                  'vbus != 0x44', 'strcmp(type,"DCP")',
                  'a52h0_write_masked(fg,A52H0_CHGCNTL2,0xff,',
                  'if(reg==A52H0_CHGCNTL2 && val>0x86)return -EPERM;'):
        if piece not in s:
            raise RuntimeError("P477 missing audit marker/gate "+piece)
    assert 7+(1500000-109375)//15625 == 0x60
    assert 7+(2100000-109375)//15625 == 0x86
    assert s.count("i2c_smbus_write_byte_data(")==2
    # The helper's register allowlist is unchanged; it rejects any
    # attempt to write a CHGCNTL2 code >0x86, regardless of caller.
    h3=s.split("/* "+MARK,1)[1].split("static void p476_h2_tick",1)[0]
    for forbidden in ("i2c_smbus_write_byte_data(", "i2c_smbus_write_word_data(",
                      "A52H0_VBUSCNTL,0xff","A52H0_BATREG,0xff",
                      "A52H0_FACTORY1,0xff", "EFS", "PDIC_WRITE"):
        if forbidden in h3:
            raise RuntimeError("P477 forbidden direct hardware operation "+forbidden)
    print("P477 SOURCE PASS: H0 rearm idempotent, 500/1000/1500/2100 DCP-only, upper cap enforced, NO ARM")

def stage(root,tg):
    sha=subprocess.check_output(["git","-C",str(tg),"rev-parse","HEAD"],text=True).strip()
    if sha!=DONOR:raise RuntimeError("P477 TG donor SHA drift: "+sha)
    donor=(tg/"drivers/battery/charger/sm5714_charger/sm5714_charger.c").read_text()
    assert donor.count("offset = (7 + ((uA - 109375) / 15625)) & 0xFF;")==1
    for ma,code in ((500,0x20),(1000,0x40),(1400,0x59),(1500,0x60),(2100,0x86)):
        if 7+((ma*1000-109375)//15625)!=code:
            raise RuntimeError("P477 TG current mapping mismatch "+str(ma))
    p=root/SRC;s=p.read_text()
    if MARK in s:raise RuntimeError("P477 already staged")

    # H0 bug: a repeated write of 1 while hardware is already active
    # must NOT relabel CHARGING -> ARMED or clear an inhibit latch.
    h0_anchor='    if(arm) {\n        int bt=a52g_ntc_temp(fg),ct=a52h_chg_ntc_temp(fg);'
    s=once(s,h0_anchor,
       '    if(arm && fg->a52h0_active) {\n'
       '        mutex_unlock(&fg->a52h0_lock);\n'
       '        return len; /* idempotent: preserve CHARGING and latch */\n'
       '    }\n'+h0_anchor,"active H0 manual rearm")

    # Explicit H2 refusals must be observable, including current H0 state.
    h2_anchor=('\t\t    strcmp(fg->a52h0_state,"CHARGING"))\n'
               '\t\t\trc=-EPERM;')
    s=once(s,h2_anchor,
       '\t\t    strcmp(fg->a52h0_state,"CHARGING")) {\n'
       '            dev_warn(fg->dev,\n'
       '             "P476 H2 ARM_REFUSED state=%s active=%d armed=%d killed=%d latch=%d\\n",\n'
       '             fg->a52h0_state?fg->a52h0_state:"OFF",fg->a52h0_active,\n'
       '             fg->a52h0_armed,fg->a52h0_killed,fg->a52g_inhibit_latched);\n'
       '\t\t\trc=-EPERM;\n'
       '        }',"H2 refusal errno logging")

    # Start the 60-second dwell from each manual H2 arm, not from boot.
    h2_on=('\t\telse\n'
           '\t\t\tfg->p476_h2_enabled=true;')
    s=once(s,h2_on,
       '\t\telse {\n'
       '\t\t\tfg->p476_h2_enabled=true;\n'
       '#if IS_ENABLED(CONFIG_P477_H3)\n'
       '            fg->p477_h3_last_step=jiffies;\n'
       '            p477_h3_reset_stable(fg,a52g_ntc_temp(fg),\n'
       '                                 a52h_chg_ntc_temp(fg));\n'
       '#endif\n'
       '        }',
       "H3 dwell begins on H2 explicit arm")

    # Every write including calls from old H0/H2 is bounded by the
    # existing sole writer, never a new unrestricted I2C call.
    s=once(s,'    old=a52h0_regread(fg,reg);',
       '    if(reg==A52H0_CHGCNTL2 && val>0x86)return -EPERM;\n'
       '    old=a52h0_regread(fg,reg);',
       "upper-bound enforcement in sole writer")

    s=once(s,'    bool p476_h2_enabled, p476_h2_fast;',
       '    bool p476_h2_enabled, p476_h2_fast;\n'
       '#if IS_ENABLED(CONFIG_P477_H3)\n'
       '    bool p477_h3_bat_hot;\n'
       '    int p477_h3_target_ma, p477_h3_actual_ma;\n'
       '    int p477_h3_bat_anchor, p477_h3_chg_anchor;\n'
       '    unsigned long p477_h3_stable_since, p477_h3_last_step;\n'
       '#endif',
       'per-device H3 state')

    s=once(s,'static void p476_h2_tick(struct a52d_fg *fg,int bat,int chg)',
           H3+'\nstatic void p476_h2_tick(struct a52d_fg *fg,int bat,int chg)',
           "H3 current controller, independent Kconfig")
    s=once(s,
       '\t/* A 2-second H0 guard pass and H0 CHARGING status are prerequisites. */',
       '#if IS_ENABLED(CONFIG_P477_H3)\n'
       '    p477_h3_tick(fg,bat,chg);\n'
       '    return;\n'
       '#endif\n'
       '\t/* A 2-second H0 guard pass and H0 CHARGING status are prerequisites. */',
       "route H2 timer to H3 only when selected")
    s=once(s,
       '    if (was_on || rc)\n',
       '#if IS_ENABLED(CONFIG_P477_H3)\n'
       '    fg->p477_h3_actual_ma=500;\n'
       '#endif\n'
       '    if (was_on || rc)\n',
       "reset H3 tracking on H2 stop")

    s=once(s,
       '\tif (rc)\n\t\tdev_warn(fg->dev,"P476 H2 OFF reason=SYSFS_UNAVAILABLE rc=%d\\n",rc);',
       '\tif (rc)\n\t\tdev_warn(fg->dev,"P476 H2 OFF reason=SYSFS_UNAVAILABLE rc=%d\\n",rc);\n'
       '#if IS_ENABLED(CONFIG_P477_H3)\n'
       '    if(!rc)p477_h3_setup(fg);\n'
       '#endif',
       "manual sysfs setup")

    p.write_text(s)
    k=root/K;ks=k.read_text()
    if "config P477_H3" in ks:raise RuntimeError("P477 H3 Kconfig already exists")
    k.write_text(ks+'''
config P477_H3
    bool "P477 H3 manual DCP battery fast-current ramp (500-2100mA)"
    depends on P476_H2 && P475_S2_CABLE
    default n
    help
      H0 remains the only charger writer. Manual a52_h2_enable is OFF
      by default. On real DCP with unchanged 0x44 input, step 60s or
      slower using the two physical NTCs, never exceed code 0x86.
''')
    check(root)

def main():
    pa=argparse.ArgumentParser()
    pa.add_argument("--root",required=True,type=Path)
    pa.add_argument("--tg",type=Path)
    pa.add_argument("--check-only",action="store_true")
    pa.add_argument("--report",type=Path)
    a=pa.parse_args()
    if not a.check_only:
        if not a.tg:raise RuntimeError("P477 needs pinned TG donor")
        stage(a.root,a.tg)
    check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps({"stage":"P477-H3","status":"SOURCE_PASS",
           "tg":DONOR,"max_fcc_ma":2100,"max_code":"0x86",
           "runtime_auto_arm":False,"charger_writer":"H0 only",
           "hardware_verified":False},indent=2)+"\n")
if __name__=="__main__":
    main()
