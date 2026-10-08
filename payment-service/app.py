"""Payment Service — Sports Event Management System (Team 17).

Responsibilities
  * Process (simulated) payments for event bookings
    (spectator tickets or team/player registration fees)
  * Refund a payment  -> the compensating action used by the Saga
  * Own its data in payment.db (Database per Service)
  * Register itself in the Service Registry (Service Discovery)
  * Notify the Notification Service through a Circuit Breaker

Run:  python app.py          (port 5004 by default)
"""
import json
import uuid
from datetime import datetime

import requests
from flask import Blueprint, Flask, jsonify, request

import config
import db
import discovery
from circuit_breaker import CircuitBreaker

notification_cb = CircuitBreaker("notification-service",
                                 failure_threshold=config.CB_FAILURE_THRESHOLD,
                                 recovery_timeout=config.CB_RECOVERY_TIMEOUT)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def now():
    return datetime.now().isoformat(timespec="seconds")


def error(message, code):
    return jsonify({"error": message}), code


def get_payment(payment_id):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()
    return db.row_to_dict(row)


def decide_outcome(amount, simulate_failure):
    """Simulated payment gateway. No real money / card data is involved."""
    if simulate_failure:
        return "FAILED", "Simulated gateway failure"
    if amount == config.TEST_DECLINE_AMOUNT:          # team contract: 999 always fails
        return "FAILED", f"Test decline (amount {config.TEST_DECLINE_AMOUNT:g})"
    if amount > config.MAX_AMOUNT:
        return "FAILED", f"Insufficient funds (limit {config.MAX_AMOUNT:.0f})"
    return "SUCCESS", None


def validate_body(body, require_currency=False):
    # Team contract (docs/api-contracts.md): only booking_id and amount are required.
    # event_id, user_id and method are optional extras.
    missing = [f for f in ("booking_id", "amount") if f not in body]
    if require_currency and "currency" not in body:
        missing.append("currency")
    if missing:
        return f"Missing fields: {', '.join(missing)}"
    try:
        amount = float(body["amount"])
    except (TypeError, ValueError):
        return "amount must be a number"
    if amount <= 0:
        return "amount must be greater than 0"
    if str(body.get("method", config.DEFAULT_METHOD)).upper() not in config.ALLOWED_METHODS:
        return f"method must be one of {sorted(config.ALLOWED_METHODS)}"
    return None


def create_payment(body, idempotency_key=None):
    amount = float(body["amount"])
    status, reason = decide_outcome(amount, body.get("simulate_failure", False))
    payment = {
        "payment_id": "PAY-" + uuid.uuid4().hex[:10].upper(),
        "booking_id": str(body["booking_id"]),
        "event_id": str(body.get("event_id", "")),
        "user_id": str(body.get("user_id", "")),
        "amount": round(amount, 2),
        "currency": body.get("currency", "INR").upper(),
        "method": str(body.get("method", config.DEFAULT_METHOD)).upper(),
        "status": status,
        "failure_reason": reason,
        "idempotency_key": idempotency_key,
        "created_at": now(),
        "updated_at": now(),
    }
    with db.get_conn() as conn:
        conn.execute(
            """INSERT INTO payments VALUES (:payment_id, :booking_id, :event_id, :user_id, :amount,
               :currency, :method, :status, :failure_reason, :idempotency_key,
               :created_at, :updated_at)""", payment)
    if status == "SUCCESS":
        notify("PAYMENT_SUCCESS", payment)
    return payment


def refund_payment(payment, reason):
    """Compensating action. Idempotent: refunding twice is safe."""
    if payment["status"] == "REFUNDED":
        return payment, 200
    if payment["status"] != "SUCCESS":
        return {"error": f"Only SUCCESS payments can be refunded (current: {payment['status']})"}, 409
    with db.get_conn() as conn:
        conn.execute("INSERT INTO refunds VALUES (?, ?, ?, ?, ?)",
                     ("REF-" + uuid.uuid4().hex[:10].upper(), payment["payment_id"],
                      payment["amount"], reason, now()))
        conn.execute("UPDATE payments SET status='REFUNDED', updated_at=? WHERE payment_id=?",
                     (now(), payment["payment_id"]))
    payment = get_payment(payment["payment_id"])
    notify("PAYMENT_REFUNDED", payment)
    return payment, 200


# --------------------------------------------------------------------------
# Inter-service communication: Notification Service via Circuit Breaker
# --------------------------------------------------------------------------
def _send_notification(event, payment):
    base_url = discovery.resolve(config.NOTIFICATION_SERVICE)     # Service Discovery
    resp = requests.post(f"{base_url}/api/v1/notifications",
                         json={"user_id": payment["user_id"],                 # team contract body
                               "message": NOTIFY_TEXT[event].format(**payment)},
                         timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return "SENT"


NOTIFY_TEXT = {
    "PAYMENT_SUCCESS": "Payment {payment_id} of Rs {amount} received for booking {booking_id}",
    "PAYMENT_REFUNDED": "Payment {payment_id} of Rs {amount} refunded for booking {booking_id}",
}


def notify(event, payment):
    """Never lets a notification problem break the payment (fault tolerance)."""
    def fallback(exc):
        # Fallback: keep the notification in our own outbox table for later.
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO pending_notifications (payment_id, event, payload, created_at) "
                "VALUES (?, ?, ?, ?)",
                (payment["payment_id"], event, json.dumps(payment), now()))
        print(f"[Payment] notification queued ({type(exc).__name__}: {exc})")
        return "QUEUED"

    return notification_cb.call(_send_notification, event, payment, fallback=fallback)


# --------------------------------------------------------------------------
# API v1
# --------------------------------------------------------------------------
v1 = Blueprint("v1", __name__, url_prefix="/api/v1")


@v1.post("/payments")
def v1_create():
    body = request.get_json(silent=True) or {}
    problem = validate_body(body)
    if problem:
        return error(problem, 400)
    payment = create_payment(body)
    return jsonify(payment), 201 if payment["status"] == "SUCCESS" else 402


@v1.get("/payments")
def v1_list():
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM payments ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@v1.get("/payments/<payment_id>")
def v1_get(payment_id):
    payment = get_payment(payment_id)
    return jsonify(payment) if payment else error("Payment not found", 404)


@v1.get("/payments/booking/<booking_id>")
def v1_by_booking(booking_id):
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM payments WHERE booking_id=? ORDER BY created_at",
                            (booking_id,)).fetchall()
    return jsonify([dict(r) for r in rows])


@v1.get("/payments/event/<event_id>/summary")
def v1_event_summary(event_id):
    """Collection report for one sports event (useful for the organiser)."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS total "
                            "FROM payments WHERE event_id=? GROUP BY status", (event_id,)).fetchall()
    by_status = {r["status"]: {"count": r["cnt"], "amount": round(r["total"], 2)} for r in rows}
    collected = by_status.get("SUCCESS", {}).get("amount", 0)
    return jsonify({"event_id": event_id, "net_collected": collected, "by_status": by_status})


@v1.put("/payments/<payment_id>")
def v1_retry(payment_id):
    """Retry a FAILED payment, optionally with a different method/amount."""
    payment = get_payment(payment_id)
    if not payment:
        return error("Payment not found", 404)
    if payment["status"] != "FAILED":
        return error("Only FAILED payments can be updated/retried", 409)
    body = request.get_json(silent=True) or {}
    method = str(body.get("method", payment["method"])).upper()
    if method not in config.ALLOWED_METHODS:
        return error(f"method must be one of {sorted(config.ALLOWED_METHODS)}", 400)
    amount = float(body.get("amount", payment["amount"]))
    status, reason = decide_outcome(amount, body.get("simulate_failure", False))
    with db.get_conn() as conn:
        conn.execute("""UPDATE payments SET method=?, amount=?, status=?, failure_reason=?,
                        updated_at=? WHERE payment_id=?""",
                     (method, amount, status, reason, now(), payment_id))
    payment = get_payment(payment_id)
    if status == "SUCCESS":
        notify("PAYMENT_SUCCESS", payment)
    return jsonify(payment), 200 if status == "SUCCESS" else 402


@v1.delete("/payments/<payment_id>")
def v1_delete(payment_id):
    payment = get_payment(payment_id)
    if not payment:
        return error("Payment not found", 404)
    if payment["status"] in ("SUCCESS",):
        return error("A successful payment cannot be deleted - refund it instead", 409)
    with db.get_conn() as conn:
        conn.execute("DELETE FROM refunds WHERE payment_id=?", (payment_id,))
        conn.execute("DELETE FROM payments WHERE payment_id=?", (payment_id,))
    return jsonify({"message": f"Payment {payment_id} deleted"}), 200


# ---- Saga compensating actions ----
@v1.post("/payments/<payment_id>/refund")
def v1_refund(payment_id):
    payment = get_payment(payment_id)
    if not payment:
        return error("Payment not found", 404)
    reason = (request.get_json(silent=True) or {}).get("reason", "Saga compensation")
    result, code = refund_payment(payment, reason)
    return jsonify(result), code


@v1.post("/payments/booking/<booking_id>/refund")
def v1_refund_by_booking(booking_id):
    """Convenient for the Booking Service: it may only know the booking_id."""
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE booking_id=? AND status IN "
                           "('SUCCESS','REFUNDED') ORDER BY created_at DESC LIMIT 1",
                           (booking_id,)).fetchone()
    if not row:
        return error("No successful payment found for this booking", 404)
    reason = (request.get_json(silent=True) or {}).get("reason", "Saga compensation")
    result, code = refund_payment(dict(row), reason)
    return jsonify(result), code


@v1.get("/pending-notifications")
def v1_pending_notifications():
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM pending_notifications ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


# --------------------------------------------------------------------------
# API v2  (differences documented in README)
#   - `currency` is mandatory
#   - supports the Idempotency-Key header (safe retries, no double charge)
#   - response includes a GST amount breakdown
#   - list endpoint supports ?status=&page=&limit= filtering/pagination
#   - every response is wrapped in {"version": "v2", "data": ...}
# --------------------------------------------------------------------------
v2 = Blueprint("v2", __name__, url_prefix="/api/v2")


def v2_view(payment):
    total = payment["amount"]
    base = round(total / (1 + config.GST_RATE), 2)
    payment = dict(payment)
    payment.pop("idempotency_key", None)
    payment["amount_breakdown"] = {"base": base, "gst": round(total - base, 2),
                                   "gst_rate": config.GST_RATE, "total": total}
    return payment


def v2_wrap(data, **extra):
    return jsonify({"version": "v2", "data": data, **extra})


@v2.post("/payments")
def v2_create():
    body = request.get_json(silent=True) or {}
    problem = validate_body(body, require_currency=True)
    if problem:
        return error(problem, 400)
    key = request.headers.get("Idempotency-Key")
    if key:
        with db.get_conn() as conn:
            existing = conn.execute("SELECT * FROM payments WHERE idempotency_key=?",
                                    (key,)).fetchone()
        if existing:   # same request retried -> return the original, do NOT charge again
            return v2_wrap(v2_view(dict(existing)), idempotent_replay=True), 200
    payment = create_payment(body, idempotency_key=key)
    return v2_wrap(v2_view(payment)), 201 if payment["status"] == "SUCCESS" else 402


@v2.get("/payments")
def v2_list():
    status = request.args.get("status")
    page = max(int(request.args.get("page", 1)), 1)
    limit = min(max(int(request.args.get("limit", 10)), 1), 100)
    where, params = ("WHERE status=?", [status.upper()]) if status else ("", [])
    with db.get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM payments {where}", params).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM payments {where} ORDER BY created_at DESC "
                            "LIMIT ? OFFSET ?", params + [limit, (page - 1) * limit]).fetchall()
    return v2_wrap([v2_view(dict(r)) for r in rows], page=page, limit=limit, total=total)


@v2.get("/payments/<payment_id>")
def v2_get(payment_id):
    payment = get_payment(payment_id)
    return v2_wrap(v2_view(payment)) if payment else error("Payment not found", 404)


@v2.post("/payments/<payment_id>/refund")
def v2_refund(payment_id):
    payment = get_payment(payment_id)
    if not payment:
        return error("Payment not found", 404)
    reason = (request.get_json(silent=True) or {}).get("reason", "Saga compensation")
    result, code = refund_payment(payment, reason)
    return (v2_wrap(v2_view(result)), code) if code == 200 else (jsonify(result), code)


# --------------------------------------------------------------------------
# App factory
# --------------------------------------------------------------------------
def create_app(start_discovery=True):
    app = Flask(__name__)
    db.init_db()
    app.register_blueprint(v1)
    app.register_blueprint(v2)

    @app.get("/health")
    def health():
        return jsonify({"service": config.SERVICE_NAME, "status": "UP"})

    @app.get("/circuit-breaker/status")
    def cb_status():
        return jsonify(notification_cb.status())

    if start_discovery:
        discovery.start_heartbeat()
    return app


if __name__ == "__main__":
    create_app().run(host=config.HOST, port=config.PORT, debug=False)
