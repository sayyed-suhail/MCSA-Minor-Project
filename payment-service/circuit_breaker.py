"""A small Circuit Breaker with CLOSED, OPEN and HALF_OPEN states.

CLOSED    -> calls go through normally. Each failure is counted.
OPEN      -> after `failure_threshold` failures, calls are NOT attempted;
             the fallback runs immediately (fail fast).
HALF_OPEN -> after `recovery_timeout` seconds one trial call is allowed.
             Success -> CLOSED, failure -> OPEN again.
"""
import threading
import time


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    CLOSED, OPEN, HALF_OPEN = "CLOSED", "OPEN", "HALF_OPEN"

    def __init__(self, name, failure_threshold=3, recovery_timeout=15):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = self.CLOSED
        self.failure_count = 0
        self.opened_at = None
        self.history = []          # last state changes, shown in the demo
        self._lock = threading.Lock()

    def _set_state(self, new_state):
        if new_state != self.state:
            self.history.append({"from": self.state, "to": new_state,
                                 "at": time.strftime("%H:%M:%S")})
            self.history = self.history[-10:]
            print(f"[CircuitBreaker:{self.name}] {self.state} -> {new_state}")
            self.state = new_state

    def call(self, func, *args, fallback=None, **kwargs):
        with self._lock:
            if self.state == self.OPEN:
                if time.time() - self.opened_at >= self.recovery_timeout:
                    self._set_state(self.HALF_OPEN)
                else:
                    if fallback:
                        return fallback(CircuitOpenError(f"{self.name} circuit is OPEN"))
                    raise CircuitOpenError(f"{self.name} circuit is OPEN")
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - any failure counts
            with self._lock:
                self.failure_count += 1
                if self.state == self.HALF_OPEN or self.failure_count >= self.failure_threshold:
                    self._set_state(self.OPEN)
                    self.opened_at = time.time()
            if fallback:
                return fallback(exc)
            raise
        with self._lock:
            self.failure_count = 0
            self._set_state(self.CLOSED)
        return result

    def status(self):
        retry_in = None
        if self.state == self.OPEN and self.opened_at:
            retry_in = max(0, round(self.recovery_timeout - (time.time() - self.opened_at), 1))
        return {
            "name": self.name,
            "state": self.state,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_sec": self.recovery_timeout,
            "half_open_in_sec": retry_in,
            "recent_transitions": self.history,
        }
