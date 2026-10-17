"""The demo steps that need no cloud service, against the local API server over PostgreSQL."""

import json
import threading
import uuid

import pytest

from booking.generator import SCALES, reference
from booking.handlers import runtime
from booking.seed import seed
from load import local_api
from ops import demo


@pytest.fixture
def ctx(monkeypatch, pool, vaults, tmp_path):
    seed(pool, 7, "small")
    monkeypatch.setattr(runtime, "pool", lambda: pool)
    runtime.client.cache_clear()
    for key, value in local_api.fake_aws().items():
        monkeypatch.setenv(key, value)
    server = local_api.Server(("127.0.0.1", 0), local_api.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    rooms = sorted(reference(7, SCALES["small"])["rooms"], key=lambda r: r["room_id"])
    monkeypatch.chdir(tmp_path)
    yield {"seed": 7, "scale": "small", "rooms": rooms, "apis": [url, url]}
    server.shutdown()
    runtime.client.cache_clear()


def test_traffic_books_replays_and_cancels(ctx):
    result = demo.traffic(ctx, bookings=60)
    assert result["failures"] == []
    statuses = {s for by in result["bookings_by_api_and_status"].values() for s in by}
    assert 201 in statuses and result["replay_status"] == 200
    assert result["cancel_statuses"] and set(result["cancel_statuses"]) == {200}


def test_availability_check_flags_only_hotels_without_a_free_room(ctx):
    api, hotel = ctx["apis"][0], ctx["rooms"][0]["hotel_id"]
    unknown = str(uuid.uuid4())
    assert demo.unavailable(api, [hotel, unknown], demo.SEARCH_STAY) == [unknown]


def test_a_failing_step_does_not_stop_the_others(ctx):
    def broken(_):
        raise RuntimeError("boom")

    summary = demo.run(ctx, {"first": broken, "second": lambda _: {"failures": []}})
    assert summary["first"]["passed"] is False and "boom" in summary["first"]["failures"][0]
    assert summary["second"] == {"passed": True, "failures": []}
    assert json.loads((demo.ARTIFACTS / "demo.json").read_text()) == summary


def test_a_booked_out_hotel_is_flagged_for_that_stay_only(ctx):
    api, hotel_id = ctx["apis"][0], ctx["rooms"][0]["hotel_id"]
    rooms = [r for r in ctx["rooms"] if r["hotel_id"] == hotel_id]
    assert set(demo.fill(api, rooms, demo.SEARCH_STAY)) == {201}
    assert demo.unavailable(api, [hotel_id], demo.SEARCH_STAY) == [hotel_id]
    later = tuple(d + demo.timedelta(days=3) for d in demo.SEARCH_STAY)
    assert demo.unavailable(api, [hotel_id], later) == []
