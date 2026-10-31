// SPDX-License-Identifier: GPL-2.0-only
/*
 * P472 A0: native 5.10 diagnostic APRv2/RPMSG + Q6CORE firmware version.
 *
 * This is a deliberately narrow, REAL APR/Q6CORE request/response client.
 * It is NOT the complete TouchGrass audio APR service dispatcher.
 * No speaker, codec, ION, calibration, voice, or userspace ABI here.
 * Source wire contract: pinned TG apr.c, apr.h and q6core.c @ 6bf351bd.
 */
#include <linux/completion.h>
#include <linux/errno.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/rpmsg.h>
#include <linux/slab.h>
#include <linux/string.h>

#define P472_APR_BASIC_RSP_RESULT     0x000110e8
#define P472_AVCS_CMD_GET_FWK_VERSION 0x0001292c
#define P472_AVCS_CMDRSP_GET_FWK_VERSION 0x0001292d
#define P472_APR_DOMAIN_APPS          5
#define P472_APR_DOMAIN_ADSP          4
#define P472_APR_SVC_CORE             3
#define P472_REQ_TIMEOUT_MS          1000
#define P472_MAX_SERVICES             64

struct p472_apr_hdr {
	__le16 hdr_field;
	__le16 pkt_size;
	u8 src_svc;
	u8 src_domain;
	__le16 src_port;
	u8 dest_svc;
	u8 dest_domain;
	__le16 dest_port;
	__le32 token;
	__le32 opcode;
} __packed;

struct p472_fw_ver {
	__le32 major;
	__le32 minor;
	__le32 branch;
	__le32 subbranch;
	__le32 count;
} __packed;

struct p472_service_version {
	__le32 id;
	__le32 version;
	__le32 branch;
} __packed;

struct p472_state {
	struct completion reply;
	int reply_rc;
	bool completed;
};

static struct device_node *p472_find_intents_node(struct rpmsg_device *rpdev)
{
	struct device_node *edge = rpdev->dev.parent->of_node;
	struct device_node *child;
	const char *name;

	/* Some 5.10 GLINK implementations preserve the subnode on rpdev. */
	if (rpdev->dev.of_node)
		return of_node_get(rpdev->dev.of_node);

	for_each_available_child_of_node(edge, child) {
		if (!of_property_read_string(child, "qcom,glink-channels",
					     &name) &&
		    !strcmp(name, "apr_audio_svc"))
			return child;
		if (!strcmp(child->name, "apr_audio_svc"))
			return child;
	}
	return NULL;
}

static int p472_validate_intents(struct rpmsg_device *rpdev)
{
	struct device_node *np;
	u32 req[2];
	int rc;

	np = p472_find_intents_node(rpdev);
	if (!np)
		return -EINVAL;
	rc = of_property_count_u32_elems(np, "qcom,intents");
	if (rc != 2) {
		rc = -EINVAL;
		goto out;
	}
	rc = of_property_read_u32_array(np, "qcom,intents", req, 2);
	if (rc)
		goto out;
	if (req[0] != 512 || req[1] != 20) {
		rc = -EINVAL;
		goto out;
	}
	dev_info(&rpdev->dev,
		 "P472 A0 APR_INTENTS requested_count=%u requested_size=%u source=dt allocation=unverified\n",
		 req[1], req[0]);
out:
	of_node_put(np);
	return rc;
}

static int p472_apr_callback(struct rpmsg_device *rpdev, void *data,
			     int len, void *priv, u32 src)
{
	struct p472_state *s = dev_get_drvdata(&rpdev->dev);
	const struct p472_apr_hdr *h = data;
	const struct p472_fw_ver *v;
	u32 opcode, status, nr;
	size_t expected;

	if (!s || !data || len < sizeof(*h))
		return -EINVAL;
	if (le16_to_cpu(h->pkt_size) != len ||
	    h->src_domain != P472_APR_DOMAIN_ADSP ||
	    h->src_svc != P472_APR_SVC_CORE ||
	    h->dest_domain != P472_APR_DOMAIN_APPS ||
	    h->dest_svc != P472_APR_SVC_CORE)
		return -EPROTO;
	if (s->completed)
		return 0;

	opcode = le32_to_cpu(h->opcode);
	if (opcode == P472_APR_BASIC_RSP_RESULT) {
		const __le32 *words;
		if (len != sizeof(*h) + 2 * sizeof(__le32))
			return -EPROTO;
		words = (const __le32 *)(h + 1);
		if (le32_to_cpu(words[0]) != P472_AVCS_CMD_GET_FWK_VERSION)
			return 0;
		status = le32_to_cpu(words[1]);
		if (!status)
			return 0; /* ACK, not a firmware-version response. */
		s->reply_rc = -EREMOTEIO;
		dev_err(&rpdev->dev, "P472 A0 Q6CORE basic_nack status=%u rc=%d\n",
			status, s->reply_rc);
		goto complete;
	}

	if (opcode != P472_AVCS_CMDRSP_GET_FWK_VERSION)
		return 0;
	if (len < sizeof(*h) + sizeof(*v)) {
		s->reply_rc = -EPROTO;
		goto complete;
	}
	v = (const struct p472_fw_ver *)(h + 1);
	nr = le32_to_cpu(v->count);
	expected = sizeof(*h) + sizeof(*v) +
		   (size_t)nr * sizeof(struct p472_service_version);
	if (nr > P472_MAX_SERVICES || expected > len) {
		s->reply_rc = -EPROTO;
		dev_err(&rpdev->dev,
			"P472 A0 Q6CORE bad_version_payload services=%u size=%d rc=%d\n",
			nr, len, s->reply_rc);
		goto complete;
	}
	s->reply_rc = 0;
	dev_info(&rpdev->dev,
		 "P472 A0 Q6CORE ver=%u.%u.%u.%u services=%u rc=0\n",
		 le32_to_cpu(v->major), le32_to_cpu(v->minor),
		 le32_to_cpu(v->branch), le32_to_cpu(v->subbranch), nr);
complete:
	s->completed = true;
	complete(&s->reply);
	return 0;
}

static int p472_apr_probe(struct rpmsg_device *rpdev)
{
	struct p472_state *s;
	struct p472_apr_hdr h = { };
	u32 remote_pid;
	int rc;
	unsigned long waited;

	if (!rpdev->dev.parent || !rpdev->dev.parent->of_node)
		return -EINVAL;
	rc = of_property_read_u32(rpdev->dev.parent->of_node,
				  "qcom,remote-pid", &remote_pid);
	if (rc) {
		dev_err(&rpdev->dev,
			"P472 A0 APR_TAL remote-pid unavailable rc=%d\n", rc);
		return -EINVAL;
	}
	if (strcmp(rpdev->id.name, "apr_audio_svc"))
		return -ENODEV;
	if (remote_pid != 2) {
		dev_err(&rpdev->dev,
			"P472 A0 APR_TAL dest=%s source=remote-pid:%u rejected rc=%d\n",
			remote_pid == 1 ? "modem" : "unknown",
			remote_pid, -ENODEV);
		return -ENODEV;
	}
	rc = p472_validate_intents(rpdev);
	if (rc) {
		dev_err(&rpdev->dev,
			"P472 A0 APR_INTENTS 20x512 unavailable rc=%d\n", rc);
		return rc;
	}
	s = devm_kzalloc(&rpdev->dev, sizeof(*s), GFP_KERNEL);
	if (!s)
		return -ENOMEM;
	init_completion(&s->reply);
	s->reply_rc = -ETIMEDOUT;
	dev_set_drvdata(&rpdev->dev, s);
	dev_info(&rpdev->dev,
		 "P472 A0 APR_TAL dest=adsp source=remote-pid:%u channel=%s rc=0\n",
		 remote_pid, rpdev->id.name);
	dev_info(&rpdev->dev, "P472 A0 APR_READY channel=%s rc=0\n",
		 rpdev->id.name);

	/* TG APR_HDR_FIELD(SEQ_CMD, 5 dwords, 0) and TG CORE service.
	 * Real request on the live ADSP GLINK endpoint; no synthetic reply.
	 */
	h.hdr_field = cpu_to_le16((2 << 8) | (5 << 4));
	h.pkt_size = cpu_to_le16(sizeof(h));
	h.src_svc = P472_APR_SVC_CORE;
	h.src_domain = P472_APR_DOMAIN_APPS;
	h.dest_svc = P472_APR_SVC_CORE;
	h.dest_domain = P472_APR_DOMAIN_ADSP;
	h.opcode = cpu_to_le32(P472_AVCS_CMD_GET_FWK_VERSION);
	rc = rpmsg_send(rpdev->ept, &h, sizeof(h));
	if (rc) {
		dev_err(&rpdev->dev, "P472 A0 Q6CORE send rc=%d\n", rc);
		goto fail;
	}
	waited = wait_for_completion_timeout(&s->reply,
					msecs_to_jiffies(P472_REQ_TIMEOUT_MS));
	rc = waited ? s->reply_rc : -ETIMEDOUT;
	if (rc) {
		dev_err(&rpdev->dev, "P472 A0 APR_TIMEOUT rc=%d reply=%d\n",
			rc, !!waited);
		goto fail;
	}
	return 0;
fail:
	dev_set_drvdata(&rpdev->dev, NULL);
	return rc;
}

static void p472_apr_remove(struct rpmsg_device *rpdev)
{
	struct p472_state *s = dev_get_drvdata(&rpdev->dev);

	if (s) {
		complete_all(&s->reply);
		dev_set_drvdata(&rpdev->dev, NULL);
	}
	dev_info(&rpdev->dev, "P472 A0 APR_TAL channel=down rc=0\n");
}

static const struct rpmsg_device_id p472_ids[] = {
	{ .name = "apr_audio_svc" },
	{ },
};
MODULE_DEVICE_TABLE(rpmsg, p472_ids);

static struct rpmsg_driver p472_driver = {
	.drv.name = "p472_a0_apr_q6core",
	.id_table = p472_ids,
	.probe = p472_apr_probe,
	.callback = p472_apr_callback,
	.remove = p472_apr_remove,
};
module_rpmsg_driver(p472_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("P472 A0 native diagnostic APRv2 Q6CORE version roundtrip (no audio card)");
