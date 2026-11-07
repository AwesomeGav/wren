#!/bin/sh
# Removes the "Loading Linux..." / "Loading initial ramdisk..." lines GRUB prints,
# and names the boot entries simply "Floe".
cfg=/boot/grub/grub.cfg
[ -f "$cfg" ] && sed -i -e "/^[[:space:]]*echo[[:space:]]*'Loading /d" \
  -e "s/menuentry '\(Floe\|Wren\)\( Linux\)\?, with Linux linux'/menuentry 'Floe'/" \
  -e "s/menuentry '\(Floe\|Wren\)\( Linux\)\?'/menuentry 'Floe'/" \
  -e "s/submenu 'Advanced options for \(Floe\|Wren\)\( Linux\)\?'/submenu 'Floe: more options'/" "$cfg"
exit 0
