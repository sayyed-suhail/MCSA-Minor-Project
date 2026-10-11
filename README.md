# Sports Event Management System — Team 17

A microservices-based Sports Event Management System that allows users to browse sports events, book tickets, make payments, and receive notifications. Each microservice has its own codebase and database, and services communicate with one another through REST APIs.

## Architecture

                     Client (Postman / curl)
                              |
                       API Gateway (8000)
                              |
          +-------------------+------------------------------+
          |         |                   |         |         |
        User      Event              Booking   Payment  Notification
       (5001)    (5002)               (5003)   (5004)     (5005)
          |         |                   |         |          |
        user.db  event_db.sqlite3  booking.db payment.db  notification.db
                    |
          +-----------------------------+
          |     Service Registry        |
          |           (5000)             |
          +-----------------------------+


### Services Overview

| Service | Port | Database | Tables | Responsibility |
|---|---|---|---|---|
| Service Registry | 5000 | in-memory (no file) | none | Services register on startup; others look them up |
| User Service | 5001 | `user.db` | `users` | Registration, login, profiles |
| Event Service | 5002 | `event_db.sqlite3` | `venues`, `events`, `teams`, `event_teams` | Venues, events, teams, seat reservation |
| Booking Service | 5003 | `booking.db` | `bookings`, `saga_log` | Booking saga orchestrator, circuit breaker |
| Payment Service | 5004 | `payment.db` | `payments`, `refunds`, `pending_notifications` | Payments, refunds |
| Notification Service | 5005 | `notification.db` | `notifications` | Confirmation messages (mock), stored as logs |
| API Gateway | 8000 | none | none | Single entry point, routes by path via the registry |

Each service owns its database. No service directly reads or modifies another service's database. Inter-service communication takes place through REST APIs.

## Key Features and Design Patterns

### 1. Service Discovery

Services register themselves with the Service Registry using `POST /register`. Other services can discover registered services using `GET /discover/<service-name>`.

Example:

```bash
curl http://127.0.0.1:5000/discover/event-service
```

### 2. API Versioning

The system supports versioned API endpoints. Version 1 provides basic response fields, while version 2 provides extended response fields where implemented.

Examples:

- `GET /api/v1/events`
- `GET /api/v2/events`
- `GET /api/v1/users`
- `GET /api/v2/users`

### 3. Database per Service

The Service Registry uses in-memory storage, and the API Gateway does not maintain a database. All other services have their own SQLite database.

### 4. API Gateway

The API Gateway runs on port `8000` and serves as the single entry point for client requests. It routes requests to the appropriate microservice using the Service Registry.

### 5. Saga Pattern

The Booking Service orchestrates the booking workflow using the Saga pattern.

**Successful booking flow:**

Reserve Seats
     |
     v
Process Payment
     |
     v
Confirm Booking
     |
     v
Send Notification

If payment fails, the Booking Service requests the Event Service to release the previously reserved seats. The booking is then marked as `FAILED`, and the Saga log records the compensating action.

A notification failure does not reverse an otherwise successful payment and confirmed booking.

### 6. Circuit Breaker Pattern

The Booking Service uses a circuit breaker when communicating with the Payment Service.

- **CLOSED:** Requests are allowed normally.
- **OPEN:** Requests are temporarily blocked after repeated failures.
- **HALF_OPEN:** After a 10-second cooldown, a trial request is allowed.
- If the trial request succeeds, the circuit returns to `CLOSED`. If it fails, the circuit returns to `OPEN`.

The Payment Service also uses a circuit breaker for its communication with the Notification Service.

## Technology Stack

- **Programming Language:** Python
- **Backend Framework:** Flask
- **Database:** SQLite
- **Inter-service Communication:** REST APIs using the `requests` library
- **API Testing:** Postman and curl
- **Version Control:** Git and GitHub

## Project Structure

MCSA-Minor-Project/
├── service-registry/
├── user-service/
├── event-service/
├── booking-service/
├── payment-service/
├── notification-service/
├── api-gateway/
├── docs/
│   └── api-contracts.md
└── README.md


Each service directory contains its own application code, dependencies, and database where applicable.

## Setup and Execution

### Prerequisites

- Python installed
- Git installed
- Postman or curl for API testing

### Install Dependencies

Open a separate Git Bash terminal for each service and navigate to its directory.

For example, to set up the Event Service:

```bash
cd ~/MCSA-Minor-Project/event-service
python -m venv venv
source venv/Scripts/activate
pip install -r requirements.txt
```

Repeat the setup for each service, using its respective directory.

On macOS or Linux, activate the virtual environment with:

```bash
source venv/bin/activate
```

### Start the Services

Start the services in the following order. Keep each service running in its own terminal.

1. **Service Registry** — port `5000`
2. **User Service** — port `5001`
3. **Event Service** — port `5002`
4. **Payment Service** — port `5004`
5. **Notification Service** — port `5005`
6. **Booking Service** — port `5003`
7. **API Gateway** — port `8000`

For each service, navigate to its directory, activate its virtual environment, install dependencies if necessary, and run:

```bash
python app.py
```

Verify that the Registry is running and that services register successfully.

## API Testing and Demo

All client requests in the following examples go through the API Gateway at `http://127.0.0.1:8000`.

### Step 1: Create a Venue

```bash
curl -X POST http://127.0.0.1:8000/api/v1/venues \
-H "Content-Type: application/json" \
-d '{"name":"City Stadium","location":"Raichur","capacity":50}'
```

### Step 2: Create a Sports Event

```bash
curl -X POST http://127.0.0.1:8000/api/v1/events \
-H "Content-Type: application/json" \
-d '{"name":"Cricket Final","sport":"Cricket","event_date":"2026-11-20","venue_id":1}'
```

The `venue_id` must match the ID returned when the venue was created.

### Step 3: Test a Successful Booking

```bash
curl -X POST http://127.0.0.1:8000/api/v1/bookings \
-H "Content-Type: application/json" \
-d '{"user_id":1,"event_id":1,"seats":2,"amount":500}'
```

Expected result: a confirmed booking, provided the referenced user and event exist, seats are available, and payment succeeds.

Check the remaining seats:

```bash
curl http://127.0.0.1:8000/api/v1/events/1/seats
```

Check the Saga log using the booking ID returned by the previous request:

```bash
curl http://127.0.0.1:8000/api/v1/bookings/<booking_id>/saga
```

Replace `<booking_id>` with the actual booking ID.

### Step 4: Test Payment Failure and Compensation

Submit a booking with an amount of `999`, which is configured to be declined by the Payment Service.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/bookings \
-H "Content-Type: application/json" \
-d '{"user_id":1,"event_id":1,"seats":2,"amount":999}'
```

Expected result:

- Booking status: `FAILED`
- Failure reason: `Payment failed`
- Reserved seats are released by the compensating action.
- The Saga log records `COMPENSATE_RELEASE`.

### Step 5: Test the Circuit Breaker

1. Stop the Payment Service using `Ctrl + C`.
2. Send multiple booking requests through the API Gateway.
3. Observe the Booking Service terminal for the circuit-breaker state transition from `CLOSED` to `OPEN`.
4. Confirm that subsequent requests return a Payment Service unavailable response while the circuit is open.
5. Restart the Payment Service and wait for the configured cooldown.
6. Send another booking request and observe the `HALF_OPEN` trial and subsequent state transition, depending on the result.

The exact number of requests required to open the circuit depends on the current failure count and circuit-breaker implementation.

### Step 6: Test API Versioning

Compare the responses from the two event endpoints:

```bash
curl http://127.0.0.1:8000/api/v1/events
```

```bash
curl http://127.0.0.1:8000/api/v2/events
```

Compare the fields returned by each version.

## API Endpoints

The following endpoints are exposed through the API Gateway, subject to the routes implemented by each service.

| Service | Method | Endpoint |
|---|---|---|
| User | POST | `/api/v1/users` |
| User | POST | `/api/v1/login` |
| User | GET | `/api/v1/users` |
| User | GET | `/api/v2/users` |
| Event | POST | `/api/v1/venues` |
| Event | GET | `/api/v1/venues` |
| Event | POST | `/api/v1/events` |
| Event | GET | `/api/v1/events` |
| Event | PUT | `/api/v1/events/<id>` |
| Event | DELETE | `/api/v1/events/<id>` |
| Event | GET | `/api/v2/events` |
| Event | POST | `/api/v1/events/<id>/reserve` |
| Event | POST | `/api/v1/events/<id>/release` |
| Event | GET | `/api/v1/events/<id>/seats` |
| Booking | POST | `/api/v1/bookings` |
| Booking | GET | `/api/v1/bookings` |
| Booking | GET | `/api/v1/bookings/<id>` |
| Booking | DELETE | `/api/v1/bookings/<id>` |
| Booking | GET | `/api/v1/bookings/<id>/saga` |
| Booking | GET | `/api/v2/bookings/<id>` |
| Payment | POST | `/api/v1/payments` |
| Notification | POST | `/api/v1/notifications` |

For detailed request and response formats, refer to [`docs/api-contracts.md`](docs/api-contracts.md).

## Team Members — Responsibilities

| Team Member | Service / Responsibility |
|---|---|
| Sayyed Suhail Naqvi | User Service |
| BANDARU SAI CHARAN | Event Service |
| SEJAL NAIK | Booking Service (Saga and Circuit Breaker), API Gateway, and integration |
| Saurav barnwal | Payment Service |
| Sanjai S | Notification Service and Service Registry |

## Git Workflow

Each feature is developed on a separate branch and merged into `main` through a pull request.

Typical workflow:

```bash
git checkout main
git pull origin main
git checkout -b feature-branch
```

After making and testing changes:

```bash
git add <files-to-commit>
git commit -m "Describe the changes"
git push -u origin feature-branch
```

Create a pull request on GitHub, review the changed files, and merge it into `main` after approval.

### Files Not to Commit

The following should be excluded from version control:

- Python virtual environments (`venv/`)
- SQLite database files (`*.db`, `*.sqlite3`)
- Python cache files (`__pycache__/`, `*.pyc`)
- Local environment files containing secrets (`.env`)

Ensure these patterns are included in the repository's `.gitignore` file.

## Conclusion

The Sports Event Management System demonstrates core microservices concepts, including independent services and databases, service discovery, API Gateway routing, API versioning, Saga-based transaction management, compensating actions, and circuit breakers for handling service failures.
