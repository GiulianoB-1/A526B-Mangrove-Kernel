/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef P472_A1_APR_H
#define P472_A1_APR_H
#include <linux/types.h>
struct p472_a1_packet {
 u8 service;
 u32 token;
 u32 opcode;
 const void *payload;
 size_t payload_len;
};
#endif
