from __future__ import annotations

from ops_control.redaction import redact_text, redact_value


def test_secret_like_values_are_redacted_from_evidence_messages() -> None:
    raw = (
        "Authorization: Bearer sk-live-abcdefghijklmnopqrstuvwxyz\n"
        "api_key=top-secret-value\n"
        "FRED_API_KEY=fred-secret-value\n"
        "token: ghp_abcdefghijklmnopqrstuvwxyz123456"
    )

    redacted = redact_text(raw)

    assert "sk-live" not in redacted
    assert "top-secret-value" not in redacted
    assert "fred-secret-value" not in redacted
    assert "ghp_" not in redacted
    assert redacted.count("[REDACTED]") == 4
    assert "Authorization: Bearer [REDACTED]" in redacted


def test_json_quoted_secret_fields_are_redacted_from_log_text() -> None:
    raw = (
        '{"api_key": "json-api-secret", "token": "json-token-secret", '
        '"Authorization": "Bearer json-bearer-secret", "row_count": 42}'
    )

    redacted = redact_text(raw)

    assert "json-api-secret" not in redacted
    assert "json-token-secret" not in redacted
    assert "json-bearer-secret" not in redacted
    assert '"row_count": 42' in redacted


def test_common_secret_key_families_and_escaped_json_are_redacted() -> None:
    raw = (
        '{"secret_key": "secret-key-value", '
        '"AWS_SECRET_ACCESS_KEY": "aws-secret-value", '
        '"private_key": "private-key-value", '
        '"client_secret": "client-secret-value", '
        '"refresh_token": "refresh-token-value"}'
    )
    escaped = (
        r'{\"api_key\": \"escaped-api-secret\", '
        r'\"private_key\": \"escaped-private-secret\"}'
    )

    redacted = redact_text(raw)
    escaped_redacted = redact_text(escaped)

    for secret in (
        "secret-key-value",
        "aws-secret-value",
        "private-key-value",
        "client-secret-value",
        "refresh-token-value",
        "escaped-api-secret",
        "escaped-private-secret",
    ):
        assert secret not in redacted + escaped_redacted
    assert r'\"api_key\": \"[REDACTED]\"' in escaped_redacted


def test_additional_secret_key_families_are_redacted_in_plain_assignments() -> None:
    redacted = redact_text(
        "secret_key=secret-value AWS_SECRET_ACCESS_KEY=aws-value "
        "private_key=private-value safe_count=12"
    )

    assert "secret-value" not in redacted
    assert "aws-value" not in redacted
    assert "private-value" not in redacted
    assert "safe_count=12" in redacted


def test_multivalue_auth_and_cookie_headers_are_redacted_as_a_whole() -> None:
    raw = (
        "Authorization=Bearer equals-bearer-value\n"
        "Authorization: Basic basic-credential-value\n"
        "Cookie: session=first-cookie-value; refresh=second-cookie-value"
    )

    redacted = redact_text(raw)

    assert "equals-bearer-value" not in redacted
    assert "basic-credential-value" not in redacted
    assert "first-cookie-value" not in redacted
    assert "second-cookie-value" not in redacted


def test_camel_case_secret_fields_are_redacted() -> None:
    redacted = redact_text(
        '{"clientSecret": "client-camel-secret", '
        '"refreshToken": "refresh-camel-token", '
        '"AWSSecretAccessKey": "aws-camel-secret"}'
    )

    assert "client-camel-secret" not in redacted
    assert "refresh-camel-token" not in redacted
    assert "aws-camel-secret" not in redacted


def test_nested_evidence_values_are_redacted_recursively() -> None:
    payload = {
        "expected": "api_key=top-secret-value",
        "details": {
            "headers": ["Authorization: Bearer secret-token-value"],
            "api_key": "bare-secret-value",
            "FRED_API_KEY": "fred-bare-secret-value",
            "AWS_SECRET_ACCESS_KEY": "aws-bare-secret-value",
            "private_key": "private-bare-secret-value",
            "clientSecret": "camel-bare-secret-value",
            "refreshToken": "camel-refresh-secret-value",
            "safe": "row_count=42",
        },
    }

    redacted = redact_value(payload)

    assert "top-secret-value" not in str(redacted)
    assert "secret-token-value" not in str(redacted)
    assert "bare-secret-value" not in str(redacted)
    assert "fred-bare-secret-value" not in str(redacted)
    assert "aws-bare-secret-value" not in str(redacted)
    assert "private-bare-secret-value" not in str(redacted)
    assert "camel-bare-secret-value" not in str(redacted)
    assert "camel-refresh-secret-value" not in str(redacted)
    assert redacted["details"]["safe"] == "row_count=42"
