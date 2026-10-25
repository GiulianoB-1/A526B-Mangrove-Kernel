#!/usr/bin/env bash
# A52 5G P461: READ-ONLY capture of the DTBO partition actually exposed
# through /dev/block/by-name on this boot, plus the live Linux FDT.
# Run with adb installed from Linux, WSL or Git Bash (NOT PowerShell 5 piping).
set -euo pipefail
OUT="${1:-a52-p461-dtbo-capture}"
mkdir -p "$OUT"
adb wait-for-device
{
  adb shell 'getprop ro.boot.slot_suffix; getprop ro.boot.dtbo_idx; getprop ro.boot.hardware.revision'
  adb shell su -c 'ls -l /dev/block/by-name/dtbo*'
  adb shell su -c 'readlink -f /dev/block/by-name/dtbo'
  adb shell su -c 'blockdev --getsize64 /dev/block/by-name/dtbo'
} >"$OUT/partition-identity.txt" 2>&1
adb shell 'cat /proc/cmdline' >"$OUT/proc-cmdline.txt"
adb shell 'getprop' >"$OUT/getprop.txt"
adb shell su -c 'dd if=/dev/block/by-name/dtbo bs=1048576 2>/dev/null' >"$OUT/flashed-dtbo.img"
if [ ! -s "$OUT/flashed-dtbo.img" ]; then
 echo 'ERROR: no DTBO bytes. Check su/root, slot suffix and by-name alias' >&2
 exit 1
fi
# This is the bootloader-applied, Linux-visible tree after overlay/fixups.
if ! adb exec-out su -c 'cat /sys/firmware/fdt' >"$OUT/live-fdt.dtb" 2>"$OUT/live-fdt-read-error.txt"; then
 rm -f "$OUT/live-fdt.dtb"
fi
adb shell su -c 'ls -R /proc/device-tree/reserved-memory 2>/dev/null' \
 >"$OUT/live-reserved-memory-list.txt" 2>&1 || :
adb shell su -c 'dmesg | grep -i -E "ramoops|pstore|reserved memory|overlap"' \
 >"$OUT/live-ramoops-dmesg.txt" 2>&1 || :
sha256sum "$OUT/flashed-dtbo.img" >"$OUT/partition-sha256.txt"
if [ -s "$OUT/live-fdt.dtb" ]; then sha256sum "$OUT/live-fdt.dtb" >>"$OUT/partition-sha256.txt"; fi
printf 'Captured READ-ONLY %s\n' "$OUT"
printf 'IMPORTANT: inspect partition-identity.txt for the actual slot/alias; this script does not flash.\n'
