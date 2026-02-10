import paho.mqtt.client as mqtt
import time
import random
import json
import sys
import logging

logger = logging.getLogger(__name__)

BROKER = "localhost"
PORT = 1883


def parse_args():
    # accept list of valve ids as args
    if len(sys.argv) > 1:
        return sys.argv[1:]
    return ["valve1"]


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        payload = {}

    parts = msg.topic.split('/')
    # expect topic: home/valves/{id}/command
    if len(parts) >= 4 and parts[0] == 'home' and parts[1] == 'valves' and parts[3] == 'command':
        vid = parts[2]
        valves = userdata.get('valves', {}) if userdata else {}
        if vid in valves:
            valves[vid]['heating'] = bool(payload.get('heating'))
            logger.info('[VALVE_SIM] Command on %s: set heating=%s', vid, valves[vid]['heating'])
        else:
            logger.info('[VALVE_SIM] Command on unknown valve %s', vid)
    else:
        logger.info('[VALVE_SIM] Command on %s: %s', msg.topic, payload)


def start_simulator(valve_ids):
    valves_state = {}
    client = mqtt.Client(userdata={'valves': valves_state})
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)

    # subscribe to all valve commands
    client.subscribe('home/valves/+/command')
    client.loop_start()

    # initialize valve states and publish retained announce for each valve
    for vid in valve_ids:
        valves_state[vid] = {
            'heating': False,
            'temp': round(random.uniform(18.0, 22.0), 2)
        }
        ann = {"id": vid, "ts": time.time(), "proto": "sim"}
        client.publish(f"home/valves/{vid}/announce", json.dumps(ann), retain=True)

    try:
        while True:
            for vid in valve_ids:
                state = valves_state[vid]
                # simple thermal model: heat up when heating, cool down otherwise
                if state['heating']:
                    delta = random.uniform(0.05, 0.25)
                    state['temp'] += delta
                else:
                    delta = random.uniform(0.01, 0.15)
                    state['temp'] -= delta
                # clamp
                state['temp'] = round(max(5.0, min(35.0, state['temp'])), 2)

                payload = {"value": state['temp']}
                topic = f"home/valves/{vid}/temperature"
                client.publish(topic, json.dumps(payload))
                logger.info('[VALVE_SIM] %s published temperature: %s (heating=%s)', vid, state['temp'], state['heating'])
                # small sleep between publishes so timestamps differ
                time.sleep(0.5)
            # wait before next round
            time.sleep(2)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == '__main__':
    ids = parse_args()
    start_simulator(ids)
