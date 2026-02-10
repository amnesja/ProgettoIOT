import paho.mqtt.client as mqtt
import time
import random
import json
import sys
import logging

logger = logging.getLogger(__name__)

# parametri broker
BROKER = "localhost"
PORT = 1883


def parse_args():
    # legge gli argomenti della riga di comando per ottenere gli id delle valvole
    if len(sys.argv) > 1:
        return sys.argv[1:]
    # valore di default se non vengono passati argomenti
    return ["valve1"]


def on_message(client, userdata, msg):
    # callback per ricevere comandi (es. heating on/off)
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        payload = {}

    parts = msg.topic.split("/")
    # ci aspettiamo topic del tipo: home/valves/{id}/command
    if len(parts) >= 4 and parts[0] == "home" and parts[1] == "valves" and parts[3] == "command":
        vid = parts[2]
        valves = userdata.get("valves", {}) if userdata else {}
        if vid in valves:
            # aggiorna lo stato 'heating' della valvola corrispondente
            valves[vid]["heating"] = bool(payload.get("heating"))
            logger.info("[VALVE_SIM] Command on %s: set heating=%s", vid, valves[vid]["heating"])
        else:
            logger.info("[VALVE_SIM] Command on unknown valve %s", vid)
    else:
        logger.info("[VALVE_SIM] Command on %s: %s", msg.topic, payload)


def start_simulator(valve_ids):
    # stato interno delle valvole
    valves_state = {}
    # passiamo valves_state nel userdata del client per accesso dalla callback
    client = mqtt.Client(userdata={"valves": valves_state})
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)

    # sottoscriviamo tutti i comandi delle valvole
    client.subscribe("home/valves/+/command")
    client.loop_start()

    # inizializziamo gli stati e pubblichiamo l'annuncio retained per ogni valvola
    for vid in valve_ids:
        valves_state[vid] = {"heating": False, "temp": round(random.uniform(18.0, 22.0), 2)}
        ann = {"id": vid, "ts": time.time(), "proto": "sim"}
        client.publish(f"home/valves/{vid}/announce", json.dumps(ann), retain=True)

    try:
        # ciclo principale: per ogni valvola aggiorna temperatura e pubblica
        while True:
            for vid in valve_ids:
                state = valves_state[vid]
                # modello termico semplice: aumenta temperatura se heating True, altrimenti diminuisce
                if state["heating"]:
                    delta = random.uniform(0.05, 0.25)
                    state["temp"] += delta
                else:
                    delta = random.uniform(0.01, 0.15)
                    state["temp"] -= delta
                # afferra nel range [5,35] e arrotonda
                state["temp"] = round(max(5.0, min(35.0, state["temp"])), 2)

                payload = {"value": state["temp"]}
                topic = f"home/valves/{vid}/temperature"
                client.publish(topic, json.dumps(payload))
                logger.info("[VALVE_SIM] %s published temperature: %s (heating=%s)", vid, state["temp"], state["heating"])
                # breve pausa per distribuire i timestamp
                time.sleep(0.5)
            # pausa tra un giro completo e il successivo
            time.sleep(2)
    finally:
        # pulizia: fermiamo il loop MQTT e disconnettiamo
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    ids = parse_args()
    start_simulator(ids)
