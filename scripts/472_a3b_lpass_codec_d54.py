#!/usr/bin/env python3
"""P472 A3b: pinned Samsung 5.4 API donor for REAL audio components.

TG A52 hardware source @6bf351bdf18bdb228db79e66f14a7a9c0178e5d7
Samsung SM7325 5.4.191 API donor @c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4

NO machine driver, TAS256x, WSA macro, WCD937x, WSA883x, FSA4480.
No invented device, no fake errno or probe success. Unique source anchors.
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

TG_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
D54_SHA = "c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4"
ROOT = Path("drivers/soc/qcom/p472_tg_audio")
MARK = "P472_A3B_LPASS_CODEC_REAL_D54_V1"
B1 = (
    "soc/pinctrl-lpi.c", "soc/pinctrl-wcd.c",
    "asoc/codecs/msm-cdc-pinctrl.c",
    "asoc/codecs/msm-cdc-supply.c",
    "asoc/codecs/audio-ext-clk-up.c",
)
B2 = tuple("asoc/codecs/bolero/" + p for p in (
    "bolero-cdc.c", "bolero-cdc-utils.c",
    "bolero-cdc-regmap.c", "bolero-cdc-tables.c",
    "bolero-clk-rsc.c", "rx-macro.c", "tx-macro.c", "va-macro.c",
))
B3 = (
    "soc/regmap-swr.c", "soc/soundwire.c", "soc/swr-mstr-ctrl.c",
    "soc/swr-wcd-ctrl.c",
    "asoc/codecs/wcd938x/wcd938x.c",
    "asoc/codecs/wcd938x/wcd938x-regmap.c",
    "asoc/codecs/wcd938x/wcd938x-tables.c",
    "asoc/codecs/wcd938x/wcd938x-mbhc.c",
    "asoc/codecs/wcd938x/wcd938x-slave.c",
    "asoc/codecs/wcd-mbhc-v2.c", "asoc/codecs/wcd-mbhc-adc.c",
    "asoc/codecs/wcd-clsh.c", "asoc/codecs/wcd-irq.c",
    "asoc/codecs/wcd9xxx-soc-init.c",
    "asoc/codecs/wcd-dsp-utils.c", "asoc/codecs/wcd-dsp-mgr.c",
    "asoc/codecs/wcdcal-hwdep.c",
)
# Names below map exactly to REAL 5.4 driver callbacks.
PROBES = {
    "soc/pinctrl-lpi.c": ("lpi_pinctrl_probe","LPI_PINCTRL","platform"),
    "soc/pinctrl-wcd.c": ("wcd_pinctrl_probe","WCD_PINCTRL","platform"),
    "asoc/codecs/msm-cdc-pinctrl.c":
        ("msm_cdc_pinctrl_probe","CDC_PINCTRL","platform"),
    "asoc/codecs/audio-ext-clk-up.c":
        ("audio_ref_clk_probe","LPASS_AUDIO_CLK","platform"),
    "asoc/codecs/bolero/bolero-cdc.c":
        ("bolero_probe","BOLERO","platform"),
    "asoc/codecs/bolero/bolero-clk-rsc.c":
        ("bolero_clk_rsc_probe","BOLERO_CLK","platform"),
    "asoc/codecs/bolero/rx-macro.c":
        ("rx_macro_probe","RX_MACRO","platform"),
    "asoc/codecs/bolero/tx-macro.c":
        ("tx_macro_probe","TX_MACRO","platform"),
    "asoc/codecs/bolero/va-macro.c":
        ("va_macro_probe","VA_MACRO","platform"),
    "soc/swr-mstr-ctrl.c": ("swrm_probe","SWR_MASTER","platform"),
    "soc/swr-wcd-ctrl.c": ("swrm_probe","SWR_WCD_MASTER","platform"),
    "asoc/codecs/wcd938x/wcd938x.c":
        ("wcd938x_probe","WCD938X","platform"),
    "asoc/codecs/wcd938x/wcd938x-slave.c":
        ("wcd938x_swr_probe","WCD938X_SWR_SLAVE","swr"),
}
SUB_MAKE = {
    "soc/Makefile":
        "obj-$(CONFIG_P472_A3B_B1) += pinctrl-lpi.o pinctrl-wcd.o\n"
        "obj-$(CONFIG_P472_A3B_B3) += regmap-swr.o soundwire.o swr-mstr-ctrl.o swr-wcd-ctrl.o\n",
    "asoc/Makefile":
        "obj-y += codecs/\n",
    "asoc/codecs/Makefile":
        "obj-$(CONFIG_P472_A3B_B1) += a3b-cdc-pinctrl-init.o msm-cdc-pinctrl.o msm-cdc-supply.o audio-ext-clk-up.o\n"
        "obj-$(CONFIG_P472_A3B_B2) += bolero/\n"
        "obj-$(CONFIG_P472_A3B_B3) += wcd938x/ wcd-mbhc-v2.o wcd-mbhc-adc.o wcd-clsh.o wcd-irq.o wcd9xxx-soc-init.o wcd-dsp-utils.o wcd-dsp-mgr.o wcdcal-hwdep.o\n",
    "asoc/codecs/bolero/Makefile":
        "obj-y += bolero-cdc.o bolero-cdc-utils.o bolero-cdc-regmap.o bolero-cdc-tables.o bolero-clk-rsc.o rx-macro.o tx-macro.o va-macro.o\n",
    "asoc/codecs/wcd938x/Makefile":
        "obj-y += wcd938x.o wcd938x-regmap.o wcd938x-tables.o wcd938x-mbhc.o wcd938x-slave.o\n",
}
KCONFIG = '''
config P472_A3B_B1
    bool "P472 A3b B1 audio clock voters and WCD/LPI pinctrl"
    depends on P472_A3A_Q6 && SND_SOC
    default n

config P472_A3B_B2
    bool "P472 A3b B2 Bolero RX/TX/VA codec macros, no WSA"
    depends on P472_A3B_B1
    default n

config P472_A3B_B3
    bool "P472 A3b B3 SoundWire masters/slaves and WCD938x MBHC"
    depends on P472_A3B_B2
    default n
'''
ROOT_MAKE = '''# P472_A3B_LPASS_CODEC_REAL_D54_V1
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include/uapi
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include/uapi/audio
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include/uapi
subdir-ccflags-$(CONFIG_P472_A3B_B1) += -DCONFIG_PINCTRL_WCD=1 -DCONFIG_PINCTRL_LPI=1 -DCONFIG_MSM_CDC_PINCTRL=1
subdir-ccflags-$(CONFIG_P472_A3B_B2) += -DCONFIG_SND_SOC_BOLERO=1 -DCONFIG_RX_MACRO=1 -DCONFIG_TX_MACRO=1 -DCONFIG_VA_MACRO=1
subdir-ccflags-$(CONFIG_P472_A3B_B3) += -DCONFIG_SOUNDWIRE=1 -DCONFIG_SOUNDWIRE_WCD_CTRL=1 -DCONFIG_SOUNDWIRE_MSTR_CTRL=1 -DCONFIG_SND_SOC_WCD938X=1 -DCONFIG_SND_SOC_WCD938X_SLAVE=1 -DCONFIG_WCD9XXX_CODEC_CORE_V2=1 -DCONFIG_SND_SOC_WCD9XXX_V2=1 -DCONFIG_SND_SOC_WCD_MBHC_ADC=1 -DCONFIG_SND_SOC_WCD_MBHC=1 -DCONFIG_WCD9XXX_CODEC_CORE=1
obj-y += soc/ asoc/
'''

CDC_INIT_SOURCE = "// SPDX-License-Identifier: GPL-2.0-only\n/* P477B: register the real CDC pinctrl before codec device_initcalls.\n * No legacy SLIMbus/I2C WCD9xxx IRQ or core is registered.\n */\n#include <linux/init.h>\n#include <linux/printk.h>\n#include <asoc/msm-cdc-pinctrl.h>\nstatic int __init p472_a3b_cdc_pinctrl_init(void)\n{\n\tint rc = msm_cdc_pinctrl_drv_init();\n\n\tpr_info(\"P472 A3b CDC_PINCTRL register rc=%d\\n\", rc);\n\treturn rc;\n}\nsubsys_initcall(p472_a3b_cdc_pinctrl_init);\n"

def one(s,a,b,label):
    n=s.count(a)
    if n!=1:
        raise RuntimeError(f"P472 A3b {label} anchor count {n}")
    return s.replace(a,b,1)

def add_probe_logger(rel,source):
    fn,part,kind=PROBES[rel]
    device_type="struct swr_device" if kind=="swr" else "struct platform_device"
    newfn="p472_a3b_logged_probe"
    probe=re.compile(r"(?m)^(\s*\.probe\s*=\s*)"+re.escape(fn)+r"(\s*,)")
    matches=list(probe.finditer(source))
    if len(matches)!=1:
        raise RuntimeError("P472 A3b real probe callback drift: "+rel)
    # Insert immediately before the actual driver object. Wrapper delegates
    # to the real function first, logs its returned errno, then returns it.
    driver=("static struct swr_driver" if kind=="swr"
            else "static struct platform_driver")
    if source.count(driver)!=1:
        raise RuntimeError("P472 A3b driver-object anchor drift: "+rel)
    wrapper=(f"static int {newfn}({device_type} *pdev)\n"
             "{\n"
             f"\tint rc={fn}(pdev);\n"
             f'\tdev_info(&pdev->dev,"P472 A3b PART {part} probe rc=%d\\n",rc);\n'
             "\treturn rc;\n"
             "}\n")
    source=one(source,driver,wrapper+driver,rel+" logger insertion")
    source,n=probe.subn(lambda m:m.group(1)+newfn+m.group(2),source)
    if n!=1:raise RuntimeError("P472 A3b callback replacement drift")
    return source

def add_enumeration(rel,src):
    # Count actual SWR status bits read from live controller registers,
    # not the DT-declared number of devices.
    if rel!="soc/swr-mstr-ctrl.c":
        return src
    anchor="\treturn 0;\nerr_mstr_init_fail:"
    injection=r'''
    /* P472 A3b: hardware-observed slave states, not DT population. */
    {
        u32 status = swr_master_read(swrm,SWRM_MCP_SLV_STATUS);
        u32 n = 0, k;
        for(k=1;k<=swrm->master.num_dev;k++) {
            u32 live=(status>>(k*2))&SWRM_MCP_SLV_STATUS_MASK;
            if(live==1 || live==2)n++;
        }
        dev_info(&pdev->dev,
          "P472 A3b SWR %s slaves=%u enumerated\n",
          dev_name(&pdev->dev),n);
    }
'''
    return one(src,anchor,injection+"\treturn 0;\nerr_mstr_init_fail:",
               "SWR hardware slave count")

def adapt_510_api(rel,data):
    """Pin exact 5.4->ACK 5.10 API conversions, reject donor drift.

    Android Common Kernel android12-5.10:
      include/sound/soc-component.h:340 has snd_soc_component_read()
      include/linux/pm_qos.h:26,61,147-163 has CPU latency QoS API.
    Donor @c4cb0a97:
      bolero-cdc.c:1211-1214 reads two real codec ID registers.
      swr-mstr-ctrl.c:2867-2869 registers CPU DMA latency request.
      swr-mstr-ctrl.c:3035,3071 removes request; :3786,3822 updates.
    """
    if rel == "asoc/codecs/bolero/bolero-cdc.c":
        # Identical read return type/register access. No fake codec IDs.
        old="snd_soc_component_read32("
        if data.count(old) != 2 or "snd_soc_component_read(" in data:
            raise RuntimeError("P472 A3b Bolero ASoC read API donor drift")
        data=data.replace(old,"snd_soc_component_read(")
    elif rel in (
        "asoc/codecs/bolero/rx-macro.c",
        "asoc/codecs/bolero/tx-macro.c",
        "asoc/codecs/bolero/va-macro.c",
    ):
        # Pinned donor (Samsung SM7325 @c4cb0a97):
        # RX macro: rx-macro.c:1029-3384, 38 32-bit register reads
        # TX macro: tx-macro.c:556-1266, 11 reads
        # VA macro: va-macro.c:854-1334, 9 reads
        # ACK 5.10 include/sound/soc-component.h:340-341:
        # snd_soc_component_read() returns unsigned int, same real I/O.
        old="snd_soc_component_read32("
        expected={
            "asoc/codecs/bolero/rx-macro.c":38,
            "asoc/codecs/bolero/tx-macro.c":11,
            "asoc/codecs/bolero/va-macro.c":9,
        }[rel]
        if data.count(old)!=expected:
            raise RuntimeError("P472 A3b macro read32 donor drift: "+rel)
        data=data.replace(old,"snd_soc_component_read(")
        if rel=="asoc/codecs/bolero/rx-macro.c":
            # In optional impedance sensing the 5.4 component read uses
            # a three-argument errno-returning API. Do not convert this
            # to the 5.10 unsigned-value API and silently lose errors.
            # ACK 5.10 soc-component.h:202 exposes the actual regmap.
            old_imp="ret = snd_soc_component_read(component, reg, &val);"
            new_imp=(
                "if (!component->regmap)\n"
                "\t\treturn -ENODEV;\n"
                "\tret = regmap_read(component->regmap, reg, &val);"
            )
            if data.count(old_imp)!=1:
                raise RuntimeError("P472 A3b RX optional impedance read ABI drift")
            data=data.replace(old_imp,new_imp,1)
            inc="#include <linux/pm_runtime.h>"
            if data.count(inc)!=1:
                raise RuntimeError("P472 A3b RX regmap include anchor drift")
            data=data.replace(inc,inc+"\n#include <linux/regmap.h>",1)
            # The actual RX mute implementation runs on playback; 5.10
            # include/sound/soc-dai.h:246-250 uses .mute_stream
            # with an additional stream direction, not .digital_mute.
            old_decl="static int rx_macro_digital_mute(struct snd_soc_dai *dai, int mute);"
            new_decl="static int rx_macro_digital_mute(struct snd_soc_dai *dai, int mute, int stream);"
            old_cb="\t.digital_mute = rx_macro_digital_mute,"
            new_cb="\t.mute_stream = rx_macro_digital_mute,"
            old_def="static int rx_macro_digital_mute(struct snd_soc_dai *dai, int mute)\n{"
            new_def="static int rx_macro_digital_mute(struct snd_soc_dai *dai, int mute, int stream)\n{"
            for before,after in ((old_decl,new_decl),
                                 (old_cb,new_cb),(old_def,new_def)):
                if data.count(before)!=1:
                    raise RuntimeError("P472 A3b RX mute ABI donor drift: "+before)
                data=data.replace(before,after,1)
            old_body="\tif (mute)\n\t\treturn 0;"
            new_body=("\t/* Only playback has RX DAI mute semantics. */\n"
                      "\tif (stream != SNDRV_PCM_STREAM_PLAYBACK)\n"
                      "\t\treturn -EINVAL;\n"
                      "\tif (mute)\n\t\treturn 0;")
            if data.count(old_body)!=1:
                raise RuntimeError("P472 A3b RX mute body donor drift")
            data=data.replace(old_body,new_body,1)
    elif rel in (
        "asoc/codecs/wcd938x/wcd938x.c",
        "asoc/codecs/wcd938x/wcd938x-mbhc.c",
    ):
        # Exact 5.4 WCD938x register reads; ACK 5.10 returns the
        # same unsigned int via snd_soc_component_read(). Do not
        # replace these hardware reads or synthesize success values.
        expected={
            "asoc/codecs/wcd938x/wcd938x.c":10,
            "asoc/codecs/wcd938x/wcd938x-mbhc.c":13,
        }[rel]
        old="snd_soc_component_read32("
        if data.count(old)!=expected or "snd_soc_component_read(" in data:
            raise RuntimeError("P472 A3b WCD938x read32 donor drift: "+rel)
        data=data.replace(old,"snd_soc_component_read(")
    elif rel == "soc/pinctrl-lpi.c":
        # TG 4.19 and A52 r02 specify qcom,num-gpios=15.
        old=(
            '\tret = of_property_read_u32(dev->of_node, "qcom,gpios-count", &npins);\n'
            '\tif (ret < 0)\n\t\treturn ret;'
        )
        new=(
            '\t{\n'
            '\t\tconst char *used = "qcom,num-gpios";\n'
            '\t\tret = of_property_read_u32(dev->of_node, "qcom,num-gpios", &npins);\n'
            '\t\tif (ret && !of_find_property(dev->of_node, "qcom,num-gpios", NULL)) {\n'
            '\t\t\tused = "qcom,gpios-count";\n'
            '\t\t\tret = of_property_read_u32(dev->of_node, "qcom,gpios-count", &npins);\n'
            '\t\t}\n'
            '\t\tdev_info(dev, "P472 A3b LPI_GPIO_PROP %s count=%u rc=%d\\n",\n'
            '\t\t\t used, ret ? 0 : npins, ret);\n'
            '\t\tif (ret < 0)\n\t\t\treturn ret;\n'
            '\t}'
        )
        if data.count(old)!=1:
            raise RuntimeError("P477B LPI GPIO property donor drift")
        data=data.replace(old,new,1)
    elif rel == "soc/pinctrl-wcd.c":
        # The TG WCD pinctrl provider uses the same A52 r02 key.
        old=(
            '\tret = of_property_read_u32(dev->of_node, "qcom,gpios-count", &npins);\n'
            '\tif (ret) {\n'
            '\t\tdev_err(dev, "%s: Looking up %s property in node %s failed\\n",\n'
            '\t\t\t__func__, "qcom,gpios-count", dev->of_node->full_name);\n'
            '\t\tret = -EINVAL;\n'
            '\t\tgoto err_priv_alloc;\n'
            '\t}'
        )
        new=(
            '\t{\n'
            '\t\tconst char *used = "qcom,num-gpios";\n'
            '\t\tret = of_property_read_u32(dev->of_node, "qcom,num-gpios", &npins);\n'
            '\t\tif (ret && !of_find_property(dev->of_node, "qcom,num-gpios", NULL)) {\n'
            '\t\t\tused = "qcom,gpios-count";\n'
            '\t\t\tret = of_property_read_u32(dev->of_node, "qcom,gpios-count", &npins);\n'
            '\t\t}\n'
            '\t\tdev_info(dev, "P472 A3b WCD_GPIO_PROP %s count=%u rc=%d\\n",\n'
            '\t\t\t used, ret ? 0 : npins, ret);\n'
            '\t\tif (ret) {\n'
            '\t\t\tdev_err(dev, "%s: Looking up %s in %s failed\\n",\n'
            '\t\t\t\t__func__, used, dev->of_node->full_name);\n'
            '\t\t\tret = -EINVAL;\n'
            '\t\t\tgoto err_priv_alloc;\n'
            '\t\t}\n'
            '\t}'
        )
        if data.count(old)!=1:
            raise RuntimeError("P477B WCD GPIO property donor drift")
        data=data.replace(old,new,1)
    elif rel == "soc/swr-wcd-ctrl.c":
        # The 5.4 donor has two distinct real SWR master drivers,
        # qcom,swr-wcd and qcom,swr-mstr, both exporting the same
        # swrm_wcd_notify symbol. Preserve this WCD controller's
        # implementation with a private unique export; the public
        # ABI below routes by the actual OF compatible.
        if (data.count("swrm_wcd_notify(")!=2 or
                data.count("EXPORT_SYMBOL(swrm_wcd_notify);")!=1 or
                data.count('"qcom,swr-wcd"')!=1):
            raise RuntimeError("P472 A3b WCD SoundWire symbol donor drift")
        data=data.replace("swrm_wcd_notify(","swrm_wcd_notify_wcd(")
        data=data.replace("EXPORT_SYMBOL(swrm_wcd_notify);",
                          "EXPORT_SYMBOL(swrm_wcd_notify_wcd);",1)
        old=(
            '\tdefault:\n'
            '\t\tdev_err(swrm->dev, "%s: swr master unknown id %d\\n",\n'
            '\t\t\t__func__, id);\n'
            '\t\tbreak;'
        )
        if data.count(old)!=1:
            raise RuntimeError("P472 A3b WCD SoundWire unsupported command drift")
        data=data.replace(old,old.replace('\t\tbreak;',
                  '\t\tret = -EOPNOTSUPP;\n\t\tbreak;'),1)
    elif rel == "soc/swr-mstr-ctrl.c":
        # Keep the canonical SWR notification ABI for the LPASS
        # master and dispatch WCD child devices to their separate
        # real implementation, never cast one controller's drvdata
        # to the other's incompatible struct.
        symbol="int swrm_wcd_notify(struct platform_device *pdev, u32 id, void *data)"
        if (data.count(symbol)!=1 or
                data.count("EXPORT_SYMBOL(swrm_wcd_notify);")!=1 or
                data.count('"qcom,swr-mstr"')!=1):
            raise RuntimeError("P472 A3b LPASS SoundWire notification ABI drift")
        start=data.index(symbol)
        end=data.index("EXPORT_SYMBOL(swrm_wcd_notify);",start)
        part=data[start:end]
        old="\tswrm = platform_get_drvdata(pdev);"
        dispatch=(
            '\t/* Both real 5.4 controllers exist; route by real DT compatible. */\n'
            '\tif (of_device_is_compatible(pdev->dev.of_node, "qcom,swr-wcd"))\n'
            '\t\treturn swrm_wcd_notify_wcd(pdev, id, data);\n'
            '\tif (!of_device_is_compatible(pdev->dev.of_node, "qcom,swr-mstr")) {\n'
            '\t\tdev_err(&pdev->dev, "P472 A3b SWR unsupported controller\\n");\n'
            '\t\treturn -ENODEV;\n'
            '\t}\n'
        )
        if part.count(old)!=1 or part.count("if (!pdev) {")!=1:
            raise RuntimeError("P472 A3b LPASS SWR fail-closed dispatch drift")
        part=part.replace(old,dispatch+old,1)
        data=data[:start]+part+data[end:]
        # The donor used the same driver.name for two different
        # compatibles. Ensure platform bus name matching cannot
        # capture the other controller before the OF match.
        if data.count(".name = SWR_WCD_NAME,")!=1:
            raise RuntimeError("P472 A3b LPASS SWR platform name drift")
        data=data.replace(".name = SWR_WCD_NAME,", '.name = "swr-mstr",',1)
        old=(
            '\tdefault:\n'
            '\t\tdev_err(swrm->dev, "%s: swr master unknown id %d\\n",\n'
            '\t\t\t__func__, id);\n'
            '\t\tbreak;'
        )
        if data.count(old)!=1:
            raise RuntimeError("P472 A3b LPASS SoundWire unsupported command drift")
        data=data.replace(old,old.replace('\t\tbreak;',
                  '\t\tret = -EOPNOTSUPP;\n\t\tbreak;'),1)
    elif rel == "asoc/codecs/wcd-dsp-mgr.c":
        # ACK 5.10 still implements arch_setup_dma_ops() on arm64,
        # declared by linux/dma-map-ops.h rather than the older
        # linux/dma-mapping.h included by the pinned Samsung donor.
        # Preserve the exact hardware DMA configuration and its args.
        old="#include <linux/dma-mapping.h>"
        if data.count(old)!=1 or data.count(
                "arch_setup_dma_ops(wdsp->mdev, 0, 0, NULL, 0);")!=1:
            raise RuntimeError("P472 A3b WCD DSP manager DMA API donor drift")
        data=data.replace(old,old+"\n#include <linux/dma-map-ops.h>",1)
    elif rel == "asoc/codecs/wcd-mbhc-adc.c":
        # SM7325 ADC code uses no symbols from legacy pdata.h. That
        # header imports linux/slimbus/slimbus.h when WDSP codec-core
        # is enabled. Keep the SoundWire ADC and its register I/O,
        # without importing the legacy SLIMbus data structure.
        old="#include <asoc/pdata.h>\n"
        if data.count(old)!=1:
            raise RuntimeError("P472 A3b ADC unused legacy pdata header drift")
        data=data.replace(old,"",1)
    elif rel == "asoc/codecs/wcd-mbhc-v2.c":
        # FSA4480 is intentionally excluded from A3b (no actual
        # FSA driver). The donor fallback header returns false
        # success. Forbid entering that path when DT requests
        # Type-C analog audio instead of silently accepting it.
        old=(
            "\tif (mbhc_cfg->enable_usbc_analog == 0 || rc != 0) {"
        )
        new=(
            "\tif (mbhc_cfg->enable_usbc_analog &&\n"
            "\t    !IS_ENABLED(CONFIG_QCOM_FSA4480_I2C)) {\n"
            "\t\tdev_err(card->dev,\n"
            "\t\t\t\"P472 A3b FSA4480 unavailable: Type-C analog rejected\\n\");\n"
            "\t\treturn -EOPNOTSUPP;\n"
            "\t}\n"
            + old
        )
        if data.count(old)!=1:
            raise RuntimeError("P472 A3b FSA4480 analog fail-closed gate drift")
        data=data.replace(old,new,1)
    elif rel == "asoc/codecs/msm-cdc-pinctrl.c":
        # SM7325 5.4 uses downstream msm_gpio_mpm_wake_set() with a
        # private TLMM wake register API. ACK 5.10 pinctrl-msm.c has
        # gpio IRQ wake propagation via irq_chip::irq_set_wake.
        # This is a real IRQ core operation and propagates any errors,
        # not a GPIO/MPM wake success stub or a private header copy.
        old_include="#include <linux/pinctrl/qcom-pinctrl.h>"
        new_include=(
            "#include <linux/pinctrl/consumer.h>\n"
            "#include <linux/interrupt.h>\n"
            "#include <linux/gpio/driver.h>\n"
            "#include <linux/string.h>"
        )
        if data.count(old_include)!=1:
            raise RuntimeError("P472 A3b CDC private 5.4 TLMM header drift")
        data=data.replace(old_include,new_include,1)
        old_call=(
            "\t\t\tret = msm_gpio_mpm_wake_set(gpio_data->tlmm_gpio[i],\n"
            "\t\t\t\t\t\t    enable);"
        )
        new_call=(
            "\t\t\t/* The r02 entries are TLMM pin offsets, not global GPIOs. */\n"
            "\t\t\tstruct gpio_chip *tlmm = gpiochip_find(NULL, p478_match_tlmm_gpiochip);\n"
            "\t\t\tint pin = gpio_data->tlmm_gpio[i];\n"
            "\t\t\tint gpio = -1, gpio_irq = -1;\n"
            "\t\t\tif (!tlmm || tlmm->base < 0) {\n"
            "\t\t\t\tret = -ENODEV;\n"
            "\t\t\t} else if (pin < 0 || pin >= tlmm->ngpio ||\n"
            "\t\t\t\t   !gpiochip_line_is_valid(tlmm, pin)) {\n"
            "\t\t\t\tret = -EINVAL;\n"
            "\t\t\t} else {\n"
            "\t\t\t\tgpio = tlmm->base + pin;\n"
            "\t\t\t\tgpio_irq = gpio_to_irq(gpio);\n"
            "\t\t\t\tret = gpio_irq < 0 ? gpio_irq :\n"
            "\t\t\t\t\tirq_set_irq_wake(gpio_irq, enable);\n"
            "\t\t\t}\n"
            "\t\t\tpr_info(\"P472 A3b CDC_TLMM_WAKE pin=%d gpio=%d irq=%d en=%d rc=%d\\n\",\n"
            "\t\t\t\tpin, gpio, gpio_irq, enable, ret);\n"
            "\t\t\tif (ret < 0)\n"
            "\t\t\t\tgoto exit;";

        )
        if data.count(old_call)!=1:
            raise RuntimeError("P472 A3b CDC downstream GPIO wake call drift")
        data=data.replace(old_call,new_call,1)
        # Find only TLMM at the verified Mangrove 0xF100000
        # node. Never assume a fixed global GPIO base.
        anchor="\nstruct msm_cdc_pinctrl_info {"
        matcher=(
            '\n/* P478: match the live A52 TLMM GPIO chip, not LPASS or PMIC. */\n'
            'static int p478_match_tlmm_gpiochip(struct gpio_chip *chip, void *unused)\n'
            '{\n'
            '\tconst struct device_node *np = chip->of_node;\n'
            '\tconst char *base;\n'
            '\t(void)unused;\n'
            '\tif (!np && chip->parent)\n'
            '\t\tnp = chip->parent->of_node;\n'
            '\tif (!np || !np->full_name)\n'
            '\t\treturn 0;\n'
            "\tbase = strrchr(np->full_name, '/');\n"
            "\tbase = base ? base + 1 : np->full_name;\n"
            '\treturn !strcmp(base, "pinctrl@f100000");\n'
            '}\n'
        )
        if data.count(anchor)!=1:
            raise RuntimeError("P478 CDC TLMM gpio_chip declaration anchor drift")
        data=data.replace(anchor,"\n"+matcher+anchor,1)

        # r02 GPIO wake property. Legacy key is a fallback only if absent.
        old_tlmm=(
            'cdc_tlmm_gpio:\n'
            '\tcount = of_property_count_u32_elems(pdev->dev.of_node, "qcom,tlmm-pins");\n'
            '\tif (count <= 0)\n'
            '\t\tgoto cdc_rst;\n'
            '\tif (!of_property_read_u32_array(pdev->dev.of_node, "qcom,tlmm-pins",\n'
        )
        new_tlmm=(
            'cdc_tlmm_gpio:\n'
            '\t{\n'
            '\t\tconst char *used = "qcom,tlmm-gpio";\n'
            '\t\tcount = of_property_count_u32_elems(pdev->dev.of_node, "qcom,tlmm-gpio");\n'
            '\t\tif (count <= 0 &&\n'
            '\t\t    !of_find_property(pdev->dev.of_node, "qcom,tlmm-gpio", NULL)) {\n'
            '\t\t\tused = "qcom,tlmm-pins";\n'
            '\t\t\tcount = of_property_count_u32_elems(pdev->dev.of_node, "qcom,tlmm-pins");\n'
            '\t\t}\n'
            '\t\tdev_info(&pdev->dev, "P472 A3b CDC_TLMM_PROP %s count=%d\\n", used, count);\n'
            '\t\tif (count <= 0)\n'
            '\t\t\tgoto cdc_rst;\n'
            '\t\tif (count > ARRAY_SIZE(tlmm_gpio)) {\n'
            '\t\t\tdev_err(&pdev->dev, "CDC TLMM count %d exceeds %zu\\n",\n'
            '\t\t\t\tcount, ARRAY_SIZE(tlmm_gpio));\n'
            '\t\t\tret = -EINVAL;\n'
            '\t\t\tgoto err_lookup_state;\n'
            '\t\t}\n'
            '\t\tif (!of_property_read_u32_array(pdev->dev.of_node, used,\n'
        )
        old_end='\t\tgpio_data->count = count;\n\t}\n\ncdc_rst:'
        new_end='\t\tgpio_data->count = count;\n\t\t}\n\t}\n\ncdc_rst:'
        if data.count(old_tlmm)!=1 or data.count(old_end)!=1:
            raise RuntimeError("P477B CDC TLMM property donor drift")
        data=data.replace(old_tlmm,new_tlmm,1)
        data=data.replace(old_end,new_end,1)
    if rel == "soc/pinctrl-lpi.c":
        # /sys/kernel/debug/gpio must NOT trigger any LPASS register
        # read. The native DBG_SHOW path was reading every pin.
        # Render explicitly cached, non-hardware state instead.
        if data.count("static void lpi_gpio_dbg_show_one(")!=1:
            raise RuntimeError("P478 LPI debugfs donor layout drift")
        i=data.index("static void lpi_gpio_dbg_show_one(")
        j=data.index("\n#else\n#define lpi_gpio_dbg_show NULL",i)
        original=data[i:j]
        if ("lpi_gpio_read(pad, LPI_GPIO_REG_DIR_CTL)" not in original or
            "lpi_gpio_read(pad, LPI_GPIO_REG_VAL_CTL)" not in original):
            raise RuntimeError("P478 LPI original debugfs MMIO path drift")
        safe=(
            'static void lpi_gpio_dbg_show(struct seq_file *s, struct gpio_chip *chip)\n'
            '{\n'
            '\t/* P478: no LPASS MMIO from a debugfs read, including SSR. */\n'
            '\tseq_printf(s, "P478 LPI gpio debugfs: %u pins; register reads disabled (ADSP/clock safety)\\n",\n'
            '\t\t   chip->ngpio);\n'
            '}\n'
        )
        data=data[:i]+safe+data[j:]
        unused=(
            'static unsigned int lpi_regval_to_drive(u32 val)\n'
            '{\n'
            '\treturn (val + 1) * 2;\n'
            '}\n\n'
        )
        if data.count(unused)!=1:
            raise RuntimeError("P478 unused LPI debugfs-only drive helper drift")
        data=data.replace(unused,"",1)
        # The native helper calls pm_runtime_get_sync() without
        # checking its return. Never access LPASS TLMM without
        # successful runtime resume and a real core clock vote.
        old='pm_runtime_get_sync(lpi_dev);'
        if data.count(old)!=2:
            raise RuntimeError("P478 LPI runtime PM accessor drift")
        data=data.replace(old,
            'ret = pm_runtime_resume_and_get(lpi_dev);\n'
            '\tif (ret < 0)\n\t\treturn ret;',2)
        # The original returns success for ADSP-down paths. This is
        # unsafe because pinconf callers then use register value 0.
        old='if (!lpi_dev_up) {'
        # Two MMIO helper guards plus one original SSR recovery guard.
        if data.count(old)!=3:
            raise RuntimeError("P478 LPI ADSP guard count drift")
        data=data.replace('return 0;\n\t}\n\tret = pm_runtime_resume_and_get(lpi_dev);',
                          'return -EHOSTDOWN;\n\t}\n\tret = pm_runtime_resume_and_get(lpi_dev);',1)
        data=data.replace('if (!lpi_dev_up) {\n\t\treturn 0;\n\t}',
                          'if (!lpi_dev_up) {\n\t\treturn -EHOSTDOWN;\n\t}',1)
        # set_mux originally had no signed errno local.
        set_mux=(
            'static int lpi_gpio_set_mux(struct pinctrl_dev *pctldev, unsigned int function,\n'
            '\t\t\t    unsigned int pin)\n'
            '{\n'
            '\tstruct lpi_gpio_pad *pad;\n'
            '\tunsigned int val;'
        )
        if data.count(set_mux)!=1:
            raise RuntimeError("P478 LPI mux signature donor drift")
        data=data.replace(set_mux,set_mux+'\n\tint ret;',1)
        # The old caller ignored the read errno and would write a
        # modified -EINVAL to LPASS registers. Propagate the error.
        old=(
            '\tval = lpi_gpio_read(pad, LPI_GPIO_REG_VAL_CTL);\n'
            '\tval &= ~(LPI_GPIO_REG_FUNCTION_MASK);'
        )
        new=(
            '\tret = lpi_gpio_read(pad, LPI_GPIO_REG_VAL_CTL);\n'
            '\tif (ret < 0)\n\t\treturn ret;\n'
            '\tval = ret;\n'
            '\tval &= ~(LPI_GPIO_REG_FUNCTION_MASK);'
        )
        if data.count(old)!=1:raise RuntimeError("P478 LPI mux read donor drift")
        data=data.replace(old,new,1)
        old='\tlpi_gpio_write(pad, LPI_GPIO_REG_VAL_CTL, val);\n\treturn 0;'
        if data.count(old)!=1:raise RuntimeError("P478 LPI mux write donor drift")
        data=data.replace(old,'\treturn lpi_gpio_write(pad, LPI_GPIO_REG_VAL_CTL, val);',1)
        old=(
            '\tval = lpi_gpio_read(pad, LPI_GPIO_REG_VAL_CTL);\n'
            '\tval &= ~(LPI_GPIO_REG_PULL_MASK'
        )
        new=(
            '\tret = lpi_gpio_read(pad, LPI_GPIO_REG_VAL_CTL);\n'
            '\tif (ret < 0)\n\t\tgoto done;\n'
            '\tval = ret;\n'
            '\tval &= ~(LPI_GPIO_REG_PULL_MASK'
        )
        if data.count(old)!=1:raise RuntimeError("P478 LPI pinconf read donor drift")
        data=data.replace(old,new,1)
        old=(
            '\tlpi_gpio_write(pad, LPI_GPIO_REG_VAL_CTL, val);\n'
            '\tlpi_gpio_write(pad, LPI_GPIO_REG_DIR_CTL,\n'
            '\t\t       pad->output_enabled << LPI_GPIO_REG_DIR_SHIFT);\n'
            'done:'
        )
        new=(
            '\tret = lpi_gpio_write(pad, LPI_GPIO_REG_VAL_CTL, val);\n'
            '\tif (ret < 0)\n\t\tgoto done;\n'
            '\tret = lpi_gpio_write(pad, LPI_GPIO_REG_DIR_CTL,\n'
            '\t\t       pad->output_enabled << LPI_GPIO_REG_DIR_SHIFT);\n'
            'done:'
        )
        if data.count(old)!=1:raise RuntimeError("P478 LPI pinconf write donor drift")
        data=data.replace(old,new,1)
        # One remaining native pinconf branch is slew-rate access,
        # which formerly ignored errors and kept a temporary slew
        # pointer after failures. It must fail closed too.
        old=(
            '\t\t\t\tlpi_gpio_write(pad, LPI_SLEW_REG_VAL_CTL, arg);\n'
            '\t\t\t\tpad->base = pad->slew_base;\n'
            '\t\t\t\tgoto slew_exit;'
        )
        new=(
            '\t\t\t\tret = lpi_gpio_write(pad, LPI_SLEW_REG_VAL_CTL, arg);\n'
            '\t\t\t\tpad->base = pad->slew_base;\n'
            '\t\t\t\tgoto slew_exit;'
        )
        if data.count(old)!=1:
            raise RuntimeError("P478 LPI direct slew write donor drift")
        data=data.replace(old,new,1)
        old=(
            '\t\t\tval = lpi_gpio_read(pad, LPI_SLEW_REG_VAL_CTL);\n'
            '\t\t\tpad->offset = pad->slew_offset;'
        )
        new=(
            '\t\t\tret = lpi_gpio_read(pad, LPI_SLEW_REG_VAL_CTL);\n'
            '\t\t\tif (ret < 0)\n'
            '\t\t\t\tgoto slew_exit;\n'
            '\t\t\tval = ret;\n'
            '\t\t\tpad->offset = pad->slew_offset;'
        )
        if data.count(old)!=1:
            raise RuntimeError("P478 LPI slew read donor drift")
        data=data.replace(old,new,1)
        old=(
            '\t\t\tlpi_gpio_write(pad, LPI_SLEW_REG_VAL_CTL, val);\n'
            'slew_exit:\n'
            '\t\t\tmutex_unlock(&state->slew_access_lock);\n'
            '\t\t\tbreak;'
        )
        new=(
            '\t\t\tret = lpi_gpio_write(pad, LPI_SLEW_REG_VAL_CTL, val);\n'
            'slew_exit:\n'
            '\t\t\tmutex_unlock(&state->slew_access_lock);\n'
            '\t\t\tif (ret < 0)\n'
            '\t\t\t\tgoto done;\n'
            '\t\t\tbreak;'
        )
        if data.count(old)!=1:
            raise RuntimeError("P478 LPI slew write/lock donor drift")
        data=data.replace(old,new,1)
        old=(
            'done:\n'
            '\treturn ret;\n'
            '}\n'
            '\nstatic const struct pinconf_ops lpi_gpio_pinconf_ops'
        )
        new=(
            'done:\n'
            '\t/* Restore primary GPIO register mapping even on failed slew. */\n'
            '\tpad->base = pad->gpio_base;\n'
            '\tpad->offset = pad->gpio_offset;\n'
            '\treturn ret;\n'
            '}\n'
            '\nstatic const struct pinconf_ops lpi_gpio_pinconf_ops'
        )
        if data.count(old)!=1:
            raise RuntimeError("P478 LPI pinconf done donor drift")
        data=data.replace(old,new,1)
        # The user-visible GPIO read reports an errno if the hardware
        # is unavailable; write() paths use pinconf errno, not success.
        old='\tvalue = lpi_gpio_read(pad, LPI_GPIO_REG_VAL_CTL);\n\treturn value;'
        if data.count(old)!=1:raise RuntimeError("P478 LPI GPIO get donor drift")
        # Already returns the native helper's signed errno: retain.
        # Generic GPIO debugfs fallback must not be used either.
        if data.count(".dbg_show\t\t= lpi_gpio_dbg_show,")!=1:
            raise RuntimeError("P478 LPI debugfs handler owner drift")
    if rel == "soc/pinctrl-wcd.c":
        # The WCD regmap may be powered down when gpio debugfs runs.
        # GPIOLIB's default dbg_show invokes ->get() for requested
        # pins. Override that with a deliberately register-free view.
        old='static const struct gpio_chip wcd_gpio_chip = {'
        if data.count(old)!=1:raise RuntimeError("P478 WCD GPIO chip donor drift")
        safe=(
            '#ifdef CONFIG_DEBUG_FS\n'
            '#include <linux/seq_file.h>\n'
            'static void wcd_gpio_dbg_show(struct seq_file *s, struct gpio_chip *chip)\n'
            '{\n'
            '\tseq_printf(s, "P478 WCD gpio debugfs: %u pins; register reads disabled (clock safety)\\n",\n'
            '\t\t   chip->ngpio);\n'
            '}\n'
            '#else\n'
            '#define wcd_gpio_dbg_show NULL\n'
            '#endif\n\n'
        )
        data=data.replace(old,safe+old,1)
        if data.count('\t.get = wcd_gpio_get,')!=1:
            raise RuntimeError("P478 WCD gpio get owner drift")
        data=data.replace('\t.get = wcd_gpio_get,',
                          '\t.get = wcd_gpio_get,\n\t.dbg_show = wcd_gpio_dbg_show,',1)
    # Independent adaptation: the SWR master also needs 5.10 CPU latency QoS.
    # Do not chain this as `elif`: the earlier SWR dispatch branch already
    # matches this exact translation unit.
    if rel == "soc/swr-mstr-ctrl.c":
        # 5.10 CPU_IDLE split the old PM_QOS_CPU_DMA_LATENCY class
        # out into cpu_latency_qos_* functions. This preserves a real
        # kernel QoS request over its full add/update/remove lifetime.
        old="\tpm_qos_add_request(&swrm->pm_qos_req,\n" \
            "\t\t\t   PM_QOS_CPU_DMA_LATENCY,\n" \
            "\t\t\t   PM_QOS_DEFAULT_VALUE);"
        new="\tcpu_latency_qos_add_request(&swrm->pm_qos_req,\n" \
            "\t\t\t   PM_QOS_DEFAULT_VALUE);"
        if data.count(old)!=1:
            raise RuntimeError("P472 A3b SWR CPU latency add ABI drift")
        data=data.replace(old,new,1)
        for old_name,new_name,count in (
            ("pm_qos_update_request(", "cpu_latency_qos_update_request(", 2),
            ("pm_qos_remove_request(", "cpu_latency_qos_remove_request(", 2),
        ):
            if data.count(old_name)!=count or new_name in data:
                raise RuntimeError("P472 A3b SWR CPU latency lifecycle donor drift: "+old_name)
            data=data.replace(old_name,new_name)
        # swr-mstr-ctrl.h includes linux/pm_qos.h and retains the real
        # struct pm_qos_request, still provided by ACK 5.10.
        if "#include <linux/pm_qos.h>" in data:
            raise RuntimeError("P472 A3b SWR unexpected direct QoS include drift")
    return data


def stage(root,tg,d54):
    for repo,pin,label in ((tg,TG_SHA,"TouchGrass"),(d54,D54_SHA,"5.4 donor")):
        have=subprocess.check_output(["git","-C",str(repo),"rev-parse","HEAD"],
                                     text=True).strip()
        if have!=pin:
            raise RuntimeError(f"P472 A3b {label} SHA drift {have}")
    donor=d54/"techpack/audio"
    target=root/ROOT/"a3b"
    if target.exists():raise RuntimeError("P472 A3b staged twice")
    # Entire private 5.4 header hierarchy stays sandboxed in a3b/include.
    # A3a includes and sources remain unchanged.
    shutil.copytree(donor/"include",target/"include")
    # The donor's shared MBHC read macro is used by both WCD938x
    # and wcd-mbhc-adc.c. Update its real MMIO-backed ASoC read,
    # not the entire global GKI header hierarchy.
    mbhc_header=target/"include/asoc/wcd-mbhc-v2.h"
    mbhc_s=mbhc_header.read_text()
    old_mbhc="snd_soc_component_read32("
    if mbhc_s.count(old_mbhc)!=1:
        raise RuntimeError("P472 A3b pinned MBHC register read macro drift")
    mbhc_header.write_text(mbhc_s.replace(old_mbhc,"snd_soc_component_read(",1))
    # The two real SoundWire masters must have separate exported
    # entry points while preserving swrm_wcd_notify() as the public
    # macro API. The private WCD declaration is used by the
    # compatible-based dispatcher, not by unrelated GKI drivers.
    swr_header=target/"include/soc/swr-wcd.h"
    swr_text=swr_header.read_text()
    swr_old="extern int swrm_wcd_notify(struct platform_device *pdev, u32 id, void *data);"
    if swr_text.count(swr_old)!=1:
        raise RuntimeError("P472 A3b pinned SoundWire public API drift")
    swr_header.write_text(swr_text.replace(
        swr_old,swr_old+"\nextern int swrm_wcd_notify_wcd(struct platform_device *pdev, u32 id, void *data);",1))
    # 5.4 downstream keeps these driver-required headers outside
    # techpack/audio/include. Stage pinned originals privately, never
    # edit global GKI include/ or invent ABI types/success stubs.
    # SM7325 @c4cb0a97:
    #   include/dt-bindings/sound/qcom,bolero-clk-rsc.h:10-18
    #   include/soc/qcom/pm.h:12-30
    extra_headers = (
        "include/dt-bindings/sound/qcom,bolero-clk-rsc.h",
        "include/soc/qcom/pm.h",
        "include/dt-bindings/sound/audio-codec-port-types.h",
        "include/linux/soc/qcom/fsa4480-i2c.h",
        "include/sound/wcd-dsp-mgr.h",
        "include/soc/qcom/ramdump.h",
    )
    for rel in extra_headers:
        source=d54/rel
        if not source.is_file():
            raise RuntimeError("P472 A3b pinned 5.4 external header missing: "+rel)
        dest=target/rel
        if dest.exists():
            raise RuntimeError("P472 A3b external header collision: "+rel)
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
    allfiles=B1+B2+B3
    for rel in allfiles:
        dest=target/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        data=(donor/rel).read_text()
        data=adapt_510_api(rel,data)
        if rel in PROBES:data=add_probe_logger(rel,data)
        data=add_enumeration(rel,data)
        dest.write_text(data)
    # Real 5.4 sibling private headers under selected subtrees.
    for directory in ("soc","asoc/codecs","asoc/codecs/bolero",
                      "asoc/codecs/wcd938x"):
        for hdr in (donor/directory).glob("*.h"):
            dest=target/directory/hdr.name
            if not dest.exists():shutil.copy2(hdr,dest)
    for path,txt in SUB_MAKE.items():
        dest=target/path
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(txt)
    (target/"asoc/codecs/a3b-cdc-pinctrl-init.c").write_text(CDC_INIT_SOURCE)
    (target/"Makefile").write_text(ROOT_MAKE)
    qmk=root/ROOT/"Makefile"
    qmk.write_text(one(qmk.read_text(),"obj-y += dsp/ soc/ ipc/",
        "obj-y += dsp/ soc/ ipc/\nobj-$(CONFIG_P472_A3B_B1) += a3b/",
        "audio subtree Kbuild"))
    qk=root/"drivers/soc/qcom/Kconfig"
    body=qk.read_text()
    if "config P472_A3B_B1" in body:
        raise RuntimeError("P472 A3b Kconfig already exists")
    qk.write_text(body+"\n"+KCONFIG)
    check(root)

def check(root):
    target=root/ROOT/"a3b"
    mk=(root/ROOT/"Makefile").read_text()
    k=(root/"drivers/soc/qcom/Kconfig").read_text()
    if mk.count("obj-$(CONFIG_P472_A3B_B1) += a3b/")!=1:
        raise RuntimeError("P472 A3b compilation Kbuild missing")
    for cfg in ("P472_A3B_B1","P472_A3B_B2","P472_A3B_B3"):
        if k.count("config "+cfg)!=1:
            raise RuntimeError("P472 A3b independent Kconfig missing: "+cfg)
        scope=k.split("config "+cfg,1)[1].split("config ",1)[0]
        if "default n" not in scope:
            raise RuntimeError("P472 A3b must be default off: "+cfg)
    for rel in ("include/dt-bindings/sound/qcom,bolero-clk-rsc.h",
                "include/dt-bindings/sound/audio-codec-port-types.h",
                "include/linux/soc/qcom/fsa4480-i2c.h",
                "include/sound/wcd-dsp-mgr.h",
                "include/soc/qcom/ramdump.h",
                "include/soc/qcom/pm.h"):
        if not (target/rel).is_file():
            raise RuntimeError("P472 A3b pinned external header absent: "+rel)
    clk = (target/"include/dt-bindings/sound/qcom,bolero-clk-rsc.h").read_text()
    if clk.count("#define MAX_CLK\t8") != 1:
        raise RuntimeError("P472 A3b donor Bolero clock resource constants drift")
    port_types=(target/"include/dt-bindings/sound/audio-codec-port-types.h").read_text()
    if (port_types.count("#define HPH_L 9")!=1 or
        port_types.count("#define MBHC 17")!=1 or
        port_types.count("#define SWRM_RX_PCM_IN 47")!=1):
        raise RuntimeError("P472 A3b WCD938x 5.4 DT port ID constants drift")
    wcd_main=(target/"asoc/codecs/wcd938x/wcd938x.c").read_text()
    if wcd_main.count("#include <dt-bindings/sound/audio-codec-port-types.h>")!=1:
        raise RuntimeError("P472 A3b WCD938x real DT port binding missing")
    pm = (target/"include/soc/qcom/pm.h").read_text()
    if (pm.count("msm_cpuidle_get_deep_idle_latency(void)") != 2 or
            "#include <linux/cpuidle.h>" not in pm):
        raise RuntimeError("P472 A3b real 5.4 SoundWire PM/QoS header drift")
    # WCD938x -> asoc/wcdcal-hwdep.h:7 imports the donor-owned
    # <audio/sound/msmcal-hwdep.h>. It is at include/uapi/audio/sound/
    # and therefore needs -I.../a3b/include/uapi (not just /uapi/audio).
    hwdep=target/"include/uapi/audio/sound/msmcal-hwdep.h"
    if not hwdep.is_file():
        raise RuntimeError("P472 A3b pinned msmcal-hwdep UAPI header absent")
    hwdep_user=target/"include/asoc/wcdcal-hwdep.h"
    if (not hwdep_user.is_file() or
        hwdep_user.read_text().count("#include <audio/sound/msmcal-hwdep.h>") != 1):
        raise RuntimeError("P472 A3b WCD938x hwdep header/source ABI drift")
    target_make=(target/"Makefile").read_text()
    # Exact Makefile lines, not an escaped backslash-n substring.
    # This audits the real compiler include path without weakening
    # the requirement that every private donor UAPI root occur once.
    flags=target_make.splitlines()
    for root_flag in (
        "subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include/uapi",
        "subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include/uapi/audio",
    ):
        if flags.count(root_flag) != 1:
            raise RuntimeError("P472 A3b UAPI include root count != 1: "+root_flag)
    # WCD938x uses the genuine CDC pinctrl sleep/active control
    # and must not enter the donor's no-op fallback branch. The real
    # driver is selected as an A3b B1 object and its implementation
    # supplies the proper extern declarations.
    b1_flags=[line for line in target_make.splitlines()
              if line.startswith("subdir-ccflags-$(CONFIG_P472_A3B_B1) +=")]
    if (len(b1_flags)!=1 or
        b1_flags[0].split().count("-DCONFIG_MSM_CDC_PINCTRL=1")!=1):
        raise RuntimeError("P472 A3b real MSM CDC pinctrl config missing")
    cdc_header=(target/"include/asoc/msm-cdc-pinctrl.h").read_text()
    cdc_source=(target/"asoc/codecs/msm-cdc-pinctrl.c").read_text()
    if (cdc_header.count("#if IS_ENABLED(CONFIG_MSM_CDC_PINCTRL)")!=1 or
        cdc_header.count("extern int msm_cdc_pinctrl_set_wakeup_capable(")!=1 or
        cdc_source.count("int msm_cdc_pinctrl_set_wakeup_capable(")!=1 or
        cdc_source.count("int msm_cdc_pinctrl_select_sleep_state(")!=1 or
        "msm-cdc-pinctrl.o" not in (target/"asoc/codecs/Makefile").read_text()):
        raise RuntimeError("P472 A3b real CDC pinctrl declarations/implementation drift")
    # Native 5.10 wake IRQ path, no fake success on unsupported GPIO.
    cdc_510=(target/"asoc/codecs/msm-cdc-pinctrl.c").read_text()
    for code in (
        "#include <linux/pinctrl/consumer.h>",
        "#include <linux/interrupt.h>",
        "gpiochip_find(NULL, p478_match_tlmm_gpiochip)",
        '!strcmp(base, "pinctrl@f100000")',
        "gpio = tlmm->base + pin;",
        "gpio_irq = gpio_to_irq(gpio);",
        "irq_set_irq_wake(gpio_irq, enable);",
        "P472 A3b CDC_TLMM_WAKE pin=%d gpio=%d irq=%d en=%d rc=%d",
    ):
        if cdc_510.count(code)!=1:
            raise RuntimeError("P472 A3b real 5.10 GPIO IRQ wake missing: "+code)
    if ("msm_gpio_mpm_wake_set(" in cdc_510 or
            "#include <linux/pinctrl/qcom-pinctrl.h>" in cdc_510):
        raise RuntimeError("P472 A3b unsupported 5.4 GPIO wake API survived")
    # P477B source contracts from TG 4.19 and A52 r02:
    for rel,prop,mark in (
        ("soc/pinctrl-lpi.c","qcom,num-gpios","P472 A3b LPI_GPIO_PROP"),
        ("soc/pinctrl-wcd.c","qcom,num-gpios","P472 A3b WCD_GPIO_PROP"),
        ("asoc/codecs/msm-cdc-pinctrl.c","qcom,tlmm-gpio","P472 A3b CDC_TLMM_PROP"),
    ):
        source=(target/rel).read_text()
        if source.count(mark)!=1 or source.count('"'+prop+'"')<2:
            raise RuntimeError("P477B A52 r02 pinctrl property drift: "+rel)
    init=(target/"asoc/codecs/a3b-cdc-pinctrl-init.c").read_text()
    if (init.count("msm_cdc_pinctrl_drv_init();")!=1 or
        init.count("subsys_initcall(p472_a3b_cdc_pinctrl_init);")!=1 or
        init.count("P472 A3b CDC_PINCTRL register rc=%d")!=1 or
        "a3b-cdc-pinctrl-init.o" not in (target/"asoc/codecs/Makefile").read_text()):
        raise RuntimeError("P477B early real CDC pinctrl driver missing")
    for legacy in ("wcd9xxx_irq_drv_init(", "wcd9xxx_init(",
                   "wcd9xxx-core-init.o"):
        if legacy in init or legacy in (target/"asoc/codecs/Makefile").read_text():
            raise RuntimeError("P477B legacy WCD9xxx core/IRQ registration forbidden")
    # P478 safety: debugfs never reads LPASS/WCD GPIO hardware.
    lpi=(target/"soc/pinctrl-lpi.c").read_text()
    wcd=(target/"soc/pinctrl-wcd.c").read_text()
    for expected in ("P478 LPI gpio debugfs:", "pm_runtime_resume_and_get(lpi_dev);",
                     "return -EHOSTDOWN;", "return lpi_gpio_write("):
        if expected not in lpi:
            raise RuntimeError("P478 LPASS guarded GPIO access missing: "+expected)
    if (lpi.count("ret = lpi_gpio_write(pad, LPI_SLEW_REG_VAL_CTL,")!=2 or
        "ret = lpi_gpio_read(pad, LPI_SLEW_REG_VAL_CTL);" not in lpi or
        "pad->base = pad->gpio_base;" not in lpi):
        raise RuntimeError("P478 LPASS slew register read/write guard missing")
    if ("static void lpi_gpio_dbg_show_one(" in lpi or
        "pm_runtime_get_sync(lpi_dev)" in lpi or
        "P478 WCD gpio debugfs:" not in wcd or
        ".dbg_show = wcd_gpio_dbg_show," not in wcd):
        raise RuntimeError("P478 unsafe GPIO debugfs register access remains")
    # WCD938x must use real IRQ and Class-H implementations. The
    # SM7325 5.4 fallback headers contain malformed/no-op stubs, while
    # B3 intentionally builds wcd-irq.c and wcd-clsh.c. Select their
    # actual declaration branches; never compile fake IRQ success.
    b3_flags=[line for line in target_make.splitlines()
              if line.startswith("subdir-ccflags-$(CONFIG_P472_A3B_B3) +=")]
    if len(b3_flags)!=1:
        raise RuntimeError("P472 A3b B3 compiler flag line missing/duplicate")
    for token in ("-DCONFIG_WCD9XXX_CODEC_CORE_V2=1",
                  "-DCONFIG_SND_SOC_WCD9XXX_V2=1"):
        if b3_flags[0].split().count(token)!=1:
            raise RuntimeError("P472 A3b real WCD IRQ/Class-H config missing: "+token)
    irq_header=(target/"include/asoc/wcd-irq.h").read_text()
    clsh_header=(target/"include/asoc/wcd-clsh.h").read_text()
    if (irq_header.count("IS_ENABLED(CONFIG_WCD9XXX_CODEC_CORE_V2)")!=1 or
        clsh_header.count("#ifdef CONFIG_SND_SOC_WCD9XXX_V2")!=1):
        raise RuntimeError("P472 A3b WCD real IRQ/Class-H header selection drift")
    irq_c=(target/"asoc/codecs/wcd-irq.c").read_text()
    clsh_c=(target/"asoc/codecs/wcd-clsh.c").read_text()
    for required in ("int wcd_irq_init(", "int wcd_request_irq("):
        if irq_c.count(required)!=1:
            raise RuntimeError("P472 A3b real WCD IRQ implementation absent: "+required)
    for required in ("void wcd_cls_h_fsm(", "void wcd_cls_h_init("):
        if clsh_c.count(required)!=1:
            raise RuntimeError("P472 A3b real WCD Class-H implementation absent: "+required)
    if ("wcd-irq.o" not in (target/"asoc/codecs/Makefile").read_text() or
        "wcd-clsh.o" not in (target/"asoc/codecs/Makefile").read_text()):
        raise RuntimeError("P472 A3b WCD support real objects not compiled")
    for rel in B1+B2+B3:
        if not (target/rel).is_file():
            raise RuntimeError("P472 A3b real donor source missing "+rel)
    # Both original SoundWire controllers are required by their
    # distinct OF nodes. Public notify is owned exactly once, routes
    # by compatible, and rejects unknown hardware and commands.
    mstr=(target/"soc/swr-mstr-ctrl.c").read_text()
    wcd=(target/"soc/swr-wcd-ctrl.c").read_text()
    swr_h=(target/"include/soc/swr-wcd.h").read_text()
    soc_make=(target/"soc/Makefile").read_text()
    for code in (
        "int swrm_wcd_notify(struct platform_device *pdev, u32 id, void *data)",
        "EXPORT_SYMBOL(swrm_wcd_notify);",
        'of_device_is_compatible(pdev->dev.of_node, "qcom,swr-wcd")',
        'of_device_is_compatible(pdev->dev.of_node, "qcom,swr-mstr")',
        "return swrm_wcd_notify_wcd(pdev, id, data);",
        '.name = "swr-mstr",',
        "P472 A3b SWR unsupported controller",
        "ret = -EOPNOTSUPP;",
    ):
        if mstr.count(code)!=1:
            raise RuntimeError("P472 A3b real LPASS SWR dispatch drift: "+code)
    for code in (
        "int swrm_wcd_notify_wcd(struct platform_device *pdev, u32 id, void *data)",
        "EXPORT_SYMBOL(swrm_wcd_notify_wcd);",
        "swrm_wcd_notify_wcd(swrm->pdev, SWR_DEVICE_DOWN, NULL);",
        "ret = -EOPNOTSUPP;",
        '"qcom,swr-wcd"',
        ".name = SWR_WCD_NAME,",
    ):
        if wcd.count(code)!=1:
            raise RuntimeError("P472 A3b real WCD SWR dispatch drift: "+code)
    if (swr_h.count("extern int swrm_wcd_notify(")!=1 or
        swr_h.count("extern int swrm_wcd_notify_wcd(")!=1 or
        soc_make.count("swr-mstr-ctrl.o")!=1 or
        soc_make.count("swr-wcd-ctrl.o")!=1):
        raise RuntimeError("P472 A3b dual SoundWire hardware ABI/ownership drift")
    # Stage checks below confirm both SWR notification routing and the
    # complete real CPU latency QoS lifecycle survive in the same source.
    # The pinned 5.4 WCD DSP manager public header is outside
    # techpack/audio. Select actual function declarations, never its
    # CONFIG_WCD9XXX_CODEC_CORE fallback that falsely returns success.
    wdsp_h=(target/"include/sound/wcd-dsp-mgr.h").read_text()
    wdsp_c=(target/"asoc/codecs/wcd-dsp-mgr.c").read_text()
    wdsp_soc=(target/"asoc/codecs/wcd9xxx-soc-init.c").read_text()
    ramdump_h=(target/"include/soc/qcom/ramdump.h").read_text()
    b3_wdsp=[line for line in target_make.splitlines()
             if line.startswith("subdir-ccflags-$(CONFIG_P472_A3B_B3) +=")]
    if (len(b3_wdsp)!=1 or
        b3_wdsp[0].split().count("-DCONFIG_WCD9XXX_CODEC_CORE=1")!=1):
        raise RuntimeError("P472 A3b real WCD DSP manager config absent")
    for expected,content in (
        ("#ifdef CONFIG_WCD9XXX_CODEC_CORE",wdsp_h),
        ("int wcd_dsp_mgr_init(void);",wdsp_h),
        ("int wcd_dsp_mgr_init(void)",wdsp_c),
        ("void wcd_dsp_mgr_exit(void)",wdsp_c),
        ("#include <sound/wcd-dsp-mgr.h>",wdsp_soc),
        ("#include <soc/qcom/ramdump.h>",wdsp_c),
        ("extern int do_ramdump(",ramdump_h),
        ("extern void *create_ramdump_device(",ramdump_h),
    ):
        if content.count(expected)!=1:
            raise RuntimeError("P472 A3b original WCD DSP/ramdump ABI drift: "+expected)
    if ("wcd-dsp-mgr.o" not in (target/"asoc/codecs/Makefile").read_text() or
        "wcd9xxx-soc-init.o" not in (target/"asoc/codecs/Makefile").read_text()):
        raise RuntimeError("P472 A3b WCD DSP manager objects missing")
    # Real arm64 DMA configuration remains intact, now with its
    # proper ACK 5.10 declaration. Do not skip setup or insert stubs.
    if (wdsp_c.count("#include <linux/dma-map-ops.h>")!=1 or
        wdsp_c.count("arch_setup_dma_ops(wdsp->mdev, 0, 0, NULL, 0);")!=1 or
        wdsp_c.count("#include <linux/dma-mapping.h>")!=1):
        raise RuntimeError("P472 A3b WCD DSP manager 5.10 DMA setup changed")
    # The donor's wcd-mbhc-v2-api.h otherwise supplies inline
    # no-op/false-success MBHC functions that collide with the real
    # wcd-mbhc-v2.c implementation. B3 must select real prototypes.
    mbhc_api=(target/"include/asoc/wcd-mbhc-v2-api.h").read_text()
    b3_api_flags=[line for line in target_make.splitlines()
                  if line.startswith("subdir-ccflags-$(CONFIG_P472_A3B_B3) +=")]
    if (len(b3_api_flags)!=1 or
        b3_api_flags[0].split().count("-DCONFIG_SND_SOC_WCD_MBHC=1")!=1 or
        mbhc_api.count("#if IS_ENABLED(CONFIG_SND_SOC_WCD_MBHC)")!=1):
        raise RuntimeError("P472 A3b real WCD MBHC API selection missing")
    mbhc_impl=(target/"asoc/codecs/wcd-mbhc-v2.c").read_text()
    for token in ("int wcd_mbhc_start(", "void wcd_mbhc_stop(",
                  "int wcd_mbhc_init(", "int wcd_mbhc_get_impedance(",
                  "void wcd_mbhc_deinit("):
        if mbhc_impl.count(token)!=1:
            raise RuntimeError("P472 A3b real WCD MBHC implementation drift: "+token)
    if "wcd-mbhc-v2.o" not in (target/"asoc/codecs/Makefile").read_text():
        raise RuntimeError("P472 A3b real WCD MBHC object missing")
    # Keep the full MBHC ADC path while isolating the unrelated
    # legacy SLIMbus pdata header. The pinned SM7325 code uses no
    # symbol from pdata.h in this translation unit.
    adc_source=(target/"asoc/codecs/wcd-mbhc-adc.c").read_text()
    if ("#include <asoc/pdata.h>" in adc_source or
        "linux/slimbus/slimbus.h" in adc_source or
        adc_source.count("void wcd_mbhc_adc_init(struct wcd_mbhc *mbhc)")!=1 or
        adc_source.count("WCD_MBHC_REG_READ(")!=22):
        raise RuntimeError("P472 A3b MBHC ADC / legacy SLIMbus isolation drift")
    # The MBHC macro must use the genuine ACK 5.10 ASoC register
    # access, and its ADC initializer must resolve to the real object.
    mbhc_shared=(target/"include/asoc/wcd-mbhc-v2.h").read_text()
    if (mbhc_shared.count("snd_soc_component_read(")!=1 or
        "snd_soc_component_read32(" in mbhc_shared or
        mbhc_shared.count("#define WCD_MBHC_REG_READ(")!=1):
        raise RuntimeError("P472 A3b shared real MBHC read macro ABI drift")
    adc_header=(target/"asoc/codecs/wcd-mbhc-adc.h").read_text()
    adc_impl=(target/"asoc/codecs/wcd-mbhc-adc.c").read_text()
    adc_flags=[line for line in target_make.splitlines()
               if line.startswith("subdir-ccflags-$(CONFIG_P472_A3B_B3) +=")]
    if (len(adc_flags)!=1 or
        adc_flags[0].split().count("-DCONFIG_SND_SOC_WCD_MBHC_ADC=1")!=1 or
        adc_header.count("#if IS_ENABLED(CONFIG_SND_SOC_WCD_MBHC_ADC)")!=1 or
        adc_impl.count("void wcd_mbhc_adc_init(struct wcd_mbhc *mbhc)")!=1 or
        "wcd-mbhc-adc.o" not in (target/"asoc/codecs/Makefile").read_text()):
        raise RuntimeError("P472 A3b real MBHC ADC declaration/implementation missing")
    # Stage original FSA4480 declarations only. No FSA driver, and
    # a DT request for USB-C analog must fail with -EOPNOTSUPP.
    fsa_header=(target/"include/linux/soc/qcom/fsa4480-i2c.h").read_text()
    mbhc_core=(target/"asoc/codecs/wcd-mbhc-v2.c").read_text()
    for required in (
        "#include <linux/soc/qcom/fsa4480-i2c.h>",
        "!IS_ENABLED(CONFIG_QCOM_FSA4480_I2C)",
        "P472 A3b FSA4480 unavailable: Type-C analog rejected",
        "return -EOPNOTSUPP;",
    ):
        if mbhc_core.count(required)!=1:
            raise RuntimeError("P472 A3b FSA4480 fail-closed ABI missing: "+required)
    if (fsa_header.count("#define FSA4480_I2C_H")!=1 or
        fsa_header.count("int fsa4480_reg_notifier(")!=2 or
        "fsa4480.o" in (target/"asoc/codecs/Makefile").read_text()):
        raise RuntimeError("P472 A3b FSA4480 original header/driver isolation drift")
    # Real 5.10 ASoC and CPU latency QoS APIs, not compat stubs.
    bolero=(target/"asoc/codecs/bolero/bolero-cdc.c").read_text()
    if (bolero.count("snd_soc_component_read(")!=2 or
        "snd_soc_component_read32(" in bolero):
        raise RuntimeError("P472 A3b Bolero 5.10 ASoC codec-ID reads missing")
    # WCD938x codec/MBHC real register reads use the 5.10 ASoC ABI.
    for rel,expected in (
        ("asoc/codecs/wcd938x/wcd938x.c",10),
        ("asoc/codecs/wcd938x/wcd938x-mbhc.c",13),
    ):
        source=(target/rel).read_text()
        if (source.count("snd_soc_component_read(")!=expected or
            "snd_soc_component_read32(" in source):
            raise RuntimeError("P472 A3b WCD938x 5.10 codec read ABI drift: "+rel)
    # All three real Bolero macro I/O paths use ACK 5.10 ASoC APIs.
    for rel,expected in (
        ("asoc/codecs/bolero/rx-macro.c",38),
        ("asoc/codecs/bolero/tx-macro.c",11),
        ("asoc/codecs/bolero/va-macro.c",9),
    ):
        macro=(target/rel).read_text()
        if (macro.count("snd_soc_component_read(")!=expected or
                "snd_soc_component_read32(" in macro):
            raise RuntimeError("P472 A3b macro 5.10 ASoC read conversion missing "+rel)
    rx=(target/"asoc/codecs/bolero/rx-macro.c").read_text()
    if (rx.count("regmap_read(component->regmap, reg, &val);")!=1 or
        "snd_soc_component_read(component, reg, &val);" in rx or
        "#include <linux/regmap.h>" not in rx):
        raise RuntimeError("P472 A3b optional RX impedance errno path missing")
    for token in (
        ".mute_stream = rx_macro_digital_mute,",
        "static int rx_macro_digital_mute(struct snd_soc_dai *dai, int mute, int stream);",
        "static int rx_macro_digital_mute(struct snd_soc_dai *dai, int mute, int stream)\n{",
        "if (stream != SNDRV_PCM_STREAM_PLAYBACK)",
    ):
        if rx.count(token)!=1:
            raise RuntimeError("P472 A3b RX 5.10 DAI mute callback missing "+token)
    if ".digital_mute = rx_macro_digital_mute," in rx:
        raise RuntimeError("P472 A3b legacy RX .digital_mute remained")
    swr_header=(target/"soc/swr-mstr-ctrl.h").read_text()
    if (swr_header.count("#include <linux/pm_qos.h>")!=1 or
        swr_header.count("struct pm_qos_request pm_qos_req;")!=1):
        raise RuntimeError("P472 A3b 5.10 QoS type/header unavailable")
    swr=(target/"soc/swr-mstr-ctrl.c").read_text()
    for symbol,n in (
        ("cpu_latency_qos_add_request(",1),
        ("cpu_latency_qos_update_request(",2),
        ("cpu_latency_qos_remove_request(",2),
    ):
        if swr.count(symbol)!=n:
            raise RuntimeError("P472 A3b real 5.10 QoS lifecycle missing: "+symbol)
    for old in ("pm_qos_add_request(", "pm_qos_update_request(",
                "pm_qos_remove_request(", "PM_QOS_CPU_DMA_LATENCY"):
        if old in swr:
            raise RuntimeError("P472 A3b legacy 5.4 QoS API remains: "+old)
    for rel,(fn,part,kind) in PROBES.items():
        source=(target/rel).read_text()
        marker=f"P472 A3b PART {part} probe rc=%d"
        if source.count(marker)!=1 or source.count("int rc="+fn+"(pdev);")!=1:
            raise RuntimeError("P472 A3b fake/missing real callback "+part)
        if len(re.findall(r"\.probe\s*=\s*p472_a3b_logged_probe\s*,",source))!=1:
            raise RuntimeError("P472 A3b fake/missing real driver registration "+part)
    swr=(target/"soc/swr-mstr-ctrl.c").read_text()
    if (swr.count("P472 A3b SWR %s slaves=%u enumerated")!=1 or
        "swr_master_read(swrm,SWRM_MCP_SLV_STATUS)" not in swr):
        raise RuntimeError("P472 A3b hardware read slave count missing")
    for bad in ("wsa-macro.o","wcd937x/","wsa883x/","tas256x/",
                "fsa4480/","kona.o"):
        if bad in "\n".join((target/p).read_text() for p in SUB_MAKE):
            raise RuntimeError("P472 A3b unwanted audio part selected "+bad)
    print("P472 A3b SOURCE PASS: 5.4 real probes, hardware SWR count, no machine/WSA/amp")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--tg",type=Path)
    p.add_argument("--d54",type=Path)
    p.add_argument("--check-only",action="store_true")
    p.add_argument("--report",type=Path)
    a=p.parse_args()
    if a.check_only:
        check(a.root)
    else:
        if not a.tg or not a.d54:
            raise RuntimeError("P472 A3b pinned TG+5.4 donor required")
        stage(a.root,a.tg,a.d54)
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps({"stage":"P472_A3B","tg":TG_SHA,
            "linux54_donor":D54_SHA,"source_pass":True,
            "real_probe_count":len(PROBES),"machine_driver":False,
            "wsa_macro":False,"hardware_probed":False},indent=2)+"\n")
if __name__=="__main__":
    main()
