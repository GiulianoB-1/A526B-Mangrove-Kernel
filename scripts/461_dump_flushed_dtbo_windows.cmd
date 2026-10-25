@echo off
setlocal EnableExtensions
REM P461 read-only extraction: executes on Windows CMD, not PowerShell.
REM It captures the *flashed partition bytes*, not a source-tree DTBO.
where adb >nul 2>&1
if errorlevel 1 (echo ERROR: adb missing from PATH& exit /b 1)
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set STAMP=%%I
set "OUT=P461_DTBO_%STAMP%"
mkdir "%OUT%" || exit /b 1
adb wait-for-device
adb shell su -c "id; getprop ro.boot.slot_suffix; getprop ro.boot.hardware; ls -l /dev/block/by-name/dtbo; readlink -f /dev/block/by-name/dtbo; cat /proc/cmdline" > "%OUT%\partition-identity.txt" 2>&1
adb shell su -c "sha256sum /dev/block/by-name/dtbo" > "%OUT%\device-dtbo-sha256.txt" 2>&1
REM adb exec-out preserves binary data. Do NOT use adb shell with a PTY.
adb exec-out su -c "cat /dev/block/by-name/dtbo" > "%OUT%\flashed-dtbo.img"
if errorlevel 1 (echo ERROR: unable to read DTBO partition& exit /b 1)
for %%F in ("%OUT%\flashed-dtbo.img") do if %%~zF LSS 4096 (echo ERROR: DTBO dump too small& exit /b 1)
adb exec-out su -c "cat /sys/firmware/fdt" > "%OUT%\live.dtb"
if errorlevel 1 (echo WARN: /sys/firmware/fdt unavailable; collector v1.20 live-tree dump still useful)
adb shell su -c "find /proc/device-tree/reserved-memory -maxdepth 2 -iname '*ramoops*'; ls -la /sys/fs/pstore; dmesg | grep -iE 'ramoops|pstore|OF: reserved mem'" > "%OUT%\live-ramoops.txt" 2>&1
certutil -hashfile "%OUT%\flashed-dtbo.img" SHA256 > "%OUT%\host-dtbo-sha256.txt" 2>&1
echo Read-only DTBO capture complete in %OUT%
echo The DTBO SHA256 must agree between host-dtbo-sha256.txt and device-dtbo-sha256.txt
echo Include flashed-dtbo.img, live.dtb, identity, and hashes for provenance audit.
endlocal
