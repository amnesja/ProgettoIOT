from thermostat.logging_config import setup_logging
from thermostat.mqtt.client import MQTTClient
from thermostat.db.database import init_db

# Configura il logging (console / file) secondo la configurazione del progetto
setup_logging()


if __name__ == "__main__":
    # Inizializza il DB (crea tabelle / applica migrazioni semplici)
    init_db()
    # crea e avvia il client MQTT che a sua volta inizializza il controller
    mqtt_client = MQTTClient()
    # avvia il loop MQTT in modalità bloccante
    mqtt_client.start()