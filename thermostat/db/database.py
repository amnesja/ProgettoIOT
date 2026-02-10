import sqlite3

DB_NAME = "thermostat.db"


def get_connection():
    # ritorna una connessione sqlite al DB locale
    return sqlite3.connect(DB_NAME)


def init_db():
    # crea le tabelle principali se mancanti e applica piccole 'migrazioni' additive
    conn = get_connection()
    cursor = conn.cursor()

    # tabella valvole base
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS valves (
        id TEXT PRIMARY KEY,
        setpoint REAL,
        last_seen REAL)
    """
    )

    # tabella storico temperature
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS temperature_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    valve_id TEXT,
    temperature REAL,
    timestamp REAL,
    FOREIGN KEY(valve_id) REFERENCES valves(id))
    """
    )

    # tabella stanze
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS rooms (
        id TEXT PRIMARY KEY,
        name TEXT,
        target_temp REAL DEFAULT 21.0,
        hysteresis REAL DEFAULT 0.5)
    """
    )

    # semplice migrazione: aggiunta di colonne se non presenti
    cursor.execute("PRAGMA table_info(valves)")
    cols = [r[1] for r in cursor.fetchall()]
    if "room_id" not in cols:
        cursor.execute("ALTER TABLE valves ADD COLUMN room_id TEXT")
    if "override_heating" not in cols:
        cursor.execute("ALTER TABLE valves ADD COLUMN override_heating INTEGER")
    if "override_expires" not in cols:
        cursor.execute("ALTER TABLE valves ADD COLUMN override_expires REAL")
    if "state" not in cols:
        cursor.execute("ALTER TABLE valves ADD COLUMN state INTEGER DEFAULT 0")

    # indice per ricerche per stanza
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_valves_room_id ON valves(room_id)")
    conn.commit()
    conn.close()