"""Silver data-quality rules: one set feeds the pipeline expectations and the quarantine table.

Each rule is a SQL expression that must hold. It is wrapped in `coalesce(..., false)`, so a NULL
counts as a violation in both places.
"""

STATE_EVENTS = ("BookingHeld", "BookingConfirmed", "BookingExpired", "BookingCancelled")
CURRENCIES = ("USD", "EUR", "GBP", "JPY")

_STATE = ", ".join(f"'{e}'" for e in STATE_EVENTS)
_CURRENCIES = ", ".join(f"'{c}'" for c in CURRENCIES)

# Checked in this order; a quarantined row carries the name of the first rule it breaks.
RULES = {
    "versioned_state_event": f"event_type NOT IN ({_STATE}) OR aggregate_version IS NOT NULL",
    "known_currency": f"event_type = 'BookingAttemptRejected' OR currency IN ({_CURRENCIES})",
    "nights_inside_stay": "check_in < check_out AND check_out <= date_add(check_in, 30)",
}


def expectations() -> dict[str, str]:
    return {name: f"coalesce({expr}, false)" for name, expr in RULES.items()}
