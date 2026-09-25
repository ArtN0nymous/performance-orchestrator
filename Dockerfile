ARG PYTHON_VERSION=3.12.8
ARG GOLANG_VERSION=1.25.1
ARG K6_VERSION=v2.2.0
ARG XK6_VERSION=v1.1.5
ARG XK6_INFLUXDB_VERSION=v0.7.0

FROM golang:${GOLANG_VERSION}-bookworm AS k6build
ARG K6_VERSION
ARG XK6_VERSION
ARG XK6_INFLUXDB_VERSION
ARG TARGETARCH
RUN go install go.k6.io/xk6/cmd/xk6@${XK6_VERSION}
WORKDIR /extract
# Official pinned k6 first (arch-aware). Overlay xk6+influxdb when the extension resolves.
RUN curl -fsSL "https://github.com/grafana/k6/releases/download/${K6_VERSION}/k6-${K6_VERSION}-linux-${TARGETARCH}.tar.gz" \
      | tar -xz \
    && mv "/extract/k6-${K6_VERSION}-linux-${TARGETARCH}/k6" /k6
RUN CGO_ENABLED=0 xk6 build \
      --k6-version "${K6_VERSION}" \
      --with "github.com/grafana/xk6-output-influxdb@${XK6_INFLUXDB_VERSION}" \
      --output /k6-xk6 \
    && mv /k6-xk6 /k6 \
    || echo "using official ${K6_VERSION} without xk6-output-influxdb ${XK6_INFLUXDB_VERSION}"

FROM python:${PYTHON_VERSION}-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ORCHESTRATOR_CONFIG=/project/orchestrator.yml
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-client curl jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=k6build /k6 /usr/local/bin/k6
RUN chmod +x /usr/local/bin/k6 && k6 version

WORKDIR /opt/orchestrator
COPY pyproject.toml README.md /opt/orchestrator/
COPY src /opt/orchestrator/src
RUN pip install --no-cache-dir /opt/orchestrator

COPY scripts/orchestrator-entrypoint.sh /usr/local/bin/orchestrator-entrypoint.sh
COPY scripts/wrappers/ /usr/local/bin/
RUN chmod +x /usr/local/bin/orchestrator-entrypoint.sh \
    && chmod +x /usr/local/bin/validate /usr/local/bin/doctor /usr/local/bin/list \
                /usr/local/bin/run /usr/local/bin/status /usr/local/bin/report \
                /usr/local/bin/recover /usr/local/bin/scheduler \
    && mkdir -p /data/results /ssh

VOLUME ["/data"]
EXPOSE 9464
HEALTHCHECK --interval=10s --timeout=5s --retries=8 CMD orchestrator ping
ENTRYPOINT ["/usr/local/bin/orchestrator-entrypoint.sh"]
CMD ["scheduler"]
