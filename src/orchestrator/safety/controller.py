from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.config.models import OrchestratorConfig, K6Test
from orchestrator.safety.duration import parse_duration


class SafetyViolation(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class SafetyDecision:
    abort: bool = False
    reasons: list[str] = field(default_factory=list)


class SafetyController:
    def __init__(self, cfg: OrchestratorConfig):
        self.cfg = cfg

    def validate_test(self, test: K6Test) -> None:
        vus = test.params.vus or test.params.max_vus or 0
        if vus > self.cfg.safety.max_vus:
            raise SafetyViolation(f"test {test.id} vus={vus} exceeds safety.max_vus={self.cfg.safety.max_vus}")
        duration = test.duration or test.params.duration
        if duration:
            if parse_duration(duration) > parse_duration(self.cfg.safety.max_test_duration):
                raise SafetyViolation(
                    f"test {test.id} duration={duration} exceeds safety.max_test_duration={self.cfg.safety.max_test_duration}"
                )
        if test.params.executor == "externally-controlled":
            raise SafetyViolation("externally-controlled executor is forbidden")

    def evaluate_metrics(
        self,
        *,
        error_rate: float | None = None,
        cpu: float | None = None,
        memory: float | None = None,
        target_reachable: bool = True,
        prometheus_ok: bool | None = None,
        elapsed_seconds: float | None = None,
        max_duration_seconds: float | None = None,
    ) -> SafetyDecision:
        decision = SafetyDecision()
        safety = self.cfg.safety
        if safety.abort_if_target_unreachable and not target_reachable:
            decision.abort = True
            decision.reasons.append("target unreachable")
        if error_rate is not None and error_rate > safety.max_error_rate:
            decision.abort = True
            decision.reasons.append(f"error_rate {error_rate} > {safety.max_error_rate}")
        if safety.max_cpu is not None and cpu is not None and cpu > safety.max_cpu:
            decision.abort = True
            decision.reasons.append(f"cpu {cpu} > {safety.max_cpu}")
        if safety.max_memory is not None and memory is not None and memory > safety.max_memory:
            decision.abort = True
            decision.reasons.append(f"memory {memory} > {safety.max_memory}")
        if safety.abort_if_prometheus_unavailable and prometheus_ok is False:
            decision.abort = True
            decision.reasons.append("prometheus unavailable")
        if elapsed_seconds is not None and max_duration_seconds is not None:
            if elapsed_seconds > max_duration_seconds:
                decision.abort = True
                decision.reasons.append("max duration exceeded")
        return decision
