# events.py: GW2 timed events (world bosses, map metas) from the wiki's event timer data.
# data/gw2-events.json is the wiki's "Widget:Event timer" data as published by
# github.com/giovazz89/gw2-api-event-timers (events.json); refresh with: python3 -m gw2tb.events --update
# Each section's "sequences" start at 00:00 UTC: first the "partial" entries, then "pattern" repeated;
# r = segment id (0 = nothing), d = minutes.
import json, os, sys, urllib.request
from datetime import datetime, timedelta, timezone

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gw2-events.json")
SOURCE = "https://raw.githubusercontent.com/giovazz89/gw2-api-event-timers/HEAD/events.json"


def load(names=None):
    try:
        secs = json.load(open(DATA))
    except (OSError, ValueError):
        return []
    return [s for s in secs if not names or s["name"] in names]


def timeline(section, day):
    """[(start, end, segment)] for one UTC day (datetime at 00:00 UTC), gaps left out."""
    seq = section.get("sequences", {})
    segs = {s["id"]: s for s in section.get("segments", [])}
    entries, pattern = list(seq.get("partial", [])), seq.get("pattern", [])
    out, t, i = [], day, 0
    while t < day + timedelta(days=1):
        if i < len(entries):
            e = entries[i]
        elif pattern:
            e = pattern[(i - len(entries)) % len(pattern)]
        else:
            break
        i += 1
        nxt = t + timedelta(minutes=e["d"])
        if e["r"] and e["r"] in segs:
            out.append((t, nxt, segs[e["r"]]))
        t = nxt
    return out


def upcoming(sections, now, horizon_min=180):
    """[(start, end, section name, segment)] still to come or running, sorted by start."""
    out = []
    day = (now - timedelta(hours=3)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now + timedelta(minutes=horizon_min)
    while day < end:
        for s in sections:
            out += [(a, b, s["name"], seg) for a, b, seg in timeline(s, day) if b > now and a < end]
        day += timedelta(days=1)
    return sorted(out, key=lambda x: x[0])


if __name__ == "__main__":
    if "--update" in sys.argv:
        with urllib.request.urlopen(SOURCE, timeout=20) as r:
            data = r.read()
        json.loads(data)
        with open(DATA, "wb") as fh:
            fh.write(data)
        print("updated", DATA)
    else:
        now = datetime.now(timezone.utc)
        for a, b, name, seg in upcoming(load(sys.argv[1:] or ["World bosses"]), now, 120)[:12]:
            print(f"{a.astimezone():%H:%M}-{b.astimezone():%H:%M}  {name}: {seg['name']}")
