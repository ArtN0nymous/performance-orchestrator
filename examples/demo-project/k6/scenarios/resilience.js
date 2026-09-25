import { scenarioFromEnv, parseThresholds } from '../lib/options.js';
import { loginFlow, errorFlow } from '../flows/core.js';
import { paymentFlow, webhookFlow, retryThenIdempotent } from '../payments/sandbox.js';

export const options = {
  scenarios: scenarioFromEnv('resilience', 'resilience'),
  thresholds: parseThresholds(),
};

export function resilience() {
  const token = loginFlow();
  if (!token) return;
  const scenario = __ENV.PAYMENT_SCENARIO || 'success';
  paymentFlow(token, scenario);
  if (scenario === 'error') {
    errorFlow();
    paymentFlow(token, '500');
  }
  webhookFlow(`evt-${__VU}-${__ITER}`, false);
  webhookFlow(`evt-${__VU}-${__ITER}`, false);
  webhookFlow(`evt-delay-${__VU}-${__ITER}`, true);
  retryThenIdempotent(token);
}
