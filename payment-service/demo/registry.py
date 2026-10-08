"""Minimal Service Registry — ONLY for testing the Payment Service alone.

If your team uses its own registry (or Consul/Eureka), you don't need this;
it just has to support the same two endpoints.

Run:  python demo/registry.py      (port 5000, as in docs/api-contracts.md)
"""
import time

from flask import Flask, jsonify, request

app = Flask(__name__)
services = {}          # name -> {"url": ..., "last_seen": ...}
TTL = 30               # seconds without heartbeat -> considered down


@app.post("/register")
def register():
    body = request.get_json(force=True)
    services[body["name"]] = {"url": body["url"], "last_seen": time.time()}
    return jsonify({"registered": body["name"]}), 200


@app.get("/services")
def list_services():
    alive = {n: s["url"] for n, s in services.items() if time.time() - s["last_seen"] < TTL}
    return jsonify(alive)


@app.get("/discover/<name>")
def get_service(name):
    s = services.get(name)
    if not s or time.time() - s["last_seen"] > TTL:
        return jsonify({"error": f"{name} not registered"}), 404
    return jsonify({"name": name, "url": s["url"]})


if __name__ == "__main__":
    app.run(port=5000)
