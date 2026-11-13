// SPDX-License-Identifier: GPL-2.0-only
/* P477 MGBATT SHADOW stage 1-2. Pure observer called by the EXISTING
 * H0/P449 worker, does not register any I2C client or power_supply.
 */
#include <linux/errno.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/mutex.h>
#include <linux/printk.h>
#include <linux/string.h>
#include "mgbatt_shadow.h"

static DEFINE_MUTEX(mgbatt_lock);
static bool attempted, ready;
static int last_dev1 = -999, last_index = -999;
static unsigned long last_report;
static struct mgbatt_policy policy;
void mgbatt_shadow_tick(struct device *owner, const char *type,
			int muic_dev1, int bat, int chg)
{
	int index, rc;
	u32 icl=0,fcc=0;
	const char *reason="UNKNOWN";
	bool report;
	if(!owner) return;
	mutex_lock(&mgbatt_lock);
	if(!attempted) {
		attempted=true;
		rc=mgbatt_parse_live_dt(&policy);
		if(rc) {
			dev_err(owner,"MGBATT SHADOW PROBE ok=0 rc=%d shadow=1\n",rc);
			goto out;
		}
		ready=true;
		dev_info(owner,"MGBATT SHADOW PROBE ok=1 shadow=1 owner=H0\n");
		dev_info(owner,"MGBATT SHADOW WRITE_BASELINE shadow_hw_writes=0 denied=%u\n",
			 mgbatt_write_denials());
	}
	if(!ready) goto out;
	index=mgbatt_cable_index(type);
	/* Real DCP default must be verified, not assumed from MUIC. */
	if(index==2 &&
	   (policy.cable[2].icl_ma!=1800 || policy.cable[2].fcc_ma!=2100))
		index=-1;
	report=(muic_dev1!=last_dev1 || index!=last_index ||
		time_after_eq(jiffies,last_report+60*HZ));
	if(!report) goto out;
	last_dev1=muic_dev1;
	last_index=index;
	last_report=jiffies;
	dev_info(owner,"MGBATT SHADOW CABLE src=muic dev1=0x%02x type=%s pd_valid=0\n",
		 muic_dev1<0?0xff:muic_dev1 & 0xff,
		 type?type:"UNKNOWN");
	mgbatt_policy_calculate(&policy,index,bat,chg,&icl,&fcc,&reason);
	dev_info(owner,"MGBATT SHADOW WOULD_SET cable=%s icl_ma=%u fcc_ma=%u float_mv=%u voters=%s\n",
		 type?type:"UNKNOWN",icl,fcc,policy.float_mv,reason);
	dev_info(owner,"MGBATT SHADOW WRITE_BASELINE shadow_hw_writes=0 denied=%u\n",
		 mgbatt_write_denials());
out:
	mutex_unlock(&mgbatt_lock);
}
