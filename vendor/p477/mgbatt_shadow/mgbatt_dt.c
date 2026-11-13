// SPDX-License-Identifier: GPL-2.0-only
/* Source: TG @6bf351bd .../drivers/battery/common/sec_battery_dt.c:163-190.
 * 5.10 adaptation: bounded i < len and cable_number < 41; never bind TG.
 * Board-rev-02 DTS @6bf351bd :435-775; live FDT remains authority.
 */
#include <linux/errno.h>
#include <linux/of.h>
#include <linux/string.h>
#include "mgbatt_shadow.h"

static int mgbatt_read(struct device_node *np, const char *name, u32 *dst)
{
	if (!np || of_property_read_u32(np,name,dst))
		return -EINVAL;
	return 0;
}
int mgbatt_parse_live_dt(struct mgbatt_policy *p)
{
	struct device_node *battery, *info, *group;
	u32 initial_icl, initial_fcc, icl, fcc, number;
	int len, i, rc=-EINVAL;

	if (!p) return -EINVAL;
	battery=of_find_compatible_node(NULL,NULL,"samsung,sec-battery");
	if (!battery) return -ENODEV;
	/* TG r02 DTS:435 battery and :690 cable-info are SIBLINGS. */
	info=of_get_child_by_name(battery->parent,"cable-info");
	if (!info) goto out_battery;
	if (mgbatt_read(battery,"battery,chg_float_voltage",&p->float_mv) ||
	    mgbatt_read(battery,"battery,swelling_high_temp_block",&p->bat_block) ||
	    mgbatt_read(battery,"battery,swelling_high_temp_recov",&p->bat_recover) ||
	    mgbatt_read(battery,"battery,chg_high_temp",&p->chg_high) ||
	    mgbatt_read(battery,"battery,chg_high_temp_recovery",&p->chg_recover) ||
	    mgbatt_read(battery,"battery,chg_input_limit_current",&p->chg_icl_cap) ||
	    mgbatt_read(battery,"battery,chg_charging_limit_current",&p->chg_fcc_cap) ||
	    mgbatt_read(info,"default_input_current",&initial_icl) ||
	    mgbatt_read(info,"default_charging_current",&initial_fcc))
		goto out_info;
	/* Refuse inconsistent or unexpected live-DT hardware policy. */
	if(p->float_mv!=4380 || p->bat_block!=410 || p->bat_recover!=390 ||
	   p->chg_high!=550 || p->chg_recover!=480 ||
	   p->chg_icl_cap!=1000 || p->chg_fcc_cap!=1400 ||
	   initial_icl!=1800 || initial_fcc!=2100)
		goto out_info;
	for(i=0;i<MGBATT_MAX_CABLES;i++) {
		p->cable[i].icl_ma=initial_icl;
		p->cable[i].fcc_ma=initial_fcc;
	}
	for_each_child_of_node(info,group) {
		if (mgbatt_read(group,"input_current",&icl) ||
		    mgbatt_read(group,"charging_current",&fcc)) {
			of_node_put(group);
			goto out_info;
		}
		len=of_property_count_u32_elems(group,"cable_number");
		if(len<=0 || len>MGBATT_MAX_CABLES) {
			of_node_put(group);
			goto out_info;
		}
		/* TG sec_battery_dt.c:185 had i <= len (one-past-end).
		 * Only 0 <= i < len, and validate each array index.
		 */
		for(i=0;i<len;i++) {
			if(of_property_read_u32_index(group,"cable_number",
						       i,&number) ||
			   number>=MGBATT_MAX_CABLES) {
				of_node_put(group);
				goto out_info;
			}
			p->cable[number].icl_ma=icl;
			p->cable[number].fcc_ma=fcc;
		}
	}
	rc=0;
out_info:
	of_node_put(info);
out_battery:
	of_node_put(battery);
	return rc;
}
