"""Fake Notification Service — used to demo inter-service communication and
the Circuit Breaker. Start it, make a payment, then STOP it (Ctrl+C) and make
more payments to watch the circuit open.

Run:  python demo/notification_mock.py      (port 5005)
"""
import threading
import time

import requests
from flask import Flask, jsonify, request

NAME, PORT, REGISTRY = "notification-service", 5005, "http://127.0.0.1:5000"
app = Flask(__name__)


@app.post("/api/v1/notifications")
def notify():
    body = request.get_json(force=True)
    print(f"[Notification] to user {body['user_id']}: {body['message']}")
    return jsonify({"ok": True}), 200


def heartbeat():
    while True:
        try:
            requests.post(f"{REGISTRY}/register",
                          json={"name": NAME, "url": f"http://127.0.0.1:{PORT}"}, timeout=2)
        except requests.RequestException:
            pass
        time.sleep(3)


if __name__ == "__main__":
    threading.Thread(target=heartbeat, daemon=True).start()
    app.run(port=PORT)
