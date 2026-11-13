// SPDX-License-Identifier: GPL-2.0-only
/* Existing P475 read-only MUIC bridge is the sole cable evidence.
 * No Type-C manager, AFC, QC, or PD-negotiated inference in this stage.
 * TG A52 r02 DTS:690-774. SEC_BATTERY_CABLE_USB=1, USB_CDP=5.
 */
#include <linux/string.h>
#include "mgbatt_shadow.h"
int mgbatt_cable_index(const char *type)
{
	if(!type) return -1;
	if(!strcmp(type,"SDP")) return 1;
	if(!strcmp(type,"CDP")) return 5;
	/* TA uses the live DT default ICL 1800/FCC 2100.
	 * Return index 2 only after checking that exact table entry
	 * matches the default in mgbatt_shadow.c.
	 */
	if(!strcmp(type,"DCP")) return 2;
	return -1;
}
