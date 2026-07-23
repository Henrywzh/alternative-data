from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate


def build_email_body(run_date: str, brief: dict) -> str:
    lines = [f"AI/LLM News Daily Brief — {run_date}", ""]
    lines.append(brief.get("overall_summary", ""))
    lines.append("")
    items = brief.get("items", [])
    if not items:
        lines.append("No high-importance items today.")
    for item in items:
        lines.append(f"- {item.get('headline', item.get('item_id', ''))}")
        lines.append(f"  {item.get('analysis', '')}")
        lines.append("")
    return "\n".join(lines)


def send_email(config: dict[str, str], *, run_date: str, body: str) -> None:
    sender = config.get("GMAIL_SENDER")
    password = config.get("GMAIL_APP_PASSWORD")
    recipient = config.get("GMAIL_RECIPIENT")
    missing = [
        name
        for name, value in {
            "GMAIL_SENDER": sender,
            "GMAIL_APP_PASSWORD": password,
            "GMAIL_RECIPIENT": recipient,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("Missing Gmail configuration: " + ", ".join(missing))

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Date"] = formatdate(localtime=True)
    message["Subject"] = f"AI/LLM News Daily Brief | {run_date}"
    message.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message, to_addrs=[recipient])
