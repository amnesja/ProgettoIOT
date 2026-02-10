import time
from thermostat.db.database import get_connection


class ThermostatRepository:
    """Livello di accesso al database SQLite.

    Contiene metodi per salvare e leggere valvole, stanze e letture di temperatura.
    I metodi sono volutamente semplici e usano connessioni sqlite ad hoc.
    """

    def save_valve(self, valve_id, setpoint, last_seen, state=None):
        # salva o aggiorna una riga nella tabella valves preservando room_id
        conn = get_connection()
        cursor = conn.cursor()

        # Inseriamo solo se manca la riga (INSERT OR IGNORE) per non perdere room_id
        cursor.execute(
            "INSERT OR IGNORE INTO valves (id, setpoint, last_seen) VALUES (?, ?, ?)",
            (valve_id, setpoint, last_seen),
        )

        # Aggiorniamo i campi setpoint/last_seen e opzionalmente lo stato
        if state is None:
            cursor.execute(
                "UPDATE valves SET setpoint = ?, last_seen = ? WHERE id = ?",
                (setpoint, last_seen, valve_id),
            )
        else:
            cursor.execute(
                "UPDATE valves SET setpoint = ?, last_seen = ?, state = ? WHERE id = ?",
                (setpoint, last_seen, state, valve_id),
            )

        conn.commit()
        conn.close()

    def save_temperature(self, valve_id, temperature):
        # registra una lettura di temperatura nella tabella temperature_readings
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
        INSERT INTO temperature_readings (valve_id, temperature, timestamp)
        VALUES (?, ?, ?)
        """,
            (valve_id, temperature, time.time()),
        )

        conn.commit()
        conn.close()

    def get_valves(self):
        # restituisce tutte le valvole con campi utili per la UI
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, setpoint, last_seen, room_id, override_heating, override_expires, state FROM valves"
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "setpoint": r[1],
                "last_seen": r[2],
                "room_id": r[3],
                "override_heating": r[4],
                "override_expires": r[5],
                "state": r[6],
            }
            for r in rows
        ]

    def get_valve(self, valve_id):
        # legge una singola valvola per id
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, setpoint, last_seen, room_id, override_heating, override_expires, state FROM valves WHERE id = ?",
            (valve_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row[0],
            "setpoint": row[1],
            "last_seen": row[2],
            "room_id": row[3],
            "override_heating": row[4],
            "override_expires": row[5],
            "state": row[6],
        }

    def get_valve_history(self, valve_id, from_ts=None, to_ts=None, limit=50):
        # restituisce lo storico delle letture per una valvola con filtri opzionali
        conn = get_connection()
        cursor = conn.cursor()

        query = """
        SELECT temperature, timestamp
        FROM temperature_readings
        WHERE valve_id = ?
        """
        params = [valve_id]

        if from_ts is not None:
            query += " AND timestamp >= ?"
            params.append(from_ts)
        if to_ts is not None:
            query += " AND timestamp <= ?"
            params.append(to_ts)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()

        return [{"temperature": r[0], "timestamp": r[1]} for r in rows]

    def save_room(self, room_id, name, target_temp, hysteresis):
        # crea o aggiorna una stanza
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
        INSERT OR REPLACE INTO rooms (id, name, target_temp, hysteresis)
        VALUES (?, ?, ?, ?)
        """,
            (room_id, name, target_temp, hysteresis),
        )

        conn.commit()
        conn.close()

    def get_rooms(self):
        # ritorna tutte le stanze
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, name, target_temp, hysteresis FROM rooms")
        rows = cursor.fetchall()
        conn.close()

        rooms = []
        for row in rows:
            rooms.append({"id": row[0], "name": row[1], "target_temp": row[2], "hysteresis": row[3]})
        return rooms

    def get_room(self, room_id):
        # legge una singola stanza per id
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, name, target_temp, hysteresis FROM rooms WHERE id = ?",
            (room_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            return {"id": row[0], "name": row[1], "target_temp": row[2], "hysteresis": row[3]}
        else:
            return None

    def assign_valve_to_room(self, valve_id, room_id):
        # associa una valvola a una stanza; se la valvola non esiste la crea
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE valves
        SET room_id = ?
        WHERE id = ?
        """, (room_id, valve_id))

        if cursor.rowcount == 0:
            # la valvola non esiste: inseriscila con setpoint di default
            import time as _t

            cursor.execute(
                """
            INSERT INTO valves (id, setpoint, last_seen, room_id)
            VALUES (?, ?, ?, ?)
            """,
                (valve_id, 22.0, _t.time(), room_id),
            )
        conn.commit()
        conn.close()

    def delete_valve(self, valve_id):
        # elimina valvola e relativo storico temperature
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM valves WHERE id = ?", (valve_id,))
        cursor.execute("DELETE FROM temperature_readings WHERE valve_id = ?", (valve_id,))
        conn.commit()
        conn.close()

    def update_room(self, room_id, name: str, target_temp: float, hysteresis: float):
        # aggiorna i campi di una stanza
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE rooms SET name = ?, target_temp = ?, hysteresis = ? WHERE id = ?",
            (name, target_temp, hysteresis, room_id),
        )
        conn.commit()
        conn.close()

    def delete_room(self, room_id):
        # rimuove una stanza e deslega le valvole associate
        conn = get_connection()
        cursor = conn.cursor()
        # annulla room_id sulle valvole che la usano
        cursor.execute("UPDATE valves SET room_id = NULL WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        conn.commit()
        conn.close()

    def set_valve_override(self, valve_id, heating: bool, expires_ts: float | None):
        # imposta un override manuale sulla valvola (heating boolean e timestamp di scadenza opzionale)
        conn = get_connection()
        cursor = conn.cursor()

        # assicurati che la riga della valvola esista
        cursor.execute(
            "INSERT OR IGNORE INTO valves (id, setpoint, last_seen) VALUES (?, ?, ?)",
            (valve_id, 22.0, time.time()),
        )

        cursor.execute(
            "UPDATE valves SET override_heating = ?, override_expires = ? WHERE id = ?",
            (1 if heating else 0, expires_ts, valve_id),
        )

        conn.commit()
        conn.close()

    def clear_valve_override(self, valve_id):
        # rimuove l'override manuale per la valvola
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE valves SET override_heating = NULL, override_expires = NULL WHERE id = ?",
            (valve_id,),
        )
        conn.commit()
        conn.close()

    def get_valve_override(self, valve_id):
        # legge l'override se presente e lo restituisce in formato dict
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT override_heating, override_expires FROM valves WHERE id = ?", (valve_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return {"heating": bool(row[0]), "expires": row[1]}
        return None

    def get_room_history(self, room_id, from_ts=None, to_ts=None, limit=50):
        # restituisce lo storico delle temperature per tutte le valvole assegnate a una stanza
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
        SELECT t.temperature, t.timestamp
        FROM temperature_readings t
        JOIN valves v ON t.valve_id = v.id 
        WHERE v.room_id = ? AND t.timestamp BETWEEN ? AND ?
        ORDER BY t.timestamp DESC
        LIMIT ?
        """,
            (room_id, from_ts, to_ts, limit),
        )

        rows = cursor.fetchall()
        conn.close()

        history = []
        for row in rows:
            history.append({"temperature": row[0], "timestamp": row[1]})
        return history