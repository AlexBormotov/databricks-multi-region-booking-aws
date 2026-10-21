// Contention proof: every VU tries once, at the same moment, to book the same room-night.
// One runner per region (EC2 spot); together they send 1000 attempts and exactly one may win.
// The invariant check (booking.store.violations) is run afterwards.
//
//   k6 run -e API_URL=https://... -e HOTEL_ID=... -e ROOM_ID=... -e CHECK_IN=2027-01-10 \
//          -e ATTEMPTS=334 -e RUNNER=us-west-2 loadtest/contention.js

import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const ATTEMPTS = Number(__ENV.ATTEMPTS || 334);
const RUNNER = __ENV.RUNNER || 'local';

const won = new Counter('booking_won');
const lost = new Counter('booking_lost');
const failed = new Counter('booking_failed');

export const options = {
  scenarios: {
    contention: {
      executor: 'per-vu-iterations',
      vus: ATTEMPTS,
      iterations: 1,
      maxDuration: '2m',
    },
  },
  thresholds: {
    // A 503 (retries exhausted) or any other answer is a failure of the run, not a lost race.
    booking_failed: ['count==0'],
  },
};

function nextDay(isoDate) {
  const day = new Date(`${isoDate}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() + 1);
  return day.toISOString().slice(0, 10);
}

export default function () {
  const body = JSON.stringify({
    hotel_id: __ENV.HOTEL_ID,
    room_id: __ENV.ROOM_ID,
    guest_id: crypto.randomUUID(),
    check_in: __ENV.CHECK_IN,
    check_out: nextDay(__ENV.CHECK_IN),
  });
  const response = http.post(`${__ENV.API_URL}/bookings`, body, {
    headers: {
      'content-type': 'application/json',
      'idempotency-key': `${RUNNER}-${__VU}-${crypto.randomUUID()}`,
    },
    tags: { runner: RUNNER },
  });

  if (response.status === 201) won.add(1);
  else if (response.status === 409) lost.add(1);
  else failed.add(1);
  check(response, { 'won or lost the race': (r) => r.status === 201 || r.status === 409 });
}

export function handleSummary(data) {
  const count = (name) => (data.metrics[name] ? data.metrics[name].values.count : 0);
  const result = {
    runner: RUNNER,
    attempts: ATTEMPTS,
    won: count('booking_won'),
    lost: count('booking_lost'),
    failed: count('booking_failed'),
    p95_ms: data.metrics.http_req_duration.values['p(95)'],
  };
  return {
    stdout: `${JSON.stringify(result)}\n`,
    [`artifacts/k6-${RUNNER}.json`]: JSON.stringify(result, null, 2),
  };
}
