# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D.Koch – Pagurus OS
"""Raumregelung fuer Klimaanlagen mit externem Fuehler.

Die Innengeraete messen unter der Decke bzw. im Luftstrom und regeln deshalb am Raum vorbei (Heizen: Raum zu warm).
Mit Raumregelung gilt die eingestellte Temperatur als Wunsch fuer den Raum. Die Cloud misst den Raum mit einem
oder mehreren Fuehlern (Mittelwert) und verstellt jede Minute die Solltemperatur am Geraet:

    Geraet = Wunsch + kp * (Wunsch - Raum) + Ausgleich

Der Ausgleich waechst langsam, solange der Raum unter dem Wunsch liegt, und sinkt, solange er darueber liegt (I-Anteil).
So lernt die Regelung die Abweichung des Geraetefuehlers selbst. Liegt der Raum beim Heizen um "cut" ueber dem Wunsch,
geht das Geraet auf seine kleinste Solltemperatur (Kompressor aus), beim Kuehlen entsprechend auf die groesste.

Mehrere Anlagen auf einer Ebene: gleiche Fuehler waehlen. Dann heizt die Anlage mit dem hoechsten Wunsch,
die anderen nehmen sich zurueck.

Wird am Geraet (Fernbedienung) eine andere Temperatur eingestellt, gilt sie als neuer Wunsch.
"""
import json
import threading
import time

from core import alert, dev_name, q

BUS = None
DEFAULT = {"on": False, "srcs": [], "kp": 1.0, "ki": 2.0, "cut": 0.5, "up": 5.0, "down": 8.0}
MAX_AGE = 1800              # Fuehlerwert gilt 30 min
MIN_GAP = 240               # Geraet hoechstens alle 4 min verstellen (ausser bei grossem Sprung)
_lock = threading.RLock()
_mismatch = {}              # dev -> Zahl der Durchlaeufe, in denen das Geraet etwas anderes zeigt als gesendet


def init_db():
    q("""CREATE TABLE IF NOT EXISTS climate_rc(dev TEXT PRIMARY KEY, cfg TEXT, wish REAL, off REAL DEFAULT 0,
         mode TEXT, last_set REAL, last_tgt REAL, room REAL, info TEXT)""")


def _row(dev):
    try:
        return q("SELECT * FROM climate_rc WHERE dev=?", (dev,), one=True)
    except Exception:                                   # Tabelle noch nicht angelegt (Start)
        return None


def get(dev):
    r = _row(dev)
    if not r:
        return None
    return {"cfg": {**DEFAULT, **json.loads(r["cfg"] or "{}")}, "wish": r["wish"], "off": r["off"] or 0.0,
            "last_tgt": r["last_tgt"], "room": r["room"], "info": r["info"] or ""}


def active(dev):
    r = get(dev)
    return r if r and r["cfg"]["on"] and r["cfg"]["srcs"] else None


def _status(dev):
    r = q("SELECT status, online FROM devices WHERE id=?", (dev,), one=True)
    return (json.loads(r["status"] or "{}"), bool(r["online"])) if r else ({}, False)


def _limits(st):
    return float(st.get("min_C") or 16), float(st.get("max_C") or 30), float(st.get("step_C") or 1)


def save(dev, c):
    cfg = dict(DEFAULT)
    cfg["on"] = bool(c.get("on"))
    cfg["srcs"] = [str(s) for s in (c.get("srcs") or []) if str(s).startswith("dev:")][:6]
    cfg["kp"] = max(0.0, min(3.0, float(c.get("kp", DEFAULT["kp"]))))
    cfg["ki"] = max(0.0, min(10.0, float(c.get("ki", DEFAULT["ki"]))))
    cfg["cut"] = max(0.2, min(3.0, float(c.get("cut", DEFAULT["cut"]))))
    cfg["up"] = max(0.0, min(10.0, float(c.get("up", DEFAULT["up"]))))
    cfg["down"] = max(0.0, min(15.0, float(c.get("down", DEFAULT["down"]))))
    if cfg["on"] and not cfg["srcs"]:
        raise ValueError("Mindestens einen Raumfühler wählen")
    with _lock:
        r = _row(dev)
        st, _ = _status(dev)
        if not r:
            q("INSERT INTO climate_rc(dev, cfg, wish, off, mode) VALUES(?,?,?,0,?)",
              (dev, json.dumps(cfg), st.get("target_C"), st.get("mode")))
        else:
            was = json.loads(r["cfg"] or "{}").get("on")
            q("UPDATE climate_rc SET cfg=? WHERE dev=?", (json.dumps(cfg), dev))
            if cfg["on"] and not was:                      # neu eingeschaltet: Wunsch = jetzige Einstellung
                q("UPDATE climate_rc SET wish=?, off=0, last_tgt=NULL, mode=? WHERE dev=?",
                  (st.get("target_C"), st.get("mode"), dev))
            if not cfg["on"] and was and r["wish"] is not None:   # aus: Wunsch wieder direkt ans Geraet
                try:
                    BUS.rpc(dev, "Climate.Set", {"id": 0, "target_C": r["wish"]})
                except Exception:
                    pass
    return cfg


def room_temp(cfg):
    import shade
    vals, bad = [], []
    for s in cfg["srcs"]:
        v, why = shade.source_value(s, MAX_AGE)
        if isinstance(v, (int, float)):
            vals.append(float(v))
        else:
            bad.append(why or "?")
    return (round(sum(vals) / len(vals), 2) if vals else None), bad


def _target(r, st, room):
    """Solltemperatur fuers Geraet aus Wunsch, Raum und Ausgleich (ohne den Ausgleich zu veraendern)."""
    cfg, wish, off = r["cfg"], r["wish"], r["off"]
    mn, mx, stp = _limits(st)
    if wish is None:
        return None
    if room is None:
        return wish
    e = wish - room
    mode = st.get("mode")
    if mode == "heat" and e <= -cfg["cut"]:
        return mn
    if mode == "cool" and e >= cfg["cut"]:
        return mx
    t = wish + cfg["kp"] * e + off
    t = max(mn, min(mx, t))
    return round(t / stp) * stp


def filter_set(dev, p):
    """Vor jedem Climate.Set: target_C ist bei aktiver Raumregelung der Wunsch fuer den Raum."""
    if "target_C" not in p and "mode" not in p:
        return p
    r = active(dev)
    if not r:
        return p
    with _lock:
        st, _ = _status(dev)
        if "mode" in p and p["mode"] != st.get("mode"):
            q("UPDATE climate_rc SET off=0, mode=? WHERE dev=?", (p["mode"], dev))
            r["off"] = 0.0
        if "target_C" in p:
            try:
                w = float(p["target_C"])
            except (TypeError, ValueError):
                return p
            q("UPDATE climate_rc SET wish=? WHERE dev=?", (w, dev))
            r["wish"] = w
            if "mode" in p:
                st = {**st, "mode": p["mode"]}
            t = _target(r, st, room_temp(r["cfg"])[0])
            p = {**p, "target_C": t}
            q("UPDATE climate_rc SET last_tgt=?, last_set=? WHERE dev=?", (t, time.time(), dev))
    return p


def step():
    now = time.time()
    for row in q("SELECT dev FROM climate_rc"):
        dev = row["dev"]
        with _lock:
            r = active(dev)
            if not r:
                continue
            cfg = r["cfg"]
            st, online = _status(dev)
            if not online or st.get("link") is False or "target_C" not in st:
                continue
            raw = _row(dev)
            cur = st.get("target_C")
            # Am Geraet (Fernbedienung) verstellt -> neuer Wunsch (zweimal hintereinander gesehen)
            diff = (raw["last_tgt"] is not None and cur is not None and abs(cur - raw["last_tgt"]) > 0.01
                    and now - (raw["last_set"] or 0) > 30)
            _mismatch[dev] = _mismatch.get(dev, 0) + 1 if diff else 0
            if _mismatch[dev] >= 2:
                _mismatch[dev] = 0
                q("UPDATE climate_rc SET wish=?, last_tgt=? WHERE dev=?", (cur, cur, dev))   # Ausgleich bleibt
                r["wish"] = cur
                alert(dev, "rule", f"{dev_name(dev)}: Raumregelung übernimmt {cur:g} °C von der Fernbedienung",
                      push=False)
            if r["wish"] is None:
                q("UPDATE climate_rc SET wish=? WHERE dev=?", (cur, dev))
                r["wish"] = cur
            room, bad = room_temp(cfg)
            info = "" if room is not None else "Raumfühler: " + ", ".join(sorted(set(bad)))
            mode = st.get("mode")
            if mode != raw["mode"]:
                q("UPDATE climate_rc SET off=0, mode=? WHERE dev=?", (mode, dev))
                r["off"] = 0.0
            mn, mx, stp = _limits(st)
            if st.get("output") and mode in ("heat", "cool") and room is not None:
                e = r["wish"] - room
                t_raw = r["wish"] + cfg["kp"] * e + r["off"]
                # I-Anteil (K pro K Abweichung und Stunde), Anti-Windup an den Geraetegrenzen
                d = cfg["ki"] * e / 60.0
                if (t_raw >= mx and d > 0) or (t_raw <= mn and d < 0):
                    d = 0.0
                if (mode == "heat" and e <= -cfg["cut"]) or (mode == "cool" and e >= cfg["cut"]):
                    d = 0.0                                   # Geraet ist ohnehin abgeregelt
                elif (mode == "heat" and e < 0 and r["off"] <= 0) or (mode == "cool" and e > 0 and r["off"] >= 0):
                    d *= 0.3                                  # unter 0 nur langsam absenken (kein Unterschwingen)
                off = max(-cfg["down"], min(cfg["up"], r["off"] + d))
                q("UPDATE climate_rc SET off=? WHERE dev=?", (off, dev))
                r["off"] = off
            q("UPDATE climate_rc SET room=?, info=? WHERE dev=?", (room, info, dev))
            if not st.get("output") or _mismatch.get(dev):    # aus, oder Fernbedienung gerade verstellt: abwarten
                continue
            if mode not in ("heat", "cool"):
                tgt = r["wish"]
            else:
                tgt = _target(r, st, room)
            if tgt is None or cur is None or abs(tgt - cur) < 0.01:
                if raw["last_tgt"] is None and cur is not None:
                    q("UPDATE climate_rc SET last_tgt=? WHERE dev=?", (cur, dev))
                continue
            if now - (raw["last_set"] or 0) < MIN_GAP and abs(tgt - cur) < 2:
                continue
            try:
                BUS.rpc(dev, "Climate.Set", {"id": 0, "target_C": tgt})
                q("UPDATE climate_rc SET last_tgt=?, last_set=? WHERE dev=?", (tgt, now, dev))
            except Exception as ex:
                q("UPDATE climate_rc SET info=? WHERE dev=?", (f"Gerät nicht erreichbar: {ex}", dev))


def view(dev):
    r = get(dev)
    if not r or not r["cfg"]["on"]:
        return None
    return {"on": True, "wish": r["wish"], "room": r["room"], "off": round(r["off"], 1), "dev_tgt": r["last_tgt"],
            "srcs": len(r["cfg"]["srcs"]), "info": r["info"]}


def wish(dev):
    r = active(dev)
    return r["wish"] if r else None


def loop():
    while True:
        try:
            step()
        except Exception as e:
            print("Raumregelung:", e, flush=True)
        time.sleep(60 - time.time() % 60 + 20)


def start(bus):
    global BUS
    BUS = bus
    init_db()
    threading.Thread(target=loop, daemon=True).start()
