// SPDX-License-Identifier: GPL-2.0-only
/* Read-only TG r02 base cable policy, swelling and charger temperature.
 * These would-set figures are observational, never hardware votes.
 * No dc_step_chg_* data is applied to conventional SM5714 charging.
 */
#include <linux/kernel.h>
#include "mgbatt_shadow.h"
void mgbatt_policy_calculate(struct mgbatt_policy *p, int index,
			    int bat, int chg, u32 *icl, u32 *fcc,
			    const char **reason)
{
	*icl=0;*fcc=0;*reason="DISCONNECTED_OR_UNTRUSTED";
	if(index<0 || index>=MGBATT_MAX_CABLES) return;
	if(bat<150 || bat>900 || chg< -200 || chg>900) {
		*reason="SENSOR_UNKNOWN";
		return;
	}
	if(bat>=(int)p->bat_block) p->bat_hot=true;
	if(p->bat_hot && bat<=(int)p->bat_recover) p->bat_hot=false;
	if(chg>=(int)p->chg_high) p->chg_hot=true;
	if(p->chg_hot && chg<=(int)p->chg_recover) p->chg_hot=false;
	*icl=p->cable[index].icl_ma;
	*fcc=p->cable[index].fcc_ma;
	*reason="TG_BASE_CABLE";
	if(p->chg_hot) {
		*icl=min(*icl,p->chg_icl_cap);
		*fcc=min(*fcc,p->chg_fcc_cap);
		*reason="TG_BASE_CHG_NTC";
	}
	if(p->bat_hot) {
		*fcc=min(*fcc,(u32)500);
		*reason="TG_BASE_SWELLING_HOLD";
	}
	/* No claim to have executed the full Samsung vote/age engine. */
}
