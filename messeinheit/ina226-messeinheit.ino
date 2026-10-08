// Autor: Paul Simmen mit Vibe (GLM-5-latest-short), 07.10.2026
//
// Firmware: Mobile Mess-Einheit (XIAO ESP32S3 + 2x INA-226 China-Modul, R010)
// Betriebsmodus: Pull – wartet auf MQTT-Trigger, misst beide Kanäle, published Resultate.
// Architektur gemäss Handover.md in diesem Repo.
//
// Benötigte Arduino-Library (Library Manager):
//   - "PubSubClient" von Nick O'Leary (MQTT)
//   - WiFi ist beim XIAO ESP32S3 enthalten
//
// WICHTIG vor dem Flashen – die Werte im Abschnitt "KONFIGURATION" anpassen:
//   WLAN-Zugangsdaten, IP des Mosquitto-Brokers (Raspberry Pi), ggf. I2C-Adressen.

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>

// ======================= KONFIGURATION =======================
const char* WIFI_SSID     = "MeinWLAN";       // <-- anpassen
const char* WIFI_PASSWORD = "WLANPasswort";   // <-- anpassen

const char* MQTT_HOST     = "nn.n.n.nn";      // <-- IP des Raspberry Pi (Mosquitto)
const int   MQTT_PORT     = 1883;
const char* MQTT_CLIENTID = "xiao-messeinheit";
const char* TOPIC_CMD     = "ina226/cmd";       // Trigger vom RasPi (abonniert)
const char* TOPIC_CH1     = "ina226/1a";        // Resultat Kanal 1 (published)
const char* TOPIC_CH2     = "ina226/10a";       // Resultat Kanal 2 (published)
const char* TOPIC_STATUS  = "ina226/status";     // Online/Offline via Last-Will

// I2C-Adressen der beiden China-INA226-Module (A0/A1-Loetstellen!)
// Modul A: A0/A1 offen  -> 0x40
// Modul B: A1=VS, A0=VS -> 0x45
// (verifiziert per I2C-Scanner, siehe Handover.md)
const uint8_t INA_ADDR_CH1 = 0x40;
const uint8_t INA_ADDR_CH2 = 0x45;

// INA226-Register (Shunt R010 = 0.01 Ohm)
const uint8_t REG_CONFIGURATION = 0x00;
const uint8_t REG_SHUNT_VOLTAGE = 0x01;
const uint8_t REG_BUS_VOLTAGE   = 0x02;
const uint8_t REG_POWER         = 0x03;
const uint8_t REG_CURRENT       = 0x04;
const uint8_t REG_CALIBRATION   = 0x05;

// Config-Register: Averaging 64, Bus/Shunt 1.1 ms, Shunt+Bus Continuous = 0x4527
const uint16_t INA_CONFIG = 0x4527;
// C
AL = 0.00512 / (Current_LSB 0.25 mA * R_shunt 0.01) = 2048
const uint16_t INA_CAL    = 2048;
const float    CURRENT_LSB_MA = 0.25;   // mA pro LSB
const float    BUS_LSB_MV     = 1.25;   // mV pro LSB

unsigned long lastTriggerCounter = 0;

WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);
bool measurementPending = false;
unsigned long triggerMillis = 0;

// ======================= INA226 LOW-LEVEL =======================

// 16-Bit-Register schreiben (Pointer + MSB + LSB)
void inaWrite16(uint8_t addr, uint8_t reg, uint16_t value) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write((value >> 8) & 0xFF);
  Wire.write(value & 0xFF);
  Wire.endTransmission();
}

// 16-Bit-Register lesen (Pointer setzen, dann 2 Bytes lesen)
uint16_t inaRead16(uint8_t addr, uint8_t reg) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.endTransmission(false);           // Repeated Start
  Wire.requestFrom((int)addr, 2);
  uint16_t v = ((uint16_t)Wire.read() << 8) | Wire.read();
  return v;
}

// Ein Modul initialisieren (Config + Kalibrierung)
bool inaInit(uint8_t addr) {
  inaWrite16(addr, REG_CONFIGURATION, INA_CONFIG);
  inaWrite16(addr, REG_CALIBRATION, INA_CAL);
  // Konfiguration zuruecklesen als Plausibilitaets-Check
  uint16_t cfg = inaRead16(addr, REG_CONFIGURATION);
  return (cfg == INA_CONFIG);
}

// Shunt-Spannung in mV (signed, 1 LSB = 2.5 uV laut Datenblatt)
float inaReadShuntMV(uint8_t addr) {
  int16_t raw = (int16_t)inaRead16(addr, REG_SHUNT_VOLTAGE);
  return raw * 0.0025;
}

// Busspannung in V (1 LSB = 1.25 mV)
float inaReadBusV(uint8_t addr) {
  uint16_t raw = inaRead16(addr, REG_BUS_VOLTAGE);
  return raw * BUS_LSB_MV / 1000.0;
}

// Strom in mA: Current-Register * Current_LSB
float inaReadCurrentMA(uint8_t addr) {
  int16_t raw = (int16_t)inaRead16(addr, REG_CURRENT);
  return raw * CURRENT_LSB_MA;
}

// ======================= MQTT =======================

void publishStatus(const char* state) {
  mqtt.publish(TOPIC_STATUS, state, tru
e);   // retained, damit Dashboard den Zustand sieht
}

void publishResult(const char* topic, float v, float a, float shuntMV) {
  // Zeitstempel setzt der RasPi beim Empfang (XIAO hat nach Reset keine Echtzeit)
  char payload[160];
  snprintf(payload, sizeof(payload),
           "{\"voltage_V\":%.4f,\"current_mA\":%.3f,\"power_W\":%.5f,\"shunt_mV\":%.4f}",
           v, a, (v * a / 1000.0), shuntMV);
  mqtt.publish(topic, payload);
}

// Eingehende Trigger verarbeiten: {"trigger": <counter>}
// Veraltete/wiederholte Counter werden ignoriert (QoS-0-Duplikate, alte Session-Nachrichten).
void onMqttMessage(char* topic, byte* payload, unsigned int len) {
  if (strcmp(topic, TOPIC_CMD) != 0) return;

  // Minimal-Parser: Zahl nach "trigger":
  char buf[64] = {0};
  if (len >= sizeof(buf)) len = sizeof(buf) - 1;
  memcpy(buf, payload, len);

  unsigned long counter = 0;
  char* p = strstr(buf, "trigger");
  if (p) {
    while (*p && (*p < '0' || *p > '9')) p++;
    counter = strtoul(p, nullptr, 10);
  } else {
    counter = ++lastTriggerCounter;  // leeres Trigger-Kommando: einfach als "jetzt" werten
  }

  if (counter > lastTriggerCounter || counter == 0) {
    lastTriggerCounter = counter;
    measurementPending = true;         // Messung in loop() ausfuehren (nicht im Callback)
    triggerMillis = millis();
  }
}

void connectMqtt() {
  while (!mqtt.connected()) {
    Serial.print("MQTT verbinde... ");
    // Last-Will: falls XIAO stirbt, published der Broker "offline"
    bool ok = mqtt.connect(MQTT_CLIENTID, nullptr, nullptr,
                           TOPIC_STATUS, 1, true, "offline");
    if (ok) {
      Serial.println("ok");
      publishStatus("online");
      mqtt.subscribe(TOPIC_CMD, 0);           // QoS 0, kein cleanSession-Ballast
      lastTriggerCounter = 0;
    } else {
      Serial.print("fehlgeschlagen, rc=");
      Serial.print(mqtt.state());
      Serial.println(" - neuer Versuch in 2 s");
      delay(2000);
    }
  }
}

// ======================= SET
UP / LOOP =======================

void setup() {
  Serial.begin(115200);
  delay(2000);  // Zeit fuer USB-Serial

  // I2C: D1=SDA (GPIO6), D2=SCL (GPIO7) sind beim XIAO ESP32S3 die Defaults
  Wire.begin();
  Wire.setClock(100000);  // 100 kHz, robust bei Kabeln

  bool ok1 = inaInit(INA_ADDR_CH1);
  bool ok2 = inaInit(INA_ADDR_CH2);
  Serial.printf("INA226 Kanal 1 (0x%02X): %s\n", INA_ADDR_CH1, ok1 ? "OK" : "FEHLER");
  Serial.printf("INA226 Kanal 2 (0x%02X): %s\n", INA_ADDR_CH2, ok2 ? "OK" : "FEHLER");
  if (!ok1 || !ok2) {
    Serial.println("!! I2C-Problem: Adressen pruefen (A0/A1-Loetstellen) und Verkabelung!");
  }

  Serial.print("WiFi verbinde: ");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nWiFi ok, IP: %s\n", WiFi.localIP().toString().c_str());

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqttMessage);
  mqtt.setKeepAlive(30);
  connectMqtt();
  Serial.printf("Warte auf Mess-Trigger auf %s ...\n", TOPIC_CMD);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(1000);
  }
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  if (measurementPending) {
    measurementPending = false;

    // Kleine Stabilisierungszeit, damit WiFi-Radio den Messvorgang nicht stoert
    delay(5);

    float shunt1 = inaReadShuntMV(INA_ADDR_CH1);
    float bus1   = inaReadBusV(INA_ADDR_CH1);
    float amps1  = inaReadCurrentMA(INA_ADDR_CH1);

    float shunt2 = inaReadShuntMV(INA_ADDR_CH2);
    float bus2   = inaReadBusV(INA_ADDR_CH2);
    float amps2  = inaReadCurrentMA(INA_ADDR_CH2);

    publishResult(TOPIC_CH1, bus1, amps1, shunt1);
    publishResult(TOPIC_CH2, bus2, amps2, shunt2);

    Serial.printf("CH1: %.3f V, %.1f mA | CH2: %.3f V, %.1f mA\n",
                  bus1, amps1, bus2, amps2);
  }
}
