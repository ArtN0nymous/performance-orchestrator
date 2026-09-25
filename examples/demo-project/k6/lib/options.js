export function applyTags() {
  return {
    testid: __ENV.TESTID || __ENV.K6_RUN_ID || 'local',
    run_id: __ENV.K6_RUN_ID || 'local',
  };
}

export function parseThresholds() {
  try {
    return JSON.parse(__ENV.THRESHOLDS_JSON || '{}');
  } catch (e) {
    return {};
  }
}

export function parseStages() {
  try {
    return JSON.parse(__ENV.STAGES_JSON || '[]');
  } catch (e) {
    return [];
  }
}

export function scenarioFromEnv(name, execFn) {
  const executor = __ENV.EXECUTOR || 'constant-vus';
  const scenario = { executor, exec: execFn, tags: applyTags() };
  if (executor === 'externally-controlled') {
    throw new Error('externally-controlled is not supported');
  }
  if (executor === 'constant-vus') {
    scenario.vus = Number(__ENV.VUS || 1);
    scenario.duration = __ENV.DURATION || '10s';
  } else if (executor === 'ramping-vus') {
    scenario.startVUs = Number(__ENV.START_VUS || 1);
    scenario.stages = parseStages().length
      ? parseStages()
      : [
          { duration: '5s', target: Number(__ENV.VUS || 2) },
          { duration: '5s', target: 0 },
        ];
  } else if (executor === 'constant-arrival-rate') {
    scenario.rate = Number(__ENV.RATE || 1);
    scenario.timeUnit = __ENV.TIME_UNIT || '1s';
    scenario.duration = __ENV.DURATION || '10s';
    scenario.preAllocatedVUs = Number(__ENV.PRE_ALLOCATED_VUS || __ENV.VUS || 2);
    scenario.maxVUs = Number(__ENV.MAX_VUS || scenario.preAllocatedVUs);
  } else if (executor === 'per-vu-iterations') {
    scenario.vus = Number(__ENV.VUS || 1);
    scenario.iterations = Number(__ENV.ITERATIONS || 1);
  } else if (executor === 'shared-iterations') {
    scenario.vus = Number(__ENV.VUS || 1);
    scenario.iterations = Number(__ENV.ITERATIONS || 1);
  }
  return { [name]: scenario };
}
