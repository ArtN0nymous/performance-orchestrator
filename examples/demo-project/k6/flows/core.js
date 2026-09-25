import http from 'k6/http';
import { check, sleep } from 'k6';
import { baseUrl, headers } from '../lib/http.js';

export function healthFlow() {
  const res = http.get(`${baseUrl()}/health`, { headers: headers() });
  check(res, { 'health 200': (r) => r.status === 200 });
  return res;
}

export function loginFlow() {
  const res = http.post(
    `${baseUrl()}/auth/login`,
    JSON.stringify({ username: 'tester', password: 'tester' }),
    { headers: headers() },
  );
  check(res, { 'login 200': (r) => r.status === 200 });
  const body = res.json();
  return body.token;
}

export function readItemsFlow(token) {
  const h = headers();
  h.Authorization = `Bearer ${token}`;
  const res = http.get(`${baseUrl()}/items`, { headers: h });
  check(res, { 'items 200': (r) => r.status === 200 });
  return res;
}

export function writeItemFlow(token) {
  const h = headers();
  h.Authorization = `Bearer ${token}`;
  const res = http.post(`${baseUrl()}/items`, JSON.stringify({ name: `item-${Date.now()}` }), {
    headers: h,
  });
  check(res, { 'item created': (r) => r.status === 201 });
  return res;
}

export function slowFlow() {
  const res = http.get(`${baseUrl()}/slow?delay_ms=200`, { headers: headers() });
  check(res, { 'slow 200': (r) => r.status === 200 });
  sleep(0.1);
  return res;
}

export function errorFlow() {
  const res = http.get(`${baseUrl()}/error`, { headers: headers() });
  check(res, { 'error 500': (r) => r.status === 500 });
  return res;
}
