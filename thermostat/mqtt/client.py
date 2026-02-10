import paho.mqtt.client as mqtt
import json
import logging
from thermostat.core.controller import ThermostatController

# Parametri del broker (config hardcoded per sviluppo locale)
BROKER = "localhost"
PORT = 1883

logger = logging.getLogger(__name__)


class MQTTClient:
    """Wrapper semplice intorno a paho mqtt che collega i messaggi al controller."""

    def __init__(self):
        # istanza del client paho
        self.client = mqtt.Client()
        # assegniamo callback
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        # creiamo il controller che userà lo stesso client per pubblicare
        self.controller = ThermostatController(self.client)

    def on_connect(self, client, userdata, flags, rc):
        # callback eseguita quando il client si connette al broker
        logger.info("Connected with result code %s", rc)
        # sottoscriviamo i topic usati dal progetto
        client.subscribe("home/valves/+/temperature")
        client.subscribe("home/thermostat/setpoint/+")

    def on_message(self, client, userdata, msg):
        # callback per la ricezione dei messaggi: instrada verso il controller
        try:
            topic_parts = msg.topic.split("/")

            # Caso 1: messaggio di temperatura dalle valvole
            if topic_parts[0] == "home" and topic_parts[1] == "valves":
                # formato atteso: home/valves/{id}/temperature
                if len(topic_parts) != 4:
                    logger.warning("Topic temperatura non valido: %s", msg.topic)
                    return
                valve_id = topic_parts[2]
                payload = json.loads(msg.payload.decode())
                # il simulatore invia nel campo "value" la temperatura
                temperature = payload.get("value")

                # inoltra al controller
                self.controller.handle_temperature(valve_id, temperature)

            # Caso 2: setpoint pubblicato (es. dalla dashboard)
            if topic_parts[0] == "home" and topic_parts[1] == "thermostat":
                # formato atteso: home/thermostat/setpoint/{id}
                if len(topic_parts) != 4:
                    logger.warning("Topic setpoint non valido: %s", msg.topic)
                    return

                valve_id = topic_parts[3]
                payload = json.loads(msg.payload.decode())
                new_setpoint = payload.get("setpoint")

                # aggiorna il setpoint nel controller
                self.controller.update_setpoint(valve_id, new_setpoint)
                return

        except Exception:
            # log di eventuali errori senza fermare il client
            logger.exception("Errore nella gestione del messaggio")

    def start(self):
        # connessione e loop bloccante
        self.client.connect(BROKER, PORT, 60)
        self.client.loop_forever()