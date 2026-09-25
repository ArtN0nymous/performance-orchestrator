FROM python:3.12.8-bookworm

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      openssh-server curl jq procps iproute2 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd /home/perf/.ssh /var/log/target

RUN useradd -m -s /bin/bash perf \
    && echo "perf ALL=(ALL) NOPASSWD: /usr/bin/touch, /bin/rm, /usr/bin/tee" >/etc/sudoers.d/perf \
    && chmod 440 /etc/sudoers.d/perf || true

COPY docker/target/app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY docker/target/app/app.py /opt/target/app.py
COPY docker/target/ssh/sshd_config /etc/ssh/sshd_config
COPY docker/target/ssh/lab_ed25519.pub /home/perf/.ssh/authorized_keys
COPY docker/target/ssh/maintenance.sh /usr/local/bin/maintenance.sh

RUN chmod 600 /home/perf/.ssh/authorized_keys \
    && chown -R perf:perf /home/perf/.ssh \
    && chmod 755 /usr/local/bin/maintenance.sh \
    && chmod 4755 /usr/local/bin/maintenance.sh || true \
    && mkdir -p /var/run \
    && chmod 777 /var/run

WORKDIR /opt/target
EXPOSE 22 5000
COPY docker/target/app/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
HEALTHCHECK --interval=5s --timeout=3s --retries=12 CMD curl -fsS http://127.0.0.1:5000/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
