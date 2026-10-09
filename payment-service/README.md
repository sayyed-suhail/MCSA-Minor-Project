# Payment Service — Sports Event Management System

One microservice of Team 17's Microservices Mini Project (**Sports Event Management System**).
It handles payments for event bookings: spectator tickets and team or player registration fees.
Built with Python + Flask + SQLite, as suggested in the project brief.

 — Payment Service

It follows the team contract in `docs/api-contracts.md`: Payment runs on **port 5004**, the Registry on **5000**
(`/register`, `/discover/<name>`) and Notification on **5005**. A payment needs only `booking_id` and `amount`,
and an amount of **999 always fails** (for the saga demo).

### Where it sits in the team's architecture

```
Client → API Gateway → User Service         (user.db)
                     → Event Service        (event.db)    events, venues, seats/slots
                     → Booking Service      (booking.db)  Saga orchestrator
                     → Payment Service      (payment.db)  ← this service
                     → Notification Service (notification.db)
            all services register in the Service Registry
```

---

## 1. What this service does

| Responsibility | How |
|---|---|
| Collect payment for a booking (ticket or registration fee) | `POST /api/v1/payments` (simulated, no real card or UPI data) |
| Per-event collection report for organisers | `GET /api/v1/payments/event/<event_id>/summary` |
| Refund a payment (Saga compensating action) | `POST /api/v1/payments/<id>/refund` |
| Own its data | `payment.db` (tables `payments`, `refunds`, `pending_notifications`) |
| Service Discovery | Registers itself as `payment-service`; finds `notification-service` by name |
| Inter-service communication | Calls the Notification Service after a payment or refund |
| Circuit Breaker | Wraps the Notification call, with CLOSED → OPEN → HALF_OPEN → CLOSED |
| Fault tolerance | If Notification or the registry is down, payments **still succeed** and notifications are queued |

## 2. Folder structure

```
payment-service/
├── app.py               # Flask app: v1 + v2 APIs, refund, notify
├── config.py            # ports, URLs, CB settings (all overridable by env vars)
├── db.py                # SQLite schema - Database per Service
├── circuit_breaker.py   # CircuitBreaker class (CLOSED / OPEN / HALF_OPEN)
├── discovery.py         # register + heartbeat + resolve(service_name)
├── requirements.txt
├── postman_collection.json
├── tests/test_payment.py        # 15 automated tests
└── demo/                        # only for testing alone, before integration
    ├── registry.py              # stand-in registry (port 5000) until the team's registry is ready
    ├── notification_mock.py     # stand-in Notification Service (port 5005)
    └── saga_demo.py             # plays the Booking + Event Services to show the Saga
```

## 3. Setup and run

```bash
pip install -r requirements.txt

# Terminal 1 - registry (or the team's service-registry)
python demo/registry.py
# Terminal 2 - notification (or the team's notification-service)
python demo/notification_mock.py
# Terminal 3 - Payment Service
python app.py                # http://127.0.0.1:5004

# Terminal 4 - tests / demos
python -m pytest -v
python demo/saga_demo.py
```

On Windows or in Anaconda Prompt the commands are the same.

## 4. Database schema (payment.db)

| Table | Columns |
|---|---|
| `payments` | payment_id (PK), booking_id, event_id, user_id, amount, currency, method, status (`SUCCESS`/`FAILED`/`REFUNDED`), failure_reason, idempotency_key, created_at, updated_at |
| `refunds` | refund_id (PK), payment_id (FK), amount, reason, created_at |
| `pending_notifications` | id, payment_id, event, payload, created_at — the Circuit Breaker fallback outbox |

**Data isolation:** `booking_id`, `event_id` and `user_id` are stored only as references.
This service never opens the Booking, Event or User database, and no other service may open `payment.db`.
They must use the API below.

## 5. API reference

Base URL: `http://127.0.0.1:5004` (or through the API Gateway).

### v1

| Method | Endpoint | Purpose | Success | Errors |
|---|---|---|---|---|
| GET | `/health` | Health check | 200 | |
| POST | `/api/v1/payments` | Make a payment | 201 SUCCESS | 402 FAILED payment, 400 bad input |
| GET | `/api/v1/payments` | List all payments | 200 | |
| GET | `/api/v1/payments/<payment_id>` | Get one payment | 200 | 404 |
| GET | `/api/v1/payments/booking/<booking_id>` | Payments of a booking | 200 | |
| GET | `/api/v1/payments/event/<event_id>/summary` | Amount collected for an event, by status | 200 | |
| PUT | `/api/v1/payments/<payment_id>` | Retry a FAILED payment (new method or amount) | 200 | 402, 404, 409 if not FAILED |
| DELETE | `/api/v1/payments/<payment_id>` | Delete a FAILED or REFUNDED record | 200 | 404, 409 if SUCCESS (refund instead) |
| POST | `/api/v1/payments/<payment_id>/refund` | **Saga compensation**: refund | 200 | 404, 409 if not SUCCESS |
| POST | `/api/v1/payments/booking/<booking_id>/refund` | Refund using only the booking id | 200 | 404 |
| GET | `/api/v1/pending-notifications` | Notifications queued while Notification was down | 200 | |
| GET | `/circuit-breaker/status` | Current CB state and transitions | 200 | |

Request body for `POST /api/v1/payments`:
```json
{ "booking_id": 1, "amount": 500.0 }
```
This is the team contract. `event_id`, `user_id` and `method` (`UPI`, `CARD`, `WALLET` or `NETBANKING`, default `UPI`)
are optional extras. To test failure, send an amount of **999** (team test flag), an amount above 10000
(treated as insufficient funds), or `"simulate_failure": true`.

### v2: what changed and why

| Feature | v1 | v2 |
|---|---|---|
| `currency` field | optional (default INR) | **required** |
| Duplicate request protection | none | **`Idempotency-Key` header**: the same key returns the original payment, so the customer is never charged twice |
| Amount details | `amount` only | adds `amount_breakdown` {base, gst, gst_rate, total} |
| List endpoint | returns everything | `?status=SUCCESS&page=1&limit=10` with `total` count |
| Response shape | bare object | `{"version": "v2", "data": ...}` |

v2 endpoints are `POST /api/v2/payments`, `GET /api/v2/payments`, `GET /api/v2/payments/<id>` and `POST /api/v2/payments/<id>/refund`.
v1 keeps working unchanged, so older clients don't break. That is the reason for versioning.

## 6. Integration contract (for teammates)

**Booking Service (Saga orchestrator)**: the saga flow is:

`Create Booking (PENDING) → Event Service reserves seat/slot → Payment → Event Service confirms seat → Booking CONFIRMED → Notification`

1. After the Event Service reserves the seat or slot, call `POST /api/v1/payments` with at least `booking_id` and `amount`
   (sending `user_id` and `event_id` too is better: notifications and the event summary use them).
2. `201` with `status: SUCCESS` → ask the Event Service to confirm the seat.
   `402` with `status: FAILED` → ask the Event Service to release the seat and cancel the booking. There is nothing to refund.
3. If a **later** step fails (for example, the event is cancelled or the slot is no longer available), call
   `POST /api/v1/payments/<payment_id>/refund` (or `/api/v1/payments/booking/<booking_id>/refund`) → `status: REFUNDED`,
   then release the seat and cancel the booking. The refund is idempotent, so retrying is safe.

**Event Service** (optional): when an organiser cancels an event, it can refund every booking by calling the
booking refund endpoint for each one, and use `/payments/event/<event_id>/summary` to check that net collected is 0.

**Notification Service**: must register as `notification-service` and expose
`POST /api/v1/notifications` accepting the contract body:
```json
{ "user_id": 1, "message": "Payment PAY-XXXX of Rs 500.0 received for booking 1" }
```

**Service Registry**: Payment uses `POST /register {name, url}` and `GET /discover/<name> → {url}` on port 5000,
as in the contract. A different address can be set with the `REGISTRY_URL` environment variable.

**API Gateway**: route `/api/v1/payments*` and `/api/v2/payments*` to the URL of `payment-service`.

### Proposed addition to docs/api-contracts.md (Payment section)

The refund endpoint is not in the team contract yet. Suggested lines to add:
```
- POST /api/v1/payments/booking/<booking_id>/refund -> 200 {"status":"REFUNDED"} | 404 if no successful payment
  (Booking should call this when a CONFIRMED booking is cancelled)
```

## 7. Demo script for the viva

**Saga + compensation**: run `python demo/saga_demo.py`:
- A: seat reserved → payment SUCCESS → seat confirmed → booking CONFIRMED
- B: seat reserved → payment SUCCESS → event cancelled (rain) → **refund** + release seat → booking CANCELLED
- C: seat reserved → payment FAILED → release seat → booking CANCELLED (no refund)

**Circuit Breaker**: you can lower the timeout to make the demo faster, for example `set CB_RECOVERY_TIMEOUT=10` before `python app.py`.
1. With notification_mock running, make a payment. The notification terminal prints it, and `/circuit-breaker/status` shows `CLOSED`.
2. Stop notification_mock with Ctrl+C.
3. Make 3 payments. Each still returns 201, the Payment log prints `CLOSED -> OPEN`, and the status shows `OPEN`.
4. Make more payments. They succeed instantly without even trying to call Notification (fail fast). Check `/api/v1/pending-notifications` to see them queued.
5. Restart notification_mock and wait for the timeout. The next payment logs `OPEN -> HALF_OPEN -> CLOSED`.

**API versioning**: send the same payment to v1 and to v2 (with `currency`). Then send the v2 request twice with the same `Idempotency-Key` and show that it returns the same payment_id with `idempotent_replay: true`.

## 8. Test results

```
$ python -m pytest -v
15 passed
```
The tests cover create/get/list, validation, failure and PUT retry, refund and idempotent refund,
refund by booking, the team-contract body and the 999 test decline, the event summary, DELETE rules, v2 currency and GST breakdown, the v2 idempotency key, v2 pagination,
fault tolerance with the Notification service down, and all three Circuit Breaker states.
