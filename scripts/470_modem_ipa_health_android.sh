#!/system/bin/sh
# P470: read-only on-device snapshot / five-minute modem health check.
# Usage (root Android shell): sh 470_modem_ipa_health_android.sh [--watch]
# Never reads IMEI, EFS, NV or modem partitions. No writes.
set -u

snapshot() {
    echo "P470 SNAPSHOT timestamp=$(date '+%Y-%m-%dT%H:%M:%S%z')"
    for p in /sys/class/remoteproc/remoteproc*; do
        [ -d "$p" ] || continue
        n=$(cat "$p/name" 2>/dev/null || echo unknown)
        case "$n" in
            *mss*|*modem*|*MPSS*|*MSS*)
                state=$(cat "$p/state" 2>/dev/null || echo unknown)
                echo "P470 MODEM remoteproc=$p name=$n state=$state"
                ;;
        esac
    done
    for n in /dev/ipa /dev/wwan_ioctl /dev/subsys_modem; do
        if [ -e "$n" ]; then ls -l "$n"; else echo "P470 NODE MISSING $n"; fi
    done
    if command -v ip >/dev/null 2>&1; then
        ip link show rmnet_ipa0 2>&1 | sed -n '1,4p'
    else
        echo "P470 TOOL ip absent"
    fi
    if command -v getprop >/dev/null 2>&1; then
        for key in init.svc.vendor.ipacm init.svc.vendor.ipacm-diag; do
            echo "P470 SERVICE $key=$(getprop "$key")"
        done
    fi
    # Count only specific faults, never dump unfiltered radio logs or IDs.
    if command -v logcat >/dev/null 2>&1; then
        count=$(logcat -d -b radio -t 6000 2>/dev/null | grep -E -c 'GetEpPair: Failed|Error getting the EP_PAIR' || true)
        echo "P470 RILD_EP_PAIR_FAILURES radio_log_count=$count"
    fi
    if command -v dmesg >/dev/null 2>&1; then
        count=$(dmesg 2>/dev/null | grep -E -c 'ps_rm:0xb9|P469B MSS STOP_FAILED' || true)
        echo "P470 MSS_FATAL_MARKERS current_kmsg=$count"
        dmesg 2>/dev/null | grep -E 'P470 (IPA|GSI|MSS)|P469B MSS STOP_OFFLINE|P469B MSS STOP_FAILED' | tail -n 20
    fi
}

mode=$(echo "$@" | cut -d " " -f1)
if [ -z "$mode" ]; then mode="--snapshot"; fi
if [ "$mode" = "--watch" ]; then
    i=0
    while [ "$i" -le 30 ]; do
        echo "P470 WATCH sample=$i/30"
        snapshot
        i=$((i + 1))
        if [ "$i" -lt 30 ]; then sleep 10; fi
    done
    echo "P470 WATCH DONE samples=31 interval_s=10 duration_s=300"
elif [ "$mode" = "--snapshot" ]; then
    snapshot
else
    echo "usage: sh $0 [--snapshot|--watch]" >&2
    exit 2
fi
