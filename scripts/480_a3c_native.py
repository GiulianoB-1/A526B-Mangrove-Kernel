#!/usr/bin/env python3
"""P480 native A3c staging against pinned TG r02 and Samsung 5.4 ASoC API.

A3c is opt-in. This script changes neither the P479 charging source nor
the preexisting HLT boot arguments. Missing hardware is never replaced
with a fake physical codec or an invented probe return code.

The 5.4 source is the 5.10 ASoC ABI bridge for the TG Kona audio family.
The source inventory and card name are pinned to A52 r02. This is a
native-build CANDIDATE until a full Image link and hardware bringup.
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

TG_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
D54_SHA = "c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4"
R02 = "arch/arm64/boot/dts/samsung/a52/a52xq/a52xq_eur_open_w00_r02.dts"
ROOT = Path("drivers/soc/qcom/p472_tg_audio")
TARGET = ROOT / "a3c"
MARK = "P480_A3C_NATIVE_WCD938X_KONA_V1"

PROVIDERS = (
    "msm-pcm-q6-v2.c",
    "msm-compress-q6-v2.c",
    "msm-pcm-hostless.c",
    "msm-pcm-afe-v2.c",
    "msm-pcm-q6-noirq.c",
    "msm-pcm-routing-v2.c",
    "msm-pcm-routing-devdep.c",
    "msm-dai-q6-v2.c",
    "msm-dai-fe.c",
    "msm-dai-stub-v2.c",
    "msm-audio-effects-q6-v2.c",
    "msm-qti-pp-config.c",
    "platform_init.c",
    "codecs/msm_stub.c",
)
# Genuine FE and BE components requested by the TG r02 Kona card.
# The analog headset and microphone codec is WCD938x, NOT WCD937x.
FE_IDS = (
    "multimedia1", "multimedia2", "multimedia3", "multimedia4",
    "multimedia5", "multimedia7", "multimedia8", "multimedia9",
    "multimedia10", "multimedia11", "multimedia12", "multimedia13",
    "multimedia14", "multimedia15", "multimedia16", "multimedia17",
    "afepcm_rx", "afepcm_tx", "cdcdma_hostless",
    "tx3_cdcdma_hostless",
)
BE_IDS = (
    "rx_dma_rx0", "rx_dma_rx1", "rx_dma_rx2", "rx_dma_rx3",
    "tx_dma_tx3", "tx_dma_tx4", "va_dma_tx0",
    "va_dma_tx1", "va_dma_tx2",
)
SELECTED = FE_IDS + BE_IDS
FORBIDDEN_LINK_TOKENS = (
    "Voice", "VOICE", "VoIP", "VOIP", "InCall", "INCALL",
    "Listen", "LISTEN", "WSA", "wsa", "tas256", "TAS256",
    "wcd937x", "WCD937X", "btfmslim", "SLIMBUS", "slimbus",
    "DISPLAY", "Display", "HDMI", "USB", "voice", "cvd",
)
# These are existing real providers, not placeholders for missing codecs.
ALLOWED_PLATFORMS = {
    "msm-pcm-dsp.0", "msm-pcm-dsp.1", "msm-pcm-dsp.2",
    "msm-compress-dsp", "msm-pcm-hostless", "msm-pcm-afe",
    "msm-pcm-routing", "msm-pcm-dsp-noirq", "msm-compr-dsp",
}


P480_PLATFORM_INIT = r'''
// SPDX-License-Identifier: GPL-2.0-only
/* P480 A3c: only real Q6 PCM/compress/routing/DAI providers.
 * In particular: no LSM/listen, no HDMI, no voice/VoIP/CVD
 * and no unported transcode/loopback/HDMI platform initializers.
 */
#include <linux/kernel.h>
#include <linux/module.h>
#include "platform_init.h"

static int __init p480_audio_platform_init(void)
{
    int rc;
    rc=msm_compress_dsp_init();
    if (rc) return rc;
    rc=msm_fe_dai_init();
    if (rc) goto err_fe;
    rc=msm_dai_q6_init();
    if (rc) goto err_q6;
    rc=msm_dai_stub_init();
    if (rc) goto err_stub;
    rc=msm_pcm_afe_init();
    if (rc) goto err_afe;
    rc=msm_pcm_hostless_init();
    if (rc) goto err_hostless;
    rc=msm_pcm_noirq_init();
    if (rc) goto err_noirq;
    rc=msm_pcm_dsp_init();
    if (rc) goto err_pcm;
    rc=msm_soc_routing_platform_init();
    if (rc) goto err_routing;
    pr_info("P480 A3c PART PLATFORM_REGISTER probe rc=0\n");
    return 0;
err_routing:
    msm_pcm_dsp_exit();
err_pcm:
    msm_pcm_noirq_exit();
err_noirq:
    msm_pcm_hostless_exit();
err_hostless:
    msm_pcm_afe_exit();
err_afe:
    msm_dai_stub_exit();
err_stub:
    msm_dai_q6_exit();
err_q6:
    msm_fe_dai_exit();
err_fe:
    msm_compress_dsp_exit();
    pr_err("P480 A3c PART PLATFORM_REGISTER probe rc=%d\n", rc);
    return rc;
}
static void __exit p480_audio_platform_exit(void)
{
    msm_soc_routing_platform_exit();
    msm_pcm_dsp_exit();
    msm_pcm_noirq_exit();
    msm_pcm_hostless_exit();
    msm_pcm_afe_exit();
    msm_dai_stub_exit();
    msm_dai_q6_exit();
    msm_fe_dai_exit();
    msm_compress_dsp_exit();
}
module_init(p480_audio_platform_init);
module_exit(p480_audio_platform_exit);
MODULE_DESCRIPTION("P480 native Q6 ASoC providers (no voice)");
MODULE_LICENSE("GPL v2");
'''

def pin(path, sha, name):
    actual = subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        text=True).strip()
    if actual != sha:
        raise RuntimeError("P480 %s pin drift %s" % (name, actual))

def one(src, before, after, label):
    if src.count(before) != 1:
        raise RuntimeError("P480 %s drift count=%d" % (label, src.count(before)))
    return src.replace(before, after, 1)

def link_inventory(tg, d54):
    dt = (tg / R02).read_text()
    if len(re.findall(r'qcom,model\s*=\s*"lito-lagoonmtp-snd-card"', dt)) != 1:
        raise RuntimeError("P480 r02 card model changed")
    platform_match = re.search(r'asoc-platform-names\s*=\s*(.*?);', dt, re.S)
    if not platform_match:
        raise RuntimeError("P480 r02 platform names absent")
    requested = set(re.findall(r'"([^"]+)"', platform_match.group(1)))
    missing = sorted(ALLOWED_PLATFORMS - requested)
    if missing:
        raise RuntimeError("P480 r02 platform contract changed: %s" % missing)
    header = (d54 / "techpack/audio/asoc/msm_dailink.h").read_text()
    links = {}
    for m in re.finditer(r'SND_SOC_DAILINK_DEFS\((\w+),([\s\S]*?)\);', header):
        links[m.group(1)] = m.group(2)
    if set(SELECTED) - set(links):
        raise RuntimeError("P480 5.4 component-array links missing")
    kept = []
    for name in SELECTED:
        block = links[name]
        platforms = re.findall(r'COMP_PLATFORM\("([^"]+)"\)', block)
        if len(platforms) < 1 or not set(platforms).intersection(requested):
            raise RuntimeError("P480 real r02 platform missing from %s" % name)
        kept.append({"id": name, "platforms": platforms})
    # Static analysis of the actual TG Kona group definitions, for the
    # manifest only. Runtime log is emitted from the machine probe.
    src = (tg / "techpack/audio/asoc/kona.c").read_text()
    groups = {}
    for m in re.finditer(
        r'static struct snd_soc_dai_link\s+(\w+)\[\]\s*=\s*\{([\s\S]*?)\n\};', src):
        body = m.group(2)
        groups[m.group(1)] = {
            "link_decl_names": re.findall(r'\.name\s*=\s*("[^"]+"|[A-Z_0-9]+)', body),
            "count": len(re.findall(r'\.name\s*=', body))
        }
    return {"card": "lito-lagoonmtp-snd-card",
            "r02_platform_names": sorted(requested),
            "selected_link_ids": kept,
            "selected_link_count": len(kept),
            "TG_link_groups": groups,
            "explicitly_unported": [
                "TAS256x", "WSA amp/macro", "WCD937x", "voice/CVD",
                "Bluetooth/FM", "USB/display", "LSM/Listen"
            ],
            "not_hardware_verified": True}

def adapt_510_pcm(source):
    """Real 5.4 snd_pcm_ops callbacks, adapted to ACK 5.10 component methods.

    Preserve every original callback and its return code. The ACK component
    receives an additional component pointer; do not turn old functions
    into no-op success stubs.
    """
    old = re.compile(r'static const struct snd_pcm_ops msm_pcm_ops = \{[\s\S]*?\n\};')
    matches = list(old.finditer(source))
    if len(matches) != 1:
        raise RuntimeError("P480 expected exactly one PCM ops table")
    callbacks = (
        ("int", "open", "struct snd_pcm_substream *substream",
         "msm_pcm_open(substream)"),
        ("int", "close", "struct snd_pcm_substream *substream",
         "msm_pcm_close(substream)"),
        ("int", "ioctl",
         "struct snd_pcm_substream *substream, unsigned int cmd, void *arg",
         "msm_pcm_ioctl(substream, cmd, (void __user *)arg)"),
        ("int", "hw_params",
         "struct snd_pcm_substream *substream, struct snd_pcm_hw_params *params",
         "msm_pcm_hw_params(substream, params)"),
        ("int", "prepare", "struct snd_pcm_substream *substream",
         "msm_pcm_prepare(substream)"),
        ("int", "trigger", "struct snd_pcm_substream *substream, int cmd",
         "msm_pcm_trigger(substream, cmd)"),
        ("snd_pcm_uframes_t", "pointer", "struct snd_pcm_substream *substream",
         "msm_pcm_pointer(substream)"),
        ("int", "copy_user",
         "struct snd_pcm_substream *substream, int channel, unsigned long pos, "
         "void __user *buf, unsigned long bytes",
         "msm_pcm_copy(substream, channel, pos, buf, bytes)"),
        ("int", "mmap",
         "struct snd_pcm_substream *substream, struct vm_area_struct *vma",
         "msm_pcm_mmap(substream, vma)"),
    )
    wrappers = "\n/* P480: real PCM callbacks translated to ACK 5.10 ASoC. */\n"
    for ret, name, params, call in callbacks:
        wrappers += ("static %s p480_pcm_%s(struct snd_soc_component *component, "
                     "%s)\n{\n\treturn %s;\n}\n" %
                     (ret, name, params, call))
    wrappers += (
        "static int p480_pcm_construct(struct snd_soc_component *component,\n"
        "\t\tstruct snd_soc_pcm_runtime *rtd)\n"
        "{\n\treturn msm_asoc_pcm_new(rtd);\n}\n"
    )
    # The constructor's target function is defined after the old ops table:
    # avoid an implicit declaration with an exact prototype.
    wrappers = (
        "static int msm_asoc_pcm_new(struct snd_soc_pcm_runtime *rtd);\n" +
        wrappers
    )
    source = source[:matches[0].start()] + wrappers + source[matches[0].end():]
    old_component = (
        "\t.ops\t\t= &msm_pcm_ops,\n"
        "\t.pcm_new\t= msm_asoc_pcm_new,"
    )
    if source.count(old_component) != 1:
        raise RuntimeError("P480 PCM 5.4 component ops layout drift")
    component_ops = "\n".join(
        "\t.%s = p480_pcm_%s," % (name, name)
        for _, name, _, _ in callbacks
    ) + "\n\t.pcm_construct = p480_pcm_construct,"
    source = source.replace(old_component, component_ops, 1)
    if ".pcm_new" in source or "=&msm_pcm_ops" in source:
        raise RuntimeError("P480 old PCM component API survived")
    return source


def adapt_510_afe(source):
    """Keep real AFE callbacks and migrate single CPU DAI access to 5.10."""
    # The pinned 5.4 AFE provider uses the removed rtd->cpu_dai member.
    # 5.10 stores DAIs in arrays accessed with asoc_rtd_to_cpu().
    legacy = "rtd->cpu_dai"
    if source.count(legacy) != 6:
        raise RuntimeError("P480 pinned AFE CPU DAI ABI drift")
    source = source.replace(legacy, "asoc_rtd_to_cpu(rtd, 0)")
    old = re.compile(r'static const struct snd_pcm_ops msm_afe_ops = \{[\s\S]*?\n\};')
    m = list(old.finditer(source))
    if len(m) != 1:
        raise RuntimeError("P480 AFE donor ops table drift")
    funcs = (
        ("int", "open", "struct snd_pcm_substream *substream",
         "msm_afe_open(substream)"),
        ("int", "close", "struct snd_pcm_substream *substream",
         "msm_afe_close(substream)"),
        ("int", "hw_params",
         "struct snd_pcm_substream *substream, struct snd_pcm_hw_params *params",
         "msm_afe_hw_params(substream, params)"),
        ("int", "prepare", "struct snd_pcm_substream *substream",
         "msm_afe_prepare(substream)"),
        ("int", "trigger", "struct snd_pcm_substream *substream, int cmd",
         "msm_afe_trigger(substream, cmd)"),
        ("snd_pcm_uframes_t", "pointer", "struct snd_pcm_substream *substream",
         "msm_afe_pointer(substream)"),
        ("int", "copy_user",
         "struct snd_pcm_substream *substream, int channel, unsigned long pos, "
         "void __user *buf, unsigned long bytes",
         "msm_afe_copy(substream, channel, pos, buf, bytes)"),
        ("int", "mmap",
         "struct snd_pcm_substream *substream, struct vm_area_struct *vma",
         "msm_afe_mmap(substream, vma)"),
    )
    wrappers = (
        "static int msm_asoc_pcm_new(struct snd_soc_pcm_runtime *rtd);\n"
        "/* P480: actual 5.4 AFE callbacks with 5.10 component prototypes. */\n"
    )
    for ret, name, params, call in funcs:
        wrappers += ("static %s p480_afe_%s(struct snd_soc_component *component, "
                     "%s)\n{\n\treturn %s;\n}\n" %
                     (ret, name, params, call))
    wrappers += (
        "static int p480_afe_construct(struct snd_soc_component *component,\n"
        "\t\tstruct snd_soc_pcm_runtime *rtd)\n"
        "{\n\treturn msm_asoc_pcm_new(rtd);\n}\n"
    )
    source = source[:m[0].start()] + wrappers + source[m[0].end():]
    oldcomp = "\t.ops\t\t= &msm_afe_ops,\n\t.pcm_new\t= msm_asoc_pcm_new,"
    if source.count(oldcomp) != 1:
        raise RuntimeError("P480 AFE component donor drift")
    adapted = "\n".join("\t.%s = p480_afe_%s," % (name, name)
                        for _, name, _, _ in funcs)
    source = source.replace(oldcomp,
        adapted + "\n\t.pcm_construct = p480_afe_construct,", 1)
    return source


def adapt_510_hostless(source):
    """Bridge the real hostless prepare and CPU latency QoS API to 5.10."""
    # Pinned 5.4 removes the PCM substream's CPU latency request using
    # pm_qos_remove_request(). ACK 5.10 renamed this CPU-scoped helper.
    old_qos = "pm_qos_remove_request(&substream->latency_pm_qos_req);"
    if source.count(old_qos) != 1:
        raise RuntimeError("P480 pinned hostless CPU latency QoS call drift")
    source = source.replace(
        old_qos,
        "cpu_latency_qos_remove_request(&substream->latency_pm_qos_req);", 1)
    pcm_header = "#include <sound/pcm.h>"
    if source.count(pcm_header) != 1:
        raise RuntimeError("P480 hostless PCM header drift")
    source = source.replace(
        pcm_header, "#include <linux/pm_qos.h>\n" + pcm_header, 1)
    old = re.compile(r'static const struct snd_pcm_ops msm_pcm_hostless_ops = '
                     r'\{[\s\S]*?\n\};')
    m = list(old.finditer(source))
    if len(m) != 1:
        raise RuntimeError("P480 hostless PCM donor ops drift")
    wrapper = (
        "static int p480_hostless_prepare(struct snd_soc_component *component,\n"
        "\t\tstruct snd_pcm_substream *substream)\n"
        "{\n\treturn msm_pcm_hostless_prepare(substream);\n}\n"
    )
    source = source[:m[0].start()] + wrapper + source[m[0].end():]
    oldcomp = "\t.ops\t\t= &msm_pcm_hostless_ops,"
    if source.count(oldcomp) != 1:
        raise RuntimeError("P480 hostless component donor drift")
    source = source.replace(oldcomp,
                            "\t.prepare = p480_hostless_prepare,", 1)
    return source


def compress_compat_header(d54):
    """Use exact 5.4 donor extension values; never overwrite global ACK UAPI."""
    params = (d54 / "include/uapi/sound/compress_params.h").read_text()
    offload = (d54 / "include/uapi/sound/compress_offload.h").read_text()
    needed = (
        "SND_AUDIOCODEC_AC3", "SND_AUDIOCODEC_EAC3", "SND_AUDIOCODEC_DTS",
        "SND_AUDIOCODEC_MP2", "SND_AUDIOCODEC_TRUEHD",
        "SNDRV_COMPRESS_RENDER_MODE_AUDIO_MASTER",
        "SNDRV_COMPRESS_RENDER_MODE_STC_MASTER",
        "SNDRV_COMPRESS_CLK_REC_MODE_NONE",
        "SNDRV_COMPRESS_CLK_REC_MODE_AUTO",
        "COMPRESSED_TIMESTAMP_FLAG",
    )
    src = params + "\n" + offload
    text = ("/* SPDX-License-Identifier: GPL-2.0-only */\n"
            "/* P480: exact SM7325 compression extension ABI constants.\n"
            " * Private to the A3c driver. Do not change the GKI kernel UAPI.\n"
            " */\n"
            "#ifndef __P480_COMPRESS_ABI_H\n"
            "#define __P480_COMPRESS_ABI_H\n"
            "#include <linux/types.h>\n")
    for name in needed:
        m = re.findall(r"(?m)^#define\s+" + name + r"\s+([^\n]+)", src)
        if len(m) != 1:
            raise RuntimeError("P480 pinned compression extension absent " + name)
        text += "#ifndef %s\n#define %s %s\n#endif\n" % (name, name, m[0])
    # These enum values extend 5.10 compressed-audio metadata. Keep the
    # definitions private so the global GKI UAPI remains unchanged.
    for key, value in (
        ("SNDRV_COMPRESS_PATH_DELAY", 3),
        ("SNDRV_COMPRESS_RENDER_MODE", 4),
        ("SNDRV_COMPRESS_CLK_REC_MODE", 5),
        ("SNDRV_COMPRESS_RENDER_WINDOW", 6),
        ("SNDRV_COMPRESS_START_DELAY", 7),
        ("SNDRV_COMPRESS_ENABLE_ADJUST_SESSION_CLOCK", 8),
        ("SNDRV_COMPRESS_ADJUST_SESSION_CLOCK", 9),
    ):
        if not re.search(r"\b" + key + r"\s*=\s*" + str(value) + r"\s*,",
                         offload):
            raise RuntimeError("P480 pinned compress metadata key drift " + key)
        text += "#ifndef %s\n#define %s %d\n#endif\n" % (key, key, value)

    # DSP_POSITION is a separate donor macro, not an enum member.
    if not re.search(r"(?m)^#define\s+SNDRV_COMPRESS_DSP_POSITION\s+10\s*$",
                     offload):
        raise RuntimeError("P480 pinned DSP position metadata key drift")
    text += ("#ifndef SNDRV_COMPRESS_DSP_POSITION\n"
             "#define SNDRV_COMPRESS_DSP_POSITION 10\n"
             "#endif\n")
    m = re.search(r"struct snd_codec_metadata \{[\s\S]*?\n\};", params)
    if not m or m.group(0).count("__u32") != 3 or "__u64 timestamp;" not in m.group(0):
        raise RuntimeError("P480 pinned codec buffer metadata ABI drift")
    text += "#ifndef COMPRESSED_TIMESTAMP_FLAG"  # defined above, use separate guard
    text = text[:text.rfind("#ifndef COMPRESSED_TIMESTAMP_FLAG")]
    # mainline 5.10 does not declare this donor-only metadata payload.
    text += m.group(0) + "\n#endif /* __P480_COMPRESS_ABI_H */\n"
    return text


def adapt_510_compress(source):
    """Bridge the real 5.4 snd_compr_ops to 5.10 snd_compress_ops."""
    old = re.compile(r'static struct snd_compr_ops msm_compr_ops = \{[\s\S]*?\n\};')
    matches = list(old.finditer(source))
    if len(matches) != 1:
        raise RuntimeError("P480 missing real donor compress ops")
    callbacks = (
        ("open", "struct snd_compr_stream *stream", "msm_compr_open(stream)"),
        ("free", "struct snd_compr_stream *stream", "msm_compr_free(stream)"),
        ("trigger", "struct snd_compr_stream *stream, int cmd",
         "msm_compr_trigger(stream, cmd)"),
        ("pointer", "struct snd_compr_stream *stream, struct snd_compr_tstamp *ts",
         "msm_compr_pointer(stream, ts)"),
        ("set_params", "struct snd_compr_stream *stream, struct snd_compr_params *params",
         "msm_compr_set_params(stream, params)"),
        ("set_metadata", "struct snd_compr_stream *stream, struct snd_compr_metadata *meta",
         "msm_compr_set_metadata(stream, meta)"),
        ("get_metadata", "struct snd_compr_stream *stream, struct snd_compr_metadata *meta",
         "msm_compr_get_metadata(stream, meta)"),
        ("ack", "struct snd_compr_stream *stream, size_t bytes",
         "msm_compr_ack(stream, bytes)"),
        ("copy", "struct snd_compr_stream *stream, char __user *buf, size_t count",
         "msm_compr_copy(stream, buf, count)"),
        ("get_caps", "struct snd_compr_stream *stream, struct snd_compr_caps *caps",
         "msm_compr_get_caps(stream, caps)"),
        ("get_codec_caps",
         "struct snd_compr_stream *stream, struct snd_compr_codec_caps *codec",
         "msm_compr_get_codec_caps(stream, codec)"),
    )
    wrapper = "\n/* P480: 5.10 component gets an extra pointer. Real callbacks stay. */\n"
    for name, params, call in callbacks:
        wrapper += (
            "static int p480_compr_%s(struct snd_soc_component *component, "
            "%s)\n{\n\treturn %s;\n}\n" % (name, params, call)
        )
    wrapper += "static const struct snd_compress_ops p480_compr_ops = {\n"
    wrapper += "".join("\t.%s = p480_compr_%s,\n" % (name, name)
                       for name, _, _ in callbacks)
    wrapper += "};"
    source = source[:matches[0].start()] + wrapper + source[matches[0].end():]
    old_assign = ".compr_ops\t= &msm_compr_ops,"
    if source.count(old_assign) != 1:
        raise RuntimeError("P480 compress 5.4 component API changed")
    source = source.replace(old_assign, ".compress_ops = &p480_compr_ops,", 1)
    inc = "#include <sound/compress_driver.h>"
    if source.count(inc) != 1:
        raise RuntimeError("P480 compress include anchor drift")
    source = source.replace(inc, inc + '\n#include "p480-compress-abi.h"', 1)
    return source



def adapt_510_dai_mute(source):
    """Bridge the real legacy digital mute callbacks to 5.10.

    In the pinned 5.4 ASoC core, .digital_mute is called for playback
    only. ACK 5.10 expects .mute_stream(dai, mute, stream).
    """
    pairs = (
        ("msm_dai_q6_spk_digital_mute", "p480_spk_mute_stream",
         "static struct snd_soc_dai_ops msm_dai_slimbus_0_rx_ops = {"),
        ("msm_dai_q6_cdc_dma_digital_mute", "p480_cdc_dma_mute_stream",
         "static struct snd_soc_dai_ops msm_dai_q6_cdc_wsa_dma_ops = {"),
    )
    if source.count(".digital_mute =") != len(pairs):
        raise RuntimeError("P480 pinned digital mute tables drift")
    for old, new, anchor in pairs:
        prototype = re.compile(
            r"static int\s+" + old +
            r"\s*\(\s*struct snd_soc_dai\s*\*dai,\s*int mute\s*\)")
        if len(prototype.findall(source)) != 1:
            raise RuntimeError("P480 pinned digital mute signature drift " + old)
        assignment = ".digital_mute = " + old + ","
        if source.count(assignment) != 1 or source.count(anchor) != 1:
            raise RuntimeError("P480 pinned digital mute ops drift " + old)
        wrapper = (
            "/* Keep the original 5.4 playback-only mute behavior. */\n"
            "static int %s(struct snd_soc_dai *dai, int mute, int stream)\n"
            "{\n"
            "\tif (stream != SNDRV_PCM_STREAM_PLAYBACK)\n"
            "\t\treturn -ENOTSUPP;\n"
            "\treturn %s(dai, mute);\n"
            "}\n\n" % (new, old))
        source = source.replace(anchor, wrapper + anchor, 1)
        source = source.replace(
            assignment,
            ".mute_stream = " + new + ",\n\t.no_capture_mute = 1,", 1)
    if ".digital_mute =" in source:
        raise RuntimeError("P480 removed digital mute member survived")
    return source


def adapt_510_dai_aif(source, driver_name):
    """Retain vendor AIF DAPM route names without changing GKI ASoC structs.

    5.4 carries both stream_name and aif_name in snd_soc_pcm_stream,
    while 5.10 exposes only stream_name. Keep the original stream widget
    names and transfer vendor AIF endpoints to a private lookup table.
    """
    if driver_name not in ("msm-dai-q6-v2.c", "msm-dai-fe.c",
                            "msm-dai-stub-v2.c"):
        raise RuntimeError("P480 unexpected AIF adapter driver")
    expected = {"msm-dai-q6-v2.c": (264, 4),
                "msm-dai-fe.c": (185, 2),
                "msm-dai-stub-v2.c": (8, 2)}
    number, per_direction = expected[driver_name]
    pair_re = re.compile(
        r'(?m)^([ \t]*)\.stream_name\s*=\s*"([^"]+)",\s*\n'
        r'[ \t]*\.aif_name\s*=\s*"([^"]+)",')
    pairs = list(pair_re.finditer(source))
    if len(pairs) != number or len(re.findall(
            r'(?m)^[ \t]*\.aif_name\s*=', source)) != number:
        raise RuntimeError("P480 pinned AIF mapping declarations drift " +
                           driver_name)
    names = {}
    for match in pairs:
        stream_name, aif_name = match.group(2, 3)
        if stream_name in names and names[stream_name] != aif_name:
            raise RuntimeError("P480 ambiguous AIF stream " + stream_name)
        names[stream_name] = aif_name
    source = pair_re.sub(
        lambda m: m.group(1) + '.stream_name = "' + m.group(2) + '",',
        source)
    for direction in ("playback", "capture"):
        old = "dai->driver->%s.aif_name" % direction
        if source.count(old) != per_direction:
            raise RuntimeError("P480 AIF route callback drift " + driver_name +
                               " " + direction)
        source = source.replace(
            old, "p480_aif_name(&dai->driver->%s)" % direction)
    if re.search(r'\.aif_name\b', source):
        raise RuntimeError("P480 obsolete snd_soc_pcm_stream.aif_name remains")
    anchors = {
        "msm-dai-fe.c": "static int fe_dai_probe(struct snd_soc_dai *dai)",
        "msm-dai-q6-v2.c":
            "static int msm_dai_q6_dai_add_route(struct snd_soc_dai *dai)",
        "msm-dai-stub-v2.c":
            "static int msm_dai_stub_add_route(struct snd_soc_dai *dai)",
    }
    anchor = anchors[driver_name]
    if source.count(anchor) != 1 or source.count(
            "#include <linux/init.h>") != 1:
        raise RuntimeError("P480 AIF route insertion anchor drift")
    table = (
        "\n/* P480: lossless AIF widget routes from the pinned 5.4 donor. */\n"
        "struct p480_aif_link {\n"
        "\tconst char *stream;\n"
        "\tconst char *aif;\n"
        "};\n"
        "static const struct p480_aif_link p480_aif_links[] = {\n")
    for stream_name, aif_name in names.items():
        table += "\t{%s, %s},\n" % (
            json.dumps(stream_name), json.dumps(aif_name))
    table += (
        "};\n"
        "static const char *p480_aif_name(const struct snd_soc_pcm_stream *s)\n"
        "{\n"
        "\tunsigned int i;\n"
        "\tif (!s || !s->stream_name)\n"
        "\t\treturn NULL;\n"
        "\tfor (i = 0; i < ARRAY_SIZE(p480_aif_links); i++)\n"
        "\t\tif (!strcmp(s->stream_name, p480_aif_links[i].stream))\n"
        "\t\t\treturn p480_aif_links[i].aif;\n"
        "\treturn NULL;\n"
        "}\n\n")
    source = source.replace(anchor, table + anchor, 1)
    source = source.replace(
        "#include <linux/init.h>",
        "#include <linux/kernel.h>\n#include <linux/string.h>\n"
        "#include <linux/init.h>", 1)
    return source


def adapt_510_routing(source):
    """Port all real routing callbacks and PCM lifecycle to 5.10."""
    old_check = "if (cal_data == NULL)"
    if source.count(old_check) != 1 or (
            "static struct cal_type_data *cal_data[MAX_ROUTING_CAL_TYPES];"
            not in source):
        raise RuntimeError("P480 routing calibration pointer guard drift")
    # cal_data is an array, never a nullable pointer. Check the actual
    # calibration entries before the DSP topology lookups instead.
    source = source.replace(
        old_check, "if (!cal_data[ADM_LSM_TOPOLOGY_CAL_TYPE_IDX] ||\n"
        "\t    !cal_data[ADM_TOPOLOGY_CAL_TYPE_IDX])", 1)
    ops = re.compile(
        r'static const struct snd_pcm_ops msm_routing_pcm_ops = \{'
        r'[\s\S]*?\n\};')
    matches = list(ops.finditer(source))
    if len(matches) != 1 or any(
            name not in matches[0].group(0)
            for name in ("msm_pcm_routing_hw_params",
                         "msm_pcm_routing_close",
                         "msm_pcm_routing_prepare")):
        raise RuntimeError("P480 routing PCM callback table drift")
    source = source[:matches[0].start()] + (
        "/* PCM callbacks are bridged to component methods below. */"
    ) + source[matches[0].end():]
    anchor = "static struct snd_soc_component_driver msm_soc_routing_component = {"
    if source.count(anchor) != 1 or any(
            source.count(x) != 1 for x in (
                "\t.ops\t\t= &msm_routing_pcm_ops,",
                "\t.pcm_new\t= msm_routing_pcm_new,",
                "\t.pcm_free\t= msm_routing_pcm_free,")):
        raise RuntimeError("P480 routing component driver ABI drift")
    wrappers = (
        "/* P480: call the real 5.4 routing engine via 5.10 component ABI. */\n"
        "static int p480_routing_hw_params(struct snd_soc_component *c,\n"
        "\tstruct snd_pcm_substream *s, struct snd_pcm_hw_params *p)\n"
        "{\n\treturn msm_pcm_routing_hw_params(s, p);\n}\n"
        "static int p480_routing_close(struct snd_soc_component *c,\n"
        "\tstruct snd_pcm_substream *s)\n"
        "{\n\treturn msm_pcm_routing_close(s);\n}\n"
        "static int p480_routing_prepare(struct snd_soc_component *c,\n"
        "\tstruct snd_pcm_substream *s)\n"
        "{\n\treturn msm_pcm_routing_prepare(s);\n}\n"
        "static int p480_routing_construct(struct snd_soc_component *c,\n"
        "\tstruct snd_soc_pcm_runtime *rtd)\n"
        "{\n\treturn msm_routing_pcm_new(rtd);\n}\n"
        "static void p480_routing_destruct(struct snd_soc_component *c,\n"
        "\tstruct snd_pcm *pcm)\n"
        "{\n\tmsm_routing_pcm_free(pcm);\n}\n\n"
    )
    source = source.replace(anchor, wrappers + anchor, 1)
    source = source.replace(
        "\t.ops\t\t= &msm_routing_pcm_ops,",
        "\t.hw_params = p480_routing_hw_params,\n"
        "\t.close = p480_routing_close,\n"
        "\t.prepare = p480_routing_prepare,", 1)
    source = source.replace(
        "\t.pcm_new\t= msm_routing_pcm_new,",
        "\t.pcm_construct = p480_routing_construct,", 1)
    source = source.replace(
        "\t.pcm_free\t= msm_routing_pcm_free,",
        "\t.pcm_destruct = p480_routing_destruct,", 1)
    return source

def adapt_header(content):
    """Drop only false WCD937x and missing SWR-DMIC alternatives.
    Preserve actual WCD938x/RX/TX/VA codec entries. No dummy replacements.
    """
    for name in BE_IDS[:6]:
        pat = r'(SND_SOC_DAILINK_DEFS\(' + name + r',)([\s\S]*?)(\);)'
        m = re.search(pat, content)
        if not m:
            raise RuntimeError("P480 missing pinned WCD938x link: " + name)
        body = m.group(2)
        before = body
        body = re.sub(r',\s*COMP_CODEC\("wcd937x_codec",\s*"wcd937x_cdc"\)', '', body)
        if name == "tx_dma_tx4":
            body = re.sub(
                r',\s*COMP_CODEC\("swr-dmic\.\d+",\s*"swr_dmic_tx\d+"\)', '', body)
        if body == before or '"wcd938x_codec"' not in body:
            raise RuntimeError("P480 WCD938x-only codec array conversion failed " + name)
        content = content[:m.start()] + m.group(1) + body + m.group(3) + content[m.end():]
    return content

def wrap_real_platform_probes(source, file_id):
    """Log errno from the real platform probe, never replace its body."""
    pattern = re.compile(r'static struct platform_driver\s+(\w+)\s*=\s*\{([\s\S]*?)\n\};')
    drivers = list(pattern.finditer(source))
    if not drivers:
        # routing-v2 and other helpers can be component registration only.
        return source, []
    old = source
    insertions = []
    probes = []
    for n, m in enumerate(drivers):
        body = m.group(2)
        pm = re.search(r'\.probe\s*=\s*(\w+)\s*,', body)
        if not pm:
            continue
        fn = pm.group(1)
        if not re.search(r'\b(?:static\s+)?int\s+' + fn +
                         r'\s*\(\s*struct platform_device\s*\*', source):
            raise RuntimeError("P480 %s real platform probe signature missing %s" %
                               (file_id, fn))
        wrapper = "p480_probe_%s_%d" % (file_id.replace('-', '_'), n)
        driver_begin = m.group(0)
        changed = driver_begin.replace(pm.group(0),
                                       pm.group(0).replace(fn, wrapper), 1)
        inserted = (
            'static int %s(struct platform_device *pdev)\n'
            '{\n'
            '\tint rc = %s(pdev);\n'
            '\tdev_info(&pdev->dev, "P480 A3c PART %s probe rc=%%d\\n", rc);\n'
            '\treturn rc;\n'
            '}\n'
            % (wrapper, fn, m.group(1).upper())
        )
        insertions.append((m.start(), driver_begin, inserted + changed))
        probes.append(m.group(1).upper())
    for pos, before, after in reversed(insertions):
        if source[pos:pos + len(before)] != before:
            raise RuntimeError("P480 platform driver changed unexpectedly")
        source = source[:pos] + after + source[pos + len(before):]
    if source == old:
        raise RuntimeError("P480 no real probe wrappers in " + file_id)
    return source, probes

FILTER = r"""
/* P480_A3C_NATIVE_WCD938X_KONA_V1
 * No unsupported physical codec is replaced with snd-soc-dummy.
 * The stock FE-only virtual codec remains the normal ASoC FE endpoint.
 */
static int p480_skipped;
static const char *p480_skip_reason(const struct snd_soc_dai_link *l)
{
    const char *n = l->name ? l->name : "";
    const char *p = (l->num_platforms && l->platforms[0].name)
                    ? l->platforms[0].name : "";
    unsigned int k;
    static const char * const unsupported[] = {
        "Voice", "VOICE", "VoIP", "VOIP", "InCall", "INCALL",
        "Listen", "LISTEN", "WSA", "wsa", "TAS256", "tas256",
        "SLIMBUS", "slimbus", "Bluetooth", "BT", "DISPLAY",
        "Display", "HDMI", "USB", "CVD", "cvd"
    };
    static const char * const platforms[] = {
        "msm-pcm-dsp.0", "msm-pcm-dsp.1", "msm-pcm-dsp.2",
        "msm-compress-dsp", "msm-pcm-hostless", "msm-pcm-afe",
        "msm-pcm-routing", "msm-pcm-dsp-noirq", "msm-compr-dsp"
    };
    bool valid = false;
    for (k = 0; k < ARRAY_SIZE(unsupported); k++)
        if (strstr(n, unsupported[k]))
            return "UNPORTED_OR_VOICE_LINK";
    for (k = 0; k < ARRAY_SIZE(platforms); k++)
        if (!strcmp(p, platforms[k]))
            valid = true;
    if (!valid)
        return "PLATFORM_NOT_PORTED";
    for (k = 0; k < l->num_codecs; k++) {
        const char *c = l->codecs[k].name;
        if (!c)
            continue;
        if (strstr(c, "wsa") || strstr(c, "tas") ||
            strstr(c, "wcd937x") || strstr(c, "swr-dmic") ||
            strstr(c, "btfmslim") || strstr(c, "ext-disp") ||
            strstr(c, "swr-haptics"))
            return "PHYSICAL_CODEC_NOT_PORTED";
    }
    return NULL;
}
static void p480_filter_links(struct snd_soc_card *card)
{
    int i, used = 0;
    p480_skipped = 0;
    for (i = 0; i < card->num_links; i++) {
        struct snd_soc_dai_link *l = &card->dai_link[i];
        const char *reason = p480_skip_reason(l);
        if (reason) {
            dev_info(card->dev,
                "P480 A3c LINK_SKIPPED name=%s reason=%s\n",
                l->name ? l->name : "UNNAMED", reason);
            p480_skipped++;
            continue;
        }
        if (i != used)
            card->dai_link[used] = *l;
        used++;
    }
    card->num_links = used;
}
static void p480_log_real_device_counts(struct snd_soc_card *card)
{
    int pcm = 0, compress = 0;
    struct snd_device *item;
    if (!card->snd_card)
        return;
    list_for_each_entry(item, &card->snd_card->devices, list) {
        if (item->type == SNDRV_DEV_PCM)
            pcm++;
        if (item->type == SNDRV_DEV_COMPRESS)
            compress++;
    }
    dev_info(card->dev, "P480 A3c DEVICES pcm=%d compress=%d\n",
             pcm, compress);
}
"""

def adapt_machine(source):
    if '#include "msm_dailink.h"' not in source:
        raise RuntimeError("P480 Kona component array ABI missing")
    # The pinned 5.4 card uses single DAI fields removed from the
    # 5.10 runtime struct. Use the first CPU and codec DAI explicitly.
    if source.count("rtd->cpu_dai") != 12:
        raise RuntimeError("P480 pinned Kona CPU DAI ABI drift")
    if source.count("rtd->codec_dai") != 5:
        raise RuntimeError("P480 pinned Kona codec DAI ABI drift")
    source = source.replace("rtd->cpu_dai", "asoc_rtd_to_cpu(rtd, 0)")
    source = source.replace("rtd->codec_dai", "asoc_rtd_to_codec(rtd, 0)")
    # Exclude the physical WSA speaker AUX devices but keep the real
    # WCD938x AUX device needed by the headset microphone path.
    source = one(source,
        '\t/* Get maximum WSA device count for this platform */',
        '\t/* P480: speaker AUX is not ported. */\n'
        '\tdev_info(&pdev->dev, "P480 A3c LINK_SKIPPED name=WSA_AUX reason=PHYSICAL_CODEC_NOT_PORTED\\n");\n'
        '\tgoto codec_aux_dev;\n'
        '\t/* Get maximum WSA device count for this platform */',
        "WSA AUX bypass")
    # Link platform names become null after OF phandle conversion.
    # Therefore filter the real FE/BE links before that conversion.
    populate = 'ret = msm_populate_dai_link_component_of_node(card);'
    source = one(source, populate,
        'p480_filter_links(card);\n'
        '\tif (!card->num_links) {\n'
        '\t\tret = -ENODEV;\n'
        '\t\tgoto err;\n'
        '\t}\n'
        '\t' + populate,
        "filter before OF conversion")
    reg = 'ret = devm_snd_soc_register_card(&pdev->dev, card);'
    source = one(source, reg,
        reg + '\n'
        '\tdev_info(&pdev->dev,\n'
        '\t\t"P480 A3c CARD register rc=%d name=%s links=%d skipped=%d\\n",\n'
        '\t\tret, card->name, card->num_links, p480_skipped);\n'
        '\tif (!ret)\n'
        '\t\tp480_log_real_device_counts(card);',
        "card real registration")
    anchor = 'static int msm_asoc_machine_probe(struct platform_device *pdev)'
    return one(source, anchor, FILTER + '\n' + anchor, "real Kona machine")

def stage(root, tg, d54, report):
    pin(tg, TG_SHA, "TouchGrass")
    pin(d54, D54_SHA, "SM7325")
    inventory = link_inventory(tg, d54)
    if (root / TARGET).exists():
        raise RuntimeError("P480 A3c already staged")
    donor = d54 / "techpack/audio/asoc"
    dest = root / TARGET
    dest.mkdir(parents=True)
    for p in PROVIDERS + ("kona.c",):
        source = donor / p
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError("P480 real donor source missing/empty " + p)
        output = dest / p
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, output)
    # Real 5.4/5.10-style component arrays; remove only absent alternatives.
    (dest / "msm_dailink.h").write_text(adapt_header(
        (donor / "msm_dailink.h").read_text()))
    for hdr in donor.glob("*.h"):
        if hdr.name != "msm_dailink.h":
            shutil.copy2(hdr, dest / hdr.name)
    # Import only real pinned codec API headers needed by Kona.
    # In particular WCD938x is the selected A52 physical codec.
    # Do not import unported WSA/WCD937x implementations.
    for rel in ("codecs/wsa881x.h", "codecs/wsa883x/wsa883x.h",
                "codecs/wcd937x/wcd937x.h",
                "codecs/wcd937x/wcd937x-mbhc.h",
                "codecs/wcd938x/wcd938x.h",
                "codecs/wcd938x/wcd938x-mbhc.h"):
        frm = donor / rel
        if not frm.is_file():
            raise RuntimeError("P480 pinned machine header missing " + rel)
        to = dest / rel
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frm, to)
    (dest / "p480-compress-abi.h").write_text(compress_compat_header(d54))
    log_names = {}
    for name in PROVIDERS:
        f = dest / name
        if name == "msm-pcm-routing-v2.c":
            # This large pinned file is a real 1.7MB routing engine.
            if f.stat().st_size < 500_000:
                raise RuntimeError("P480 truncated real routing provider")
        src = f.read_text()
        if name in ("msm-pcm-q6-v2.c", "msm-pcm-q6-noirq.c"):
            src = adapt_510_pcm(src)
        if name == "msm-pcm-afe-v2.c":
            src = adapt_510_afe(src)
        if name == "msm-pcm-hostless.c":
            src = adapt_510_hostless(src)
        if name == "msm-compress-q6-v2.c":
            src = adapt_510_compress(src)
        if name in ("msm-dai-fe.c", "msm-dai-q6-v2.c",
                    "msm-dai-stub-v2.c"):
            src = adapt_510_dai_aif(src, name)
        if name == "msm-dai-q6-v2.c":
            src = adapt_510_dai_mute(src)
        if name == "msm-pcm-routing-v2.c":
            src = adapt_510_routing(src)
        if name == "platform_init.c":
            # The 5.4 all-platform initializer calls unported voice,
            # CVD, HDMI and LSM functions. Never import that behavior.
            src = P480_PLATFORM_INIT
        if "snd_soc_component_read32(" in src:
            src = src.replace("snd_soc_component_read32(",
                              "snd_soc_component_read(")
        src, names = wrap_real_platform_probes(
            src, Path(name).stem)
        if names:
            log_names[name] = names
        f.write_text(src)
    machine = dest / "kona.c"
    machine.write_text(adapt_machine(machine.read_text()))
    # Build against the real pinned A3b vendor UAPI header tree.
    # Never add synthetic empty declarations to make compilation pass.
    uapi = root / ROOT / "a3b/include/uapi/audio"
    for header in ("linux/msm_audio.h", "sound/audio_effects.h",
                   "sound/audio_compressed_formats.h"):
        if not (uapi / header).is_file():
            raise RuntimeError("P480 required real 5.4 vendor header missing " + header)
    # P480 exact SM7325 5.4 ION declarations, privately scoped to A3c.
    # These are API headers only. Do not enable CONFIG_ION_MSM_HEAPS,
    # replace the P479 allocator, or create a fake ION backend.
    for original, relative in (
        ("include/linux/msm_ion.h", "linux/msm_ion.h"),
        ("include/uapi/linux/msm_ion.h", "uapi/linux/msm_ion.h"),
        ("include/uapi/linux/msm_ion_ids.h", "linux/msm_ion_ids.h"),
    ):
        src = d54 / original
        if not src.is_file():
            raise RuntimeError("P480 pinned ION declaration absent " + original)
        out = dest / "include" / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    for original, sha in (
        ("linux/msm_ion.h", "struct ion_prefetch_region"),
        ("uapi/linux/msm_ion.h", "ION_FLAGS_CP_MASK"),
        ("linux/msm_ion_ids.h", "ION_ADSP_HEAP_ID"),
    ):
        if sha not in (dest / "include" / original).read_text():
            raise RuntimeError("P480 pinned ION ABI declaration drift " + original)
    # 5.4 A3b and TG A3a provide the actual header API declarations.
    mk = r"""# P480_A3C_NATIVE_WCD938X_KONA_V1
# A3c-specific real donor ION declarations precede public A3b includes.
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3c/include
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include
# The pinned A3b donor carries TG/QCOM UAPI headers in include/uapi/audio/.
# Add its root so <audio/linux/msm_audio.h> and
# <audio/sound/audio_effects.h> resolve to genuine donor declarations.
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include/uapi
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3b/include/uapi/audio
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/include/uapi
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3c
subdir-ccflags-y += -I$(srctree)/drivers/soc/qcom/p472_tg_audio/a3c/codecs
subdir-ccflags-y += -DCONFIG_SND_SOC_QDSP6V2=1
# The genuine msm-qti-pp-config.o is built into A3c. Its donor header must
# expose the matching real functions, not the CONFIG_QTI_PP=n inline stubs.
# Scope this feature selection to A3c only and keep P480_A3C default n.
subdir-ccflags-y += -DCONFIG_QTI_PP=1
obj-$(CONFIG_P480_A3C) += msm-pcm-q6-v2.o msm-compress-q6-v2.o
obj-$(CONFIG_P480_A3C) += msm-pcm-hostless.o msm-pcm-afe-v2.o msm-pcm-q6-noirq.o
obj-$(CONFIG_P480_A3C) += msm-pcm-routing-v2.o msm-pcm-routing-devdep.o
obj-$(CONFIG_P480_A3C) += msm-dai-q6-v2.o msm-dai-fe.o msm-dai-stub-v2.o
obj-$(CONFIG_P480_A3C) += msm-audio-effects-q6-v2.o msm-qti-pp-config.o
obj-$(CONFIG_P480_A3C) += platform_init.o kona.o codecs/
"""
    (dest / "Makefile").write_text(mk)
    (dest / "codecs/Makefile").write_text(
        "obj-$(CONFIG_P480_A3C) += msm_stub.o\n")
    audiomk = root / ROOT / "Makefile"
    audiomk.write_text(one(audiomk.read_text(),
        "obj-$(CONFIG_P472_A3B_B1) += a3b/",
        "obj-$(CONFIG_P472_A3B_B1) += a3b/\n"
        "obj-$(CONFIG_P480_A3C) += a3c/",
        "native A3c Kbuild directory"))
    kcfg = root / "drivers/soc/qcom/Kconfig"
    kcfg.write_text(kcfg.read_text() + r"""
config P480_A3C
    bool "P480 native Q6 PCM/compress/DAI and A52 Kona WCD938x card"
    depends on P472_A3B_B3 && P472_A3A_Q6 && SND_SOC
    default n
    help
      A3c only. Build pinned 5.4/5.10 ASoC providers and real Kona.
      No WSA, TAS256x or voice. Does not change P479 charging/H0.
""")
    inventory["real_provider_sources"] = list(PROVIDERS)
    inventory["real_provider_probe_wrappers"] = log_names
    inventory["machine_source"] = "Samsung SM7325 5.4 Kona adapted with pinned TG r02 contract"
    inventory["A3c_hardware_verified"] = False
    inventory["fallback_unchanged_when_CONFIG_P480_A3C_n"] = True
    inventory["no_voice_init"] = True
    inventory["no_TAS256x"] = True
    inventory["no_EFS_ACDB_TAS_writes_added"] = True
    inventory["p480_native_link_verified"] = False
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    check(root)

def check(root):
    dest = root / TARGET
    k = (root / "drivers/soc/qcom/Kconfig").read_text()
    s = (dest / "kona.c").read_text()
    if "config P480_A3C" not in k or "default n" not in k.split(
            "config P480_A3C", 1)[1].split("config ", 1)[0]:
        raise RuntimeError("P480 must default OFF")
    for marker in (MARK, "P480 A3c CARD register rc=%d name=%s links=%d skipped=%d",
                   "P480 A3c LINK_SKIPPED name=%s reason=%s",
                   "P480 A3c DEVICES pcm=%d compress=%d",
                   "devm_snd_soc_register_card(&pdev->dev, card);"):
        if marker not in s:
            raise RuntimeError("P480 real Kona marker missing " + marker)
    for rel in ("linux/msm_ion.h", "uapi/linux/msm_ion.h",
                "linux/msm_ion_ids.h"):
        if not (dest / "include" / rel).is_file():
            raise RuntimeError("P480 pinned ION donor header missing " + rel)
    for rel, required in (
        ("codecs/wcd938x/wcd938x.h", "WCD938X_DRV_NAME"),
        ("codecs/wcd938x/wcd938x-mbhc.h", "wcd938x_mbhc_hs_detect"),
    ):
        header = dest / rel
        if not header.is_file() or required not in header.read_text():
            raise RuntimeError("P480 genuine WCD938x Kona header missing " + rel)
    pcm=(dest / "msm-pcm-q6-v2.c").read_text()
    compr=(dest / "msm-compress-q6-v2.c").read_text()
    # No local stubs may shadow the built-in QTI PP provider definitions.
    makefile = (dest / "Makefile").read_text()
    pp_h = (dest / "msm-qti-pp-config.h").read_text()
    pp_c = (dest / "msm-qti-pp-config.c").read_text()
    if ("subdir-ccflags-y += -DCONFIG_QTI_PP=1" not in makefile or
            "msm-qti-pp-config.o" not in makefile or
            "#ifdef CONFIG_QTI_PP" not in pp_h):
        raise RuntimeError("P480 genuine QTI PP built-in feature guard missing")
    for fn in ("msm_adsp_init_mixer_ctl_pp_event_queue",
               "msm_adsp_clean_mixer_ctl_pp_event_queue",
               "msm_adsp_inform_mixer_ctl",
               "msm_adsp_stream_cmd_info",
               "msm_adsp_stream_callback_get",
               "msm_adsp_stream_callback_info"):
        if "int " + fn + "(" not in pp_c:
            raise RuntimeError("P480 genuine QTI PP function absent " + fn)
    if ".pcm_construct = p480_pcm_construct" not in pcm:
        raise RuntimeError("P480 real PCM component callback bridge missing")
    for filename, needle in (
        ("msm-pcm-q6-noirq.c", ".pcm_construct = p480_pcm_construct"),
        ("msm-pcm-afe-v2.c", ".pcm_construct = p480_afe_construct"),
        ("msm-pcm-hostless.c", ".prepare = p480_hostless_prepare"),
    ):
        if needle not in (dest / filename).read_text():
            raise RuntimeError("P480 real AFE/noirq/hostless component API bridge missing " + filename)
    afe = (dest / "msm-pcm-afe-v2.c").read_text()
    if ("rtd->cpu_dai" in afe or
            afe.count("asoc_rtd_to_cpu(rtd, 0)") != 6):
        raise RuntimeError("P480 5.10 AFE CPU DAI accessor bridge missing")
    if ("rtd->cpu_dai" in s or "rtd->codec_dai" in s or
            s.count("asoc_rtd_to_cpu(rtd, 0)") != 12 or
            s.count("asoc_rtd_to_codec(rtd, 0)") != 5):
        raise RuntimeError("P480 5.10 Kona CPU/codec DAI accessor bridge missing")
    if ".compress_ops = &p480_compr_ops" not in compr:
        raise RuntimeError("P480 real compress callback bridge missing")
    for driver_name, expected in (("msm-dai-fe.c", 185),
                                  ("msm-dai-q6-v2.c", 264),
                                  ("msm-dai-stub-v2.c", 8)):
        dai = (dest / driver_name).read_text()
        header = "static const struct p480_aif_link p480_aif_links[] = {"
        if dai.count(header) != 1:
            raise RuntimeError("P480 private AIF table missing " + driver_name)
        table = dai.split(header, 1)[1].split("};", 1)[0]
        if (table.count("\n\t{") != expected or
                "p480_aif_name(" not in dai or
                re.search(r'\.aif_name\b', dai)):
            raise RuntimeError("P480 native AIF routes missing " + driver_name)
    dai_q6 = (dest / "msm-dai-q6-v2.c").read_text()
    if (".digital_mute =" in dai_q6 or
            dai_q6.count(".no_capture_mute = 1,") != 2):
        raise RuntimeError("P480 DAI playback-only mute ABI bridge missing")
    for cb in ("p480_spk_mute_stream", "p480_cdc_dma_mute_stream"):
        if dai_q6.count(".mute_stream = " + cb + ",") != 1:
            raise RuntimeError("P480 5.10 mute_stream missing " + cb)
    routing = (dest / "msm-pcm-routing-v2.c").read_text()
    for method in (".hw_params = p480_routing_hw_params",
                   ".close = p480_routing_close",
                   ".prepare = p480_routing_prepare",
                   ".pcm_construct = p480_routing_construct",
                   ".pcm_destruct = p480_routing_destruct"):
        if method not in routing:
            raise RuntimeError("P480 routing component callback bridge missing " + method)
    if ("if (cal_data == NULL)" in routing or
            "if (!cal_data[ADM_LSM_TOPOLOGY_CAL_TYPE_IDX]" not in routing):
        raise RuntimeError("P480 routing real calibration guard missing")
    if "SND_AUDIOCODEC_AC3" not in (dest / "p480-compress-abi.h").read_text():
        raise RuntimeError("P480 pinned compress ABI absent")
    hostless = (dest / "msm-pcm-hostless.c").read_text()
    if ("cpu_latency_qos_remove_request(&substream->latency_pm_qos_req)"
            not in hostless or
            "pm_qos_remove_request(" in hostless or
            "#include <linux/pm_qos.h>" not in hostless):
        raise RuntimeError("P480 hostless CPU latency QoS 5.10 bridge missing")
    init=(dest / "platform_init.c").read_text()
    for forbidden in ("msm_voice_host_init(", "msm_pcm_voice_init(",
                      "msm_pcm_voip_init(", "msm_lsm_client_init(",
                      "msm_dai_q6_hdmi_init(", "msm_transcode_loopback_init("):
        if forbidden in init:
            raise RuntimeError("P480 forbidden voice/nonported initializer "+forbidden)
    for required in ("msm_compress_dsp_init(", "msm_fe_dai_init(",
                     "msm_dai_q6_init(", "msm_pcm_dsp_init(",
                     "msm_soc_routing_platform_init("):
        if required not in init:
            raise RuntimeError("P480 required real platform init absent "+required)
    if "obj-$(CONFIG_P480_A3C) += a3c/" not in (
            root / ROOT / "Makefile").read_text():
        raise RuntimeError("P480 native Kbuild missing")
    if "CONFIG_P480_A3C" not in (dest / "Makefile").read_text():
        raise RuntimeError("P480 real providers not selected")
    selected = (dest / "msm_dailink.h").read_text()
    for nm in BE_IDS:
        match = re.search(r'SND_SOC_DAILINK_DEFS\(' + nm +
                          r',([\s\S]*?)\);', selected)
        if not match or ('"wcd938x_codec"' not in match.group(1)
                         and nm not in ("va_dma_tx0","va_dma_tx1","va_dma_tx2")):
            raise RuntimeError("P480 missing actual WCD938x link " + nm)
        if '"wcd937x_codec"' in match.group(1):
            raise RuntimeError("P480 alternate unsupported physical codec " + nm)
    print("P480 A3c SOURCE GATE PASS: real provider files and Kona card, WCD938x-only BE, NO ARM, H4 unchanged")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--tg", type=Path)
    ap.add_argument("--d54", type=Path)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    if args.check_only:
        check(args.root)
    else:
        if not args.tg or not args.d54 or not args.report:
            raise RuntimeError("P480 pinned TG+5.4 donors and report required")
        stage(args.root, args.tg, args.d54, args.report)

if __name__ == "__main__":
    main()
