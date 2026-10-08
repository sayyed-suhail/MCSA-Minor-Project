"""Automated API tests.  Run from the payment-service folder:  python -m pytest -v"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import app as payment_app  # noqa: E402
from circuit_breaker import CircuitBreaker  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test_payment.db"))
    monkeypatch.setattr(config, "REGISTRY_URL", "http://127.0.0.1:1")   # nothing running
    payment_app.notification_cb.__init__("notification-service", 3, 15)
    return payment_app.create_app(start_discovery=False).test_client()


def pay(client, **over):
    body = {"booking_id": "BKG-1", "event_id": "EVT-1", "user_id": "U1", "amount": 500, "method": "UPI", **over}
    return client.post("/api/v1/payments", json=body)


def test_health(client):
    assert client.get("/health").json["status"] == "UP"


def test_create_and_get_payment(client):
    r = pay(client)
    assert r.status_code == 201 and r.json["status"] == "SUCCESS"
    pid = r.json["payment_id"]
    assert client.get(f"/api/v1/payments/{pid}").json["booking_id"] == "BKG-1"
    assert len(client.get("/api/v1/payments/booking/BKG-1").json) == 1


def test_validation_errors(client):
    assert client.post("/api/v1/payments", json={"amount": 10}).status_code == 400
    assert pay(client, amount=-5).status_code == 400
    assert pay(client, method="BITCOIN").status_code == 400


def test_failed_payment_and_retry_with_put(client):
    r = pay(client, amount=50000)
    assert r.status_code == 402 and r.json["status"] == "FAILED"
    pid = r.json["payment_id"]
    r = client.put(f"/api/v1/payments/{pid}", json={"amount": 900, "method": "CARD"})
    assert r.status_code == 200 and r.json["status"] == "SUCCESS"


def test_refund_is_compensation_and_idempotent(client):
    pid = pay(client).json["payment_id"]
    r1 = client.post(f"/api/v1/payments/{pid}/refund", json={"reason": "delivery failed"})
    r2 = client.post(f"/api/v1/payments/{pid}/refund")
    assert r1.json["status"] == r2.json["status"] == "REFUNDED"


def test_refund_by_booking(client):
    pay(client, booking_id="BKG-77")
    r = client.post("/api/v1/payments/booking/BKG-77/refund")
    assert r.status_code == 200 and r.json["status"] == "REFUNDED"


def test_team_contract_minimal_body_and_999_decline(client):
    # docs/api-contracts.md: body {"booking_id", "amount"} -> 201 | 402 if declined
    r = client.post("/api/v1/payments", json={"booking_id": 1, "amount": 500.0})
    assert r.status_code == 201 and r.json["method"] == "UPI"
    r = client.post("/api/v1/payments", json={"booking_id": 2, "amount": 999})
    assert r.status_code == 402 and r.json["status"] == "FAILED"


def test_event_summary(client):
    pay(client, event_id="EVT-CRICKET", amount=300)
    pay(client, event_id="EVT-CRICKET", amount=200)
    pid = pay(client, event_id="EVT-CRICKET", amount=500).json["payment_id"]
    client.post(f"/api/v1/payments/{pid}/refund")
    r = client.get("/api/v1/payments/event/EVT-CRICKET/summary").json
    assert r["net_collected"] == 500 and r["by_status"]["REFUNDED"]["count"] == 1


def test_cannot_refund_failed_payment(client):
    pid = pay(client, simulate_failure=True).json["payment_id"]
    assert client.post(f"/api/v1/payments/{pid}/refund").status_code == 409


def test_delete_rules(client):
    ok = pay(client).json["payment_id"]
    bad = pay(client, simulate_failure=True).json["payment_id"]
    assert client.delete(f"/api/v1/payments/{ok}").status_code == 409
    assert client.delete(f"/api/v1/payments/{bad}").status_code == 200
    assert client.get(f"/api/v1/payments/{bad}").status_code == 404


def test_v2_requires_currency_and_has_breakdown(client):
    body = {"booking_id": "BKG-2", "event_id": "EVT-1", "user_id": "U1", "amount": 118, "method": "UPI"}
    assert client.post("/api/v2/payments", json=body).status_code == 400
    r = client.post("/api/v2/payments", json={**body, "currency": "INR"})
    assert r.json["version"] == "v2"
    assert r.json["data"]["amount_breakdown"] == {"base": 100.0, "gst": 18.0,
                                                   "gst_rate": 0.18, "total": 118.0}


def test_v2_idempotency_key_prevents_double_charge(client):
    body = {"booking_id": "BKG-3", "event_id": "EVT-1", "user_id": "U1", "amount": 200, "method": "UPI",
            "currency": "INR"}
    h = {"Idempotency-Key": "abc-123"}
    first = client.post("/api/v2/payments", json=body, headers=h)
    second = client.post("/api/v2/payments", json=body, headers=h)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json["idempotent_replay"] is True
    assert first.json["data"]["payment_id"] == second.json["data"]["payment_id"]
    assert client.get("/api/v2/payments").json["total"] == 1


def test_v2_pagination_and_filter(client):
    for i in range(3):
        pay(client, booking_id=f"O{i}")
    pay(client, simulate_failure=True)
    r = client.get("/api/v2/payments?status=SUCCESS&limit=2&page=1").json
    assert r["total"] == 3 and len(r["data"]) == 2


def test_notification_down_payment_still_works_and_circuit_opens(client):
    # Registry/Notification unreachable -> payments must still succeed (fault tolerance)
    for i in range(4):
        assert pay(client, booking_id=f"CB-{i}").status_code == 201
    status = client.get("/circuit-breaker/status").json
    assert status["state"] == "OPEN"
    # Fallback stored every notification in the outbox
    assert len(client.get("/api/v1/pending-notifications").json) == 4


def test_circuit_breaker_states():
    cb = CircuitBreaker("x", failure_threshold=2, recovery_timeout=0)
    boom = lambda: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    fb = lambda e: "fallback"  # noqa: E731
    assert cb.call(boom, fallback=fb) == "fallback" and cb.state == "CLOSED"
    cb.call(boom, fallback=fb)
    assert cb.state == "OPEN"
    # recovery_timeout=0 -> next call goes HALF_OPEN, succeeds -> CLOSED
    assert cb.call(lambda: "ok") == "ok" and cb.state == "CLOSED"
    assert [h["to"] for h in cb.history] == ["OPEN", "HALF_OPEN", "CLOSED"]
