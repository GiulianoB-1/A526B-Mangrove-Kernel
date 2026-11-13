# P477 A3b 5.4 API donor and live-r02 hardware authority

**TG hardware authority:** [A52XQ TouchGrass 4.19 @ 6bf351bd](https://github.com/micr0softstore/samsung_android_kernel_a52xq/tree/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/techpack/audio). **5.4 code candidate:** [Samsung SM7325 @ c4cb0a97](https://github.com/turex/android_kernel_samsung_sm7325/tree/c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4/techpack/audio), Linux 5.4.191 (Makefile:2-4). Both pinned at exact commits, not floating branch tips.

## CONFIRMED file-by-file source presence

| Part | TG 4.19 source (hardware family) | Donor 5.4 entry point, real probe |
|---|---|---|
| WCD/LPI pinctrl | `techpack/audio/soc/pinctrl-wcd.c`, `pinctrl-lpi.c` | `pinctrl-lpi.c:640`, `pinctrl-wcd.c:265` |
| Codec pinctrl | `techpack/audio/asoc/codecs/msm-cdc-pinctrl.c` | `msm-cdc-pinctrl.c:219` |
| LPASS ref-clock voters | `techpack/audio/asoc/codecs/audio-ext-clk-up.c` | `audio-ext-clk-up.c:517`, `qcom,audio-ref-clk` at :611 |
| Bolero base | `techpack/audio/asoc/codecs/bolero/bolero-cdc.c` | `bolero-cdc.c:1343`, actual Bolero platform probe |
| Bolero macro resources | `techpack/audio/asoc/codecs/bolero/rx-macro.c`, `tx-macro.c`, `va-macro.c` | `rx-macro.c:4254`, `tx-macro.c:3573`, `va-macro.c:3051` |
| SoundWire master | `techpack/audio/soc/swr-mstr-ctrl.c` | `swr-mstr-ctrl.c:2605`, real register-based slave-state reading :2342-2349, registration :2944-2981 |
| WCD938x and MBHC | `techpack/audio/asoc/codecs/wcd938x/` | `wcd938x.c:4313`, slave `wcd938x-slave.c:338` |

Donor links: [SWR master](https://github.com/turex/android_kernel_samsung_sm7325/blob/c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4/techpack/audio/soc/swr-mstr-ctrl.c#L2605), [WCD938x codec](https://github.com/turex/android_kernel_samsung_sm7325/blob/c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4/techpack/audio/asoc/codecs/wcd938x/wcd938x.c#L4313), [WCD938x slave](https://github.com/turex/android_kernel_samsung_sm7325/blob/c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4/techpack/audio/asoc/codecs/wcd938x/wcd938x-slave.c#L338), [Bolero](https://github.com/turex/android_kernel_samsung_sm7325/blob/c4cb0a9783fcfb8d17ddda02c0ad1678dcd0dac4/techpack/audio/asoc/codecs/bolero/bolero-cdc.c#L1343).

## A52 hardware authority, separate from donor

**LIVE-CONFIRMED (user-reported hardware):** r02 live DT agrees with TG A52XQ r02 for the battery nodes. For audio, user-supplied live DT inventory specifies Bolero, RX/TX/VA macro, SoundWire master/slave and WCD938x; WSA macro, WCD937x, WSA883x, FSA4480 disabled. Do not create or enable a disabled DT node just to satisfy a probe.

**CONFIRMED A52 DT compatible** from the supplied decoded DTS: `qcom,bolero-codec`, clock consumers `lpass_core_hw_vote` and `lpass_audio_hw_vote`, with `tx-macro@3220000` and `rx-macro@3200000`; real matching device binding is required. The 5.4 SM7325 donor provides API-converted driver families, **not** authority for Samsung A52 clocks, pins, port mapping or codec revision.

## 4.19 to 5.10 integration boundaries

- **CONFIRMED:** TG A52 4.19 `techpack/audio/soc/Kbuild` and `asoc/codecs/bolero/Kbuild` use `AUDIO_BLD_DIR:=.../msm-4.19`; SM7325 5.4 equivalents use `msm-5.4`. P477 stages only selected 5.4 source files and private headers in a new sandbox; it does not transplant the 5.4 system Kbuild or alter existing A3a TG APR/ION/Q6.
- **CONFIRMED:** A3b `.probe` wrappers call original donor callback and log its exact return value before returning it. `P472 A3b SWR ... slaves=<n> enumerated` reads SWR hardware slave-status bits, not DT-declared slave count.
- **SUSPECTED:** 5.4 ASoC and runtime-PM interfaces will compile unchanged on this specific GKI 5.10. The native build and hardware probe determine the verdict. Every compile failure must be fixed at its real source instead of supplying no-op functions.
- **SUSPECTED:** every A52 clock/pinctrl supplier is present and on before codec probe. `-EPROBE_DEFER` must be logged with true errno and is NOT acceptance.
- **Excluded by Kbuild:** machine driver/sound card, WSA macro, TAS256x, WCD937x, WSA883x, FSA4480 and voice audio.

## Charger and shadow source anchors

- TG [sm5714_charger.c:243-264](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/drivers/battery/charger/sm5714_charger/sm5714_charger.c#L243-L264): FCC conversion gives 500=0x20, 1000=0x40, 1500=0x60, 2100=0x86. H0 only register writer, masked-write/readback, high-code hard ceiling.
- TG [a52xq r02 DTS:489-492](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/arch/arm64/boot/dts/samsung/a52/a52xq/a52xq_eur_open_w00_r02.dts#L489-L492): charger temp 55C / recover 48C, ICL cap 1000 and FCC cap 1400.
- TG [r02 DTS:532-533](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/arch/arm64/boot/dts/samsung/a52/a52xq/a52xq_eur_open_w00_r02.dts#L532-L533): swelling 41/39C.
- TG [r02 DTS:690-774](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/arch/arm64/boot/dts/samsung/a52/a52xq/a52xq_eur_open_w00_r02.dts#L690-L774): real cable-info defaults and groups. TG [sec_battery_dt.c:176-190](https://github.com/micr0softstore/samsung_android_kernel_a52xq/blob/6bf351bdf18bdb228db79e66f14a7a9c0178e5d7/drivers/battery/common/sec_battery_dt.c#L176-L190): original `i <= len` overreads. Shadow copy corrects to `i < len` and rejects cable_number >= 41.
- **SHADOW only:** no new power_supply, no charger/FG/Type-C drivers or I2C clients, no register writes; the existing FG read-selector remains owned by the existing FG bridge. A full Samsung vote/age policy engine is not claimed in stage 1-2.
