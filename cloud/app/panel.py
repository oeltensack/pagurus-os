# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D.Koch – Pagurus OS
"""Wandtafeln: eigene Bedienseite fuer das Shelly Wall Display (Einstellungen -> Home Assistant -> URL) oder
jedes andere Tablet. Zugang ueber einen geheimen Schluessel in der Adresse, ohne Anmeldung – deshalb sieht und
bedient die Seite nur die Kacheln, die fuer diese Tafel ausgewaehlt sind."""
import json
import secrets
import time

from core import q, qid

CLIMATE_KEYS = ("on", "mode", "target_C", "fan", "swing_v", "swing_h", "eco", "turbo", "mute", "sleep", "display")


def init_db():
    q("""CREATE TABLE IF NOT EXISTS panels(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, token TEXT UNIQUE,
         tiles TEXT DEFAULT '[]', control INTEGER DEFAULT 1, created REAL)""")
    cols = [r["name"] for r in q("PRAGMA table_info(panels)")]
    if "bind" not in cols:                                     # an ein Geraet (Wall Display) oder eine IP gebunden
        q("ALTER TABLE panels ADD COLUMN bind TEXT")


def bind_ip(bind):
    """Bindung -> aktuelle IP: Geraete-ID (IP aus der Cloud, folgt DHCP-Wechseln) oder feste IP."""
    if not bind:
        return None
    r = q("SELECT ip FROM devices WHERE id=?", (bind,), one=True)
    return (r["ip"] if r else None) or (bind if bind.count(".") == 3 else None)


def all_panels():
    return [{"id": r["id"], "name": r["name"], "token": r["token"], "tiles": json.loads(r["tiles"] or "[]"),
             "control": bool(r["control"]), "bind": r["bind"] or "", "bind_ip": bind_ip(r["bind"])}
            for r in q("SELECT * FROM panels ORDER BY name")]


def by_ip(ip):
    """Tafel fuer diesen Absender (kurze Adresse ohne Schluessel)."""
    if not ip:
        return None
    for r in q("SELECT * FROM panels WHERE bind IS NOT NULL AND bind!=''"):
        if bind_ip(r["bind"]) == ip:
            return r
    return None


def by_token(tok):
    return q("SELECT * FROM panels WHERE token=?", (tok,), one=True) if tok else None


def save(d):
    tiles = []
    for t in d.get("tiles") or []:
        k, v = str(t).partition(":")[0], str(t).partition(":")[2]
        if k in ("dev", "scene") and v:
            tiles.append(f"{k}:{v}")
    name = str(d.get("name") or "Wandtafel").strip()[:40]
    ctl = 1 if d.get("control", True) else 0
    bind = str(d.get("bind") or "").strip()[:80] or None
    if d.get("id"):
        q("UPDATE panels SET name=?, tiles=?, control=?, bind=? WHERE id=?",
          (name, json.dumps(tiles), ctl, bind, int(d["id"])))
        return int(d["id"])
    return qid("INSERT INTO panels(name, token, tiles, control, created, bind) VALUES(?,?,?,?,?,?)",
               (name, secrets.token_urlsafe(18), json.dumps(tiles), ctl, time.time(), bind))


def new_token(pid):
    q("UPDATE panels SET token=? WHERE id=?", (secrets.token_urlsafe(18), pid))


def kind(d):
    c = d.get("comp") or ""
    s = d.get("status") or {}
    if c.startswith("cover:"):
        return "cover"
    if c.startswith("climate:"):
        return "climate"
    if c == "sensor:0":
        return "sensor"
    if c.startswith("pm1:") or s.get("meter_only"):
        return "meter"
    if "output" in s:
        return "light" if "brightness" in s else "switch"
    if "apower" in s:
        return "meter"
    return "info"


def _tile(d):
    s = d.get("status") or {}
    k = kind(d)
    t = {"id": "dev:" + d["id"], "k": k, "name": d.get("name") or d["id"], "room": d.get("room") or "",
         "online": bool(d.get("online")), "locked": bool(d.get("locked"))}
    m = d.get("meter") or {}
    if "apower" in s:
        t["w"] = s.get("apower")
    elif m.get("online") and m.get("apower") is not None:
        t["w"] = m.get("apower")
    if k in ("switch", "light"):
        t["on"] = bool(s.get("output"))
        if "brightness" in s:
            t["bri"] = s.get("brightness")
    elif k == "cover":
        t.update(state=s.get("state"), pos=s.get("current_pos"), posc=bool(s.get("pos_control")))
    elif k == "climate":
        room = s.get("ext_temperature_C", s.get("current_C"))
        import roomctl
        rc = roomctl.view(d["id"])
        tgt = s.get("target_C")
        if rc and rc["wish"] is not None:                 # Raumregelung: Wunsch und Raumfuehler zeigen
            tgt = rc["wish"]
            room = rc["room"] if rc["room"] is not None else room
        t.update(on=bool(s.get("output")), link=s.get("link") is not False, mode=s.get("mode"),
                 target=tgt, fan=s.get("fan"), room_C=room, hum=s.get("ext_humidity"),
                 outdoor=s.get("outdoor_C"), modes=s.get("modes") or ["cool", "heat", "dry", "fan", "auto"],
                 fans=s.get("fans") or ["auto", "low", "low_mid", "mid", "mid_high", "high"], step=s.get("step_C") or 1,
                 min=s.get("min_C") or 16, max=s.get("max_C") or 31,
                 paused=(d.get("winopen") or {}).get("reason") if (d.get("winopen") or {}).get("paused") else None)
    elif k == "sensor":
        tc = s.get("temperature")
        hu = s.get("humidity")
        t.update(tC=tc.get("tC") if isinstance(tc, dict) else None, rh=hu.get("rh") if isinstance(hu, dict) else None,
                 lux=s.get("lux"), contact=s.get("contact"), motion=s.get("motion"), bat=s.get("battery"))
    return t


def state(p, devices):
    """Kacheln einer Tafel mit aktuellem Zustand. devices = Liste aus /api/devices (dev_row)."""
    by = {d["id"]: d for d in devices}
    for d in devices:                          # Kanaele aus zusammengefassten Karten auch einzeln erreichbar
        for c in d.get("channels") or []:
            by[c["id"]] = c
    scenes = {r["id"]: r["name"] for r in q("SELECT id, name FROM scenes")}
    tiles, sc = [], []
    for t in json.loads(p["tiles"] or "[]"):
        k, _, v = t.partition(":")
        if k == "dev" and v in by:
            tiles.append(_tile(by[v]))
        elif k == "scene" and v.isdigit() and int(v) in scenes:
            sc.append({"id": t, "name": scenes[int(v)]})
    return {"name": p["name"], "control": bool(p["control"]), "tiles": tiles, "scenes": sc,
            "outdoor": _outdoor(), "ts": time.time()}


def _outdoor():
    try:
        import shade
        wx = shade.WX
        return wx.get("temp") if wx.get("ok") else None
    except Exception:
        return None


def allowed(p, tile_id):
    return tile_id in json.loads(p["tiles"] or "[]")
