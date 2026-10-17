// The contention scenario: ATTEMPTS bookings of one room-night, each with its own guest and
// Idempotency-Key, spread over the API URLs. Exactly one may get 201; the rest get 409 or 503.
//
//   k6 run -e API_URLS=https://a,https://b -e HOTEL_ID=.. -e ROOM_ID=.. -e ATTEMPTS=1000 \
//     -e VUS=200 -e SUMMARY=summary.json load/contention.js
//
// In the cloud each of three instances runs a share of the attempts; ops/demo.py adds them up.
// START_AT (epoch ms) holds every VU's first request until one shared instant, so the attempts
// really race; without it the first booking commits before most of the others arrive.

import http from "k6/http";
import { sleep } from "k6";
import { Counter } from "k6/metrics";

const urls = __ENV.API_URLS.split(",");
const attempts = Number(__ENV.ATTEMPTS || 1000);
// One counter per outcome: tagged sub-metrics reach the summary only when a threshold names them.
const outcomes = { 201: new Counter("created"), 409: new Counter("conflict"), 503: new Counter("busy") };
const other = new Counter("other");

export const options = {
  scenarios: {
    contention: {
      executor: "shared-iterations",
      vus: Math.min(Number(__ENV.VUS || 200), attempts),
      iterations: attempts,
      maxDuration: "5m",
    },
  },
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
  const url = urls[__ITER % urls.length];
  const response = http.post(
    `${url}/bookings`,
    JSON.stringify({
      hotel_id: __ENV.HOTEL_ID,
      room_id: __ENV.ROOM_ID,
      guest_id: uuid4(),
      check_in: __ENV.CHECK_IN || "2027-03-01",
      check_out: __ENV.CHECK_OUT || "2027-03-02",
    }),
    { headers: { "content-type": "application/json", "idempotency-key": uuid4() } },
  );
  (outcomes[response.status] || other).add(1);
  if (!outcomes[response.status]) console.error(`unexpected ${response.status}: ${response.body}`);
}

// Counts by outcome, which is all the demo checks.
export function handleSummary(data) {
  const counts = {};
  for (const name of ["created", "conflict", "busy", "other"]) {
    counts[name] = data.metrics[name] ? data.metrics[name].values.count : 0;
  }
  return { [__ENV.SUMMARY || "summary.json"]: JSON.stringify(counts, null, 2) };
}
