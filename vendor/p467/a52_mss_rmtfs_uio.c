// SPDX-License-Identifier: GPL-2.0-only
/*
 * P467 MSS RMTFS UIO — TG msm_sharedmem ABI, Qualcomm GKI 5.10 SCM API.
 * Deliberately NOT upstream qcom_rmtfs_mem (/dev/qcom_rmtfs_mem* ABI).
 * UIO mapping is published ONLY AFTER successful HLOS+MSS VM assignment.
 * No modem/IPA firmware boot here; PAS is root-controlled, auto_boot=false.
 */
#include <linux/dma-mapping.h>
#include <linux/dma-direct.h>
#include <linux/err.h>
#include <linux/io.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/qcom_scm.h>
#include <linux/sizes.h>
#include <linux/slab.h>
#include <linux/uio_driver.h>

#define P467_RMTFS_SIZE 0x280000U
#define P467_RMTFS_CLIENT_ID 1U
#define P467_GUARD SZ_4K

struct a52_rmtfs {
	struct uio_info uio;
	void *cpu;
	dma_addr_t dma;
	phys_addr_t phys;
	size_t allocation;
	unsigned int vmids;
	bool assigned;
	bool registered;
};

static int a52_rmtfs_mmap(struct uio_info *info,
			   struct vm_area_struct *vma)
{
	struct uio_mem *mem;
	unsigned long size = vma->vm_end - vma->vm_start;

	if (vma->vm_pgoff != 0)
		return -EINVAL;
	mem = &info->mem[0];
	if (size > mem->size)
		return -EINVAL;
	vma->vm_page_prot = pgprot_writecombine(vma->vm_page_prot);
	return remap_pfn_range(vma, vma->vm_start,
			       mem->addr >> PAGE_SHIFT, size,
			       vma->vm_page_prot);
}

/* Never free memory while it remains assigned to the modem VM.
 * Freeing would allow an unrelated kernel allocation to reuse pages
 * accessible to MSS. In such a failure, deliberately leak and log.
 */
static void a52_rmtfs_release(struct device *dev, struct a52_rmtfs *m)
{
	int rc;
	struct qcom_scm_vmperm host = {
		.vmid = QCOM_SCM_VMID_HLOS, .perm = QCOM_SCM_PERM_RW,
	};

	if (m->registered) {
		uio_unregister_device(&m->uio);
		m->registered = false;
	}
	if (m->assigned) {
		rc = qcom_scm_assign_mem(m->phys, P467_RMTFS_SIZE,
					  &m->vmids, &host, 1);
		if (rc) {
			dev_err(dev,
			    "P467 RMTFS UIO unassign FAILED rc=%d: retaining memory; DO NOT recycle MSS-owned pages\n",
			    rc);
			return;
		}
		m->assigned = false;
	}
	if (m->cpu) {
		dma_free_coherent(dev, m->allocation, m->cpu, m->dma);
		m->cpu = NULL;
	}
}

static int a52_rmtfs_probe(struct platform_device *pdev)
{
	struct a52_rmtfs *m;
	struct resource *res;
	u32 client = 0;
	int rc;
	struct qcom_scm_vmperm perms[2] = {
		{ .vmid = QCOM_SCM_VMID_HLOS, .perm = QCOM_SCM_PERM_RW },
		{ .vmid = QCOM_SCM_VMID_MSS_MSA, .perm = QCOM_SCM_PERM_RW },
	};

	/* No UIO node before the explicit SCM activation knob is used. */
	if (!qcom_scm_is_available())
		return -EPROBE_DEFER;
	if (!pdev->dev.of_node)
		return -ENODEV;
	rc = of_property_read_u32(pdev->dev.of_node, "qcom,client-id", &client);
	if (rc || client != P467_RMTFS_CLIENT_ID ||
	    !of_property_read_bool(pdev->dev.of_node, "qcom,guard-memory"))
		return -EINVAL;
	res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	if (!res || resource_size(res) != P467_RMTFS_SIZE ||
	    res->start != 0)
		return -EINVAL;

	m = devm_kzalloc(&pdev->dev, sizeof(*m), GFP_KERNEL);
	if (!m)
		return -ENOMEM;
	m->allocation = P467_RMTFS_SIZE + 2 * P467_GUARD;
	/* The vendor userspace mmap contract expects a physical, 32-bit
	 * address; use a direct-DMA device with no IOMMU on this DT node.
	 */
	rc = dma_set_mask_and_coherent(&pdev->dev, DMA_BIT_MASK(32));
	if (rc)
		return rc;
	m->cpu = dma_alloc_coherent(&pdev->dev, m->allocation,
				     &m->dma, GFP_KERNEL);
	if (!m->cpu)
		return -ENOMEM;
	m->phys = dma_to_phys(&pdev->dev, m->dma) + P467_GUARD;
	if (!PAGE_ALIGNED(m->phys)) {
		rc = -EINVAL;
		goto unwind;
	}
	m->vmids = BIT(QCOM_SCM_VMID_HLOS);
	rc = qcom_scm_assign_mem(m->phys, P467_RMTFS_SIZE, &m->vmids,
				 perms, ARRAY_SIZE(perms));
	if (rc) {
		dev_err(&pdev->dev,
			"P467 RMTFS UIO SCM_ASSIGN_FAIL rc=%d size=%#x client=%u\n",
			rc, P467_RMTFS_SIZE, client);
		goto unwind;
	}
	m->assigned = true;

	m->uio.name = "rmtfs";
	m->uio.version = "1.0";
	m->uio.mmap = a52_rmtfs_mmap;
	m->uio.mem[0].addr = m->phys;
	m->uio.mem[0].size = P467_RMTFS_SIZE;
	m->uio.mem[0].memtype = UIO_MEM_PHYS;
	rc = uio_register_device(&pdev->dev, &m->uio);
	if (rc)
		goto unwind;
	m->registered = true;
	platform_set_drvdata(pdev, m);
	dev_info(&pdev->dev,
		 "P467 RMTFS UIO client=%u phys=%pa size=%#x guard=4096+4096 vmid_hlos=%d vmid_mss=%d scm_assign=0 rc=0 name=rmtfs\n",
		 client, &m->phys, P467_RMTFS_SIZE,
		 QCOM_SCM_VMID_HLOS, QCOM_SCM_VMID_MSS_MSA);
	return 0;
unwind:
	a52_rmtfs_release(&pdev->dev, m);
	return rc;
}

static int a52_rmtfs_remove(struct platform_device *pdev)
{
	struct a52_rmtfs *m = platform_get_drvdata(pdev);

	if (m)
		a52_rmtfs_release(&pdev->dev, m);
	return 0;
}

static const struct of_device_id a52_rmtfs_of_match[] = {
	{ .compatible = "qcom,sharedmem-uio" },
	{}
};
MODULE_DEVICE_TABLE(of, a52_rmtfs_of_match);

static struct platform_driver a52_rmtfs_driver = {
	.probe = a52_rmtfs_probe,
	.remove = a52_rmtfs_remove,
	.driver = {
		.name = "a52-mss-sharedmem-uio",
		.of_match_table = a52_rmtfs_of_match,
	},
};
module_platform_driver(a52_rmtfs_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("P467 RMTFS UIO vendor ABI, guarded modem SCM assignment");
