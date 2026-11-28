# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D.Koch – Pagurus OS
"""Klimaanlagen: minuetlicher Verlauf (Raum-/Soll-/Ausblastemperatur, Betrieb, Kompressor) und Auswertung
fuer den eigenen Bereich in der Cloud. Strom und Kosten kommen vom gekoppelten Energiemesser."""
import json
import threading
import time
from datetime import timedelta

from core import KEEP_POWER_DAYS, alert, dev_name, now_local, price_eur_kwh, q, qid

BUS = None
FANS = ("auto", "low", "low_mid", "mid", "mid_high", "high")

MODES = ("heat", "cool", "dry", "fan", "auto")


def init_db():
    q("""CREATE TABLE IF NOT EXISTS climate_log(dev TEXT, ts INTEGER, on_ INTEGER, mode TEXT, target REAL,
         room REAL, unit REAL, outlet REAL, hum REAL, comp INTEGER, PRIMARY KEY(dev, ts))""")
    q("""CREATE TABLE IF NOT EXISTS climate_sched(id INTEGER PRIMARY KEY AUTOINCREMENT, dev TEXT, enabled INTEGER DEFAULT 1,
         days INTEGER DEFAULT 127, time TEXT, action TEXT, last_run TEXT)""")


# ======================= Zeitplaene =======================
def sched_clean(d):
    """Eingabe pruefen: Tage, Zeit (HH:MM oder sunrise/sunset±min), Aktion {on, mode, target_C, fan}."""
    import engine
    t = str(d.get("time") or "").strip()
    try:
        engine.sched_time(t, now_local().date())
    except Exception:
        raise ValueError("Zeit als HH:MM oder Sonnenauf-/-untergang ± Minuten")
    days = int(d.get("days", 127)) & 127
    if not days:
        raise ValueError("Mindestens einen Tag wählen")
    a = d.get("action") or {}
    act = {"on": bool(a.get("on"))}
    if act["on"]:
        if a.get("mode") in MODES:
            act["mode"] = a["mode"]
        if a.get("target_C") not in (None, ""):
            act["target_C"] = max(16, min(31, round(float(a["target_C"]) * 2) / 2))   # halbe Grad (Midea)
        if a.get("fan") in FANS:
            act["fan"] = a["fan"]
    return {"days": days, "time": t, "action": act, "enabled": 1 if d.get("enabled", True) else 0}


def sched_save(dev, d):
    c = sched_clean(d)
    vals = (c["enabled"], c["days"], c["time"], json.dumps(c["action"]))
    if d.get("id"):
        q("UPDATE climate_sched SET enabled=?, days=?, time=?, action=?, last_run=NULL WHERE id=? AND dev=?",
          vals + (int(d["id"]), dev))
        return int(d["id"])
    return qid("INSERT INTO climate_sched(enabled, days, time, action, dev) VALUES(?,?,?,?,?)", vals + (dev,))


def sched_list(dev):
    import engine
    out = []
    for r in q("SELECT * FROM climate_sched WHERE dev=?", (dev,)):
        try:
            t = engine.sched_time(r["time"], now_local().date())
            today = t.strftime("%H:%M") if t else None
        except Exception:
            today = None
        out.append({"id": r["id"], "enabled": bool(r["enabled"]), "days": r["days"], "time": r["time"],
                    "today": today, "action": json.loads(r["action"] or "{}")})
    out.sort(key=lambda x: (x["today"] or x["time"]))
    return out


def _apply(dev, act):
    """Zeitplan ausfuehren. Steht die Anlage wegen offenem Fenster in Pause, wird nur der Wunsch fuer danach
    gemerkt (Einschalten) bzw. die Pause beendet (Ausschalten)."""
    w = q("SELECT paused, saved FROM winopen WHERE dev=?", (dev,), one=True)
    if w and w["paused"]:
        if act["on"]:
            saved = json.loads(w["saved"] or "{}")
            saved.update({k: v for k, v in act.items() if k != "on"})
            q("UPDATE winopen SET saved=? WHERE dev=?", (json.dumps(saved), dev))
        else:
            q("UPDATE winopen SET paused=NULL, until=NULL, saved=NULL, reason=NULL WHERE dev=?", (dev,))
        return
    import roomctl
    BUS.rpc(dev, "Climate.Set", roomctl.filter_set(dev, {"id": 0, **act}))


def run_schedules():
    import engine
    now = now_local()
    key = now.strftime("%Y-%m-%d")
    for s in q("SELECT * FROM climate_sched WHERE enabled=1"):
        if not (s["days"] >> now.weekday()) & 1 or s["last_run"] == key:
            continue
        try:
            t = engine.sched_time(s["time"], now.date())
        except Exception:
            continue
        if t is None or not (t <= now < t + timedelta(minutes=10)):
            continue
        q("UPDATE climate_sched SET last_run=? WHERE id=?", (key, s["id"]))
        try:
            _apply(s["dev"], json.loads(s["action"] or "{}"))
        except Exception as e:
            alert(s["dev"], "rule", f"Klima-Zeitplan {dev_name(s['dev'])} {s['time']}: {e}")


def _f(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def record():
    import roomctl
    ts = int(time.time()) // 60 * 60
    for r in q("SELECT id, status FROM devices WHERE comp LIKE 'climate:%' AND online=1"):
        st = json.loads(r["status"] or "{}")
        if st.get("link") is False or "mode" not in st:
            continue
        q("""INSERT OR REPLACE INTO climate_log(dev, ts, on_, mode, target, room, unit, outlet, hum, comp)
             VALUES(?,?,?,?,?,?,?,?,?,?)""",
          (r["id"], ts, 1 if st.get("output") else 0, st.get("mode"),
           _f(roomctl.wish(r["id"])) if roomctl.wish(r["id"]) is not None else _f(st.get("target_C")),
           _f(st.get("ext_temperature_C")) if _f(st.get("ext_temperature_C")) is not None else _f(st.get("current_C")),
           _f(st.get("current_C")), _f(st.get("outlet_C")),
           _f(st.get("ext_humidity")), 1 if st.get("compressor") else 0))


def _day_start(days_back=0):
    d = now_local().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_back)
    return int(d.timestamp())


def _hours(dev, t0, t1=None):
    t1 = t1 or int(time.time()) + 60
    r = q("""SELECT SUM(on_) AS on_m, SUM(comp) AS comp_m,
                    SUM(CASE WHEN on_=1 AND mode='heat' THEN 1 ELSE 0 END) AS heat_m,
                    SUM(CASE WHEN on_=1 AND mode='cool' THEN 1 ELSE 0 END) AS cool_m
             FROM climate_log WHERE dev=? AND ts>=? AND ts<?""", (dev, t0, t1), one=True)
    return {k: round((r[k] or 0) / 60, 2) for k in ("on_m", "comp_m", "heat_m", "cool_m")}


def _energy(meter, days):
    if not meter:
        return None
    since = (now_local() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    r = q("SELECT SUM(wh) AS wh FROM energy WHERE dev=? AND day>=?", (meter, since), one=True)
    wh = r["wh"] or 0.0
    return {"wh": round(wh, 1), "cost": round(wh / 1000 * price_eur_kwh(), 2)}


def series(dev, meter, hours=24):
    """Verlauf in 5-Minuten-Schritten: [ts, raum, soll, ausblas, an, kompressor, modus, watt]."""
    t0 = int(time.time()) - hours * 3600
    rows = q("""SELECT ts/300*300 AS b, AVG(room) AS room, AVG(target) AS target, AVG(outlet) AS outlet,
                       MAX(on_) AS on_, MAX(comp) AS comp, MAX(mode) AS mode
                FROM climate_log WHERE dev=? AND ts>=? GROUP BY b ORDER BY b""", (dev, t0))
    pw = {}
    if meter:
        for p in q("SELECT ts/300*300 AS b, AVG(w) AS w FROM power WHERE dev=? AND ts>=? GROUP BY b", (meter, t0)):
            pw[p["b"]] = p["w"]
    rnd = lambda v: None if v is None else round(v, 1)
    return [[r["b"], rnd(r["room"]), rnd(r["target"]), rnd(r["outlet"]), r["on_"], r["comp"], r["mode"],
             rnd(pw.get(r["b"]))] for r in rows]


def days(dev, meter, n=14):
    """Je Tag: kWh (Energiemesser), Stunden an, davon Heizen/Kuehlen, Kompressor."""
    out = []
    ewh = {}
    if meter:
        since = (now_local() - timedelta(days=n - 1)).strftime("%Y-%m-%d")
        ewh = {r["day"]: r["wh"] for r in q("SELECT day, wh FROM energy WHERE dev=? AND day>=?", (meter, since))}
    for i in range(n - 1, -1, -1):
        t0 = _day_start(i)
        day = time.strftime("%Y-%m-%d", time.localtime(t0))
        h = _hours(dev, t0, t0 + 86400)
        out.append({"day": day, "wh": round(ewh.get(day, 0.0), 1) if meter else None, **h})
    return out


def view(d, wo=None):
    """d = Geraetezeile wie in /api/devices (dev_row)."""
    dev = d["id"]
    meter = (d.get("meter") or {}).get("id")
    return {
        "dev": dev, "name": d["name"] or dev, "room": d["room"], "online": d["online"], "status": d["status"],
        "meter": d.get("meter"), "winopen": wo, "locked": d.get("locked", False),
        "today": _hours(dev, _day_start()),
        "e_today": _energy(meter, 1), "e_30": _energy(meter, 30),
        "series": series(dev, meter), "days": days(dev, meter), "sched": sched_list(dev),
    }


def cleanup():
    q("DELETE FROM climate_log WHERE ts<?", (int(time.time()) - KEEP_POWER_DAYS * 86400,))


def loop():
    n = 0
    while True:
        try:
            record()
            run_schedules()
            n += 1
            if n % 360 == 0:
                cleanup()
        except Exception as e:
            print("Klima-Verlauf:", e, flush=True)
        time.sleep(60 - time.time() % 60 + 1)


def start(bus):
    global BUS
    BUS = bus
    init_db()
    threading.Thread(target=loop, daemon=True).start()
