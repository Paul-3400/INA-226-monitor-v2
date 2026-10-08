
# Bedienungsanleitung – INA226 Monitor v2

> Autor: Paul Simmen mit Vibe (GLM-5-latest-short), 08.10.2026
> Inbetriebnahme und Handhabung der Monitorstation, inklusive Befehlsreferenz

---

## 1. Die Station im Überblick

| Einheit | Bestandteile | Aufgabe |
| --- | --- | --- |
| **Mess-Einheit** | XIAO ESP32S3 + 2 × INA226, LiPo-Akku | misst auf Abruf zwei Stromkreise, sendet per WLAN |
| **Steuer-Einheit** | Raspberry Pi (RpPi2W-002) | fragt Messungen ab, zeigt Dashboard im Browser, speichert CSV |

Die Geräte kommunizieren über das Heim-WLAN (MQTT-Protokoll). Beide starten nach einem Stromausfall selbstständig neu.

---

## 2. Inbetriebnahme

1. **Steuer-Einheit:** Raspberry Pi mit Strom versorgen. Nach ca. 1 Minute läuft alles automatisch (Mosquitto-Broker und Monitor-Software starten von selbst).
2. **Mess-Einheit:** LiPo anschliessen bzw. XIAO einschalten – die Einheit verbindet sich mit dem WLAN.
3. **Dashboard öffnen:** im Browser `http://<Pi-IP>:5000` aufrufen (z. B. mit dem Handy im Heimnetz). Der grüne Punkt neben «Mess-Einheit: online» bestätigt die Verbindung.
4. **Erste Messung:** Knopf **«Jetzt messen»** drücken – die Kanalkarten zeigen innert 1–2 Sekunden Werte und den Zeitpunkt der Messung.

> **Tipp:** Die IP des Pi im Router fixieren (DHCP-Reservierung), dann ändert sich die Adresse nie.

---

## 3. Das Dashboard bedienen

### Statuszeile

- **Grüner Punkt / «online»:** Mess-Einheit verbunden und empfangsbereit
- **Roter Punkt / «offline»:** Mess-Einheit ausgeschaltet oder ohne WLAN

### Kanalkarten (Kanal 1 / Kanal 2)

Zeigen die letzte Messung je Kanal: **Spannung (V), Strom (mA), Leistung (W), Shunt-Spannung (mV)** plus Zeitstempel.

### Messung steuern

| Element | Funktion |
| --- | --- |
| **5×/Min (12 s)** / **2×/Min (30 s)** / **1×/Min (60 s)** / **12×/Std (300 s)** | Automatisches Messintervall wählen (aktives Preset blau markiert) |
| **Auto: an/aus** | Automatische Messungen ein-/ausschalten |
| **Jetzt messen** | Sofortige Einzelmessung, unabhängig vom Intervall |

### Verlauf (Grafik)

- Kurve zeigt beide Kanäle (Kanal 1 = blau, Kanal 2 = orange)
- **Zeithorizont:** letzte 60 / 120 / 300 Punkte wählbar
- **Messgrösse:** Spannung / Strom / Leistung umschaltbar
- Der Verlauf ist auf der SD-Karte des Pi gespeichert und überlebt Neustarts

### Aufzeichnung (CSV)

| Aktion | Beschreibung |
| --- | --- |
| **Aufzeichnung starten** | Schreibt pro Messzyklus eine Zeile in `data/messung_JJJJMMTT_HHMMSS.csv` |
| **Aufzeichnung stoppen** | Beendet die Datei (Status «Bereit») |
| **herunterladen** | CSV-Datei auf PC/Tablet laden (für Excel/Numbers) |
| **löschen** | Datei auf dem Pi entfernen |

Die Aufzeichnung läuft auch über Neustarts hinweg weiter (gleiche Datei wird fortgesetzt).

**Spaltentitel der CSV:** `Zeitstempel, Kanal1_Spannung_V, Kanal1_Strom_mA, Kanal1_Leistung_W, Kanal2_Spannung_V, Kanal2_Strom_mA, Kanal2_Leistung_W`

---

## 4. Verbraucher anschliessen

An den Schraubklemmen je Kanal:

```text
Quelle (+) ──► VIN   [durch den Shunt]   VOUT ──► Verbraucher (+)
Quelle (−) ──► GND ◄────────────────────────── Verbraucher (−)
```

- Max. **36 V** und **~8 A** pro Kanal (Modulgrenze durch Shunt R010)
- Klemmen nur im spannungsfreien Zustand anschliessen/ändern
- Der Strom fliesst durch die Schraubklemmen, nicht über die Dupont-Kabel

---

## 5. Wichtigste Befehle zur Kontrolle und Steuerung

Alle Befehle auf dem Raspberry Pi (SSH oder Raspberry Pi Connect).

### 5.1 Monitor-Software (systemd-Service)

| Zweck | Befehl |
| --- | --- |
| Status anzeigen | `systemctl status ina226-monitor` |
| Software neu starten | `sudo systemctl restart ina226-monitor` |
| Stoppen / Starten | `sudo systemctl stop ina226-monitor` / `sudo systemctl start ina226-monitor` |
| Autostart deaktivieren | `sudo systemctl disable ina226-monitor` |
| Live-Log mitverfolgen | `journalctl -u ina226-monitor -f` |
| Letzte 100 Log-Zeilen | `journalctl -u ina226-monitor -n 100` |

### 5.2 MQTT-Broker

| Zweck | Befehl |
| --- | --- |
| Broker-Status | `systemctl status mosquitto` |
| Alle Messwerte mithören | `mosquitto_sub -h localhost -t 'ina226/#' -v` |
| Manuell messen (Trigger) | `mosquitto_pub -h localhost -t ina226/cmd -m '{"trigger":1}'` |
| Status der Mess-Einheit | `mosquitto_sub -h localhost -t 'ina226/status' -v` |

### 5.3 Software aktualisieren

```bash
cd ~/INA-226-monitor-v2
git pull origin main
sudo systemctl restart ina226-monitor
```

> Nach jedem `git pull` **immer neu starten**, damit die neue Version aktiv wird.

### 5.4 Dashboard-API (für Scripts/Automatisierung)

| Endpunkt | Methode | Wirkung |
| --- | --- | --- |
| `/api/values` | GET | Aktuelle Messwerte, Status, Intervall |
| `/api/history?points=120` | GET | Verlaufspunkte für die Grafik |
| `/api/measure` | POST | Sofortmessung auslösen |
| `/api/interval` | POST | Intervall setzen: `{"seconds": 60}` |
| `/api/auto` | POST | Automatik: `{"auto": true/false}` |
| `/api/record/start` · `/api/record/stop` | POST | CSV-Aufzeichnung starten/stoppen |
| `/api/files` | GET | Aufzeichnungen auflisten |

Beispiel – Sofortmessung per Kommandozeile:

```bash
curl -X POST http://localhost:5000/api/measure
```

---

## 6. Fehlerbehebung

| Symptom | Ursache | Abhilfe |
| --- | --- | --- |
| Dashboard zeigt «offline» | Mess-Einheit stromlos / WLAN weg | XIAO einschalten, WLAN prüfen; «online» kommt von selbst |
| Trigger laufen, keine Werte | INA226 nicht initialisiert | Seriellen Monitor prüfen: «INA226 Kanal: FEHLER» → Verkabelung kontrollieren |
| Kein Zugriff aufs Dashboard | Service gestoppt oder Pi offline | `systemctl status ina226-monitor`; Pi-IP prüfen |
| Strom zeigt ±0.25–0.5 mA bei offenem Kreis | Messrauschen (1–2 LSB) | normal, keine Massnahme |
| Grafik nach Neustart leer | erster Start oder Verlaufsdatei gelöscht | füllt sich ab der nächsten Messung |
| App startet nach Neuinstallation nicht | Venv fehlt | `cd ~/INA-226-monitor-v2 && python3 -m venv venv && source venv/bin/activate && pip install flask paho-mqtt` |

---

## 7. Wartung und Grenzen

- **SD-Karte:** Die Verlaufsdatei `data/history.csv` begrenzt das System automatisch (letzte 600 Messungen); CSV-Aufzeichnungen bei Bedarf herunterladen und löschen
- **LiPo der Mess-Einheit:** regelmässig über USB-C laden; Laufzeit im Dauerbetrieb beobachten (abhängig von der Akkukapazität)
- **Messgenauigkeit:** Werkseinstellung CAL 2048 / Shunt R010; für Präzisionsanwendungen mit Referenzmessgerät eichen
- **Messbereiche:** 0–36 V, ±8.2 A pro Kanal, Auflösung 1.25 mV / 0.25 mA