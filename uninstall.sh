#!/bin/sh
# uninstall.sh: stops and removes gw2-touchbar, tiny-dfr gets the Touch Bar back. Keeps ~/.config/gw2-touchbar.
set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
systemctl disable --now gw2-touchbar.service 2>/dev/null || true
USER_NAME=${SUDO_USER:-}
[ -n "$USER_NAME" ] && systemctl --user -M "$USER_NAME@" stop gw2-touchbar-feed.service 2>/dev/null || true
systemctl --global disable gw2-touchbar-feed.service 2>/dev/null || true
rm -f /etc/systemd/system/gw2-touchbar.service /usr/local/bin/gw2-touchbarctl /etc/systemd/user/gw2-touchbar-feed.service
rm -f /etc/polkit-1/rules.d/50-gw2-touchbar.rules
rm -f /etc/systemd/system/*.target.wants/gw2-touchbar.service /etc/systemd/user/*.target.wants/gw2-touchbar-feed.service
rm -f /usr/local/bin/gw2-touchbar-settings /usr/share/applications/gw2-touchbar-settings.desktop
[ -n "$USER_NAME" ] && rm -f "$(getent passwd "$USER_NAME" | cut -d: -f6)/.config/autostart/gw2-touchbar-settings.desktop"
rm -rf /usr/local/lib/gw2-touchbar /var/lib/gw2-touchbar
systemctl daemon-reload
systemctl start tiny-dfr.service
echo "removed, tiny-dfr runs the Touch Bar again (your setup is left in ~/.config/gw2-touchbar)"
