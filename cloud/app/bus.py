# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D.Koch – Pagurus OS
"""MQTT-Anbindung (Gen2-Format) und Geraetezustand."""
import itertools
import json
import os
import threading
import time

import paho.mqtt.client as mqtt

import blu
import engine
import shade
import core
from core import OFFLINE_ALERT_AFTER, alert, dev_name, now_local, q, today

MQTT_HOST = os.environ.get("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
SRC = "hermit-cloud"
MAIN_COMPS = ("switch:", "cct:", "light:", "cover:", "climate:", "pm1:")
METER_COMPS = ("pm1:",)                   # reine Messgeraete (Plus PM Mini, Mini PM G3): kein Schalten


# Geraete mit mehreren Schaltkanaelen (Shelly 2.5): Kanal 2 wird als eigene Zeile "<id>~1" gefuehrt –
# mit eigener Leistung, Energie, Raum, Regeln. Das Geraet selbst (MQTT-Topic) bleibt <id>.
def row_id(dev, comp):
    kind, _, cid = comp.partition(":")
    return f"{dev}~{cid}" if comp.startswith(MAIN_COMPS) and cid.isdigit() and int(cid) > 0 else dev


SENSOR_COMPS = ("temperature:", "humidity:", "illuminance:")
POLL_S = 30

# Gen1-Batteriefuehler mit Original-Firmware (Shelly Door/Window 1/2, H&T): melden per MQTT im Gen1-Format
# unter shellies/<id>/sensor/<wert>. Uebernommen werden nur Temperatur, Feuchte und Helligkeit (plus Batterie).
# Die Geraete schlafen zwischen den Meldungen – kein RPC, keine Offline-Meldung, Zeile mit comp "sensor:0".
GEN1_SENSOR = "sensor:0"
GEN1_MODELS = {"shellydw2": "SHDW-2", "shellydw": "SHDW-1", "shellyht": "SHHT-1"}


def _num(payload):
    try:
        return float(payload.decode().strip())
    except Exception:
        return None


def gen1_message(topic, payload, retained=False):
    """shellies/<id>/sensor/<name> und shellies/announce."""
    parts = topic.split("/")
    if parts[1:2] == ["announce"]:
        try:
            d = json.loads(payload)
        except Exception:
            return
        dev = d.get("id") or ""
        if dev.split("-")[0] not in GEN1_MODELS:
            return
        set_info(dev, {"model": d.get("model") or GEN1_MODELS[dev.split("-")[0]], "mac": d.get("mac"),
                       "ip": d.get("ip"), "ver": d.get("fw_ver"), "gen": 1}, live=False)
        _gen1_row(dev)
        return
    if len(parts) != 4 or parts[2] != "sensor" or not payload:
        return
    dev, name = parts[1], parts[3]
    if dev.split("-")[0] not in GEN1_MODELS:
        return
    v = _num(payload)
    if v is None:
        return
    st = {}
    if name == "temperature":
        st = {"temperature": {"tC": v}}
        if not retained:
            shade.sensor(dev, "temperature:0", {"tC": v})
    elif name == "lux":
        st = {"lux": v}
        if not retained:
            shade.sensor(dev, "illuminance:0", {"lux": v})
    elif name == "humidity":
        st = {"humidity": {"rh": v}}
        if not retained:
            shade.sensor(dev, "humidity:0", {"rh": v})
    elif name == "battery":
        st = {"battery": v}
    else:
        return                                   # Kontakt, Neigung, Vibration usw. werden nicht genutzt
    _gen1_row(dev)
    st["sleeping"] = True
    set_status(dev, GEN1_SENSOR, st, merge=True, live=not retained)


def _gen1_row(dev):
    ensure(dev)
    q("UPDATE devices SET gen=1, comp=?, model=COALESCE(model, ?) WHERE id=?",
      (GEN1_SENSOR, GEN1_MODELS.get(dev.split("-")[0]), dev))


def is_gen1_sensor(dev):
    r = q("SELECT comp FROM devices WHERE id=?", (dev,), one=True)
    return bool(r and r["comp"] == GEN1_SENSOR)


def real_id(row):
    return row.split("~", 1)[0]


def channel_rows(dev):
    return [r["id"] for r in q("SELECT id FROM devices WHERE id LIKE ?", (dev + "~%",))]


class Bus:
    def __init__(self):
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{SRC}-{os.getpid()}")
        if MQTT_USER:
            self.c.username_pw_set(MQTT_USER, MQTT_PASS)
        self.c.on_connect = self.on_connect
        self.c.on_message = self.on_message
        self.connected = False
        self.ids = itertools.count(1)
        self.wait = {}
        self.topics = {}                          # Geraet -> gesehene Topics (zum Loeschen gespeicherter Nachrichten)
        self.poll = set()                         # Geraete ohne eigene Statusmeldungen: Cloud fragt ab
        self.ntf_checked = set()

    def start(self):
        self.c.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        self.c.loop_start()
        threading.Thread(target=self.poll_loop, daemon=True).start()

    def on_connect(self, c, userdata, flags, rc, props=None):
        self.connected = not rc.is_failure
        if self.connected:
            c.subscribe([("+/online", 0), ("+/info", 0), ("+/status/+", 0), ("+/events/rpc", 0),
                         (f"{SRC}/rpc", 0), ("shellies/+/sensor/+", 0), ("shellies/announce", 0)])

    def on_message(self, c, userdata, msg):
        try:
            self.handle(msg.topic, msg.payload, msg.retain)
        except Exception as e:
            print("Fehler bei", msg.topic, e, flush=True)

    def handle(self, topic, payload, retained=False):
        # Gespeicherte (retained) Nachrichten liefert der Broker beim Verbinden der Cloud erneut aus –
        # sie aktualisieren die Daten, zaehlen aber nicht als Lebenszeichen. Massgeblich ist dann /online.
        if topic == f"{SRC}/rpc":
            d = json.loads(payload)
            w = self.wait.get(d.get("id"))
            if w:
                w[1].append(d)
                w[0].set()
            return
        if topic.startswith("shellies/"):
            parts = topic.split("/")
            if len(parts) > 2:
                self.topics.setdefault(parts[1], set()).add(topic)
                if retained and not known(parts[1]):
                    return
            gen1_message(topic, payload, retained)
            return
        dev, _, rest = topic.partition("/")
        if not dev or dev == SRC:
            return
        if not payload:
            return                                # leere Nachricht = geloeschte gespeicherte Nachricht (auch unser Echo)
        self.topics.setdefault(dev, set()).add(topic)
        # Gespeicherte Nachricht eines unbekannten (z. B. geloeschten) Geraets legt es nicht neu an –
        # nur ein Geraet, das wirklich sendet.
        if retained and not known(dev):
            return
        if rest == "online":
            on = payload.decode().strip() == "true"
            if not on and not known(dev):
                return                            # Offline-Meldung (Last Will) eines unbekannten Geraets
            seen(dev, online=on)
            for v in channel_rows(dev):
                seen(v, online=on)
            if on and not q("SELECT info FROM devices WHERE id=? AND info!='{}'", (dev,), one=True):
                threading.Thread(target=self.fetch_info, args=(dev,), daemon=True).start()
            if on:
                threading.Thread(target=self.after_online, args=(dev,), daemon=True).start()
            return
        if not payload:
            return
        d = json.loads(payload)
        live = not retained
        if rest == "info":
            set_info(dev, d, live=live)
            for v in channel_rows(dev):
                set_info(v, {k: d.get(k) for k in ("model", "app", "ver", "mac", "gen", "ip")}, live=live)
        elif rest.startswith("status/"):
            comp = rest[7:]
            if comp == "wifi" and isinstance(d, dict) and d.get("sta_ip"):
                set_ip(dev, d["sta_ip"])
            if comp.startswith(MAIN_COMPS):
                set_status(self.chan_row(dev, comp), comp, d, live=live)
            elif comp.startswith(SENSOR_COMPS):
                shade.sensor(dev, comp, d)
                if live:
                    seen(dev)
            elif comp.startswith("bthome"):
                blu.status(dev, comp, d, live=live)
                if live:
                    seen(dev)
            elif live:
                seen(dev)
        elif rest == "events/rpc" and live:
            m = d.get("method")
            p = d.get("params") or {}
            if m == "NotifyEvent":
                for e in p.get("events", []):
                    on_event(dev, e)
            elif m in ("NotifyStatus", "NotifyFullStatus"):
                for k, v in p.items():
                    if k == "wifi" and isinstance(v, dict) and v.get("sta_ip"):
                        set_ip(dev, v["sta_ip"])
                    if isinstance(v, dict) and k.startswith(MAIN_COMPS):
                        set_status(row_id(dev, k), k, v, merge=True)
                    elif isinstance(v, dict) and k.startswith(SENSOR_COMPS):
                        shade.sensor(dev, k, v)
                    elif isinstance(v, dict) and k.startswith("bthome"):
                        blu.status(dev, k, v)
                seen(dev)

    def forget(self, dev):
        """Gespeicherte (retained) Nachrichten eines geloeschten Geraets beim Broker entfernen."""
        topics = set(self.topics.pop(dev, set()))
        topics |= {f"{dev}/online", f"{dev}/info", f"{dev}/status/sys", f"{dev}/status/wifi",
                   f"{dev}/status/mqtt", f"{dev}/status/switch:0", f"{dev}/status/switch:1",
                   f"{dev}/status/input:0", f"{dev}/status/cover:0", f"{dev}/status/light:0", f"{dev}/status/cct:0"}
        if self.connected:
            for t in topics:
                self.c.publish(t, b"", retain=True)
        return len(topics)

    def chan_row(self, dev, comp):
        rid = row_id(dev, comp)
        if rid != dev and not q("SELECT 1 FROM devices WHERE id=?", (rid,), one=True):
            ensure(rid)                          # neuer Kanal: Grunddaten vom Geraet uebernehmen
            base = q("SELECT model, app, ver, mac, gen, ip, room FROM devices WHERE id=?", (dev,), one=True)
            if base:
                q("UPDATE devices SET model=?, app=?, ver=?, mac=?, gen=?, ip=?, room=? WHERE id=?",
                  (base["model"], base["app"], base["ver"], base["mac"], base["gen"], base["ip"], base["room"], rid))
        return rid

    def fetch_status(self, dev):
        """Vollstaendigen Status per RPC holen – fuer Geraete, die keinen Status per MQTT senden."""
        st = self.rpc(dev, "Shelly.GetStatus")
        for k, v in (st or {}).items():
            if isinstance(v, dict) and k.startswith(MAIN_COMPS):
                set_status(self.chan_row(dev, k), k, v, merge=True)
            elif isinstance(v, dict) and k.startswith(SENSOR_COMPS):
                shade.sensor(dev, k, v)

    def after_online(self, dev):
        """Nach dem Verbinden: fehlenden Status holen und pruefen, ob das Geraet Aenderungen selbst meldet.
        Meldet es nichts (Statusmeldungen und RPC-Benachrichtigungen aus), fragt die Cloud regelmaessig ab."""
        time.sleep(1)
        try:
            r = q("SELECT comp, status, gen FROM devices WHERE id=?", (dev,), one=True)
            if not r or (r["gen"] or 2) < 2:
                return
            try:                                   # IP fuer Anzeige und Wandtafel-Bindung (GetDeviceInfo hat keine)
                w = self.rpc(dev, "WiFi.GetStatus")
                if w.get("sta_ip"):
                    set_ip(dev, w["sta_ip"])
            except Exception:
                pass
            st = json.loads(r["status"] or "{}")
            if not (r["comp"] or "").startswith(MAIN_COMPS) or not any(k in st for k in ("output", "state", "mode", "apower")):
                self.fetch_status(dev)
            if dev in self.ntf_checked:
                return
            c = self.rpc(dev, "MQTT.GetConfig")
            self.ntf_checked.add(dev)
            if c.get("status_ntf") is False and c.get("rpc_ntf") is False:
                if dev not in self.poll:
                    alert(dev, "info", f"{dev_name(dev)} meldet Änderungen nicht von selbst – die Cloud fragt alle "
                          f"{POLL_S} s ab. Besser am Gerät unter MQTT „RPC status notifications“ einschalten.", push=False)
                self.poll.add(dev)
            else:
                self.poll.discard(dev)
        except Exception:
            pass

    def poll_loop(self):
        while True:
            time.sleep(POLL_S)
            for dev in list(self.poll):
                try:
                    if q("SELECT 1 FROM devices WHERE id=? AND online=1", (dev,), one=True):
                        self.fetch_status(dev)
                except Exception:
                    pass

    def fetch_info(self, dev):
        try:
            set_info(dev, self.rpc(dev, "Shelly.GetDeviceInfo"))
        except Exception:
            pass

    def rpc(self, dev, method, params=None, timeout=6):
        if not self.connected:
            raise RuntimeError("Keine Verbindung zum MQTT-Broker")
        if is_gen1_sensor(real_id(dev)):
            raise RuntimeError(f"{dev_name(dev)}: Batteriefühler – nur Messwerte, keine Befehle")
        if method.startswith("Climate."):          # Klima-ESP wartet auf die Anlage (UART), Midea bis ~4 s
            timeout = max(timeout, 15)
        rid = next(self.ids)
        ev, box = threading.Event(), []
        self.wait[rid] = (ev, box)
        try:
            req = {"id": rid, "src": SRC, "method": method}
            if params is not None:
                req["params"] = params
            self.c.publish(f"{real_id(dev)}/rpc", json.dumps(req, ensure_ascii=False).encode())  # Shelly-JSON versteht nur \u00XX-Escapes
            if not ev.wait(timeout):
                raise TimeoutError(f"{dev_name(dev)} antwortet nicht")
            r = box[0]
            if "error" in r:
                raise RuntimeError(r["error"].get("message") or str(r["error"]))
            return r.get("result")
        finally:
            self.wait.pop(rid, None)

    # ---- Schalten (fuer Oberflaeche, Zeitplaene, Regeln) ----
    def switch(self, dev, on=None, brightness=None, cover=None, pos=None):
        r = q("SELECT comp, status FROM devices WHERE id=?", (dev,), one=True)
        if not r:
            raise RuntimeError(f"Unbekanntes Gerät {dev}")
        if json.loads(r["status"] or "{}").get("meter_only"):
            raise RuntimeError(f"{dev_name(dev)}: Messfirmware – nicht schaltbar")
        comp = r["comp"] or "switch:0"
        if comp.startswith(METER_COMPS):
            raise RuntimeError(f"{dev_name(dev)}: Messgerät – nicht schaltbar")
        kind, cid = comp.split(":")
        if kind == "cover":                       # Rollladen: an = oeffnen, aus = schliessen
            st = json.loads(r["status"] or "{}")
            if pos is not None:
                res = self.rpc(dev, "Cover.GoToPosition", {"id": int(cid), "pos": max(0, min(100, int(round(float(pos)))))})
            else:
                act = cover or ("open" if on is True else "close" if on is False else
                                "stop" if st.get("state") in ("opening", "closing", "calibrating") else
                                "close" if st.get("last_direction") == "open" else "open")
                res = self.rpc(dev, {"open": "Cover.Open", "close": "Cover.Close", "stop": "Cover.Stop"}[act], {"id": int(cid)})
            try:
                set_status(dev, comp, self.rpc(dev, "Cover.GetStatus", {"id": int(cid)}), merge=True)
            except Exception:
                pass
            return res
        m = {"switch": "Switch", "cct": "CCT", "light": "Light", "climate": "Climate"}.get(kind, "Switch")
        if brightness is not None and kind in ("light", "cct"):
            b = max(0, min(100, int(round(float(brightness)))))
            p = {"id": int(cid), "brightness": b} if b > 0 else {"id": int(cid), "on": False}
            if b > 0:
                p["on"] = True
            res = self.rpc(dev, f"{m}.Set", p)
        elif on is None:
            res = self.rpc(dev, f"{m}.Toggle", {"id": int(cid)})
        else:
            res = self.rpc(dev, f"{m}.Set", {"id": int(cid), "on": bool(on)})
        try:
            st = self.rpc(dev, f"{m}.GetStatus", {"id": int(cid)})
            set_status(dev, comp, st, merge=True)
        except Exception:
            pass
        return res


BUS = Bus()


# ======================= Geraetezustand =======================
def known(dev):
    return bool(q("SELECT 1 FROM devices WHERE id=?", (dev,), one=True))


def ensure(dev):
    if dev.startswith("pagurus-"):
        rename_legacy(dev)
    q("INSERT OR IGNORE INTO devices(id, first_seen) VALUES(?,?)", (dev, time.time()))


_RENAMED = set()


def rename_legacy(dev):
    """Geraet meldet sich als pagurus-…, ist aber noch als hermit-… bekannt (neu geflasht nach der Umbenennung):
    vorhandenen Eintrag samt Kanaelen, Verlauf, Regeln usw. auf die neue ID umschreiben statt neu anzulegen."""
    base = dev.split("~")[0]
    if base in _RENAMED:
        return
    _RENAMED.add(base)
    old = "hermit-" + base[len("pagurus-"):]
    if q("SELECT 1 FROM devices WHERE id=?", (base,), one=True) or \
            not q("SELECT 1 FROM devices WHERE id=?", (old,), one=True):
        return
    n = core.rename_everywhere(old, base)
    print(f"Geraet {old} heisst jetzt {base} – {n} Eintraege uebernommen", flush=True)


def seen(dev, online=None):
    """Lebenszeichen bzw. Online-Meldung. Offline wird sofort angezeigt, aber erst nach
    OFFLINE_ALERT_AFTER gemeldet (siehe check_offline) – kurze WLAN-Aussetzer erzeugen keine Meldung."""
    ensure(dev)
    r = q("SELECT online, off_alerted FROM devices WHERE id=?", (dev,), one=True)
    if online is False:
        if r["online"]:
            q("UPDATE devices SET online=0, off_since=?, off_alerted=0 WHERE id=?", (time.time(), dev))
        return
    if not r["online"]:
        q("UPDATE devices SET online=1, last_seen=?, off_since=NULL, off_alerted=0 WHERE id=?", (time.time(), dev))
        if r["off_alerted"]:                       # nur wenn vorher wirklich „offline“ gemeldet wurde
            alert(dev, "online", f"{dev_name(dev)} ist wieder online")
            engine.on_online(dev, True)
        return
    q("UPDATE devices SET last_seen=? WHERE id=?", (time.time(), dev))


def check_offline():
    """Vom Watchdog aufgerufen: Geraete, die laenger als OFFLINE_ALERT_AFTER weg sind, melden."""
    lim = time.time() - OFFLINE_ALERT_AFTER
    for r in q("SELECT id, hidden FROM devices WHERE online=0 AND off_alerted=0 AND off_since IS NOT NULL AND off_since<?",
               (lim,)):
        q("UPDATE devices SET off_alerted=1 WHERE id=?", (r["id"],))
        if not r["hidden"]:
            alert(r["id"], "offline", f"{dev_name(r['id'])} ist offline")
        engine.on_online(r["id"], False)


def set_info(dev, d, live=True):
    ensure(dev)
    old = q("SELECT info FROM devices WHERE id=?", (dev,), one=True)
    merged = {**json.loads(old["info"] or "{}"), **{k: v for k, v in d.items() if v is not None}}
    q("""UPDATE devices SET info=?, model=COALESCE(?, model), app=COALESCE(?, app), ver=COALESCE(?, ver),
         mac=COALESCE(?, mac), gen=COALESCE(?, gen), ip=COALESCE(?, ip),
         name=COALESCE(NULLIF(name,''), ?, name) WHERE id=?""",
      (json.dumps(merged), d.get("model"), d.get("app"), d.get("ver"), d.get("mac"), d.get("gen"),
       d.get("ip"), d.get("name"), dev))
    if live:
        seen(dev)


def set_ip(dev, ip):
    """IP merken (auch fuer weitere Kanaele desselben Geraets)."""
    q("UPDATE devices SET ip=? WHERE (id=? OR id LIKE ?) AND COALESCE(ip,'')!=?", (ip, dev, dev + "~%", ip))


def set_status(dev, comp, st, merge=False, live=True):
    ensure(dev)
    r = q("SELECT status, comp, last_total FROM devices WHERE id=?", (dev,), one=True)
    old = json.loads(r["status"] or "{}") if r["comp"] in (None, comp) else {}
    new = {**old, **st} if merge else st
    q("UPDATE devices SET status=?, comp=? WHERE id=?", (json.dumps(new), comp, dev))
    if not live:
        return                                    # alter Stand vom Broker: nichts verbuchen
    seen(dev)
    now = int(time.time())
    if "apower" in st:
        w = float(st["apower"])
        q("""INSERT INTO power(dev, ts, w, wmax) VALUES(?,?,?,?)
             ON CONFLICT(dev, ts) DO UPDATE SET w=excluded.w, wmax=MAX(COALESCE(wmax, 0), excluded.wmax)""",
          (dev, now // 60 * 60, w, w))
    tot = (st.get("aenergy") or {}).get("total")
    if tot is not None:
        tot = float(tot)
        last = r["last_total"]
        if last is not None and tot > last:
            q("""INSERT INTO energy(dev, day, wh) VALUES(?,?,?)
                 ON CONFLICT(dev, day) DO UPDATE SET wh = wh + excluded.wh""", (dev, today(), tot - last))
            q("""INSERT INTO energy_h(dev, hour, wh) VALUES(?,?,?)
                 ON CONFLICT(dev, hour) DO UPDATE SET wh = wh + excluded.wh""",
              (dev, now_local().strftime("%Y-%m-%d %H"), tot - last))
        q("UPDATE devices SET last_total=? WHERE id=?", (tot, dev))   # kleiner = Zaehler zurueckgesetzt
    engine.on_status(dev, comp, new, old)
    shade.on_status(dev, comp, new, old)


EVENT_TEXT = {
    "overpower": ("overpower", "Überlast – abgeschaltet"),
    "obstruction": ("obstruction", "Rollladen: Hindernis erkannt – angehalten"),
    "calibration_failed": ("calibration", "Rollladen: Kalibrierung fehlgeschlagen (Endlage nicht erkannt)"),
    "overtemperature": ("overtemp", "Übertemperatur – abgeschaltet"),
    "overtemp": ("overtemp", "Übertemperatur – abgeschaltet"),
    "reset": ("reset", "Schutzabschaltung am Gerät zurückgesetzt"),
    "overvoltage": ("overvoltage", "Überspannung"),
}


def on_event(dev, e):
    seen(dev)
    if e.get("component", "").startswith("bthomesensor:"):
        blu.event(dev, e["component"], e.get("event", ""))
        return
    comp = e.get("component", "")
    ev = e.get("event", "")
    if comp.startswith("input:") and ev in ("single_push", "double_push", "triple_push", "long_push"):
        r = q("SELECT status FROM devices WHERE id=?", (dev,), one=True)
        if r:                                     # letzte Taste fuer die Karte (Komponente der Zeile bleibt)
            st = json.loads(r["status"] or "{}")
            names = {"single_push": "kurz", "double_push": "doppelt", "triple_push": "dreifach", "long_push": "lang"}
            st.update(button=f"Taste {int(comp.split(':')[1]) + 1} {names[ev]}", button_ts=time.time())
            q("UPDATE devices SET status=? WHERE id=?", (json.dumps(st), dev))
    dev = row_id(dev, comp)
    if ev in EVENT_TEXT:
        kind, text = EVENT_TEXT[ev]
        alert(dev, kind, f"{dev_name(dev)}: {text}")
    engine.on_event(dev, e.get("component", ""), ev)
