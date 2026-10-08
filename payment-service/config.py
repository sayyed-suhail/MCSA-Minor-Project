"""Configuration for the Payment Service.

Every value can be overridden with an environment variable, so teammates can
change ports / URLs during integration without touching the code.
"""
import os

SERVICE_NAME = os.getenv("SERVICE_NAME", "payment-service")
HOST = os.getenv("PAYMENT_HOST", "127.0.0.1")
PORT = int(os.getenv("PAYMENT_PORT", "5004"))

# Database per Service: this file is owned ONLY by the Payment Service.
DB_PATH = os.getenv("PAYMENT_DB", os.path.join(os.path.dirname(__file__), "payment.db"))

# Service Discovery registry - team contract: Registry on port 5000
REGISTRY_URL = os.getenv("REGISTRY_URL", "http://127.0.0.1:5000")
HEARTBEAT_SECONDS = int(os.getenv("HEARTBEAT_SECONDS", "5"))

# Name under which the Notification Service registers itself
NOTIFICATION_SERVICE = os.getenv("NOTIFICATION_SERVICE", "notification-service")

# Circuit Breaker settings
CB_FAILURE_THRESHOLD = int(os.getenv("CB_FAILURE_THRESHOLD", "3"))   # failures before OPEN
CB_RECOVERY_TIMEOUT = int(os.getenv("CB_RECOVERY_TIMEOUT", "15"))    # seconds OPEN -> HALF_OPEN
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "2"))

# Simulated payment rules (no real payment / card data is ever used)
MAX_AMOUNT = float(os.getenv("MAX_AMOUNT", "10000"))   # above this -> "insufficient funds"
GST_RATE = float(os.getenv("GST_RATE", "0.18"))        # used by v2 for tax breakdown
ALLOWED_METHODS = {"UPI", "CARD", "WALLET", "NETBANKING"}
DEFAULT_METHOD = "UPI"                                  # used when the caller sends no method
TEST_DECLINE_AMOUNT = 999.0                             # team contract: amount 999 always fails
