import requests
from flask import Flask, jsonify, request
import sqlite3

app = Flask(__name__)

DATABASE = "notification.db"


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
def register_with_registry():
    registry_url = "http://127.0.0.1:5000/register"

    service_details = {
        "name": "notification-service",
        "url": "http://127.0.0.1:5005"
    }

    try:
        response = requests.post(
            registry_url,
            json=service_details,
            timeout=5
        )

        if response.status_code == 200:
            print("Successfully registered with Service Registry.")
        else:
            print("Registration failed:", response.text)

    except requests.RequestException as error:
        print("Could not connect to Service Registry:", error)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "service": "Notification Service",
        "status": "running"
    }), 200


@app.route("/api/v1/notifications", methods=["POST"])
def create_notification():

    data = request.get_json(silent=True) or {}

    user_id = data.get("user_id")
    message = data.get("message")

    if user_id is None or not message:
        return jsonify({
            "error": "user_id and message are required"
        }), 400

    conn = get_db_connection()

    cursor = conn.execute("""
        INSERT INTO notifications
        (user_id, message, status)
        VALUES (?, ?, ?)
    """, (
        user_id,
        message,
        "sent"
    ))

    notification_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "id": notification_id,
        "user_id": user_id,
        "message": message,
        "status": "sent"
    }), 200


@app.route("/api/v1/notifications", methods=["GET"])
def get_notifications():

    conn = get_db_connection()

    rows = conn.execute("""
        SELECT id, user_id, message, status
        FROM notifications
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    notifications = [dict(row) for row in rows]

    return jsonify({
        "notifications": notifications,
        "total": len(notifications)
    }), 200


if __name__ == "__main__":
    init_db()
    register_with_registry()
    app.run(port=5005, debug=True)