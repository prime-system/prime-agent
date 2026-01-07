"""
Tests for credential safety and redaction utilities.

Ensures credentials are never logged, redacted properly, and sensitive
information is not exposed in error messages or debug output.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.utils.redaction import redact_dict, redact_sensitive_data


class TestRedactionUtility:
    """Tests for the redaction utility functions."""

    def test_redact_dict_hides_api_key(self) -> None:
        """Verify API keys are redacted from dictionaries."""
        data = {
            "api_key": "sk-ant-v12345678901234567890",
            "username": "user@example.com",
        }

        redacted = redact_dict(data)

        assert redacted["api_key"] == "[REDACTED]"
        assert redacted["username"] == "user@example.com"

    def test_redact_dict_hides_auth_token(self) -> None:
        """Verify auth tokens are redacted from dictionaries."""
        data = {
            "auth_token": "Bearer token123456789abcdef",
            "user_id": "123",
        }

        redacted = redact_dict(data)

        assert redacted["auth_token"] == "[REDACTED]"
        assert redacted["user_id"] == "123"

    def test_redact_dict_hides_apple_credentials(self) -> None:
        """Verify Apple credentials are redacted from dictionaries."""
        data = {
            "apple_team_id": "ABC123DEF456",
            "apple_key_id": "KEY123456789",
            "apple_p8_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
            "bundle_id": "com.example.app",
        }

        redacted = redact_dict(data)

        assert redacted["apple_team_id"] == "[REDACTED]"
        assert redacted["apple_key_id"] == "[REDACTED]"
        assert redacted["apple_p8_key"] == "[REDACTED]"
        assert redacted["bundle_id"] == "com.example.app"

    def test_redact_dict_hides_git_credentials(self) -> None:
        """Verify Git credentials are redacted from dictionaries."""
        data = {
            "git_ssh_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n...\n-----END OPENSSH PRIVATE KEY-----",
            "git_token": "ghp_1234567890abcdefghijklmnop",
            "git_username": "user",
        }

        redacted = redact_dict(data)

        assert redacted["git_ssh_key"] == "[REDACTED]"
        assert redacted["git_token"] == "[REDACTED]"
        assert redacted["git_username"] == "user"

    def test_redact_dict_recursively_redacts_nested_dicts(self) -> None:
        """Verify nested dictionaries are recursively redacted."""
        data = {
            "config": {
                "auth_token": "secret123456789",
                "database": {"password": "db_secret123"},
            },
            "public": "info",
        }

        redacted = redact_dict(data)

        assert redacted["config"]["auth_token"] == "[REDACTED]"
        assert redacted["config"]["database"]["password"] == "[REDACTED]"
        assert redacted["public"] == "info"

    def test_redact_sensitive_data_pattern_matching(self) -> None:
        """Verify pattern-based redaction works correctly."""
        text = (
            "API Key: api_key=sk-ant-abc123def456ghi7890 "
            "Token: token=Bearer123456789abcdef "
            "Endpoint: https://api.example.com"
        )

        redacted = redact_sensitive_data(text)

        assert "sk-ant-abc123def456ghi7890" not in redacted
        assert "Bearer123456789abcdef" not in redacted
        assert "https://api.example.com" in redacted
        assert "[REDACTED_" in redacted

    def test_redact_sensitive_data_handles_pem_keys(self) -> None:
        """Verify PEM-formatted private keys are redacted."""
        text = (
            "Private key: -----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA...\n"
            "-----END RSA PRIVATE KEY-----\n"
            "Public key: -----BEGIN PUBLIC KEY-----"
        )

        redacted = redact_sensitive_data(text)

        assert "-----BEGIN RSA PRIVATE KEY-----" not in redacted
        assert "-----END RSA PRIVATE KEY-----" not in redacted
        assert "-----BEGIN PUBLIC KEY-----" in redacted


class TestConfigCredentialSafety:
    """Tests for credential safety in configuration."""

    def test_config_no_print_statements_with_credentials(self, caplog: pytest.LogCaptureFixture) -> None:
        """Verify that config loading doesn't use print() for credentials."""
        # This test relies on the actual code not having print() statements
        # We verify this by checking the grep results during implementation
        import app.config

        # Verify logger is used instead of print
        source = open(app.config.__file__).read()
        lines_with_apn_debug = [
            line
            for line in source.split("\n")
            if "apple_team_id" in line or "apple_key_id" in line or "apple_p8_key" in line
        ]

        # Should not find any print() statements with credentials
        for line in lines_with_apn_debug:
            assert "print(" not in line, f"Found print() with credentials: {line}"

    def test_apn_logging_safe_in_main(self) -> None:
        """Verify APNs initialization logging doesn't expose credentials."""
        import app.main

        source = open(app.main.__file__).read()

        # Should not find logger calls that include team_id or key_id
        dangerous_patterns = [
            "team_id:",
            "key_id:",
            "{settings.apple_team_id}",
            "{settings.apple_key_id}",
        ]

        for pattern in dangerous_patterns:
            assert pattern not in source, (
                f"Found dangerous pattern in main.py: {pattern}"
            )


class TestLoggingNoCredentials:
    """Tests to ensure logging never captures credentials."""

    @pytest.mark.asyncio
    async def test_no_credentials_in_relay_client_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verify relay client doesn't log capability secrets."""
        from app.services.relay_client import PrimePushRelayClient

        client = PrimePushRelayClient(timeout_seconds=5)
        push_url = "https://relay.example.com/push/pushid-123/secret-456"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = lambda: {"queued": True}
            mock_response.raise_for_status = lambda: None

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = AsyncMock()
            mock_client_class.return_value = mock_client

            with caplog.at_level(logging.DEBUG):
                await client.send_push(
                    push_url=push_url,
                    title="Test",
                    body="Test body",
                )

        # Verify no sensitive patterns in logs
        sensitive_patterns = ["secret-456", push_url]
        for pattern in sensitive_patterns:
            assert pattern not in caplog.text, (
                f"Found sensitive pattern in logs: {pattern}"
            )
