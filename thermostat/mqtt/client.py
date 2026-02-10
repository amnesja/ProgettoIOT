import paho.mqtt.client as mqtt
import json
import logging
from thermostat.core.controller import ThermostatController

BROKER = "localhost"
PORT = 1883

logger = logging.getLogger(__name__)


class MQTTClient:

    def __init__(self):
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.controller = ThermostatController(self.client)

    def on_connect(self, client, userdata, flags, rc):
        logger.info("Connected with result code %s", rc)
        client.subscribe("home/valves/+/temperature")
        client.subscribe("home/thermostat/setpoint/+")
    
    def on_message(self, client, userdata, msg):
        try:
            topic_parts = msg.topic.split('/')
            
            #Caso 1: temperatura delle valvole
            if topic_parts[0] == "home" and topic_parts[1] == "valves":
                if len(topic_parts) != 4:
                    logger.warning("Topic temperatura non valido: %s", msg.topic)
                    return
                valve_id = topic_parts[2]
                payload = json.loads(msg.payload.decode())
                temperature = payload.get("value")

                self.controller.handle_temperature(valve_id, temperature)

            #Caso 2: aggiornamento setpoint dal thermostat
            if topic_parts[0] == "home" and topic_parts[1] == "thermostat":
                if len(topic_parts) != 4:
                    logger.warning("Topic setpoint non valido: %s", msg.topic)
                    return

                valve_id = topic_parts[3]
                payload = json.loads(msg.payload.decode())
                new_setpoint = payload.get("setpoint")

                self.controller.update_setpoint(valve_id, new_setpoint)
                return
                
        except Exception:
            logger.exception("Errore nella gestione del messaggio")
    
    def start(self):
        self.client.connect(BROKER, PORT, 60)
        self.client.loop_forever()