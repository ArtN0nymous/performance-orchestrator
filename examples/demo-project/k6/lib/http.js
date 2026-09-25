export function headers() {
  const h = { 'Content-Type': 'application/json' };
  if (__ENV.BYPASS_HEADER_NAME && __ENV.BYPASS_HEADER_VALUE) {
    h[__ENV.BYPASS_HEADER_NAME] = __ENV.BYPASS_HEADER_VALUE;
  }
  if (__ENV.API_KEY) {
    h['X-API-Key'] = __ENV.API_KEY;
  }
  if (__ENV.ADMIN_API_KEY) {
    h['X-API-Key'] = __ENV.ADMIN_API_KEY;
  }
  if (__ENV.ACCESS_TOKEN) {
    const name = __ENV.ACCESS_TOKEN_HEADER || 'X-Access-Token';
    h[name] = __ENV.ACCESS_TOKEN;
  }
  if (__ENV.AUTH_TOKEN) {
    h.Authorization = `Bearer ${__ENV.AUTH_TOKEN}`;
  }
  return h;
}

export function baseUrl() {
  return (__ENV.BASE_URL || 'http://target-nginx:8088').replace(/\/$/, '');
}

export function publicUrl() {
  return (__ENV.PUBLIC_BASE_URL || 'http://target-nginx:80').replace(/\/$/, '');
}
