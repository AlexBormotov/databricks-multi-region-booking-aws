#!/usr/bin/env python3
"""Record CLI usage without storing prompts, responses, credentials or billing estimates."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

ROUTES = ("claude", "codex", "cursor", "gemini")
MAX_OUTPUT = 32 * 1024 * 1024


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def state_dir():
    if os.environ.get("SECOND_OPINION_STATE_DIR"):
        return Path(os.environ["SECOND_OPINION_STATE_DIR"]).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    project = hashlib.sha256(os.fsencode(Path.cwd().resolve())).hexdigest()[:16]
    return base / "ai-factory-kit/second-opinion" / project


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=True, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def counters(value, keys):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in keys:
        if key in value:
            number = value[key]
            if type(number) is not int or number < 0:
                raise ValueError("invalid_token_counter")
            result[key] = number
    return result


def objects(raw):
    # Decode whole objects, never nested JSON quoted inside an assistant answer.
    decoder = json.JSONDecoder()
    position = 0
    while position < len(raw):
        start = raw.find("{", position)
        if start < 0:
            return
        try:
            value, length = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            newline = raw.find("\n", start)
            if newline < 0:
                return
            position = newline + 1
            continue
        position = start + length
        if isinstance(value, dict):
            yield value


def parse_usage(route, raw):
    result = {"terminal": False, "provider_success": None, "coverage": "unknown",
              "scope": "unreported", "total_tokens": None, "counters": []}
    events = list(objects(raw))
    if route == "codex":
        ends = [e for e in events if e.get("type") in ("turn.completed", "turn.failed")]
        if not ends:
            return result
        result.update(terminal=True, provider_success=ends[-1]["type"] == "turn.completed")
        # This adapter sends one prompt and does not resume. Multiple turns are ambiguous.
        if len(ends) != 1 or ends[0]["type"] != "turn.completed":
            result["scope"] = "ambiguous_or_failed_turn"
            return result
        c = counters(ends[0].get("usage"), ("input_tokens", "cached_input_tokens",
                     "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens"))
        result.update(scope="completed_turn", counters=[c] if c else [])
        if "input_tokens" in c and "output_tokens" in c:
            for subset, whole in (("cached_input_tokens", "input_tokens"),
                                  ("reasoning_output_tokens", "output_tokens")):
                if c.get(subset, 0) > c[whole]:
                    raise ValueError("invalid_token_subset")
            result.update(coverage="reported", total_tokens=c["input_tokens"] + c["output_tokens"])
        return result
    if route in ("claude", "cursor"):
        ends = [e for e in events if e.get("type") == "result"]
        if not ends:
            return result
        final = ends[-1]
        result.update(terminal=True, provider_success=(final.get("subtype") == "success"
                      and final.get("is_error") is False))
        if route == "cursor":
            result["scope"] = "token_usage_not_in_documented_schema"
            return result
        models = final.get("modelUsage")
        if isinstance(models, dict) and models:
            rows = []
            totals = []
            for model, usage in models.items():
                if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,150}", model):
                    raise ValueError("invalid_model_identifier")
                c = counters(usage, ("inputTokens", "outputTokens", "cacheReadInputTokens",
                                     "cacheCreationInputTokens", "thinkingTokens"))
                rows.append({"model": model, **c})
                required = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
                if all(k in c for k in required):
                    if c.get("thinkingTokens", 0) > c["outputTokens"]:
                        raise ValueError("invalid_token_subset")
                    totals.append(sum(c[k] for k in required))
            result.update(scope="query_pipeline_excluding_some_helpers", counters=rows,
                          coverage="partial")
            if len(totals) == len(rows):
                result.update(coverage="reported", total_tokens=sum(totals))
        else:
            c = counters(final.get("usage"), ("input_tokens", "output_tokens",
                         "cache_read_input_tokens", "cache_creation_input_tokens"))
            result.update(scope="main_loop_only", coverage="partial" if c else "unknown",
                          counters=[c] if c else [])
        return result
    ends = [e for e in events if "conversation_id" in e and "status" in e]
    if ends:
        final = ends[-1]
        c = counters(final.get("usage"), ("input_tokens", "output_tokens", "total_tokens",
                     "total_input_tokens", "total_output_tokens", "cache_read_tokens", "thinking_tokens"))
        result.update(terminal=True, provider_success=final["status"] == "SUCCESS" and not final.get("error"),
                      scope="agy_raw_counters_semantics_unverified", coverage="partial" if c else "unknown",
                      counters=[c] if c else [])
    return result


def start(root, route, model):
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,150}", model):
        raise ValueError("invalid_requested_model")
    run_id = str(uuid.uuid4())
    write_once(root / (run_id + ".start.json"), {"schema_version": 1, "run_id": run_id,
               "route": route, "requested_model": model, "started_at": timestamp(),
               "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    return run_id


def finish(root, run_id, exit_code, raw):
    run_id = str(uuid.UUID(run_id))
    opening = json.loads((root / (run_id + ".start.json")).read_text())
    try:
        if len(raw.encode("utf-8")) > MAX_OUTPUT:
            raise ValueError("output_limit_exceeded")
        usage = parse_usage(opening["route"], raw)
    except (ValueError, RecursionError):
        usage = {"terminal": False, "provider_success": None, "coverage": "unknown",
                 "scope": "invalid_or_oversized_output", "total_tokens": None, "counters": []}
    if exit_code != 0 and usage["coverage"] == "reported":
        usage["coverage"] = "partial"
    record = {**opening, "finished_at": timestamp(), "exit_code": exit_code, **usage}
    write_once(root / (run_id + ".finish.json"), record)
    return record


def report(root, since=None):
    groups = {}
    errors = []
    for path in sorted(root.glob("*.start.json")):
        try:
            opening = json.loads(path.read_text())
            if since and opening["started_at"][:10] < since:
                continue
            key = (opening["route"], opening["requested_model"])
            row = groups.setdefault(key, {"route": key[0], "requested_model": key[1], "runs": 0,
                    "reported": 0, "partial": 0, "unknown": 0, "unfinished": 0,
                    "failed": 0, "known_tokens": 0, "total_tokens": None})
            row["runs"] += 1
            end = path.with_name(opening["run_id"] + ".finish.json")
            if not end.exists():
                row["unfinished"] += 1
                continue
            record = json.loads(end.read_text())
            row[record["coverage"]] += 1
            row["failed"] += int(record["exit_code"] != 0 or record["provider_success"] is False)
            if record["total_tokens"] is not None:
                row["known_tokens"] += record["total_tokens"]
        except (OSError, ValueError, KeyError, TypeError):
            errors.append(path.name)
    for row in groups.values():
        if row["reported"] == row["runs"]:
            row["total_tokens"] = row["known_tokens"]
    return {"generated_at": timestamp(), "groups": list(groups.values()), "unreadable_records": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=state_dir())
    sub = parser.add_subparsers(dest="command", required=True)
    begin = sub.add_parser("start")
    begin.add_argument("--route", choices=ROUTES, required=True)
    begin.add_argument("--model", required=True)
    end = sub.add_parser("finish")
    end.add_argument("--run-id", required=True)
    end.add_argument("--exit-code", required=True, type=int)
    summary = sub.add_parser("report")
    summary.add_argument("--since", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date().isoformat())
    args = parser.parse_args()
    try:
        if args.command == "start":
            print(start(args.state_dir, args.route, args.model))
        elif args.command == "finish":
            raw = sys.stdin.buffer.read(MAX_OUTPUT + 1).decode("utf-8", errors="replace")
            print(json.dumps(finish(args.state_dir, args.run_id, args.exit_code, raw)))
        else:
            result = report(args.state_dir, args.since)
            print(json.dumps(result, indent=2))
            return int(bool(result["unreadable_records"]))
    except (OSError, ValueError, KeyError) as error:
        print("second-opinion monitoring failed: " + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
