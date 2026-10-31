# P472 A0/D0 audit: legacy APRv2/Q6CORE on the running ADSP

**State: SOURCE AUDIT ONLY. No audio code staged, no image built, no phone test, no ARM.**
P472 and P473 are independent children of the hardware-data-working P471 commit `4ea703414a90078232fbdece6f185df311dde8db`.
TG kernel pin: `micr0softstore/samsung_android_kernel_a52xq@6bf351bdf18bdb228db79e66f14a7a9c0178e5d7`.
Source paths below are relative to that TG tree, unless indicated otherwise.
P471 IPA, GSI, rmnet, MSS, P469B fallback, SELinux and calibrated storage are out of scope.

## A0 contract audit, evidence and conclusions

| Requirement | Source evidence | D0 disposition |
| --- | --- | --- |
| Audio destination = ADSP, not CDSP | `arch/arm64/boot/dts/vendor/qcom/lagoon.dtsi:2319-2344` ADSP GLINK edge includes `apr_audio_svc` with intents `<0x200 20>`; adjacent `IPCRTR` and `fastrpcglink-apps-dsp`. | TG DT verified. User reports ADSP already operational on Mangrove; 5.10 APR rpmsg channel enumeration NOT yet proved. |
| APR transport | `techpack/audio/ipc/apr_tal_rpmsg.c:207-278` registers `rpmsg_driver`, matches `apr_audio_svc`, checks parent `mbox-names` contains `adsp`, sets `APR_DL_SMD/APR_DEST_QDSP6/APR_CLIENT_AUDIO`, handles removal by clearing handle/state. | **Port legacy rpmsg APR**, not SPF/GPR. Do not infer the channel is live solely from DT or ADSP FastRPC. |
| Precisely which APR variant | `techpack/audio/config/litoauto.conf:11` has `CONFIG_MSM_QDSP6_APRV2_RPMSG=m`. `techpack/audio/ipc/Kbuild:113-116,186-189` puts `apr.o`, `apr_v2.o`, `apr_tal_rpmsg.o` into `apr_dlkm`. | **APRv2**, not APRv3 or GPR. Original TG techpack builds as modules; for Mangrove evaluate controlled built-in linking without duplicate transport instances. |
| Q6CORE command | `techpack/audio/dsp/q6core.c:545-598` builds `APR_MSG_TYPE_SEQ_CMD` header, opcode `AVCS_CMD_GET_FWK_VERSION`, sends with `apr_send_pkt`, waits for real response and returns error or `-ETIMEDOUT`. `q6core.c:26` TG `TIMEOUT_MS=1000`; `q6core.c:34` ADSP-ready timeout is 3000ms. | Reuse real Q6CORE completion and validate response opcode/version. **A0 outer readiness budget <=3000ms**, no infinite waits or synthetic successful version. Distinguish 1s per-TG command timeout from A0's 3s readiness cap. |
| Q6CORE dependencies | `techpack/audio/dsp/Kbuild:114-131,176-181,252-268` Q6 core also links calibration, ADM, AFE, ASM, voice, ION, RTAC etc under `q6_dlkm`; PDR/SSR notifier separate modules. | A0 may need a narrow subset or a faithful dependency bundle. Do not pull the full A1 codec/speaker stack just to print a ready marker. Do not stub missing APIs. |
| ADSP and modem SSR/PDR | `techpack/audio/dsp/audio_notifier.c:57-95` defines SSR_ADSP, SSR_MODEM and PDR_ADSP. `audio_notifier.c:531-574` exposes client notifier API; `apr.c:1196-1209` registers notifier and snd_event paths. | Reuse existing Mangrove TG-compatible `drivers/a52_pil/subsystem_notif.c` + P470-A6c canonical bridge; **one notifier ownership route**. P470-A4b's MSS producer does NOT itself establish the ADSP producer; audit and add ADSP producer separately. |
| Prior boot evidence | Work order reports PAS1 ADSP up with FastRPC sensors and GLINK. | **Hardware report only**; direct APR/Q6CORE round trip remains to be measured. |

### A0 build and safety gates, proposed next stage

1. Pin the exact TG APRv2 files `ipc/apr.c`, `ipc/apr_v2.c`, `ipc/apr_tal_rpmsg.c` and the Q6CORE subset. Generate a source/API-diff report against the pinned Android12 5.10 kernel and selected 5.10-compatible Qualcomm donor. Fail if duplicate `apr_audio_svc` transports, duplicate SRCU/SSR providers, or unresolved references appear.
2. Use the *existing* ADSP GLINK/rpmsg edge and PAS1 ownership. Match only the audio rpmsg channel. No new remoteproc boot owner, no CDSP start, no duplicate ADSP or modem notifier, no IPA/rmnet changes.
3. On real channel bind: print `P472 A0 APR_READY` only after the ADSP destination is genuinely connected. Submit `AVCS_CMD_GET_FWK_VERSION` with a bounded response and log `P472 A0 Q6CORE ver=...` only after validated reply; else `P472 A0 APR_TIMEOUT` or distinct negative errno. Explicitly account for ADSP SSR/unbind, fail closed and cancel pending requests; no stale handle use.
4. If firmware/SCM resources are missing return `-EPROBE_DEFER` as appropriate. Keep new audio probes behind a root-controlled staged enable until safe. No speaker I/O at A0, no forced Android card creation, and no calibration/EFS writes.
5. Require complete `Image` link, actual `System.map` symbols, one APR channel owner, and runtime Q6CORE reply before starting A1. CI source/link checks are NOT hardware proof.

## Subsequent stage dependencies, not part of A0

- **A1**: TG `asoc/kona.c` on `qcom,kona-asoc-snd`, Bolero/LPI/SoundWire, correct WCD codec from **live merged DT**, 33 PCM names, card `lito-lagoonmtp-snd-card` (id `litolagoonmtpsn`), 32-bit HAL compat ioctls, `/dev/msm_audio_cal`, `/dev/msm_rtac`, audio ION DMA SID `0x1001`; retain Samsung sysfs parent paths and genfscon. Confirm 5.10 mappings, not inferred.
- **A2**: TAS256x `18-004c` read-only chip ID first; GPIO 52/53 reset 55 IRQ 54, one client left 0x4d/right 0x4c; only then low-volume ringtone and real DMA IOVA/route trace. No writes to `/efs/tas25xx/*` or ACDB/calibration.
- **A3**: mic, MBHC and USB-C accessory. **A4**: q6voice MVM/CVS/CVP, normal consenting-number call only, no emergency calls. BT audio SLIMBUS_7/8 is jointly gated on P473 and A2.

## Missing proofs before A0 source port

- Extract the **actual boot-time merged FDT**, not merely TG DTS, to confirm active ADSP APR and audio dependencies; prior CI did not have the flashed DTBO.
- Pin a compatible 5.10 audio donor/review API adaptations (rpmsg device teardown, legacy notifier, completion, DMA, 32-bit ioctls). **No donor selected or binary compatibility asserted yet.**
- Confirm that a live `apr_audio_svc` rpmsg device is created in the P471 hardware baseline, and record baseline `/proc/asound/cards`, `/dev/msm_audio_cal`, `/dev/msm_rtac`, relevant `dmesg`.
- Retain the successful P471 data boot as immediate rollback. No change to IPA automatic arm state.

### Source reference links

- [TG APR transport](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio/ipc/apr_tal_rpmsg.c#L207-L278)
- [TG Q6CORE firmware-version query](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio/dsp/q6core.c#L545-L598)
- [TG APRv2 build](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio/ipc/Kbuild#L113-L125)
- [Existing Mangrove notifier bridge](https://github.com/GiulianoB-1/A526B-Mangrove-Kernel/blob/4ea703414a90078232fbdece6f185df311dde8db/scripts/470_a6c_notifier_abi.py)

**A0 audit decision:** TG APRv2/rpmsg + Q6CORE and the existing legacy notifier bridge are the required ABI direction. Implementation and hardware APR ready are **PENDING**, so this report does not authorize a flash.
