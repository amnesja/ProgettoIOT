from enum import Enum
import time
import json
import logging
import threading
from thermostat.db.repository import ThermostatRepository

from enum import Enum
import time
import json
import logging
import threading
from thermostat.db.repository import ThermostatRepository

logger = logging.getLogger(__name__)


class ValveState(Enum):
    # Stati possibili di una valvola gestiti dal controller
    IDLE = 0
    HEATING = 1
    OFFLINE = 2


class Valve:
    # Oggetto leggero che rappresenta una valvola in memoria
    def __init__(self, valve_id, setpoint=22.0):
        # id della valvola
        self.valve_id = valve_id
        # setpoint efficace (può essere sovrascritto dal setpoint della stanza)
        self.setpoint = setpoint
        # ultima temperatura ricevuta
        self.current_temp = None
        # stato logico (IDLE, HEATING, OFFLINE)
        self.state = ValveState.IDLE
        # timestamp dell'ultimo messaggio ricevuto
        self.last_seen = time.time()

    def update_temperature(self, temperature):
        # aggiorna la temperatura corrente e il timestamp di last_seen
        self.current_temp = temperature
        self.last_seen = time.time()


class ThermostatController:
    # Controller principale: mantiene lo stato delle valvole, prende decisioni
    def __init__(self, mqtt_client):
        # dizionario valve_id -> Valve
        self.valves = {}
        # client MQTT (usato per pubblicare comandi)
        self.mqtt_client = mqtt_client
        # repository per persistenza su DB
        self.repository = ThermostatRepository()
        # timeout per considerare una valvola offline (s)
        self.OFFLINE_TIMEOUT = 10.0
        # intervallo tra sweep per controllo offline (s)
        self.SWEEP_INTERVAL = 5.0
        # avvia thread background per rilevamento offline
        t = threading.Thread(target=self._offline_sweep, daemon=True)
        t.start()

    def handle_temperature(self, valve_id, temperature):
        # isteresi di default (può essere sovrascritta dalla stanza)
        HYSTERESIS = 0.5

        # Se non conosciamo la valvola la instanziamo in memoria
        if valve_id not in self.valves:
            logger.info("Nuova valvola rilevata: %s", valve_id)
            self.valves[valve_id] = Valve(valve_id)

        valve = self.valves[valve_id]
        # aggiorniamo temperatura e last_seen
        valve.update_temperature(temperature)

        # salviamo informazioni base sul DB e la lettura di temperatura
        self.repository.save_valve(valve_id, valve.setpoint, valve.last_seen)
        self.repository.save_temperature(valve_id, temperature)

        # valore di default per il comando heating
        heating = False

        # calcoliamo setpoint e isteresi effettivi.
        # se la valvola è assegnata a una stanza, usiamo il setpoint della stanza.
        effective_setpoint = valve.setpoint
        effective_hysteresis = HYSTERESIS
        try:
            vrow = self.repository.get_valve(valve_id)
            if vrow and vrow.get('room_id'):
                room = self.repository.get_room(vrow.get('room_id'))
                if room:
                    # se la stanza esiste, prendi target_temp e hysteresis
                    effective_setpoint = room.get('target_temp', effective_setpoint)
                    effective_hysteresis = room.get('hysteresis', effective_hysteresis)
                    # aggiorna anche l'oggetto in memoria per coerenza con UI
                    valve.setpoint = effective_setpoint
        except Exception:
            # non blocchiamo il flusso su errori DB: logghiamo e procediamo
            logger.exception("Errore ottenimento room per valvola %s", valve_id)

        # Verifica se esiste un override manuale salvato nel DB
        override = self.repository.get_valve_override(valve_id)
        if override:
            expires = override.get("expires")
            # se expires è None => override persistente fino a cancellazione
            if expires is None or expires > time.time():
                # rispettare l'override: heating true/false
                heating = bool(override.get("heating"))
                valve.state = ValveState.HEATING if heating else ValveState.IDLE
            else:
                # override scaduto: rimuovilo e procedi con la logica normale
                self.repository.clear_valve_override(valve_id)
                override = None

        # Logica di controllo con isteresi: si evita il toggle continuo
        if not override:
            if valve.current_temp < effective_setpoint - effective_hysteresis:
                # troppo freddo: accendi riscaldamento
                valve.state = ValveState.HEATING
                heating = True
            elif valve.current_temp > effective_setpoint + effective_hysteresis:
                # troppo caldo: spegni
                valve.state = ValveState.IDLE
                heating = False
            else:
                # nella finestra di isteresi manteniamo lo stato corrente
                heating = (valve.state == ValveState.HEATING)

        # estraiamo dati di override per il log (se presenti)
        ov_heating = override.get("heating") if override else None
        ov_expires = override.get("expires") if override else None
        logger.info(
            "[Controller] %s | Temp: %s | Setpoint: %s | State: %s | Heating: %s | OverrideHeating: %s | OverrideExpires: %s",
            valve_id,
            valve.current_temp,
            effective_setpoint,
            valve.state.value,
            heating,
            ov_heating,
            ov_expires,
        )

        # Pubblica comando sul topic di comando della valvola
        topic_command = f"home/valves/{valve_id}/command"
        payload = {"heating": heating}
        self.mqtt_client.publish(topic_command, json.dumps(payload))

        # Persistiamo lo stato calcolato della valvola (es. HEATING/IDLE/OFFLINE)
        try:
            self.repository.save_valve(valve_id, valve.setpoint, valve.last_seen, valve.state.value)
        except Exception:
            logger.exception("Errore salvataggio stato valvola")

    def _offline_sweep(self):
        # thread che periodicamente controlla last_seen e marca OFFLINE le valvole
        while True:
            try:
                now = time.time()
                for vid, valve in list(self.valves.items()):
                    if valve.last_seen is None:
                        continue
                    # se non ricevuta per più di OFFLINE_TIMEOUT la marcchiamo OFFLINE
                    if now - valve.last_seen > self.OFFLINE_TIMEOUT:
                        if valve.state != ValveState.OFFLINE:
                            logger.info(
                                "Marking valve %s as OFFLINE (last_seen %.1fs ago)", vid, now - valve.last_seen
                            )
                            valve.state = ValveState.OFFLINE
                            try:
                                # persistiamo lo stato OFFLINE
                                self.repository.save_valve(vid, valve.setpoint, valve.last_seen, valve.state.value)
                            except Exception:
                                logger.exception("Errore salvataggio stato valvola during offline sweep")
            except Exception:
                logger.exception("Errore nel ciclo di sweep offline")
            time.sleep(self.SWEEP_INTERVAL)

    def update_setpoint(self, valve_id, new_setpoint):
        # cambiare il setpoint in memoria e sul DB (se la valvola è nota)
        if valve_id in self.valves:
            self.valves[valve_id].setpoint = new_setpoint
            logger.info("[Controller] Setpoint aggiornato per %s: %s", valve_id, new_setpoint)

            # aggiornamento nel DB
            self.repository.save_valve(
                valve_id, new_setpoint, self.valves[valve_id].last_seen
            )
        else:
            logger.warning("[Controller] Valvola %s non trovata", valve_id)