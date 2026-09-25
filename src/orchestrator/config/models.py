"""YAML configuration schema. Project-specific values live outside the core."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ProjectConfig(BaseModel):
    name: str
    timezone: str = "UTC"


class EnvironmentConfig(BaseModel):
    name: str = "local"
    timezone: str | None = None


class TrafficConfig(BaseModel):
    public_base_url: str
    test_base_url: str
    bypass_header_name: str | None = "X-Perf-Test-Traffic"
    bypass_header_value: str | None = None
    public_expect_status_when_maintenance: int = 503
    test_expect_status_when_maintenance: int = 200
    health_path: str = "/health"
    # Optional headers for health / maintenance HTTP probes (e.g. X-API-Key).
    health_headers: dict[str, str] = Field(default_factory=dict)


class SshConfig(BaseModel):
    host: str
    port: int = 22
    user: str
    identity_file: str
    known_hosts_file: str
    strict_host_key_checking: Literal["yes", "accept-new"] = "yes"
    connect_timeout_seconds: int = 10

    @field_validator("strict_host_key_checking", mode="before")
    @classmethod
    def _coerce_strict(cls, value):
        if value is True:
            return "yes"
        if value is False:
            raise ValueError("StrictHostKeyChecking cannot be disabled")
        return value


class CommandSet(BaseModel):
    check_connection: str = "uname -a"
    capture_state: str = "echo {}"
    enable_maintenance: str
    verify_maintenance: str | None = None
    disable_maintenance: str
    verify_live: str | None = None
    collect_diagnostics: str = "echo {}"
    php_fpm_status: str | None = None
    queue_status: str | None = None
    web_server_status: str | None = None
    database_status: str | None = None
    install_watchdog: str | None = None
    logs: str | None = None
    # Optional DB snapshot around the load window (mysqldump / restore via SSH).
    backup_database: str | None = None
    restore_database: str | None = None
    # Optional: print a single JSON object of table → row counts (before/after deltas).
    database_row_counts: str | None = None


class TargetConfig(BaseModel):
    type: Literal["ssh_generic", "laravel", "none"] = "ssh_generic"
    ssh: SshConfig | None = None
    remote_workdir: str | None = None
    php_binary: str = "php"
    artisan_path: str | None = None
    down_command: str | None = None
    up_command: str | None = None
    commands: CommandSet | None = None
    traffic: TrafficConfig


class MaintenanceConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = 7200
    watchdog_enabled: bool = True
    secret: str | None = None


class DatabaseSnapshotConfig(BaseModel):
    """Orchestrator-controlled DB backup/restore + row-count deltas for the report."""

    enabled: bool = False
    # When true, mysql/mysqldump on the target get client SSL disabled (typical Docker / private net).
    disable_ssl: bool = True
    # Optional free-form client flags (overrides disable_ssl when non-empty), e.g. --ssl-mode=REQUIRED.
    mysql_opts: str | None = None

    def resolved_mysql_opts(self) -> str:
        """Flags injected into remote mysql/mysqldump via {mysql_ssl_opts}."""
        if self.mysql_opts is not None and str(self.mysql_opts).strip() != "":
            return str(self.mysql_opts).strip()
        if self.disable_ssl:
            # MariaDB client: --ssl=0. Oracle MySQL 8: set mysql_opts=--ssl-mode=DISABLED.
            return "--ssl=0"
        return ""


class HealthConfig(BaseModel):
    public_url: str | None = None
    test_url: str | None = None
    timeout_seconds: float = 5.0
    retries: int = 5
    retry_delay_seconds: float = 1.0


class MonitoringConfig(BaseModel):
    enabled: bool = False
    prometheus_url: str | None = None
    grafana_url: str | None = None
    scrape_interval_seconds: int = 5
    cpu_query: str | None = None
    memory_query: str | None = None
    disk_query: str | None = None
    network_query: str | None = None
    load_query: str | None = None


class InfluxConfig(BaseModel):
    enabled: bool = False
    url: str | None = None
    org: str | None = None
    bucket: str | None = None
    token: str | None = None


class StorageConfig(BaseModel):
    sqlite_path: str = "/data/orchestrator.db"
    results_dir: str = "/data/results"
    influx: InfluxConfig = Field(default_factory=InfluxConfig)


class SafetyConfig(BaseModel):
    max_vus: int = 200
    max_test_duration: str = "1h"
    max_error_rate: float = 0.5
    max_cpu: float | None = None
    max_memory: float | None = None
    abort_if_target_unreachable: bool = True
    abort_if_prometheus_unavailable: bool = False
    poll_interval_seconds: float = 2.0


class ScheduleJob(BaseModel):
    id: str
    cron: str
    suite: str
    misfire: Literal["skip", "run"] = "skip"
    enabled: bool = True


class ScheduleConfig(BaseModel):
    timezone: str = "UTC"
    jobs: list[ScheduleJob] = Field(default_factory=list)
    tick_seconds: float = 5.0
    misfire_grace_seconds: int = 300


class ThresholdsConfig(BaseModel):
    http_req_failed: str | None = None
    http_req_duration_p95: str | None = None
    extra: dict[str, str] = Field(default_factory=dict)

    def as_k6_map(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        if self.http_req_failed:
            out["http_req_failed"] = [self.http_req_failed]
        if self.http_req_duration_p95:
            out["http_req_duration"] = [self.http_req_duration_p95]
        for key, expr in self.extra.items():
            out.setdefault(key, []).append(expr)
        return out


class ScenarioParams(BaseModel):
    executor: str = "constant-vus"
    vus: int | None = None
    duration: str | None = None
    iterations: int | None = None
    start_rate: str | None = None
    rate: str | None = None
    time_unit: str | None = None
    pre_allocated_vus: int | None = None
    max_vus: int | None = None
    stages: list[dict[str, Any]] | None = None
    graceful_stop: str | None = "5s"


class K6Test(BaseModel):
    id: str
    script: str
    scenario: str | None = None
    required: list[str] = Field(default_factory=list)
    continue_on_failure: bool = False
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    duration: str | None = None
    params: ScenarioParams = Field(default_factory=ScenarioParams)
    env: dict[str, str] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)


class SuiteDef(BaseModel):
    id: str
    tests: list[str]
    continue_on_failure: bool = True
    depends_on: list[str] = Field(default_factory=list)
    order: list[str] | None = None


class OrchestratorConfig(BaseModel):
    project: ProjectConfig
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    target: TargetConfig
    maintenance: MaintenanceConfig = Field(default_factory=MaintenanceConfig)
    database_snapshot: DatabaseSnapshotConfig = Field(default_factory=DatabaseSnapshotConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    suites: dict[str, SuiteDef] = Field(default_factory=dict)
    tests: dict[str, K6Test] = Field(default_factory=dict)
    max_concurrent_runs: int = 1
    k6_bin: str = "k6"
    k6_root: str = "."
    redaction_keys: list[str] = Field(
        default_factory=lambda: [
            "password",
            "token",
            "secret",
            "authorization",
            "api_key",
            "apikey",
            "stripe",
            "identity_file",
        ]
    )
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_maintenance_traffic_split(self) -> "OrchestratorConfig":
        if not self.maintenance.enabled:
            return self
        traffic = self.target.traffic
        if traffic.test_expect_status_when_maintenance in (503, 502):
            raise ValueError(
                "test_expect_status_when_maintenance cannot be a maintenance/error status; "
                "test traffic must remain live during maintenance"
            )
        # Stub / live window: API stays up for everyone (expect 2xx on public) — no split required.
        public_stays_live = 200 <= traffic.public_expect_status_when_maintenance < 300
        if public_stays_live:
            return self
        # Hard maintenance (public 503): require distinct test URL or a real bypass so k6 is not 503-only.
        same = traffic.public_base_url.rstrip("/") == traffic.test_base_url.rstrip("/")
        has_bypass = bool(traffic.bypass_header_name and traffic.bypass_header_value)
        if same and not has_bypass:
            raise ValueError(
                "maintenance with public 503 requires distinct public_base_url vs test_base_url "
                "or a configured traffic bypass header so k6 does not only receive 503"
            )
        return self

    def timezone(self) -> str:
        return self.environment.timezone or self.project.timezone or self.schedule.timezone
