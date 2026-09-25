import { scenarioFromEnv, parseThresholds } from '../lib/options.js';
import { healthFlow, loginFlow, readItemsFlow, writeItemFlow } from '../flows/core.js';

export const options = {
  scenarios: scenarioFromEnv('load', 'load'),
  thresholds: parseThresholds(),
};

export function load() {
  healthFlow();
  const token = loginFlow();
  if (token) {
    readItemsFlow(token);
    writeItemFlow(token);
  }
}
