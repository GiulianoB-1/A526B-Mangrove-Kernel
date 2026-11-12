# P472 A3a → A3b → A3c: staged audio port and source audit

## Proven parent / hard gates

- Parent source: `agent/p476-h2-only-a2a-hlt-no-arm` @ `2884655a393369636489d57e82ca9ce8255d3d1a`; inherited successful A2a-HLT `23ca01ab33ed93c5c32c0ab2fba476d792641b69`.
- A3a/A3b/A3c use separate Kconfig gates, fail-closed source audits and unique HLT-only artifact filenames. No automatic ARM, no userland/SELinux workarounds, no speaker amplification, no EFS/ACDB/voice-call writes.
- Child testing is conditional on the **parent H2-only image passing hardware** (keyboard at ~2 min, BT <=2/10 min, LTE, nohlt=0). CI PASS is not hardware acceptance.

## A3a Q6 services: pinned 4.19 dependency closure

**CONFIRMED:** TG `micr0softstore/samsung_android_kernel_a52xq@6bf351bdf18bdb228db79e66f14a7a9c0178e5d7`.

- [TG `techpack/audio/dsp/Kbuild:114-130`](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio/dsp/Kbuild#L114-L130) lists `msm-audio-event-notify`, existing A2a `audio_calibration`, `audio_cal_utils`, `q6adm`, `q6afe`, `q6asm`, `q6audio-v2`, `q6voice`, existing `q6core`, `q6common`, `rtac`, `q6lsm`, `adsp_err`, existing `msm_audio_ion`, `avtimer`, `q6_init`. The VM alternative `Kbuild:133-149` is **not** applicable. Conditionally selected extras are at `Kbuild:152-169`.
- [TG `dsp/q6_init.c:10-29`](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio/dsp/q6_init.c#L10-L29) initializes **all** DSP services including q6core/cal/ION, already initialized by A2a. Linking/running it unchanged would duplicate init. **5.10 adaptation:** use a separately gated A3a real-service init chain with checked return values. Do NOT reinitialize A2a q6core/cal/ION.
- [TG `dsp/q6core.c:722-748`](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio/dsp/q6core.c#L722-L748) queries actual ADSP-reported service API versions through the working TG APR and returns negative errors when unavailable. Query and log `AFE=9`, `ASM=2`, `ADM=4`, with no synthetic response.
- TG `include/dsp/apr_audio-v2.h:11674-11747` defines framework-version response and service IDs: AFE 0x4, ASM 0x7, ADM 0x8, LSM 0xD. [Source](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio/include/dsp/apr_audio-v2.h#L11673-L11747).
- **CONFIRMED:** TG Q6 service entry points `q6afe.c:11906` (`afe_init`), `q6asm.c:11406` (`q6asm_init`), `q6adm.c:5517` (`adm_init`), `q6lsm.c:2955` (`q6lsm_init`). Register each with real return code. **SUSPECTED:** full `rtac`/`q6voice`/`avtimer` helper closure may need several Linux 5.10 adaptations and correct probe ordering. Do not substitute no-op symbols.
- **Acceptance:** real `P472 A3a Q6 <service> registered rc=0` lines produced only after successful init; real DSP version responses (AFE 9, ASM 2, ADM 4) recorded and checked. No ASoC card at this stage.

## A3b: LPASS/codec transport, **not** in A3a

Genuine LPASS audio clocks, LPI and WCD pinctrl, Bolero RX/TX/VA, SoundWire master/slave enumeration, WCD938x/MBHC from the live A52 DT. No WSA macro, WCD937x, WSA883x or FSA4480; real probe rc required. Separate Kconfig default n.

## A3c: 5.4-compatible Kona machine donor identified

- **CONFIRMED donor candidate:** Samsung SM7325 `turex/android_kernel_samsung_sm7325@c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4` uses Linux **5.4.191** in [`Makefile:2-4`](https://github.com/turex/android_kernel_samsung_sm7325/blob/c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4/Makefile#L2-L4).
- **CONFIRMED:** donor [`techpack/audio/asoc/kona.c:7518-7526`](https://github.com/turex/android_kernel_samsung_sm7325/blob/c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4/techpack/audio/asoc/kona.c#L7518-L7526) uses `struct snd_soc_dai_link_component`; [`kona.c:7980`](https://github.com/turex/android_kernel_samsung_sm7325/blob/c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4/techpack/audio/asoc/kona.c#L7980) uses `devm_snd_soc_register_card`. It contains `qcom,kona-asoc-snd` at `kona.c:7165`, Bolero (e.g. `kona.c:5483`), and WCD938x controls (`kona.c:3662-3695`). This is a strong **5.4 ASoC API donor**, not proof of A52 hardware/DAI identity.
- **CONFIRMED TG difference:** TG [`asoc/kona.c:8247-8311`](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio/asoc/kona.c#L8247-L8311) still uses old direct `cpu_dai_name/codec_name/platform_name` assignment. Use the donor's component-array API with TG's A52 DAI graph, Samsung extras and live-DT status. Do not copy the SM7325 links wholesale.
- **SUSPECTED:** donor's actual `kona.c` topology differs in FE/BE, platform naming, Samsung userspace controls and WSA paths. Confirm 33 A52 PCM devices before enabling a card. 5.4 API compatibility is **not automatically 5.10 build compatibility**.
- Never claim `lito-lagoonmtp-snd-card` or 33 PCMs unless a genuine ASoC machine registration and ALSA hardware enumeration proves both. Keep TAS256x out.

## Future A3a/A3b/A3c hardware gates

Every new stage: boot cmdline `nohlt=0 cpu_idle_force_poll=0`, A2a LINKED, Q6 Up, keyboard at 2 minutes, BT <=2 restarts/10 min, LTE/mobile data; no fake registrations, no SELinux permissive, no DMABUF_HEAPS, no unknown device writes. When a stage fails, restore the tested parent HLT image and keep later stages disabled.
