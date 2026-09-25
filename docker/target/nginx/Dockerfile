FROM nginx:1.27.3
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY docker/target/nginx/nginx.conf /etc/nginx/nginx.conf
HEALTHCHECK --interval=5s --timeout=3s --retries=12 CMD curl -fsS http://127.0.0.1/health || exit 1
