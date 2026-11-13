/* P477: read-only Samsung battery policy observer, NOT a second charger. */
#ifndef _MGBATT_SHADOW_H_
#define _MGBATT_SHADOW_H_
#include <linux/device.h>
#include <linux/of.h>
#include <linux/types.h>
#define MGBATT_MAX_CABLES 41
struct mgbatt_limit { u32 icl_ma, fcc_ma; };
struct mgbatt_policy {
	struct mgbatt_limit cable[MGBATT_MAX_CABLES];
	u32 float_mv, bat_block, bat_recover, chg_high, chg_recover;
	u32 chg_icl_cap, chg_fcc_cap;
	bool bat_hot, chg_hot;
};
int mgbatt_parse_live_dt(struct mgbatt_policy *policy);
int mgbatt_cable_index(const char *type);
void mgbatt_policy_calculate(struct mgbatt_policy *p, int index,
			   int bat_decic, int chg_decic,
			   u32 *icl_ma, u32 *fcc_ma, const char **reason);
int mgbatt_write_gate(unsigned int reg, unsigned int value);
unsigned int mgbatt_write_denials(void);
void mgbatt_shadow_tick(struct device *owner, const char *type,
			int muic_dev1, int bat_decic, int chg_decic);
#endif
