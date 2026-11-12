#!/usr/bin/env python3
"""P475 S2 read-only real SM5714 MUIC BC1.2 cable classification (no fake device).

TG 6bf351bd, include/linux/mfd/sm/sm5714/sm5714-private.h:19,38
  MUIC 8-bit address 0x4a => real I2C 7-bit 0x25; DEVICETYPE1=0x07.
TG include/linux/muic/sm/sm5714/sm5714-muic.h:68-81
  SDP bit1; DCP bit2; CDP bit3; AFC bit5; QC bit6.
TG drivers/muic/sm/sm5714/sm5714-muic.c:1555-1560
  Real read-only MUIC DEVICETYPE1 BC1.2 classification.
No fabricated I2C clients, no writes, no PDIC changes.
"""
import argparse
import json
import subprocess
from pathlib import Path

DONOR="6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
SRC=Path("drivers/a52_447/a52_sm5714_fg_ro.c")
K=Path("drivers/a52_447/Kconfig")
MARK="A52_P475_S2_CABLE_READ_ONLY_V1"
C=r'''
/* A52_P475_S2_CABLE_READ_ONLY_V1
 * TG sm5714-private.h:19,38: MUIC 0x4a (8-bit) = 0x25 (7-bit),
 * DEVICETYPE1 reg 0x07. TG sm5714-muic.h:68-81: BC1.2 bits.
 * Read-only SMBus xfer on existing charger adapter: no fake device.
 */
#if IS_ENABLED(CONFIG_P475_S2_CABLE)
static int p475_s2_dt1(struct a52d_fg *fg)
{
	union i2c_smbus_data data;
	int rc;

	if (!fg->a52g_chg || !fg->a52g_chg->adapter)
		return -ENODEV;
	rc = i2c_smbus_xfer(fg->a52g_chg->adapter, 0x25, 0,
			    I2C_SMBUS_READ, 0x07, I2C_SMBUS_BYTE_DATA, &data);
	if (rc < 0)
		return rc;
	return data.byte;
}
static const char *p475_s2_type(struct a52d_fg *fg, int *dt1)
{
	int status = a52h0_regread(fg, A52G_CHG_STATUS1);
	int type;
	if (status < 0) {
		*dt1 = status;
		return "UNKNOWN";
	}
	if (!(status & BIT(0))) {
		*dt1 = -ENOLINK;
		return "NONE";
	}
	type = p475_s2_dt1(fg);
	*dt1 = type;
	if (type < 0)
		return "UNKNOWN";
	/* Contradictory classifications fail closed instead of guessing. */
	if ((type & BIT(5)) && (type & BIT(6)))
		return "UNKNOWN";
	if (type & BIT(5))
		return (type & (BIT(1)|BIT(3))) ? "UNKNOWN" : "AFC";
	if (type & BIT(6))
		return (type & (BIT(1)|BIT(3))) ? "UNKNOWN" : "QC";
	if ((type & BIT(2)) &&
	    !(type & (BIT(1)|BIT(3)|BIT(4)|BIT(7))))
		return "DCP";
	if ((type & BIT(3)) && !(type & (BIT(1)|BIT(2))))
		return "CDP";
	if ((type & BIT(1)) && !(type & (BIT(2)|BIT(3))))
		return "SDP";
	return "UNKNOWN";
}
static void p475_s2_log(struct a52d_fg *fg)
{
	int dt1;
	const char *type = p475_s2_type(fg, &dt1);
	if (dt1 == fg->p475_s2_last_dt1 &&
	    !strcmp(type, fg->p475_s2_last_type))
		return;
	dev_info(fg->dev, "P475 S2 CABLE type=%s dt1=%d vbuscntl=read_only\n",
		 type, dt1);
	fg->p475_s2_last_dt1 = dt1;
	fg->p475_s2_last_type = type;
}
static ssize_t a52_cable_type_show(struct device *dev,
				struct device_attribute *attr, char *buf)
{
	struct a52d_fg *fg = dev_get_drvdata(dev);
	const char *type;
	int dt1;
	if (!fg)
		return -ENODEV;
	mutex_lock(&fg->a52h0_lock);
	type = p475_s2_type(fg, &dt1);
	mutex_unlock(&fg->a52h0_lock);
	return scnprintf(buf, PAGE_SIZE, "%s dt1=%d\n", type, dt1);
}
static DEVICE_ATTR_RO(a52_cable_type);
static void p475_s2_remove(void *arg)
{
	struct a52d_fg *fg = arg;
	device_remove_file(fg->dev, &dev_attr_a52_cable_type);
}
static void p475_s2_setup(struct a52d_fg *fg)
{
	int rc = device_create_file(fg->dev, &dev_attr_a52_cable_type);
	if (!rc) {
		rc = devm_add_action_or_reset(fg->dev, p475_s2_remove, fg);
		if (!rc)
			p475_s2_log(fg);
	}
	if (rc)
		dev_warn(fg->dev, "P475 S2 CABLE type=UNKNOWN sysfs_rc=%d\n", rc);
}
#else
static const char *p475_s2_type(struct a52d_fg *fg, int *dt1)
{
	*dt1 = -ENODEV;
	return "UNKNOWN";
}
static void p475_s2_log(struct a52d_fg *fg) {}
static void p475_s2_setup(struct a52d_fg *fg) {}
#endif
''';

def once(s,old,new,which):
    n=s.count(old)
    if n!=1:
        raise RuntimeError(f"P475 S2 {which} unique anchor drift count={n}")
    return s.replace(old,new,1)

def stage(root,tg):
    pinned=subprocess.check_output(["git","-C",str(tg),"rev-parse","HEAD"],text=True).strip()
    if pinned!=DONOR:raise RuntimeError("P475 S2 TG donor SHA drift")
    m=(tg/"include/linux/mfd/sm/sm5714/sm5714-private.h").read_text()
    h=(tg/"include/linux/muic/sm/sm5714/sm5714-muic.h").read_text()
    for marker in ("SM5714_I2C_SADR_MUIC\t(0x4A >> 1)",
                   "SM5714_MUIC_REG_DEVICETYPE1     = 0x07"):
        if m.count(marker)!=1:raise RuntimeError("P475 S2 TG MUIC address/reg changed "+marker)
    for marker in ("DEV_TYPE1_DCP\t\t\t(0x1 << 2)",
                   "DEV_TYPE1_SDP\t\t\t(0x1 << 1)",
                   "DEV_TYPE1_CDP\t\t\t(0x1 << 3)"):
        if h.count(marker)!=1:raise RuntimeError("P475 S2 TG DEVICETYPE1 bit drift")
    file=root/SRC
    s=file.read_text()
    if MARK in s:raise RuntimeError("P475 S2 already applied")
    s=once(s,"struct delayed_work a52g_guard_work;",
           "struct delayed_work a52g_guard_work;\n    int p475_s2_last_dt1;\n    const char *p475_s2_last_type;",
           "state fields")
    s=once(s,"static void a52h0_tick(struct a52d_fg *fg)",
           C+"\nstatic void a52h0_tick(struct a52d_fg *fg)",
           "read-only source before H0 tick")
    s=once(s,"    mutex_init(&fg->a52h0_lock);",
           '    mutex_init(&fg->a52h0_lock);\n    fg->p475_s2_last_dt1=-999;\n    fg->p475_s2_last_type="INIT";',
           "initialize state")
    s=once(s,'        a52h0_off(fg,"GUARD_IO",true);',
           '        a52h0_off(fg,"GUARD_IO",true);',
           "P449 preserve guard")
    # Sample inside the existing mutex-owned H0 tick, without altering
    # P449 guard-first worker, 2-second cadence or PM notifier structure.
    s=once(s,"    mutex_lock(&fg->a52h0_lock);\n    /* Track ten consecutive seconds of both real physical NTCs valid. */",
           "    mutex_lock(&fg->a52h0_lock);\n    p475_s2_log(fg);\n    /* Track ten consecutive seconds of both real physical NTCs valid. */",
           "H0 tick read-only MUIC sampling")
    s=once(s,'    if(fg->a52h0_killed)\n        dev_warn(fg->dev,"P452 H0 FAULT_LATCHED init; no arm, P449 guard scheduled\\n");',
           '    if(fg->a52h0_killed)\n        dev_warn(fg->dev,"P452 H0 FAULT_LATCHED init; no arm, P449 guard scheduled\\n");\n    p475_s2_setup(fg);',
           "read-only sysfs registration")
    file.write_text(s)
    k=root/K;cs=k.read_text()
    if "config P475_S2_CABLE" in cs:raise RuntimeError("P475 existing Kconfig collision")
    k.write_text(cs+'''
config P475_S2_CABLE
    bool "P475 SM5714 read-only MUIC cable detection (no device created)"
    depends on I2C && POWER_SUPPLY && A52_447D_SM5714_RO
    default n
    help
      Read BC1.2 type from real SM5714 MUIC register; no writes.
''')

def check(root):
    s=(root/SRC).read_text()
    k=(root/K).read_text()
    requirements=("/* "+MARK,"i2c_smbus_xfer(fg->a52g_chg->adapter, 0x25, 0,",
                  "I2C_SMBUS_READ, 0x07, I2C_SMBUS_BYTE_DATA",
                  "P475 S2 CABLE type=%s",
                  "DEVICE_ATTR_RO(a52_cable_type)",
                  'return "DCP";','return "UNKNOWN";',
                  "p475_s2_log(fg);","p475_s2_setup(fg);")
    for item in requirements:
        if item not in s:raise RuntimeError("P475 source invariant: "+item)
    if s.count("P475 S2 CABLE type=%s")!=1:
        raise RuntimeError("P475 duplicated cable log")
    if "config P475_S2_CABLE" not in k or "default n" not in k.split("config P475_S2_CABLE")[1].split("config ")[0]:
        raise RuntimeError("P475 default-off Kconfig missing")
    for forbidden in ("i2c_smbus_write", "i2c_new_dummy_device", "i2c_new_client_device",
                      "sm5714_update_reg", "SM5714_MUIC_REG_AFCCTRL"):
        if forbidden in C:raise RuntimeError("P475 S2 attempted writes/fake devices")
    print("P475 S2 SOURCE PASS: read-only real MUIC, SDP/CDP/DCP/AFC/QC, no writes")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--tg",type=Path)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    if not a.check_only:
        if not a.tg:raise RuntimeError("S2 pinned TG required")
        stage(a.root,a.tg)
    check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps({"stage":"P475-S2","donor":DONOR,
          "source":"MUIC real read-only SMBus reg 0x07 at 7bit 0x25",
          "status":"SOURCE_PASS","no_writes":True,"hardware_confirmed":False,
          "kconfig_default":"n"},indent=2)+"\n")
if __name__=="__main__":
    main()
