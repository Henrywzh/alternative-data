from __future__ import annotations

from ops_control.redaction import redact_text, redact_value


def test_secret_like_values_are_redacted_from_evidence_messages() -> None:
    raw = (
        "Authorization: Bearer sk-live-abcdefghijklmnopqrstuvwxyz "
        "api_key=top-secret-value "
        "FRED_API_KEY=fred-secret-value "
        "token: ghp_abcdefghijklmnopqrstuvwxyz123456"
    )

    redacted = redact_text(raw)

    assert "sk-live" not in redacted
    assert "top-secret-value" not in redacted
    assert "fred-secret-value" not in redacted
    assert "ghp_" not in redacted
    assert redacted.count("[REDACTED]") == 4


def test_nested_evidence_values_are_redacted_recursively() -> None:
    payload = {
        "expected": "api_key=top-secret-value",
        "details": {
            "headers": ["Authorization: Bearer secret-token-value"],
            "api_key": "bare-secret-value",
            "FRED_API_KEY": "fred-bare-secret-value",
            "safe": "row_count=42",
        },
    }

    redacted = redact_value(payload)

    assert "top-secret-value" not in str(redacted)
    assert "secret-token-value" not in str(redacted)
    assert "bare-secret-value" not in str(redacted)
    assert "fred-bare-secret-value" not in str(redacted)
    assert redacted["details"]["safe"] == "row_count=42"
