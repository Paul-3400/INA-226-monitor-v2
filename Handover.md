
# Handover – INA226-Monitor: Mobile Messeinheit

> Autor: Paul Simmen mit Vibe (GLM-5-latest-short), 07.10.2026
> Sitzungen vom 02.–08.10.2026 – Evaluation, Aufbau und Inbetriebnahme der mobilen Mess-Einheit
> Status: **System in Betrieb – vollständig automatisiert (Autostart via systemd), End-to-End getestet (Hardware, Firmware, Broker, Dashboard, Verlauf, CSV-Aufzeichnung)**

---

## 1. Architektur (final, umgesetzt)

| Einheit | Komponenten | Funktion | Status |
| --- | --- | --- | --- |
| Mess-Einheit | Seeed Studio XIAO ESP32S3 + 2 × INA-226 China-Modul (R010), LiPo an Bat+/Bat− | Misst auf MQTT-Abruf Ströme/Spannungen beider Kanäle | ✅ in Betrieb |
| Steuer-Einheit | Raspberry Pi Zero 2 W (RpPi2W-002, Pi OS 13 Trixie 64-bit) mit Mosquitto + Flask | Triggert Messungen, Dashboard, Verlaufsgrafik, CSV-Speicher | ✅ in Betrieb |
| Verbindung | Heim-WLAN (MQTT) | Dauerhaft verbunden (kein Deep-Sleep) | ✅ |

**Architektur-Entscheid (03.10.2026):** Die ursprünglich geplanten M5Stack-Module und der HW617/TCA9548A-Multiplexer entfallen. Zwei generische INA-226-Module (China, 20×27 mm, Schraubklemmen) erhalten über A0/A1-Lötstellen unterschiedliche I²C-Adressen – kein Multiplexer nötig, Betrieb direkt am 3V3-Pin des XIAO.

---

## 2. Betriebsmodus: Pull statt Push

1. Pi published Trigger auf `ina226/cmd` (Payload `{"trigger": <unix-zeit>}`, nie retained – als Nummer dient die Unix-Zeit, damit der Zähler auch nach einem App-Neustart immer grösser bleibt als der letzte Stand des XIAO)
2. XIAO misst beide Kanäle, published JSON auf `ina226/1a` und `ina226/10a`
3. XIAO verwirft veraltete/doppelte Trigger (Counter-Vergleich)
4. XIAO meldet Offline via Last-Will auf `ina226/status` (retained)

**Abfragefrequenz:** Dashboard-Presets **12 s (5×/Min), 30 s (2×/Min), 60 s (1×/Min), 300 s (12×/h)**, plus Sofortmessung («Jetzt messen») und Auto ein/aus.

---

## 3. Energiebilanz

- Kein Deep-Sleep (bewusste Entscheidung): WiFi dauerhaft verbunden (~20–30 mA Idle)
- LiPo am XIAO (Bat+/Bat−, Laden via USB-C) – Laufzeit hängt von der LiPo-Kapazität ab
- Referenzwert vom Batteriepack-Test (02.10.2026, BESTANDEN): 10'000 mAh Pack (5 V) → ~13–14 Tage Laufzeit

---

## 4. Stromversorgung (umgesetzt)

```
LiPo (3.7 V) ── Bat+ / Bat− (Unterseite XIAO ESP32S3)
Laden bei Bedarf über USB-C (5 V), Lade-IC auf dem XIAO
XIAO 3V3 ──► VCC beider INA-226-Module (2.7–5.5 V, offiziell abgedeckt)
```

Bei 3.3-V-Versorgung liegen die I²C-Pull-ups automatisch auf 3.3 V → saubere Pegel, keine 5-V-Schiene, keine Pegelanpassung.

---

## 5. Verkabelung – XIAO ESP32S3 ↔ INA-226 Module

### XIAO ESP32S3 Pinbelegung für I²C

| XIAO-Pin | Funktion | Verbindung |
| --- | --- | --- |
| **D1 (GPIO6)** | **SDA** (Default-I²C) | SDA beider INA-226-Module |
| **D2 (GPIO7)** | **SCL** (Default-I²C) | SCL beider Module |
| **3V3** | 3.3-V-Versorgung | VCC beider Module |
| **GND** | Masse | GND beider Module (Sternpunkt) |

> `Wire.begin()` ohne Argumente genügt – D1/D2 sind die Default-I²C-Pins des XIAO ESP32S3.

### INA-226 Modul-Anschlüsse (pro Modul)

| Modul-Pin | Verbindung |
| --- | --- |
| VCC | XIAO 3V3 |
| GND | XIAO GND |
| SDA / SCL | XIAO D1 / D2 |
| VIN / VOUT (Schraubklemmen) | Messstrecke (Quelle + → VIN, Verbraucher + → VOUT, gemeinsame Masse) |
| A0 / A1 | Adress-Lötstellen (gesetzt, siehe unten) |
| ALERT | nicht verwendet |

### Messstrecke (pro Modul)

```
Quelle (+) ── VIN ──[SHUNT R010]── VOUT ── Verbraucher (+)
Quelle (−) ── GND ◄────────────────────── Verbraucher (−)
```

### I²C-Adressen (umgesetzt und verifiziert)

| Modul | A1 | A0 | Adresse | Kanal |
| --- | --- | --- | --- | --- |
| Modul A | offen (GND) | offen (GND) | **0x40** | Kanal 1 |
| Modul B | gebrückt (VS) | gebrückt (VS) | **0x45** | Kanal 2 |

> I²C-Scan 07.10.2026: **0x40 und 0x45 bestätigt**, beide Chips als INA226 verifiziert (Manufacturer-ID 0x5449/TI, Die-ID 0x2260, Config-Reset-Wert 0x4127).

---

## 6. INA-226 Konfiguration (Shunt R010 = 0.01 Ω)

| Parameter | Wert |
| --- | --- |
| Shunt | R010 (0.01 Ω) |
| Max. Strom (±81.92 mV Shunt-Range) | **~8.2 A** pro Kanal |
| Current_LSB | 0.25 mA |
| **CAL-Register** | **2048** = 0.00512 / (0.00025 × 0.01) |
| Busspannungs-Messbereich | 0–36 V (unabhängig von VCC) |
| Auflösung Busspannung | 1.25 mV |
| Config-Register | 0x4527 (Averaging 64, 1.1 ms, Shunt+Bus continuous) |

> Beide Kanäle haben denselben Messbereich (kein separater Feinmesskanal wie bei M5Stack 0.1 Ω). Messrauschen im Nullpunkt: ±0.25–0.5 mA (1–2 LSB), normal.

---

## 7. Softwarestand (08.10.2026)

### Mess-Einheit: `messeinheit/ina226-messeinheit.ino` (Arduino, XIAO ESP32S3)

- Library: PubSubClient (Nick O'Leary), WiFi on-board
- MQTT: LWT auf `ina226/status`, Subscribe `ina226/cmd`, Publish `ina226/1a` + `ina226/10a` (JSON: voltage_V, current_mA, power_W, shunt_mV)
- Repo-Version mit generischen Konfigurationswerten (WLAN/IP ersetzt durch Platzhalter)
- Erster Flash und End-to-End-Test: 07.10.2026 erfolgreich

### Steuer-Einheit: `app.py` (Flask, Pi) + `templates/index.html`

- **MQTT-Subscriber:** empfängt `ina226/1a`, `ina226/10a`, `ina226/status` (paho-mqtt 2.x, Callback-API V2)
- **Trigger-Thread:** sendet `ina226/cmd` im einstellbaren Intervall (Auto ein/aus, `/api/auto`), Sofortmessung via `/api/measure`
- **Verlaufs-Speicher:** letzte 600 Punkte pro Kanal, persistiert in `data/history.csv` (Trim bei Übergrösse), beim Start neu geladen; Endpoint `/api/history?points=N`
- **CSV-Aufzeichnung:** `data/messung_YYYYMMDD_HHMMSS.csv`, **eine Zeile pro vollständigem Messzyklus** (geschrieben, sobald beide Kanäle eines Zyklus eingetroffen sind); Start/Stop via `/api/record/start|stop`, Dateiliste/Download/Delete via `/api/files`
- **Persistenz:** Verlauf und laufende Aufzeichnung überleben App-Neustarts (Fortsetzen im Append-Modus via `data/recording_state.json`)
- **Dashboard:** Kanal 1/Kanal 2 als Karten, Status der Mess-Einheit (online/offline), Intervall-Presets 12/30/60/300 s, Verlaufsgrafik (HTML-Canvas, ohne externe Bibliothek, Metrik umschaltbar V/mA/W), Aufzeichnungs-Panel mit Dateiliste und Download

### Raspberry Pi (RpPi2W-002)

- Pi OS 13 Trixie 64-bit (Neuinstallation 07.10.2026), Mosquitto mit `local.conf` (Listener 1883), IP 10.0.1.27
- Python-venv mit flask 3.x und paho-mqtt 2.1.0

---

## 8. Offene Punkte / To-dos

- [x] Batteriepack-Test (02.10.2026): BESTANDEN
- [x] Architektur-Entscheid: China-INA-226 statt M5Stack + Multiplexer (03.10.2026)
- [x] Schaltungsaufbau (07.10.2026): abgeschlossen, A0/A1 gesetzt (0x40/0x45)
- [x] I²C-Scan (07.10.2026): BESTANDEN – 0x40 und 0x45, Chips als INA226 verifiziert
- [x] Firmware XIAO ESP32S3 (07.10.2026): FERTIG UND GETESTET – erste Messung erfolgreich
- [x] Pi-Neuinstallation + Mosquitto + venv (07.10.2026)
- [x] Empfänger auf dem Pi (07.10.2026): MQTT-Subscriber in Flask-App integriert, Messwerte werden verarbeitet
- [x] Dashboard (07.10.2026): NEU – Kanal 1/2, Intervall-Presets, Verlaufsgrafik, Statusanzeige, Sofortmessung
- [x] CSV-Aufzeichnung (07.10.2026): eine Zeile pro Messzyklus, Panel mit Start/Stop/Download
- [x] systemd-Service installiert (07.10.2026): `active (running)` nach Reboot bestätigt – Autostart nach Boot/Stromausfall, Log via `journalctl -u ina226-monitor -f`
- [x] Verlauf persistiert (08.10.2026): jede Messung landet in `data/history.csv`, App-Start lädt die letzten 600 Punkte neu; laufende CSV-Aufzeichnung wird nach Neustart im Append-Modus fortgesetzt (`data/recording_state.json`)
- [ ] Kalibrierung verifizieren: Messung eines bekannten Stroms (z. B. Widerstandslast) gegen CAL 2048, Vergleich mit digitalen Referenzmessgeräten (Dauerbetriebs-Auswertung läuft seit 07.10.2026)
- [ ] LiPo-Kapazität klären → Laufzeitprognose der Mess-Einheit

---

## 9. Benötigte Komponenten

| Komponente | Zweck | Status |
| --- | --- | --- |
| Seeed Studio XIAO ESP32S3 | Kern Mess-Einheit | ✅ verbaut |
| 2 × INA-226 China-Module (R010) | Messkanäle | ✅ verbaut (Bastelkiste) |
| LiPo-Akku | Versorgung via Bat+/Bat− | ⚠️ bereitzustellen (Kapazität offen) |
| 5-V-Quelle (USB) | Laden des LiPo | ✅ vorhanden |
| ~~HW617 / TCA9548A~~ | ~~Multiplexer~~ | ❌ entfallen |
| ~~M5Stack UNIT INA226~~ | ~~Sensoren~~ | ❌ entfallen |
| RpPi2W-002 | Steuer-Einheit | ✅ neu aufgesetzt |

---

## 10. Verweise

- Repo: https://github.com/Paul-3400/INA-226-monitor-v2
- Nachbau-Anleitung: `README.md` | Bedienung: `Bedienungsanleitung.md`
- Firmware mit Anleitung: `messeinheit/ina226-messeinheit.ino` + `messeinheit/README.md`
- Steuer-Einheit: `app.py`, `templates/index.html`
- Datenblatt China-INA-226-Modul (PDF): VCC 2.7–5.5 V, A0/A1-Adresstabelle 0x40–0x4F, Messbereich 0–36 V
