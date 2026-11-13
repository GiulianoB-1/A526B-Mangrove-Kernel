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
        "obj-$(CONFIG_P472_A3B_B1) += msm-cdc-pinctrl.o msm-cdc-supply.o audio-ext-clk-up.o\n"
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
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include/uapi/audio
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include/uapi
subdir-ccflags-$(CONFIG_P472_A3B_B1) += -DCONFIG_PINCTRL_WCD=1 -DCONFIG_PINCTRL_LPI=1
subdir-ccflags-$(CONFIG_P472_A3B_B2) += -DCONFIG_SND_SOC_BOLERO=1 -DCONFIG_RX_MACRO=1 -DCONFIG_TX_MACRO=1 -DCONFIG_VA_MACRO=1
subdir-ccflags-$(CONFIG_P472_A3B_B3) += -DCONFIG_SOUNDWIRE=1 -DCONFIG_SOUNDWIRE_WCD_CTRL=1 -DCONFIG_SOUNDWIRE_MSTR_CTRL=1 -DCONFIG_SND_SOC_WCD938X=1 -DCONFIG_SND_SOC_WCD938X_SLAVE=1
obj-y += soc/ asoc/
'''

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
    elif rel == "soc/swr-mstr-ctrl.c":
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
        if data.count("#include <linux/pm_qos.h>")!=1:
            raise RuntimeError("P472 A3b SWR 5.4 pm_qos header not present")
        # Keep struct pm_qos_request, which remains the real ACK 5.10 ABI.
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
    # 5.4 downstream keeps these driver-required headers outside
    # techpack/audio/include. Stage pinned originals privately, never
    # edit global GKI include/ or invent ABI types/success stubs.
    # SM7325 @c4cb0a97:
    #   include/dt-bindings/sound/qcom,bolero-clk-rsc.h:10-18
    #   include/soc/qcom/pm.h:12-30
    extra_headers = (
        "include/dt-bindings/sound/qcom,bolero-clk-rsc.h",
        "include/soc/qcom/pm.h",
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
                "include/soc/qcom/pm.h"):
        if not (target/rel).is_file():
            raise RuntimeError("P472 A3b pinned external header absent: "+rel)
    clk = (target/"include/dt-bindings/sound/qcom,bolero-clk-rsc.h").read_text()
    if clk.count("#define MAX_CLK\t8") != 1:
        raise RuntimeError("P472 A3b donor Bolero clock resource constants drift")
    pm = (target/"include/soc/qcom/pm.h").read_text()
    if (pm.count("msm_cpuidle_get_deep_idle_latency(void)") != 2 or
            "#include <linux/cpuidle.h>" not in pm):
        raise RuntimeError("P472 A3b real 5.4 SoundWire PM/QoS header drift")
    for rel in B1+B2+B3:
        if not (target/rel).is_file():
            raise RuntimeError("P472 A3b real donor source missing "+rel)
    # Real 5.10 ASoC and CPU latency QoS APIs, not compat stubs.
    bolero=(target/"asoc/codecs/bolero/bolero-cdc.c").read_text()
    if (bolero.count("snd_soc_component_read(")!=2 or
        "snd_soc_component_read32(" in bolero):
        raise RuntimeError("P472 A3b Bolero 5.10 ASoC codec-ID reads missing")
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
