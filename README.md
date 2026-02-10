 # Termostato Smart — Progetto Universitario

Author: Naman Bagga

Corso: Laboratorio di sistemi embedded e IOT

Date: 10/02/2026

## Descrizione del progetto

Questo progetto realizza un prototipo di termostato intelligente per valvole radiatore utilizzando MQTT come mezzo di comunicazione. Il sistema include:

- Un controller che si sottoscrive ai report di temperatura e pubblica comandi alle valvole in base ai setpoint delle stanze e agli override manuali.
- Una dashboard web (FastAPI) per registrare valvole e stanze, visualizzare gli stati correnti e lo storico delle temperature, e inviare comandi manuali.
- Un simulatore multi-valvola che pubblica annunci retained e misure di temperatura periodiche e accetta comandi di accensione/spegnimento.
- Un livello di persistenza leggero basato su SQLite per memorizzare valvole, stanze, storico temperature e override manuali.

Il sistema è volutamente semplice e pensato per scopi didattici e dimostrativi.

## Architettura

- Broker MQTT (esterno) — es. Mosquitto su `localhost:1883`.
- Controller — `thermostat/core/controller.py` insieme a `thermostat/mqtt/client.py`. Si sottoscrive ai topic delle temperature e agli eventuali setpoint e decide lo stato di riscaldamento.
- API / Dashboard — `thermostat/api/app.py` (FastAPI) che serve la pagina in `thermostat/api/templates/DashBoard.html`.
- Simulatore — `valve_simulator/valve.py` (modulo `valve_simulator.valve`) per emulare più valvole.
- Persistenza — database SQLite `thermostat.db` creato e gestito da `thermostat/db/database.py` e accessibile tramite `thermostat/db/repository.py`.

Topic MQTT principali usati nel progetto:

- `home/valves/{id}/announce` (retained) — annunci di presenza/metadati da parte del simulatore/valvola.
- `home/valves/{id}/temperature` — pubblicazione periodica delle temperature (payload JSON).
- `home/valves/{id}/command` — comandi pubblicati dal controller o dalla dashboard: {"heating": true|false}.
- `home/thermostat/setpoint/{id}` — setpoint inviato via dashboard al controller (per valvola o stanza).

Il controller utilizza una logica di isteresi per evitare commutazioni troppo frequenti. Gli override manuali vengono salvati nel DB e rispettati fino alla scadenza.

## File principali

- `thermostat/main.py` — entrypoint del controller (inizializza DB e avvia il client MQTT).
- `thermostat/api/app.py` — applicazione FastAPI e rotte web (dashboard, gestione simulatori, CRUD stanze/valvole).
- `thermostat/core/controller.py` — logica decisionale: setpoint, isteresi, override, e rilevamento offline.
- `thermostat/db/database.py` — inizializzazione del DB e semplici migrazioni.
- `thermostat/db/repository.py` — layer di accesso al DB.
- `valve_simulator/valve.py` — simulatore multi-valvola (esegui come modulo passando gli id delle valvole come argomenti).
- `thermostat/api/templates/DashBoard.html` — template Jinja2 della dashboard (Bootstrap + Chart.js).

Consultare i file sorgente per i dettagli di implementazione.

## Prima esecuzione (sviluppo locale)

Prerequisiti:

- Python 3.10+ (il progetto è stato sviluppato usando Python 3.14 in virtualenv). Assicurarsi di avere `python` e `pip` funzionanti.
- Un broker MQTT raggiungibile su `localhost:1883` (es. Mosquitto).

Passi consigliati (in terminali separati):

1. Creare e attivare un virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Avviare il controller (inizializza il DB e si sottoscrive ai topic MQTT)

```bash
python -m thermostat.main
```

3. Avviare l'API / dashboard

```bash
uvicorn thermostat.api.app:app --reload --host 0.0.0.0 --port 8000
```

4. Aprire la dashboard nel browser:

```
http://localhost:8000/
```

5. Avviare i simulatori (dalla dashboard o manualmente):

Esempio da shell con 3 valvole:

```bash
python -m valve_simulator.valve valve1 valve2 valve3
```

Oppure usare il form della dashboard per avviare/spegnere simulatori specificando gli id separati da virgola.

Note:

- L'API usa un client paho MQTT in-process per pubblicare i comandi. Il controller gestisce le sottoscrizioni per temperature e setpoint; per funzionare al meglio entrambi i processi (controller e API) dovrebbero essere attivi.
- Il file del database `thermostat.db` viene creato nella cartella di lavoro corrente quando viene eseguito `init_db()` dal controller.

## Endpoint API (selezione)

- GET `/` — pagina della dashboard.
- GET `/valves` — lista JSON delle valvole registrate e dei loro stati.
- GET `/valves/{valve_id}/history` — storico delle temperature per una valvola.
- POST `/rooms` — crea una stanza (body: id, name, target_temp, hysteresis).
- POST `/valves` — registra una valvola (body: id, optional room_id).
- PUT `/valves/{valve_id}/setpoint` — invia il setpoint al controller per una valvola.
- POST `/web/valves/{valve_id}/command` — endpoint usato dalla dashboard per impostare un override manuale (heating on/off + durata). L'override viene salvato nel DB.
- POST `/web/simulators/start` — avvia un processo simulatore (comodità per sviluppo).
- POST `/web/simulators/stop` — arresta un simulatore per nome o pid.

Per i dettagli completi leggere `thermostat/api/app.py`.

## Schema del database (panoramica)

- Tabella `valves` — colonne: `id`, `setpoint`, `last_seen` (timestamp), `room_id`, `override_heating`, `override_expires`, `state` (HEATING|IDLE|OFFLINE).
- Tabella `temperature_readings` — letture temporizzate delle temperature per valvola.
- Tabella `rooms` — metadati stanza: id, name, target_temp, hysteresis.

Il layer repository (`thermostat/db/repository.py`) offre metodi di comodo per interrogare e aggiornare queste tabelle.

## Comportamento del simulatore

- Pubblica un payload `announce` retained per ogni valvola affinché il sistema possa scoprirle.
- Pubblica periodicamente valori di temperatura su `home/valves/{id}/temperature`.
- Si sottoscrive a `home/valves/+/command` e attiva/disattiva la variabile interna di riscaldamento per simulare la reazione ai comandi.

Il simulatore è volutamente semplice e facilita il testing della logica del controller e della dashboard.

## Risoluzione problemi e note

- Se le valvole appaiono offline nella dashboard, verificare che il simulatore o i dispositivi reali pubblicheranno aggiornamenti di `temperature` e che il controller sia in esecuzione.
- Se la dashboard non riesce a pubblicare comandi, verificare la connettività verso il broker MQTT (`localhost:1883` di default).
- I processi simulatore avviati dalla web API sono tracciati in una registry in memoria: tale registro viene perso se l'API viene riavviata. È disponibile un meccanismo di fallback tramite pid per arrestare processi rimasti attivi.

## Sviluppo & idee di estensione

- Integrare Alembic o altro sistema di migrazioni per gestire gli aggiornamenti dello schema.
- Persistere lo stato dei simulatori o usare un supervisor/process manager per test più affidabili.
- Aggiungere autenticazione alla dashboard e alle API.
- Migliorare il modello termico del simulatore e aggiungere rumore configurabile.
- Aggiungere test unitari e di integrazione per la logica di isteresi e override del controller.

## Licenza

Questo repository è fornito per scopi didattici.

## Contatti

Per domande consultare i file sorgente elencati sopra o contattare l'autore del progetto.
