# Copy this directory to a project overlay. Keep secrets out of git.

project:
  name: my-project
  timezone: UTC

environment:
  name: lab

target:
  type: ssh_generic
  ssh:
    host: ${TARGET_SSH_HOST}
    port: 22
    user: ${TARGET_SSH_USER}
    identity_file: ${TARGET_SSH_IDENTITY}
    known_hosts_file: ${TARGET_KNOWN_HOSTS}
    strict_host_key_checking: "yes"
  commands:
    check_connection: "uname -a"
    capture_state: "echo {}"
    enable_maintenance: "true"
    disable_maintenance: "true"
    collect_diagnostics: "uptime"
  traffic:
    public_base_url: http://localhost
    test_base_url: http://localhost:8088
    health_path: /health

maintenance:
  enabled: false

suites:
  smoke:
    tests: [smoke]

tests:
  smoke:
    script: k6/smoke.js
    params:
      executor: constant-vus
      vus: 1
      duration: 10s
