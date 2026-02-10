import time
from thermostat.db.database import get_connection

class ThermostatRepository:

    def save_valve(self, valve_id, setpoint, last_seen, state=None):
        conn = get_connection()
        cursor = conn.cursor()

        # Do not use INSERT OR REPLACE because it would delete the existing row
        # and drop the room_id column for that valve. Instead, insert if missing
        # and then update the setpoint/last_seen, preserving room_id.
        cursor.execute(
            "INSERT OR IGNORE INTO valves (id, setpoint, last_seen) VALUES (?, ?, ?)",
            (valve_id, setpoint, last_seen)
        )

        if state is None:
            cursor.execute(
                "UPDATE valves SET setpoint = ?, last_seen = ? WHERE id = ?",
                (setpoint, last_seen, valve_id)
            )
        else:
            cursor.execute(
                "UPDATE valves SET setpoint = ?, last_seen = ?, state = ? WHERE id = ?",
                (setpoint, last_seen, state, valve_id)
            )

        conn.commit()
        conn.close()

    def save_temperature(self, valve_id, temperature):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO temperature_readings (valve_id, temperature, timestamp)
        VALUES (?, ?, ?)
        """, (valve_id, temperature, time.time()))

        conn.commit()
        conn.close()

    def get_valves(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, setpoint, last_seen, room_id, override_heating, override_expires, state FROM valves")
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "setpoint": r[1], "last_seen": r[2], "room_id": r[3], "override_heating": r[4], "override_expires": r[5], "state": r[6]}
            for r in rows
        ]

    def get_valve(self, valve_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, setpoint, last_seen, room_id, override_heating, override_expires, state FROM valves WHERE id = ?", (valve_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {"id": row[0], "setpoint": row[1], "last_seen": row[2], "room_id": row[3], "override_heating": row[4], "override_expires": row[5], "state": row[6]}
    def get_valve_history(self, valve_id, from_ts=None, to_ts=None, limit=50):
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
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT OR REPLACE INTO rooms (id, name, target_temp, hysteresis)
        VALUES (?, ?, ?, ?)
        """, (room_id, name, target_temp, hysteresis))

        conn.commit()
        conn.close()

    def get_rooms(self):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, name, target_temp, hysteresis FROM rooms")
        rows = cursor.fetchall()
        conn.close()

        rooms = []
        for row in rows:
            rooms.append({
                "id": row[0],
                "name": row[1],
                "target_temp": row[2],
                "hysteresis": row[3]
            })
        return rooms
    
    def get_room(self, room_id):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, name, target_temp, hysteresis FROM rooms WHERE id = ?", (room_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "id": row[0],
                "name": row[1],
                "target_temp": row[2],
                "hysteresis": row[3]
            }
        else:
            return None
        
    def assign_valve_to_room(self, valve_id, room_id):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        UPDATE valves
        SET room_id = ?
        WHERE id = ?
        """, (room_id, valve_id))

        if cursor.rowcount == 0:
            import time
            cursor.execute("""
            INSERT INTO valves (id, setpoint, last_seen, room_id)
            VALUES (?, ?, ?, ?)
            """, (valve_id, 22.0, time.time(), room_id))
        conn.commit()
        conn.close()

    def delete_valve(self, valve_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM valves WHERE id = ?", (valve_id,))
        cursor.execute("DELETE FROM temperature_readings WHERE valve_id = ?", (valve_id,))
        conn.commit()
        conn.close()

    def update_room(self, room_id, name: str, target_temp: float, hysteresis: float):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE rooms SET name = ?, target_temp = ?, hysteresis = ? WHERE id = ?",
                       (name, target_temp, hysteresis, room_id))
        conn.commit()
        conn.close()

    def delete_room(self, room_id):
        conn = get_connection()
        cursor = conn.cursor()
        # unset room_id on valves assigned to this room
        cursor.execute("UPDATE valves SET room_id = NULL WHERE room_id = ?", (room_id,))
        cursor.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        conn.commit()
        conn.close()

    def set_valve_override(self, valve_id, heating: bool, expires_ts: float | None):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("INSERT OR IGNORE INTO valves (id, setpoint, last_seen) VALUES (?, ?, ?)",
                       (valve_id, 22.0, time.time()))

        cursor.execute("UPDATE valves SET override_heating = ?, override_expires = ? WHERE id = ?",
                       (1 if heating else 0, expires_ts, valve_id))

        conn.commit()
        conn.close()

    def clear_valve_override(self, valve_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE valves SET override_heating = NULL, override_expires = NULL WHERE id = ?", (valve_id,))
        conn.commit()
        conn.close()

    def get_valve_override(self, valve_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT override_heating, override_expires FROM valves WHERE id = ?", (valve_id,))
        row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return {"heating": bool(row[0]), "expires": row[1]}
        return None

    def get_room_history(self, room_id, from_ts = None, to_ts = None, limit=50):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT t.temperature, t.timestamp
        FROM temperature_readings t
        JOIN valves v ON t.valve_id = v.id 
        WHERE v.room_id = ? AND t.timestamp BETWEEN ? AND ?
        ORDER BY t.timestamp DESC
        LIMIT ?
        """, (room_id, from_ts, to_ts, limit))

        rows = cursor.fetchall()
        conn.close()

        history = []
        for row in rows:
            history.append({
                "temperature": row[0],
                "timestamp": row[1]
            })
        return history