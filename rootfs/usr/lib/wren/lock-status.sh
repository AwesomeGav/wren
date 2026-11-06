#!/bin/sh
# Wi-Fi and battery text for the lock screen (Nerd Font icons).
out=""
if nmcli -t -f TYPE,STATE device 2>/dev/null | grep -q '^wifi:connected'; then out="󰖩"; fi
for b in /sys/class/power_supply/BAT*; do
  [ -r "$b/capacity" ] || continue
  cap=$(cat "$b/capacity"); st=$(cat "$b/status")
  if [ "$st" = Charging ]; then icon="󰂄"; else icon="󰁹"; fi
  out="$out   $icon $cap%"
  break
done
echo "$out"
