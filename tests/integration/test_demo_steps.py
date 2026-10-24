"""The demo steps that need no cloud service, against the local API server over DynamoDB Local."""

import json
import threading

import pytest

from booking.generator import SCALES, reference
from booking.handlers import runtime
from booking.seed import seed
from load import local_api
from ops import demo


@pytest.fixture
def ctx(monkeypatch, db, vaults, tmp_path):
    seed(db, 7, "small")
    monkeypatch.setattr(runtime, "store", lambda: db)
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


def test_a_failing_step_does_not_stop_the_others(ctx):
    def broken(_):
        raise RuntimeError("boom")

    summary = demo.run(ctx, {"first": broken, "second": lambda _: {"failures": []}})
    assert summary["first"]["passed"] is False and "boom" in summary["first"]["failures"][0]
    assert summary["second"] == {"passed": True, "failures": []}
    assert json.loads((demo.ARTIFACTS / "demo.json").read_text()) == summary
