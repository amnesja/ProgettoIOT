from enum import Enum
import time
import json
import logging
import threading
from thermostat.db.repository import ThermostatRepository

logger = logging.getLogger(__name__)

class ValveState(Enum):
    IDLE = 0
    HEATING = 1
    OFFLINE = 2

class Valve:
    def __init__(self, valve_id, setpoint=22.0):
        self.valve_id = valve_id
        self.setpoint = setpoint
        self.current_temp = None
        self.state = ValveState.IDLE
        self.last_seen = time.time()

    def update_temperature(self, temperature):
        self.current_temp = temperature
        self.last_seen = time.time()

class ThermostatController:
    
    def __init__(self, mqtt_client):
        self.valves = {}
        self.mqtt_client = mqtt_client
        self.repository = ThermostatRepository()
        # start background thread to detect offline valves
        self.OFFLINE_TIMEOUT = 10.0
        self.SWEEP_INTERVAL = 5.0
        t = threading.Thread(target=self._offline_sweep, daemon=True)
        t.start()


    def handle_temperature(self, valve_id, temperature):
        HYSTERESIS = 0.5

        #Se la valvola non esiste la creiamo
        if valve_id not in self.valves:
            logger.info("Nuova valvola rilevata: %s", valve_id)
            self.valves[valve_id] = Valve(valve_id)
        
        valve = self.valves[valve_id]
        #Aggiornamento temperatura
        valve.update_temperature(temperature)
        
        self.repository.save_valve(valve_id, valve.setpoint, valve.last_seen)
        self.repository.save_temperature(valve_id, temperature)


        # default
        heating = False

        # determine effective setpoint/hysteresis: prefer room target if valve assigned to a room
        effective_setpoint = valve.setpoint
        effective_hysteresis = HYSTERESIS
        try:
            vrow = self.repository.get_valve(valve_id)
            if vrow and vrow.get('room_id'):
                room = self.repository.get_room(vrow.get('room_id'))
                if room:
                    effective_setpoint = room.get('target_temp', effective_setpoint)
                    effective_hysteresis = room.get('hysteresis', effective_hysteresis)
                    # reflect in-memory setpoint for UI clarity
                    valve.setpoint = effective_setpoint
        except Exception:
            logger.exception("Errore ottenimento room per valvola %s", valve_id)

        # Check for manual override
        override = self.repository.get_valve_override(valve_id)
        if override:
            expires = override.get("expires")
            if expires is None or expires > time.time():
                heating = bool(override.get("heating"))
                # set state accordingly
                valve.state = ValveState.HEATING if heating else ValveState.IDLE
            else:
                # override expired
                self.repository.clear_valve_override(valve_id)
                override = None

        #Logica decisionale
        '''if valve.current_temp < valve.setpoint:
            valve.state = ValveState.HEATING
            heating = True
        else:
            valve.state = ValveState.IDLE
            heating = False
        '''
        if not override:
            if valve.current_temp < effective_setpoint - effective_hysteresis:
                valve.state = ValveState.HEATING
                heating = True
            elif valve.current_temp > effective_setpoint + effective_hysteresis:
                valve.state = ValveState.IDLE
                heating = False
            else:
                #mantiene stato attuale
                heating = (valve.state == ValveState.HEATING)

        ov_heating = override.get("heating") if override else None
        ov_expires = override.get("expires") if override else None
        logger.info("[Controller] %s | Temp: %s | Setpoint: %s | State: %s | Heating: %s | OverrideHeating: %s | OverrideExpires: %s", valve_id, valve.current_temp, effective_setpoint, valve.state.value, heating, ov_heating, ov_expires)

        #Pubblica comando MQTT
        topic_command = f"home/valves/{valve_id}/command"
        payload = {"heating": heating}

        self.mqtt_client.publish(topic_command, json.dumps(payload))
        # persist controller state
        try:
            self.repository.save_valve(valve_id, valve.setpoint, valve.last_seen, valve.state.value)
        except Exception:
            logger.exception("Errore salvataggio stato valvola")

    def _offline_sweep(self):
        while True:
            try:
                now = time.time()
                for vid, valve in list(self.valves.items()):
                    if valve.last_seen is None:
                        continue
                    if now - valve.last_seen > self.OFFLINE_TIMEOUT:
                        if valve.state != ValveState.OFFLINE:
                            logger.info("Marking valve %s as OFFLINE (last_seen %.1fs ago)", vid, now - valve.last_seen)
                            valve.state = ValveState.OFFLINE
                            try:
                                self.repository.save_valve(vid, valve.setpoint, valve.last_seen, valve.state.value)
                            except Exception:
                                logger.exception("Errore salvataggio stato valvola during offline sweep")
            except Exception:
                logger.exception("Errore nel ciclo di sweep offline")
            time.sleep(self.SWEEP_INTERVAL)


    def update_setpoint(self, valve_id, new_setpoint):
        if valve_id in self.valves:
            self.valves[valve_id].setpoint = new_setpoint
            logger.info("[Controller] Setpoint aggiornato per %s: %s", valve_id, new_setpoint)

            #aggironamento db
            self.repository.save_valve(
                valve_id,
                new_setpoint,
                self.valves[valve_id].last_seen
            )
        else:
            logger.warning("[Controller] Valvola %s non trovata", valve_id)