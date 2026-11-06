// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) 2017-2019 The Linux Foundation. All rights reserved.
 */

#include <linux/module.h>
#include <linux/spinlock.h>
#include <linux/mutex.h>
#include <linux/wait.h>
#include <linux/delay.h>
#include <linux/rpmsg.h>
#include <ipc/apr_tal.h>
#include <linux/of_device.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <linux/atomic.h>
#include <linux/completion.h>
#include <linux/workqueue.h>
#include <linux/srcu.h>
#include <linux/hardirq.h>
#include <ipc/apr.h>

enum apr_channel_state {
	APR_CH_DISCONNECTED,
	APR_CH_CONNECTED,
};

#define APR_MAXIMUM_NUM_OF_RETRIES 2
/* P472_A1_TG_TAL_REMOTE_PID_A0B_DEFERRED_RX_V1 */
#define P472_TG_APR_GET_STATE 0x0001290c
#define P472_TG_APR_GET_STATE_RSP 0x0001290d
#define P472_TG_APR_RX_MAX 8192
#define P472_TG_APR_RX_BOUND 256
#define P472_TG_APR_WAIT_MS 100
#define P472_TG_APR_POLL_MS 50
#define P472_TG_APR_DEADLINE_MS 10000

/* EXPERIMENTAL only: direct APR callbacks may sleep under TG's r_lock.
 * Leave disabled during normal phone operation.
 */
static bool p472_tg_apr_sync_rx;
module_param_named(sync_rx_experimental, p472_tg_apr_sync_rx, bool, 0600);
MODULE_PARM_DESC(sync_rx_experimental,
	"Unsafe TG-style synchronous RX callback (default off)");
static atomic64_t p472_tg_apr_rx_drops = ATOMIC64_INIT(0);

extern void p472_tg_apr_a0b_ready(void);
extern void p472_tg_apr_a0b_down(void);

struct p472_tg_ctx {
	spinlock_t rx_lock; /* serialize RX queueing against RPMsg remove */
	struct rpmsg_device *rpdev;
	struct apr_svc_ch_dev *channel;
	struct work_struct ready_work;
	struct workqueue_struct *rx_wq;
	struct completion state_completion;
	atomic_t pending;
	atomic_t queued;
	atomic_t rx_seen;
	bool removing;
	u32 adsp_state;
};
struct p472_tg_rx_packet {
	struct work_struct work;
	struct p472_tg_ctx *ctx;
	int len;
	u8 data[];
};
DEFINE_STATIC_SRCU(p472_tg_rx_srcu);

/* Each RX drop increments the count. Ratelimited printk may coalesce logs.
 * Partial headers have svc=-1/opcode=0 until those fields are available.
 */
static int p472_tg_apr_rx_drop(struct rpmsg_device *rpdev,
				const void *data, int len, int error,
				const char *reason)
{
	const struct apr_hdr *hdr = data;
	s64 n = atomic64_inc_return(&p472_tg_apr_rx_drops);
	int svc = -1;
	u32 opcode = 0;
	__le32 wire;

	if (data && len > offsetof(struct apr_hdr, dest_svc))
		svc = hdr->dest_svc;
	if (data && len >= sizeof(*hdr)) {
		memcpy(&wire, (const u8 *)data + offsetof(struct apr_hdr, opcode),
		       sizeof(wire));
		opcode = le32_to_cpu(wire);
	}
	dev_warn_ratelimited(&rpdev->dev,
		"P472 TG APR_RX_DROP count=%lld reason=%s rc=%d len=%d svc=%d opcode=0x%08x\n",
		(long long)n, reason, error, len, svc, opcode);
	return error;
}


static struct apr_svc_ch_dev
	apr_svc_ch[APR_DL_MAX][APR_DEST_MAX][APR_CLIENT_MAX];

/**
 * apr_tal_write() - Write a message across to the remote processor
 * @apr_ch: apr channel handle
 * @data: buffer that needs to be transferred over the channel
 * @pkt_priv: private data of the packet
 * @len: length of the buffer
 *
 * Returns len of buffer successfully transferred on success
 * and an appropriate error value on failure.
 */
int apr_tal_write(struct apr_svc_ch_dev *apr_ch, void *data,
			   struct apr_pkt_priv *pkt_priv, int len)
{
	int rc = 0, retries = 0;
	unsigned long flags;
	struct rpmsg_device *rpdev = NULL;

	if (!apr_ch || len > APR_MAX_BUF ||
	    apr_ch->channel_state != APR_CH_CONNECTED)
		return -EINVAL;

	spin_lock_irqsave(&apr_ch->w_lock, flags);
	rpdev = apr_ch->handle;
	if (!rpdev) {
		spin_unlock_irqrestore(&apr_ch->w_lock, flags);
		return -EINVAL;
	}

	do {
		if (rc == -EAGAIN)
			udelay(50);
		rc = rpmsg_trysend(rpdev->ept, data, len);
	} while (rc == -EAGAIN && retries++ < APR_MAXIMUM_NUM_OF_RETRIES);
	spin_unlock_irqrestore(&apr_ch->w_lock, flags);

	pr_info_ratelimited("P472 TG APR_SEND_PKT len=%d rpmsg_rc=%d\n",
			    len, rc);
	if (rc)
		pr_err("%s: Unable to send the packet, rc:%d\n", __func__, rc);
	else
		rc = len;

	return rc;
}
EXPORT_SYMBOL(apr_tal_write);

/**
 * apr_tal_rx_intents_config() - Configure glink intents for remote processor
 * @apr_ch: apr channel handle
 * @num_of_intents: number of intents
 * @size: size of the intents
 *
 * This api is not supported with RPMSG. Returns 0 to indicate success
 */
int apr_tal_rx_intents_config(struct apr_svc_ch_dev *apr_ch,
			      int num_of_intents, uint32_t size)
{
	pr_debug("%s: NO-OP\n", __func__);
	return 0;
}
EXPORT_SYMBOL(apr_tal_rx_intents_config);

/**
 * apr_tal_start_rx_rt() - Set RT thread priority for APR RX transfer
 * @apr_ch: apr channel handle
 *
 * This api is not supported with RPMSG as message transfer occurs
 * in client's context. Returns 0 to indicate success.
 */
int apr_tal_start_rx_rt(struct apr_svc_ch_dev *apr_ch)
{
	pr_debug("%s: NO-OP\n", __func__);
	return 0;
}
EXPORT_SYMBOL(apr_tal_start_rx_rt);

/**
 * apr_tal_end_rx_rt() - Remove RT thread priority for APR RX transfer
 * @apr_ch: apr channel handle
 *
 * This api is not supported with RPMSG. Returns 0 to indicate success
 */
int apr_tal_end_rx_rt(struct apr_svc_ch_dev *apr_ch)
{
	pr_debug("%s: NO-OP\n", __func__);
	return 0;
}
EXPORT_SYMBOL(apr_tal_end_rx_rt);

/**
 * apr_tal_open() - Open a transport channel for data transfer
 * on remote processor.
 * @clnt: apr client, audio or voice
 * @dest: destination remote processor for which apr channel is requested for.
 * @dl: type of data link
 * @func: callback function to handle data transfer from remote processor
 * @priv: private data of the client
 *
 * Returns apr_svc_ch_dev handle on success and NULL on failure.
 */
struct apr_svc_ch_dev *apr_tal_open(uint32_t clnt, uint32_t dest, uint32_t dl,
				    apr_svc_cb_fn func, void *priv)
{
	int rc = 0;
	struct apr_svc_ch_dev *apr_ch = NULL;

	if ((clnt != APR_CLIENT_AUDIO) || (dest >= APR_DEST_MAX) ||
	    (dl != APR_DL_SMD)) {
		pr_err("%s: Invalid params, clnt:%d, dest:%d, dl:%d\n",
		       __func__, clnt, dest, dl);
		return NULL;
	}
	apr_ch = &apr_svc_ch[dl][dest][clnt];
	mutex_lock(&apr_ch->m_lock);
	if (!apr_ch->handle) {
		rc = wait_event_timeout(apr_ch->wait,
			(apr_ch->channel_state == APR_CH_CONNECTED), 5 * HZ);

		if (rc == 0) {
			pr_err("%s: TIMEOUT for APR_CH_CONNECTED event\n",
				__func__);
			rc = -ETIMEDOUT;
			goto unlock;
		}
	}

	pr_debug("%s: Channel connected, returning handle :%pK\n",
			 __func__, apr_ch->handle);
	apr_ch->func = func;
	apr_ch->priv = priv;

unlock:
	mutex_unlock(&apr_ch->m_lock);
	return rc ? NULL : apr_ch;
}
EXPORT_SYMBOL(apr_tal_open);

/**
 * apr_tal_close() - Close transport channel on remote processor.
 * @apr_ch: apr channel handle
 *
 * Returns 0 on success and an appropriate error value on failure.
 */
int apr_tal_close(struct apr_svc_ch_dev *apr_ch)
{
	int rc = 0;

	if (!apr_ch || !apr_ch->handle) {
		rc = -EINVAL;
		goto exit;
	}

	mutex_lock(&apr_ch->m_lock);
	apr_ch->func = NULL;
	apr_ch->priv = NULL;
	mutex_unlock(&apr_ch->m_lock);
	/* Workqueue callbacks run outside RX/IRQ context.  SRCU drains
	 * callbacks that observed the previous registered service.
	 */
	synchronize_srcu(&p472_tg_rx_srcu);

exit:
	return rc;
}
EXPORT_SYMBOL(apr_tal_close);


static void p472_tg_apr_rx_work(struct work_struct *work)
{
	struct p472_tg_rx_packet *packet =
		container_of(work, struct p472_tg_rx_packet, work);
	struct apr_svc_ch_dev *ch = packet->ctx->channel;
	apr_svc_cb_fn func;
	void *priv;
	int idx;

	if (!READ_ONCE(packet->ctx->removing)) {
		idx = srcu_read_lock(&p472_tg_rx_srcu);
		func = READ_ONCE(ch->func);
		priv = READ_ONCE(ch->priv);
		if (func)
			func(packet->data, packet->len, priv);
		else
			p472_tg_apr_rx_drop(packet->ctx->rpdev, packet->data,
				packet->len, -ENOTCONN, "no_apr_callback");
		srcu_read_unlock(&p472_tg_rx_srcu, idx);
	} else {
		p472_tg_apr_rx_drop(packet->ctx->rpdev, packet->data,
				packet->len, -ENODEV, "removing_drain");
	}
	atomic_dec(&packet->ctx->queued);
	kfree(packet);
}

static void p472_tg_apr_ready_work(struct work_struct *work)
{
	struct p472_tg_ctx *ctx = container_of(work, struct p472_tg_ctx,
					       ready_work);
	struct apr_hdr cmd = { };
	unsigned long deadline, waited;
	int rc, attempts = 0;

	/* A0b matches the working ADSP GET_STATE handshake. */
	msleep(100);
	deadline = jiffies + msecs_to_jiffies(P472_TG_APR_DEADLINE_MS);
	cmd.hdr_field = (2 << 8) | (5 << 4);
	cmd.pkt_size = sizeof(cmd);
	cmd.src_svc = APR_SVC_ADSP_CORE;
	cmd.src_domain = APR_DOMAIN_APPS;
	cmd.dest_svc = APR_SVC_ADSP_CORE;
	cmd.dest_domain = APR_DOMAIN_ADSP;
	cmd.opcode = P472_TG_APR_GET_STATE;
	while (time_before(jiffies, deadline)) {
		if (READ_ONCE(ctx->removing))
			return;
		attempts++;
		reinit_completion(&ctx->state_completion);
		WRITE_ONCE(ctx->adsp_state, 0);
		atomic_set(&ctx->pending, 1);
		rc = rpmsg_send(ctx->rpdev->ept, &cmd, sizeof(cmd));
		dev_info(&ctx->rpdev->dev,
			 "P472 TG APR_SEND GET_STATE attempt=%d rc=%d\n",
			 attempts, rc);
		if (!rc) {
			waited = wait_for_completion_timeout(&ctx->state_completion,
				msecs_to_jiffies(P472_TG_APR_WAIT_MS));
			atomic_set(&ctx->pending, 0);
			if (READ_ONCE(ctx->removing))
				return;
			if (waited && READ_ONCE(ctx->adsp_state)) {
				dev_info(&ctx->rpdev->dev,
					"P472 TG APR ADSP_READY state=%u attempts=%d\n",
					READ_ONCE(ctx->adsp_state), attempts);
				p472_tg_apr_a0b_ready();
				return;
			}
		} else {
			atomic_set(&ctx->pending, 0);
		}
		if (time_after_eq(jiffies, deadline))
			break;
		msleep(P472_TG_APR_POLL_MS);
	}
	if (!READ_ONCE(ctx->removing))
		dev_err(&ctx->rpdev->dev,
			"P472 TG APR ADSP_READY_TIMEOUT attempts=%d\n", attempts);
}

static int apr_tal_rpmsg_callback(struct rpmsg_device *rpdev,
				  void *data, int len, void *priv, u32 addr)
{
	struct p472_tg_ctx *ctx = dev_get_drvdata(&rpdev->dev);
	struct p472_tg_rx_packet *packet;
	const struct apr_hdr *hdr = data;
	int seen;
	int idx;
	unsigned long flags;
	u16 hdr_len;
	__le32 state;

	if (!ctx || READ_ONCE(ctx->removing) || !data)
		return p472_tg_apr_rx_drop(rpdev, data, len, -ENODEV,
					     "channel_unavailable");
	seen = atomic_inc_return(&ctx->rx_seen);
	if (seen <= 32) {
		dev_info(&rpdev->dev,
			"P472 TG APR_RX_RAW seq=%d len=%d\n", seen, len);
		if (len > 0)
			print_hex_dump(KERN_INFO, "P472 TG APR_RX_RAW ",
				       DUMP_PREFIX_OFFSET, 16, 1, data,
				       min_t(int, len, 512), false);
	}
	if (len < sizeof(*hdr) || len > P472_TG_APR_RX_MAX)
		return p472_tg_apr_rx_drop(rpdev, data, len, -EMSGSIZE,
					     "packet_size");
	hdr_len = ((hdr->hdr_field >> 4) & 0x0f) * 4;
	if (hdr_len < sizeof(*hdr) || hdr_len > len ||
	    hdr->pkt_size != len)
		return p472_tg_apr_rx_drop(rpdev, data, len, -EPROTO,
					     "invalid_apr_header");
	if (hdr->opcode == P472_TG_APR_GET_STATE_RSP &&
	    hdr->src_domain == APR_DOMAIN_ADSP &&
	    hdr->src_svc == APR_SVC_ADSP_CORE &&
	    atomic_read(&ctx->pending) && len >= hdr_len + 4) {
		memcpy(&state, (u8 *)data + hdr_len, sizeof(state));
		WRITE_ONCE(ctx->adsp_state, le32_to_cpu(state));
		complete(&ctx->state_completion);
		return 0;
	}
	/* Diagnostic-only direct TG dispatch. Never call client code from an
	 * atomic/IRQ context. Otherwise keep serialized deferred delivery.
	 * Client callbacks can still sleep; direct spinlocked dispatch is unsafe
	 * unless each registered client was audited as strictly non-sleeping.
	 */
	if (unlikely(READ_ONCE(p472_tg_apr_sync_rx))) {
		if (in_interrupt() || in_atomic() || irqs_disabled() ||
		    atomic_read(&ctx->queued)) {
			dev_warn_ratelimited(&rpdev->dev,
				"P472 TG APR_SYNC_FALLBACK atomic_or_queued=1\n");
		} else {
			struct apr_svc_ch_dev *ch = ctx->channel;
			apr_svc_cb_fn func;
			void *p;

			idx = srcu_read_lock(&p472_tg_rx_srcu);
			spin_lock_irqsave(&ch->r_lock, flags);
			func = READ_ONCE(ch->func);
			p = READ_ONCE(ch->priv);
			if (func && !READ_ONCE(ctx->removing))
				func(data, len, p);
			else
				func = NULL;
			spin_unlock_irqrestore(&ch->r_lock, flags);
			srcu_read_unlock(&p472_tg_rx_srcu, idx);
			if (!func)
				return p472_tg_apr_rx_drop(rpdev, data, len,
						-ENOTCONN, "sync_unavailable");
			return 0;
		}
	}
	if (!ctx->rx_wq)
		return p472_tg_apr_rx_drop(rpdev, data, len, -ENODEV,
					     "queue_unavailable");
	if (atomic_inc_return(&ctx->queued) > P472_TG_APR_RX_BOUND) {
		atomic_dec(&ctx->queued);
		return p472_tg_apr_rx_drop(rpdev, data, len, -ENOSPC,
					     "queue_full");
	}
	packet = kmalloc(sizeof(*packet) + len, GFP_ATOMIC);
	if (!packet) {
		atomic_dec(&ctx->queued);
		return p472_tg_apr_rx_drop(rpdev, data, len, -ENOMEM,
					     "alloc_failure");
	}
	packet->ctx = ctx;
	packet->len = len;
	memcpy(packet->data, data, len);
	INIT_WORK(&packet->work, p472_tg_apr_rx_work);
	/* A callback that passed the first removing check must not race
	 * with destroy_workqueue() in the .remove path.
	 */
	spin_lock_irqsave(&ctx->rx_lock, flags);
	if (ctx->removing || !ctx->rx_wq) {
		spin_unlock_irqrestore(&ctx->rx_lock, flags);
		atomic_dec(&ctx->queued);
		kfree(packet);
		return p472_tg_apr_rx_drop(rpdev, data, len, -ENODEV,
					     "remove_race");
	}
	if (!queue_work(ctx->rx_wq, &packet->work)) {
		spin_unlock_irqrestore(&ctx->rx_lock, flags);
		atomic_dec(&ctx->queued);
		kfree(packet);
		return p472_tg_apr_rx_drop(rpdev, data, len, -EIO,
					     "queue_work_failed");
	}
	spin_unlock_irqrestore(&ctx->rx_lock, flags);
	return 0;
}

static int apr_tal_rpmsg_probe(struct rpmsg_device *rpdev)
{
	struct p472_tg_ctx *ctx;
	struct device_node *edge;
	struct apr_svc_ch_dev *apr_ch;
	u32 remote_pid;
	int rc;

	if (strcmp(rpdev->id.name, "apr_audio_svc"))
		return -ENODEV;
	edge = rpdev->dev.parent ? rpdev->dev.parent->of_node : NULL;
	if (!edge || of_property_read_u32(edge, "qcom,remote-pid",
					 &remote_pid) || remote_pid != 2) {
		dev_err(&rpdev->dev,
			"P472 TG APR_TAL remote-pid rejected only_adsp=2\n");
		return -ENODEV;
	}
	apr_ch = &apr_svc_ch[APR_DL_SMD][APR_DEST_QDSP6][APR_CLIENT_AUDIO];
	ctx = devm_kzalloc(&rpdev->dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ctx->rpdev = rpdev;
	ctx->channel = apr_ch;
	spin_lock_init(&ctx->rx_lock);
	init_completion(&ctx->state_completion);
	atomic_set(&ctx->pending, 0);
	atomic_set(&ctx->queued, 0);
	atomic_set(&ctx->rx_seen, 0);
	ctx->rx_wq = alloc_workqueue("p472_tg_apr_rx",
				    WQ_UNBOUND | WQ_MEM_RECLAIM, 1);
	if (!ctx->rx_wq)
		return -ENOMEM;
	INIT_WORK(&ctx->ready_work, p472_tg_apr_ready_work);
	dev_set_drvdata(&rpdev->dev, ctx);
	apr_ch->handle = rpdev;
	apr_ch->channel_state = APR_CH_CONNECTED;
	wake_up(&apr_ch->wait);
	dev_info(&rpdev->dev,
		 "P472 TG APR_TAL dest=adsp remote-pid=%u hdr_dynamic=1 max_pkt=8192\n",
		 remote_pid);
	rc = schedule_work(&ctx->ready_work) ? 0 : -EBUSY;
	if (rc) {
		apr_ch->handle = NULL;
		apr_ch->channel_state = APR_CH_DISCONNECTED;
		dev_set_drvdata(&rpdev->dev, NULL);
		destroy_workqueue(ctx->rx_wq);
	}
	return rc;
}

static void apr_tal_rpmsg_remove(struct rpmsg_device *rpdev)
{
	struct p472_tg_ctx *ctx = dev_get_drvdata(&rpdev->dev);
	struct apr_svc_ch_dev *apr_ch;
	unsigned long flags;

	if (!ctx)
		return;
	apr_ch = ctx->channel;
	/* Stop new RX work submissions before draining the queue. */
	spin_lock_irqsave(&ctx->rx_lock, flags);
	WRITE_ONCE(ctx->removing, true);
	spin_unlock_irqrestore(&ctx->rx_lock, flags);
	/* Block APR TX and drop the RPMsg endpoint while in-flight
	 * rpmsg_trysend() callers are serialized by w_lock.
	 */
	spin_lock_irqsave(&apr_ch->w_lock, flags);
	apr_ch->channel_state = APR_CH_DISCONNECTED;
	apr_ch->handle = NULL;
	spin_unlock_irqrestore(&apr_ch->w_lock, flags);
	cancel_work_sync(&ctx->ready_work);
	complete_all(&ctx->state_completion);
	destroy_workqueue(ctx->rx_wq);
	/* Drain any opt-in synchronous RX callback before devm releases ctx. */
	synchronize_srcu(&p472_tg_rx_srcu);
	p472_tg_apr_a0b_down();
	dev_set_drvdata(&rpdev->dev, NULL);
	dev_info(&rpdev->dev,
		 "P472 TG APR_TAL channel=down pending=0 queued=%d rx_drops=%lld\n",
		 atomic_read(&ctx->queued),
		 (long long)atomic64_read(&p472_tg_apr_rx_drops));
}

static const struct rpmsg_device_id apr_tal_rpmsg_match[] = {
	{ "apr_audio_svc" },
	{}
};

static struct rpmsg_driver apr_tal_rpmsg_driver = {
	.probe = apr_tal_rpmsg_probe,
	.remove = apr_tal_rpmsg_remove,
	.callback = apr_tal_rpmsg_callback,
	.id_table = apr_tal_rpmsg_match,
	.drv = {
		.name = "apr_tal_rpmsg",
	},
};

/**
 * apr_tal_int() - Registers rpmsg driver with rpmsg framework.
 *
 * Returns 0 on success and an appropriate error value on failure.
 */
int apr_tal_init(void)
{
	int i, j, k;
	int ret;

	memset(apr_svc_ch, 0, sizeof(apr_svc_ch));
	for (i = 0; i < APR_DL_MAX; i++) {
		for (j = 0; j < APR_DEST_MAX; j++) {
			for (k = 0; k < APR_CLIENT_MAX; k++) {
				init_waitqueue_head(&apr_svc_ch[i][j][k].wait);
				spin_lock_init(&apr_svc_ch[i][j][k].w_lock);
				spin_lock_init(&apr_svc_ch[i][j][k].r_lock);
				mutex_init(&apr_svc_ch[i][j][k].m_lock);
			}
		}
	}
	ret = register_rpmsg_driver(&apr_tal_rpmsg_driver);
	return ret;
}
EXPORT_SYMBOL(apr_tal_init);

/**
 * apr_tal_exit() - De-register rpmsg driver with rpmsg framework.
 */
void apr_tal_exit(void)
{
	unregister_rpmsg_driver(&apr_tal_rpmsg_driver);
}
EXPORT_SYMBOL(apr_tal_exit);

