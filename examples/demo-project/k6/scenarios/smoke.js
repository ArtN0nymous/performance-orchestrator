import { scenarioFromEnv, parseThresholds } from '../lib/options.js';
import { healthFlow } from '../flows/core.js';

export const options = {
  scenarios: scenarioFromEnv('smoke', 'smoke'),
  thresholds: parseThresholds(),
  tags: { suite: 'smoke' },
};

export function smoke() {
  healthFlow();
}
