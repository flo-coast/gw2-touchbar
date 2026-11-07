#!/bin/sh
# install.sh: copies gw2-touchbar and the macarchy-touchbar engine to /usr/local/lib/gw2-touchbar (root
# owned, because the service runs as root) and sets up the services. Nothing is enabled: the bar only runs
# while you switch it on in the settings app.
# Run with sudo from this folder. MACARCHY=<checkout> if macarchy-touchbar isn't in ~/src.
set -eu
[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
USER_NAME=${SUDO_USER:-$(stat -c %U "$SRC")}
MACARCHY=${MACARCHY:-$(getent passwd "$USER_NAME" | cut -d: -f6)/src/macarchy-touchbar}
DEST=/usr/local/lib/gw2-touchbar
[ -d "$MACARCHY/macarchy_touchbar" ] || { echo "no macarchy-touchbar at $MACARCHY, get it with: git clone -b gw2-local https://github.com/flo-coast/macarchy-touchbar $MACARCHY" >&2; exit 1; }

rm -rf "$DEST"
install -d "$DEST/engine" "$DEST/modules"
cp -r "$SRC/gw2tb" "$SRC/data" "$DEST/"
cp "$SRC/gw2-touchbar" "$SRC/gw2-touchbar-feed" "$SRC/gw2-touchbar-settings" "$SRC/hwtest" "$SRC/tbfix" "$DEST/"
install -d "$DEST/tests"
cp "$SRC/tests/fake-wvw.json" "$SRC/tests/hwtest.toml" "$DEST/tests/"
cp -r "$SRC/modules/gw2" "$DEST/modules/"
cp -rL "$MACARCHY/modules/core" "$DEST/modules/"
cp -rL "$MACARCHY/macarchy_touchbar" "$DEST/engine/"
find "$DEST" -name __pycache__ -prune -exec rm -rf {} +
chown -R root:root "$DEST"
chmod -R go-w "$DEST"
cp "$MACARCHY/bin/macarchy-touchbar" "$DEST/engine/cli"
# gw2-touchbarctl status|reload|screenshot <png>|touch x,y|group keys|gw2 state (talks to the service)
printf '#!/bin/sh\nexec env XDG_RUNTIME_DIR=/run/gw2-touchbar MACARCHY_TOUCHBAR_DATA=%s/engine python3 %s/engine/cli "$@"\n' \
    "$DEST" "$DEST" > /usr/local/bin/gw2-touchbarctl
chmod 755 /usr/local/bin/gw2-touchbarctl

# the settings app (writes ~/.config/gw2-touchbar/config.toml, the bar reloads it by itself)
ln -sf "$DEST/gw2-touchbar-settings" /usr/local/bin/gw2-touchbar-settings
cp "$SRC/gw2-touchbar-settings.desktop" /usr/share/applications/
# map/spec names letterbox already looked up, if it is installed (saves a few API calls)
install -d /var/lib/gw2-touchbar
[ -f /var/lib/gw2-touchbar/names.json ] || cp /var/lib/letterbox/gw2-names.json /var/lib/gw2-touchbar/names.json 2>/dev/null || true

sed "s|@USER@|$USER_NAME|" "$SRC/gw2-touchbar.service" > /etc/systemd/system/gw2-touchbar.service
# the settings app may start and stop exactly this service, without a password
sed "s|@USER@|$USER_NAME|" "$SRC/50-gw2-touchbar.rules" > /etc/polkit-1/rules.d/50-gw2-touchbar.rules
chmod 644 /etc/polkit-1/rules.d/50-gw2-touchbar.rules
# the data feed runs as the user (network, session bus), also only while the app has the bar switched on
cp "$SRC/gw2-touchbar-feed.service" /etc/systemd/user/
# older installs started both by themselves, take those links away
rm -f /etc/systemd/system/*.target.wants/gw2-touchbar.service /etc/systemd/user/*.target.wants/gw2-touchbar-feed.service
systemctl daemon-reload
systemctl --user -M "$USER_NAME@" daemon-reload 2>/dev/null || true
# if the bar is on right now, it gets the new code
systemctl try-restart gw2-touchbar.service
systemctl --user -M "$USER_NAME@" try-restart gw2-touchbar-feed.service 2>/dev/null || true
echo "installed. Open \"GW2 Touch Bar\" and switch the bar on there. Logs: journalctl -u gw2-touchbar -f"
