# Pagurus Cloud

Kleine Heim-Cloud für Pagurus-OS-Geräte (und Shelly Plus/Pro Gen2/Gen3). Läuft zu Hause als
Docker-Paket. Sie ist **optional**: Die Geräte arbeiten ohne sie genauso, die Cloud liest nur mit.

**Funktionen**
- **Geräte nach Räumen**, Schalten einzeln oder „alle an/aus“ je Raum, Energie und Kosten von heute
- **Wäsche:** Waschmaschine und Trockner mit Fertig-Erkennung – läuft/fertig, Restzeit aus früheren Läufen,
  Energie und Kosten je Lauf, Push „fertig“ und Erinnerung, wenn nicht ausgeräumt wird. Dazu Spülmaschine
  und beliebige Geräte (z. B. Akkuladegerät) mit Fertig-Meldung
- **Kühlgeräte:** Kompressor-Zyklen, Laufanteil, Kosten pro Jahr; Warnung bei Dauerlauf (Tür offen?),
  Stillstand und auffälligem Verbrauch
- **Energie:** Leistungsverlauf 6 h bis 30 Tage mit Spitzenwerten und Zoom, Energie pro Tag/Monat mit Kosten,
  Verbrauch je Gerät, **Grundlast/Standby** mit Kosten pro Jahr, **CSV-Export** für Excel
- **Beschattung:** Rollläden nach Sonnenstand und Temperatur – je Fassade Himmelsrichtung und Sonnenhöhe,
  Temperatur von Fühlern (Shelly H&T, Add-on …) oder Wetter (Open-Meteo, ohne Schlüssel), optional Innentemperatur,
  Höchstwert-Vorhersage und Sonneneinstrahlung, Verzögerung, Zeitfenster, Frostschutz. Fährt nur nach unten,
  öffnet danach nur, wenn der Rollladen noch dort steht, und lässt von Hand bewegte Rollläden in Ruhe
- **Klima-Raumregelung:** Solltemperatur am Innengerät nach externem Raumfühler (BLU, H&T, Wall Display,
  DHT22 am Gerät, Mittelwert mehrerer) nachführen – das Gerät misst unter der Decke zu warm; PI-Regler lernt die
  Abweichung, schaltet bei Erreichen ab, übernimmt Werte von der Fernbedienung; mehrere Anlagen auf einer Ebene
  teilen sich die Fühler
- **Parallel zur Shelly Cloud:** Shelly Gen2/Gen3/Gen4 mit Original-Firmware im Netz suchen und mit einem Klick
  verbinden – App, Szenen und Shelly Cloud laufen weiter
- **Automatik:** Zeitpläne (Uhrzeit oder Sonnenauf-/untergang ± Minuten, Wochentage, Gerät oder Raum) und
  **Regeln** (Wenn Leistung/Schalter/Ereignis/offline/fertig/URL-Aufruf → schalten, verzögert, automatisch
  wieder aus, Push), mit Zeitfenster; Rollläden: öffnen, schließen oder auf Position
- **Heizung:** Warmwasser (Ölkessel mit Shelly-Logik-Script), Zirkulationspumpe und Raumheizer (Heizlüfter,
  Konvektor) mit Live-Werten, Boost und allen Einstellungen; Warmwasser-Verlauf mit Brennerstarts und Öl je Tag; erkennt Duschen und Baden am Speicherabfall und zeigt ein Wochenprofil;
  Meldung bei Störung. Die Regelung bleibt auf den Shellys
- **Scripte:** Shelly-Scripte aller Gen2+-Geräte mit Version anzeigen, in der Cloud bearbeiten und übertragen,
  mit Sicherung der vorigen Fassung und Bibliothek zum Verteilen auf mehrere Geräte
- **Meldungen** mit **Push** über ntfy oder Telegram
- **Firmware-Übersicht** mit Update einzeln oder für alle Geräte
- **Sicherung** der Geräte-Einstellungen (nachts automatisch) und Zurückspielen, auch auf ein Ersatzgerät
- **Benutzer** mit Rollen (Administrator, Benutzer, Betrachter)
- **Handy:** als App auf dem Startbildschirm (PWA)
- **Selbst-Update** aus diesem Repo

![Wäsche](../docs/img/cloud-waesche.png)

```
Pagurus-Geräte ──MQTT (Gen2-Format)──►  Mosquitto :1883  ◄──►  Pagurus Cloud :8080  ──► Browser
```

## Installation auf Proxmox

Am einfachsten ein Debian-12-LXC-Container (1 CPU, 512 MB RAM, 4 GB Disk). Für Docker im LXC unter
*Optionen → Features* **Nesting** einschalten.

```bash
# im Container
apt update && apt install -y curl git
curl -fsSL https://get.docker.com | sh        # Docker inkl. „docker compose“
git clone https://github.com/oeltensack/pagurus-os.git
cd pagurus-os/cloud
cp .env.example .env
nano .env          # MQTT_USER, MQTT_PASS, CLOUD_PASSWORD, PUBLIC_BROKER (IP des Containers)
docker compose up -d
```

Weboberfläche: `http://<IP-des-Containers>:8080`

Alternativ geht jeder Rechner mit Docker (VM, Raspberry Pi, NAS).

## Geräte verbinden

**Pagurus OS** (ab 1.12.0): Geräteoberfläche → *System* → *Cloud / MQTT*
- Haken „MQTT einschalten“
- Server: `<IP-des-Containers>:1883`
- Benutzer/Passwort: `MQTT_USER` / `MQTT_PASS` aus der `.env`
- Topic-Präfix leer lassen (= Geräte-ID)

**Shelly Gen2/Gen3/Gen4 mit Original-Firmware** (Plus, Pro, Gen3, Gen4 – auch neben der Shelly Cloud):
am einfachsten in der Cloud unter *Einstellungen → Shelly Gen2+ anbinden* das Netz durchsuchen und
„Verbinden“ klicken. Die Cloud trägt sich am Gerät als MQTT-Server ein (bei Gerätepasswort dieses angeben)
und startet es neu. Shelly-App und Shelly Cloud laufen weiter – nur ein anderer MQTT-Server geht verloren
(ein Gerät kann nur einen), darauf weist die Cloud vorher hin.

Von Hand geht es auch: *Einstellungen → MQTT*, gleicher Server und Zugang, Client-ID und Präfix = Geräte-ID,
„RPC status notifications over MQTT“ und „Generic status update over MQTT“ einschalten.

**Shelly Door/Window 2 und H&T (Gen1, Original-Firmware)** als Temperatur- und Helligkeitsfühler bzw.
Temperatur-/Feuchtefühler: Taster am Gerät kurz drücken (dann bleibt es einige Minuten wach), sofort unter
*Einstellungen → Shelly Gen2+ anbinden* suchen und „Verbinden“. Die Cloud schaltet am Gerät MQTT ein
(Server, Zugang, ID) – bei Gen1 geht dabei die Shelly Cloud aus. Übernommen werden nur Temperatur,
Helligkeit (Lux), Feuchte und Batterie; Kontakt, Neigung und Vibration werden ignoriert. Die Fühler stehen
dann unter *Beschattung → Fühler* und als Temperaturquelle in den Beschattungsregeln.

Von Hand: Geräteoberfläche → *Internet & Security → Advanced – Developer Settings* → MQTT einschalten,
Server `<IP>:1883`, Benutzer/Passwort aus der `.env`, Client-ID unverändert lassen.

Damit die Werte regelmäßig kommen, am Door/Window 2 unter *Settings* eine **Aufwachzeit** einstellen
(z. B. 30–60 min) – sonst meldet er nur bei Öffnen/Schließen. Die Beschattung nimmt Fühlerwerte bis 6 h
Alter; längere Abstände gelten als „Fühler-Wert zu alt“. Jede Meldung kostet Batterie.

**Shelly BLU (Bluetooth)** über Gen2+/Gen3-Shellys als Gateway, ohne Shelly Cloud: Die BLU-Geräte müssen
auf dem Shelly selbst angelegt sein (Shelly-App bzw. Geräteoberfläche → *Bluetooth / BTHome-Geräte* →
Gerät hinzufügen), und der Shelly muss per MQTT an der Cloud hängen. Die Cloud liest die Zuordnung einmal
vom Shelly und legt jedes BLU-Gerät als eigenes Gerät `blu-<adresse>` an – hören es mehrere Shellys, bleibt
es eines. Übernommen werden Temperatur, Feuchte, Helligkeit (auch für die Beschattung), Fenster/Tür,
Bewegung, Neigung, Wasser, Batterie und Tasten. Für Regeln („Ereignis am Gerät“): `open` / `closed`,
`motion` / `no_motion`, `single_push` / `double_push` / `long_push`, bei mehreren Tasten `button:2.single_push`.

Mehrkanal-Geräte (Plus 2PM, Pro 4PM, Pro Dual Cover, Shelly 2.5 mit Pagurus OS) erscheinen je Kanal als
eigenes Gerät. Temperatur-, Feuchte- und Helligkeitsfühler stehen unter *Beschattung → Fühler*.

Die Geräte erscheinen automatisch, sobald sie verbunden sind.

## Beschattung

Unter *Einstellungen* den **Standort** eintragen (Breiten-/Längengrad), dann unter *Beschattung* je Fassade
eine Regel anlegen:

| Einstellung | Bedeutung |
|---|---|
| Fassade | Himmelsrichtung der Fenster (Süd = 180°) und Bereich ± Grad, in dem die Sonne hereinscheint |
| Sonnenhöhe | z. B. ab 10° (tiefer verdecken oft Nachbarhäuser) |
| Beschatten auf | Position in % offen (0 = zu) – Rollläden ohne Positionssteuerung fahren ganz zu |
| Temperatur | Fühler oder Wetter; an ab … °C, aus unter … °C (Abstand verhindert Hin und Her) |
| Innentemperatur, Höchstwert heute, Einstrahlung | zusätzliche Bedingungen, leer = egal |
| Lichtsensor | Helligkeit vor Ort (BLU Motion, BLU Door/Window …) ≥ Schwelle in lx; ersetzt die Einstrahlung aus dem Wetter. Meldet der Sensor 30 min nichts, gilt wieder die Einstrahlung |
| Verzögerung | so lange müssen die Bedingungen anhalten (Standard 5 min an, 15 min aus) |
| Danach | ganz öffnen, vorige Position oder stehen lassen |

Die Regel fährt nur nach unten (ein Rollladen, der schon weiter zu ist, bleibt) und öffnet danach nur,
wenn er noch auf der Beschattungsposition steht. Wer während der Beschattung von Hand fährt – am Taster,
in der Shelly-App oder in der Cloud –, hat bis zum Ende der Beschattung Vorrang. „Heute pausieren“ setzt
eine Regel bis Mitternacht aus. **Frostschutz:** unter der eingestellten Außentemperatur bewegen Regeln und
Zeitpläne keine Rollläden (festgefrorener Behang).

Morgens öffnen und abends schließen geht über *Automatik → Zeitpläne* (Sonnenaufgang/-untergang ± Minuten,
Aktion „Rollladen auf Position“, „öffnen“ oder „schließen“).

## Wandtafel (Shelly Wall Display)

Eigene Bedienseite mit großen Kacheln für das Shelly Wall Display oder ein Tablet.

1. Cloud → Einstellungen → **Wandtafeln** → „Neue Wandtafel“: Name, Kacheln (Geräte, Klimaanlagen, Rollläden,
   Fühler, Szenen) und ob geschaltet werden darf
2. Am Wall Display unter **Einstellungen → Home Assistant** die Adresse eintragen:
   - mit **Gerät** (das Wall Display aus der Liste oder seine feste IP) genügt die kurze Adresse der Cloud,
     z. B. `http://192.168.4.102:8080` – die Cloud erkennt das Display an seiner IP und zeigt gleich die Tafel
   - ohne Gerät die lange Adresse mit Schlüssel (`http://<cloud>:8080/wd/<schlüssel>`), z. B. für ein Tablet

   Das Wall Display nimmt nur Adressen an, die wie ein Home Assistant antworten. Für gebundene Displays beantwortet
   die Cloud diese Prüfung (Anmelde-Schnittstelle nach der dokumentierten HA-API). Fragt das Display nach Benutzer
   und Passwort, irgendetwas eintragen – es wird nicht gebraucht und nicht gespeichert.

Oben Uhr, Datum und Außentemperatur (aus der Beschattung), darunter Räume als Reiter und die Szenen.
Tippen schaltet, langes Drücken auf ein dimmbares Licht öffnet den Helligkeitsregler. Klimaanlagen: Soll ±,
Modus, Lüfter, Ein/Aus. Die Adresse enthält einen geheimen Schlüssel – wer sie kennt, sieht und bedient genau die
Kacheln dieser Tafel. „Schlüssel neu erzeugen“ macht die alte Adresse ungültig. Geräte mit „nur Anzeige“ lassen sich
auch hier nicht schalten.

## Taster (Plus i4 u. a.)

Gerät → Bearbeiten → **Taster …**: je Taste kurz / doppelt / lang eine Aktion (Gerät oder Raum an, aus,
umschalten oder eine Szene). Der Eingang muss am Gerät als Taster („button“) eingestellt sein. Die Einträge sind
normale Regeln (Automatik → Regeln) und laufen ohne Shelly Cloud. Die Karte des i4 zeigt die zuletzt gedrückte Taste.

## Update

Die Cloud aktualisiert sich selbst. Unter **Info → Cloud-Update**:

| Modus | Verhalten |
|---|---|
| Aus | keine Prüfung |
| Nur prüfen | alle 6 h prüfen, Hinweis oben rechts, Installation mit **Jetzt aktualisieren** |
| Automatisch installieren (Standard) | zusätzlich täglich zur eingestellten Stunde installieren |

Installiert wird vom Container `hermit-cloud-updater`: Er holt den neuen Stand (`git pull`, bei
entpacktem ZIP das Archiv von GitHub), baut die Container neu und startet sie. Die Oberfläche ist dabei
etwa eine Minute weg und lädt danach von selbst neu. Das Protokoll steht unter Info.

- `docker compose` immer **im Ordner `cloud/`** starten – der Updater merkt sich diesen Pfad.
- Der Updater braucht Zugriff auf `/var/run/docker.sock` und den Repo-Ordner. Wer das nicht will, nimmt den
  Dienst `updater` aus der `docker-compose.yml` und aktualisiert von Hand:
  `cd pagurus-os && git pull && cd cloud && docker compose up -d --build`
- Wer die Cloud aus dem ZIP installiert hat: in einem eigenen Ordner entpacken (z. B. `/opt/hermit/cloud`).

**Von einer Version vor 1.2.3** einmal von Hand (danach geht es automatisch):
```bash
cd pagurus-os && git pull && cd cloud && docker compose up -d --build
```

Die Daten liegen in `cloud/data/cloud.db` (SQLite) und bleiben beim Update erhalten.
Sicherung: den Ordner `data/` kopieren.

## Einstellungen (.env)

| Variable | Bedeutung |
|---|---|
| `MQTT_USER`, `MQTT_PASS` | Zugang zum Broker für Geräte und Cloud (leer = Broker ohne Anmeldung) |
| `CLOUD_PASSWORD` | Passwort des Benutzers `admin` (leer und keine Benutzer = ohne Anmeldung) |
| `PUBLIC_BROKER` | IP des Rechners, wird in der Oberfläche unter *Info* angezeigt |
| `WEB_PORT` | Port der Weboberfläche (Standard 8080) |
| `TZ` | Zeitzone für die Tageswerte |

Weitere Werte im Container: `KEEP_POWER_DAYS` (Leistungsverlauf, Standard 31 Tage),
`OFFLINE_AFTER` (s ohne Lebenszeichen bis „offline“, Standard 180), `OFFLINE_ALERT_AFTER` (s offline bis zur
Meldung, Standard 120).

Ein abgezogenes Gerät meldet der Broker nach etwa 45 s (Pagurus OS ab 1.12.2) als offline; spätestens nach
`OFFLINE_AFTER` setzt die Cloud es selbst auf offline. Offline-Geräte bleiben mit ihren Werten in der Liste,
bis du sie mit **Entfernen** löschst.

## Erste Schritte

1. **Einstellungen → Strom & Standort:** Strompreis in ct/kWh, Breiten-/Längengrad (für Sonnenzeiten) und die
   Adresse der Cloud (z. B. `http://192.168.0.50:8080`, für URL-Auslöser).
2. **Einstellungen → Push:** ntfy oder Telegram eintragen, **Testnachricht** senden.
3. **Geräte → Bearbeiten:** Name und Raum vergeben.
4. **Kühlgeräte → Gerät hinzufügen:** die Messsteckdose von Kühlschrank bzw. Gefriergerät zuordnen.
5. **Wäsche → Gerät hinzufügen:** die Messsteckdose der Waschmaschine bzw. des Trockners zuordnen.
   Die Vorgaben passen für die meisten Geräte; nach ein paar Läufen zeigt die Cloud auch die Restzeit.

**Push über ntfy:** App „ntfy“ installieren, ein langes, zufälliges Thema abonnieren (z. B.
`hermit-k7f3q9x2`) und in der Cloud `https://ntfy.sh/hermit-k7f3q9x2` eintragen. Wer nichts über ntfy.sh
schicken will, startet den eigenen ntfy-Server mit `docker compose --profile ntfy up -d` und trägt
`http://<IP>:8090/<thema>` ein (Server in der App hinzufügen).

**Push über Telegram:** Bei @BotFather einen Bot anlegen (Token), dem Bot schreiben, die Chat-ID z. B. über
`https://api.telegram.org/bot<TOKEN>/getUpdates` ablesen.

**Tür-/Fensterkontakt (z. B. Shelly Door/Window 2):** Regel mit Auslöser „URL-Aufruf“ anlegen, die angezeigte
URL am Kontakt unter *Actions → Open* eintragen. Beispiel: Fenster auf → Raum Bad ausschalten.

**Benutzer:** Der Administrator `admin` kommt aus `CLOUD_PASSWORD`. Weitere Benutzer unter Einstellungen;
ändert man dort das admin-Passwort, gilt ab dann dieses (die `.env` wird dann ignoriert).

## Von unterwegs

Nicht direkt ins Internet stellen. Am besten über den WireGuard-Tunnel ins Heimnetz
oder über einen Reverse-Proxy mit HTTPS und gesetztem `CLOUD_PASSWORD`.

Fürs Handy: **Pagurus App** für Android (separat), zu Hause direkt, unterwegs über das Portal.

Ohne offenen Port und ohne VPN: **Pagurus Portal** auf einem Webhosting (PHP). Die Cloud meldet sich dort
von sich aus, im Portal kann man schalten und Meldungen sehen. Einrichtung: [`portal/README.md`](../portal/README.md).

## Schnittstelle

| Methode | Pfad | |
|---|---|---|
| GET | `/api/devices` | alle Geräte mit Status und Energie heute |
| POST | `/api/devices/{id}/switch` | `{}` umschalten, `{"on":true}` setzen |
| POST | `/api/devices/{id}/rpc` | `{"method":"Switch.GetStatus","params":{"id":0}}` beliebige RPC |
| POST | `/api/devices/{id}/name` | `{"name":"…"}` |
| DELETE | `/api/devices/{id}` | Gerät und gespeicherte Werte entfernen |
| GET | `/api/devices/{id}/power?hours=24` | Leistung je Minute |
| GET | `/api/energy?dev=…&days=31` | Energie pro Tag (ohne `dev`: alle) |
| GET | `/api/energy/months?dev=…` | Energie pro Monat |
| GET | `/api/energy/by_device?days=30` | Verbrauch je Gerät |
| GET | `/api/alerts` · POST `/api/alerts/ack` | Meldungen, `{"id":…}` oder alle quittieren |
