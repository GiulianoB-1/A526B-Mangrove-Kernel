#!/usr/bin/env python3
"""P472 A0: strictly adapt pinned TG APRv2 transport to 5.10 GLINK remote-pid.

This is an APR transport source patch, NOT a completed Q6CORE/ASoC port.
Never inject standalone symbols or create a fake ready event.
"""
import argparse
import json
from pathlib import Path

TG_REL = "techpack/audio/ipc/apr_tal_rpmsg.c"
MARK = "P472_A0_APR_REMOTE_PID_INTENTS_V1"

PROBE = r'''static int apr_tal_rpmsg_probe(struct rpmsg_device *rpdev)
{
	struct apr_svc_ch_dev *apr_ch;
	struct device_node *edge_np;
	unsigned long flags;
	u32 remote_pid, intents[2];
	int ret;
	u32 dest;

	/* 5.10 RPMSG devices hang under remoteproc glink-edge, which has
	 * qcom,remote-pid but NOT TG's legacy mbox-names.
	 * Do not use substring matches against PAS mbox-names ("mss-pil").
	 */
	if (!rpdev || !rpdev->dev.parent ||
	    !rpdev->dev.parent->of_node) {
		dev_err(&rpdev->dev, "P472 A0 APR_TAL missing parent edge rc=%d\n",
			-EINVAL);
		return -EINVAL;
	}
	edge_np = rpdev->dev.parent->of_node;
	ret = of_property_read_u32(edge_np, "qcom,remote-pid",
				   &remote_pid);
	if (ret) {
		dev_err(&rpdev->dev,
			"P472 A0 APR_TAL remote-pid unavailable rc=%d\n", ret);
		return -EINVAL;
	}

	/* P472 A0 only binds the TG apr_audio_svc service. Do not enable
	 * apr_voice_svc here: modem voice is a separate P472 A4 stage.
	 */
	if (strcmp(rpdev->id.name, "apr_audio_svc")) {
		dev_err(&rpdev->dev,
			"P472 A0 APR_TAL unexpected service=%s rc=%d\n",
			rpdev->id.name, -ENODEV);
		return -ENODEV;
	}
	switch (remote_pid) {
	case 2:
		dest = APR_DEST_QDSP6;
		break;
	case 1:
		/* The transport retains TG's MODEM routing, but on A0 the
		 * only allowlisted channel is the ADSP audio service.
		 */
		dev_err(&rpdev->dev,
			"P472 A0 APR_TAL dest=modem source=remote-pid:%u rejected A0\n",
			remote_pid);
		return -ENODEV;
	default:
		dev_err(&rpdev->dev,
			"P472 A0 APR_TAL unknown remote-pid:%u rc=%d\n",
			remote_pid, -ENODEV);
		return -ENODEV;
	}

	/* A0 requires the DT channel to request TG's RX inventory.
	 * This checks DT intent configuration only, not allocation success.
	 * CI must independently verify the 5.10 GLINK provider consumes
	 * qcom,intents; runtime RX allocation still needs hardware proof.
	 */
	if (!rpdev->dev.of_node ||
	    of_property_count_u32_elems(rpdev->dev.of_node,
					"qcom,intents") != 2 ||
	    of_property_read_u32_array(rpdev->dev.of_node,
				       "qcom,intents", intents, 2) ||
	    intents[0] != 512 || intents[1] != 20) {
		dev_err(&rpdev->dev,
			"P472 A0 APR_INTENTS 20x512 DT contract missing rc=%d\n",
			-EINVAL);
		return -EINVAL;
	}

	apr_ch = &apr_svc_ch[APR_DL_SMD][dest][APR_CLIENT_AUDIO];
	spin_lock_irqsave(&apr_ch->w_lock, flags);
	if (apr_ch->handle || apr_ch->channel_state == APR_CH_CONNECTED) {
		spin_unlock_irqrestore(&apr_ch->w_lock, flags);
		dev_err(&rpdev->dev,
			"P472 A0 APR_TAL duplicate owner rc=%d\n", -EBUSY);
		return -EBUSY;
	}
	apr_ch->handle = rpdev;
	apr_ch->channel_state = APR_CH_CONNECTED;
	dev_set_drvdata(&rpdev->dev, apr_ch);
	spin_unlock_irqrestore(&apr_ch->w_lock, flags);
	dev_info(&rpdev->dev,
		 "P472 A0 APR_TAL dest=adsp source=remote-pid:%u channel=%s rc=0\n",
		 remote_pid, rpdev->id.name);
	dev_info(&rpdev->dev,
		 "P472 A0 APR_INTENTS requested_count=%u requested_size=%u source=dt (allocation unverified)\n",
		 intents[1], intents[0]);
	wake_up(&apr_ch->wait);
	return 0;
}

'''

REMOVE = r'''static void apr_tal_rpmsg_remove(struct rpmsg_device *rpdev)
{
	struct apr_svc_ch_dev *apr_ch = dev_get_drvdata(&rpdev->dev);
	unsigned long flags;

	if (!apr_ch) {
		dev_err(&rpdev->dev, "P472 A0 APR_TAL remove without handle\n");
		return;
	}
	/* Protect writers against the RPMSG teardown. A0 cannot keep
	 * references to an endpoint after the remoteproc GLINK removal.
	 */
	spin_lock_irqsave(&apr_ch->w_lock, flags);
	apr_ch->channel_state = APR_CH_DISCONNECTED;
	apr_ch->handle = NULL;
	spin_unlock_irqrestore(&apr_ch->w_lock, flags);
	dev_set_drvdata(&rpdev->dev, NULL);
	dev_info(&rpdev->dev,
		 "P472 A0 APR_TAL channel=%s state=down rc=0\n",
		 rpdev->id.name);
	wake_up_all(&apr_ch->wait);
}

'''

def replace_section(s, start, end, replacement, label):
    if s.count(start) != 1 or s.count(end) != 1:
        raise RuntimeError(f"P472 {label}: ambiguous TG function anchors")
    a, b = s.index(start), s.index(end)
    if a >= b:
        raise RuntimeError(f"P472 {label}: inverted TG anchors")
    return s[:a] + replacement + s[b:]

def patch(s):
    if MARK in s or "P472 A0 APR_TAL" in s:
        raise RuntimeError("P472 already patched; no repeat staging")
    for required in (
        'of_property_read_string(rpdev->dev.parent->of_node,',
        '"mbox-names", &dest',
        'strstr(dest, "adsp")',
        'strstr(dest, "mpss")',
        '{ "apr_audio_svc" }',
    ):
        if required not in s:
            raise RuntimeError("P472 pinned TG source drift: " + required)
    s = s.replace('#include <linux/of_device.h>',
                  '#include <linux/of_device.h>\n#include <linux/of.h>\n'
                  '/* ' + MARK + ' */', 1)
    s = replace_section(s, "static int apr_tal_rpmsg_probe(",
                        "static void apr_tal_rpmsg_remove(",
                        PROBE, "probe")
    s = replace_section(s, "static void apr_tal_rpmsg_remove(",
                        "static const struct rpmsg_device_id ",
                        REMOVE, "remove")
    return s

def check(s):
    checks = (
        MARK, 'of_property_read_u32(edge_np, "qcom,remote-pid"',
        'case 2:', 'case 1:', 'return -ENODEV;',
        'P472 A0 APR_INTENTS requested_count=',
        'of_property_count_u32_elems(rpdev->dev.of_node,',
        'intents[0] != 512 || intents[1] != 20',
        'spin_lock_irqsave(&apr_ch->w_lock, flags);',
        'wake_up_all(&apr_ch->wait)',
    )
    for x in checks:
        if x not in s:
            raise RuntimeError("P472 missing source contract: " + x)
    if '"mbox-names", &dest' in s or 'strstr(dest' in s:
        raise RuntimeError("P472 stale TG mbox string detection")
    return {
        "phase": "P472-A0-APR-TAL",
        "marker": MARK,
        "remote_pid_map": {"2": "ADSP", "1": "MSS (A0 rejected)"},
        "unknown_pid_fail_closed": True,
        "intent_count_dt_requested": 20,
        "intent_bytes_dt_requested": 512,
        "intents_allocated_on_hardware": "UNVERIFIED",
        "aprv2_q6core_roundtrip": "UNVERIFIED",
        "audio_card": "NOT STAGED",
        "speaker_power": "NO",
        "ipa_p471_modified": False,
        "flash_authorized": False,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tg", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--report", type=Path)
    a = p.parse_args()
    if a.check_only:
        s = a.out.read_text()
    else:
        s = patch((a.tg / TG_REL).read_text())
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(s)
    result = check(s)
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("P472 A0 APR remote-pid and RX-intent DT guards SOURCE PASS, no Image or Q6CORE claim")

if __name__ == "__main__":
    main()
