import http from 'k6/http';
import { check } from 'k6';
import { baseUrl, headers } from '../lib/http.js';

export function paymentFlow(token, scenario) {
  const h = headers();
  h.Authorization = `Bearer ${token}`;
  h['X-Payment-Scenario'] = scenario;
  h['Idempotency-Key'] = `lab-${__VU}-${__ITER}-${scenario}`;
  const res = http.post(
    `${baseUrl()}/payments`,
    JSON.stringify({ amount_cents: 500, scenario }),
    { headers: h },
  );
  const expected = {
    success: 200,
    decline: 402,
    timeout: 504,
    slow: 200,
    '500': 500,
    network: 502,
  };
  check(res, {
    [`payment ${scenario}`]: (r) => r.status === (expected[scenario] || 200),
  });
  return res;
}

export function webhookFlow(eventId, delayed) {
  const q = delayed ? '?delay=1' : '';
  const res = http.post(
    `${baseUrl()}/webhooks/payment${q}`,
    JSON.stringify({ id: eventId, type: 'payment_intent.succeeded', sandbox: true }),
    { headers: headers() },
  );
  check(res, { 'webhook accepted': (r) => r.status === 200 });
  return res;
}

export function retryThenIdempotent(token) {
  paymentFlow(token, '500');
  const first = paymentFlow(token, 'success');
  const second = paymentFlow(token, 'success');
  check(second, {
    'idempotent replay or success': (r) => r.status === 200,
  });
  return { first, second };
}
