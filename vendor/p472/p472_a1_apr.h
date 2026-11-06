/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef P472_A1_APR_H
#define P472_A1_APR_H
#include <linux/types.h>
#include <linux/notifier.h>
#define P472_A1_SVC_AFE 0x04
#define P472_A1_SVC_ASM 0x07
#define P472_A1_SVC_ADM 0x08
#define P472_A1_SVC_LSM 0x0d
#define P472_A1_ADSP_DOWN 0
#define P472_A1_ADSP_UP 1

struct p472_a1_packet {
 u8 service;
 u16 src_port;
 u16 dest_port;
 u16 hdr_len;
 u16 pkt_len;
 u16 msg_type;
 u32 token;
 u32 opcode;
 const void *payload;
 size_t payload_len;
};
typedef int (*p472_a1_rx_fn)(const struct p472_a1_packet *packet,
                             void *priv);
int p472_a1_apr_register(u8 service, p472_a1_rx_fn cb, void *priv);
void p472_a1_apr_unregister(u8 service, p472_a1_rx_fn cb, void *priv);
int p472_a1_apr_send(u8 service, u16 src_port, u16 dest_port,
                    u32 token, u32 opcode, const void *payload,
                    size_t payload_len);
int p472_a1_adsp_notifier_register(struct notifier_block *nb);
int p472_a1_adsp_notifier_unregister(struct notifier_block *nb);
#endif
