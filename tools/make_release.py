#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 D.Koch – Pagurus OS
"""Baut alle Varianten, kopiert sie nach bin/ und schreibt update.json fuer das Auto-Update.

Aufruf im Projektverzeichnis:  python3 tools/make_release.py
Danach committen und pushen – die Geraete finden die neue Version ueber update.json.
"""
import gzip, hashlib, json, re, shutil, subprocess, pathlib, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
VARIANTS = {               # PlatformIO-Env -> Name in bin/ und Schluessel in update.json
    "shelly1": "hermit-1",
    "shelly1pm": "hermit-1pm",
    "shelly1_addon": "hermit-1-addon",
    "shelly1pm_addon": "hermit-1pm-addon",
    "plugs": "hermit-plugs",
    "plug": "hermit-plug",
    "duo": "hermit-duo",
    "dimmer2": "hermit-dimmer2",
    "shelly25": "hermit-25",
    "shelly25_cover": "hermit-25-cover",
    "shelly1pm_meter": "hermit-1pm-meter",
    "plugs_meter": "hermit-plugs-meter",
    "plug_meter": "hermit-plug-meter",
    "rfbridge": "hermit-rfbridge",
    "plug1m": "hermit-plug1m",
}
# 1 MB Flash: Update ueber den passenden 1-MB-Loader, Datei gepackt
ONE_MB = {"hermit-rfbridge": "hermit-loader-1m", "hermit-plug1m": "hermit-loader-1m-plug1m"}

ini = (ROOT / "platformio.ini").read_text()
version = re.search(r'FW_VERSION=\\"([0-9.]+)\\"', ini).group(1)

subprocess.run(["pio", "run"], cwd=ROOT, check=True)

# ESP32 (Klimaanlagen TCL und Midea, Heizungsanzeige AZ-Touch): eigenes PlatformIO-Projekt in esp32/, gleiche Versionsnummer
e32 = ROOT / "esp32"
e32ini = (e32 / "platformio.ini").read_text()
e32ini = re.sub(r' -DFW_VERSION_OVR=\\"[0-9.]+\\"', '', e32ini)   # Vorab-Version einer Variante endet mit dem Release
(e32 / "platformio.ini").write_text(re.sub(r'FW_VERSION=\\"[0-9.]+\\"', f'FW_VERSION=\\\\"{version}\\\\"', e32ini))
subprocess.run(["pio", "run", "-d", str(e32)], check=True)

bindir = ROOT / "bin"
bindir.mkdir(exist_ok=True)
for f in bindir.glob("*.bin*"):
    f.unlink()

files = {}
for env, name in VARIANTS.items():
    src = ROOT / ".pio" / "build" / env / "firmware.bin"
    dst = bindir / f"{name}.bin"
    shutil.copy(src, dst)
    data = dst.read_bytes()
    with gzip.open(bindir / f"{name}.bin.gz", "wb", compresslevel=9) as g:
        g.write(data)
    files[name] = {"url": f"bin/{name}.bin", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}

# ESP32: Programm fuer OTA (update.json) und Komplettabbild fuer das erste Flashen per Kabel (ab 0x0).
# Env -> (Name, Chip, Adresse des Bootloaders: ESP32 0x1000, ESP32-C3 0x0)
ESP32 = {"tclac": ("hermit-tclac-esp32", "esp32", "0x1000"),
         "midea_c3": ("hermit-midea-esp32c3", "esp32c3", "0x0"),
         "aztouch": ("pagurus-aztouch-esp32", "esp32", "0x1000")}
boot_app0 = next(pathlib.Path.home().glob(".platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin"))
esptool = str(next(pathlib.Path.home().glob(".platformio/packages/tool-esptoolpy/esptool.py")))
for env, (name, chip, boot) in ESP32.items():
    b32 = e32 / ".pio" / "build" / env
    shutil.copy(b32 / "firmware.bin", bindir / f"{name}.bin")
    data = (bindir / f"{name}.bin").read_bytes()
    files[name] = {"url": f"bin/{name}.bin", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    subprocess.run([sys.executable, esptool, "--chip", chip, "merge_bin", "-o", str(bindir / f"{name}-factory.bin"),
                    "--flash_mode", "dio", "--flash_size", "4MB",
                    boot, str(b32 / "bootloader.bin"), "0x8000", str(b32 / "partitions.bin"),
                    "0xe000", str(boot_app0), "0x10000", str(b32 / "firmware.bin")], check=True, stdout=subprocess.DEVNULL)

# Pagurus Loader – fuer den Wechsel von Tasmota; der 1-MB-Loader zusaetzlich als Zwischenstufe beim Update
for env, name in (("loader", "hermit-loader"), ("loader_1m", "hermit-loader-1m"), ("loader_1m_plug1m", "hermit-loader-1m-plug1m")):
    shutil.copy(ROOT / ".pio" / "build" / env / "firmware.bin", bindir / f"{name}.bin")
    with gzip.open(bindir / f"{name}.bin.gz", "wb", compresslevel=9) as g:
        g.write((bindir / f"{name}.bin").read_bytes())

# 1 MB (Layout 1m64): Sketch-Bereich 0x1000..0xEB000. Neue Datei muss neben die laufende passen.
up = lambda n: (n + 4095) // 4096 * 4096
AREA = 0xEB000 - 0x1000
for name, lname in ONE_MB.items():
    ldr = (bindir / f"{lname}.bin.gz").read_bytes()
    ldr_bin = (bindir / f"{lname}.bin").stat().st_size
    gz = (bindir / f"{name}.bin.gz").read_bytes()
    fw_bin = (bindir / f"{name}.bin").stat().st_size
    if AREA - up(fw_bin) < up(len(ldr)) or AREA - up(ldr_bin) < up(len(gz)):
        raise SystemExit(f"{name}: passt nicht ins 1-MB-Update (frei {(AREA - up(fw_bin)) // 1024} KB für Loader "
                         f"{len(ldr) // 1024} KB, frei {(AREA - up(ldr_bin)) // 1024} KB für Firmware {len(gz) // 1024} KB)")
    print(f"   {name}: 1-MB-Reserve {(AREA - up(fw_bin) - up(len(ldr))) // 1024} KB")
    files[name] = {"url": f"bin/{name}.bin.gz", "sha256": hashlib.sha256(gz).hexdigest(), "size": len(gz),
                   "loader": f"bin/{lname}.bin.gz", "loader_sha256": hashlib.sha256(ldr).hexdigest()}

# Uebergang: AZ-Touch hiess bis 1.19.4 hermit-aztouch-esp32 - alte Kennung zeigt auf die neue Datei
if "pagurus-aztouch-esp32" in files:
    files["hermit-aztouch-esp32"] = dict(files["pagurus-aztouch-esp32"])

(ROOT / "update.json").write_text(json.dumps({"version": version, "files": files}, separators=(",", ":")) + "\n")
print(f"update.json fuer Version {version} geschrieben")

# Kleine update.json pro Variante: alte Firmware (bis 1.17) liest die ganze Datei in den RAM und
# scheitert an der grossen Gesamtdatei. Adressen absolut, weil die Datei in einem Unterordner liegt.
RAW = "https://raw.githubusercontent.com/oeltensack/pagurus-os/main/"
udir = ROOT / "update"; udir.mkdir(exist_ok=True)
for old in udir.glob("*.json"):
    old.unlink()
for name, f in files.items():
    g = {k: (RAW + v if k in ("url", "loader") else v) for k, v in f.items()}
    (udir / f"{name}.json").write_text(json.dumps({"version": version, "files": {name: g}}, separators=(",", ":")) + "\n")

# Pro Modell eine Zip: Firmware (+Add-on-Variante), Loader, Flash-Tool, Anleitung
MODELS = {
    "Shelly-1":      ["hermit-1", "hermit-1-addon"],
    "Shelly-1PM":    ["hermit-1pm", "hermit-1pm-addon", "hermit-1pm-meter"],
    "Shelly-Plug-S": ["hermit-plugs", "hermit-plugs-meter"],
    "Shelly-Plug":   ["hermit-plug", "hermit-plug-meter"],
    "Shelly-Duo":    ["hermit-duo"],
    "Shelly-Dimmer-2": ["hermit-dimmer2"],
    "Shelly-2.5":    ["hermit-25", "hermit-25-cover"],
    "Sonoff-RF-Bridge": ["hermit-rfbridge"],
    "Steckdose-1MB-ESP8285": ["hermit-plug1m"],
}
EXTRA = {"Klima-TCL-ESP32": ["hermit-tclac-esp32.bin", "hermit-tclac-esp32-factory.bin"],
         "Klima-Midea-ESP32-C3": ["hermit-midea-esp32c3.bin", "hermit-midea-esp32c3-factory.bin"],
         "Heizungsanzeige-AZ-Touch": ["pagurus-aztouch-esp32.bin", "pagurus-aztouch-esp32-factory.bin"]}
dist = ROOT / "dist"
dist.mkdir(exist_ok=True)
for f in dist.glob("*.zip"):
    f.unlink()
for model, names in MODELS.items():
    top = f"Pagurus-OS-{version}-{model}"
    out = dist / f"{top}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.write(bindir / f"{n}.bin", f"{top}/bin/{n}.bin")
            z.write(bindir / f"{n}.bin.gz", f"{top}/bin/{n}.bin.gz")
        ld = next((ONE_MB[n] for n in names if n in ONE_MB), "hermit-loader")
        z.write(bindir / f"{ld}.bin.gz", f"{top}/bin/{ld}.bin.gz")
        z.write(ROOT / "tools" / "pagurus_flash.py", f"{top}/tools/pagurus_flash.py")
        z.write(ROOT / "tools" / "pagurus_flash_gui.py", f"{top}/tools/pagurus_flash_gui.py")
        z.write(ROOT / "Pagurus-Flasher.pyw", f"{top}/Pagurus-Flasher.pyw")
        z.write(ROOT / "tools" / "pagurus_scanner.py", f"{top}/tools/pagurus_scanner.py")
        z.write(ROOT / "Pagurus-Scanner.pyw", f"{top}/Pagurus-Scanner.pyw")
        z.write(ROOT / "tools" / "build_exe.bat", f"{top}/tools/build_exe.bat")
        z.write(ROOT / "README.md", f"{top}/README.md")
        z.write(ROOT / "CHANGELOG.md", f"{top}/CHANGELOG.md")
        z.write(ROOT / "LICENSE", f"{top}/LICENSE")
        for d in sorted((ROOT / "docs").glob("*.md")):
            z.write(d, f"{top}/docs/{d.name}")
    print("  ", out.name)


# Scanner einzeln (ohne Firmware)
sv = re.search(r'VERSION = "([^"]+)"', (ROOT / "tools" / "pagurus_scanner.py").read_text()).group(1)
top = f"Pagurus-Scanner-{sv}"
with zipfile.ZipFile(dist / f"{top}.zip", "w", zipfile.ZIP_DEFLATED) as z:
    z.write(ROOT / "Pagurus-Scanner.pyw", f"{top}/Pagurus-Scanner.pyw")
    z.write(ROOT / "tools" / "pagurus_scanner.py", f"{top}/tools/pagurus_scanner.py")
    z.write(ROOT / "tools" / "build_scanner.bat", f"{top}/tools/build_scanner.bat")
    z.write(ROOT / "docs" / "SCANNER.md", f"{top}/SCANNER.md")
    z.write(ROOT / "LICENSE", f"{top}/LICENSE")
print("  ", f"{top}.zip")


# ESP32-Klima: Programm (OTA) + Komplettabbild (Kabel) + Anleitung
for model, fnames in EXTRA.items():
    top = f"Pagurus-OS-{version}-{model}"
    out = dist / f"{top}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n in fnames:
            z.write(bindir / n, f"{top}/bin/{n}")
        z.write(ROOT / "esp32" / "README.md", f"{top}/README.md")
        z.write(ROOT / "LICENSE", f"{top}/LICENSE")
    print("  ", out.name)
