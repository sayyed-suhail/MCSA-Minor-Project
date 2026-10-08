import sqlite3, time, requests
from flask import Flask, request, jsonify

app = Flask(__name__)
DB = "booking.db"
REGISTRY = "http://127.0.0.1:5000"
MY_URL = "http://127.0.0.1:5003"
# Used only if the registry is down (keeps local testing unblocked)
FALLBACK = {
    "event-service": "http://127.0.0.1:5002",
    "payment-service": "http://127.0.0.1:5004",
    "notification-service": "http://127.0.0.1:5005",
}

# ---------- Database (booking.db only) ----------
def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS bookings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, event_id INTEGER, seats INTEGER,
            amount REAL, status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("""CREATE TABLE IF NOT EXISTS saga_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER, step TEXT, result TEXT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP)""")

def log_step(bid, step, result):
    with db() as c:
        c.execute("INSERT INTO saga_log(booking_id, step, result) VALUES(?,?,?)",
                  (bid, step, result))
    print(f"[SAGA] booking={bid} {step}: {result}")

def set_status(bid, status):
    with db() as c:
        c.execute("UPDATE bookings SET status=? WHERE id=?", (status, bid))

# ---------- Service discovery ----------
def discover(name):
    try:
        r = requests.get(f"{REGISTRY}/discover/{name}", timeout=2)
        r.raise_for_status()
        return r.json()["url"]
    except Exception:
        print(f"[DISCOVERY] registry unavailable, using fallback for {name}")
        return FALLBACK[name]

def register():
    try:
        requests.post(f"{REGISTRY}/register",
                      json={"name": "booking-service", "url": MY_URL}, timeout=2)
        print("[DISCOVERY] registered with registry")
    except requests.RequestException:
        print("[DISCOVERY] registry not up yet")

# ---------- Circuit breaker ----------
class CircuitOpen(Exception):
    pass

class CircuitBreaker:
    def __init__(self, max_failures=3, cooldown=10):
        self.max_failures, self.cooldown = max_failures, cooldown
        self.failures, self.state, self.opened_at = 0, "CLOSED", 0

    def _set(self, state):
        if state != self.state:
            print(f"[BREAKER] {self.state} -> {state}")
        self.state = state

    def call(self, fn, *a, **kw):
        if self.state == "OPEN":
            if time.time() - self.opened_at >= self.cooldown:
                self._set("HALF_OPEN")
            else:
                raise CircuitOpen()
        try:
            result = fn(*a, **kw)
        except Exception:
            self.failures += 1
            if self.state == "HALF_OPEN" or self.failures >= self.max_failures:
                self._set("OPEN")
                self.opened_at = time.time()
            raise
        self.failures = 0
        self._set("CLOSED")
        return result

payment_breaker = CircuitBreaker()

# ---------- Calls to other services ----------
def reserve_seats(event_id, seats):
    url = discover("event-service")
    r = requests.post(f"{url}/api/v1/events/{event_id}/reserve",
                      json={"seats": seats}, timeout=3)
    r.raise_for_status()

def release_seats(event_id, seats):
    try:
        url = discover("event-service")
        requests.post(f"{url}/api/v1/events/{event_id}/release",
                      json={"seats": seats}, timeout=3)
    except Exception as e:
        print(f"[WARN] release failed: {e}")

def charge(booking_id, amount):
    url = discover("payment-service")
    r = requests.post(f"{url}/api/v1/payments",
                      json={"booking_id": booking_id, "amount": amount}, timeout=3)
    r.raise_for_status()

# ---------- Saga orchestrator ----------
@app.post("/api/v1/bookings")
def create_booking():
    d = request.get_json()
    with db() as c:
        cur = c.execute(
            "INSERT INTO bookings(user_id,event_id,seats,amount,status) VALUES(?,?,?,?,'PENDING')",
            (d["user_id"], d["event_id"], d["seats"], d["amount"]))
        bid = cur.lastrowid
    log_step(bid, "CREATED", "PENDING")

    # Step 1: reserve seats (nothing to undo if this fails)
    try:
        reserve_seats(d["event_id"], d["seats"])
        log_step(bid, "RESERVE_SEATS", "OK")
    except Exception as e:
        log_step(bid, "RESERVE_SEATS", f"FAILED: {e}")
        set_status(bid, "FAILED")
        return jsonify(id=bid, status="FAILED", reason="Seats unavailable"), 409

    # Step 2: payment through the circuit breaker
    try:
        payment_breaker.call(charge, bid, d["amount"])
        log_step(bid, "PAYMENT", "OK")
    except CircuitOpen:
        log_step(bid, "PAYMENT", "CIRCUIT_OPEN")
        release_seats(d["event_id"], d["seats"])
        log_step(bid, "COMPENSATE_RELEASE", "OK")
        set_status(bid, "FAILED")
        return jsonify(id=bid, status="FAILED",
                       reason="Payment service unavailable, try again shortly"), 503
    except Exception as e:
        log_step(bid, "PAYMENT", f"FAILED: {e}")
        release_seats(d["event_id"], d["seats"])
        log_step(bid, "COMPENSATE_RELEASE", "OK")
        set_status(bid, "FAILED")
        return jsonify(id=bid, status="FAILED", reason="Payment failed"), 402

    # Step 3: confirm
    set_status(bid, "CONFIRMED")
    log_step(bid, "CONFIRM", "OK")

    # Step 4: notify (best effort, never undoes a paid booking)
    try:
        url = discover("notification-service")
        requests.post(f"{url}/api/v1/notifications",
                      json={"user_id": d["user_id"],
                            "message": f"Booking {bid} confirmed"}, timeout=3)
        log_step(bid, "NOTIFY", "OK")
    except Exception as e:
        log_step(bid, "NOTIFY", f"FAILED (ignored): {e}")

    return jsonify(id=bid, status="CONFIRMED"), 201

# ---------- CRUD ----------
@app.get("/api/v1/bookings")
def list_bookings():
    with db() as c:
        rows = c.execute("SELECT * FROM bookings").fetchall()
    return jsonify([dict(r) for r in rows])

@app.get("/api/v1/bookings/<int:bid>")
def get_booking(bid):
    with db() as c:
        r = c.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    if not r:
        return jsonify(error="Not found"), 404
    return jsonify(dict(r))

@app.delete("/api/v1/bookings/<int:bid>")
def cancel_booking(bid):
    with db() as c:
        r = c.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    if not r:
        return jsonify(error="Not found"), 404
    if r["status"] == "CONFIRMED":
        release_seats(r["event_id"], r["seats"])
        log_step(bid, "CANCEL_RELEASE", "OK")
    set_status(bid, "CANCELLED")
    return jsonify(id=bid, status="CANCELLED")

@app.get("/api/v1/bookings/<int:bid>/saga")
def get_saga(bid):
    with db() as c:
        rows = c.execute("SELECT step,result,ts FROM saga_log WHERE booking_id=? ORDER BY id",
                         (bid,)).fetchall()
    return jsonify([dict(r) for r in rows])

# ---------- v2: same data plus the saga log ----------
@app.get("/api/v2/bookings/<int:bid>")
def get_booking_v2(bid):
    with db() as c:
        r = c.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
        if not r:
            return jsonify(error="Not found"), 404
        steps = c.execute("SELECT step,result,ts FROM saga_log WHERE booking_id=? ORDER BY id",
                          (bid,)).fetchall()
    out = dict(r)
    out["saga_log"] = [dict(s) for s in steps]
    out["circuit_state"] = payment_breaker.state
    return jsonify(out)

if __name__ == "__main__":
    init_db()
    register()
    app.run(port=5003, debug=True, use_reloader=False)