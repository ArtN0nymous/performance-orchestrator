import pytest
from pydantic import ValidationError

from orchestrator.config.models import SshConfig
from orchestrator.ssh.client import SshClient, SshError


def test_rejects_strict_no_in_schema():
    with pytest.raises(ValidationError):
        SshConfig(host="h", user="u", identity_file="/id", known_hosts_file="/kh", strict_host_key_checking="no")


def test_client_rejects_no_even_if_forced():
    cfg = SshConfig.model_construct(
        host="h", user="u", identity_file="/id", known_hosts_file="/kh", strict_host_key_checking="no", port=22, connect_timeout_seconds=1
    )
    with pytest.raises(SshError):
        SshClient(cfg)
