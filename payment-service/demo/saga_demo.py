"""Saga demo for the Sports Event Management System, from the Payment Service's side.

This script plays the Booking Service (the saga orchestrator) and the
Event Service, so you can demonstrate your part before the team integrates:

  A (happy path):    Create Booking -> Reserve Seat/Slot (Event) -> Payment SUCCESS
                     -> Confirm Booking -> Notify            => CONFIRMED
  B (compensation):  Create Booking -> Reserve Seat -> Payment SUCCESS
                     -> Confirm FAILS (event cancelled due to rain)
                     -> compensate: REFUND payment + RELEASE seat => CANCELLED
  C (early failure): Create Booking -> Reserve Seat -> Payment FAILED
                     -> compensate: RELEASE seat (nothing to refund) => CANCELLED

Run with the Payment Service already running:  python demo/saga_demo.py
(Set PAYMENT_URL to go through the API Gateway, e.g. http://127.0.0.1:5000)
"""
import os
import uuid

import requests

PAYMENT = os.getenv("PAYMENT_URL", "http://127.0.0.1:5004") + "/api/v1/payments"


def step(msg):
    print(f"   -> {msg}")


def run_saga(title, event_id, amount, confirm_ok, simulate_failure=False):
    booking_id = "BKG-" + uuid.uuid4().hex[:6].upper()
    print(f"\n=== {title} ({booking_id}, {event_id}) ===")
    step("Booking Service: booking created (status PENDING)")
    step("Event Service: 1 seat/slot RESERVED")

    r = requests.post(PAYMENT, json={"booking_id": booking_id, "event_id": event_id,
                                     "user_id": "U101", "amount": amount, "method": "UPI",
                                     "simulate_failure": simulate_failure}, timeout=5)
    pay = r.json()
    step(f"Payment Service: HTTP {r.status_code} status={pay['status']} "
         f"{pay.get('failure_reason') or ''}".rstrip())
    if pay["status"] != "SUCCESS":
        step("Compensation: Event Service RELEASES the seat (no refund needed)")
        step("Booking Service: booking CANCELLED")
        return

    if confirm_ok:
        step("Event Service: seat CONFIRMED")
        step("Booking Service: booking CONFIRMED (ticket issued)")
        return

    step("Event Service: confirmation FAILED - event cancelled due to rain")
    step("Compensation 1: asking Payment Service to refund ...")
    r = requests.post(f"{PAYMENT}/{pay['payment_id']}/refund",
                      json={"reason": "Event cancelled - booking could not be confirmed"},
                      timeout=5)
    step(f"Payment Service: HTTP {r.status_code} status={r.json()['status']}")
    step("Compensation 2: Event Service RELEASES the seat")
    step("Booking Service: booking CANCELLED")


if __name__ == "__main__":
    run_saga("Scenario A - happy path", "EVT-CRICKET-01", 499, confirm_ok=True)
    run_saga("Scenario B - event cancelled, payment refunded", "EVT-FOOTBALL-02", 799,
             confirm_ok=False)
    run_saga("Scenario C - payment fails (amount 999 = test decline)", "EVT-MARATHON-03", 999,
             confirm_ok=True)
    try:
        s = requests.get(PAYMENT + "/event/EVT-FOOTBALL-02/summary", timeout=5).json()
        print(f"\nEvent summary EVT-FOOTBALL-02: net collected Rs {s['net_collected']} "
              f"{s['by_status']}")
    except requests.RequestException:
        pass
