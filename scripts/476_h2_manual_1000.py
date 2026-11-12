#!/usr/bin/env python3
"""P476 H2: opt-in 1000mA on existing H0, default OFF, always fail closed.

TG @6bf351bd drivers/battery/charger/sm5714_charger/sm5714_charger.c:
  243-264: fast current code 7+(mA*1000-109375)/15625,
           500mA -> 0x20; 1000mA -> 0x40, register CHGCNTL2.
  301-307: VBUSCNTL 0x44 -> 100 + 68*25 = 1800mA.
We NEVER write VBUSCNTL, BATREG float, FACTORY1, PDIC, OTP, EFS.
H0's stricter input<=0x44 remains; H2 thus needs exactly 0x44.
"""
import argparse
import json
import subprocess
from pathlib import Path

DONOR="6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
SRC=Path("drivers/a52_447/a52_sm5714_fg_ro.c")
K=Path("drivers/a52_447/Kconfig")
MARK="A52_P476_H2_WALL_FAST_CURRENT_MANUAL_V1"
# H2 uses only the EXISTING audited H0 I2C write gate. No additional
# raw i2c_smbus_write_byte_data() callsites.
PROTOTYPE=r'''
#if IS_ENABLED(CONFIG_P476_H2)
static int p476_h2_off(struct a52d_fg *fg, const char *reason);
#endif
'''
CODE=r'''
/* A52_P476_H2_WALL_FAST_CURRENT_MANUAL_V1
 * Independent Kconfig default=n and sysfs runtime default=0.
 * TG sm5714_charger.c:243-264: 1000mA -> CHGCNTL2 code 0x40.
 * H0's 0x44 input ceiling is PRESERVED. Do not write VBUSCNTL.
 */
#if IS_ENABLED(CONFIG_P476_H2)
#define P476_H2_1000MA_CODE 0x40
#define P476_H2_BATTERY_STOP_DECI_C 390
#define P476_H2_CHARGER_STOP_DECI_C 450
static const char *p475_s2_type(struct a52d_fg *fg, int *dt1);

/* Locking: a52h0_lock is held by all callers, including H0 OFF paths. */
static int p476_h2_off(struct a52d_fg *fg, const char *reason)
{
	int current, rc=0;
	bool was_on=fg->p476_h2_fast || fg->p476_h2_enabled;

	/* Absolutely no extra I2C reads/writes on the H0-only default. */
	if (!was_on)
		return 0;
	current=a52h0_regread(fg,A52H0_CHGCNTL2);
	if (fg->p476_h2_fast || current==P476_H2_1000MA_CODE) {
		rc=a52h0_write_masked(fg,A52H0_CHGCNTL2,0xff,
				      A52H0_CHG_FAST_500MA);
		if (rc) {
			/* If 500mA cannot be restored, caller must inhibit H0. */
			fg->a52h0_killed=true;
			fg->a52h0_armed=false;
		}
	}
	fg->p476_h2_fast=false;
	fg->p476_h2_enabled=false;
	if (was_on || rc)
		dev_warn(fg->dev,"P476 H2 OFF reason=%s rc=%d cur=500_request\n",
			 reason,rc);
	return rc;
}
static void p476_h2_tick(struct a52d_fg *fg,int bat,int chg)
{
	int vbus,fl,fc,cur,dt1,ctrl,wdt,st1,rc;
	const char *type, *reason=NULL;

	/* A 2-second H0 guard pass and H0 CHARGING status are prerequisites. */
	if (!fg->p476_h2_enabled && !fg->p476_h2_fast)
		return;
	if (!fg->a52h0_active || !fg->a52h0_armed ||
	    fg->a52h0_killed || fg->a52g_inhibit_latched ||
	    strcmp(fg->a52h0_state,"CHARGING")) {
		reason="H0_NOT_CHARGING";
		goto off;
	}
	if (bat<150 || bat>=P476_H2_BATTERY_STOP_DECI_C) {
		reason="BATTERY_39C";
		goto off;
	}
	if (chg< -200 || chg>=P476_H2_CHARGER_STOP_DECI_C) {
		reason="CHARGER_45C";
		goto off;
	}
	vbus=a52h0_regread(fg,A52H0_VBUSCNTL);
	fc=a52h0_regread(fg,A52H0_FACTORY1);
	fl=a52h0_regread(fg,A52H0_BATREG);
	st1=a52h0_regread(fg,A52G_CHG_STATUS1);
	ctrl=a52h0_regread(fg,A52G_CHG_CNTL1);
	wdt=a52h0_regread(fg,A52H0_WDTCNTL);
	cur=a52h0_regread(fg,A52H0_CHGCNTL2);
	if (vbus<0 || fc<0 || fl<0 || st1<0 || ctrl<0 ||
	    wdt<0 || cur<0) {
		reason="READ_ERROR";
		goto off;
	}
	/* H0.1 rejects >0x44, so BOTH bounds are kept. */
	if (vbus < 0x44 || vbus>A52H01_MAX_BOOTLOADER_VBUSCNTL) {
		reason="INPUT_NOT_WALL";
		goto off;
	}
	if ((fc&(BIT(0)|BIT(1))) ||
	    (fl&0x3f)!=A52H0_FLOAT_4380_CODE) {
		reason="FACTORY_OR_FLOAT";
		goto off;
	}
	if (!(st1&BIT(0)) || !(ctrl&A52G_CHG_ENQ4FET) ||
	    (wdt&0x07)!=(A52H0_90S_WDT|BIT(0))) {
		reason="VBUS_OR_WDT";
		goto off;
	}
	/*
	 * Both tracks are independently gated. When S2 is unavailable
	 * or the real MUIC disagrees, NO elevated current is permitted.
	 */
	type=p475_s2_type(fg,&dt1);
	if (strcmp(type,"DCP")) {
		dev_warn(fg->dev,
			 "P476 H2 CABLE_DISAGREE vbuscntl=0x%02x type=%s dt1=%d\n",
			 vbus,type,dt1);
		reason="CABLE_NOT_DCP";
		goto off;
	}
	if (fg->p476_h2_fast) {
		if (cur!=P476_H2_1000MA_CODE) {
			reason="CHGCNTL2_DRIFT";
			goto off;
		}
		return;
	}
	/* Never increase from an unknown fast-charge register value. */
	if (cur!=A52H0_CHG_FAST_500MA) {
		reason="PRE_RAISE_CHGCNTL2_DRIFT";
		goto off;
	}
	rc=a52h0_write_masked(fg,A52H0_CHGCNTL2,0xff,
			      P476_H2_1000MA_CODE);
	if (rc) {
		reason="1000MA_WRITE_OR_READBACK";
		goto off;
	}
	fg->p476_h2_fast=true;
	dev_info(fg->dev,"P476 H2 ON cur=1000 vbuscntl=0x%02x type=%s\n",
		 vbus,type);
	return;
off:
	rc=p476_h2_off(fg,reason ? reason : "UNKNOWN");
	if (rc)
		dev_err(fg->dev,"P476 H2 OFF reason=500MA_RESTORE_FAILED rc=%d; H0 must inhibit\n",rc);
}
static ssize_t a52_h2_enable_show(struct device *dev,
				 struct device_attribute *attr,char *buf)
{
	struct a52d_fg *fg=dev_get_drvdata(dev);
	if (!fg)
		return -ENODEV;
	return scnprintf(buf,PAGE_SIZE,"%d\n",fg->p476_h2_enabled);
}
static ssize_t a52_h2_enable_store(struct device *dev,
				 struct device_attribute *attr,
				 const char *buf,size_t len)
{
	struct a52d_fg *fg=dev_get_drvdata(dev);
	bool enable;
	int rc=0;
	if (!fg || kstrtobool(buf,&enable))
		return -EINVAL;
	mutex_lock(&fg->a52h0_lock);
	if (enable) {
		/* Manual arm is refused unless H0 is already charging. */
		if (!fg->a52h0_active || !fg->a52h0_armed ||
		    fg->a52h0_killed || fg->a52g_inhibit_latched ||
		    strcmp(fg->a52h0_state,"CHARGING"))
			rc=-EPERM;
		else
			fg->p476_h2_enabled=true;
	} else {
		rc=p476_h2_off(fg,"MANUAL_DISARM");
		if (rc)
			a52h0_off(fg,"H2_RESTORE_FAILED",true);
	}
	mutex_unlock(&fg->a52h0_lock);
	return rc ? rc : len;
}
static DEVICE_ATTR(a52_h2_enable,0600,a52_h2_enable_show,a52_h2_enable_store);
static void p476_h2_remove(void *arg)
{
	struct a52d_fg *fg=arg;
	device_remove_file(fg->dev,&dev_attr_a52_h2_enable);
}
static void p476_h2_setup(struct a52d_fg *fg)
{
	int rc;
	fg->p476_h2_enabled=false;
	fg->p476_h2_fast=false;
	rc=device_create_file(fg->dev,&dev_attr_a52_h2_enable);
	if (!rc)
		rc=devm_add_action_or_reset(fg->dev,p476_h2_remove,fg);
	if (rc)
		dev_warn(fg->dev,"P476 H2 OFF reason=SYSFS_UNAVAILABLE rc=%d\n",rc);
}
#else
static void p476_h2_setup(struct a52d_fg *fg) {}
#endif
''';

def once(s,old,new,label):
    n=s.count(old)
    if n!=1:raise RuntimeError(f"P476 H2 {label} anchor count={n}")
    return s.replace(old,new,1)

def stage(root,tg):
    pin=subprocess.check_output(["git","-C",str(tg),"rev-parse","HEAD"],text=True).strip()
    if pin!=DONOR:raise RuntimeError("P476 H2 donor SHA drift")
    f=(tg/"drivers/battery/charger/sm5714_charger/sm5714_charger.c").read_text()
    if "offset = (7 + ((uA - 109375) / 15625)) & 0xFF;" not in f:
        raise RuntimeError("P476 H2 TG code/current mapping changed")
    if "return ((reg & 0x7F) * 25) + 100;" not in f:
        raise RuntimeError("P476 H2 TG VBUSCNTL code/current mapping changed")
    assert 7+((1000000-109375)//15625)==0x40
    assert 7+((500000-109375)//15625)==0x20
    assert 100+0x44*25==1800
    p=root/SRC;s=p.read_text()
    if MARK in s:raise RuntimeError("H2 already staged")
    if "A52_P475_S2_CABLE_READ_ONLY_V1" not in s:
        raise RuntimeError("H2 must be staged after real S2 cable detector")
    s=once(s,"    int p475_s2_last_dt1;",
           "    bool p476_h2_enabled, p476_h2_fast;\n    int p475_s2_last_dt1;",
           "zero-initialized H2 flags in FG owner")
    s=once(s,"static void a52h0_off(struct a52d_fg *fg,const char *why,bool permanent)",
           PROTOTYPE+"""
static void a52h0_off(struct a52d_fg *fg,const char *why,bool permanent)""",
           "forward helper")
    s=once(s,"    int ctrl=a52h0_regread(fg,A52G_CHG_CNTL1);\n    int rc=0;",
           """    int ctrl=a52h0_regread(fg,A52G_CHG_CNTL1);
    int rc=0;
#if IS_ENABLED(CONFIG_P476_H2)
    /* Return to 500 mA BEFORE any existing H0 disable/stop path. */
    if((fg->p476_h2_fast || fg->p476_h2_enabled) &&
       p476_h2_off(fg,why))
        permanent=true;
#endif""",
           "all H0 OFF paths safely demote 500mA")
    s=once(s,"static void a52h0_tick(struct a52d_fg *fg)",
           CODE+"\nstatic void a52h0_tick(struct a52d_fg *fg)",
           "H2 manual gate logic")
    s=once(s,"        /* Guard checks run every 2s; kick hardware WDT no faster than 10s. */",
           """#if IS_ENABLED(CONFIG_P476_H2)
        p476_h2_tick(fg,tbat,tchg);
        if(fg->a52h0_killed) {
            a52h0_off(fg,"H2_RESTORE_FAILED",true);
            goto done;
        }
#endif
        /* Guard checks run every 2s; kick hardware WDT no faster than 10s. */""",
           "H2 tick after H0 verification before 10s WDT limit")
    s=once(s,"    p475_s2_setup(fg);",
           "    p475_s2_setup(fg);\n    p476_h2_setup(fg);",
           "H2 independent default-off sysfs")
    p.write_text(s)
    k=root/K;cs=k.read_text()
    if "config P476_H2" in cs:raise RuntimeError("H2 Kconfig collision")
    k.write_text(cs+'''
config P476_H2
    bool "P476 H2 manual-only SM5714 1000mA wall current"
    depends on A52_447D_SM5714_RO && P475_S2_CABLE
    default n
    help
      Runtime OFF by default. Require H0 CHARGING, VBUSCNTL 0x44 and DCP.
      Fail-closed restore 500mA before H0 OFF on any discrepancy.
''')

def check(root):
    s=(root/SRC).read_text();k=(root/K).read_text()
    begin=s.index("/* "+MARK);end=s.index("static void a52h0_tick",begin)
    h2=s[begin:end]
    for required in ("P476 H2 ON cur=1000 vbuscntl=0x%02x type=%s",
                     "P476 H2 OFF reason=%s",
                     "P476 H2 CABLE_DISAGREE",
                     "P476_H2_BATTERY_STOP_DECI_C 390",
                     "P476_H2_CHARGER_STOP_DECI_C 450",
                     "P476_H2_1000MA_CODE 0x40",
                     "a52_h2_enable", "DEVICE_ATTR(a52_h2_enable,0600",
                     "p475_s2_type(fg,&dt1)",
                     "A52H01_MAX_BOOTLOADER_VBUSCNTL",
                     "a52h0_write_masked(fg,A52H0_CHGCNTL2,0xff,",
                     "p476_h2_off(fg,why)",
                     "p476_h2_setup(fg);",
                     "p476_h2_tick(fg,tbat,tchg)"):
        if required not in s:raise RuntimeError("P476 H2 source gate absent "+required)
    if "config P476_H2" not in k or "default n" not in k.split("config P476_H2")[1]:
        raise RuntimeError("H2 Kconfig must default n")
    if s.count("i2c_smbus_write_byte_data(")!=2:
        raise RuntimeError("H2 added prohibited generic register write site")
    for forbidden in ("i2c_smbus_write_byte_data(", "A52H0_FACTORY1,0xff",
                      "A52H0_VBUSCNTL,0xff","A52H0_BATREG,0xff",
                      "i2c_smbus_write_word_data(","EFS","PDIC_WRITE"):
        if forbidden in h2:raise RuntimeError("H2 forbidden new write/side effect "+forbidden)
    if s.count("P476 H2 ON cur=1000")!=1:
        raise RuntimeError("H2 marker duplication")
    print("P476 H2 SOURCE PASS: manual OFF; real H0 gated 1000mA; 39C/45C to 500; no prohibited register writes")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--tg",type=Path)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    if not a.check_only:
        if not a.tg:raise RuntimeError("H2 pinned donor required")
        stage(a.root,a.tg)
    check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps({"stage":"P476-H2","donor":DONOR,
          "status":"SOURCE_PASS","default":"off","manual_arm":True,
          "hard_battery_stop_C":39,"hard_charger_stop_C":45,
          "max_charge_mA":1000,"revert_mA":500,
          "mutated_registers":["CHGCNTL2 via audited H0 only"],
          "hardware_confirmed":False},indent=2)+"\n")
if __name__=="__main__":
    main()
