# P467 MSS first-boot engineering report — P466 base

Base commit: 2770bd8ff1650c538ac44a4fb857e5bd46352f49. Manual MSS only. No IPA/rmnet, modem FastRPC, glinkpkt DATA, or ICNSS.

## Port decisions

- New 5.10 PAS descriptor: compatible qcom,sm6350-mss-pas; PAS 4; firmware modem.mdt; SMEM crash 421; sysmon modem; ssctl 0x12; auto_boot=false; AOSS load_state MODEM=2.
- Reuse the P451 balanced regulator-level votes at 384: TG PM6150A S1 (vdd_cx) and S6 (vdd_mss). Same handling on PAS auth failure and handover; no competing rpmhpd.
- Replace the original PAS parent device_wakeup_enable() with a checked device_init_wakeup(...,true) for both ADSP and MSS; preserve probe/remove cleanup. Does not guarantee asynchronous GLINK re-probe completion.
- DT edge remote-pid=1, IPCC client=2, channel children only IPCRTR and glink_ssr, remove old duplicate GLINK transport owner. Preserve IRQ SPI136 and SMP2P slave-kernel 0/1/2/3; bit7 shutdown-ack remains named but UNHANDLED by 5.10 q6v5, no fake handler.
- RMTFS is the downstream qcom,sharedmem-uio ABI (not upstream qcom_rmtfs_mem): 0x280000 bytes, client 1, 4KiB guards, physically mapped UIO name rmtfs. SCM-off probe EPROBE_DEFER; real qcom_scm_assign_mem with VMIDs HLOS=3 MSS_MSA=15 before uio_register_device. UIO number 0 is expected only if nothing else registers first.

## Does TG load IPA firmware first?

NO in the captured TG boot: at 7.178498s modem subsystem get begins, 7.184468s modem.mdt starts loading, 8.649651s lagoon_ipa_fws get occurs, 8.650350s IPA FW starts loading, and 8.765163s IPA FW is loaded. This proves MSS loading STARTS before IPA firmware in this boot; it does NOT prove an MSS-only GKI image can finish remote startup with IPA disabled. Source: library file 05-plus-2s.dmesg.txt lines 4817-4824 and 4968-4981.

## What is modem_shared_mem_region at d0000000?

It is a separate 96MiB reserved modem shared-memory pool owned by downstream qcom,memshare client_4 in TG's DTBO; not the 2.5MiB RMTFS UIO region. TG logs at 0.595160s the reserved memory assignment and at 0.595561s the memshare client reports size zero / no registered clients. The original P466 boot-final.dts did not contain the d0000000 node. Do not invent a 5.10 owner or expose that region through UIO; retain any live DTBO reservation and defer a dedicated memshare port until runtime evidence requires it. Source: library 01-post-fs-data.dmesg.txt lines 64-66, 489-495.

## Gating and safety

Keep P466 FastRPC DMA-BUF + unbounded listener waits, P463 suspend-safe guard, P460B, P457 apps-SMMU, Phase206 default veto, manual SCM/ADSP knobs, and P462 watchdog unchanged.
Expect markers: P467 MSS PROBE, P467 MSS RAILS, P467 MSS PAS_AUTH, P467 MSS GLINK REGISTER, P467 RMTFS UIO, P467 PAS PARENT_WAKE.
First verify no autoboot before manual start and RMTFS SCM assign before UIO. Never force RF/data or deliberate SSR in this phase.
Before invoking MSS, verify backups of modemst1, modemst2, fsg, fsc, efs, sec_efs and persist and known-good boot/recovery access. Modem code can write NV/EFS, so a failed test may be more than a harmless reboot.
