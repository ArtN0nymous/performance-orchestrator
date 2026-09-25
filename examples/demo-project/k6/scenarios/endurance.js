import { scenarioFromEnv, parseThresholds } from '../lib/options.js';
import { healthFlow, loginFlow, readItemsFlow } from '../flows/core.js';

export const options = {
  scenarios: scenarioFromEnv('spike', 'spike'),
  thresholds: parseThresholds(),
};

export function spike() {
  healthFlow();
  const token = loginFlow();
  if (token) readItemsFlow(token);
}
