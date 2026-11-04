#!/bin/sh
# Removes the "Loading Linux..." / "Loading initial ramdisk..." lines GRUB prints.
cfg=/boot/grub/grub.cfg
[ -f "$cfg" ] && sed -i -e "/^[[:space:]]*echo[[:space:]]*'Loading /d" \
  -e "s/menuentry 'Wren Linux, with Linux linux'/menuentry 'Wren Linux'/" "$cfg"
exit 0
