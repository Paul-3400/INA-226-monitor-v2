# Mess-Einheit Firmware (XIAO ESP32S3)

Arduino-Sketch für die mobile Mess-Einheit des INA226-Monitor.

> Autor: Paul Simmen mit Vibe (GLM-5-latest-short), 07.10.2026

## Hardware

- Seeed Studio XIAO ESP32S3 (I²C: D1=SDA/GPIO6, D2=SCL/GPIO7, 3V3 versorgt die Sensoren)
- 2 × INA-226 China-Module (Shunt R010 = 0.01 Ω), I²C-Adressen **0x40** und **0x45**
- Versorgung: LiPo an Bat+/Bat− (Laden via USB-C)

## Funktion (Betriebsmodus: Pull)

1. Verbindet sich mit WLAN und dem Mosquitto-Broker auf dem Raspberry Pi
2. Abonniert `ina226/cmd` (Trigger, Payload `{"trigger": <counter>}`)
3. Misst bei Trigger beide Kanäle und published JSON auf `ina226/1a` und `ina226/10a`
4. Last-Will auf `ina226/status` (online/offline, retained)

## Vor dem Flashen

1. Library installieren: **PubSubClient** von Nick O'Leary (Library Manager)
2. Im Abschnitt **KONFIGURATION** anpassen:
   - `WIFI_SSID` / `WIFI_PASSWORD` – eigene WLAN-Zugangsdaten
   - `MQTT_HOST` – IP-Adresse des Raspberry Pi (Mosquitto-Broker)
   - ggf. `INA_ADDR_CH1` / `INA_ADDR_CH2` falls andere A0/A1-Lötstellen gesetzt sind
3. Board "XIAO_ESP32S3" auswählen, Upload, Serial Monitor 115200 Baud

## Konfiguration der INA226

| Parameter | Wert |
| --- | --- |
| Config-Register | 0x4527 (Averaging 64, 1.1 ms, Shunt+Bus continuous) |
| Kalibrierung CAL | 2048 (Current_LSB 0.25 mA, Shunt 0.01 Ω) |
| Max. Strom | ~8.2 A (±81.92 mV Shunt-Range) |

## Testen

```bash
# Auf dem Pi mithören:
mosquitto_sub -h localhost -t 'ina226/#' -v

# Messung triggern:
mosquitto_pub -h localhost -t ina226/cmd -m '{"trigger":1}'
```

Details zu Architektur, Verkabelung und Entscheidungen: siehe `Handover.md` im Hauptverzeichnis des Repos.
