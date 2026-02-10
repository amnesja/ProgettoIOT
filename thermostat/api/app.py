import paho.mqtt.client as mqtt
import json
import time
import subprocess
import sys
import re
import os
import signal

from fastapi import FastAPI, HTTPException, Query
from fastapi.templating import Jinja2Templates
from pathlib import Path
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import Request, Form

from thermostat.db.database import get_connection
from thermostat.db.repository import ThermostatRepository
from thermostat.api.schema import RoomCreate, ValveRegister, SetpointModel


app = FastAPI(title="Smart Thermostat API")
# path dei template Jinja2
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
repo = ThermostatRepository()

# Client paho usato dall'API per pubblicare comandi (non per sottoscrizioni)
mqtt_client = mqtt.Client()
mqtt_client.connect("localhost", 1883, 60)
mqtt_client.loop_start()

# Registry in memoria per i processi simulatore lanciati dall'API (sviluppo)
# key: nome scelto dall'utente, value: subprocess.Popen
_sim_procs: dict[str, subprocess.Popen] = {}


def _valid_id(s: str) -> bool:
    # validazione semplice per gli id usati nella UI (solo lettere numeri _ e -)
    return re.match(r'^[A-Za-z0-9_\-]+$', s) is not None


@app.get("/valves")
def get_valves():
    # ritorna elenco di valvole salvate nel DB (JSON)
    return repo.get_valves()


@app.get("/valves/{valve_id}/history")
def get_history(valve_id: str, from_ts: float = None, to_ts: float = None, limit: int = 50):
    # restituisce lo storico di una valvola con filtri opzionali
    history = repo.get_valve_history(valve_id, from_ts, to_ts, limit)
    if not history:
        # 404 se non ci sono dati
        raise HTTPException(status_code=404, detail="Valvola non trovata o nessun dato disponibile")
    return history


@app.post("/rooms", status_code=201)
def create_room(payload: RoomCreate):
    # crea/aggiorna una stanza
    repo.save_room(payload.id, payload.name, payload.target_temp, payload.hysteresis)
    return {"message": "room created", "room_id": payload.id}


@app.get("/rooms")
def list_rooms():
    # lista stanze
    return repo.get_rooms()


@app.post("/valves", status_code=201)
def register_valve(payload: ValveRegister):
    # registra una valvola: se viene fornita una room la assegna
    if payload.room_id:
        repo.assign_valve_to_room(payload.id, payload.room_id)
    else:
        repo.save_valve(payload.id, 22.0, time.time())
    return {"message": "valve registered", "valve_id": payload.id}


@app.get("/rooms/{room_id}/history")
def room_history(room_id: str, from_ts: float | None = Query(None), to_ts: float | None = Query(None), limit: int = Query(50)):
    # storico aggregato per stanza (usa join tra valves e temperature_readings)
    room = repo.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="Room not found")
    history = repo.get_room_history(room_id, from_ts, to_ts, limit)
    return {"room_id": room_id, "history": history}


@app.put("/valves/{valve_id}/setpoint")
def update_setpoint(valve_id: str, data: SetpointModel):
    # endpoint API per inviare un setpoint: pubblica su topic MQTT
    setpoint = data.setpoint
    topic = f"home/thermostat/setpoint/{valve_id}"
    payload = {"setpoint": setpoint}

    mqtt_client.publish(topic, json.dumps(payload))

    return {"message": "Setpoint inviato al controller", "valve_id": valve_id, "new_setpoint": setpoint}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    # pagina HTML principale: passa stanze e valvole al template
    rooms = repo.get_rooms()
    valves = repo.get_valves()
    return templates.TemplateResponse("DashBoard.html", {"request": request, "rooms": rooms, "valves": valves})


@app.post("/web/valves/register")
def web_register_valve(id: str = Form(...), room_id: str | None = Form(None)):
    # form web per registrare una valvola
    if room_id:
        repo.assign_valve_to_room(id, room_id)
    else:
        repo.save_valve(id, 22.0, time.time())
    return RedirectResponse(url="/", status_code=303)


@app.post("/web/rooms/register")
def web_register_room(id: str = Form(...), name: str = Form(...), target_temp: float = Form(21.0), hysteresis: float = Form(0.5)):
    # form web per registrare una stanza
    repo.save_room(id, name, target_temp, hysteresis)
    return RedirectResponse(url="/", status_code=303)


@app.post("/web/valves/{valve_id}/assign")
def web_assign_valve(valve_id: str, room_id: str = Form(...)):
    # assegna una valvola a una stanza via web form
    repo.assign_valve_to_room(valve_id, room_id)
    return {"message": "assigned", "valve_id": valve_id, "room_id": room_id}


@app.post("/web/valves/{valve_id}/command")
def web_command_valve(valve_id: str, heating: str = Form(...), duration: int = Form(600)):
    # riceve il comando dalla UI: heating può essere 'true'/'false' o '1'/'0'
    h = True if str(heating).lower() in ("1", "true", "yes", "on") else False
    # calcola timestamp di scadenza dell'override (None se duration<=0)
    expires = time.time() + int(duration) if duration and int(duration) > 0 else None
    # salva l'override sul DB
    repo.set_valve_override(valve_id, h, expires)

    # pubblica anche il comando MQTT in modo che il simulatore riceva immediatamente
    topic = f"home/valves/{valve_id}/command"
    payload = {"heating": h}
    mqtt_client.publish(topic, json.dumps(payload))
    return {"message": "command sent", "valve_id": valve_id, "heating": h, "expires": expires}


@app.post("/web/valves/{valve_id}/setpoint")
def update_setpoint_web(valve_id: str, setpoint: float = Form(...)):
    # form web per inviare setpoint
    topic = f"home/thermostat/setpoint/{valve_id}"
    payload = {"setpoint": setpoint}

    mqtt_client.publish(topic, json.dumps(payload))

    return RedirectResponse(url="/", status_code=303)


@app.post("/web/valves/{valve_id}/delete")
def web_delete_valve(valve_id: str):
    # cancella valvola e relativo storico poi redirect alla dashboard
    repo.delete_valve(valve_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/web/rooms/{room_id}/edit")
def web_edit_room(room_id: str, name: str = Form(...), target_temp: float = Form(21.0), hysteresis: float = Form(0.5)):
    # modifica i parametri di una stanza
    repo.update_room(room_id, name, target_temp, hysteresis)
    return RedirectResponse(url="/", status_code=303)


@app.post("/web/rooms/{room_id}/delete")
def web_delete_room(room_id: str):
    # elimina una stanza e deslega valvole
    repo.delete_room(room_id)
    return RedirectResponse(url="/", status_code=303)


@app.post("/web/simulators/start")
def web_start_simulator(valves: str = Form(...), name: str = Form("sim")):
    # avvia un processo Python che esegue il modulo simulatore con gli id passati
    ids = [v.strip() for v in valves.split(',') if v.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="Provide at least one valve id")
    if len(ids) > 50:
        raise HTTPException(status_code=400, detail="Too many valve ids")
    for v in ids:
        if not _valid_id(v):
            raise HTTPException(status_code=400, detail=f"Invalid valve id: {v}")

    # se esiste già un processo con lo stesso nome e vivo, ritorniamo
    existing = _sim_procs.get(name)
    if existing and existing.poll() is None:
        return {"message": "already running", "name": name, "pid": existing.pid}

    cmd = [sys.executable, "-m", "valve_simulator.valve"] + ids
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # breve controllo: se il processo esce subito segnaliamo errore
    time.sleep(0.2)
    if p.poll() is not None:
        rc = p.returncode
        raise HTTPException(status_code=500, detail=f"simulator process exited immediately (rc={rc})")
    _sim_procs[name] = p
    return {"message": "started", "name": name, "pid": p.pid, "valves": ids}


@app.post("/web/simulators/stop")
def web_stop_simulator(name: str = Form(None), pid: int | None = Form(None)):
    # arresta un simulatore preferendo la ricerca per nome
    if name:
        p = _sim_procs.get(name)
        if not p:
            raise HTTPException(status_code=404, detail="simulator not found")
        if p.poll() is not None:
            # processo già terminato: rimuovilo dal registro
            del _sim_procs[name]
            return {"message": "already stopped", "name": name}
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        del _sim_procs[name]
        return {"message": "stopped", "name": name}

    # fallback: se viene passato il pid, proviamo a segnalare il processo
    if pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
            return {"message": "signalled pid", "pid": pid}
        except ProcessLookupError:
            raise HTTPException(status_code=404, detail="pid not found")
        except PermissionError:
            raise HTTPException(status_code=403, detail="permission denied to kill pid")

    raise HTTPException(status_code=400, detail="provide name or pid")


@app.get("/web/simulators")
def web_list_simulators():
    # lista dei simulatori attivi tracciati in memoria
    items = []
    for name, p in _sim_procs.items():
        items.append({"name": name, "pid": p.pid, "alive": p.poll() is None})
    return {"simulators": items}
