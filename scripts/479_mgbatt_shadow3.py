#!/usr/bin/env python3
"""P479 read-only MGBATT shadow stage 3: r02 full/recharge and H4 compare."""
import argparse
import json
from pathlib import Path

SRC = Path("drivers/a52_447/a52_sm5714_fg_ro.c")
SH = Path("drivers/a52_447/mgbatt_shadow")
MARK = "P479_MGBATT_SHADOW3_COMPARE_NO_WRITES_V1"

COMPARE = r'''
/* P479_MGBATT_SHADOW3_COMPARE_NO_WRITES_V1
 * This observer never applies a vote, writes a register, or changes H0.
 * Full/recharge indications are reported using the live r02 thresholds;
 * they are not a second Samsung battery state machine.
 */
void mgbatt_shadow_compare(struct device *owner, const char *type,
                           int bat, int chg, int soc, int vcell,
                           int actual_icl, int actual_fcc, bool full)
{
    static int prev_icl=-1,prev_fcc=-1,prev_wicl=-1,prev_wfcc=-1;
    static bool prev_full;
    static unsigned long last_compare;
    int index;
    u32 would_icl=0,would_fcc=0;
    const char *reason="UNAVAILABLE";
    bool changed;
    if (!owner) return;
    mutex_lock(&mgbatt_lock);
    if (!ready) goto out;
    index=mgbatt_cable_index(type);
    mgbatt_policy_calculate(&policy,index,bat,chg,
                            &would_icl,&would_fcc,&reason);
    /* Real DT full-check/recharge thresholds, observational only.
     * Respect H0's hardware top-off/full state rather than inventing
     * a TG sec_battery vote or changing charging hardware.
     */
    if (full && soc>=0 && vcell>=0) {
        if (soc>=policy.full_soc &&
            vcell>=policy.full_vcell) {
            would_fcc=0;
            reason="TG_R02_FULL_CONDITION";
        } else if (vcell<=policy.recharge_vcell ||
                   soc<=policy.recharge_soc) {
            reason="TG_R02_RECHARGE_CONDITION";
        } else {
            reason="H0_FULL_NO_TG_THRESHOLD_MATCH";
        }
    }
    changed=(actual_icl!=prev_icl || actual_fcc!=prev_fcc ||
             would_icl!=prev_wicl || would_fcc!=prev_wfcc ||
             full!=prev_full);
    if (!changed &&
        time_before(jiffies,last_compare+60*HZ))
        goto out;
    prev_icl=actual_icl;
    prev_fcc=actual_fcc;
    prev_wicl=would_icl;
    prev_wfcc=would_fcc;
    prev_full=full;
    last_compare=jiffies;
    dev_info(owner,
      "MGBATT SHADOW COMPARE would_icl=%u would_fcc=%u actual_icl=%d actual_fcc=%d match=%d reason=%s\n",
      would_icl,would_fcc,actual_icl,actual_fcc,
      would_icl==actual_icl && would_fcc==actual_fcc,reason);
out:
    mutex_unlock(&mgbatt_lock);
}
'''

def once(data,a,b,label):
    n=data.count(a)
    if n!=1: raise RuntimeError("P479 shadow3 %s drift count=%d" % (label,n))
    return data.replace(a,b,1)

def stage(root):
    sh=root/SH
    if not (sh/"mgbatt_shadow.c").exists():
        raise RuntimeError("P479 shadow3 requires original stage")
    header=sh/"mgbatt_shadow.h"
    h=header.read_text()
    h=once(h,"u32 chg_icl_cap, chg_fcc_cap;",
        "u32 chg_icl_cap, chg_fcc_cap;\n"
        "\tu32 full_soc, full_vcell, recharge_soc, recharge_vcell;",
        "policy full/recharge fields")
    h=once(h,"#endif\n",
        "void mgbatt_shadow_compare(struct device *owner,const char *type,\n"
        "       int bat,int chg,int soc,int vcell,int actual_icl,int actual_fcc,bool full);\n"
        "#endif\n",
        "observer-only API")
    header.write_text(h)
    dt=sh/"mgbatt_dt.c"
    s=dt.read_text()
    s=once(s,
      'mgbatt_read(battery,"battery,chg_charging_limit_current",&p->chg_fcc_cap) ||',
      'mgbatt_read(battery,"battery,chg_charging_limit_current",&p->chg_fcc_cap) ||\n'
      '    mgbatt_read(battery,"battery,full_condition_soc",&p->full_soc) ||\n'
      '    mgbatt_read(battery,"battery,full_condition_vcell",&p->full_vcell) ||\n'
      '    mgbatt_read(battery,"battery,recharge_condition_soc",&p->recharge_soc) ||\n'
      '    mgbatt_read(battery,"battery,recharge_condition_vcell",&p->recharge_vcell) ||',
      "four real live DT thresholds")
    s=once(s,
      "initial_icl!=1800 || initial_fcc!=2100)",
      "initial_icl!=1800 || initial_fcc!=2100 ||\n"
      "   p->full_soc!=93 || p->full_vcell!=4250 ||\n"
      "   p->recharge_soc!=98 || p->recharge_vcell!=4310)",
      "r02 full/recharge range")
    dt.write_text(s)
    observer=sh/"mgbatt_shadow.c"
    observer.write_text(observer.read_text()+COMPARE)
    src=root/SRC
    s=src.read_text()
    if MARK in s: raise RuntimeError("shadow3 duplicate")
    s=once(s,
      "    rc=p479_h4_apply(fg,icl,target);\n",
      "    rc=p479_h4_apply(fg,icl,target);\n",
      "h4 apply anchor")
    # Insert read-only compare only AFTER H0's real successful readbacks.
    s=once(s,
      "    if (target!=actual) {\n",
      "    mgbatt_shadow_compare(fg->dev,type,bat,chg,\n"
      "                          a52d_soc(fg),a52d_mv(fg),\n"
      "                          fg->p479_h4_applied_icl,\n"
      "                          fg->p479_h4_applied_fcc,\n"
      "                          fg->a52h0_full);\n"
      "    if (target!=actual) {\n",
      "after-success H4 compare")
    s=once(s,
      "/* P479_H4_AUTO_5V_SOLE_WRITER_V1",
      "/* "+MARK+" */\n/* P479_H4_AUTO_5V_SOLE_WRITER_V1",
      "shadow3 owner marker")
    src.write_text(s)
    check(root)

def check(root):
    sh=root/SH
    data="\n".join((sh/f).read_text() for f in
                   ("mgbatt_shadow.c","mgbatt_dt.c","mgbatt_shadow.h",
                    "mgbatt_write_gate.c"))
    s=(root/SRC).read_text()
    for needle in (MARK,"MGBATT SHADOW COMPARE would_icl=%u would_fcc=%u",
                   "mgbatt_shadow_compare(fg->dev,type,bat,chg,",
                   "battery,full_condition_vcell",
                   "battery,recharge_condition_vcell",
                   "p->full_soc!=93", "p->recharge_vcell!=4310",
                   "return -EPERM;"):
        if needle not in data+s:
            raise RuntimeError("P479 shadow3 contract missing "+needle)
    for forbidden in ("i2c_smbus_write_","regmap_write(","regmap_update_bits(",
                      "power_supply_register(","i2c_new_client_device("):
        if forbidden in data:
            raise RuntimeError("P479 shadow3 forbidden hardware operation "+forbidden)
    print("P479 MGBATT shadow3 SOURCE PASS: live r02 full/recharge thresholds, actual H4 comparison, zero new writes")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",required=True,type=Path)
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--report",type=Path)
    a=ap.parse_args()
    if not a.check_only:stage(a.root)
    else:check(a.root)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps({
          "phase":"P479_MGBATT_SHADOW3","hardware_writes":0,
          "full_soc":93,"full_vcell_mv":4250,
          "recharge_soc":98,"recharge_vcell_mv":4310,
          "exact_samsung_vote_engine":False,
          "reason":"Only a read-only live-DT observer, not the full framework",
          "runtime_verified":False},indent=2)+"\n")
if __name__=="__main__":main()
