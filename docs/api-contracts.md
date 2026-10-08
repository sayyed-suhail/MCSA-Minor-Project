# API Contracts (Team 17)

Ports: Registry 5000 | User 5001 | Event 5002 | Booking 5003 | Payment 5004 | Notification 5005 | Gateway 8000

## Registry (Student 3)
- POST /register body {"name":"event-service","url":"http://localhost:5002"} -> 200
- GET /discover/<name> -> 200 {"url":"http://localhost:5002"} | 404

## Event Service (Student 1)
- GET /api/v1/events/<id> -> 200 {"id","name","available_seats","price"} | 404
- POST /api/v1/events/<id>/reserve body {"seats":2} -> 200 | 409 if not enough seats
- POST /api/v1/events/<id>/release body {"seats":2} -> 200

## Payment Service (Student 4)
- POST /api/v1/payments body {"booking_id":1,"amount":500.0} -> 201 | 402 if declined
- Test flag: amount 999 always fails (for the saga demo)

## Notification Service (Student 3)
- POST /api/v1/notifications body {"user_id":1,"message":"..."} -> 200

## Booking Service (Team leader)
- POST /api/v1/bookings body {"user_id","event_id","seats","amount"}
- GET /api/v1/bookings, GET /api/v1/bookings/<id>, DELETE /api/v1/bookings/<id>
- GET /api/v1/bookings/<id>/saga

## Rules
- All requests and responses are JSON. Any non-2xx status means failure.
- Every service registers itself with the registry on startup.
- Each service uses only its own .db file. No service reads another's database.
- Work only inside your own folder.