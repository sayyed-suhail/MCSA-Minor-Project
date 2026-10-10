
import sqlite3

from flask import Flask, request, jsonify
from database import get_connection, initialize_database

app = Flask(__name__)

# Initialize the Event Service database
initialize_database()


# -------------------- HEALTH CHECK --------------------

@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({
        "service": "Event Service",
        "status": "running"
    }), 200


# -------------------- VENUE APIs --------------------

@app.route("/api/v1/venues", methods=["POST"])
def create_venue():
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    location = data.get("location")
    capacity = data.get("capacity")

    if not name or not location or capacity is None:
        return jsonify({
            "error": "name, location and capacity are required"
        }), 400

    try:
        capacity = int(capacity)
        if capacity <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({
            "error": "capacity must be a positive integer"
        }), 400

    name = str(name).strip()
    location = str(location).strip()

    if not name or not location:
        return jsonify({"error": "Invalid venue name or location"}), 400

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO venues (name, location, capacity)
            VALUES (?, ?, ?)
        """, (name, location, capacity))

        venue_id = cursor.lastrowid

    return jsonify({
        "message": "Venue created successfully",
        "venue_id": venue_id
    }), 201


# -------------------- EVENT APIs: VERSION 1 --------------------

@app.route("/api/v1/events", methods=["POST"])
def create_event_v1():
    data = request.get_json(silent=True) or {}

    required = ["name", "sport", "event_date", "venue_id"]
    missing = [
        field for field in required
        if data.get(field) is None or data.get(field) == ""
    ]

    if missing:
        return jsonify({
            "error": "Missing required fields",
            "fields": missing
        }), 400

    name = str(data["name"]).strip()
    sport = str(data["sport"]).strip()
    event_date = str(data["event_date"]).strip()
    description = str(data.get("description", "")).strip()

    if not name or not sport or not event_date:
        return jsonify({
            "error": "Name, sport and event_date cannot be empty"
        }), 400

    try:
        venue_id = int(data["venue_id"])
        if venue_id <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({
            "error": "venue_id must be a positive integer"
        }), 400

    with get_connection() as conn:
        venue = conn.execute(
            "SELECT id FROM venues WHERE id = ?",
            (venue_id,)
        ).fetchone()

        if not venue:
            return jsonify({"error": "Venue not found"}), 404

        cursor = conn.execute("""
            INSERT INTO events
                (name, sport, description, event_date, venue_id)
            VALUES (?, ?, ?, ?, ?)
        """, (name, sport, description, event_date, venue_id))

        event_id = cursor.lastrowid

    return jsonify({
        "message": "Event created successfully",
        "event_id": event_id
    }), 201


@app.route("/api/v1/events", methods=["GET"])
def get_events_v1():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT e.*, v.name AS venue_name,
                   v.location AS venue_location
            FROM events e
            JOIN venues v ON e.venue_id = v.id
            ORDER BY e.id DESC
        """).fetchall()

    return jsonify([dict(row) for row in rows]), 200


@app.route("/api/v1/events/<int:event_id>", methods=["GET"])
def get_event_v1(event_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT e.*, v.name AS venue_name,
                   v.location AS venue_location
            FROM events e
            JOIN venues v ON e.venue_id = v.id
            WHERE e.id = ?
        """, (event_id,)).fetchone()

    if not row:
        return jsonify({"error": "Event not found"}), 404

    return jsonify(dict(row)), 200


@app.route("/api/v1/events/<int:event_id>", methods=["PUT"])
def update_event_v1(event_id):
    data = request.get_json(silent=True) or {}

    allowed = {
        "name", "sport", "description",
        "event_date", "venue_id", "status"
    }
    updates = {
        key: value for key, value in data.items()
        if key in allowed
    }

    if not updates:
        return jsonify({
            "error": "Provide at least one valid field"
        }), 400

    if any(value is None for value in updates.values()):
        return jsonify({"error": "Field values cannot be null"}), 400

    for field in ("name", "sport", "event_date"):
        if field in updates:
            updates[field] = str(updates[field]).strip()
            if not updates[field]:
                return jsonify({
                    "error": f"{field} cannot be empty"
                }), 400

    if "description" in updates:
        updates["description"] = str(updates["description"])

    if "venue_id" in updates:
        try:
            updates["venue_id"] = int(updates["venue_id"])
            if updates["venue_id"] <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({
                "error": "venue_id must be a positive integer"
            }), 400

    valid_statuses = {
        "scheduled", "ongoing", "completed", "cancelled"
    }

    if "status" in updates and updates["status"] not in valid_statuses:
        return jsonify({"error": "Invalid event status"}), 400

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM events WHERE id = ?",
            (event_id,)
        ).fetchone()

        if not existing:
            return jsonify({"error": "Event not found"}), 404

        if "venue_id" in updates:
            venue = conn.execute(
                "SELECT id FROM venues WHERE id = ?",
                (updates["venue_id"],)
            ).fetchone()

            if not venue:
                return jsonify({"error": "Venue not found"}), 404

        columns = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values()) + [event_id]

        conn.execute(
            f"UPDATE events SET {columns} WHERE id = ?",
            values
        )

    return jsonify({"message": "Event updated successfully"}), 200


@app.route("/api/v1/events/<int:event_id>", methods=["DELETE"])
def delete_event_v1(event_id):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM events WHERE id = ?",
            (event_id,)
        ).fetchone()

        if not existing:
            return jsonify({"error": "Event not found"}), 404

        conn.execute(
            "DELETE FROM events WHERE id = ?",
            (event_id,)
        )

    return jsonify({"message": "Event deleted successfully"}), 200


# -------------------- EVENT APIs: VERSION 2 --------------------

# V2 returns a simplified event representation inside a wrapper.
@app.route("/api/v2/events", methods=["GET"])
def get_events_v2():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT e.id, e.name, e.sport, e.event_date,
                   e.status, v.name AS venue
            FROM events e
            JOIN venues v ON e.venue_id = v.id
            ORDER BY e.event_date
        """).fetchall()

    return jsonify({
        "version": "v2",
        "count": len(rows),
        "events": [dict(row) for row in rows]
    }), 200


# -------------------- TEAM APIs --------------------

@app.route("/api/v1/teams", methods=["POST"])
def create_team():
    data = request.get_json(silent=True) or {}

    name = data.get("name")
    sport = data.get("sport")

    if not isinstance(name, str) or not name.strip():
        return jsonify({"error": "A valid team name is required"}), 400

    if not isinstance(sport, str) or not sport.strip():
        return jsonify({"error": "A valid sport is required"}), 400

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO teams (name, sport) VALUES (?, ?)",
                (name.strip(), sport.strip())
            )
            team_id = cursor.lastrowid

    except sqlite3.IntegrityError:
        return jsonify({"error": "Team name already exists"}), 409

    return jsonify({
        "message": "Team created successfully",
        "team_id": team_id
    }), 201


@app.route("/api/v1/teams", methods=["GET"])
def get_teams():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, name, sport, created_at
            FROM teams
            ORDER BY id
        """).fetchall()

    return jsonify([dict(row) for row in rows]), 200


@app.route(
    "/api/v1/events/<int:event_id>/teams/<int:team_id>",
    methods=["POST"]
)
def assign_team(event_id, team_id):
    with get_connection() as conn:
        event = conn.execute(
            "SELECT id FROM events WHERE id = ?",
            (event_id,)
        ).fetchone()

        if not event:
            return jsonify({"error": "Event not found"}), 404

        team = conn.execute(
            "SELECT id FROM teams WHERE id = ?",
            (team_id,)
        ).fetchone()

        if not team:
            return jsonify({"error": "Team not found"}), 404

        try:
            conn.execute("""
                INSERT INTO event_teams (event_id, team_id)
                VALUES (?, ?)
            """, (event_id, team_id))
        except sqlite3.IntegrityError:
            return jsonify({
                "error": "Team is already assigned to this event"
            }), 409

    return jsonify({
        "message": "Team assigned to event successfully"
    }), 201


@app.route("/api/v1/events/<int:event_id>/teams", methods=["GET"])
def get_event_teams(event_id):
    with get_connection() as conn:
        event = conn.execute(
            "SELECT id FROM events WHERE id = ?",
            (event_id,)
        ).fetchone()

        if not event:
            return jsonify({"error": "Event not found"}), 404

        rows = conn.execute("""
            SELECT t.id, t.name, t.sport
            FROM teams t
            JOIN event_teams et ON et.team_id = t.id
            WHERE et.event_id = ?
            ORDER BY t.name
        """, (event_id,)).fetchall()

    return jsonify([dict(row) for row in rows]), 200


# -------------------- ERROR HANDLERS --------------------

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# ---------- Seat reservation (needed by Booking Service saga) ----------
import requests as _requests

def _ensure_seats(conn, event_id):
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(events)")]
    if "available_seats" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN available_seats INTEGER")
    conn.execute("""UPDATE events SET available_seats =
                    (SELECT capacity FROM venues WHERE venues.id = events.venue_id)
                    WHERE id = ? AND available_seats IS NULL""", (event_id,))

@app.route("/api/v1/events/<int:event_id>/reserve", methods=["POST"])
def reserve_seats(event_id):
    n = (request.get_json(silent=True) or {}).get("seats")
    if not isinstance(n, int) or n <= 0:
        return jsonify({"error": "seats must be a positive integer"}), 400
    with get_connection() as conn:
        if not conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone():
            return jsonify({"error": "Event not found"}), 404
        _ensure_seats(conn, event_id)
        cur = conn.execute("""UPDATE events SET available_seats = available_seats - ?
                              WHERE id = ? AND available_seats >= ?""", (n, event_id, n))
        if cur.rowcount == 0:
            return jsonify({"error": "Not enough seats"}), 409
        left = conn.execute("SELECT available_seats FROM events WHERE id=?",
                            (event_id,)).fetchone()[0]
    return jsonify({"message": "Seats reserved", "available_seats": left}), 200

@app.route("/api/v1/events/<int:event_id>/release", methods=["POST"])
def release_seats(event_id):
    n = (request.get_json(silent=True) or {}).get("seats")
    if not isinstance(n, int) or n <= 0:
        return jsonify({"error": "seats must be a positive integer"}), 400
    with get_connection() as conn:
        if not conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone():
            return jsonify({"error": "Event not found"}), 404
        _ensure_seats(conn, event_id)
        conn.execute("""UPDATE events SET available_seats = MIN(available_seats + ?,
                        (SELECT capacity FROM venues WHERE venues.id = events.venue_id))
                        WHERE id = ?""", (n, event_id))
        left = conn.execute("SELECT available_seats FROM events WHERE id=?",
                            (event_id,)).fetchone()[0]
    return jsonify({"message": "Seats released", "available_seats": left}), 200

@app.route("/api/v1/events/<int:event_id>/seats", methods=["GET"])
def get_seats(event_id):
    with get_connection() as conn:
        if not conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone():
            return jsonify({"error": "Event not found"}), 404
        _ensure_seats(conn, event_id)
        left = conn.execute("SELECT available_seats FROM events WHERE id=?",
                            (event_id,)).fetchone()[0]
    return jsonify({"event_id": event_id, "available_seats": left})

def register_with_registry():
    try:
        _requests.post("http://127.0.0.1:5000/register",
                       json={"name": "event-service", "url": "http://127.0.0.1:5002"},
                       timeout=2)
        print("Registered with service registry")
    except Exception:
        print("Registry not reachable yet")
# -------------------- START SERVER --------------------

if __name__ == "__main__":
    register_with_registry()
    app.run(host="127.0.0.1", port=5002, debug=False)