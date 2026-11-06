#!/bin/bash
# Root side of Battery saver (run through pkexec; allowed without a password
# for the person signed in). Only these two fixed actions are possible.
set -u
cpu=/sys/devices/system/cpu
put() { [ -w "$2" ] && echo "$1" > "$2" 2>/dev/null; }
profile() {
  local p=/sys/firmware/acpi/platform_profile
  [ -r ${p}_choices ] && grep -qw "$1" ${p}_choices && put "$1" $p
}

case "${1:-}" in
  saver-on)
    touch /run/wren-battery-saver
    tlp power-saver >/dev/null 2>&1 || tlp bat >/dev/null 2>&1
    for f in $cpu/cpu[0-9]*/cpufreq/energy_performance_preference; do put power "$f"; done
    put 1 $cpu/intel_pstate/no_turbo
    put 0 $cpu/cpufreq/boost
    profile low-power || profile quiet
    for w in /sys/class/net/*/wireless; do
      dev=$(basename "$(dirname "$w")")
      iw dev "$dev" set power_save on >/dev/null 2>&1
    done
    ;;
  saver-off)
    rm -f /run/wren-battery-saver
    for f in $cpu/cpu[0-9]*/cpufreq/energy_performance_preference; do put balance_performance "$f"; done
    put 0 $cpu/intel_pstate/no_turbo
    put 1 $cpu/cpufreq/boost
    profile balanced
    tlp start >/dev/null 2>&1   # back to the normal settings for battery or charger
    ;;
  *) echo "usage: power-helper.sh saver-on|saver-off" >&2; exit 2 ;;
esac
exit 0
