
#!/usr/bin/env python3
# ============================================================
# INA226 Monitor – Flask Web Dashboard (Pi als Steuer-Einheit)
# Architektur: Mess-Einheit (XIAO ESP32S3) misst auf MQTT-Trigger,
# der Pi empfaengt die Resultate, zeigt sie im Dashboard an und
# zeichnet sie optional als CSV auf.
# Built as a "brain gym" project 🧠💪
# Autor: Paul Simmen mit Vibe (GLM-5-latest-short), 07.10.2026
# ============================================================

import json
import csv
import os
import threading
import time
from collections import deque
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_file
import paho.mqtt.client as mqtt

# ============================================================
# Flask App erstellen
# ============================================================
app = Flask(__name__)

# ============================================================
# Konfiguration
# ============================================================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_CLIENT_ID = "ina226-dashboard"

TOPIC_CMD    = "ina226/cmd"     # Trigger an die Mess-Einheit (published)
TOPIC_CH1    = "ina226/1a"      # Resultat Kanal 1 (abonniert)
TOPIC_CH2    = "ina226/10a"     # Resultat Kanal 2 (abonniert)
TOPIC_STATUS = "ina226/status"  # Online/Offline der Mess-Einheit (abonniert, retained)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Persistenter Verlauf (ueberlebt App-Neustarts) + Aufzeichnungs-Status
HISTORY_FILE = os.path.join(DATA_DIR, "history.csv")
RECORDING_STATE_FILE = os.path.join(DATA_DIR, "recording_state.json")

# ============================================================
# Globale Variablen (Zustand des Dashboards)
# ============================================================
current_values = {
    "1A": {"voltage_V": 0.0, "current_mA": 0.0, "power_W": 0.0,
           "shunt_mV": 0.0, "timestamp": ""},
    "10A": {"voltage_V": 0.0, "current_
mA": 0.0, "power_W": 0.0,
            "shunt_mV": 0.0, "timestamp": ""}
}

unit_status = {"online": False, "last_change": ""}

# Messintervall in Sekunden (Presets: 12 / 30 / 60 / 300)
measurement_interval = {"seconds": 60}

# CSV-Aufzeichnung
recording = {"active": False, "filename": None, "file": None, "writer": None}

# Verlaufs-Speicher fuer Grafik (letzte 600 Punkte pro Kanal, ~10 h bei 60 s)
HISTORY_MAX = 600
history = {"1A": deque(maxlen=HISTORY_MAX), "10A": deque(maxlen=HISTORY_MAX)}

# Trigger-Zaehler: startet bei Unix-Zeit (siehe send_trigger) und ist damit
# auch nach App-Neustarts immer groesser als der letzte vom XIAO gesehene Wert
trigger_state = {"counter": 0, "auto": True}
trigger_lock = threading.Lock()

# Zustand des aktuellen Messzyklus (fuer CSV: eine Zeile pro Zyklus,
# geschrieben sobald BEIDE Kanaele eingetroffen sind)
cycle_state = {"id": 0, "received": [], "written": False}

# ============================================================
# MQTT Callbacks
# ============================================================
def on_connect(client, userdata, flags, reason_code, properties):
    """Nach Verbindung: Topics abonnieren"""
    print(f"  MQTT verbunden, RC={reason_code}")
    client.subscribe([(TOPIC_CH1, 0), (TOPIC_CH2, 0), (TOPIC_STATUS, 0)])
    print(f"  Abonniert: {TOPIC_CH1}, {TOPIC_CH2}, {TOPIC_STATUS}")

def on_message(client, userdata, msg):
    """Empfaengt Messwerte und Status der Mess-Einheit"""
    try:
        payload_raw = msg.payload.decode()

        # Status-Nachricht kommt als reiner String ("online"/"offline")
        if msg.topic == TOPIC_STATUS:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            online = payload_raw.strip().lower() in ("online", "true", "1")
            unit_status["online"] = online
            unit_status["last_change"] = timestamp
            print(f"  Mess-Einheit: {'ONLINE' if online else 'OFFLINE'}")
            return

        payload = json.loads(payload_raw)
      
  timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if msg.topic == TOPIC_CH1:
            channel = "1A"
        elif msg.topic == TOPIC_CH2:
            channel = "10A"
        else:
            return

        # Messwerte uebernehmen (Zeitstempel setzt der Pi)
        current_values[channel] = {
            "voltage_V": float(payload.get("voltage_V", 0.0)),
            "current_mA": float(payload.get("current_mA", 0.0)),
            "power_W": float(payload.get("power_W", 0.0)),
            "shunt_mV": float(payload.get("shunt_mV", 0.0)),
            "timestamp": timestamp
        }
        print(f"  {channel}: {current_values[channel]['voltage_V']:.3f} V, "
              f"{current_values[channel]['current_mA']:.1f} mA")

        # Punkt in den Verlaufs-Speicher aufnehmen (fuer Grafik)
        history[channel].append(current_values[channel])

        # Messzyklus vollstaendig, sobald BEIDE Kanaele eingetroffen sind
        if channel not in cycle_state["received"]:
            cycle_state["received"].append(channel)
            if len(cycle_state["received"]) >= 2 and not cycle_state["written"]:
                cycle_state["written"] = True

                # Verlauf immer persistieren (Grafik ueberlebt Neustart)
                write_history_row(timestamp, current_values["1A"], current_values["10A"])

                # CSV-Aufzeichnung: genau eine Zeile pro vollstaendigem Zyklus
                if recording["active"] and recording["writer"]:
                    recording["writer"].writerow([
                        timestamp,
                        current_values["1A"]["voltage_V"],
                        current_values["1A"]["current_mA"],
                        current_values["1A"]["power_W"],
                        current_values["10A"]["voltage_V"],
                        current_values["10A"]["current_mA"],
                        current_values["10A"]["power_W"]
                    ])
                    recording["file"].flush()

   
 except Exception as e:
        print(f"  MQTT-Nachricht Fehler ({msg.topic}): {e}")

# ============================================================
# Persistenz: Verlauf + Aufzeichnungs-Status
# ============================================================
def write_history_row(ts, c1, c2):
    """Haengt einen vollstaendigen Messzyklus an die Verlaufs-Datei an."""
    try:
        with open(HISTORY_FILE, "a", newline="") as f:
            csv.writer(f).writerow([
                ts,
                c1["voltage_V"], c1["current_mA"], c1["power_W"], c1["shunt_mV"],
                c2["voltage_V"], c2["current_mA"], c2["power_W"], c2["shunt_mV"]
            ])
    except Exception as e:
        print(f"  History-Schreibfehler: {e}")

def load_history():
    """Laedt den gespeicherten Verlauf nach einem App-Neustart.
    Grossen Dateien wird ein Trim verpasst (nur die letzten HISTORY_MAX Zeilen)."""
    if not os.path.exists(HISTORY_FILE):
        print("  Kein gespeicherter Verlauf gefunden – starte leer")
        return
    try:
        with open(HISTORY_FILE, newline="") as f:
            rows = [r for r in csv.reader(f) if len(r) == 9]

        # Datei begrenzen (SD-Karte schonen), wenn sie sehr gross geworden ist
        if len(rows) > HISTORY_MAX * 2:
            with open(HISTORY_FILE, "w", newline="") as f:
                csv.writer(f).writerows(rows[-HISTORY_MAX:])
            rows = rows[-HISTORY_MAX:]

        for row in rows[-HISTORY_MAX:]:
            ts, v1, a1, p1, s1, v2, a2, p2, s2 = row
            history["1A"].append({
                "voltage_V": float(v1), "current_mA": float(a1),
                "power_W": float(p1), "shunt_mV": float(s1), "timestamp": ts})
            history["10A"].append({
                "voltage_V": float(v2), "current_mA": float(a2),
                "power_W": float(p2), "shunt_mV": float(s2), "timestamp": ts})
        print(f"  Verlauf geladen: {len(history['1A'])} Punkte aus {os.path.basename(HISTORY_FILE)}")
    except E
xception as e:
        print(f"  History-Ladefehler: {e}")

def save_recording_state():
    """Merkt sich Aufzeichnungs-Zustand, damit er einen Neustart ueberlebt."""
    try:
        with open(RECORDING_STATE_FILE, "w") as f:
            json.dump({"active": recording["active"],
                       "filename": recording["filename"]}, f)
    except Exception:
        pass

def resume_recording():
    """Setzt eine unterbrochene CSV-Aufzeichnung im Append-Modus fort."""
    if not os.path.exists(RECORDING_STATE_FILE):
        return
    try:
        with open(RECORDING_STATE_FILE) as f:
            state = json.load(f)
        if state.get("active") and state.get("filename"):
            filepath = os.path.join(DATA_DIR, state["filename"])
            if os.path.exists(filepath):
                recording["filename"] = state["filename"]
                recording["file"] = open(filepath, "a", newline="")
                recording["writer"] = csv.writer(recording["file"])
                recording["active"] = True
                print(f"  Aufzeichnung fortgesetzt (Append): {state['filename']}")
    except Exception as e:
        print(f"  Aufzeichnungs-Fortsetzung fehlgeschlagen: {e}")

# ============================================================
# MQTT Client einrichten
# ============================================================
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

def send_trigger():
    """Loest eine Messung an der Mess-Einheit aus und oeffnet einen neuen Zyklus.
    Als Trigger-Nummer dient die Unix-Zeit (max mit +1 fuer Mehrfachtrigger in
    derselben Sekunde): nach einem App-Neustart ist sie automatisch groesser
    als der letzte Stand des XIAO – der zaehlt sonst alte Trigger als 'zu alt'."""
    with trigger_lock:
        trigger_state["counter"] = max(trigger_state["counter"] + 1, int(time.time()))
        counter = trigger_state[
"counter"]
        cycle_state["id"] = counter
        cycle_state["received"] = []
        cycle_state["written"] = False
    payload = json.dumps({"trigger": counter})
    mqtt_client.publish(TOPIC_CMD, payload, qos=0, retain=False)
    print(f"  Trigger gesendet: {payload}")

def trigger_loop():
    """Hintergrund-Thread: triggert die Mess-Einheit im eingestellten Intervall"""
    while True:
        if trigger_state["auto"] and mqtt_client.is_connected():
            send_trigger()
        time.sleep(max(1, measurement_interval["seconds"]))

# ============================================================
# Flask Routen – Webseiten
# ============================================================
@app.route("/")
def index():
    """Startseite – Dashboard"""
    return render_template("index.html")

# ============================================================
# Flask Routen – API Endpunkte
# ============================================================
@app.route("/api/values")
def api_values():
    """Liefert aktuelle Messwerte beider Kanaele + Geraetestatus.
    Die Kanaele liegen auf oberster Ebene (kompatibel zu index.html),
    zusaetzlich unit/interval/auto fuer kuenftige Dashboard-Erweiterungen."""
    response = dict(current_values)          # "1A" und "10A" oben
    response["unit"] = unit_status
    response["interval"] = measurement_interval
    response["auto"] = trigger_state["auto"]
    return jsonify(response)

@app.route("/api/history")
def api_history():
    """Liefert die Verlaufspunkte beider Kanaele fuer die Grafik.
    Optional ?points=N (letzte N Punkte, Default 120)."""
    try:
        points = max(2, min(HISTORY_MAX, int(request.args.get("points", 120))))
    except ValueError:
        points = 120
    return jsonify({
        "1A": list(history["1A"])[-points:],
        "10A": list(history["10A"])[-points:]
    })

@app.route("/api/measure", methods=["POST"])
def api_measure():
    """Manuelle Einzelmessung anstossen"""
    if not mqtt_clien
t.is_connected():
        return jsonify({"status": "error", "msg": "MQTT nicht verbunden"}), 503
    send_trigger()
    return jsonify({"status": "trigger sent"})

@app.route("/api/auto", methods=["POST"])
def api_auto():
    """Automatisches Triggern ein-/ausschalten"""
    data = request.get_json() or {}
    trigger_state["auto"] = bool(data.get("auto", not trigger_state["auto"]))
    return jsonify({"status": "ok", "auto": trigger_state["auto"]})

@app.route("/api/interval", methods=["GET", "POST"])
def api_interval():
    """Messintervall lesen oder setzen (1-3600 Sekunden)"""
    if request.method == "POST":
        data = request.get_json()
        seconds = int(data.get("seconds", 60))
        measurement_interval["seconds"] = max(1, min(3600, seconds))
        return jsonify({"status": "ok", "interval": measurement_interval})
    return jsonify(measurement_interval)

@app.route("/api/record/start", methods=["POST"])
def api_record_start():
    """Startet CSV-Aufzeichnung"""
    if recording["active"]:
        return jsonify({"status": "already recording"})

    filename = f"messung_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = os.path.join(DATA_DIR, filename)
    recording["filename"] = filename
    recording["file"] = open(filepath, "w", newline="")
    recording["writer"] = csv.writer(recording["file"])
    recording["writer"].writerow([
        "Zeitstempel",
        "Kanal1_Spannung_V", "Kanal1_Strom_mA", "Kanal1_Leistung_W",
        "Kanal2_Spannung_V", "Kanal2_Strom_mA", "Kanal2_Leistung_W"
    ])
    recording["active"] = True
    save_recording_state()
    return jsonify({"status": "recording", "filename": filename})

@app.route("/api/record/stop", methods=["POST"])
def api_record_stop():
    """Stoppt CSV-Aufzeichnung"""
    if not recording["active"]:
        return jsonify({"status": "not recording"})

    recording["active"] = False
    if recording["file"]:
        recording["file"].close()
    save_recording_state()
    return
 jsonify({"status": "stopped", "filename": recording["filename"]})

@app.route("/api/files")
def api_files():
    """Listet alle CSV-Dateien auf"""
    files = []
    for f in sorted(os.listdir(DATA_DIR)):
        if f.endswith(".csv"):
            filepath = os.path.join(DATA_DIR, f)
            size = os.path.getsize(filepath)
            files.append({"name": f, "size_kb": round(size / 1024, 1)})
    return jsonify(files)

@app.route("/api/files/download/<filename>")
def api_download(filename):
    """CSV-Datei herunterladen"""
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({"error": "file not found"}), 404

@app.route("/api/files/delete/<filename>", methods=["DELETE"])
def api_delete(filename):
    """CSV-Datei loeschen"""
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return jsonify({"status": "deleted"})
    return jsonify({"error": "file not found"}), 404

# ============================================================
# App starten
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("  INA226 Monitor – Dashboard (Steuer-Einheit)")
    print("  Mess-Einheit: XIAO ESP32S3 via MQTT")
    print("=" * 50)

    os.makedirs(DATA_DIR, exist_ok=True)

    # Gespeicherten Verlauf laden (Grafik ueberlebt Neustart),
    # laufende Aufzeichnung ggf. im Append-Modus fortsetzen
    load_history()
    resume_recording()

    # MQTT verbinden (Reconnect automatisch via loop_start)
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()

    # Trigger-Thread starten (periodisches Messen im Intervall)
    threading.Thread(target=trigger_loop, daemon=True).start()
    print(f"  Auto-Trigger aktiv, Intervall {measurement_interval['seconds']} s")

    print("  Dashboard: http://RpPi2W-002.local:5000")
    print("="
 * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
