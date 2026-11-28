// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 D.Koch – Pagurus OS
// Pagurus OS fuer ESP32 – Klimaanlagen am UART des WLAN-Moduls. Gemeinsamer Kern, die Anlage selbst
// steckt in ac_tcl.h (TCL/Kesser, ESP32 mit DHT22) bzw. ac_midea.h (Midea/Dimstal, ESP32-C3).
// Variante DEV_DISPLAY: Heizungsanzeige auf dem AZ-Touch MOD (disp_aztouch.h) statt Klimaanlage.
// Spricht dieselbe Schnittstelle wie Pagurus OS auf den Shellys: JSON-RPC ueber HTTP und MQTT
// (Gen2-Format), Updates aus update.json mit SHA-256-Pruefung.
//   climate:0      Klimaanlage (output = an/aus, mode, target_C, current_C, fan, swing …)
//   temperature:0  DHT22 (nur TCL-Variante)
//   humidity:0     DHT22 (nur TCL-Variante)
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Update.h>
#include <mbedtls/sha256.h>
#include <time.h>
#ifdef DEV_DISPLAY
#include "webui_disp_gz.h"
#else
#include "webui_gz.h"
#endif

#ifdef FW_VERSION_OVR                   // einzelne Variante vorab mit eigener Version (platformio.ini)
#undef FW_VERSION
#define FW_VERSION FW_VERSION_OVR
#endif
#ifndef FW_VERSION
#define FW_VERSION "0.0.0"
#endif
#define DEF_UPD_URL "https://raw.githubusercontent.com/oeltensack/pagurus-os/main/update.json"

#if defined(DEV_DISPLAY)
// Heizungsanzeige AZ-Touch MOD 2,4" (ESP32)
#define DEV_PREFIX  "pagurus-aztouch"
#define DEV_MODEL   "PAGURUS-AZTOUCH-ESP32"
#define DEV_VARIANT "pagurus-aztouch-esp32"
#define DEV_APP     "HeatDisplay"
#define DEF_BEEP    false
#elif defined(AC_MIDEA)
// Midea/Dimstal am ESP32-C3 – Belegung wie in der bisherigen ESPHome-Konfiguration
#define DEV_PREFIX  "hermit-midea"
#define DEV_MODEL   "HERMIT-MIDEA-ESP32C3"
#define DEV_VARIANT "hermit-midea-esp32c3"
#define DEV_APP     "MideaAc"
#define PIN_AC_TX   21
#define PIN_AC_RX   20
#define DEF_BEEP    false
#else
// TCL/Kesser am ESP32 – Belegung wie in der bisherigen ESPHome-Konfiguration
#define DEV_PREFIX  "hermit-tclac"
#define DEV_MODEL   "HERMIT-TCLAC-ESP32"
#define DEV_VARIANT "hermit-tclac-esp32"
#define DEV_APP     "TclAc"
#define PIN_AC_TX   16
#define PIN_AC_RX   17
#define PIN_DHT     18
#define HAS_DHT     1
#define DEF_BEEP    true
#endif

#ifdef HAS_DHT
#include <DHT.h>
#endif

WebServer server(80);
DNSServer dns;
Preferences prefs;
WiFiClient mqNet;
PubSubClient mq(mqNet);
#ifdef HAS_DHT
DHT dht(PIN_DHT, DHT22);
#endif

String devId, mac;
bool apActive = false;
uint32_t apSince = 0, wifiLostAt = 0, rebootAt = 0;

struct Cfg {
  String name, ssid, pass;
  bool mqEnable = false; String mqServer, mqUser, mqPass, mqPrefix;
  String updUrl = DEF_UPD_URL; String updMode = "check";   // check | auto | off
  bool beep = DEF_BEEP;
  float tOffset = 0;                    // Korrektur DHT22
  bool swap = false;                    // TX/RX zur Klimaanlage tauschen
} cfg;

float dhtT = NAN, dhtH = NAN;
uint32_t dhtAt = 0, dhtOk = 0, dhtFail = 0;
bool mqDirty = false;
String updAvailVer, updAvailUrl, updAvailSha, updErr, updState = "idle";
uint32_t updNextCheck = 120000;
bool updPending = false;

// ======================= Einstellungen =======================
void loadCfg() {
  prefs.begin("pagurus", true);
  cfg.name = prefs.getString("name", "");
  cfg.ssid = prefs.getString("ssid", "");
  cfg.pass = prefs.getString("pass", "");
  cfg.mqEnable = prefs.getBool("mqEn", false);
  cfg.mqServer = prefs.getString("mqSrv", "");
  cfg.mqUser = prefs.getString("mqUser", "");
  cfg.mqPass = prefs.getString("mqPass", "");
  cfg.mqPrefix = prefs.getString("mqPre", "");
  cfg.updUrl = prefs.getString("updUrl", DEF_UPD_URL);
  cfg.updMode = prefs.getString("updMode", "check");
  cfg.beep = prefs.getBool("beep", DEF_BEEP);
  cfg.tOffset = prefs.getFloat("tOff", 0);
  cfg.swap = prefs.getBool("swap", false);
  prefs.end();
}

void saveCfg() {
  prefs.begin("pagurus", false);
  prefs.putString("name", cfg.name);
  prefs.putString("ssid", cfg.ssid);
  prefs.putString("pass", cfg.pass);
  prefs.putBool("mqEn", cfg.mqEnable);
  prefs.putString("mqSrv", cfg.mqServer);
  prefs.putString("mqUser", cfg.mqUser);
  prefs.putString("mqPass", cfg.mqPass);
  prefs.putString("mqPre", cfg.mqPrefix);
  prefs.putString("updUrl", cfg.updUrl);
  prefs.putString("updMode", cfg.updMode);
  prefs.putBool("beep", cfg.beep);
  prefs.putFloat("tOff", cfg.tOffset);
  prefs.putBool("swap", cfg.swap);
  prefs.end();
}

String jstr(JsonVariantConst v, const char* def) { return v.is<const char*>() ? String(v.as<const char*>()) : String(def); }
int idxOf(const char* const* arr, int n, const String& s) { for (int i = 0; i < n; i++) if (s == arr[i]) return i; return -1; }

#if defined(DEV_DISPLAY)
#include "disp_aztouch.h"
#elif defined(AC_MIDEA)
#include "ac_midea.h"
#else
#include "ac_tcl.h"
#endif

// ======================= Status =======================
#ifndef DEV_DISPLAY
void climateStatus(JsonObject o) {
  o["id"] = 0;
  acStatus(o);
#ifdef HAS_DHT
  if (!acValid()) return;
  if (!isnan(dhtT)) o["ext_temperature_C"] = roundf((dhtT + cfg.tOffset) * 10) / 10;   // DHT22 fuer die Karte
  if (!isnan(dhtH)) o["ext_humidity"] = roundf(dhtH);
#endif
}
#endif
#ifdef HAS_DHT
void tempStatus(JsonObject o) { o["id"] = 0; o["reads_ok"] = dhtOk; o["reads_failed"] = dhtFail; if (!isnan(dhtT)) o["tC"] = roundf((dhtT + cfg.tOffset) * 10) / 10; else o["errors"].add("read"); }
void humStatus(JsonObject o) { o["id"] = 0; if (!isnan(dhtH)) o["rh"] = roundf(dhtH * 10) / 10; else o["errors"].add("read"); }
#endif

void deviceInfo(JsonObject o) {
  o["name"] = cfg.name.length() ? cfg.name : (const char*)nullptr;
  o["id"] = devId; o["mac"] = mac; o["model"] = DEV_MODEL; o["gen"] = 2;
  o["fw_id"] = String(FW_VERSION) + "-pagurus"; o["ver"] = FW_VERSION; o["app"] = DEV_APP;
  o["variant"] = DEV_VARIANT; o["auth_en"] = false;
}

void sysStatus(JsonObject o) {
  o["mac"] = mac; o["uptime"] = millis() / 1000;
  o["ram_free"] = ESP.getFreeHeap(); o["ram_size"] = ESP.getHeapSize();
  o["fs_size"] = 0; o["fs_free"] = 0;
  JsonObject u = o["available_updates"].to<JsonObject>();
  if (updAvailVer.length()) u["stable"]["version"] = updAvailVer;
  o["restart_required"] = false;
  o["upd_state"] = updState;
  if (updErr.length()) o["upd_error"] = updErr;
}

void wifiStatus(JsonObject o) {
  bool c = WiFi.status() == WL_CONNECTED;
  o["sta_ip"] = c ? WiFi.localIP().toString() : (const char*)nullptr;
  o["status"] = c ? "got ip" : "disconnected";
  o["ssid"] = c ? WiFi.SSID() : (const char*)nullptr;
  if (c) o["rssi"] = WiFi.RSSI();
  o["tx_dbm"] = WiFi.getTxPower() / 4.0;
  o["ap"] = apActive;
}

void fullStatus(JsonObject o) {
  sysStatus(o["sys"].to<JsonObject>());
  wifiStatus(o["wifi"].to<JsonObject>());
  o["mqtt"]["connected"] = mq.connected();
#ifdef DEV_DISPLAY
  dispStatus(o["display:0"].to<JsonObject>());
#else
  climateStatus(o["climate:0"].to<JsonObject>());
#endif
#ifdef HAS_DHT
  tempStatus(o["temperature:0"].to<JsonObject>());
  humStatus(o["humidity:0"].to<JsonObject>());
#endif
}

void fullConfig(JsonObject o) {
  o["sys"]["device"]["name"] = cfg.name;
  o["sys"]["device"]["mac"] = mac;
  JsonObject m = o["mqtt"].to<JsonObject>();
  m["enable"] = cfg.mqEnable; m["server"] = cfg.mqServer; m["user"] = cfg.mqUser;
  m["topic_prefix"] = cfg.mqPrefix.length() ? cfg.mqPrefix : devId;
  o["wifi"]["sta"]["ssid"] = cfg.ssid;
#ifdef DEV_DISPLAY
  dispConfig(o["display:0"].to<JsonObject>());
#else
  acConfig(o["climate:0"].to<JsonObject>());
#endif
#ifdef HAS_DHT
  o["temperature:0"]["offset_C"] = cfg.tOffset;
#endif
  o["update"]["url"] = cfg.updUrl; o["update"]["mode"] = cfg.updMode;
}

// ======================= MQTT (Gen2-Format) =======================
uint32_t mqNext = 0, mqLast = 0, mqBackoff = 5000;
String mqPre() { return cfg.mqPrefix.length() ? cfg.mqPrefix : devId; }

void mqPub(const String& topic, JsonDocument& d, bool retain = false) {
  if (!mq.connected()) return;
  String s; serializeJson(d, s);
  mq.publish(topic.c_str(), s.c_str(), retain);
}

void mqStatusAll() {
#ifdef DEV_DISPLAY
  JsonDocument a; dispStatus(a.to<JsonObject>()); mqPub(mqPre() + "/status/display:0", a, true);
#else
  JsonDocument a; climateStatus(a.to<JsonObject>()); mqPub(mqPre() + "/status/climate:0", a, true);
#endif
#ifdef HAS_DHT
  JsonDocument b; tempStatus(b.to<JsonObject>());    mqPub(mqPre() + "/status/temperature:0", b, true);
  JsonDocument c; humStatus(c.to<JsonObject>());     mqPub(mqPre() + "/status/humidity:0", c, true);
#endif
  JsonDocument d; sysStatus(d.to<JsonObject>());     mqPub(mqPre() + "/status/sys", d, true);
  JsonDocument n;
  n["src"] = devId; n["dst"] = mqPre() + "/events"; n["method"] = "NotifyStatus";
  n["params"]["ts"] = (double)time(nullptr);
#ifdef DEV_DISPLAY
  dispStatus(n["params"]["display:0"].to<JsonObject>());
#else
  climateStatus(n["params"]["climate:0"].to<JsonObject>());
#endif
  mqPub(mqPre() + "/events/rpc", n);
  mqLast = millis();
}

void mqInfo() {
  JsonDocument d; JsonObject o = d.to<JsonObject>();
  deviceInfo(o); o["ip"] = WiFi.localIP().toString();
  mqPub(mqPre() + "/info", d, true);
}

int rpcCall(const String& method, JsonVariantConst p, JsonDocument& out, String& err);

void mqCallback(char* topic, uint8_t* payload, unsigned int len) {
  JsonDocument req, out, res;
  if (deserializeJson(req, payload, len)) return;
  String method = jstr(req["method"], ""), src = jstr(req["src"], "");
  if (!method.length()) return;
  String err;
  int code = rpcCall(method, req["params"], out, err);
  if (!src.length()) return;
  res["id"] = req["id"]; res["src"] = devId; res["dst"] = src;
  if (code == 0) res["result"] = out; else { res["error"]["code"] = code; res["error"]["message"] = err; }
  mqPub(src + "/rpc", res);
  mqDirty = true;
}

void handleMqtt() {
  if (!cfg.mqEnable) { if (mq.connected()) mq.disconnect(); return; }
  if (WiFi.status() != WL_CONNECTED) return;
  if (!mq.connected()) {
    if ((int32_t)(millis() - mqNext) < 0) return;
    String host = cfg.mqServer; int port = 1883;
    int c = host.lastIndexOf(':');
    if (c > 0) { port = host.substring(c + 1).toInt(); host = host.substring(0, c); }
    if (!host.length()) { mqNext = millis() + 30000; return; }
    mq.setServer(host.c_str(), port);
    mq.setBufferSize(2048); mq.setKeepAlive(30); mq.setSocketTimeout(5);
    mq.setCallback(mqCallback);
    String will = mqPre() + "/online";
    bool ok = cfg.mqUser.length()
      ? mq.connect(devId.c_str(), cfg.mqUser.c_str(), cfg.mqPass.c_str(), will.c_str(), 0, true, "false")
      : mq.connect(devId.c_str(), nullptr, nullptr, will.c_str(), 0, true, "false");
    if (!ok) { mqNext = millis() + mqBackoff; mqBackoff = min<uint32_t>(mqBackoff * 2, 30000); return; }
    mqBackoff = 5000;
    mq.publish(will.c_str(), "true", true);
    mq.subscribe((mqPre() + "/rpc").c_str());
    mqInfo(); mqStatusAll();
    return;
  }
  mq.loop();
  if (mqDirty || millis() - mqLast > 30000) { mqDirty = false; mqStatusAll(); }
}

// ======================= Updates =======================
String resolveUrl(const String& base, const String& rel) {
  if (rel.startsWith("http")) return rel;
  int s = base.lastIndexOf('/');
  return (s > 8 ? base.substring(0, s + 1) : base + "/") + rel;
}

int verCmp(const String& a, const String& b) {
  int ia = 0, ib = 0;
  while (ia < (int)a.length() || ib < (int)b.length()) {
    long x = a.substring(ia).toInt(), y = b.substring(ib).toInt();
    if (x != y) return x < y ? -1 : 1;
    int da = a.indexOf('.', ia), db = b.indexOf('.', ib);
    ia = da < 0 ? a.length() : da + 1; ib = db < 0 ? b.length() : db + 1;
  }
  return 0;
}

bool openUrl(HTTPClient& http, WiFiClientSecure& sec, WiFiClient& plain, const String& url) {
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  http.setTimeout(15000);
  if (url.startsWith("https")) { sec.setInsecure(); return http.begin(sec, url); }   // Echtheit ueber SHA-256
  return http.begin(plain, url);
}

bool updCheck() {
  updErr = "";
  WiFiClientSecure sec; WiFiClient plain; HTTPClient http;
  if (!openUrl(http, sec, plain, cfg.updUrl)) { updErr = "URL ungültig"; return false; }
  http.useHTTP10(true);
  int code = http.GET();
  if (code != 200) { updErr = "update.json: HTTP " + String(code); http.end(); return false; }
  JsonDocument filter; filter["version"] = true; filter["files"][DEV_VARIANT] = true;
  JsonDocument d;
  DeserializationError e = deserializeJson(d, http.getStream(), DeserializationOption::Filter(filter));
  http.end();
  if (e) { updErr = String("update.json ungültig (") + e.c_str() + ")"; return false; }
  JsonVariantConst f = d["files"][DEV_VARIANT];
  String ver = jstr(d["version"], "");
  if (!ver.length() || !f["url"].is<const char*>()) { updErr = "Keine Datei für " DEV_VARIANT; return false; }
  if (verCmp(ver, FW_VERSION) > 0) {
    updAvailVer = ver; updAvailUrl = resolveUrl(cfg.updUrl, f["url"].as<const char*>());
    updAvailSha = jstr(f["sha256"], ""); updAvailSha.toLowerCase();
  } else { updAvailVer = ""; }
  return true;
}

String updInstall() {
  if (!updAvailVer.length() && !updCheck()) return updErr;
  if (!updAvailVer.length()) return "Firmware ist aktuell";
  updState = "updating";
  WiFiClientSecure sec; WiFiClient plain; HTTPClient http;
  if (!openUrl(http, sec, plain, updAvailUrl)) { updState = "idle"; return "URL ungültig"; }
  http.useHTTP10(true);   // kein Chunked-Encoding (GitHub-Cache liefert beim ersten Abruf sonst Chunks)
  int code = http.GET();
  if (code != 200) { http.end(); updState = "idle"; return "Download: HTTP " + String(code); }
  int len = http.getSize();
  if (!Update.begin(len > 0 ? len : UPDATE_SIZE_UNKNOWN)) { http.end(); updState = "idle"; return "Kein Platz für das Update"; }
  mbedtls_sha256_context ctx; mbedtls_sha256_init(&ctx); mbedtls_sha256_starts(&ctx, 0);
  WiFiClient* s = http.getStreamPtr();
  uint8_t buf[1024]; int got = 0; uint32_t last = millis();
  // weiterlesen, solange Daten im Puffer sind – GitHub schliesst die Verbindung oft vor dem letzten Lesen
  while ((len < 0 || got < len) && (http.connected() || s->available())) {
    if (millis() - last > 20000) break;                       // 20 s ohne Fortschritt: abbrechen
    int n = s->available();
    if (n > 0) n = s->read(buf, min(n, (int)sizeof buf));     // read() statt readBytes(): kehrt sofort zurueck
    if (n > 0) {
      mbedtls_sha256_update(&ctx, buf, n);
      if (Update.write(buf, n) != (size_t)n) break;
      got += n; last = millis();
    } else delay(2);
  }
  http.end();
  uint8_t h[32]; mbedtls_sha256_finish(&ctx, h); mbedtls_sha256_free(&ctx);
  char hex[65]; for (int i = 0; i < 32; i++) sprintf(hex + i * 2, "%02x", h[i]);
  if ((len > 0 && got != len) || (updAvailSha.length() && updAvailSha != hex)) {
    Update.abort(); updState = "idle";
    return (len > 0 && got != len) ? "Download abgebrochen (" + String(got) + "/" + String(len) + ")"
                                   : "SHA-256 stimmt nicht – Update verworfen";
  }
  if (!Update.end(true)) { updState = "idle"; return "Update fehlgeschlagen (" + String(Update.getError()) + ")"; }
  updState = "done"; rebootAt = millis() + 1500;
  return "";
}

void handleUpdates() {
  if (WiFi.status() != WL_CONNECTED || cfg.updMode == "off") return;
  if ((int32_t)(millis() - updNextCheck) < 0) return;
  updNextCheck = millis() + 6UL * 3600 * 1000;
  if (updCheck() && updAvailVer.length() && cfg.updMode == "auto") updPending = true;
}

// ======================= RPC =======================
#define ERR(c, m) do { err = m; return c; } while (0)

int rpcCall(const String& method, JsonVariantConst p, JsonDocument& out, String& err) {
  String m = method; m.toLowerCase();
  JsonObject o = out.to<JsonObject>();
  if (m == "shelly.getdeviceinfo") { deviceInfo(o); return 0; }
  if (m == "shelly.getstatus") { fullStatus(o); return 0; }
  if (m == "shelly.getconfig") { fullConfig(o); return 0; }
  if (m == "shelly.listmethods") {
    JsonArray a = o["methods"].to<JsonArray>();
    for (const char* x : {"Shelly.GetDeviceInfo", "Shelly.GetStatus", "Shelly.GetConfig", "Shelly.Reboot",
                          "Shelly.CheckForUpdate", "Shelly.Update", "Sys.GetStatus", "Sys.SetConfig",
                          "WiFi.GetStatus", "WiFi.SetConfig", "WiFi.Scan", "MQTT.GetConfig", "MQTT.SetConfig",
#ifndef DEV_DISPLAY
                          "Climate.GetStatus", "Climate.Set", "Climate.Toggle", "Climate.SetConfig",
#endif
                          AC_METHODS
#ifdef HAS_DHT
                          "Temperature.GetStatus", "Temperature.SetConfig", "Humidity.GetStatus"
#endif
                          }) a.add(x);
    return 0;
  }
  if (m == "shelly.reboot") { rebootAt = millis() + 1000; return 0; }
  if (m == "sys.getstatus") { sysStatus(o); return 0; }
  if (m == "sys.setconfig") {
    if (p["config"]["device"]["name"].is<const char*>()) { cfg.name = p["config"]["device"]["name"].as<const char*>(); saveCfg(); }
    if (p["config"]["update"]["url"].is<const char*>()) cfg.updUrl = p["config"]["update"]["url"].as<const char*>();
    if (p["config"]["update"]["mode"].is<const char*>()) cfg.updMode = p["config"]["update"]["mode"].as<const char*>();
    saveCfg(); mqDirty = true;
    o["restart_required"] = false; return 0;
  }
  if (m == "wifi.getstatus") { wifiStatus(o); return 0; }
  if (m == "wifi.setconfig") {
    JsonVariantConst s = p["config"]["sta"];
    if (!s["ssid"].is<const char*>()) ERR(-103, "config.sta.ssid fehlt");
    cfg.ssid = s["ssid"].as<const char*>();
    if (s["pass"].is<const char*>()) cfg.pass = s["pass"].as<const char*>();
    saveCfg(); rebootAt = millis() + 1500;
    o["restart_required"] = true; return 0;
  }
  if (m == "wifi.scan") {
    int n = WiFi.scanNetworks();
    JsonArray a = o["results"].to<JsonArray>();
    for (int i = 0; i < n; i++) { JsonObject x = a.add<JsonObject>(); x["ssid"] = WiFi.SSID(i); x["rssi"] = WiFi.RSSI(i); }
    return 0;
  }
  if (m == "mqtt.getconfig") { JsonDocument t; fullConfig(t.to<JsonObject>()); out.set(t["mqtt"]); return 0; }
  if (m == "mqtt.setconfig") {
    JsonVariantConst c = p["config"];
    if (c["enable"].is<bool>()) cfg.mqEnable = c["enable"];
    if (c["server"].is<const char*>()) cfg.mqServer = c["server"].as<const char*>();
    if (c["user"].is<const char*>()) cfg.mqUser = c["user"].as<const char*>();
    if (c["pass"].is<const char*>()) cfg.mqPass = c["pass"].as<const char*>();
    if (c["topic_prefix"].is<const char*>()) cfg.mqPrefix = c["topic_prefix"].as<const char*>();
    if (cfg.mqPrefix == devId) cfg.mqPrefix = "";
    saveCfg(); mq.disconnect(); mqNext = 0;
    o["restart_required"] = false; return 0;
  }
  if (m == "shelly.checkforupdate") {
    if (!updCheck()) ERR(-114, updErr);
    if (updAvailVer.length()) o["stable"]["version"] = updAvailVer;
    return 0;
  }
  if (m == "shelly.update") { updPending = true; return 0; }
#ifndef DEV_DISPLAY
  if (m == "climate.getstatus") { climateStatus(o); return 0; }
  if (m == "climate.set") { String e = acSet(p); if (e.length()) ERR(-103, e); o["was_on"] = acPower(); return 0; }
  if (m == "climate.toggle") {
    JsonDocument q; q["on"] = !acPower();
    String e = acSet(q.as<JsonVariantConst>()); if (e.length()) ERR(-103, e); return 0;
  }
  if (m == "climate.setconfig") { acSetConfig(p["config"]); o["restart_required"] = false; return 0; }
#endif
  { String e; if (acRpc(m, p, o, e)) { if (e.length()) ERR(-103, e); mqDirty = true; return 0; } }
#ifdef HAS_DHT
  if (m == "temperature.getstatus") { tempStatus(o); return 0; }
  if (m == "temperature.setconfig") {
    if (p["config"]["offset_C"].is<float>()) { cfg.tOffset = p["config"]["offset_C"]; saveCfg(); }
    o["restart_required"] = false; return 0;
  }
  if (m == "humidity.getstatus") { humStatus(o); return 0; }
#endif
  ERR(-114, "Methode unbekannt: " + method);
}

// ======================= HTTP =======================
void sendJson(int code, JsonDocument& d) { String s; serializeJson(d, s); server.send(code, "application/json", s); }

void handleRpcPost() {
  JsonDocument req, out, res;
  if (deserializeJson(req, server.arg("plain"))) { res["error"]["code"] = -32700; res["error"]["message"] = "JSON ungültig"; sendJson(400, res); return; }
  String err;
  int code = rpcCall(jstr(req["method"], ""), req["params"], out, err);
  res["id"] = req["id"]; res["src"] = devId;
  if (code == 0) res["result"] = out; else { res["error"]["code"] = code; res["error"]["message"] = err; }
  sendJson(200, res);
}

void handleRpcGet(const String& method) {
  JsonDocument p, out;
  for (int i = 0; i < server.args(); i++) {
    String k = server.argName(i), v = server.arg(i);
    if (v == "true" || v == "false") p[k] = v == "true";
    else if (v.length() && (isdigit(v[0]) || v[0] == '-') && v.toFloat() == v.toFloat()) p[k] = v.toFloat();
    else if (v.startsWith("{") || v.startsWith("[")) { JsonDocument t; if (!deserializeJson(t, v)) p[k] = t; else p[k] = v; }
    else p[k] = v;
  }
  String err;
  int code = rpcCall(method, p.as<JsonVariantConst>(), out, err);
  if (code) { JsonDocument e; e["code"] = code; e["message"] = err; sendJson(500, e); return; }
  sendJson(200, out);
}

// ======================= WLAN =======================
// ESP32-C3 SuperMini: Quarz direkt an der Keramikantenne, schlecht angepasst. Mit voller Sendeleistung bricht die
// Verbindung staendig ab; 8,5 dBm (WIFI_TX_X4=34) laeuft stabil. Muss nach jedem WiFi.mode()/begin() neu gesetzt werden.
void applyTx() {
#ifdef WIFI_TX_X4
  WiFi.setTxPower((wifi_power_t)WIFI_TX_X4);
#endif
}

void startAP() {
  if (apActive) return;
  String ssid = String(DEV_PREFIX) + "-" + mac.substring(6);
  WiFi.mode(cfg.ssid.length() ? WIFI_AP_STA : WIFI_AP);
  applyTx();
  WiFi.softAPConfig(IPAddress(192, 168, 33, 1), IPAddress(192, 168, 33, 1), IPAddress(255, 255, 255, 0));
  WiFi.softAP(ssid.c_str());
  dns.start(53, "*", IPAddress(192, 168, 33, 1));
  apActive = true; apSince = millis();
}

void stopAP() {
  if (!apActive) return;
  dns.stop(); WiFi.softAPdisconnect(true); WiFi.mode(WIFI_STA); applyTx(); apActive = false;
}

void handleWifi() {
  if (!cfg.ssid.length()) { startAP(); return; }
  if (WiFi.status() == WL_CONNECTED) {
    wifiLostAt = 0;
    if (apActive && millis() - apSince > 300000) stopAP();   // nach Einrichtung 5 min AP, dann aus
    return;
  }
  if (!wifiLostAt) wifiLostAt = millis();
  if (millis() - wifiLostAt > 60000) startAP();             // 1 min kein WLAN: Zugangspunkt zum Einrichten
}

// ======================= Start =======================
void setup() {
#ifndef AC_MIDEA
  Serial.begin(115200);                     // nicht beim ESP32-C3: dort liegt die Klimaanlage auf den UART0-Pins
#endif
  uint8_t m[6]; WiFi.macAddress(m);
  char b[13]; sprintf(b, "%02x%02x%02x%02x%02x%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
  mac = String(b); mac.toUpperCase();
  devId = String(DEV_PREFIX) + "-" + String(b);
  loadCfg();
#ifdef DEV_DISPLAY
  dispBegin();
#else
  acBegin();
#endif
#ifdef HAS_DHT
  dht.begin();
#endif

  WiFi.persistent(false);
  WiFi.setHostname(devId.c_str());
  WiFi.mode(WIFI_STA);
  applyTx();
  if (cfg.ssid.length()) WiFi.begin(cfg.ssid.c_str(), cfg.pass.c_str());
  else startAP();
  applyTx();
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);                     // kein Modem-Sleep: sonst antwortet die Weboberflaeche traege
  configTzTime("CET-1CEST,M3.5.0,M10.5.0/3", "pool.ntp.org", "time.cloudflare.com");

  server.on("/", HTTP_GET, []() {             // Seite gepackt ausliefern (spart ~70 %)
    server.sendHeader("Cache-Control", "no-store");
    server.sendHeader("Content-Encoding", "gzip");
    server.send_P(200, "text/html; charset=utf-8", (const char*)INDEX_HTML_GZ, INDEX_HTML_GZ_LEN);
  });
  server.on("/rpc", HTTP_POST, handleRpcPost);
  // Firmware von Hand hochladen (System → Datei)
  server.on("/update", HTTP_POST, []() {
    bool ok = !Update.hasError();
    server.send(ok ? 200 : 500, "text/plain", ok ? "OK – Neustart" : "Fehler " + String(Update.getError()));
    if (ok) rebootAt = millis() + 1000;
  }, []() {
    HTTPUpload& u = server.upload();
#ifdef DEV_DISPLAY
    esp_task_wdt_reset();                     // grosse Datei: Watchdog nicht ausloesen
#endif
    if (u.status == UPLOAD_FILE_START) Update.begin(UPDATE_SIZE_UNKNOWN);
    else if (u.status == UPLOAD_FILE_WRITE) Update.write(u.buf, u.currentSize);
    else if (u.status == UPLOAD_FILE_END) Update.end(true);
    else if (u.status == UPLOAD_FILE_ABORTED) Update.abort();
  });
  server.on("/shelly", HTTP_GET, []() { JsonDocument d; deviceInfo(d.to<JsonObject>()); sendJson(200, d); });
  server.onNotFound([]() {
    String u = server.uri();
    if (u.startsWith("/rpc/")) { handleRpcGet(u.substring(5)); return; }
    if (apActive) { server.sendHeader("Location", "http://192.168.33.1/"); server.send(302); return; }
    server.send(404, "text/plain", "Nicht gefunden");
  });
  server.begin();
  MDNS.begin(devId.c_str());
  MDNS.addService("http", "tcp", 80);
}

void loop() {
  server.handleClient();
  if (apActive) dns.processNextRequest();
  handleWifi();
#ifdef DEV_DISPLAY
  dispLoop();
#else
  acLoop();
#endif
#ifdef HAS_DHT
  if (millis() - dhtAt > (dhtOk ? 30000UL : 5000UL) && millis() > 3000) {   // DHT22 braucht ~2 s nach dem Start
    dhtAt = millis();
    float t = dht.readTemperature(), h = dht.readHumidity();
    if (!isnan(t) && !isnan(h)) { dhtT = t; dhtH = h; dhtOk++; } else dhtFail++;
    mqDirty = true;
  }
#endif
  handleMqtt();
  handleUpdates();
  if (updPending) {
    updPending = false;
#ifdef DEV_DISPLAY
    dispUpdating();
#endif
    String e = updInstall();
    if (e.length()) updErr = e;
#ifdef DEV_DISPLAY
    if (e.length()) dispUpdateFailed(e);
#endif
  }
  if (rebootAt && (int32_t)(millis() - rebootAt) >= 0) ESP.restart();
  delay(2);
}
