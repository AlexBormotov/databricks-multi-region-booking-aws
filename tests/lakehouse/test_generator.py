import json
from collections import defaultdict
from datetime import date, datetime, timedelta

from booking.generator import SCALES, history, reference, write

SCALE = SCALES["small"]
CONTRACT = {
    "event_id", "event_type", "aggregate_id", "aggregate_version", "home_region",
    "occurred_at", "schema_version", "payload",
}  # fmt: skip


def events(seed=7):
    return [json.loads(e) for e in history(seed, SCALE, reference(seed, SCALE))]


def test_generator_seed(tmp_path):
    write(tmp_path / "a", 7, "small")
    write(tmp_path / "b", 7, "small")
    write(tmp_path / "c", 8, "small")
    files = sorted(p.relative_to(tmp_path / "a") for p in (tmp_path / "a").rglob("*.gz"))
    assert len(files) == 5
    for f in files:
        assert (tmp_path / "a" / f).read_bytes() == (tmp_path / "b" / f).read_bytes()
    assert any(
        (tmp_path / "a" / f).read_bytes() != (tmp_path / "c" / f).read_bytes() for f in files
    )


def test_generator_contract():
    evs = events()
    assert all(set(e) == CONTRACT for e in evs)
    assert len({e["event_id"] for e in evs}) == len(evs)
    assert all(datetime.fromisoformat(e["occurred_at"]).utcoffset() == timedelta(0) for e in evs)

    versions = defaultdict(list)
    for e in evs:
        if e["event_type"] == "BookingAttemptRejected":
            assert e["aggregate_id"] is None and e["aggregate_version"] is None
        elif e["event_type"] != "PaymentRefunded":
            versions[e["aggregate_id"]].append(e["aggregate_version"])
    assert all(v == list(range(1, len(v) + 1)) for v in versions.values())
    kinds = {e["event_type"] for e in evs}
    assert kinds == {
        "BookingHeld", "BookingConfirmed", "BookingExpired", "BookingCancelled",
        "PaymentRefunded", "BookingAttemptRejected",
    }  # fmt: skip


def test_generator_never_double_books():
    final = {}
    for e in events():
        if e["event_type"] not in ("BookingAttemptRejected", "PaymentRefunded"):
            final[e["aggregate_id"]] = e["payload"]
    sold = defaultdict(int)
    for b in final.values():
        if b["status"] == "confirmed":
            night = date.fromisoformat(b["check_in"])
            while night < date.fromisoformat(b["check_out"]):
                sold[b["room_id"], night] += 1
                night += timedelta(days=1)
    assert sold and max(sold.values()) == 1
