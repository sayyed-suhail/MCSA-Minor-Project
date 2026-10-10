import requests
from flask import Flask, request, Response, jsonify

app = Flask(__name__)
REGISTRY = "http://127.0.0.1:5000"
FALLBACK = {
    "user-service": "http://127.0.0.1:5001",
    "event-service": "http://127.0.0.1:5002",
    "booking-service": "http://127.0.0.1:5003",
    "payment-service": "http://127.0.0.1:5004",
    "notification-service": "http://127.0.0.1:5005",
}

# path prefix -> service name
ROUTES = [
    ("/api/v1/users", "user-service"),
    ("/api/v2/users", "user-service"),
    ("/api/v1/login", "user-service"),
    ("/api/v1/events", "event-service"),
    ("/api/v2/events", "event-service"),
    ("/api/v1/venues", "event-service"),
    ("/api/v1/bookings", "booking-service"),
    ("/api/v2/bookings", "booking-service"),
    ("/api/v1/payments", "payment-service"),
    ("/api/v1/notifications", "notification-service"),
]

def discover(name):
    try:
        r = requests.get(f"{REGISTRY}/discover/{name}", timeout=2)
        r.raise_for_status()
        return r.json()["url"]
    except Exception:
        print(f"[GATEWAY] registry lookup failed, using fallback for {name}")
        return FALLBACK[name]

@app.get("/health")
def health():
    return jsonify(status="UP", service="api-gateway")

@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(path):
    full = "/" + path
    for prefix, service in ROUTES:
        if full.startswith(prefix):
            target = discover(service) + full
            print(f"[GATEWAY] {request.method} {full} -> {service}")
            try:
                resp = requests.request(
                    request.method, target,
                    params=request.args,
                    data=request.get_data(),
                    headers={"Content-Type": request.content_type or "application/json"},
                    timeout=10)
            except requests.RequestException as e:
                return jsonify(error=f"{service} unavailable", detail=str(e)), 503
            return Response(resp.content, resp.status_code,
                            content_type=resp.headers.get("Content-Type"))
    return jsonify(error="No route for this path"), 404

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True, use_reloader=False)