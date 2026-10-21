from booking.generator import SCALES, reference
from booking.seed import ROOM_FIELDS, seed


def test_seed_matches_reference(db):
    ref = reference(7, SCALES["small"])
    assert seed(db, 7, "small") == {"rooms": 60}
    assert seed(db, 7, "small") == {"rooms": 60}  # a re-run adds nothing
    currency = {h["hotel_id"]: h["currency"] for h in ref["hotels"]}
    expected = {
        tuple(str(v) for v in ({**r, "currency": currency[r["hotel_id"]]}[f] for f in ROOM_FIELDS))
        for r in ref["rooms"]
    }
    assert {tuple(str(r[f]) for f in ROOM_FIELDS) for r in db.scan("rooms")} == expected
