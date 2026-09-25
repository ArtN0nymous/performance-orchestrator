import { scenarioFromEnv, parseThresholds } from '../lib/options.js';
import { healthFlow, slowFlow } from '../flows/core.js';

export const options = {
  scenarios: scenarioFromEnv('stress', 'stress'),
  thresholds: parseThresholds(),
};

export function stress() {
  healthFlow();
  slowFlow();
}
