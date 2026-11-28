# Änderungen

## Pagurus Cloud 1.28.0
- **Raumregelung für Klimaanlagen** (Karte → „Raumregelung …“). Die eingestellte Temperatur gilt für den Raum. Die
  Cloud misst ihn mit einem oder mehreren Fühlern (Mittelwert) und verstellt jede Minute die Solltemperatur am
  Innengerät: Gerät = Wunsch + P·(Wunsch − Raum) + Ausgleich. Der Ausgleich (I-Anteil) lernt die Abweichung des
  Gerätefühlers. Ab Wunsch + 0,5 K geht das Gerät auf seine kleinste Temperatur (Kompressor aus), beim Kühlen auf
  die größte. Das Gerät wird höchstens alle 4 min verstellt.
- Zeitpläne, Karte, Wandtafel und Portal setzen bei aktiver Raumregelung den Wunsch, nicht den Gerätewert.
  Angezeigt werden Wunsch und Raumfühler, dazu auf der Karte „Raum … → Gerät …“. Der Verlauf zeigt als Soll den Wunsch.
- Eine an der Fernbedienung eingestellte Temperatur wird als neuer Wunsch übernommen.
- Mehrere Anlagen auf einer Ebene: dieselben Fühler wählen, dann heizt die Anlage mit dem höchsten Wunsch.

## Pagurus Cloud 1.27.7
- Klimaanlagen mit „Nur Anzeige“ sperren jetzt nur noch das Ein-/Ausschalten von Hand. Solltemperatur, Modus,
  Lüfter, Swing, Eco/Turbo/Leise und Anzeige lassen sich wieder bedienen. Vorher waren alle Bedienelemente
  ausgeblendet. Die Karte zeigt dann „🔒 Ein/Aus gesperrt“.

## Pagurus Cloud 1.27.6
- Klima-Verlauf: Die Leistungsbalken werden mindestens auf 500 W skaliert. Bisher füllte bei einem Gerät, das den
  ganzen Tag nur im Standby lief (z. B. 12 W), schon der Standby die Balken voll aus und sah aus wie Dauerbetrieb.

## Pagurus Cloud 1.27.5
- **Behoben:** Nach einem Update über den Updater startete die Cloud nicht mehr („ZoneInfoNotFoundError … CET-1CEST“).
  Der Updater hatte seit 1.27.2 für die Protokoll-Uhrzeiten `TZ` als POSIX-Regel gesetzt, und `docker compose` gab
  das an die Cloud weiter. Jetzt gilt die Regel nur noch für die Uhrzeiten im Protokoll; außerdem fällt die Cloud bei
  einer unbrauchbaren `TZ` auf Europe/Berlin zurück, statt abzubrechen.

## Pagurus Cloud 1.27.4
- **Wächter:** Der Updater prüft jede Minute, ob die Cloud läuft und antwortet. Ist der Container beendet, startet er
  ihn wieder; antwortet die Cloud 4 Minuten lang nicht, startet er sie neu. Jeder Eingriff steht mit den letzten
  Protokollzeilen der Cloud in `data/watchdog.log` und unter Einstellungen → System beim Update („Wächter: Cloud
  wurde neu gestartet“). Aktiv nach dem Update auf 1.27.4 (der Updater liest sein Skript danach neu ein).

## Pagurus Cloud 1.27.3
- Fertig-Erkennung: im Dialog des Geräts neuer Link **„Regel ‚bei fertig' anlegen“** – öffnet eine vorbereitete Regel
  (Auslöser „Gerät fertig“, Aktion Push-Nachricht), die sich um Schalten, Szenen oder Rollläden erweitern lässt.
- Regeln mit Auslöser „Gerät fertig“/„Gerät startet“ bieten nur Geräte mit Fertig-Erkennung an und sagen, wo man sie
  einrichtet, falls noch keine da ist.

## Pagurus Cloud 1.27.2
- Update-Protokoll: Uhrzeiten in deutscher Zeit statt UTC (der Updater-Container hatte keine Zeitzone), „FERTIG“
  jetzt mit Datum. Greift ab dem nächsten Update ohne Neubau des Updaters; `docker-compose.yml` und das
  Updater-Image setzen die Zeitzone künftig auch selbst.

## Pagurus Cloud 1.27.1
- Fertig-Erkennung: Ein neuer Lauf nach „fertig“ wird zuverlässig erkannt und setzt „fertig“ samt Erinnerung zurück.
  Bisher musste die Leistung die ganze Startzeit am Stück über der Schwelle liegen – Waschmaschinen mit Pausen
  (Wasserzulauf, Trommel steht) wurden erst beim Heizen erkannt, Kaltwäsche gar nicht. Jetzt reicht: Startzeit
  vergangen und davon mindestens die Hälfte über der Schwelle; Pausen bis 90 s (Wäsche) bzw. 30 s brechen den Start
  nicht ab. Knitterschutz eines fertigen Trockners (kurze Drehungen) zählt weiterhin nicht als neuer Lauf.

## Pagurus OS ESP32: Heizungsanzeige AZ-Touch
- Neue Variante **`pagurus-aztouch-esp32`**: die Heizungsanzeige (bisher Arduino-Sketch AZ_Touch_Heizung v12.1)
  auf Pagurus OS. Gleiche Anzeige und Bedienung (Boost, Zirkulation), aber WLAN über den Zugangspunkt,
  Adressen von Warmwasser-Logik und Zirkulation in der Weboberfläche, MQTT für die Pagurus Cloud und
  Firmware-Updates über `update.json`. Komponente `display:0`, RPC `Display.*`. Firmware-Stand 1.19.4 wie die
  übrigen ESP32-Varianten; Klima-Varianten unverändert.
- Zweite Seite **BAD** für einen Heizlüfter (wie AZ_Touch v13.0, mit Taste BETRIEB wie CYD v14): Adresse und Name
  im Reiter *Anzeige*, Wechsel über die Kopfzeile. Startausgabe auf der seriellen Schnittstelle (115200).
- WLAN-Seite (Anzeige und Klima): nach „Netze suchen“ ist kein Netz mehr vorausgewählt – vorher wurde beim Speichern
  ohne Auswahl das stärkste fremde Netz übernommen. Rückfrage mit dem Netznamen vor dem Speichern.
- AZ-Touch: Scheitert ein Firmware-Update (Download, Prüfsumme), blieb die Anzeige auf „Firmware-Update …“ stehen
  und der Watchdog aus. Jetzt geht es mit Watchdog normal weiter.
- AZ-Touch: neue Oberfläche – dunkle Karten, große Zahlen, schlanke Balken mit Soll-Marke, runde Tasten, Seite BAD mit
  Ring um die Raumtemperatur; Umlaute und Gradzeichen. Gezeichnet wird nur, was sich ändert (kein Flackern mehr).
  Liest von der Warmwasser-Logik `status` (Soll, Rücklauf, Fühlerstörung), bei älterer Logik weiter `api_data`.
- AZ-Touch heißt jetzt **`pagurus-aztouch-esp32`** (Gerät `pagurus-aztouch-…`, Zugangspunkt `pagurus-aztouch-xxxxxx`,
  Modell `PAGURUS-AZTOUCH-ESP32`). Ein Gerät mit der bisherigen Kennung findet das Update weiterhin; danach meldet es
  sich unter dem neuen Namen in der Cloud (der alte Eintrag kann gelöscht werden).

## Pagurus Cloud 1.27.0
- Heizung: **Duschen und Baden erkennen.** Die Cloud wertet die minütliche Warmwasser-Aufzeichnung aus: Fällt der
  Speicher schnell (ab 0,3 K in 3 min, insgesamt ab 0,8 K), ist das eine Zapfung – kleine Zapfung, Duschen (ab 1,5 K)
  oder Baden (ab 5 K oder 20 min). Liste der letzten 14 Tage und Wochenprofil (Mo–Fr / Sa–So in 30-Minuten-Fenstern,
  28 Tage) im Heizung-Reiter unter dem Verlauf. Gespeichert wird ein Jahr lang. Vorerst nur Erfassung, die Heizzeiten
  werden nicht verstellt. API: `GET /api/heizung/draws?days=28`.

## Pagurus Cloud 1.26.0
- Beschattung: neue Bedingung **Lichtsensor**. Ein Helligkeitsfühler vor Ort (z. B. Shelly BLU Motion oder
  BLU Door/Window) mit Schwelle in Lux entscheidet, ob die Sonne scheint – genauer als die Einstrahlung aus dem
  Wetter. Beim Beschatten gilt 60 % der Schwelle, damit kurze Wolken die Rollläden nicht hochfahren. Meldet der
  Sensor 30 Minuten nichts, nimmt die Regel wieder die Wetter-Einstrahlung und zeigt das als Hinweis an.

## Pagurus Cloud 1.25.1
- Scripte: Übertragen auf die Shellys schlug mit „Missing or bad argument 'code'“ fehl, sobald der Code Zeichen
  außerhalb von Latin-1 enthielt (z. B. Gedankenstrich, Emojis). Die Cloud sendet RPC jetzt als UTF-8 statt mit
  \uXXXX-Escapes, die der JSON-Parser der Shellys nicht versteht. Umlaute kamen vorher ebenfalls verfälscht an.

## Pagurus Cloud 1.25.0
- Neuer Reiter **Scripte** (nur Administratoren): alle Scripte der Shelly Gen2+ mit Version (aus der ersten
  Kommentarzeile), Zustand, Autostart und freiem Speicher. Code in der Cloud bearbeiten und auf das Gerät speichern,
  starten/stoppen, Autostart, neue Scripte anlegen. Vor jedem Überschreiben sichert die Cloud den alten Code (je Script
  die letzten 20 Fassungen, zurückholbar) und prüft nach dem Start, ob das Script läuft.
- **Bibliothek:** Scripte zentral pflegen und auf ein oder mehrere Geräte übertragen.

## Pagurus Cloud 1.24.1
- Einstellungen in Unterreiter aufgeteilt: Allgemein (Strom, Standort, Push), Geräte (Anbinden, Firmware, Sicherungen),
  Wandtafeln, Zugang (Benutzer, Fernzugang), System (Cloud-Update). Der zuletzt gewählte Unterreiter bleibt gemerkt.
- Sicherungen: je Gerät nur die neueste Zeile, ältere zum Aufklappen. Firmware: nur Geräte mit Update, „Alle Geräte
  zeigen“ blendet den Rest ein.

## Pagurus Cloud 1.24.0
- Heizung: **Warmwasser-Verlauf**. Die Cloud zeichnet jede Minute Speicher, Kessel, Rücklauf, Soll, Brenner,
  Pumpe und Ölzähler auf. Diagramm über 24 h, 3 oder 7 Tage (Brenner und Pumpe als Balken darunter, Werte beim
  Darüberfahren) und eine Tabelle der letzten 14 Tage: Öl, Brennerlaufzeit, Starts, Ø Laufzeit je Start, Pumpe,
  Speicher min–max. Aufbewahrung wie der Leistungsverlauf (mindestens 30 Tage).

## Pagurus Cloud 1.23.1
- Heizung: Warmwasser-Logik ohne externe Cloud (ab V13.2) – der Schalter „Cloud darf vorgeben“ wird dann ausgeblendet.

## Pagurus Cloud 1.23.0
- Neuer Bereich **Heizung**: Warmwasser (Ölkessel mit Shelly-Logik-Script), Zirkulationspumpe und Raumheizer
  (Heizlüfter-Script v11, Konvektor-Logik v1.6) an einer Stelle. Live-Werte, Boost, Ein/Aus, Quittieren sowie alle
  Einstellungen: beim Warmwasser Zeiten, Sollwerte, Kessel, Ladepumpe, Brenner, Cloud-Vorgaben und gelerntes
  Nachheizen, bei den Heizern Halte-Temperatur, Zeitfenster, Boost und beim Konvektor die Höchststufe.
  Die Regelung bleibt auf den Shellys; die Cloud spricht sie direkt per HTTP an (kein CORS-Problem wie im Browser).
  Geräte unter *Heizung → Geräte*: Cloud-Gerät wählen (IP folgt automatisch) oder IP eintragen.
- Neue Meldungsart „Heizung-Störung“ (Fühlerstörung am Warmwasser, Störung eines Heizers), mit Push.

## Pagurus Cloud 1.22.9
- Geräte-Seite: Räume als eigene, farbig markierte Bereiche mit Kopfzeile (Temperatur/Feuchte eines Fühlers im Raum,
  „x von y an“, Gesamtleistung, Anzahl Geräte). Räume lassen sich zuklappen (merkt sich der Browser);
  oben Sprungleiste zu jedem Raum.

## Pagurus OS 1.19.4
- TCL-Klima: Lernmodus war nicht erreichbar (Methodennamen werden klein verglichen) – behoben.

## Pagurus OS 1.19.3
- TCL-Klima: „Fernbedienungstasten lernen“ auf der Modul-Webseite. Zeichnet auf, welche Bytes im Zustand der Anlage
  sich ändern, wenn an der Fernbedienung eine Funktion geschaltet wird (für Sleep, Health, 8 °C, I Feel).

## Pagurus OS 1.19.2 / Pagurus Cloud 1.22.8
- TCL-Klima: Anzeige am Innengerät schaltbar (Knopf „Anzeige“ in Cloud, Wandtafel, Portal und Modul-Webseite).
  Bisher schaltete jeder Befehl aus der Cloud die Anzeige wieder ein – auch wenn sie per Fernbedienung aus war.
  Jetzt bleibt der zuletzt gemeldete Zustand erhalten.

## Pagurus Cloud 1.22.7
- Vorbereitung Umbenennung hermit → pagurus (docs/UMBENENNUNG.md, Schritt 1): Die Cloud erkennt Pagurus OS auch an
  `pagurus-os` und Modellen `PAGURUS-…`. Meldet sich ein Gerät als `pagurus-…`, das noch als `hermit-…` bekannt ist,
  wird der vorhandene Eintrag mit Kanälen, Verlauf, Energie, Regeln, Szenen und Wandtafeln auf die neue ID umgeschrieben.
- Flash-Tool erkennt ebenfalls beide Namen.

## Pagurus OS 1.19.1
- Flash-Tool: Feld „WLAN für das Gerät“ (SSID wird vom Gerät vorbelegt, Passwort eintragen). Die Daten werden vor
  dem Aufspielen fest in die Firmware eingetragen und haben beim ersten Start Vorrang – der Umstieg von
  Original-Firmware oder Tasmota verliert das WLAN nicht mehr. Kommandozeile: `--ssid … --wifi-pass …`.
- Flash-Tool: Knopf „Abbrechen“; Suche und Warten lassen sich jederzeit beenden.
- Flash-Tool: Nach dem Aufspielen wird früher per MAC nach dem Gerät gesucht (neue IP) statt erst nach 3 Minuten.

## Pagurus Cloud 1.22.6
- Gerätekarten: Die Temperatur der Elektronik in Schaltern, Steckdosen und Messgeräten steht nur noch klein als „intern … °C“ unten in der Karte; als „Temperatur“ erscheinen nur noch echte Fühler. Das Portal zeigt sie gar nicht mehr.

## Pagurus Cloud 1.22.5
- Wall Display: Antworten der Home-Assistant-Prüfung hatten eine zu große Längenangabe (Content-Length) – der Client des Displays wartete auf fehlende Bytes und meldete „keine gültige HA-Instanz“. Jetzt passend; Manifest wie bei Home Assistant, `/api` auch ohne Schrägstrich

## Pagurus Cloud 1.22.4
- Wandtafeln: Display direkt aus der Anfrageliste an eine Tafel binden („an … binden“)

## Pagurus Cloud 1.22.3
- IP von Gen2+/Gen3-Geräten, die per MQTT verbunden sind, wird jetzt ermittelt (`WiFi.GetStatus` beim Verbinden und aus den Statusmeldungen) – vorher blieb sie leer, und eine an ein Gerät gebundene Wandtafel fand das Wall Display nicht
- Einstellungen → Wandtafeln zeigt die letzten Anfragen von Displays an die Home-Assistant-Prüfung mit IP und Ergebnis

## Pagurus Cloud 1.22.2
- Shelly Wall Display: Die Cloud beantwortet für gebundene Displays die Home-Assistant-Prüfung (`/auth/login_flow`, `/auth/providers`, `/auth/token`, `/api/`, `/api/config`, `/api/websocket`, `/manifest.json`) – vorher meldete das Display „keine gültige HA-Instanz“. Andere Geräte bekommen dort weiterhin 404; die ausgegebenen Tokens gelten für nichts

## Pagurus Cloud 1.22.1
- Wandtafel an ein Gerät binden (Wall Display aus der Liste oder feste IP): Am Display genügt dann die kurze Adresse der Cloud (`http://<cloud>:8080`), die Cloud erkennt es an seiner IP und zeigt gleich die Tafel. Die IP folgt DHCP-Wechseln, wenn das Display in der Cloud verbunden ist

## Pagurus Cloud 1.22.0
- **Wandtafeln** für das Shelly Wall Display oder ein Tablet (Einstellungen → Wandtafeln): eigene Seite `/wd/<schlüssel>` mit großen Kacheln, Räumen als Reiter, Szenen, Uhr und Außentemperatur. Schalten, Helligkeit (lange drücken), Rollladen ▲■▼, Klima (Soll ±, Modus, Lüfter, Ein/Aus), Fühler und Messgeräte. Zugriff nur auf die ausgewählten Kacheln, wahlweise nur Anzeige; „nur Anzeige“ einzelner Geräte gilt auch hier
- **Taster** (Gerät → Bearbeiten → Taster …): Plus i4 und andere Gen2+-Eingänge – je Taste kurz/doppelt/lang Gerät, Raum oder Szene, ohne Shelly Cloud. i4-Karte ohne Schaltknopf, zeigt die zuletzt gedrückte Taste

## Pagurus Cloud 1.21.4
- Bereich Klima, Midea: Raumtemperatur im 24-h-Verlauf kommt vom Gerätefühler, wenn kein DHT22 da ist; „Kompressor“ nur bei Anlagen, die ihn melden (TCL)

## Pagurus Cloud 1.21.3
- Reine Messgeräte (Shelly Plus PM Mini, Mini PM G3, Komponente `pm1:0`) werden erkannt: Leistung, Spannung, Strom, Verbrauch und Kosten, Energieverlauf; kein Schaltknopf mehr. Auch für Kühlgerät-/Fertig-Erkennung und als Energiemesser der Klimaanlage nutzbar; Raum-Schalten und Szenen lassen sie aus

## Pagurus Cloud 1.21.2
- Falsche Offline-Meldungen behoben: Geräte ohne Leistungsmessung (Plus 1, Plus 1 Mini, Plus i4, Mini G3 …) senden oft minutenlang nichts und galten nach 3 min als offline. Die Cloud fragt solche Geräte jetzt erst per `Sys.GetStatus` ab und meldet nur, wer wirklich nicht antwortet

## Pagurus Scanner 1.1.0
- Gründlicher: zwei Durchgänge (zweiter mit längeren Zeitlimits für alle, die nicht geantwortet haben), mDNS-Suche und ARP-Tabelle als zusätzliche Quellen, bis zu drei Versuche je Abfrage, weniger gleichzeitige Verbindungen – langsame oder beschäftigte Geräte (v. a. Gen1) wurden vorher teils übersprungen
- Geräte mit Webserver, aber ohne Shelly/Tasmota-Antwort erscheinen als „Unbekannt“ (Filter, anfangs aus)
- Letzte Hermit-Reste umbenannt (Kennung, Einstellungsordner – alte Einstellungen werden übernommen); eigenes Paket `Pagurus-Scanner-1.1.0.zip` mit `build_scanner.bat`

## Pagurus Cloud 1.21.1
- Gen2/Gen3-Geräte ohne MQTT-Statusmeldungen (z. B. Shelly Plus 1 mit ausgeschalteten „Generic status update“ und „RPC status notifications“) blieben ohne Schaltzustand und ließen sich nicht schalten: Die Cloud holt den Status jetzt beim Verbinden per RPC und fragt solche Geräte alle 30 s ab; ein Hinweis erscheint unter Meldungen

## Pagurus Cloud 1.21.0 / Pagurus Portal 1.9
- Mehrkanalige Geräte (2PM, 2.5): Kanäle wahlweise in einer Karte zusammenfassen (Kanal 1 bearbeiten → Kanäle). Je Kanal eigener Schaltknopf mit Namen (z. B. Stufe 1/Stufe 2), Leistung und Verbrauch, dazu die Summe; auch im Portal und in der App (ab 1.7.0). Zeitpläne, Regeln und Energieauswertung behandeln die Kanäle weiter einzeln

## 1.19.0 / Pagurus Cloud 1.20.0 / Pagurus Portal 1.8
- **Neue Variante `hermit-midea-esp32c3`:** Midea-Klimaanlagen (auch Dimstal, Comfee, Qlima, Electrolux, Artel …)
  an einem ESP32-C3 statt WLAN-Stick bzw. ESPHome, UART TX GPIO21 / RX GPIO20 (9600 8N1). Protokoll über die
  Bibliothek dudanov/MideaUART (MIT), dieselbe wie in ESPHome. Fähigkeiten werden bei der Anlage abgefragt
  (Modi, Swing, Eco, Turbo); Soll in 0,5 °C, Raum- und Außentemperatur, Lüfter Auto/1/2/3, Leise, Turbo,
  Nachtmodus, Anzeige an/aus, Piepton abschaltbar (Standard aus). Umstieg von ESPHome per Browser-Upload,
  Komplettabbild fürs Kabel (`esp32c3`, ab 0x0)
- ESP32-Projekt aufgeteilt: gemeinsamer Kern, Anbindung je Anlage (`ac_tcl.h`, `ac_midea.h`); TCL unverändert
- Klima-Seite am Gerät zeigt Modi, Lüfter, Extras und Messwerte nach dem, was die Anlage meldet
- Cloud (Gerätekarte und Bereich Klima) und Portal: zeigen nur die Modi/Lüfterstufen des Geräts (`modes`, `fans`), Soll ± in der
  Schrittweite des Geräts (halbe Grad), Außentemperatur; Nachtmodus (`sleep`) wird durchgereicht

## Pagurus Cloud 1.19.0 / Pagurus Portal 1.7
- „Nur Anzeige“ je Gerät (Bearbeiten → Bedienung): Der Schaltknopf zeigt nur noch den Zustand, Schalten von Hand ist in Cloud, Portal und App (ab 1.6.0) gesperrt – auch Helligkeit, Rollladen und Klima. Automatik, Zeitpläne, Regeln und Szenen schalten weiter

## Pagurus Cloud 1.18.0
- Klima-Zeitpläne je Anlage (Bereich Klima → „+ Zeitpunkt“): Wochentage, Uhrzeit oder Sonnenauf-/-untergang ± Minuten, Einschalten mit Modus/Soll/Lüfter (jeweils auch „unverändert“) oder Ausschalten. Läuft eine Fenster-offen-Pause, wird das Einschalten für danach vorgemerkt, Ausschalten beendet die Pause
- Nach einer Fenster-offen-Pause werden neben dem Modus auch Solltemperatur und Lüfter wiederhergestellt

## Pagurus Cloud 1.17.0
- Eigener Bereich **Klima**: je Anlage Bedienung (Ein/Aus, Soll ±, Modus, Lüfter, Swing ↕/↔, Eco, Turbo, Leise), Raum-/Geräte-/Ausblastemperatur, Feuchte, Leistung, Verbrauch und Kosten heute/30 Tage, Laufzeit und Kompressorzeit heute, 24-h-Verlauf (Temperaturen, Soll, Leistung, Heiz-/Kühlbetrieb) und 14-Tage-Balken, Stand der Fenster-offen-Erkennung
- Klima-Verlauf wird minütlich aufgezeichnet (Tabelle `climate_log`, Aufbewahrung wie die Leistungswerte)

## Pagurus Cloud 1.16.0 / Pagurus Portal 1.6
- Fenster/Tür offen an Klimaanlagen (Gerät bearbeiten → „Fenster offen …“): Steht ein gewählter Kontakt (z. B. BLU Door/Window) länger offen, wird die Anlage ausgeschaltet und nach dem Schließen mit dem vorigen Modus wieder eingeschaltet; wahlweise auch ohne Kontakt über einen Temperatursturz am DHT22 mit fester Pause. Gilt standardmäßig nur beim Heizen, Kühlen usw. zuschaltbar. Selbst einschalten beendet die Pause. Meldung „Fenster offen“ (auch als Push)
- Portal zeigt die Pause auf der Klima-Karte

## 1.18.7
- ESP32-Klima: Hex-Anzeige (letzter Rahmen, Rohdaten) und Schalter „TX/RX tauschen“ von der Seite entfernt, die Diagnosezeile bleibt; Status-Meldungen dadurch kleiner

## Pagurus Cloud 1.15.0
- Klimaanlagen lassen sich mit einem Energiemesser koppeln (Gerät bearbeiten → Energiemesser): Leistung, Verbrauch heute und Kosten erscheinen auf der Klima-Karte, auch im Portal und in der App (ab 1.4.0); der Messer kann als eigenes Gerät ausgeblendet werden

## Pagurus Cloud 1.14.0 / Pagurus Portal 1.5
- Klimaanlage im Portal: Solltemperatur −/+, Modus und Lüfter, Raumtemperatur/Feuchte vom Fühler. Neue Spalte `arg` in der Befehlstabelle wird beim ersten Aufruf automatisch angelegt
- Cloud führt Klima-Befehle aus dem Portal aus (Climate.Set, danach frischer Status)

## 1.18.6
- ESP32-Klima: Online-Update konnte beim Lesen hängen bleiben (Weboberfläche tot, Gerät nur noch per Ping erreichbar); Abbruch jetzt immer nach 20 s ohne Fortschritt

## 1.18.5
- ESP32-Klima: Online-Update lädt per HTTP/1.0 (GitHub lieferte beim ersten Abruf in Chunks, dadurch falsche Prüfsumme und „Download abgebrochen“); Fehlermeldung zeigt geladene Bytes
- Kleine `update/<variante>.json` je Gerät: alte Firmware (bis 1.17) scheiterte mit „update.json ungültig“ an der gewachsenen Gesamtdatei (zu wenig RAM); `update.json` kompakt geschrieben

## 1.18.4
- ESP32-Klima: Weboberfläche lädt deutlich schneller (WLAN-Modem-Sleep aus, Seite gepackt)

## 1.18.3
- ESP32-Klima: Update brach ab, wenn GitHub die Verbindung vor dem letzten Lesen schloss; Firmware-Datei lässt sich zusätzlich im Reiter System hochladen

## 1.18.2
- ESP32-Klima: Zustandsrahmen werden auch ohne Richtungsbyte `01 00` / Kennung `04` angenommen (Anlage antwortete, wurde aber verworfen); Diagnose zeigt letzten Rahmen und Rohdaten als Hex, eigenes Echo wird erkannt

## 1.18.1
- ESP32-Klima: Diagnose auf der Seite (gesendete/empfangene UART-Rahmen und Bytes, DHT22-Lesungen), Schalter „TX/RX tauschen“ ohne Umlöten, DHT22 liest nach dem Start schneller nach

## 1.18.0 / Pagurus Cloud 1.13.0
- **Pagurus OS für ESP32** (`esp32/`, Variante `hermit-tclac-esp32`): steuert TCL-/Kesser-Klimaanlagen
  über den UART des WLAN-Moduls (eigene Protokollumsetzung), DHT22 für Raumtemperatur und Feuchte.
  Weboberfläche, JSON-RPC, MQTT im Gen2-Format, Updates über update.json mit SHA-256; Umstieg von ESPHome
  per Browser-Upload, Komplettabbild fürs Kabel
- Cloud: Klimaanlagen (`climate:0`) mit Modus, Solltemperatur ±, Lüfter und Swing auf der Gerätekarte,
  An/Aus wie ein Schalter (auch in Portal, App, Szenen und Regeln); DHT22 als Fühler für die Beschattung

## 1.17.4
- **Neue Variante `hermit-plug1m`:** einfache WLAN-Steckdose mit ESP8285 (1 MB), Touch-Taste, ohne
  Leistungsmessung (Relais GPIO12, Taste GPIO13, LEDs GPIO4/GPIO5). Updates wie bei der RF Bridge über einen
  eigenen 1-MB-Loader (`hermit-loader-1m-plug1m`); Weg von ESPHome in docs/FLASHEN.md

## 1.17.3
- Geräteseite: Zahlen mit deutschem Komma (0,0 W, 1,154 kWh, Faktor 1,0234); IP-Adressen bleiben mit Punkt

## Pagurus Cloud 1.12.1 / Pagurus Portal 1.4
- Portal: Dimmer zeigen die Helligkeit und haben einen Regler (vorher nur an/aus)

## Repo
- Die Android-App liegt nicht mehr in diesem Repo

## Pagurus App 1.0.0 (Android) / Pagurus Cloud 1.12.0 / Pagurus Portal 1.3
- **Neue Android-App** (liegt separat): zu Hause direkt zur Cloud, unterwegs
  automatisch über das Portal. Geräte, Rollläden, Szenen, Fühler, Meldungen, die volle Cloud-Oberfläche,
  Push-Meldungen ohne Google-Dienste, Widget mit Favoriten, drei Schnellkacheln
- Portal: reicht Anfragen der App an die Cloud durch (Long-Polling, ~0,5 s) und wartet für den Push auf
  neue Meldungen; bei `READ_ONLY` nur lesend
- Cloud: Anmeldung per Token (`Authorization: Bearer …`, Login liefert `token`), Long-Polling
  `/api/alerts/wait`, interner Zugang für das Portal

## Pagurus Cloud 1.11.0 / Pagurus Portal 1.2
- **Shelly BLU** über Gen2+/Gen3-Shellys als Gateway (BTHome-Komponenten per MQTT, ohne Shelly Cloud):
  jedes BLU-Gerät eigenes Gerät, Temperatur/Feuchte/Helligkeit auch für die Beschattung, Fenster/Tür,
  Bewegung, Neigung, Wasser, Batterie, Tasten. Ereignisse `open`/`closed`, `motion`/`no_motion`,
  `single_push` … als Regel-Auslöser; mehrere Gateways lösen nur einmal aus
- Fehler behoben: Batteriefühler (DW2, H&T, BLU) wurden nach 3 Minuten Funkstille als „offline“ gemeldet
- Portal: Kontakt und Bewegung auf den Fühler-Karten

## Pagurus Cloud 1.10.0 / Pagurus Portal 1.1
- **Szenen:** mehrere Geräte/Räume/Rollläden mit einem Klick („Gute Nacht“: alles aus, Rollläden zu).
  Anlegen unter *Automatik → Szenen*; Tasten oben in der Geräteübersicht; Szenen sind Ziel in Zeitplänen
  und Regeln. Alle Aktionen einer Szene laufen gleichzeitig
- Portal: Szenen-Tasten, Leistung jetzt und Energie heute oben, als App installierbar
  (Startbildschirm, Vollbild, Symbol)
- Portal: Fehler behoben – nach einem Befehl blieb der Schaltknopf auf „…“ stehen (falsche Befehlsnummer)

## Pagurus Cloud 1.9.0 / Pagurus Portal 1.0
- **Pagurus Portal** (neu, Ordner `portal/`): Fernzugang als PHP-Seite für ein normales Webhosting.
  Die Cloud meldet sich dort von sich aus per HTTPS (kein offener Port, kein VPN), überträgt Geräte und
  Meldungen und holt Schaltbefehle per Long-Polling ab – Befehle kommen sofort an. Schalten, Rollläden,
  Fühlerwerte, Meldungen; Anmeldung mit Passwort und Sperre nach Fehlversuchen, optional nur Anzeige
- Cloud: *Einstellungen → Fernzugang-Portal* (Adresse, Schlüssel, Verbindungsstatus)

## Pagurus Cloud 1.8.2
- Geräteübersicht: Tasten „alle an“ / „alle aus“ bei den Räumen entfernt

## 1.17.2
- Update-Prüfung: sporadisches „update.json ungültig“ behoben (v. a. RF Bridge). Die Datei wird nicht mehr
  komplett in den RAM geladen; das Gerät liest nur Version und den eigenen Eintrag direkt aus dem Datenstrom,
  mit bis zu 3 Versuchen. Schlägt es trotzdem fehl, steht der Grund und der freie RAM in der Meldung

## 1.17.1 / Pagurus Cloud 1.8.1
- RF Bridge: Taste **„Leeren“** bei „Zuletzt empfangen“ (neue RPC `RF.ClearRecent`); gespeicherte Codes bleiben
- Cloud: **„Alle löschen“** bei den Meldungen (mit Rückfrage), neben „Alle quittieren“

## 1.17.0 / Pagurus Cloud 1.8.0
- **Neuer Name: Pagurus OS** (vorher Hermit OS – der Name gehört schon dem Rust-Unikernel HermitOS).
  Pagurus ist der Einsiedlerkrebs. Umbenannt sind Oberfläche, Doku, Flasher (`Pagurus-Flasher`, `pagurus-flash`),
  Scanner (`Pagurus-Scanner`), Loader-Seite, Cloud und das GitHub-Repo (`oeltensack/pagurus-os`)
- Unverändert für die Verträglichkeit: Gerätekennungen (`hermit-duo-…`), Varianten (`hermit-1pm`, Dateien in `bin/`),
  `fw_id` (`hermit-os/…`), MQTT-Topics, Zugangspunkt `hermit-…`. Vorhandene Geräte updaten weiter und bleiben in der Cloud
- Flasher erkennt den Loader unter altem und neuem Namen

## 1.16.1
- Update-Fehler behoben: Ein einmal gefundenes Update wurde nie neu geprüft. Kam danach eine neuere Version,
  passte die SHA-256 nicht mehr zur Datei in `bin/` und das Update wurde jedes Mal verworfen (z. B. Duo blieb
  auf 1.12 mit „1.13.0 verfügbar“). Jetzt wird vor jeder Installation und bei jedem Termin frisch geprüft

## 1.16.0
- **Sonoff RF Bridge 433** (`hermit-rfbridge`, R2 mit EFM8BB1, Original- oder Portisch-Firmware im Funkchip):
  - Empfangene Codes anzeigen, übernehmen und speichern als Taste, Kontakt (offen/zu) oder Schalter (Funksteckdose)
  - Funksteckdosen erscheinen als `switch:<n>` – schaltbar per RPC, Zeitplan, Regel, Hermit Cloud; Fernbedienung
    aktualisiert den Zustand
  - Ereignisse `rf.button`, `rf.open`, `rf.closed`, `rf.unknown`, `switch.on/off` je gespeichertem Code (Aktionen, MQTT)
  - Empfangsmodi Standard (24 Bit), alle Protokolle und Rohdaten (Portisch); Senden beliebiger Codes; Summer
  - RPC `RF.*`, Reiter „Funk“ in der Oberfläche
- **1-MB-Geräte:** Update über den neuen **Hermit Loader 1 MB** (lädt per HTTPS, prüft SHA-256, Einstellungen
  bleiben); WLAN aus Tasmota wird vor dem ersten Formatieren gelesen
- Flasher: RF Bridge von Tasmota (bei Platzmangel automatisch über tasmota-minimal) und Hermit-zu-Hermit-Update über den Loader

## Hermit Cloud 1.7.3
- Regeln mit Ereignis einer bestimmten Komponente, z. B. `rf:3.button` oder `rf:2.open` (RF Bridge)

## Hermit Cloud 1.7.2
- Fehler aus 1.7.1 behoben: Beim Löschen kam das Gerät sofort ohne Daten zurück (leere Nachricht zum
  Entfernen der gespeicherten Daten wurde als „offline“ gelesen). Leere Nachrichten und die Offline-Meldung
  eines unbekannten Geräts legen kein Gerät mehr an

## Hermit Cloud 1.7.1
- Gelöschte Geräte kommen nach einem Neustart oder Update der Cloud nicht mehr zurück: Beim Löschen werden
  die beim Broker gespeicherten (retained) Nachrichten des Geräts entfernt, und gespeicherte Nachrichten
  legen kein unbekanntes Gerät mehr an – nur ein Gerät, das wirklich sendet

## Hermit Cloud 1.7.0
- **Shelly Door/Window 2 und H&T (Gen1, Original-Firmware) als Fühler:** MQTT im Gen1-Format
  (`shellies/<id>/sensor/…`); Temperatur, Helligkeit, Feuchte und Batterie gehen in die Fühler und in die
  Beschattung, Kontakt/Neigung/Vibration werden ignoriert
- Gen1-Fühler werden beim Netzsuchen erkannt (wenn wach) und per Klick auf die Cloud als MQTT-Server gestellt
- Gerätekarte für Batteriefühler: Temperatur, Helligkeit, Feuchte, Batterie, letzte Meldung; kein Schalten,
  keine Sicherung, nicht in Raum-Schaltungen

## Hermit Cloud 1.6.0
- **Beschattung:** neuer Reiter – Rollläden nach Sonnenstand (Azimut/Höhe je Fassade) und Temperatur
  (Fühler oder Wetter von Open-Meteo), optional Innentemperatur, Höchstwert-Vorhersage, Einstrahlung;
  Verzögerung, Zeitfenster, Tage, Frostschutz; nur nach unten, Handbedienung hat Vorrang, „heute pausieren“;
  Kompass mit Sonnenstand und Fassaden
- **Shelly Gen2+ mit Original-Firmware parallel zur Shelly Cloud:** Netz durchsuchen, mit einem Klick als
  MQTT-Server eintragen (auch mit Gerätepasswort, Digest SHA-256), Warnung bei vorhandenem MQTT-Server
- Mehrkanal-Geräte (Plus 2PM, Pro 4PM, Pro Dual Cover) je Kanal als eigenes Gerät
- Fühler (Temperatur, Feuchte, Helligkeit) werden gesammelt
- Zeitpläne und Regeln: Aktion „Rollladen auf Position“; Rollläden in der Zielauswahl


## 1.15.0
- **Shelly 2.5** – zwei Firmwares:
  - `hermit-25`: zwei Schaltkanäle wie Shelly Plus 2PM (`switch:0`, `switch:1`), je Kanal Leistung, Spannung,
    Strom, cos φ, Frequenz und Energie (ADE7953), eigene Einstellungen, Timer, Aktionen, Kalibrierung
  - `hermit-25-cover`: Rollladen wie Shelly Plus 2PM (`cover:0`) – Auf/Ab/Stopp, Position nach Kalibrierfahrt,
    Endlagen am Motorstrom, Höchstfahrzeit, Hinderniserkennung, ein oder zwei Eingänge (Schalter/Taster),
    Richtungs- und Eingangstausch, 0,5 s Pause beim Richtungswechsel, nie beide Relais an
  - WLAN-Reset auch über den Taster auf der Platine (10 s)
- Firmware intern auf mehrere Kanäle umgebaut (Relais, Timer, Messung, Einstellungen)
- Flasher: Shelly 2.5 von Original-Firmware (erkennt Rollladenbetrieb) und Tasmota; `--cover` / `--switch`

## Hermit Cloud 1.5.0
- Shelly 2.5: Kanal 2 erscheint als eigenes Gerät (eigene Leistung, Energie, Raum, Regeln)
- Rollladen: Auf/Stopp/Zu und Positionsregler in der Gerätekarte; in Zeitplänen und Regeln gilt
  „an“ = öffnen, „aus“ = schließen; Meldungen bei Hindernis und fehlgeschlagener Kalibrierung
- Gerät löschen entfernt auch die Stundenwerte


## 1.14.0
- **Shelly Dimmer 2** (`hermit-dimmer2`): verhält sich wie ein Shelly Dimmer Gen3 (`light:0`, `Light.Set`,
  `Light.DimUp/DimDown/DimStop`), zwei Eingänge (`input:0` SW1, `input:1` SW2)
  - Taster: kurz an/aus, halten dimmt (Richtung wechselt); oder zwei Taster (SW1 heller, SW2 dunkler); oder Schalter
  - Mindest-/Höchsthelligkeit, Phasenab-/-anschnitt, Überblendzeit, Dimmgeschwindigkeit
  - Leistung und Energie vom STM32, Temperatur, Abschaltung bei 250 W / 85 °C
  - Licht bleibt bei Update und Neustart an; nach Stromausfall standardmäßig letzter Zustand
  - Läuft mit der Original-STM32-Firmware (2.x) und der quelloffenen (51.x) – es wird nichts am STM32 geflasht
- Flasher: Dimmer 2 von Original-Firmware (über mg2tasmota-ShellyDimmer2) und Tasmota

## Hermit Cloud 1.4.1
- Dimmer: Helligkeitsregler in der Gerätekarte (auch für die Duo), Fehler „Dimmer-Chip antwortet nicht“


## Hermit Scanner 1.0.0
- Neues Windows-Programm `Hermit-Scanner` (tools/hermit_scanner.py): findet Shelly Gen1, Shelly Gen2/Gen3, Tasmota und
  Hermit OS in einem oder mehreren Netzen; Name, Modell, Firmware, MAC, Empfang, Zustand, Leistung, Update, Laufzeit;
  Filter, Sortierung, Browser öffnen, Neustart, CSV-Export; EXE über tools/build_exe.bat

## Hermit Cloud 1.4.0
- **Verbrauch je Zeitraum** (wie in der Shelly-App): Tag (Stunden), Woche, Monat, Jahr – mit Blättern,
  gestrichelter Linie für den Zeitraum davor, Gesamt mit Kosten, Abweichung in %, Durchschnitt, Max, Min
- Stundenwerte werden ab jetzt gespeichert (für ältere Tage aus dem Leistungsverlauf berechnet)
- Diagramme: feinere Skalen, auf dem Handy größere Beschriftung

## Hermit Cloud 1.3.1
- Kühlgerät anlegen ergab „HTTP 500“ (Geräte-ID fehlte beim Speichern)

## Hermit Cloud 1.3.0
- Neuer Reiter **Kühlgeräte** (Kühlschrank, Gefrierschrank, Kombi): Kompressor-Zeitleiste der letzten 24 h,
  Laufanteil, Zyklen, Ø Laufzeit/Pause, Energie heute und Ø pro Tag, Kosten pro Jahr
- Warnungen per Push: Kompressor läuft ohne Pause (Tür offen?), läuft nicht mehr an (kühlt es noch?),
  Tagesverbrauch deutlich über dem Schnitt der letzten 14 Tage (Vereisung, Dichtung)

## 1.13.0
- **Mehrere Access Points mit gleichem Namen:** Hermit OS sucht vor dem Verbinden den stärksten AP und verbindet
  sich gezielt mit ihm. Liegt der Empfang unter −70 dBm (einstellbar), sucht es alle 5 min nach einem AP, der
  mindestens 8 dB besser ist, und wechselt. Ist der gewählte AP weg, wird nach 30 s neu gesucht.
  Einstellung unter WLAN, Status zeigt AP (BSSID), Kanal und Anzahl der Wechsel

## Hermit Cloud 1.2.3
- Updater erneuert seinen eigenen Container nicht mehr (das hat ihn zweimal gestoppt). Sein Skript liegt im
  Repo-Ordner und ist nach dem `git pull` schon neu – er liest es nach dem Update einfach neu ein.

## Hermit Cloud 1.2.2
- Kurze Verbindungsaussetzer (z. B. bei schwachem WLAN) erzeugen keine Meldungen mehr: „offline“ wird erst
  gemeldet, wenn ein Gerät länger als 2 Minuten weg ist (`OFFLINE_ALERT_AFTER`), „wieder online“ nur danach.
  Auch Regeln mit Auslöser offline/online warten diese Zeit ab.

## 1.12.4
- WLAN-Übernahme von der Original-Firmware: Mongoose OS hat zwei Dateisystem-Bereiche, ein Werksreset leert
  nur den aktiven. Bisher wurde der erste Treffer aus dem zweiten Bereich genommen – das konnte ein altes
  Passwort sein. Jetzt werden alle gefundenen Zugangsdaten (Chip-Speicher, beide Bereiche, Tasmota)
  gesammelt und beim ersten Start der Reihe nach je 25 s probiert, sichtbare Netze zuerst
- `Hermit.TestImport` zeigt alle gefundenen Einträge (`mgos_all`) und die probierten (`tried`)

## 1.12.3
- WLAN-Übernahme von der Original-Firmware: deren Konfiguration hat jetzt Vorrang vor dem SDK-Speicher
  (der kann einen alten Stand enthalten); feste IP nur, wenn IP, Maske und Gateway zusammenpassen
- Zugangspunkt bleibt erreichbar, während das Gerät das Heim-WLAN sucht: Suche nur noch alle 3 min für 30 s
  und nie, solange jemand mit dem Zugangspunkt verbunden ist
- Absturzschutz: nach 3 Abstürzen in Folge abgesicherter Start (keine Übernahme, kein MQTT, Zugangspunkt sofort)

## Hermit Cloud 1.2.1
- Updater: erneuert sich jetzt über einen Hilfscontainer – vorher blieb er nach einem Update, das ihn selbst
  betraf, gestoppt („Updater-Container läuft nicht“)

## Hermit Cloud 1.2.0
- **Wäsche:** Fertig-Erkennung für Waschmaschine, Trockner, Spülmaschine und beliebige Geräte – Läufe mit Dauer,
  Energie, Kosten und Spitzenleistung, Restzeit-Schätzung, Push bei „fertig“ und Erinnerung
- **Kosten:** Strompreis einstellbar, Euro überall neben kWh
- **Push** über ntfy (optional eigener Server per Compose-Profil) oder Telegram, Arten wählbar, Testnachricht
- **Räume** und Schalten je Raum
- **Zeitpläne** mit Uhrzeit oder Sonnenauf-/untergang, **Regeln** (Leistung, Schalter, Ereignis, online/offline,
  fertig/startet, URL-Aufruf) mit Zeitfenster, Verzögerung, automatischem Ausschalten und Push
- **Grundlast/Standby** je Gerät mit Kosten pro Jahr, **CSV-Export** (Energie, Leistung, Läufe)
- Leistungsverlauf 6 h bis 30 Tage mit Spitzenwerten und Zoom
- **Firmware-Übersicht** mit Update einzeln/alle, **Sicherung und Rücksicherung** der Geräte-Einstellungen
- **Benutzer mit Rollen** (Administrator, Benutzer, Betrachter)
- **PWA:** als App auf dem Handy-Startbildschirm

## Hermit Cloud 1.1.1 / Hermit OS 1.12.2
- Cloud: Nach einem Neustart der Cloud (z. B. Update) wurden abgezogene Geräte durch gespeicherte
  Broker-Nachrichten wieder als online angezeigt – gespeicherte Nachrichten zählen jetzt nicht mehr als Lebenszeichen
- Firmware: MQTT-Keepalive 30 s – ein abgezogenes Gerät erscheint nach ca. 45 s als offline

## Hermit Cloud 1.1.0
- Selbst-Update: Prüfung auf GitHub, Knopf „Jetzt aktualisieren“, automatische Installation zur eingestellten
  Stunde; neuer Container `hermit-cloud-updater` (git pull bzw. Archiv, Neubau, Neustart)

## 1.12.1
- Repo ist öffentlich: Auto-Update ohne Token, Hinweise zum Token nur noch für private Forks
- README überarbeitet (Download, Hermit Cloud mit Bild, Mitmachen, English summary), Issue-Vorlagen
- Hermit Cloud: Link „Energie“ nur bei Geräten mit Messung

## 1.12.0
- MQTT im Gen2-Format (optional): `MQTT.GetConfig/SetConfig/GetStatus`, Topics `…/online`, `…/rpc`,
  `…/events/rpc` (NotifyEvent/NotifyStatus), `…/status/<komponente>`, `…/info`; Karte „Cloud / MQTT“ unter System
- Neu: **Hermit Cloud** (`cloud/`) – Heim-Cloud als Docker-Paket mit Mosquitto: Geräteübersicht, Schalten,
  Energieverlauf (24 h, Tage, Monate, je Gerät) und Meldungen (Überlast, Übertemperatur, offline)

## 1.11.0
- Relais bleibt bei Software-Neustart (Update, Neustart-Befehl, Absturz) im bisherigen Zustand – wie bei der
  Original-Firmware. Der Arduino-Core setzte vorher alle GPIOs beim Start auf Eingang.
- Updates deshalb auch bei eingeschaltetem Relais (alle Geräte); die 20-W-Wartegrenze der Messfirmware entfällt

## 1.10.2
- Messfirmware: Auto-Update und Update per RPC trotz dauerhaft angezogenem Relais; automatisch erst bei Last unter 20 W.
  Beim Neustart fällt das Relais ca. 1 s ab, eine gespeicherte Schutzabschaltung bleibt erhalten.

## 1.10.1
- Messfirmware auch für den Shelly Plug (16 A): `hermit-plug-meter` (Reset am Gerätetaster, ohne Temperaturschutz)

## 1.10.0
- Neue Messfirmware für Shelly 1PM (`hermit-1pm-meter`) und Plug S (`hermit-plugs-meter`): nur
  Energiemessung, Relais dauerhaft an, nicht fernschaltbar; Schutzabschaltung bei Überlast/Übertemperatur
  bleibt gespeichert und wird nur am Taster bzw. SW-Eingang zurückgesetzt (Ereignis `switch.reset`)
- Flasher: Option „Messfirmware“ (`--meter`)

## 1.9.0
- Neues Gerät: Shelly Plug (16 A, `SHPLG-1`/`SHPLG2-1`) als `hermit-plug` – Relais GPIO4, Taster GPIO12,
  HLW8012-Leistungsmessung (12,53 W/Hz), LEDs rot/blau
- LED-Polarität je Gerät einstellbar (`LED_ON_LEVEL`)
- Tasmota-`PowerCal` wird je nach Messchip (BL0937/HLW8012) richtig umgerechnet
- Flasher: Plug von Original-Firmware (mg2tasmota-ShellyPlug2) und von Tasmota

## 1.8.7
- Geräte ohne Eingang (Duo) bieten keine Eingangs-Ereignisse mehr für Aktionen an
- Dokumentation neu gegliedert: README, `docs/FLASHEN.md`, `docs/GERAETE.md`, `docs/API.md`

## 1.8.6
- Duo: Regler und Farbknöpfe schalten die Lampe nicht mehr ein
- Duo: Reiter „Licht“ statt „Schalter“, nur passende Einstellungen

## 1.8.5
- Duo: zwei Weißkanäle (GPIO5 kalt, GPIO4 warm) statt Helligkeit/Farbtemperatur – Ein/Aus und Dimmen funktionieren
- Duo: WLAN-Reset zählt nur echte Stromunterbrechungen
- `Sys.GetStatus` meldet `reset_reason`

## 1.8.4
- Diagnose `Hermit.Gpio` für unbekannte Hardware

## 1.8.3
- Feste IP wird aus Original-Firmware und Tasmota übernommen
- Flasher sucht das Gerät nach dem Flashen per MAC-Adresse, falls es eine neue IP hat
- Duo: Anzeige „Eingang SW“ entfällt

## 1.8.2
- WLAN-Übernahme aus der Original-Firmware erkennt die Mongoose-Schreibweise mit Leerzeichen
- Diagnose `Hermit.TestImport`

## 1.8.1
- Plug S: Spannung und Strom waren vertauscht (SEL HIGH = Spannung)

## Flasher
- Grafische Oberfläche mit Netzsuche (`Hermit-Flasher.pyw`), EXE-Bau per `tools/build_exe.bat`
- mg2hermit wird unkomprimiert gepackt (die Original-Firmware kann kein DEFLATE)
- Port wird nach Abbruch freigegeben und unter Windows exklusiv belegt
- Protokoll zeigt OTA-Antwort, Update-Status, jede Verbindung und einen Selbsttest
- Ein Zip-Paket pro Modell

## 1.8.0
- Shelly Duo (E27/GU10) mit `cct:0` wie die Duo Bulb Gen3, Gen1-Endpunkt `/light/0`
- WLAN-Übernahme nur noch beim allerersten Start

## 1.7.0
- Shelly Plug S mit Leistung, Spannung, Strom, cos φ, Gerätetaster und LEDs

## 1.6.0
- Flash-Tool `hermit_flash.py`: Original-Firmware (mg2hermit), Tasmota, Loader, Hermit OS
- WLAN-Übernahme aus der Konfiguration der Original-Firmware

## 1.5.x
- Hermit Loader für den direkten Wechsel von Tasmota (ca. 230 KB)
- WLAN-Übernahme aus den Tasmota-Einstellungen und dem WLAN-Speicher des ESP

## 1.4.x
- Auto-Update über `update.json` mit SHA-256-Prüfung, `Shelly.CheckForUpdate`/`Shelly.Update`
- Eingangsdiagnose und Eingangsfilter Wechselspannung/Pegel

## 1.3.0
- Add-on-Variante: Gen1-Temperatur-Add-on als potenzialfreier Taster (`input:100`)

## 1.2.0
- Umbenennung in Hermit OS

## 1.1.0
- 1PM: Standardkalibrierung für den BL0937 (vorher ca. 7-fach zu hoch), Kalibrierung über Referenz,
  Tasmota-`PowerCal` oder Faktor, bleibt bei Werkseinstellungen erhalten

## 1.0.0
- Erste Version für Shelly 1 und 1PM: Gen2-RPC, Webhooks, Weboberfläche, OTA, Energiemessung
