// SPDX-License-Identifier: GPL-2.0-only
/*
 * P472 A0: native 5.10 diagnostic APRv2/RPMSG + Q6CORE firmware version.
 *
 * This is a deliberately narrow, REAL APR/Q6CORE request/response client.
 * It is NOT the complete TouchGrass audio APR service dispatcher.
 * No speaker, codec, ION, calibration, voice, or userspace ABI here.
 * Source wire contract: pinned TG apr.c, apr.h and q6core.c @ 6bf351bd.
 */
#include <linux/atomic.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/errno.h>
#include <linux/jiffies.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/rpmsg.h>
#include <linux/mutex.h>
#include <linux/rwsem.h>
#include <linux/notifier.h>
#ifdef CONFIG_P472_A1_APR_DISPATCH
#include "p472_a1_apr.h"
#endif
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/workqueue.h>

#define P472_APR_BASIC_RSP_RESULT     0x000110e8
#define P472_AVCS_CMD_ADSP_EVENT_GET_STATE 0x0001290c
#define P472_AVCS_CMDRSP_ADSP_EVENT_GET_STATE 0x0001290d
#define P472_AVCS_CMD_GET_FWK_VERSION 0x0001292c
#define P472_AVCS_CMDRSP_GET_FWK_VERSION 0x0001292d
#define P472_APR_DOMAIN_APPS          5
#define P472_APR_DOMAIN_ADSP          4
#define P472_APR_SVC_CORE             3
#define P472_REQ_TIMEOUT_MS          3000
#define P472_STATE_TIMEOUT_MS         100
#define P472_READY_POLL_INTERVAL_MS    50
#define P472_READY_INITIAL_DELAY_MS   100
#define P472_READY_DEADLINE_MS      10000
#define P472_RX_RAW_MAX_PACKETS        32
#define P472_RX_RAW_MAX_BYTES         512
#define P472_MAX_SERVICES             64
/* P472_A1_APR_REAL_SERVICE_DISPATCH_V1: single RPMSG owner, no second provider. */
/* P472_A1_APR_VARIABLE_HEADER_V1: TG APR hdr_len = bits[7:4] * 4. */

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
	struct work_struct query_work;
	struct rpmsg_device *rpdev;
	struct completion reply;
	struct completion state_reply;
	atomic_t rx_seen;
	int reply_rc;
	int state_rc;
	u32 adsp_state;
	bool state_pending;
	bool fwk_pending;
	bool removing;
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


#ifdef CONFIG_P472_A1_APR_DISPATCH
/* AFE, ASM, ADM and LSM are the TG ADSP services. Modem voice is separate. */
#define P472_A1_PROVENANCE "P472 A1 BUILD run_id=UNSTAMPED sha=UNSTAMPED"
#define P472_A1_ROUTE_COUNT 0x17
struct p472_a1_route {
	p472_a1_rx_fn cb;
	void *priv;
};
static struct p472_a1_route p472_a1_routes[P472_A1_ROUTE_COUNT];
static DECLARE_RWSEM(p472_a1_routes_lock);
static DEFINE_MUTEX(p472_a1_tx_lock);
static struct p472_state *p472_a1_active;
static BLOCKING_NOTIFIER_HEAD(p472_a1_adsp_notifiers);

static bool p472_a1_allowed(u8 service)
{
	return service == P472_A1_SVC_AFE ||
	       service == P472_A1_SVC_ASM ||
	       service == P472_A1_SVC_ADM ||
	       service == P472_A1_SVC_LSM;
}

/* Registration lifetime is synchronized with read-locked RX dispatch. */
int p472_a1_apr_register(u8 service, p472_a1_rx_fn cb, void *priv)
{
	struct p472_a1_route *route;

	if (!p472_a1_allowed(service) || !cb)
		return -EINVAL;
	down_write(&p472_a1_routes_lock);
	route = &p472_a1_routes[service];
	if (route->cb) {
		up_write(&p472_a1_routes_lock);
		return -EBUSY;
	}
	route->priv = priv;
	route->cb = cb;
	up_write(&p472_a1_routes_lock);
	pr_info("P472 A1 DISPATCH register svc=%u rc=0\n", service);
	return 0;
}
EXPORT_SYMBOL_GPL(p472_a1_apr_register);

void p472_a1_apr_unregister(u8 service, p472_a1_rx_fn cb, void *priv)
{
	struct p472_a1_route *route;

	if (!p472_a1_allowed(service) || !cb)
		return;
	/* Never unregister from inside an APR callback. */
	down_write(&p472_a1_routes_lock);
	route = &p472_a1_routes[service];
	if (route->cb == cb && route->priv == priv) {
		route->cb = NULL;
		route->priv = NULL;
	}
	up_write(&p472_a1_routes_lock);
}
EXPORT_SYMBOL_GPL(p472_a1_apr_unregister);

/* Real ADSP APR service send, never a synthetic response or fake PCM. */
int p472_a1_apr_send(u8 service, u16 src_port, u16 dest_port,
		     u32 token, u32 opcode, const void *payload,
		     size_t payload_len)
{
	struct p472_apr_hdr *hdr;
	struct p472_state *s;
	size_t bytes;
	int rc;

	if (!p472_a1_allowed(service) || (payload_len && !payload))
		return -EINVAL;
	if (payload_len > P472_RX_RAW_MAX_BYTES - sizeof(*hdr))
		return -EMSGSIZE;
	bytes = sizeof(*hdr) + payload_len;
	hdr = kzalloc(bytes, GFP_KERNEL);
	if (!hdr)
		return -ENOMEM;
	hdr->hdr_field = cpu_to_le16((2 << 8) | (5 << 4));
	hdr->pkt_size = cpu_to_le16(bytes);
	hdr->src_domain = P472_APR_DOMAIN_APPS;
	hdr->dest_domain = P472_APR_DOMAIN_ADSP;
	hdr->src_svc = service;
	hdr->dest_svc = service;
	hdr->src_port = cpu_to_le16(src_port);
	hdr->dest_port = cpu_to_le16(dest_port);
	hdr->token = cpu_to_le32(token);
	hdr->opcode = cpu_to_le32(opcode);
	if (payload_len)
		memcpy(hdr + 1, payload, payload_len);

	mutex_lock(&p472_a1_tx_lock);
	s = p472_a1_active;
	if (!s || READ_ONCE(s->removing) ||
	    READ_ONCE(s->adsp_state) == 0 || READ_ONCE(s->reply_rc)) {
		rc = -ENOTCONN;
	} else {
		rc = rpmsg_send(s->rpdev->ept, hdr, bytes);
	}
	mutex_unlock(&p472_a1_tx_lock);
	pr_info("P472 A1 APR_SEND svc=%u opcode=0x%08x token=%u len=%zu rc=%d\n",
		service, opcode, token, bytes, rc);
	kfree(hdr);
	return rc;
}
EXPORT_SYMBOL_GPL(p472_a1_apr_send);

int p472_a1_adsp_notifier_register(struct notifier_block *nb)
{
	return blocking_notifier_chain_register(&p472_a1_adsp_notifiers, nb);
}
EXPORT_SYMBOL_GPL(p472_a1_adsp_notifier_register);

int p472_a1_adsp_notifier_unregister(struct notifier_block *nb)
{
	return blocking_notifier_chain_unregister(&p472_a1_adsp_notifiers, nb);
}
EXPORT_SYMBOL_GPL(p472_a1_adsp_notifier_unregister);

static int p472_a1_dispatch_rx(struct rpmsg_device *rpdev,
			       const struct p472_apr_hdr *h,
			       const void *payload, size_t payload_len,
			       size_t hdr_size, int len)
{
	const u8 service = h->dest_svc;
	struct p472_state *s = dev_get_drvdata(&rpdev->dev);
	struct p472_a1_packet p;
	struct p472_a1_route *r;
	int rc;

	if (!p472_a1_allowed(service))
		return -EPROTO;
	/* Reject traffic when ADSP state or framework version is not ready. */
	if (!s || READ_ONCE(s->removing) || !READ_ONCE(s->adsp_state) ||
	    READ_ONCE(s->reply_rc))
		return -ENOTCONN;
	p.service = service;
	p.src_port = le16_to_cpu(h->src_port);
	p.dest_port = le16_to_cpu(h->dest_port);
	p.hdr_len = hdr_size;
	p.pkt_len = len;
	p.msg_type = (le16_to_cpu(h->hdr_field) >> 8) & 3;
	p.token = le32_to_cpu(h->token);
	p.opcode = le32_to_cpu(h->opcode);
	p.payload = payload;
	p.payload_len = payload_len;
	down_read(&p472_a1_routes_lock);
	r = &p472_a1_routes[service];
	if (r->cb)
		rc = r->cb(&p, r->priv);
	else
		rc = -ENODEV;
	up_read(&p472_a1_routes_lock);
	dev_info_ratelimited(&rpdev->dev,
		"P472 A1 DISPATCH rx svc=%u opcode=0x%08x token=%u hdr=%zu payload=%zu rc=%d\n",
		service, p.opcode, p.token, hdr_size, payload_len, rc);
	return rc;
}
#endif

/*
 * Dump the first 32 packets, including malformed/unexpected APR traffic,
 * before the APR filters. Bound each dump to the 512-byte DT intent size.
 */
static int p472_apr_callback(struct rpmsg_device *rpdev, void *data,
			     int len, void *priv, u32 src)
{
	struct p472_state *s = dev_get_drvdata(&rpdev->dev);
	const struct p472_apr_hdr *h = data;
	const struct p472_fw_ver *v;
	const __le32 *words;
	u32 opcode, status, nr;
	size_t expected, hdr_size;
	const u8 *payload;
	u16 hdr_field;
	int seen;

	if (!s)
		return -ENODEV;
	seen = atomic_inc_return(&s->rx_seen);
	if (seen <= P472_RX_RAW_MAX_PACKETS) {
		int nbytes = data && len > 0 ?
			min_t(int, len, P472_RX_RAW_MAX_BYTES) : 0;

		dev_info(&rpdev->dev,
			 "P472 A0b APR_RX_RAW seq=%d src=%u len=%d dump=%d\n",
			 seen, src, len, nbytes);
		if (nbytes)
			print_hex_dump(KERN_INFO, "P472 A0b APR_RX_RAW ",
				       DUMP_PREFIX_OFFSET, 16, 1,
				       data, nbytes, false);
	}
	if (!data || len < sizeof(*h))
		return -EINVAL;
	if (le16_to_cpu(h->pkt_size) != len ||
	    h->src_domain != P472_APR_DOMAIN_ADSP ||
	    h->dest_domain != P472_APR_DOMAIN_APPS)
		return -EPROTO;
	/*
	 * TG apr_cb_func() decodes hdr_len from hdr_field[7:4] in dwords.
	 * ADSP uses 8 dwords (32 bytes) on this device, not the outgoing
	 * 5-dword (20-byte) header. Never parse payload at (h + 1).
	 */
	hdr_field = le16_to_cpu(h->hdr_field);
	hdr_size = ((hdr_field >> 4) & 0x0f) * 4;
	if (hdr_size < sizeof(*h) || hdr_size > len) {
		dev_err_ratelimited(&rpdev->dev,
			"P472 A1 APR_HDR_INVALID hdr_field=0x%04x hdr_size=%zu len=%d\n",
			hdr_field, hdr_size, len);
		return -EPROTO;
	}
	payload = (const u8 *)data + hdr_size;
#ifdef CONFIG_P472_A1_APR_DISPATCH
	if (h->dest_svc != P472_APR_SVC_CORE)
		return p472_a1_dispatch_rx(rpdev, h, payload, len - hdr_size,
					   hdr_size, len);
#endif
	if (h->src_svc != P472_APR_SVC_CORE ||
	    h->dest_svc != P472_APR_SVC_CORE)
		return -EPROTO;
	if (READ_ONCE(s->removing))
		return 0;

	if (atomic_read(&s->rx_seen) <= P472_RX_RAW_MAX_PACKETS)
		dev_info(&rpdev->dev,
			 "P472 A1 APR_HDR hdr_field=0x%04x hdr_len=%zu pkt=%d opcode=0x%08x\n",
			 hdr_field, hdr_size, len, le32_to_cpu(h->opcode));
	opcode = le32_to_cpu(h->opcode);
	if (opcode == P472_APR_BASIC_RSP_RESULT) {
		if (len != hdr_size + 2 * sizeof(__le32))
			return -EPROTO;
		words = (const __le32 *)payload;
		status = le32_to_cpu(words[1]);
		switch (le32_to_cpu(words[0])) {
		case P472_AVCS_CMD_ADSP_EVENT_GET_STATE:
			/* ACK status 0 is not the actual GET_STATE response. */
			if (!READ_ONCE(s->state_pending) || !status)
				return 0;
			s->state_rc = -EREMOTEIO;
			dev_err(&rpdev->dev,
				"P472 A0b GET_STATE basic_nack status=%u rc=%d\n",
				status, s->state_rc);
			WRITE_ONCE(s->state_pending, false);
			complete(&s->state_reply);
			return 0;
		case P472_AVCS_CMD_GET_FWK_VERSION:
			if (!READ_ONCE(s->fwk_pending) || !status)
				return 0;
			s->reply_rc = -EREMOTEIO;
			dev_err(&rpdev->dev,
				"P472 A0 Q6CORE basic_nack status=%u rc=%d\n",
				status, s->reply_rc);
			WRITE_ONCE(s->fwk_pending, false);
			complete(&s->reply);
			return 0;
		default:
			return 0;
		}
	}

	if (opcode == P472_AVCS_CMDRSP_ADSP_EVENT_GET_STATE) {
		if (!READ_ONCE(s->state_pending))
			return 0;
		if (len < hdr_size + sizeof(__le32)) {
			s->state_rc = -EPROTO;
			dev_err(&rpdev->dev,
				"P472 A0b GET_STATE short_reply len=%d rc=%d\n",
				len, s->state_rc);
		} else {
			words = (const __le32 *)payload;
			s->adsp_state = le32_to_cpu(words[0]);
			s->state_rc = 0;
			dev_info(&rpdev->dev,
				 "P472 A0b GET_STATE response state=%u rc=0\n",
				 s->adsp_state);
		}
		WRITE_ONCE(s->state_pending, false);
		complete(&s->state_reply);
		return 0;
	}
	if (opcode != P472_AVCS_CMDRSP_GET_FWK_VERSION ||
	    !READ_ONCE(s->fwk_pending))
		return 0;
	if (len < hdr_size + sizeof(*v)) {
		s->reply_rc = -EPROTO;
		goto fwk_complete;
	}
	v = (const struct p472_fw_ver *)payload;
	nr = le32_to_cpu(v->count);
	expected = hdr_size + sizeof(*v) +
		   (size_t)nr * sizeof(struct p472_service_version);
	if (nr > P472_MAX_SERVICES || expected > len) {
		s->reply_rc = -EPROTO;
		dev_err(&rpdev->dev,
			"P472 A0 Q6CORE bad_version_payload services=%u size=%d rc=%d\n",
			nr, len, s->reply_rc);
		goto fwk_complete;
	}
	s->reply_rc = 0;
	dev_info(&rpdev->dev,
		 "P472 A0 Q6CORE ver=%u.%u.%u.%u services=%u rc=0\n",
		 le32_to_cpu(v->major), le32_to_cpu(v->minor),
		 le32_to_cpu(v->branch), le32_to_cpu(v->subbranch), nr);
fwk_complete:
	WRITE_ONCE(s->fwk_pending, false);
	complete(&s->reply);
	return 0;
}

static int p472_send_command(struct p472_state *s, u32 opcode)
{
	struct rpmsg_device *rpdev = s->rpdev;
	struct p472_apr_hdr h = { };
	int rc;

	/* Same TG wire header, zero token, and CORE src/dest as A0. */
	h.hdr_field = cpu_to_le16((2 << 8) | (5 << 4));
	h.pkt_size = cpu_to_le16(sizeof(h));
	h.src_svc = P472_APR_SVC_CORE;
	h.src_domain = P472_APR_DOMAIN_APPS;
	h.dest_svc = P472_APR_SVC_CORE;
	h.dest_domain = P472_APR_DOMAIN_ADSP;
	h.opcode = cpu_to_le32(opcode);
	rc = rpmsg_send(rpdev->ept, &h, sizeof(h));
	dev_info(&rpdev->dev, "P472 A0b APR_SEND opcode=0x%08x rc=%d\n",
		 opcode, rc);
	return rc;
}

static void p472_query_work(struct work_struct *work)
{
	struct p472_state *s = container_of(work, struct p472_state, query_work);
	struct rpmsg_device *rpdev = s->rpdev;
	unsigned long deadline, waited, timeout;
	unsigned int attempts = 0;
	int rc;

	/* TG waits 100 ms before querying AVS readiness. */
	if (READ_ONCE(s->removing))
		return;
	msleep(P472_READY_INITIAL_DELAY_MS);
	deadline = jiffies + msecs_to_jiffies(P472_READY_DEADLINE_MS);
	while (time_before(jiffies, deadline)) {
		if (READ_ONCE(s->removing))
			return;
		attempts++;
		reinit_completion(&s->state_reply);
		s->state_rc = -ETIMEDOUT;
		s->adsp_state = 0;
		WRITE_ONCE(s->state_pending, true);
		rc = p472_send_command(s, P472_AVCS_CMD_ADSP_EVENT_GET_STATE);
		if (rc) {
			WRITE_ONCE(s->state_pending, false);
			dev_err(&rpdev->dev,
				"P472 A0b GET_STATE attempt=%u send_rc=%d\n",
				attempts, rc);
		} else {
			timeout = min_t(unsigned long,
					msecs_to_jiffies(P472_STATE_TIMEOUT_MS),
					deadline - jiffies);
			waited = wait_for_completion_timeout(&s->state_reply,
							    timeout);
			WRITE_ONCE(s->state_pending, false);
			if (READ_ONCE(s->removing))
				return;
			if (waited && !s->state_rc && s->adsp_state) {
				dev_info(&rpdev->dev,
					 "P472 A0b ADSP_READY state=%u attempts=%u rc=0\n",
					 s->adsp_state, attempts);
				goto get_fwk_version;
			}
			dev_info(&rpdev->dev,
				 "P472 A0b GET_STATE attempt=%u reply=%u state=%u rc=%d\n",
				 attempts, !!waited, s->adsp_state,
				 waited ? s->state_rc : -ETIMEDOUT);
		}
		if (time_after_eq(jiffies, deadline))
			break;
		msleep(P472_READY_POLL_INTERVAL_MS);
	}
	if (!READ_ONCE(s->removing))
		dev_err(&rpdev->dev,
			"P472 A0b ADSP_READY_TIMEOUT attempts=%u rc=%d\n",
			attempts, -ETIMEDOUT);
	return;

get_fwk_version:
	if (READ_ONCE(s->removing))
		return;
	reinit_completion(&s->reply);
	s->reply_rc = -ETIMEDOUT;
	WRITE_ONCE(s->fwk_pending, true);
	rc = p472_send_command(s, P472_AVCS_CMD_GET_FWK_VERSION);
	if (rc) {
		WRITE_ONCE(s->fwk_pending, false);
		return;
	}
	waited = wait_for_completion_timeout(&s->reply,
					    msecs_to_jiffies(P472_REQ_TIMEOUT_MS));
	WRITE_ONCE(s->fwk_pending, false);
	if (READ_ONCE(s->removing))
		return;
	rc = waited ? s->reply_rc : -ETIMEDOUT;
	if (rc)
		dev_err(&rpdev->dev, "P472 A0 APR_TIMEOUT rc=%d reply=%d\n",
			rc, !!waited);
#ifdef CONFIG_P472_A1_APR_DISPATCH
	else {
		dev_info(&rpdev->dev,
			 "P472 A1 DISPATCH adsp_ready=1 services=AFE,ASM,ADM,LSM\n");
		blocking_notifier_call_chain(&p472_a1_adsp_notifiers,
					     P472_A1_ADSP_UP, NULL);
	}
#endif
}

static int p472_apr_probe(struct rpmsg_device *rpdev)
{
	struct p472_state *s;
	u32 remote_pid;
	int rc;

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
	init_completion(&s->state_reply);
	atomic_set(&s->rx_seen, 0);
	s->reply_rc = -ETIMEDOUT;
	s->state_rc = -ETIMEDOUT;
	dev_set_drvdata(&rpdev->dev, s);
	dev_info(&rpdev->dev,
		 "P472 A0 APR_TAL dest=adsp source=remote-pid:%u channel=%s rc=0\n",
		 remote_pid, rpdev->id.name);
	dev_info(&rpdev->dev, "P472 A0 APR_READY channel=%s rc=0\n",
		 rpdev->id.name);

	INIT_WORK(&s->query_work, p472_query_work);
	s->rpdev = rpdev;
#ifdef CONFIG_P472_A1_APR_DISPATCH
	mutex_lock(&p472_a1_tx_lock);
	p472_a1_active = s;
	mutex_unlock(&p472_a1_tx_lock);
	dev_info(&rpdev->dev, P472_A1_PROVENANCE "\n");
#endif
	schedule_work(&s->query_work);
	return 0;
}

static void p472_apr_remove(struct rpmsg_device *rpdev)
{
	struct p472_state *s = dev_get_drvdata(&rpdev->dev);

	if (s) {
		WRITE_ONCE(s->removing, true);
#ifdef CONFIG_P472_A1_APR_DISPATCH
		mutex_lock(&p472_a1_tx_lock);
		if (p472_a1_active == s)
			p472_a1_active = NULL;
		mutex_unlock(&p472_a1_tx_lock);
#endif
		cancel_work_sync(&s->query_work);
#ifdef CONFIG_P472_A1_APR_DISPATCH
		blocking_notifier_call_chain(&p472_a1_adsp_notifiers,
					     P472_A1_ADSP_DOWN, NULL);
		dev_info(&rpdev->dev, "P472 A1 DISPATCH adsp_down=1 rc=0\n");
#endif
		complete_all(&s->state_reply);
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
MODULE_DESCRIPTION("P472 A0b APRv2 ADSP readiness + Q6CORE version diagnostics (no audio card)");
