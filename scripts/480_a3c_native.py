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
    for key, value in (
        ("SNDRV_COMPRESS_RENDER_MODE", 4),
        ("SNDRV_COMPRESS_CLK_REC_MODE", 5),
        ("SNDRV_COMPRESS_RENDER_WINDOW", 6),
    ):
        if not re.search(r"\b" + key + r"\s*=\s*" + str(value) + r"\s*,",
                         offload):
            raise RuntimeError("P480 pinned compress metadata key drift " + key)
        text += "#ifndef %s\n#define %s %d\n#endif\n" % (key, key, value)
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
    # Only headers, never the unported WSA/WCD937x implementations.
    for rel in ("codecs/wsa881x.h", "codecs/wsa883x/wsa883x.h",
                "codecs/wcd937x/wcd937x.h",
                "codecs/wcd937x/wcd937x-mbhc.h"):
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
        if name == "msm-pcm-q6-v2.c":
            src = adapt_510_pcm(src)
        if name == "msm-compress-q6-v2.c":
            src = adapt_510_compress(src)
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
    pcm=(dest / "msm-pcm-q6-v2.c").read_text()
    compr=(dest / "msm-compress-q6-v2.c").read_text()
    if ".pcm_construct = p480_pcm_construct" not in pcm:
        raise RuntimeError("P480 real PCM component callback bridge missing")
    if ".compress_ops = &p480_compr_ops" not in compr:
        raise RuntimeError("P480 real compress callback bridge missing")
    if "SND_AUDIOCODEC_AC3" not in (dest / "p480-compress-abi.h").read_text():
        raise RuntimeError("P480 pinned compress ABI absent")
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
