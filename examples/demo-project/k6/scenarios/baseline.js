import { scenarioFromEnv, parseThresholds } from '../lib/options.js';
import { healthFlow, loginFlow, readItemsFlow } from '../flows/core.js';

export const options = {
  scenarios: scenarioFromEnv('baseline', 'baseline'),
  thresholds: parseThresholds(),
};

export function baseline() {
  healthFlow();
  const token = loginFlow();
  if (token) readItemsFlow(token);
}
