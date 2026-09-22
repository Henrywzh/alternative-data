from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate
import smtplib
import ssl
from typing import Iterable

from .incidents import ACTIVE_STATUSES, Incident
from .registry import PipelineRegistry


TAIPEI = timezone(timedelta(hours=8))


def build_digest(*, registry: PipelineRegistry, incidents: Iterable[Incident], now: datetime, weekly: bool = False) -> str:
    incidents = list(incidents)
    open_incidents = [item for item in incidents if item.status in ACTIVE_STATUSES]
    recent_cutoff = now - timedelta(hours=24)
    recovered = [
        item for item in incidents
        if item.status == "RECOVERED"
        and item.recovered_at is not None
        and datetime.fromisoformat(item.recovered_at.replace("Z", "+00:00")) >= recent_cutoff
    ]
    needs_human = [item for item in open_incidents if item.needs_human]
    needs_local = [item for item in open_incidents if item.needs_local]
    stale = [item for item in open_incidents if item.derived_state in {"STALE", "DEGRADED_RETAINED", "REGRESSED"}]
    jobs_without_open_incidents = 0
    total_jobs = 0
    unhealthy_keys = {(item.pipeline_id, item.job_id) for item in open_incidents}
    for pipeline in registry.pipelines.values():
        for job in pipeline.jobs.values():
            total_jobs += 1
            if (pipeline.pipeline_id, job.job_id) not in unhealthy_keys:
                jobs_without_open_incidents += 1
    local_now = now.astimezone(TAIPEI)
    weekday = local_now.strftime("%A")
    lines = [
        f"Alternative-data ops digest — {local_now.strftime('%Y-%m-%d %H:%M %Z')}",
        "",
        f"Jobs without open incidents: {jobs_without_open_incidents}/{total_jobs}",
        f"Open incidents: {len(open_incidents)}",
        f"Recovered in last 24h: {len(recovered)}",
        f"Needs human: {len(needs_human)}",
        f"Needs local: {len(needs_local)}",
        f"Stale/retained/regressed: {len(stale)}",
    ]
    if not open_incidents:
        lines.extend(["", "No open incidents in registered jobs."])
    else:
        lines.extend(["", "Open incidents:"])
        for item in open_incidents:
            url = f" ({item.issue_url})" if item.issue_url else ""
            lines.append(f"- {item.pipeline_id}/{item.job_id}: {item.status} {item.derived_state} — {item.summary}{url}")
    if recovered:
        lines.extend(["", "Recovered in last 24h:"])
        for item in recovered:
            url = f" ({item.issue_url})" if item.issue_url else ""
            lines.append(
                f"- {item.pipeline_id}/{item.job_id}: recovered at {item.recovered_at}; "
                f"previous issue: {item.summary}{url}"
            )
    if weekly or weekday == "Monday":
        weekly_cutoff = now - timedelta(days=7)
        counts = Counter(
            item.error_class for item in incidents
            if datetime.fromisoformat(item.updated_at.replace("Z", "+00:00")) >= weekly_cutoff
        )
        lines.extend(["", "Weekly reliability:"])
        if not counts:
            lines.append("- No incidents in the current window.")
        else:
            for error_class, count in counts.most_common():
                lines.append(f"- {error_class}: {count}")
    return "\n".join(lines) + "\n"


def send_digest_email(*, body: str, sender: str, password: str, recipients: list[str], now: datetime) -> None:
    if not sender or not password or not recipients:
        raise ValueError("Digest email requires sender, password, and recipients")
    local_now = now.astimezone(TAIPEI)
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Date"] = formatdate(localtime=True)
    message["Subject"] = f"alternative-data ops digest | {local_now.strftime('%Y-%m-%d')}"
    message.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message, to_addrs=recipients)
