from thermostat.logging_config import setup_logging
from thermostat.mqtt.client import MQTTClient
from thermostat.db.database import init_db

setup_logging()

if __name__ == "__main__":
    init_db()
    mqtt_client = MQTTClient()
    mqtt_client.start()