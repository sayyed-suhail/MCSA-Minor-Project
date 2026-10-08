"""Service Discovery client.

- register(): tells the registry "payment-service lives at http://host:port"
- heartbeat thread: re-registers every few seconds so the registry knows we're alive
- resolve(name): asks the registry for another service's URL by NAME
  (we never hard-code the Notification Service's address).

Registry contract (from the team's docs/api-contracts.md):
    POST /register        {"name": "...", "url": "http://..."}  -> 200
    GET  /discover/<name> -> 200 {"url": "http://..."} | 404
"""
import threading
import time

import requests

import config


def register():
    url = f"http://{config.HOST}:{config.PORT}"
    try:
        requests.post(f"{config.REGISTRY_URL}/register",
                      json={"name": config.SERVICE_NAME, "url": url},
                      timeout=config.HTTP_TIMEOUT)
        return True
    except requests.RequestException:
        # Fault tolerance: payment keeps working even if the registry is down.
        return False


def start_heartbeat():
    def loop():
        registered = None
        while True:
            ok = register()
            if ok != registered:
                print(f"[Discovery] registry {'reachable - registered' if ok else 'NOT reachable - will retry'}")
                registered = ok
            time.sleep(config.HEARTBEAT_SECONDS)

    threading.Thread(target=loop, daemon=True).start()


def resolve(service_name):
    """Return the base URL of a service by name, or raise if unknown."""
    resp = requests.get(f"{config.REGISTRY_URL}/discover/{service_name}",
                        timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["url"]
