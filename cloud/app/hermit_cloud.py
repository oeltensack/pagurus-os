# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D.Koch – Pagurus OS
"""Pagurus Cloud – kleine Heim-Cloud fuer Pagurus-OS- und Shelly-Gen2+-Geraete.

Die Geraete verbinden sich per MQTT (Gen2-Format) mit dem Broker. Diese App liest mit, speichert Status,
Leistung und Energie in SQLite und bietet die Weboberflaeche: Geraete und Raeume, Waesche & Co. mit
Fertig-Erkennung, Energie und Kosten, Zeitplaene und Regeln, Meldungen mit Push, Firmware, Sicherungen.
"""
import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse, PlainTextResponse

import blu
import climate
import core
import energy_view
import engine
import fridge
import gen2
import hacompat
import heizung
import scripts
import panel
import portal
import roomctl
import shade
import winopen
from bus import BUS, check_offline, seen, set_status
from core import (DATA, dev_name, KEEP_POWER_DAYS, OFFLINE_AFTER, TZ, alert, now_local, price_eur_kwh, q, qid,
                  set_setting, setting, today)

VERSION = json.loads((Path(__file__).parent / "version.json").read_text())["version"]
UPDATE_URL = os.environ.get("UPDATE_URL",
                            "https://raw.githubusercontent.com/oeltensack/pagurus-os/main/cloud/app/version.json")
PASSWORD = os.environ.get("CLOUD_PASSWORD", "")
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Pagurus Cloud", version=VERSION)


# ======================= Benutzer =======================
ROLES = ("admin", "user", "viewer")      # Admin: alles · Benutzer: schalten · Betrachter: nur lesen


def pw_hash(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${h}"


def pw_ok(pw, stored):
    try:
        salt, _ = stored.split("$", 1)
        return hmac.compare_digest(pw_hash(pw, salt), stored)
    except Exception:
        return False


def users_exist():
    return bool(q("SELECT 1 FROM users LIMIT 1", one=True))


def ensure_admin():
    """CLOUD_PASSWORD legt beim ersten Start den Benutzer 'admin' an (bzw. setzt sein Passwort)."""
    if not PASSWORD:
        return
    r = q("SELECT pw FROM users WHERE name='admin'", one=True)
    if not r:
        q("INSERT INTO users(name, pw, role, created) VALUES('admin',?,'admin',?)", (pw_hash(PASSWORD), time.time()))
    elif setting("admin_pw_from_env", True) and not pw_ok(PASSWORD, r["pw"]):
        q("UPDATE users SET pw=? WHERE name='admin'", (pw_hash(PASSWORD),))


# Interner Zugang fuer Anfragen, die das Fernzugang-Portal durchreicht (nur von diesem Rechner aus,
# Schluessel wechselt bei jedem Start). Rolle legt das Portal fest (schreibgeschuetzt = viewer).
INTERNAL_KEY = secrets.token_hex(24)


def current_user(request: Request):
    ik = request.headers.get("x-pagurus-internal", "")
    if ik and hmac.compare_digest(ik, INTERNAL_KEY) and request.client and request.client.host in ("127.0.0.1", "::1"):
        role = request.headers.get("x-pagurus-role", "viewer")
        return {"name": "portal", "role": role if role in ROLES else "viewer"}
    if not users_exist():
        return {"name": "admin", "role": "admin", "open": True}
    auth_h = request.headers.get("authorization", "")
    tok = auth_h[7:].strip() if auth_h.lower().startswith("bearer ") else request.cookies.get("hc", "")
    if tok:
        s = q("SELECT s.name, u.role FROM sessions s JOIN users u ON u.name=s.name WHERE s.token=?", (tok,), one=True)
        if s:
            q("UPDATE sessions SET seen=? WHERE token=?", (time.time(), tok))
            return {"name": s["name"], "role": s["role"]}
    return None


def need(request, role):
    u = request.state.user
    order = {"viewer": 0, "user": 1, "admin": 2}
    if order.get(u["role"], -1) < order[role]:
        raise HTTPException(403, "Keine Berechtigung")


OPEN_PATHS = ("/api/login", "/api/info/public")


@app.middleware("http")
async def auth(request: Request, call_next):
    p = request.url.path
    ip = request.client.host if request.client else None
    ha = p in hacompat.PATHS and panel.by_ip(ip)                     # Wall-Display-Pruefung
    if p.startswith("/api/") and p not in OPEN_PATHS and not ha:
        u = current_user(request)
        if not u:
            if hacompat.watched(p):
                hacompat.note(ip, request.method, p, 401)
            return JSONResponse({"detail": "Anmeldung erforderlich"}, status_code=401)
        request.state.user = u
    resp = await call_next(request)
    if hacompat.watched(p):
        hacompat.note(ip, request.method, p, resp.status_code)
    return resp


@app.post("/api/login")
async def login(request: Request, response: Response):
    d = await request.json()
    if not users_exist():
        return {"ok": True}
    name = str(d.get("name") or "admin").strip()
    r = q("SELECT pw FROM users WHERE name=?", (name,), one=True)
    if not r or not pw_ok(str(d.get("password", "")), r["pw"]):
        raise HTTPException(401, "Name oder Passwort falsch")
    tok = secrets.token_urlsafe(24)
    q("INSERT INTO sessions(token, name, created, seen) VALUES(?,?,?,?)", (tok, name, time.time(), time.time()))
    response.set_cookie("hc", tok, max_age=365 * 86400, httponly=True, samesite="lax")
    return {"ok": True, "token": tok}         # Token fuer die App (Authorization: Bearer …)


@app.post("/api/logout")
def logout(request: Request, response: Response):
    q("DELETE FROM sessions WHERE token=?", (request.cookies.get("hc", ""),))
    response.delete_cookie("hc")
    return {"ok": True}


@app.get("/api/users")
def users(request: Request):
    need(request, "admin")
    return [{"name": r["name"], "role": r["role"], "created": r["created"]}
            for r in q("SELECT * FROM users ORDER BY name")]


@app.post("/api/users")
async def user_save(request: Request):
    need(request, "admin")
    d = await request.json()
    name, role, pw = str(d.get("name", "")).strip(), d.get("role", "user"), d.get("password") or ""
    if not name or role not in ROLES:
        raise HTTPException(400, "Name und Rolle angeben")
    r = q("SELECT 1 FROM users WHERE name=?", (name,), one=True)
    if not r:
        if len(pw) < 6:
            raise HTTPException(400, "Passwort mindestens 6 Zeichen")
        q("INSERT INTO users(name, pw, role, created) VALUES(?,?,?,?)", (name, pw_hash(pw), role, time.time()))
    else:
        if name == "admin" and role != "admin":
            raise HTTPException(400, "admin bleibt Administrator")
        q("UPDATE users SET role=? WHERE name=?", (role, name))
        if pw:
            if len(pw) < 6:
                raise HTTPException(400, "Passwort mindestens 6 Zeichen")
            q("UPDATE users SET pw=? WHERE name=?", (pw_hash(pw), name))
            q("DELETE FROM sessions WHERE name=?", (name,))
            if name == "admin":
                set_setting("admin_pw_from_env", False)
    return {"ok": True}


@app.delete("/api/users/{name}")
def user_delete(name: str, request: Request):
    need(request, "admin")
    if name == "admin":
        raise HTTPException(400, "admin kann nicht gelöscht werden")
    q("DELETE FROM users WHERE name=?", (name,))
    q("DELETE FROM sessions WHERE name=?", (name,))
    return {"ok": True}


# ======================= Start =======================
def ping_devices(devs):
    """Lebenszeichen per RPC abfragen; liefert die Geraete, die geantwortet haben."""
    import concurrent.futures
    if not devs or not BUS.connected:
        return set()

    def one(d):
        try:
            BUS.rpc(d, "Sys.GetStatus", None, 5)
            return d
        except Exception:
            return None
    with concurrent.futures.ThreadPoolExecutor(min(8, len(devs))) as ex:
        return {d for d in ex.map(one, devs) if d}


def watchdog():
    while True:
        time.sleep(20)
        try:
            lim = time.time() - OFFLINE_AFTER
            # Batteriefuehler (BLU, Door/Window, H&T) schlafen zwischen den Meldungen – nicht als offline melden.
            # Geraete ohne Leistungsmessung (Plus 1, Mini, i4 …) senden oft minutenlang nichts: vor „offline“
            # erst selbst nachfragen (Sys.GetStatus). Nur wer nicht antwortet, gilt als offline.
            stale = [r["id"] for r in q("SELECT id FROM devices WHERE online=1 AND last_seen<? "
                                        "AND COALESCE(comp,'')!='sensor:0'", (lim,))]
            alive = ping_devices({d.split("~")[0] for d in stale})
            for d in stale:
                seen(d, online=None if d.split("~")[0] in alive else False)
            check_offline()
            q("DELETE FROM power WHERE ts<?", (int(time.time()) - KEEP_POWER_DAYS * 86400,))
            q("DELETE FROM alerts WHERE ts<? AND ack=1", (time.time() - 180 * 86400,))
            q("DELETE FROM sessions WHERE seen<?", (time.time() - 365 * 86400,))
            fridge.cleanup()
        except Exception as e:
            print("Watchdog:", e, flush=True)


@app.on_event("startup")
def startup():
    core.init_db()
    blu.init_db()
    winopen.init_db()
    climate.init_db()
    panel.init_db()
    blu.BUS = BUS
    ensure_admin()
    pk = setting("push_kinds")                 # neue Push-Art in bestehende Auswahl aufnehmen (einmalig)
    if pk is not None and "fridge" not in pk and not setting("mig_push_fridge"):
        set_setting("push_kinds", pk + ["fridge"])
    set_setting("mig_push_fridge", True)
    pk = setting("push_kinds")
    if pk is not None and "window" not in pk and not setting("mig_push_window"):
        set_setting("push_kinds", pk + ["window"])
    set_setting("mig_push_window", True)
    pk = setting("push_kinds")
    if pk is not None and "heating" not in pk and not setting("mig_push_heating"):
        set_setting("push_kinds", pk + ["heating"])
    set_setting("mig_push_heating", True)
    core.start_push()
    BUS.start()
    engine.start(BUS)
    shade.start(BUS)
    winopen.start(BUS)
    climate.start(BUS)
    roomctl.start(BUS)
    heizung.start()
    scripts.start(BUS)
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=updater_loop, daemon=True).start()
    portal.start(devices)


app.include_router(hacompat.router)
app.include_router(heizung.router)
app.include_router(scripts.router)


@app.get("/")
def index(request: Request):
    if request.client and panel.by_ip(request.client.host):   # gebundenes Wall Display: gleich seine Tafel
        return RedirectResponse("/wd", status_code=302)
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


def _static(f, t):
    return lambda: FileResponse(STATIC / f, media_type=t, headers={"Cache-Control": "no-cache"})


for _f, _t in (("manifest.webmanifest", "application/manifest+json"), ("sw.js", "text/javascript"),
               ("icon-192.png", "image/png"), ("icon-512.png", "image/png"), ("apple-touch-icon.png", "image/png")):
    app.get("/" + _f, include_in_schema=False)(_static(_f, _t))


# ======================= Geraete =======================
async def rpc_async(dev, method, params=None, timeout=6):
    try:
        return await asyncio.to_thread(BUS.rpc, dev, method, params, timeout)
    except Exception as e:
        raise HTTPException(502, str(e))


def is_hermit(r):
    info = json.loads(r["info"] or "{}")
    return str(info.get("fw_id", "")).startswith(("hermit", "pagurus")) or \
        str(r["model"] or "").upper().startswith(("HERMIT", "PAGURUS"))


def dev_row(r, latest=None):
    st = json.loads(r["status"] or "{}")
    e = q("SELECT wh FROM energy WHERE dev=? AND day=?", (r["id"], today()), one=True)
    wh = round(e["wh"], 1) if e else 0.0
    hermit = is_hermit(r)
    out = {
        "id": r["id"], "name": r["name"] or "", "room": r["room"] or "", "model": r["model"], "app": r["app"],
        "ver": r["ver"], "mac": r["mac"], "ip": r["ip"], "gen": r["gen"], "online": bool(r["online"]),
        "last_seen": r["last_seen"], "comp": r["comp"], "status": st, "hermit": hermit,
        "today_wh": wh, "today_cost": round(wh / 1000 * price_eur_kwh(), 2), "fw_new": None,
        "locked": bool(r["locked"]),
    }
    if "~" in r["id"]:                           # zweiter Kanal eines Geraets
        base = q("SELECT name FROM devices WHERE id=?", (r["id"].split("~")[0],), one=True)
        out["channel_of"] = r["id"].split("~")[0]
        if not out["name"]:
            out["name"] = f"{(base['name'] if base and base['name'] else out['channel_of'])} · Kanal {int(r['id'].split('~')[1]) + 1}"
    elif hermit and latest:
        out["fw_new"] = latest if engine.ver_tuple(latest) > engine.ver_tuple(r["ver"]) else None
    elif r["id"] in engine.FW["gen2"]:
        out["fw_new"] = engine.FW["gen2"][r["id"]]
    a = engine.appliance(r["id"])
    if a:
        out["appliance"] = {"type": a["type"], "label": a["label"], "state": a["state"]}
    f = fridge.get(r["id"])
    if f:
        out["fridge"] = {"label": f["label"], "state": f["state"], "alarm": bool(f["alarm_run"] or f["alarm_off"])}
    if r["meter"]:                                 # gekoppelter Energiemesser: Leistung und Verbrauch uebernehmen
        m = q("SELECT * FROM devices WHERE id=?", (r["meter"],), one=True)
        if m:
            ms = json.loads(m["status"] or "{}")
            me = q("SELECT wh FROM energy WHERE dev=? AND day=?", (m["id"], today()), one=True)
            mwh = round(me["wh"], 1) if me else 0.0
            out["meter"] = {"id": m["id"], "name": m["name"] or m["id"], "online": bool(m["online"]),
                            "apower": ms.get("apower"), "today_wh": mwh,
                            "today_cost": round(mwh / 1000 * price_eur_kwh(), 2), "hide": bool(r["meter_hide"])}
    if (r["comp"] or "").startswith("climate:"):
        w = winopen.view(r["id"])
        if w:
            out["winopen"] = w
    p = q("SELECT id, meter_hide FROM devices WHERE meter=? LIMIT 1", (r["id"],), one=True)
    if p:                                          # ist selbst Energiemesser eines anderen Geraets
        out["meter_of"] = p["id"]
        out["meter_hidden"] = bool(p["meter_hide"])
    return out


@app.get("/api/devices")
def devices():
    latest = engine.FW["hermit"]
    rows = q("SELECT * FROM devices WHERE hidden=0 ORDER BY COALESCE(NULLIF(room,''),'~'), COALESCE(NULLIF(name,''), id)")
    out = [dev_row(r, latest) for r in rows]
    out.sort(key=lambda d: (d["room"] == "", d["room"].lower(), (d["name"] or d["id"]).lower()))   # Kanal 2 neben Kanal 1
    comb = {r["id"]: r for r in rows if r["combine"] and "~" not in r["id"]}
    if comb:                                     # mehrkanalige Geraete: Kanaele in der Karte von Kanal 1
        by = {d["id"]: d for d in out}
        for base, r in comb.items():
            kids = [d for d in out if d.get("channel_of") == base]
            if base in by and kids:
                by[base]["combined"] = True
                by[base]["ch_label"] = r["ch_label"] or "Kanal 1"
                by[base]["channels"] = kids
                for k in kids:
                    k["combined_into"] = base
    return out


def get_dev(dev):
    r = q("SELECT * FROM devices WHERE id=?", (dev,), one=True)
    if not r:
        raise HTTPException(404, "Unbekanntes Gerät")
    return r


def not_locked(r):
    if r["locked"]:
        raise HTTPException(423, "Gesperrt – Schalten von Hand ist für dieses Gerät abgeschaltet")


@app.post("/api/devices/{dev}/rpc")
async def dev_rpc(dev: str, request: Request):
    need(request, "admin")
    get_dev(dev)
    d = await request.json()
    return {"result": await rpc_async(dev, d["method"], d.get("params"))}


@app.post("/api/devices/{dev}/switch")
async def dev_switch(dev: str, request: Request):
    need(request, "user")
    not_locked(get_dev(dev))
    d = await request.json()
    try:
        res = await asyncio.to_thread(BUS.switch, dev, d.get("on") if "on" in d else None, d.get("brightness"),
                                      d.get("cover"), d.get("pos"))
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"result": res}


@app.post("/api/devices/{dev}/climate")
async def dev_climate(dev: str, request: Request):
    """Klimaanlage (Pagurus OS ESP32): Modus, Solltemperatur, Luefter, Swing, Eco/Turbo/Leise/Nacht."""
    need(request, "user")
    d = await request.json()
    if "on" in d:                       # "Nur Anzeige" sperrt bei Klimageraeten nur Ein/Aus
        not_locked(get_dev(dev))
    p = {"id": 0}
    for k in ("on", "mode", "target_C", "fan", "swing_v", "swing_h", "eco", "turbo", "mute", "sleep", "display", "display_toggle"):
        if k in d:
            p[k] = d[k]
    try:
        p = await asyncio.to_thread(roomctl.filter_set, dev, p)
        res = await asyncio.to_thread(BUS.rpc, dev, "Climate.Set", p)
        st = await asyncio.to_thread(BUS.rpc, dev, "Climate.GetStatus", {"id": 0})
        set_status(dev, "climate:0", st, merge=True)
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"result": res}


# ======================= Taster (Plus i4 u. a.) =======================
BTN_EVENTS = ("single_push", "double_push", "triple_push", "long_push")


def _btn_rules(dev):
    out = []
    for r in q("SELECT * FROM rules"):
        t = json.loads(r["trig"] or "{}")
        if t.get("type") == "event" and t.get("dev") == dev and str(t.get("comp", "")).startswith("input:") \
                and t.get("event") in BTN_EVENTS and t.get("btn"):
            out.append((r, t))
    return out


@app.get("/api/buttons/{dev}")
def buttons_get(dev: str, request: Request):
    """Zuordnung Eingang × Druckart -> Aktion (intern als Regeln mit Kennzeichen btn gespeichert)."""
    need(request, "admin")
    get_dev(dev)
    m = []
    for r, t in _btn_rules(dev):
        a = (json.loads(r["action"] or "[]") or [{}])[0]
        m.append({"input": int(t["comp"].split(":")[1]), "event": t["event"], "target": a.get("target"),
                  "mode": a.get("mode", "toggle"), "enabled": bool(r["enabled"])})
    return {"map": m, "events": BTN_EVENTS}


@app.post("/api/buttons/{dev}")
async def buttons_save(dev: str, request: Request):
    need(request, "admin")
    get_dev(dev)
    d = await request.json()
    rows = []
    for x in d.get("map") or []:
        if not x.get("target"):
            continue
        if x.get("event") not in BTN_EVENTS:
            raise HTTPException(400, "Unbekannte Druckart")
        _target_ok(x["target"])
        mode = x.get("mode") or "toggle"
        if x["target"].startswith("scene:"):
            mode = "on"
        elif mode not in ("on", "off", "toggle"):
            raise HTTPException(400, "Aktion: an, aus oder umschalten")
        rows.append((int(x.get("input", 0)), x["event"], x["target"], mode))
    for r, _ in _btn_rules(dev):
        q("DELETE FROM rules WHERE id=?", (r["id"],))
    names = {"single_push": "kurz", "double_push": "doppelt", "triple_push": "dreifach", "long_push": "lang"}
    for inp, ev, target, mode in rows:
        trig = {"type": "event", "dev": dev, "comp": f"input:{inp}", "event": ev, "btn": True}
        act = [{"type": "switch", "target": target, "mode": mode}]
        qid("INSERT INTO rules(name, enabled, trig, action) VALUES(?,?,?,?)",
            (f"Taster {dev_name(dev)} {inp + 1} {names[ev]}", 1, json.dumps(trig), json.dumps(act)))
    return {"ok": True, "count": len(rows)}


# ======================= Wandtafeln (Wall Display) =======================
@app.get("/api/panels")
def panels_list(request: Request):
    need(request, "admin")
    return panel.all_panels()


@app.post("/api/panels")
async def panels_save(request: Request):
    need(request, "admin")
    d = await request.json()
    pid = panel.save(d)
    if d.get("new_token"):
        panel.new_token(pid)
    return {"id": pid}


@app.get("/api/panels/log")
def panels_log(request: Request):
    """Letzte Anfragen von Displays an die Home-Assistant-Pruefung – zeigt, mit welcher IP das Display kommt."""
    need(request, "admin")
    return list(hacompat.LOG)


@app.delete("/api/panels/{pid}")
def panels_delete(pid: int, request: Request):
    need(request, "admin")
    q("DELETE FROM panels WHERE id=?", (pid,))
    return {"ok": True}


def _panel(tok, request=None):
    """Tafel ueber den Schluessel in der Adresse oder – kurze Adresse /wd – ueber die IP des Absenders."""
    p = panel.by_ip(request.client.host if request and request.client else None) if tok == "-" else panel.by_token(tok)
    if not p:
        raise HTTPException(404, "Unbekannte Wandtafel – Adresse prüfen bzw. Gerät in der Cloud an die Tafel binden")
    return p


@app.get("/wd")
def wd_short(request: Request):
    _panel("-", request)
    return FileResponse(STATIC / "wd.html", headers={"Cache-Control": "no-store"})


@app.get("/wd/{tok}")
def wd_page(tok: str, request: Request):
    _panel(tok, request)
    return FileResponse(STATIC / "wd.html", headers={"Cache-Control": "no-store"})


@app.get("/wd/{tok}/state")
def wd_state(tok: str, request: Request):
    return panel.state(_panel(tok, request), devices())


@app.post("/wd/{tok}/act")
async def wd_act(tok: str, request: Request):
    """Bedienung von der Tafel: nur Kacheln dieser Tafel, nur wenn die Tafel bedienen darf."""
    p = _panel(tok, request)
    d = await request.json()
    tid, a, v = str(d.get("id") or ""), d.get("a"), d.get("v")
    if not p["control"] or not panel.allowed(p, tid):
        raise HTTPException(403, "Nicht erlaubt")
    kind, _, ref = tid.partition(":")
    try:
        if kind == "scene":
            errs = await asyncio.to_thread(engine.run_scene, int(ref))
            return {"errors": errs}
        not_locked(get_dev(ref))
        if a == "toggle":
            await asyncio.to_thread(BUS.switch, ref)
        elif a == "bri":
            await asyncio.to_thread(BUS.switch, ref, None, int(v))
        elif a == "cover" and v in ("open", "stop", "close"):
            await asyncio.to_thread(BUS.switch, ref, None, None, v)
        elif a == "pos":
            await asyncio.to_thread(BUS.switch, ref, None, None, None, int(v))
        elif a == "climate" and isinstance(v, dict):
            prm = {"id": 0, **{k: x for k, x in v.items() if k in panel.CLIMATE_KEYS}}
            prm = await asyncio.to_thread(roomctl.filter_set, ref, prm)
            await asyncio.to_thread(BUS.rpc, ref, "Climate.Set", prm)
            st = await asyncio.to_thread(BUS.rpc, ref, "Climate.GetStatus", {"id": 0})
            set_status(ref, "climate:0", st, merge=True)
        else:
            raise HTTPException(400, "Unbekannte Aktion")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@app.get("/api/climates")
def climates():
    """Eigener Bereich Klimaanlagen: Zustand, Laufzeiten, Verbrauch, 24-h-Verlauf, 14 Tage."""
    out = []
    for r in q("SELECT * FROM devices WHERE comp LIKE 'climate:%' AND hidden=0 "
               "ORDER BY COALESCE(NULLIF(room,''),'~'), COALESCE(NULLIF(name,''), id)"):
        d = dev_row(r)
        w = winopen.get(r["id"])
        wo = None
        if w:
            wo = {**winopen.view(r["id"]), "sensors": len(w["cfg"]["sensors"]), "drop": w["cfg"]["drop"],
                  "modes": w["cfg"]["modes"]}
        v = climate.view(d, wo)
        v["rc"] = roomctl.view(r["id"])
        out.append(v)
    return out


@app.post("/api/climates/{dev}/sched")
async def climate_sched_save(dev: str, request: Request):
    need(request, "admin")
    r = get_dev(dev)
    if not (r["comp"] or "").startswith("climate:"):
        raise HTTPException(400, "Keine Klimaanlage")
    try:
        return {"id": climate.sched_save(dev, await request.json())}
    except (ValueError, TypeError, KeyError) as e:
        raise HTTPException(400, str(e) or "Zeit als HH:MM oder sunrise±Minuten / sunset±Minuten")


@app.delete("/api/climates/{dev}/sched/{sid}")
def climate_sched_delete(dev: str, sid: int, request: Request):
    need(request, "admin")
    q("DELETE FROM climate_sched WHERE id=? AND dev=?", (sid, dev))
    return {"ok": True}


@app.get("/api/climates/{dev}/rc")
def roomctl_get(dev: str, request: Request):
    need(request, "admin")
    get_dev(dev)
    r = roomctl.get(dev)
    sens = [x for x in shade.sensors() if x["unit"] == "°C"]
    return {"cfg": r["cfg"] if r else roomctl.DEFAULT, "state": roomctl.view(dev), "sensors": sens}


@app.post("/api/climates/{dev}/rc")
async def roomctl_save(dev: str, request: Request):
    """Raumregelung: Solltemperatur am Geraet nach externem Raumfuehler nachfuehren."""
    need(request, "admin")
    r = get_dev(dev)
    if not (r["comp"] or "").startswith("climate:"):
        raise HTTPException(400, "Keine Klimaanlage")
    try:
        return {"cfg": await asyncio.to_thread(roomctl.save, dev, await request.json())}
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/devices/{dev}/winopen")
def winopen_get(dev: str, request: Request):
    get_dev(dev)
    r = winopen.get(dev)
    return {"cfg": r["cfg"] if r else None, "default": winopen.DEFAULT, "state": winopen.view(dev)}


@app.post("/api/devices/{dev}/winopen")
async def winopen_save(dev: str, request: Request):
    """Fenster/Tuer offen: Klimaanlage pausieren (Kontakte und/oder Temperatursturz)."""
    need(request, "admin")
    get_dev(dev)
    try:
        return {"cfg": winopen.save(dev, await request.json())}
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/devices/{dev}/winopen")
def winopen_delete(dev: str, request: Request):
    need(request, "admin")
    winopen.delete(dev)
    return {"ok": True}


@app.post("/api/devices/{dev}/meta")
async def dev_meta(dev: str, request: Request):
    """Name und Raum (der Name wird auch am Geraet gesetzt, wenn es erreichbar ist)."""
    need(request, "admin")
    get_dev(dev)
    d = await request.json()
    if "room" in d:
        q("UPDATE devices SET room=? WHERE id=?", (str(d["room"]).strip(), dev))
    if "combine" in d and "~" not in dev:
        q("UPDATE devices SET combine=? WHERE id=?", (1 if d["combine"] else 0, dev))
    if "ch_label" in d:
        q("UPDATE devices SET ch_label=? WHERE id=?", (str(d["ch_label"] or "").strip() or None, dev))
    if "locked" in d:
        q("UPDATE devices SET locked=? WHERE id=?", (1 if d["locked"] else 0, dev))
    if "meter" in d:
        m = str(d["meter"] or "").strip()
        if m and (m == dev or not q("SELECT id FROM devices WHERE id=?", (m,), one=True)):
            raise HTTPException(400, "Unbekannter Energiemesser")
        q("UPDATE devices SET meter=?, meter_hide=? WHERE id=?", (m or None, 1 if d.get("meter_hide", True) else 0, dev))
    if "name" in d:
        name = str(d["name"]).strip()
        q("UPDATE devices SET name=? WHERE id=?", (name, dev))
        try:
            if "~" in dev:                         # zweiter Kanal: Name des Schaltkanals am Geraet
                await asyncio.to_thread(BUS.rpc, dev, "Switch.SetConfig",
                                        {"id": int(dev.split("~")[1]), "config": {"name": name}}, 4)
            else:
                await asyncio.to_thread(BUS.rpc, dev, "Sys.SetConfig", {"config": {"device": {"name": name}}}, 4)
        except Exception:
            pass
    return {"ok": True}


@app.post("/api/devices/{dev}/name")
async def dev_rename(dev: str, request: Request):
    return await dev_meta(dev, request)


@app.delete("/api/devices/{dev}")
def dev_delete(dev: str, request: Request):
    need(request, "admin")
    get_dev(dev)
    rows = [dev] + ([] if "~" in dev else [r["id"] for r in q("SELECT id FROM devices WHERE id LIKE ?", (dev + "~%",))])
    for d in rows:                               # mit zweitem Kanal (Shelly 2.5)
        for t in ("power", "energy", "energy_h", "appliances", "runs", "backups", "fridges", "fridge_cycles", "winopen", "climate_log", "climate_sched"):
            try:
                q(f"DELETE FROM {t} WHERE dev=?", (d,))
            except Exception:
                pass
        q("DELETE FROM devices WHERE id=?", (d,))
        q("UPDATE devices SET meter=NULL WHERE meter=?", (d,))
    if "~" not in dev:
        BUS.forget(dev)                          # sonst legt der Broker es beim naechsten Neustart wieder an
    return {"ok": True}


@app.get("/api/rooms")
def rooms():
    return [r["room"] for r in q("SELECT DISTINCT room FROM devices WHERE room!='' AND hidden=0 ORDER BY room")]


@app.post("/api/rooms/switch")
async def room_switch(request: Request):
    need(request, "user")
    d = await request.json()
    errs = await asyncio.to_thread(engine.do_switch, f"room:{d['room']}", "on" if d.get("on") else "off")
    return {"errors": errs}


# ======================= Leistung, Energie, Kosten =======================
@app.get("/api/devices/{dev}/power")
def dev_power(dev: str, hours: float = 24, start: float = 0, end: float = 0, points: int = 800):
    end = end or time.time()
    start = start or end - min(hours, KEEP_POWER_DAYS * 24) * 3600
    rows = q("SELECT ts, w, COALESCE(wmax, w) AS wmax FROM power WHERE dev=? AND ts>=? AND ts<=? ORDER BY ts",
             (dev, int(start), int(end)))
    if len(rows) <= points:
        return {"start": start, "end": end, "data": [[r["ts"], r["w"], r["wmax"]] for r in rows], "bucket_s": 60}
    step = (end - start) / points
    buckets = {}
    for r in rows:
        b = int((r["ts"] - start) // step)
        s = buckets.setdefault(b, [0.0, 0, 0.0])
        s[0] += r["w"]
        s[1] += 1
        s[2] = max(s[2], r["wmax"])
    data = [[int(start + (b + 0.5) * step), s[0] / s[1], s[2]] for b, s in sorted(buckets.items())]
    return {"start": start, "end": end, "data": data, "bucket_s": step}


@app.get("/api/energy")
def energy(dev: str = "", days: int = 31):
    start = (now_local() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    if dev:
        rows = q("SELECT day, wh FROM energy WHERE dev=? AND day>=? ORDER BY day", (dev, start))
    else:
        rows = q("SELECT day, SUM(wh) AS wh FROM energy WHERE day>=? GROUP BY day ORDER BY day", (start,))
    have = {r["day"]: r["wh"] for r in rows}
    out = []
    for i in range(days):
        d = (now_local() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        out.append([d, round(have.get(d, 0.0), 1)])
    return out


@app.get("/api/energy/period")
def energy_period(dev: str = "", kind: str = "month", date: str = ""):
    return energy_view.period(dev, kind, date)


@app.get("/api/energy/months")
def energy_months(dev: str = ""):
    p = price_eur_kwh()
    if dev:
        rows = q("SELECT substr(day,1,7) AS m, SUM(wh) AS wh FROM energy WHERE dev=? GROUP BY m ORDER BY m DESC LIMIT 24", (dev,))
    else:
        rows = q("SELECT substr(day,1,7) AS m, SUM(wh) AS wh FROM energy GROUP BY m ORDER BY m DESC LIMIT 24")
    return [[r["m"], round(r["wh"], 1), round(r["wh"] / 1000 * p, 2)] for r in rows]


@app.get("/api/energy/by_device")
def energy_by_device(days: int = 30):
    start = (now_local() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    p = price_eur_kwh()
    rows = q("""SELECT e.dev, COALESCE(NULLIF(d.name,''), e.dev) AS name, SUM(e.wh) AS wh FROM energy e
                LEFT JOIN devices d ON d.id=e.dev WHERE e.day>=? GROUP BY e.dev ORDER BY wh DESC""", (start,))
    return [{"dev": r["dev"], "name": r["name"], "wh": round(r["wh"], 1), "cost": round(r["wh"] / 1000 * p, 2)}
            for r in rows]


@app.get("/api/baseload")
def baseload(days: int = 7):
    """Grundlast je Geraet: 10-%-Quantil der Minutenwerte der letzten Tage."""
    since = int(time.time()) - days * 86400
    p = price_eur_kwh()
    out = []
    for d in q("SELECT id, name FROM devices WHERE hidden=0"):
        ws = [r["w"] for r in q("SELECT w FROM power WHERE dev=? AND ts>=? ORDER BY w", (d["id"], since))]
        if len(ws) < 60:
            continue
        base = ws[len(ws) // 10]
        if base < 0.3:
            continue
        kwh_y = base * 8.76
        out.append({"dev": d["id"], "name": d["name"] or d["id"], "w": round(base, 1), "kwh_year": round(kwh_y, 1),
                    "cost_year": round(kwh_y * p, 2), "hours": round(len(ws) / 60)})
    out.sort(key=lambda x: -x["w"])
    return {"devices": out, "total_w": round(sum(x["w"] for x in out), 1),
            "total_kwh_year": round(sum(x["kwh_year"] for x in out), 1),
            "total_cost_year": round(sum(x["cost_year"] for x in out), 2)}


def csv_response(name, header, rows):
    buf = io.StringIO()
    buf.write("﻿")                         # BOM: Excel erkennt UTF-8
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    for r in rows:
        w.writerow([str(x).replace(".", ",") if isinstance(x, float) else x for x in r])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/export/energy.csv")
def export_energy(start: str = "", end: str = "", dev: str = ""):
    start = start or (now_local() - timedelta(days=30)).strftime("%Y-%m-%d")
    end = end or today()
    p = price_eur_kwh()
    sql = """SELECT e.day, e.dev, COALESCE(NULLIF(d.name,''), e.dev) AS name, d.room, e.wh FROM energy e
             LEFT JOIN devices d ON d.id=e.dev WHERE e.day>=? AND e.day<=?"""
    args = [start, end]
    if dev:
        sql += " AND e.dev=?"
        args.append(dev)
    rows = q(sql + " ORDER BY e.day, name", args)
    return csv_response(f"energie_{start}_{end}.csv", ["Tag", "Gerät", "Name", "Raum", "kWh", "Kosten €"],
                        [[r["day"], r["dev"], r["name"], r["room"] or "", round(r["wh"] / 1000, 3),
                          round(r["wh"] / 1000 * p, 2)] for r in rows])


@app.get("/api/export/power.csv")
def export_power(dev: str, hours: float = 24):
    since = int(time.time() - hours * 3600)
    rows = q("SELECT ts, w, wmax FROM power WHERE dev=? AND ts>=? ORDER BY ts", (dev, since))
    return csv_response(f"leistung_{dev}.csv", ["Zeit", "Leistung W", "Spitze W"],
                        [[datetime.fromtimestamp(r["ts"], TZ).strftime("%d.%m.%Y %H:%M"), float(r["w"]),
                          float(r["wmax"] if r["wmax"] is not None else r["w"])] for r in rows])


@app.get("/api/export/runs.csv")
def export_runs(dev: str = ""):
    sql = """SELECT r.*, COALESCE(NULLIF(d.name,''), r.dev) AS name FROM runs r LEFT JOIN devices d ON d.id=r.dev
             WHERE r.end IS NOT NULL"""
    args = []
    if dev:
        sql += " AND r.dev=?"
        args.append(dev)
    rows = q(sql + " ORDER BY r.start", args)
    lbl = {k: v["label"] for k, v in engine.TYPES.items()}
    return csv_response("laeufe.csv", ["Start", "Ende", "Dauer min", "Gerät", "Art", "kWh", "Kosten €", "Spitze W"],
                        [[datetime.fromtimestamp(r["start"], TZ).strftime("%d.%m.%Y %H:%M"),
                          datetime.fromtimestamp(r["end"], TZ).strftime("%d.%m.%Y %H:%M"),
                          round((r["end"] - r["start"]) / 60), r["name"], lbl.get(r["type"], r["type"]),
                          round((r["wh"] or 0) / 1000, 3), round(r["cost"] or 0, 2), float(r["peak_w"] or 0)]
                         for r in rows])


# ======================= Waesche & Co. =======================
@app.get("/api/appliances")
def appliances():
    return {"types": engine.TYPES,
            "items": [engine.appliance_view(a) for a in q("SELECT * FROM appliances ORDER BY type, dev")]}


@app.post("/api/appliances/{dev}")
async def appliance_save(dev: str, request: Request):
    need(request, "admin")
    get_dev(dev)
    try:
        engine.set_appliance(dev, await request.json())
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/appliances/{dev}")
def appliance_delete(dev: str, request: Request):
    need(request, "admin")
    q("DELETE FROM appliances WHERE dev=?", (dev,))
    return {"ok": True}


@app.post("/api/appliances/{dev}/ack")
def appliance_ack(dev: str, request: Request):
    need(request, "user")
    engine.ack_appliance(dev)
    return {"ok": True}


@app.get("/api/runs")
def runs(dev: str = "", limit: int = 50):
    sql = """SELECT r.*, COALESCE(NULLIF(d.name,''), r.dev) AS name FROM runs r LEFT JOIN devices d ON d.id=r.dev
             WHERE r.end IS NOT NULL"""
    args = []
    if dev:
        sql += " AND r.dev=?"
        args.append(dev)
    return [dict(r) for r in q(sql + " ORDER BY r.start DESC LIMIT ?", args + [limit])]


@app.delete("/api/runs/{rid}")
def run_delete(rid: int, request: Request):
    need(request, "admin")
    q("DELETE FROM runs WHERE id=? AND end IS NOT NULL", (rid,))
    return {"ok": True}


# ======================= Kuehlgeraete =======================
@app.get("/api/fridges")
def fridges():
    return {"types": fridge.TYPES, "items": [fridge.view(f) for f in q("SELECT * FROM fridges ORDER BY label, dev")]}


@app.post("/api/fridges/{dev}")
async def fridge_save(dev: str, request: Request):
    need(request, "admin")
    get_dev(dev)
    try:
        fridge.save(dev, await request.json())
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/fridges/{dev}")
def fridge_delete(dev: str, request: Request):
    need(request, "admin")
    fridge.delete(dev)
    return {"ok": True}


# ======================= Zeitplaene + Regeln =======================
def _target_ok(t, scene=True):
    if not t or t.partition(":")[0] not in (("dev", "room", "scene") if scene else ("dev", "room")) \
            or not t.partition(":")[2]:
        raise HTTPException(400, "Ziel fehlt")


# ======================= Szenen =======================
@app.get("/api/scenes")
def scenes():
    out = []
    for r in q("SELECT * FROM scenes ORDER BY sort, name COLLATE NOCASE"):
        d = dict(r)
        d["actions"] = json.loads(r["actions"] or "[]")
        out.append(d)
    return out


@app.post("/api/scenes")
async def scene_save(request: Request):
    need(request, "admin")
    d = await request.json()
    name = str(d.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name fehlt")
    acts = []
    for a in d.get("actions") or []:
        _target_ok(a.get("target"), scene=False)
        m = str(a.get("mode") or "on")
        if m not in ("on", "off", "toggle") and not (m.startswith("pos:") and m[4:].isdigit() and int(m[4:]) <= 100):
            raise HTTPException(400, "Aktion fehlt")
        acts.append({"target": a["target"], "mode": m})
    if not acts:
        raise HTTPException(400, "Mindestens eine Aktion")
    vals = (name, int(d.get("sort") or 0), json.dumps(acts))
    if d.get("id"):
        q("UPDATE scenes SET name=?, sort=?, actions=? WHERE id=?", vals + (int(d["id"]),))
        return {"id": int(d["id"])}
    return {"id": qid("INSERT INTO scenes(name, sort, actions) VALUES(?,?,?)", vals)}


@app.delete("/api/scenes/{sid}")
def scene_delete(sid: int, request: Request):
    need(request, "admin")
    q("DELETE FROM scenes WHERE id=?", (sid,))
    return {"ok": True}


@app.post("/api/scenes/{sid}/run")
async def scene_run(sid: int, request: Request):
    need(request, "user")
    return {"errors": await asyncio.to_thread(engine.run_scene, sid)}


@app.get("/api/schedules")
def schedules():
    out = []
    for s in q("SELECT * FROM schedules ORDER BY time"):
        d = dict(s)
        d["target_label"] = engine.target_label(s["target"])
        try:
            t = engine.sched_time(s["time"], now_local().date())
            d["today"] = t.strftime("%H:%M") if t else None
        except Exception:
            d["today"] = None
        out.append(d)
    return out


@app.post("/api/schedules")
async def schedule_save(request: Request):
    need(request, "admin")
    d = await request.json()
    _target_ok(d.get("target"))
    act = str(d.get("action") or "")
    if d["target"].startswith("scene:"):
        d["action"] = act = "run"
    if act not in ("on", "off", "toggle", "run") and not (act.startswith("pos:") and act[4:].isdigit() and int(act[4:]) <= 100):
        raise HTTPException(400, "Aktion fehlt")
    try:
        engine.sched_time(d.get("time"), now_local().date())
    except Exception:
        raise HTTPException(400, "Zeit als HH:MM oder sunrise±Minuten / sunset±Minuten")
    vals = (d.get("name") or "", 1 if d.get("enabled", True) else 0, int(d.get("days", 127)), d["time"].strip(),
            d["target"], d["action"])
    if d.get("id"):
        q("UPDATE schedules SET name=?, enabled=?, days=?, time=?, target=?, action=?, last_run=NULL WHERE id=?",
          vals + (int(d["id"]),))
    else:
        qid("INSERT INTO schedules(name, enabled, days, time, target, action) VALUES(?,?,?,?,?,?)", vals)
    return {"ok": True}


@app.delete("/api/schedules/{sid}")
def schedule_delete(sid: int, request: Request):
    need(request, "admin")
    q("DELETE FROM schedules WHERE id=?", (sid,))
    return {"ok": True}


def hook_base(request):
    return (setting("public_url", "") or str(request.base_url)).rstrip("/")


@app.get("/api/rules")
def rules(request: Request):
    base = hook_base(request)
    out = []
    for r in q("SELECT * FROM rules ORDER BY id"):
        d = dict(r)
        d["trig"] = json.loads(r["trig"])
        d["action"] = json.loads(r["action"] or "[]")
        if d["trig"].get("type") == "webhook" and r["token"]:
            d["hook_url"] = f"{base}/hook/{r['token']}"
        out.append(d)
    return out


RULE_TYPES = ("power", "switch", "event", "online", "offline", "webhook", "finished", "started")


@app.post("/api/rules")
async def rule_save(request: Request):
    need(request, "admin")
    d = await request.json()
    trig, action = d.get("trig") or {}, d.get("action") or []
    if trig.get("type") not in RULE_TYPES:
        raise HTTPException(400, "Auslöser fehlt")
    if trig["type"] != "webhook" and not trig.get("dev"):
        raise HTTPException(400, "Gerät für den Auslöser fehlt")
    if trig["type"] == "power":
        try:
            trig["w"] = float(str(trig.get("w")).replace(",", "."))
        except Exception:
            raise HTTPException(400, "Leistungsschwelle fehlt")
    if not action:
        raise HTTPException(400, "Mindestens eine Aktion")
    for a in action:
        if a.get("type") == "switch":
            _target_ok(a.get("target"))
    vals = (d.get("name") or "Regel", 1 if d.get("enabled", True) else 0, json.dumps(trig), json.dumps(action))
    if d.get("id"):
        r = q("SELECT token FROM rules WHERE id=?", (int(d["id"]),), one=True)
        tok = (r["token"] if r and r["token"] else engine.new_token()) if trig["type"] == "webhook" else None
        q("UPDATE rules SET name=?, enabled=?, trig=?, action=?, active=0, token=? WHERE id=?",
          vals + (tok, int(d["id"])))
    else:
        tok = engine.new_token() if trig["type"] == "webhook" else None
        qid("INSERT INTO rules(name, enabled, trig, action, token) VALUES(?,?,?,?,?)", vals + (tok,))
    return {"ok": True}


@app.delete("/api/rules/{rid}")
def rule_delete(rid: int, request: Request):
    need(request, "admin")
    q("DELETE FROM rules WHERE id=?", (rid,))
    return {"ok": True}


@app.post("/api/rules/{rid}/run")
def rule_run(rid: int, request: Request):
    need(request, "admin")
    r = q("SELECT * FROM rules WHERE id=?", (rid,), one=True)
    if not r:
        raise HTTPException(404, "Regel nicht gefunden")
    engine.fire({**dict(r), "enabled": 1, "trig": json.dumps({"type": "test"})}, "Test")
    return {"ok": True}


@app.api_route("/hook/{token}", methods=["GET", "POST"])
def hook(token: str):
    """Ausloeser fuer Regeln vom Typ 'URL-Aufruf' (z. B. Aktion eines Tuer-/Fensterkontakts)."""
    r = engine.fire_webhook(token)
    if r is None:
        return PlainTextResponse("unbekannt", status_code=404)
    return PlainTextResponse("ok" if r else "ausserhalb des Zeitfensters")


# ======================= Meldungen =======================
@app.get("/api/alerts")
def alerts(limit: int = 200):
    rows = q("""SELECT a.*, COALESCE(NULLIF(d.name,''), a.dev) AS name FROM alerts a
                LEFT JOIN devices d ON d.id=a.dev ORDER BY a.id DESC LIMIT ?""", (limit,))
    return [dict(r) for r in rows]


@app.get("/api/alerts/wait")
async def alerts_wait(after: int = 0, timeout: int = 25):
    """Long-Polling fuer die App: wartet, bis es Meldungen mit id > after gibt (hoechstens timeout s)."""
    end = time.time() + max(0, min(timeout, 55))
    while True:
        rows = q("""SELECT a.*, COALESCE(NULLIF(d.name,''), a.dev) AS name FROM alerts a
                    LEFT JOIN devices d ON d.id=a.dev WHERE a.id>? ORDER BY a.id LIMIT 50""", (after,))
        if rows or time.time() >= end:
            last = q("SELECT MAX(id) AS m FROM alerts", one=True)["m"] or 0
            return {"alerts": [dict(r) for r in rows], "last": last}
        await asyncio.sleep(1)


@app.post("/api/alerts/ack")
async def alerts_ack(request: Request):
    need(request, "user")
    d = await request.json() if (await request.body()) else {}
    if d.get("id"):
        q("UPDATE alerts SET ack=1 WHERE id=?", (int(d["id"]),))
    else:
        q("UPDATE alerts SET ack=1 WHERE ack=0")
    return {"ok": True}


@app.delete("/api/alerts")
def alerts_clear(request: Request, id: int = 0):
    """Meldungen loeschen: eine (id) oder alle."""
    need(request, "user")
    if id:
        q("DELETE FROM alerts WHERE id=?", (id,))
    else:
        q("DELETE FROM alerts")
    return {"ok": True}


# ======================= Beschattung =======================
@app.get("/api/shade")
def shade_get():
    return shade.overview()


@app.post("/api/shade")
async def shade_save(request: Request):
    need(request, "admin")
    d = await request.json()
    try:
        rid = shade.save_rule(d)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    return {"id": rid}


@app.delete("/api/shade/{rid}")
def shade_delete(rid: int, request: Request):
    need(request, "admin")
    q("DELETE FROM shades WHERE id=?", (rid,))
    return {"ok": True}


@app.post("/api/shade/{rid}/pause")
async def shade_pause(rid: int, request: Request):
    need(request, "user")
    d = await request.json() if (await request.body()) else {}
    shade.pause_today(rid, d.get("on", True))
    await asyncio.to_thread(shade.step)
    return shade.overview()


@app.post("/api/shade/settings")
async def shade_settings(request: Request):
    need(request, "admin")
    d = await request.json()
    if "frost_c" in d:
        v = d["frost_c"]
        set_setting("frost_c", float(str(v).replace(",", ".")) if v not in (None, "") else None)
    if "weather_on" in d:
        set_setting("weather_on", bool(d["weather_on"]))
    await asyncio.to_thread(shade.fetch_weather)
    return shade.overview()


@app.post("/api/shade/check")
async def shade_check(request: Request):
    """Sofort pruefen (statt bis zur naechsten Minute zu warten)."""
    need(request, "user")
    await asyncio.to_thread(shade.fetch_weather)
    await asyncio.to_thread(shade.step)
    return shade.overview()


# ======================= Gen2+ (Original-Firmware) anbinden =======================
@app.post("/api/gen2/scan")
async def gen2_scan(request: Request):
    need(request, "admin")
    d = await request.json()
    try:
        return await asyncio.to_thread(gen2.scan, d.get("net", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/gen2/connect")
async def gen2_connect(request: Request):
    need(request, "admin")
    d = await request.json()
    try:
        return await asyncio.to_thread(gen2.connect, str(d.get("ip", "")).strip(), d.get("password") or "",
                                       str(d.get("broker") or "").strip(), bool(d.get("force")))
    except Exception as e:
        raise HTTPException(400, str(e))


# ======================= Einstellungen + Push =======================
@app.get("/api/settings")
def settings_get():
    p = core.push_cfg()
    return {"price_ct": setting("price_ct", 30.0), "push_kinds": setting("push_kinds", core.DEFAULT_PUSH),
            "push_all": core.PUSH_KINDS, "location": setting("location", {}) or {},
            "push": {"ntfy_url": p.get("ntfy_url", ""), "ntfy_token_set": bool(p.get("ntfy_token")),
                     "tg_chat": p.get("tg_chat", ""), "tg_token_set": bool(p.get("tg_token"))},
            "public_url": setting("public_url", ""),
            "portal": {"url": (setting("portal", {}) or {}).get("url", ""),
                       "token_set": bool((setting("portal", {}) or {}).get("token")), **portal.STATE}}


@app.post("/api/settings")
async def settings_set(request: Request):
    need(request, "admin")
    d = await request.json()
    try:
        if "price_ct" in d:
            set_setting("price_ct", max(0.0, float(str(d["price_ct"]).replace(",", "."))))
        if "location" in d:
            loc = d["location"] or {}
            f = lambda v: float(str(v).replace(",", ".")) if v not in (None, "") else None   # noqa: E731
            set_setting("location", {"lat": f(loc.get("lat")), "lon": f(loc.get("lon"))})
    except ValueError:
        raise HTTPException(400, "Zahl erwartet")
    if "push_kinds" in d:
        set_setting("push_kinds", [k for k in d["push_kinds"] if k in core.PUSH_KINDS])
    if "public_url" in d:
        set_setting("public_url", str(d["public_url"]).strip())
    if "portal" in d:
        p = dict(setting("portal", {}) or {})
        if "url" in d["portal"]:
            p["url"] = str(d["portal"]["url"]).strip()
        if d["portal"].get("token") is not None:
            p["token"] = str(d["portal"]["token"]).strip()
        set_setting("portal", p)
        portal.STATE.update(ok=None, err="")
    if "push" in d:
        p = core.push_cfg()
        for k in ("ntfy_url", "tg_chat"):
            if k in d["push"]:
                p[k] = str(d["push"][k]).strip()
        for k in ("ntfy_token", "tg_token"):
            if d["push"].get(k) is not None:
                p[k] = str(d["push"][k]).strip()
        set_setting("push", p)
    return settings_get()


@app.post("/api/push/test")
async def push_test(request: Request):
    need(request, "admin")
    errs = await asyncio.to_thread(core.push_test)
    if errs:
        raise HTTPException(502, "; ".join(errs))
    return {"ok": True}


# ======================= Firmware =======================
@app.get("/api/firmware")
def firmware():
    latest = engine.FW["hermit"]
    out = []
    for r in q("SELECT * FROM devices WHERE hidden=0 AND id NOT LIKE '%~%' ORDER BY COALESCE(NULLIF(name,''), id)"):
        d = dev_row(r, latest)
        out.append({k: d.get(k) for k in ("id", "name", "model", "ver", "online", "hermit", "fw_new")})
    return {"hermit_latest": latest, "checked": engine.FW["checked"], "devices": out}


@app.post("/api/firmware/check")
async def firmware_check(request: Request):
    need(request, "admin")
    await asyncio.to_thread(engine.fw_check, True)
    for r in q("SELECT * FROM devices WHERE online=1 AND hidden=0 AND id NOT LIKE '%~%'"):
        if is_hermit(r) or r["comp"] == "sensor:0":
            continue
        try:                                     # Shelly Gen2+: beim Geraet nachfragen
            res = await asyncio.to_thread(BUS.rpc, r["id"], "Shelly.CheckForUpdate", None, 10)
            engine.FW["gen2"][r["id"]] = ((res or {}).get("stable") or {}).get("version")
        except Exception:
            pass
    return firmware()


@app.post("/api/firmware/update")
async def firmware_update(request: Request):
    need(request, "admin")
    d = await request.json()
    res = {}
    for dev in d.get("devices") or []:
        try:
            await asyncio.to_thread(BUS.rpc, dev, "Shelly.Update", {"stage": "stable"}, 10)
            res[dev] = "gestartet"
        except Exception as e:
            res[dev] = f"Fehler: {e}"
    return {"result": res}


# ======================= Sicherungen =======================
@app.get("/api/backups")
def backups():
    rows = q("""SELECT b.id, b.dev, b.ts, b.model, b.ver, length(b.data) AS size,
                COALESCE(NULLIF(d.name,''), b.dev) AS name FROM backups b LEFT JOIN devices d ON d.id=b.dev
                ORDER BY b.ts DESC LIMIT 300""")
    return [dict(r) for r in rows]


@app.post("/api/backups")
async def backup_now(request: Request):
    need(request, "admin")
    d = await request.json() if (await request.body()) else {}
    devs = [d["dev"]] if d.get("dev") else [r["id"] for r in q("SELECT id FROM devices WHERE online=1 AND hidden=0 AND id NOT LIKE '%~%' AND COALESCE(comp,'')!='sensor:0'")]
    res = {}
    for dev in devs:
        try:
            res[dev] = await asyncio.to_thread(engine.backup_device, dev)
        except Exception as e:
            res[dev] = f"Fehler: {e}"
    return {"result": res}


@app.get("/api/backups/{bid}")
def backup_get(bid: int):
    b = q("SELECT * FROM backups WHERE id=?", (bid,), one=True)
    if not b:
        raise HTTPException(404, "Sicherung nicht gefunden")
    return Response(b["data"], media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="sicherung_{b["dev"]}_{int(b["ts"])}.json"'})


@app.post("/api/backups/{bid}/restore")
async def backup_restore(bid: int, request: Request):
    need(request, "admin")
    d = await request.json()
    dev = d.get("dev")
    get_dev(dev)
    try:
        log = await asyncio.to_thread(engine.restore_backup, bid, dev, bool(d.get("hooks", True)))
    except Exception as e:
        raise HTTPException(400, str(e))
    return {"log": log}


@app.delete("/api/backups/{bid}")
def backup_delete(bid: int, request: Request):
    need(request, "admin")
    q("DELETE FROM backups WHERE id=?", (bid,))
    return {"ok": True}


# ======================= Update der Cloud =======================
# Die App prueft version.json auf GitHub. Installiert wird vom Container "updater": die App legt
# data/update.request ab, der Updater holt den neuen Stand (git pull bzw. Archiv) und baut neu.
UPD = {"available": None, "last_check": 0, "error": ""}


def upd_check():
    try:
        with urllib.request.urlopen(UPDATE_URL + f"?t={int(time.time())}", timeout=15) as r:
            v = json.loads(r.read())["version"]
        UPD["available"] = v if engine.ver_tuple(v) > engine.ver_tuple(VERSION) else None
        UPD["error"] = ""
    except Exception as e:
        UPD["error"] = f"Prüfung fehlgeschlagen: {e}"
    UPD["last_check"] = time.time()
    return UPD["available"]


def updater_present():
    try:
        return time.time() - float((DATA / "updater.alive").read_text()) < 120
    except Exception:
        return False


def upd_request():
    if not updater_present():
        raise RuntimeError("Updater-Container läuft nicht (siehe cloud/README.md)")
    (DATA / "update.request").write_text(UPD["available"] or "manual")
    alert("cloud", "update", f"Cloud-Update auf {UPD['available'] or 'aktuellen Stand'} gestartet", push=False)


def updater_loop():
    time.sleep(60)
    last_day = None
    while True:
        try:
            mode, hour = setting("upd_mode", "install"), int(setting("upd_hour", 4))
            now = now_local()
            if mode != "off" and (time.time() - UPD["last_check"] > 6 * 3600 or
                                  (now.hour == hour and last_day != now.date())):
                if upd_check() and mode == "install" and now.hour == hour and last_day != now.date() \
                        and updater_present() and not (DATA / "update.request").exists():
                    upd_request()
                if now.hour == hour:
                    last_day = now.date()
        except Exception as e:
            print("Update:", e, flush=True)
        time.sleep(300)


@app.get("/api/update")
def update_info():
    def rd(n):
        try:
            return (DATA / n).read_text()[-3000:]
        except Exception:
            return ""
    return {"current": VERSION, "available": UPD["available"], "last_check": UPD["last_check"],
            "error": UPD["error"], "mode": setting("upd_mode", "install"), "hour": int(setting("upd_hour", 4)),
            "updater": updater_present(), "running": (DATA / "update.request").exists(), "log": rd("update.log"),
            "watchdog": rd("watchdog.log")}


@app.post("/api/update/check")
def update_check(request: Request):
    need(request, "admin")
    upd_check()
    return update_info()


@app.post("/api/update/install")
def update_install(request: Request):
    need(request, "admin")
    try:
        upd_request()
    except Exception as e:
        raise HTTPException(409, str(e))
    return update_info()


@app.post("/api/update/config")
async def update_config(request: Request):
    need(request, "admin")
    d = await request.json()
    if d.get("mode") in ("off", "check", "install"):
        set_setting("upd_mode", d["mode"])
    if "hour" in d and 0 <= int(d["hour"]) <= 23:
        set_setting("upd_hour", int(d["hour"]))
    return update_info()


@app.get("/api/info")
def info(request: Request):
    return {"version": VERSION, "mqtt": BUS.connected, "auth": users_exist(), "update": UPD["available"],
            "broker": os.environ.get("PUBLIC_BROKER", ""), "user": request.state.user,
            "price_ct": setting("price_ct", 30.0)}


@app.get("/api/info/public")
def info_public():
    return {"version": VERSION, "auth": users_exist()}
