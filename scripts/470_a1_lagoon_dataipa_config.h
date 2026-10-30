/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * P470-A1: pinned Galaxy A52xq Lagoon 4.19 feature contract for 5.10
 * dataipa *external compile probe only*. Not a production Kconfig.
 *
 * Derived from micr0softstore/samsung_android_kernel_a52xq
 * 6bf351bdf18bdb228db79e66f14a7a9c0178e5d7:
 * arch/arm64/configs/a52xq_defconfig and vendor/a52xq_eur_open_defconfig.
 * Both set GSI_REGISTER_VERSION_2, IPA_WDI_UNIFIED_API, RMNET_IPA3,
 * RNDIS_IPA and explicitly disable IPA3_REGDUMP.
 *
 * Qualcomm's generic dataipa/config/dataipa.h incorrectly forces
 * IPA3_REGDUMP_IPA_4_5, which is NOT an IPA 4.7 register map. Never
 * include that donor header with this probe.
 */
#ifndef P470_A1_LAGOON_DATAIPA_CONFIG_H
#define P470_A1_LAGOON_DATAIPA_CONFIG_H
#define CONFIG_GSI 1
#define CONFIG_GSI_REGISTER_VERSION_2 1
#define CONFIG_RMNET_IPA3 1
#define CONFIG_RNDIS_IPA 1
#define CONFIG_IPA_WDI_UNIFIED_API 1
/* CONFIG_IPA3_REGDUMP is not set */
/* CONFIG_IPA3_APPS_REGDUMP is not set */
/* CONFIG_IPA3_REGDUMP_IPA_4_5 is not set */
#if defined(CONFIG_IPA3_REGDUMP) || defined(CONFIG_IPA3_APPS_REGDUMP) || defined(CONFIG_IPA3_REGDUMP_IPA_4_5)
#error "P470-A1: refusing wrong-layout IPA 4.5 register dump on Lagoon IPA 4.7"
#endif
#endif
