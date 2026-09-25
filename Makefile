PYTHON ?= python3
COMPOSE ?= docker compose
PROFILES ?= --profile local-target --profile observability
EXT_COMPOSE ?= -f docker-compose.yml -f docker-compose.external-target.yml -f docker-compose.host-data.yml

.PHONY: install test test-unit test-fail lab-up lab-down doctor smoke \
	ext-net ext-up ext-down ext-doctor ext-smoke ext-commerce ext-full ext-weekend

install:
	$(PYTHON) -m pip install -e ".[dev]"

test: test-unit test-fail

test-unit:
	$(PYTHON) -m pytest tests/unit tests/failures -q

test-fail:
	$(PYTHON) -m pytest tests/failures -q

test-integration:
	$(PYTHON) -m pytest tests/integration tests/e2e -q -m "integration or e2e"

lab-up:
	$(COMPOSE) $(PROFILES) up -d --build

lab-down:
	$(COMPOSE) $(PROFILES) down -v

doctor:
	$(COMPOSE) exec orchestrator doctor

smoke:
	$(COMPOSE) exec orchestrator run --suite smoke

# --- External API target (shared Docker network; hosts from .env) ---

ext-net:
	docker network create $${EXTERNAL_TARGET_NETWORK:-perf-loadtest} 2>/dev/null || true

ext-up: ext-net
	$(COMPOSE) $(EXT_COMPOSE) --profile observability up -d --build orchestrator prometheus cadvisor docker-stats-exporter grafana influxdb

ext-down:
	$(COMPOSE) $(EXT_COMPOSE) stop orchestrator

ext-doctor:
	$(COMPOSE) $(EXT_COMPOSE) exec orchestrator doctor

ext-smoke:
	$(COMPOSE) $(EXT_COMPOSE) exec orchestrator run --suite smoke

ext-commerce:
	$(COMPOSE) $(EXT_COMPOSE) exec orchestrator run --suite commerce

ext-full:
	$(COMPOSE) $(EXT_COMPOSE) exec orchestrator run --suite full

ext-weekend:
	$(COMPOSE) $(EXT_COMPOSE) exec orchestrator run --suite weekend
