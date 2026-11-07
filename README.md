# gw2-touchbar

The MacBook Touch Bar shows Guild Wars 2 while the game runs and goes back to tiny-dfr's F-keys when it closes.

Nothing starts by itself. You open "GW2 Touch Bar" and flip the switch at the top. From then on the bar takes over whenever GW2 runs, or right away if it already does. Close the app and the F-keys are back. If you want it ready after every login, there are two switches for that in the settings, both off unless you turn them on.

The bar has pages. Swipe left or right to switch, the dots on the right show where you are. Out of the box there are five

- Game with your class icon, map, facing and mount, the combat timer, the next world boss, the Keys group, GPU temperature and the clock
- Performance with FPS, ping, the GW2 main thread, GPU busy and temperature, CPU clock and a guess at what holds the game back
- Events with a timeline of the world bosses of the next two hours, a run timer and your playtime
- Account and Everyday with the panels below that need a key or a town, they tell you on the bar what's missing

What you can put on a page

- performance numbers like FPS with the 1 % low, ping, CPU and GPU clock, temperature and power, VRAM, fans, memory and network. Each one as a number, a graph of the last 30 s to 5 min, or both
- the GW2 main thread, the usual culprit when the CPU looks idle but FPS drop
- a sensors tile where you pick up to six of those values to sit side by side, like GPU temp, CPU clock and the main thread
- character and map, combat timer (tap resets the session total), next world boss (tap copies its waypoint, a long press lists the next five), the event timeline, a run timer (tap to start and stop), playtime and your squad if you use the letterbox bridge in Nexus
- with a GW2 API key your WvW matchup (victory points, skirmish, points per tick), session earnings in gold and currencies, the Wizard's Vault and a Trading Post watchlist with item icons, trends and a target price. The gem exchange works without a key
- now playing from any player (tap to pause), the latest desktop notification, the batteries of your Bluetooth devices and other gear, all in one tile or each in its own, the weather in your town and live scores from ESPN
- the Keys group with game keys of your choice, a clock and empty space

Discord notifications slide over the bar for 6 seconds, but never while you're in combat. Which ones is up to you in the settings.

## Settings

Open "GW2 Touch Bar" from the app menu or run `gw2-touchbar-settings`. You get a preview of the real bar, live while GW2 runs and with sample data otherwise. Add pages, add panels, move them around and give each one its own width, colour, font size and style. Click a panel in the preview to pick it. The API key, the watchlist, your town, the league and the notification filter go in the tab "Account and online". Everything is saved to `~/.config/gw2-touchbar/config.toml` (only readable by you) right away and the bar takes it over within two seconds, even in the middle of a game.

## How it fits together

Two small services, started and stopped by the app. Neither one is enabled, and both quit by themselves a few seconds after the app is gone, even if it crashed. `gw2-touchbar-feed` runs as you and collects the data once a second while GW2 runs. That's MumbleLink, sysfs, MangoHud logs, the game's connection, the GW2 API and the other online sources, MPRIS, UPower and the notifications. Online data is only fetched for panels that are on one of your pages. `gw2-touchbar` runs as root because the Touch Bar's display, its touch input and tiny-dfr need it. It only draws what the feed collected and sends taps back. Network access and your desktop session never run as root that way, and nothing from the config file can run commands.

It doesn't need letterbox. The boss timers ship in `data/gw2-events.json` (the wiki's event timer data via giovazz89/gw2-api-event-timers) and the class icons are in `data/icons`. The drawing, touch handling and key sending are the [macarchy-touchbar](https://github.com/macarchy/macarchy-touchbar) engine (MIT), which install.sh copies in from `~/src/macarchy-touchbar`.

## Install and remove

The bar runs on a fork of the macarchy-touchbar engine with a few fixes for the T2's Touch Bar. install.sh expects it in `~/src/macarchy-touchbar`.

```
git clone -b gw2-local https://github.com/flo-coast/macarchy-touchbar ~/src/macarchy-touchbar
git clone https://github.com/flo-coast/gw2-touchbar && cd gw2-touchbar
sudo ./install.sh
```

`sudo ./uninstall.sh` takes it all away again and leaves your settings in `~/.config/gw2-touchbar`.

install.sh puts everything in `/usr/local/lib/gw2-touchbar`, sets up `gw2-touchbar.service` and the user service `gw2-touchbar-feed.service` without enabling them, and adds the settings app. A small polkit rule lets the app start and stop the bar service without a password. It allows nothing else, just that one service for your user. If the bar ever stays dark, `sudo /usr/local/lib/gw2-touchbar/tbfix` brings tiny-dfr back.

## Testing

`tests/smoke` runs everything without the Touch Bar or GW2. The config tests, the feed with fake game data, the bar headless with a screenshot and a tap on every page, and the settings app photographing each tab. The shots land in `tests/shots`. Your real config and playtime stay untouched. The settings part is skipped while the screen is locked, because KWin draws no windows then.

By hand it goes like this

```
GW2TB_FAKE=tests/fake-wvw.json ./gw2-touchbar-feed &      # fake game data
./gw2-touchbar --headless &
macarchy-touchbar screenshot bar.png      # ~/src/macarchy-touchbar/bin/macarchy-touchbar
macarchy-touchbar next                    # next page
```

`sudo /usr/local/lib/gw2-touchbar/hwtest 120` drives the real bar for two minutes with a stream of taps and reports whether the display kept up.

## Good to know

The T2's Touch Bar display driver freezes when it gets partial screen updates in quick succession. The bar therefore always sends whole frames, at most ten per second.

It's made for and tested on a 16" MacBook Pro 2019 with Arch Linux, KDE Plasma and GW2 under Proton. Other T2 MacBooks with a Touch Bar should work too, but nobody tried yet.

## Credits and license

Engine by [macarchy-touchbar](https://github.com/macarchy/macarchy-touchbar) (MIT). Event timer data from the GW2 wiki via [giovazz89/gw2-api-event-timers](https://github.com/giovazz89/gw2-api-event-timers). Class icons © ArenaNet.

Not affiliated with ArenaNet or NCSOFT. Guild Wars 2 is a trademark of ArenaNet, LLC.

GPL-3.0-or-later, see [LICENSE](LICENSE).

Written by **flo-coast** (2026), with Claude (Anthropic) as a coding assistant.
