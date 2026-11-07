#!/usr/bin/env python3
"""Config tests: normalize() must turn anything into a safe, complete config, save/load must round-trip.
python3 tests/test_config.py (no pytest needed)."""
import os
import stat
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
from gw2tb import config  # noqa: E402

GARBAGE = [
    {}, {"settings": 5}, {"settings": []}, {"settings": {"tp_watch": "x"}},
    {"settings": {"tp_watch": [{"id": "19721", "target": "abc"}, {"id": 1.5}, "x", {"id": "-3"}]}},
    {"settings": {"brightness": "9", "swipe": 1, "graph_seconds": True, "api_key": 7}},
    {"keys": 5}, {"keys": "abc"}, {"keys": [{"keys": "B"}, {"keys": [], "label": 1}, {"keys": [1, 2]}]},
    {"pages": 5}, {"pages": "abc"}, {"pages": [5, "x", {"panels": 5}, {"panels": "abc"}, {"name": [1]}]},
    {"pages": [{"panels": [{"type": ["fps"]}, {"type": {"a": 1}}, {"type": "fps", "width": "wide"},
                           {"type": "fps", "width": 99999, "size": -4, "color": "red", "style": 3},
                           {"type": "fps", "run": "rm -rf ~", "command": "x"}]}]},
    {"pages": [{"panels": [{"type": "sensors", "items": ["gtemp", "rm -rf", 5, "cpu", "cpu"] + ["fps"] * 9},
                           {"type": "sensors", "items": "gtemp"}, {"type": "battery", "device": ["x"]},
                           {"type": "battery", "device": "A" * 500, "device_name": None}]}]},
]


def check(cfg):
    assert set(cfg) == {"settings", "keys", "pages"}
    assert set(cfg["settings"]) == set(config.DEFAULT["settings"])
    for k, v in config.DEFAULT["settings"].items():
        assert type(cfg["settings"][k]) is type(v), (k, cfg["settings"][k])
    for w in cfg["settings"]["tp_watch"]:
        assert set(w) == {"id", "target"} and all(type(x) is int for x in w.values()), w
    for k in cfg["keys"]:
        assert set(k) == {"label", "keys"} and k["keys"] and all(isinstance(x, str) for x in k["keys"])
    assert cfg["pages"]
    for pg in cfg["pages"]:
        assert set(pg) == {"name", "panels"} and isinstance(pg["name"], str)
        for p in pg["panels"]:
            extra = {"sensors": {"items"}, "battery": {"device", "device_name"}}.get(p["type"], set())
            assert set(p) == {"type", "width", "color", "size", "style", "sub"} | extra, p
            if p["type"] == "sensors":
                assert len(p["items"]) <= config.MAX_ITEMS and all(i in config.NUMS for i in p["items"]), p
            if p["type"] == "battery":
                assert isinstance(p["device"], str) and isinstance(p["device_name"], str), p
            assert p["type"] in config.CATALOG and 0 <= p["width"] <= config.BAR_WIDTH
    return cfg


def test_garbage():
    for g in GARBAGE:
        try:
            check(config.normalize(g))
        except Exception as e:
            raise AssertionError(f"normalize({g!r}) -> {e!r}") from e


def test_no_commands():
    cfg = config.normalize(GARBAGE[-1])
    assert "rm -rf" not in config.dumps(cfg) and "run" not in str(cfg["pages"])


def test_tp_watch():
    cfg = config.normalize({"settings": {"tp_watch": [{"id": "19721", "target": "abc"}, {"id": 24, "target": 300}]}})
    assert cfg["settings"]["tp_watch"] == [{"id": 19721, "target": 0}, {"id": 24, "target": 300}]


def test_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "sub", "config.toml")
        cfg = config.normalize({})
        cfg["settings"]["api_key"] = 'k"ey\\'
        cfg["settings"]["tp_watch"] = [{"id": 19721, "target": 250}]
        cfg["pages"][0]["name"] = 'Quote " and \\ back'
        config.save(cfg, f)
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
        assert config.load(f) == cfg


def test_broken_file():
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "config.toml")
        with open(f, "w") as fh:
            fh.write("this is [not toml")
        assert config.load(f) == config.normalize({})
        assert config.load(os.path.join(d, "missing.toml")) == config.normalize({})


def test_engine_data():
    cfg = config.normalize({})
    for i in range(len(cfg["pages"])):
        data = config.engine_data(cfg, i)
        assert data, i


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:
                failed += 1
                print(f"FAIL  {name}: {e}")
    sys.exit(1 if failed else 0)
