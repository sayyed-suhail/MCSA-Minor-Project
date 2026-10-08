import threading, time
from flask import Flask, request, jsonify

# ----- Mock Event Service (5002) -----
event = Flask("event")
seats = {1: 10}

@event.get("/api/v1/events/<int:i>")
def get_event(i):
    return jsonify(id=i, name="Mock Cricket Final", available_seats=seats.get(i, 0), price=500)

@event.post("/api/v1/events/<int:i>/reserve")
def reserve(i):
    n = request.get_json()["seats"]
    if seats.get(i, 0) < n:
        return jsonify(error="Not enough seats"), 409
    seats[i] -= n
    print(f"[EVENT] reserved {n}, left {seats[i]}")
    return jsonify(ok=True, left=seats[i])

@event.post("/api/v1/events/<int:i>/release")
def release(i):
    seats[i] = seats.get(i, 0) + request.get_json()["seats"]
    print(f"[EVENT] released, left {seats[i]}")
    return jsonify(ok=True, left=seats[i])

# ----- Mock Payment Service (5004) -----
pay = Flask("payment")
state = {"down": False}

@pay.post("/api/v1/payments")
def payment():
    if state["down"]:
        return jsonify(error="Payment service down"), 500
    if request.get_json()["amount"] == 999:
        return jsonify(status="DECLINED"), 402
    return jsonify(status="SUCCESS"), 201

@pay.post("/toggle")
def toggle():
    state["down"] = not state["down"]
    return jsonify(down=state["down"])

# ----- Mock Notification Service (5005) -----
notif = Flask("notif")

@notif.post("/api/v1/notifications")
def notify():
    print("[NOTIFY]", request.get_json())
    return jsonify(ok=True)

def run(app, port):
    app.run(port=port, use_reloader=False)

for a, p in [(event, 5002), (pay, 5004), (notif, 5005)]:
    threading.Thread(target=run, args=(a, p), daemon=True).start()

print("Mocks running: event 5002, payment 5004, notification 5005. Ctrl+C to stop.")
while True:
    time.sleep(1)