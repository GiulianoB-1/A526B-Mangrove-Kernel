#!/usr/bin/env python3
"""P477B: fail-closed A3b DT-property and driver-init contract audit.

Compare every parsed OF read in the privately staged donor C files with
the pinned TG 4.19 equivalent and TG A52 board-r02 DTS. Optional or
dynamically produced property names have explicit, reviewable exceptions.
"""
import argparse
import json
import re
import runpy
import subprocess
from pathlib import Path

TG_SHA = "6bf351bdf18bdb228db79e66f14a7a9c0178e5d7"
D54_SHA = "c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4"
R02 = Path("arch/arm64/boot/dts/samsung/a52/a52xq/a52xq_eur_open_w00_r02.dts")
ROOT = Path("drivers/soc/qcom/p472_tg_audio/a3b")
READER = re.compile(
    r"\b(of_property_(?:read\w*|count\w*)|of_get_named_gpio(?:_flags)?|of_find_property)\s*\("
)
POINTER_STRING = re.compile(
    r"\b(?:static\s+)?(?:const\s+)?char\s*\*\s*(\w+)\s*=\s*\"([^\"]+)\""
)
FUNCTION_DEFINITION = re.compile(
    r"(?m)^\s*(?:static\s+)?(?:int|void)\s+([a-zA-Z_]\w*_drv_init)\s*\([^;{}]*?\)\s*\{",
    re.S,
)

# Exceptions are local to the source file and every entry states *why*
# the A52 r02 DTS or the TG equivalent does not carry this property.
OPTIONAL = {
    ("soc/pinctrl-lpi.c", "qcom,gpios-count"): "legacy donor key, fallback only if r02 num-gpios absent",
    ("soc/pinctrl-wcd.c", "qcom,gpios-count"): "legacy donor key, fallback only if r02 num-gpios absent",
    ("asoc/codecs/msm-cdc-pinctrl.c", "qcom,tlmm-pins"): "legacy donor fallback, A52 live key is tlmm-gpio",
    ("asoc/codecs/msm-cdc-pinctrl.c", "qcom,chip-wakeup-reg"): "optional older codec wake-register scheme, absent on r02",
    ("asoc/codecs/msm-cdc-pinctrl.c", "qcom,chip-wakeup-maskbit"): "conditional on optional chip-wakeup-reg",
    ("asoc/codecs/msm-cdc-pinctrl.c", "qcom,chip-wakeup-default-val"): "conditional on optional chip-wakeup-reg",
    ("asoc/codecs/msm-cdc-pinctrl.c", "qcom,cdc-rst-n-gpio"): "optional reset GPIO for other codec layouts",
    ("asoc/codecs/msm-cdc-supply.c", "qcom,%s-current"): "runtime supply-name template, checked at use site",
    ("asoc/codecs/msm-cdc-supply.c", "qcom,%s-lpm-supported"): "runtime optional supply-name template",
    ("asoc/codecs/msm-cdc-supply.c", "qcom,cdc-cp-supplies"): "optional charge-pump regulator list",
    ("asoc/codecs/audio-ext-clk-up.c", "qcom,mclk-clk-reg"): "optional external clock register",
    ("asoc/codecs/audio-ext-clk-up.c", "pmic-clock-names"): "optional external PMIC clock list",
    ("asoc/codecs/audio-ext-clk-up.c", "qcom,use-pinctrl"): "optional external-clock pinctrl path",
    ("asoc/codecs/bolero/bolero-cdc.c", "qcom,va-without-decimation"): "optional VA macro mode, absent on r02",
    ("asoc/codecs/bolero/bolero-cdc.c", "qcom,bolero-version"): "optional codec version, driver has fallback",
    ("asoc/codecs/bolero/rx-macro.c", "qcom,is-used-swr-gpio"): "optional GPIO selection, macro provides default",
    ("asoc/codecs/bolero/tx-macro.c", "qcom,is-used-swr-gpio"): "optional GPIO selection, macro provides default",
    ("asoc/codecs/bolero/tx-macro.c", "qcom,disable-afe-wakeup-event-listener"): "optional AFE wake-event configuration",
    ("asoc/codecs/bolero/va-macro.c", "qcom,va-without-decimation"): "optional VA decimation mode; boolean false when absent from A52 r02",
    ("asoc/codecs/bolero/va-macro.c", "qcom,is-used-swr-gpio"): "optional GPIO selection, macro provides default",
    ("asoc/codecs/bolero/va-macro.c", "qcom,va-vdd-micb-voltage"): "conditional VA micbias regulator property",
    ("asoc/codecs/bolero/va-macro.c", "qcom,va-vdd-micb-current"): "conditional VA micbias regulator property",
    ("soc/swr-mstr-ctrl.c", "qcom,swr-master-version"): "optional version, donor uses SWRM_VERSION_1_6",
    ("soc/swr-mstr-ctrl.c", "qcom,dynamic-port-map-supported"): "optional support flag, donor defaults to 1",
    ("soc/swr-mstr-ctrl.c", "qcom,swrm-hctl-reg"): "optional hardware control MMIO",
    ("soc/swr-mstr-ctrl.c", "qcom,swr-phy-dev-addr"): "optional custom slave addresses, auto enum remains",
    ("soc/swr-mstr-ctrl.c", "qcom,is-always-on"): "optional always-on flag, zero when absent",
    ("soc/swr-mstr-ctrl.c", "qcom,swr-wakeup-irq"): "optional wake IRQ, donor checks availability",
    ("asoc/codecs/wcd-mbhc-v2.c", "detect-extn-cable"): "optional legacy extension cable detection",
    ("asoc/codecs/wcd-mbhc-v2.c", "qcom,msm-mbhc-usbc-audio-supported"): "absent on r02; unsupported FSA4480 analog path rejects if requested",
    ("asoc/codecs/wcd-mbhc-v2.c", "qcom,msm-mbhc-moist-cfg"): "optional moisture thresholds, donor has defaults",
    ("asoc/codecs/wcd-dsp-mgr.c", "qcom,wdsp-cmpnt-dev-name"): "optional WCD DSP manager child name",
    ("asoc/codecs/wcd-dsp-mgr.c", "qcom,img-filename"): "optional WCD DSP-manager node not active on A52 r02",
}
# These OF calls receive a property variable, not a string literal.
# Resolve only the pinned, verified call-site property candidates.
DYNAMIC = {
    ("asoc/codecs/msm-cdc-supply.c", "prop_name"): (
        "qcom,%s-current", "qcom,%s-lpm-supported",
    ),
    ("asoc/codecs/msm-cdc-supply.c", "sup_list"): (
        "qcom,cdc-static-supplies", "qcom,cdc-on-demand-supplies",
        "qcom,cdc-cp-supplies",
    ),
    ("asoc/codecs/wcd938x/wcd938x.c", "prop"): (
        "qcom,rx_swr_ch_map", "qcom,tx_swr_ch_map",
    ),
    ("asoc/codecs/wcd938x/wcd938x.c", "name"): tuple(
        "qcom,cdc-micbias%d-mv" % n for n in range(1, 5)
    ),
}
REQUIRED = {
    ("soc/pinctrl-lpi.c", "qcom,num-gpios"),
    ("soc/pinctrl-wcd.c", "qcom,num-gpios"),
    ("asoc/codecs/msm-cdc-pinctrl.c", "qcom,tlmm-gpio"),
}

def uncomment(source):
    # Preserve newline counts for source-line reporting.
    return re.sub(
        r"/\*.*?\*/|//[^\n]*",
        lambda match: "\n" * match.group().count("\n"),
        source, flags=re.S,
    )

def split_call_args(code, after_open):
    args, buf = [], []
    depth, quoted, escaped = 1, False, False
    for c in code[after_open:]:
        if quoted:
            buf.append(c)
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                quoted = False
            continue
        if c == '"':
            quoted = True
            buf.append(c)
        elif c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth -= 1
            if depth == 0:
                args.append("".join(buf).strip())
                return args
            buf.append(c)
        elif c == "," and depth == 1:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(c)
    raise RuntimeError("P477B unbalanced DT property read")

def property_reads(source, rel):
    code = uncomment(source)
    constants = dict(POINTER_STRING.findall(code))
    rows = []
    for match in READER.finditer(code):
        args = split_call_args(code, match.end())
        if len(args) < 2:
            raise RuntimeError("P477B OF read without property argument: " + rel)
        token = args[1].strip()
        literal = re.fullmatch(r'"([^"]+)"', token)
        if literal:
            props = (literal.group(1),)
            derivation = "literal"
        elif token in constants:
            props = (constants[token],)
            derivation = "local-constant:" + token
        elif (rel, token) in DYNAMIC:
            props = DYNAMIC[(rel, token)]
            derivation = "pinned-dynamic:" + token
        else:
            raise RuntimeError(
                "P477B unreviewed dynamic DT property %s:%d %s(%s)"
                % (rel, code.count("\n", 0, match.start()) + 1, match.group(1), token)
            )
        for prop in props:
            rows.append({
                "file": rel, "line": code.count("\n", 0, match.start()) + 1,
                "call": match.group(1), "property": prop, "derivation": derivation,
            })
    return rows

def dt_declared(dts, prop):
    return bool(re.search(
        r"(?m)^\s*" + re.escape(prop) + r"\s*(?:=|;)", dts
    ))

def run(root, tg, d54):
    for folder, sha, label in ((tg, TG_SHA, "TG"), (d54, D54_SHA, "SM7325")):
        current = subprocess.check_output(
            ["git", "-C", str(folder), "rev-parse", "HEAD"], text=True
        ).strip()
        if current != sha:
            raise RuntimeError("P477B %s donor SHA drift: %s" % (label, current))
    donor_files = runpy.run_path(
        str(Path(__file__).with_name("472_a3b_lpass_codec_d54.py"))
    )
    names = donor_files["B1"] + donor_files["B2"] + donor_files["B3"]
    dts = (tg / R02).read_text()
    if not dt_declared(dts, "qcom,num-gpios") or not dt_declared(dts, "qcom,tlmm-gpio"):
        raise RuntimeError("P477B pinned A52 r02 DT missing active audio pinctrl keys")
    records, errors, staged = [], [], {}
    for rel in names:
        c = (root / ROOT / rel).read_text()
        original_tg = (tg / "techpack/audio" / rel).read_text()
        original_54 = (d54 / "techpack/audio" / rel).read_text()
        staged[rel] = uncomment(c)
        tg_props = {item["property"] for item in property_reads(original_tg, rel)}
        original_props = {item["property"] for item in property_reads(original_54, rel)}
        for item in property_reads(c, rel):
            prop = item["property"]
            reason = OPTIONAL.get((rel, prop))
            item["in_TG_equivalent"] = prop in tg_props
            item["in_A52_r02_DTS"] = dt_declared(dts, prop)
            item["present_in_SM7325_donor"] = prop in original_props
            item["optional_exception"] = reason
            item["status"] = (
                "MATCH" if item["in_TG_equivalent"] and item["in_A52_r02_DTS"]
                else "OPTIONAL_WHITELISTED" if reason else "FAIL"
            )
            if item["status"] == "FAIL":
                errors.append("%s:%d %s TG=%d DTS=%d" % (
                    rel, item["line"], prop,
                    item["in_TG_equivalent"], item["in_A52_r02_DTS"]
                ))
            records.append(item)
    for rel, prop in sorted(REQUIRED):
        active = [x for x in records if x["file"] == rel and x["property"] == prop
                  and x["status"] == "MATCH"]
        if not active:
            errors.append("required TG/r02 source property missing: %s %s" % (rel, prop))
    # Every *_drv_init definition in the actual compiled staged C
    # sources must be called, rather than just existing as an object.
    init_file = root / ROOT / "asoc/codecs/a3b-cdc-pinctrl-init.c"
    init_source = uncomment(init_file.read_text())
    all_code = "\n".join(list(staged.values()) + [init_source])
    defined = sorted({
        name for c in staged.values() for name in FUNCTION_DEFINITION.findall(c)
    })
    init_records = []
    for name in defined:
        references = len(re.findall(r"\b" + re.escape(name) + r"\s*\(", all_code))
        count_definitions = sum(len(re.findall(
            r"\b" + re.escape(name) + r"\s*\([^;{}]*?\)\s*\{", c, re.S
        )) for c in staged.values())
        calls = references - count_definitions
        init_records.append({"name": name, "definitions": count_definitions, "calls": calls})
        if calls < 1:
            errors.append("staged %s defined but never called" % name)
    if ("msm_cdc_pinctrl_drv_init();" not in init_source or
        "subsys_initcall(p472_a3b_cdc_pinctrl_init);" not in init_source or
        "wcd9xxx_irq_drv_init(" in init_source or
        "wcd9xxx_init(" in init_source):
        errors.append("early real CDC pinctrl registration missing or legacy WCD core selected")
    if not any(x["name"] == "msm_cdc_pinctrl_drv_init" and x["calls"] >= 1
               for x in init_records):
        errors.append("CDC pinctrl registration has no real staged caller")
    return {
        "tag": "P477B_DT_CONTRACT_R02_NO_ARM",
        "tg": TG_SHA, "sm7325": D54_SHA, "r02": str(R02),
        "property_reads": sorted(records, key=lambda x: (x["file"], x["line"], x["property"])),
        "read_count": len(records),
        "optional_whitelisted": sum(x["status"] == "OPTIONAL_WHITELISTED" for x in records),
        "init_calls": init_records, "errors": errors, "pass": not errors,
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--tg", required=True, type=Path)
    parser.add_argument("--d54", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.root, args.tg, args.d54)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if result["errors"]:
        for err in result["errors"][:60]:
            print("P477B DT CONTRACT FAIL:", err)
        raise SystemExit("P477B DT CONTRACT FAILED (%d errors); see %s" %
                         (len(result["errors"]), args.report))
    print("P477B DT CONTRACT PASS: %d OF reads; %d explicit optional; %d real drv_init" %
          (result["read_count"], result["optional_whitelisted"],
           len(result["init_calls"])))

if __name__ == "__main__":
    main()
