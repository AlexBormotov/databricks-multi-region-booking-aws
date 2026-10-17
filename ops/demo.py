"""The demo's steps and the checks that turn their output into pass or fail (plan section 3.2).

    python -m ops.demo run --seed 7 --scale small    every step, artifacts into artifacts/
    python -m ops.demo check-k6 --attempts 1000 SUMMARY.json [SUMMARY.json ...]

Every step runs even if an earlier one failed, so a broken run still leaves its evidence. The
exit code is non-zero if any step failed.
"""

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import boto3

from booking import generator
from booking.db import create_pool
from ops.session import HOME, LIVE, outputs

ARTIFACTS = Path("artifacts")
REPO = Path(__file__).resolve().parents[1]
INVARIANT = (REPO / "sql" / "invariant.sql").read_text(encoding="utf-8")
ATTEMPTS = 1000
K6_REGIONS = ("us-east-1", "us-east-2", "us-west-2")
# The contested room-night lies after every stay the live traffic books.
CONTESTED = (date(2027, 3, 1), date(2027, 3, 2))
SEARCH_STAY = (date(2027, 2, 20), date(2027, 2, 22))


def contention(summaries: list[dict], attempts: int) -> dict:
    """Adds up the k6 summaries; exactly one attempt may win and every attempt must be answered."""
    names = ("created", "conflict", "busy", "other")
    total = {name: sum(s[name] for s in summaries) for name in names}
    answered = sum(total.values())
    failures = []
    if total["created"] != 1:
        failures.append(f"{total['created']} bookings created, expected exactly 1")
    if total["other"]:
        failures.append(f"{total['other']} responses were neither 201, 409 nor 503")
    if answered != attempts:
        failures.append(f"{answered} of {attempts} attempts answered")
    return {**total, "attempts": attempts, "failures": failures}


def call(method: str, url: str, body: dict | None = None, headers: dict | None = None):
    request = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}")


def free_rooms(api: str, hotel_id: str, stay: tuple[date, date]) -> list[str] | None:
    query = urlencode({"hotel_id": hotel_id, "check_in": stay[0], "check_out": stay[1]})
    status, body = call("GET", f"{api}/availability?{query}")
    return body.get("room_ids") if status == 200 else None


def unavailable(api: str, hotel_ids: list[str], stay: tuple[date, date]) -> list[str]:
    """The hotels with no free room for the stay, asked independently of /search."""
    return [h for h in hotel_ids if not free_rooms(api, h, stay)]


# --- steps ---------------------------------------------------------------------------------


def backfill(ctx) -> dict:
    s3 = boto3.client("s3", region_name=HOME)
    with tempfile.TemporaryDirectory() as tmp:
        generator.write(Path(tmp), ctx["seed"], ctx["scale"])
        keys = []
        for path in sorted(Path(tmp).rglob("*.json.gz")):
            key = path.relative_to(tmp).as_posix()
            s3.upload_file(str(path), ctx["landing"], key)
            keys.append(key)
    return {"bucket": ctx["landing"], "keys": keys, "failures": []}


def traffic(ctx, bookings: int = 200) -> dict:
    """Guests and bookings through both regions: 201s, 409s, a replay and some cancellations."""
    rng = random.Random(ctx["seed"])
    apis = ctx["apis"]
    guests = [
        call("POST", f"{api}/guests", {"name": "Demo Guest", "email": f"g{i}@example.org",
                                       "phone": "+1 555 0100", "country": country})
        for i, (api, country) in enumerate(zip(apis * 2, ("US", "DE", "GB", "FR"), strict=False))
    ]  # fmt: skip
    rooms = ctx["rooms"][:-1]  # the last room is reserved for the contention scenario
    requests = []
    for i in range(bookings):
        room = rng.choice(rooms)
        check_in = date(2027, 1, 5) + timedelta(days=rng.randrange(40))
        check_out = check_in + timedelta(days=rng.randint(1, 4))
        requests.append((apis[i % len(apis)], str(uuid.UUID(int=rng.getrandbits(128))), {
            "hotel_id": room["hotel_id"], "room_id": room["room_id"],
            "guest_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "check_in": str(check_in), "check_out": str(check_out),
        }))  # fmt: skip

    def book(request):
        api, key, body = request
        return api, call("POST", f"{api}/bookings", body, {"idempotency-key": key})

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(book, requests))
    by_status: dict[str, dict[int, int]] = {}
    for api, (status, _) in results:
        by_status.setdefault(api, {}).setdefault(status, 0)
        by_status[api][status] += 1
    replay = book(requests[0])[1][0]
    created = [body["booking_id"] for _, (status, body) in results if status == 201]
    cancelled = [
        call("POST", f"{apis[0]}/bookings/{b}/cancel")[0] for b in created[: len(created) // 10]
    ]
    failures = []
    if any(status not in (201, 409) for _, (status, _) in results):
        failures.append("a booking answered neither 201 nor 409")
    if replay not in (200, 201):
        failures.append(f"the replay answered {replay}")
    if any(status != 201 for status, _ in guests):
        failures.append("a guest registration failed")
    return {
        "guests": [status for status, _ in guests],
        "bookings_by_api_and_status": by_status,
        "replay_status": replay,
        "cancel_statuses": cancelled,
        "failures": failures,
    }


def fill(api: str, rooms: list[dict], stay: tuple[date, date]) -> list[int]:
    """Books every given room for the stay; returns the statuses."""
    return [
        call("POST", f"{api}/bookings", {
            "hotel_id": r["hotel_id"], "room_id": r["room_id"], "guest_id": str(uuid.uuid4()),
            "check_in": str(stay[0]), "check_out": str(stay[1]),
        }, {"idempotency-key": str(uuid.uuid4())})[0]
        for r in rooms
    ]  # fmt: skip


def search_ids(api: str, q: str, stay: tuple[date, date]) -> tuple[int, list[str]]:
    query = urlencode({"q": q, "check_in": stay[0], "check_out": stay[1]})
    status, body = call("GET", f"{api}/search?{query}")
    return status, [h["hotel_id"] for h in body.get("hotels", [])]


def search(ctx) -> dict:
    """Every hotel /search returns has a free room, and a hotel booked out for the stay is left
    out even when the query names it, while the same query on other dates returns it."""
    stay, other_stay = (
        SEARCH_STAY,
        (SEARCH_STAY[0] + timedelta(days=3), SEARCH_STAY[1] + timedelta(days=3)),
    )
    hotel = ctx["hotels"][0]
    filled = fill(
        ctx["apis"][0], [r for r in ctx["rooms"] if r["hotel_id"] == hotel["hotel_id"]], stay
    )
    named = f"{hotel['name']}, a hotel in {hotel['city']}"
    found, failures = {}, []
    if set(filled) != {201}:
        failures.append(f"could not book out {hotel['name']}: {filled}")
    for api in ctx["apis"]:
        results = {
            "generic": search_ids(api, "quiet hotel with a pool near the park", stay),
            "named_booked_out": search_ids(api, named, stay),
            "named_free": search_ids(api, named, other_stay),
        }
        found[api] = {k: {"status": st, "hotels": ids} for k, (st, ids) in results.items()}
        for kind, (status, ids) in results.items():
            if status != 200:
                failures.append(f"{api}/search ({kind}) answered {status}")
            when = other_stay if kind == "named_free" else stay
            if bad := unavailable(api, ids, when):
                failures.append(f"{api}/search ({kind}) returned hotels without a free room: {bad}")
        if hotel["hotel_id"] in results["named_booked_out"][1]:
            failures.append(f"{api}/search returned {hotel['name']}, which is booked out")
        if hotel["hotel_id"] not in results["named_free"][1]:
            failures.append(f"{api}/search did not return {hotel['name']} on free dates")
    # The availability check itself must go red: an unknown hotel has no free room.
    control = unavailable(ctx["apis"][0], [str(uuid.uuid4())], stay)
    if len(control) != 1:
        failures.append("the availability check did not flag an unknown hotel")
    return {"stay": [str(d) for d in stay], "booked_out": hotel, "found": found,
            "control_flagged": control, "failures": failures}  # fmt: skip


def k6(ctx) -> dict:
    room = ctx["rooms"][-1]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    # Time for three spot instances to boot and fetch k6; the script holds every VU until then.
    start_at_ms = int((time.time() + 6 * 60) * 1000)
    shares = [ATTEMPTS // len(K6_REGIONS) + (i < ATTEMPTS % len(K6_REGIONS)) for i in range(3)]
    env = {
        **os.environ,
        "TF_VAR_start_at_ms": str(start_at_ms),
        "TF_VAR_run_id": run_id,
        "TF_VAR_hotel_id": room["hotel_id"],
        "TF_VAR_room_id": room["room_id"],
        "TF_VAR_check_in": str(CONTESTED[0]),
        "TF_VAR_check_out": str(CONTESTED[1]),
    }
    applies = [
        subprocess.Popen(
            ["terragrunt", "apply", "-auto-approve", "-input=false", "--non-interactive"],
            cwd=LIVE / region / "k6",
            env={**env, "TF_VAR_attempts": str(share)},
        )
        for region, share in zip(K6_REGIONS, shares, strict=True)
    ]
    if any(p.wait() for p in applies):
        return {"run_id": run_id, "failures": ["a k6 instance could not be created"]}

    s3 = boto3.client("s3", region_name=HOME)
    keys = {region: f"k6/{run_id}/{region}.json" for region in K6_REGIONS}
    summaries, deadline = {}, start_at_ms / 1000 + 10 * 60
    while len(summaries) < len(keys) and time.time() < deadline:
        for region, key in keys.items():
            if region not in summaries:
                try:
                    obj = s3.get_object(Bucket=ctx["landing"], Key=key)
                    summaries[region] = json.loads(obj["Body"].read())
                except s3.exceptions.NoSuchKey:
                    pass
        time.sleep(15)
    result = contention(list(summaries.values()), ATTEMPTS)
    missing = sorted(set(keys) - set(summaries))
    if missing:
        result["failures"].append(f"no k6 summary from {missing}")
    subprocess.run(
        ["terragrunt", "run", "--all", "--non-interactive", "--filter", "./*/k6",
         "--", "destroy", "-auto-approve", "-input=false"],
        cwd=LIVE, env=env, check=False,
    )  # fmt: skip
    return {"run_id": run_id, "room": room, "night": str(CONTESTED[0]),
            "by_region": summaries, **result}  # fmt: skip


def invariant(ctx) -> dict:
    room = ctx["rooms"][-1]
    os.environ["DSQL_ENDPOINT"] = ctx["dsql_endpoint"]
    os.environ.pop("DSQL_ROLE", None)
    with create_pool(max_size=1) as pool, pool.connection() as conn:
        violations = conn.execute(INVARIANT).fetchall()
        contested = conn.execute(
            "SELECT count(*) FROM bookings WHERE room_id = %s AND check_in < %s AND %s < check_out",
            (room["room_id"], CONTESTED[1], CONTESTED[0]),
        ).fetchone()[0]
        total = conn.execute("SELECT count(*) FROM bookings").fetchone()[0]
    failures = []
    if violations:
        failures.append(f"{len(violations)} room-nights sold twice")
    if contested != 1:
        failures.append(f"{contested} bookings exist for the contested room-night, expected 1")
    return {"violations": [list(map(str, v)) for v in violations],
            "contested_bookings": contested, "bookings": total, "failures": failures}  # fmt: skip


def mrsc(ctx) -> dict:
    out = ARTIFACTS / "mrsc-race.json"
    subprocess.run(
        [sys.executable, str(REPO / "spike" / "dynamodb" / "mrsc_race.py"),
         "--table", ctx["mrsc_table"], "--attempts", "100", "--out", str(out)],
        check=False,
    )  # fmt: skip
    if not out.exists():
        return {"failures": ["the MRSC race script wrote no result"]}
    return json.loads(out.read_text())


STEPS = {
    "backfill": backfill,
    "traffic": traffic,
    "search": search,
    "k6": k6,
    "invariant": invariant,
    "mrsc": mrsc,
}


def context(seed: int, scale: str) -> dict:
    ref = generator.reference(seed, generator.SCALES[scale])
    return {
        "seed": seed,
        "scale": scale,
        "hotels": ref["hotels"],
        "rooms": sorted(ref["rooms"], key=lambda r: r["room_id"]),
        "apis": [outputs(f"{r}/api")["api_url"].rstrip("/") for r in ("us-east-1", "us-east-2")],
        "landing": outputs("us-east-1/landing")["bucket"],
        "dsql_endpoint": outputs("us-east-1/dsql")["endpoints"][HOME],
        "mrsc_table": outputs("us-east-1/mrsc")["table_name"],
    }


def run(ctx: dict, steps=STEPS) -> dict:
    ARTIFACTS.mkdir(exist_ok=True)
    summary = {}
    for name, step in steps.items():
        started = time.monotonic()
        try:
            result = step(ctx)
        except Exception:
            result = {"failures": [traceback.format_exc()]}
        result["seconds"] = round(time.monotonic() - started, 1)
        (ARTIFACTS / f"{name}.json").write_text(json.dumps(result, indent=2, default=str))
        summary[name] = {"passed": not result["failures"], "failures": result["failures"]}
        print(f"{name}: {'pass' if not result['failures'] else 'FAIL'} ({result['seconds']} s)")
    (ARTIFACTS / "demo.json").write_text(json.dumps(summary, indent=2))
    return summary


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="ops.demo")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("run")
    demo.add_argument("--seed", type=int, required=True)
    demo.add_argument("--scale", required=True)
    check = commands.add_parser("check-k6")
    check.add_argument("--attempts", type=int, required=True)
    check.add_argument("summaries", nargs="+", type=Path)
    args = parser.parse_args(argv)

    if args.command == "run":
        summary = run(context(args.seed, args.scale))
        sys.exit(0 if all(s["passed"] for s in summary.values()) else 1)
    if args.command == "check-k6":
        result = contention([json.loads(p.read_text()) for p in args.summaries], args.attempts)
        print(json.dumps(result, indent=2))
        sys.exit(1 if result["failures"] else 0)


if __name__ == "__main__":
    main()
