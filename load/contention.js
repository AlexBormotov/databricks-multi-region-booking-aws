// The contention scenario: ATTEMPTS bookings of one room-night, each with its own guest and
// Idempotency-Key, spread over the API URLs. Exactly one may get 201; the rest must get 409.
//
//   k6 run -e API_URLS=https://a,https://b -e HOTEL_ID=.. -e ROOM_ID=.. -e ATTEMPTS=1000 \
//     -e VUS=200 -e SUMMARY=summary.json load/contention.js
//
// In the cloud each of three instances runs a share of the attempts; ops/demo.py adds them up.
// START_AT (epoch ms) holds every VU's first request until one shared instant, so the attempts
// really race; without it the first booking commits before most of the others arrive.
// A 429 or 503 (API Gateway or Lambda throttled, or the store too busy) and a 409 with
// Retry-After (the key still in flight) are retried with the same Idempotency-Key, so every attempt reaches the store; an
// attempt still unanswered after RETRIES tries counts as busy.

import http from "k6/http";
import { sleep } from "k6";
import exec from "k6/execution";
import { Counter } from "k6/metrics";

const urls = __ENV.API_URLS.split(",");
const attempts = Number(__ENV.ATTEMPTS || 1000);
const retries = Number(__ENV.RETRIES || 30);
// One counter per outcome: tagged sub-metrics reach the summary only when a threshold names them.
const outcomes = { 201: new Counter("created"), 409: new Counter("conflict"), 503: new Counter("busy") };
const other = new Counter("other");
// Tagged sub-metrics reach the summary only through a threshold, so each status that may land in
// `other` gets one; 0 is a request that got no response.
const OTHER_STATUSES = [0, 400, 403, 404, 422, 429, 500, 502, 504];
const retried = new Counter("retried");

export const options = {
  scenarios: {
    contention: {
      executor: "shared-iterations",
      vus: Math.min(Number(__ENV.VUS || 200), attempts),
      iterations: attempts,
      maxDuration: "5m",
    },
  },
  thresholds: Object.fromEntries(OTHER_STATUSES.map((s) => [`other{status:${s}}`, ["count>=0"]])),
};

function uuid4() {
  const hex = [...Array(32)].map(() => Math.floor(Math.random() * 16).toString(16));
  hex[12] = "4";
  hex[16] = "89ab"[Math.floor(Math.random() * 4)];
  const s = hex.join("");
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

export default function () {
  if (__ENV.START_AT && __ITER === 0) sleep(Math.max(0, Number(__ENV.START_AT) - Date.now()) / 1000);
  // The test-wide iteration number: __ITER counts per VU, and with one iteration per VU it is
  // always 0, which sent every attempt to the first URL.
  const url = urls[exec.scenario.iterationInTest % urls.length];
  const body = JSON.stringify({
    hotel_id: __ENV.HOTEL_ID,
    room_id: __ENV.ROOM_ID,
    guest_id: uuid4(),
    check_in: __ENV.CHECK_IN || "2027-03-01",
    check_out: __ENV.CHECK_OUT || "2027-03-02",
  });
  const params = { headers: { "content-type": "application/json", "idempotency-key": uuid4() } };
  let response;
  for (let attempt = 0; attempt < retries; attempt++) {
    if (attempt > 0) {
      retried.add(1);
      sleep(Math.random() * Math.min(2, 0.1 * 2 ** attempt)); // full jitter, capped at 2 s
    }
    response = http.post(`${url}/bookings`, body, params);
    const again =
      response.status === 429 ||
      response.status === 503 ||
      (response.status === 409 && response.headers["Retry-After"]);
    if (!again) break;
  }
  if (outcomes[response.status]) outcomes[response.status].add(1);
  else other.add(1, { status: String(response.status) });
  if (!outcomes[response.status]) console.error(`unexpected ${response.status}: ${response.body}`);
}

// Counts by outcome, which is all the demo checks.
export function handleSummary(data) {
  const counts = {};
  for (const name of ["created", "conflict", "busy", "other", "retried"]) {
    counts[name] = data.metrics[name] ? data.metrics[name].values.count : 0;
  }
  counts.other_by_status = {};
  for (const s of OTHER_STATUSES) {
    const metric = data.metrics[`other{status:${s}}`];
    if (metric && metric.values.count) counts.other_by_status[s] = metric.values.count;
  }
  return { [__ENV.SUMMARY || "summary.json"]: JSON.stringify(counts, null, 2) };
}
