// SPDX-License-Identifier: GPL-2.0-only
/* All new shadow hardware setters MUST call this gate; it never writes.
 * The preexisting FG SRAM 0x8c selector remains exclusively in FG owner.
 * TG sm5714-private.h:119-129; FG @6bf351bd:147-170.
 */
#include <linux/atomic.h>
#include <linux/errno.h>
#include "mgbatt_shadow.h"
static atomic_t mgbatt_denied=ATOMIC_INIT(0);
int mgbatt_write_gate(unsigned int reg, unsigned int val)
{
	(void)reg;(void)val;
	atomic_inc(&mgbatt_denied);
	return -EPERM;
}
unsigned int mgbatt_write_denials(void)
{
	return (unsigned int)atomic_read(&mgbatt_denied);
}
