"""Preview and breadth-qualified Gmail alerts for the market-regime radar.

The scheduled job records component transitions in preview mode. Defensive
mode can send only when current domain breadth qualifies and an indicator
state changes. Gmail failures never block the pipeline/artifact path.
"""

from __future__ import annotations

import html
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .config import (
    ALERT_STATE_MAX_KEYS,
    ALERT_STATE_PATH,
    ALERT_STATE_VERSION,
    CONDITION_RULES,
    FRESH_CONDITION_STATUSES,
    REPO_ROOT,
    STATE_SEVERITY,
)
from .storage import atomic_write_text, utc_now


STATE_LABELS_ZH = {
    "Normal": "正常",
    "Watch": "观察",
    "Confirmed": "确认",
    "Escalating": "升级",
    "Improving": "缓和",
    "Unavailable": "不可用",
}
KNOWN_ALERT_STATES = frozenset(STATE_SEVERITY) | {"Unavailable"}


def load_gmail_config(recipient_override: str | None = None) -> dict[str, str]:
    allowed_keys = {
        "GMAIL_SENDER",
        "GMAIL_APP_PASSWORD",
        "GMAIL_RECIPIENT",
        "GMAIL_RECIPIENTS",
    }
    values = {
        key: os.environ[key]
        for key in allowed_keys
        if os.environ.get(key)
    }
    config_path = REPO_ROOT / ".config"
    if config_path.exists():
        for raw in config_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in allowed_keys:
                values.setdefault(key, value.strip().strip('"').strip("'"))
    if recipient_override:
        recipients = [recipient_override.strip()]
    else:
        recipients = [
            item.strip()
            for item in re.split(r"[,;]", values.get("GMAIL_RECIPIENTS") or values.get("GMAIL_RECIPIENT", ""))
            if item.strip()
        ]
    values["GMAIL_RECIPIENTS"] = ", ".join(recipients)
    missing = [key for key in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD") if not values.get(key)]
    if not recipients:
        missing.append("GMAIL_RECIPIENTS")
    if missing:
        raise RuntimeError("Missing Gmail config for global_market_regime: " + ", ".join(missing))
    return values


def _default_state() -> dict[str, Any]:
    return {
        "version": ALERT_STATE_VERSION,
        "last_states": {},
        "last_overall": "Normal",
        "sent_event_keys": [],
        "last_sent_at": None,
        "last_evaluation_at": None,
        "last_run_id": None,
        "last_decision": None,
        "last_component_events": [],
        "alert_mode": "preview",
    }


def load_alert_state(path: Path | str | None = None) -> dict[str, Any]:
    state_path = Path(path) if path is not None else ALERT_STATE_PATH
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(raw, Mapping) or raw.get("version") != ALERT_STATE_VERSION:
        return _default_state()
    state = _default_state()
    last_states = raw.get("last_states")
    if isinstance(last_states, Mapping):
        state["last_states"] = {str(k): str(v) for k, v in last_states.items()}
    if raw.get("last_overall"):
        state["last_overall"] = str(raw["last_overall"])
    keys = raw.get("sent_event_keys")
    if isinstance(keys, list):
        state["sent_event_keys"] = [str(k) for k in keys if str(k).strip()][-ALERT_STATE_MAX_KEYS:]
    if raw.get("last_sent_at"):
        state["last_sent_at"] = str(raw["last_sent_at"])
    if raw.get("last_evaluation_at"):
        state["last_evaluation_at"] = str(raw["last_evaluation_at"])
    if raw.get("last_run_id"):
        state["last_run_id"] = str(raw["last_run_id"])
    if raw.get("last_decision"):
        state["last_decision"] = str(raw["last_decision"])
    component_events = raw.get("last_component_events")
    if isinstance(component_events, list):
        state["last_component_events"] = [
            dict(event) for event in component_events if isinstance(event, Mapping)
        ][-16:]
    if raw.get("alert_mode") in {"preview", "defensive"}:
        state["alert_mode"] = str(raw["alert_mode"])
    return state


def save_alert_state(state: Mapping[str, Any], path: Path | str | None = None) -> None:
    state_path = Path(path) if path is not None else ALERT_STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["version"] = ALERT_STATE_VERSION
    atomic_write_text(
        state_path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def _esc(value: object) -> str:
    if value is None:
        return "—"
    missing = pd.isna(value)
    if isinstance(missing, bool) and missing:
        return "—"
    if type(missing).__name__ == "bool_" and bool(missing):
        return "—"
    return html.escape(str(value))


def detect_state_changes(current: pd.DataFrame, previous_states: Mapping[str, str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    required = {"indicator_id", "state", "freshness", "observation_date"}
    if (
        current is None
        or current.empty
        or not required.issubset(current.columns)
    ):
        return events
    for row in current.to_dict("records"):
        indicator_id = str(row.get("indicator_id") or "")
        new_state = str(row.get("state") or "Unavailable")
        old_state = str(previous_states.get(indicator_id) or "Normal")
        freshness = str(row.get("freshness") or "")
        observation_date = pd.to_datetime(
            row.get("observation_date"),
            errors="coerce",
        )
        if (
            indicator_id not in CONDITION_RULES
            or freshness not in FRESH_CONDITION_STATUSES
            or new_state not in KNOWN_ALERT_STATES
            or old_state not in KNOWN_ALERT_STATES
            or new_state == "Unavailable"
            or pd.isna(observation_date)
        ):
            continue
        if new_state == old_state:
            continue
        events.append(
            {
                "indicator_id": indicator_id,
                "domain_id": (CONDITION_RULES.get(indicator_id) or {}).get("domain_id"),
                "label_zh": row.get("label_zh") or indicator_id,
                "label_en": row.get("label_en") or indicator_id,
                "from_state": old_state,
                "to_state": new_state,
                "value": row.get("value"),
                "observation_date": row.get("observation_date"),
                "event_key": f"{indicator_id}|{old_state}|{new_state}|{row.get('observation_date')}",
            }
        )
    return events


def evaluate_alert(
    snapshot: pd.DataFrame,
    *,
    state: Mapping[str, Any] | None = None,
    mode: str = "defensive",
) -> dict[str, Any]:
    """Classify changes separately from the decision to send a defensive alert."""
    if mode not in {"preview", "defensive"}:
        raise ValueError(f"Unsupported alert mode: {mode}")
    current_state = dict(state or _default_state())
    events = detect_state_changes(snapshot, current_state.get("last_states") or {})
    sent = set(current_state.get("sent_event_keys") or [])
    new_events = [event for event in events if event["event_key"] not in sent]
    fresh = snapshot.copy() if snapshot is not None else pd.DataFrame()
    if not fresh.empty and {"indicator_id", "state", "freshness"}.issubset(
        fresh.columns
    ):
        valid_observation_date = (
            pd.to_datetime(fresh["observation_date"], errors="coerce").notna()
            if "observation_date" in fresh.columns
            else pd.Series(False, index=fresh.index)
        )
        fresh = fresh[
            fresh["freshness"].isin(FRESH_CONDITION_STATUSES)
            & fresh["indicator_id"].isin(CONDITION_RULES)
            & fresh["state"].isin(KNOWN_ALERT_STATES - {"Unavailable"})
            & valid_observation_date
        ]
    else:
        fresh = pd.DataFrame()
    confirmed_domains: set[str] = set()
    for row in fresh.to_dict("records") if not fresh.empty else []:
        indicator_id = str(row.get("indicator_id") or "")
        domain_id = (CONDITION_RULES.get(indicator_id) or {}).get("domain_id")
        if domain_id and STATE_SEVERITY.get(str(row.get("state")), 0) >= STATE_SEVERITY["Confirmed"]:
            confirmed_domains.add(str(domain_id))
    financial_stress_confirmed = "financial_stress" in confirmed_domains
    defensive_eligible = len(confirmed_domains) >= 2 or financial_stress_confirmed
    should_send = bool(new_events) and mode == "defensive" and defensive_eligible
    if should_send:
        kind = "defensive"
    elif new_events and defensive_eligible:
        kind = "defensive_eligible"
    elif new_events:
        kind = "component_preview"
    else:
        kind = "quiet"
    return {
        "should_send": should_send,
        "events": new_events,
        "kind": kind,
        "mode": mode,
        "confirmed_domain_count": len(confirmed_domains),
        "confirmed_domain_ids": sorted(confirmed_domains),
        "defensive_alert_eligible": defensive_eligible,
    }


def advance_alert_state(
    snapshot: pd.DataFrame,
    *,
    events: list[dict[str, Any]],
    state: Mapping[str, Any] | None = None,
    sent: bool,
    decision: Mapping[str, Any] | None = None,
    mode: str = "preview",
    run_id: str | None = None,
) -> dict[str, Any]:
    current = dict(state or _default_state())
    latest = dict(current.get("last_states") or {})
    latest.update({
        str(row["indicator_id"]): str(row.get("state") or "Unavailable")
        for row in (snapshot.to_dict("records") if snapshot is not None and not snapshot.empty else [])
        if str(row.get("freshness") or "") in FRESH_CONDITION_STATUSES
        and str(row.get("indicator_id") or "") in CONDITION_RULES
        and str(row.get("state") or "Unavailable")
        in KNOWN_ALERT_STATES - {"Unavailable"}
    })
    current["last_states"] = latest
    if latest:
        current["last_overall"] = max(latest.values(), key=lambda name: STATE_SEVERITY.get(name, 0))
    if sent and events:
        keys = list(current.get("sent_event_keys") or [])
        keys.extend(event["event_key"] for event in events)
        current["sent_event_keys"] = keys[-ALERT_STATE_MAX_KEYS:]
        current["last_sent_at"] = utc_now()
    current["last_evaluation_at"] = utc_now()
    if run_id:
        current["last_run_id"] = str(run_id)
    current["last_decision"] = str((decision or {}).get("kind") or "quiet")
    current["last_component_events"] = [dict(event) for event in events][-16:]
    current["alert_mode"] = mode
    return current


def build_email_html(
    snapshot: pd.DataFrame,
    events: list[dict[str, Any]],
    *,
    overall_state: str,
    breadth_zh: str | None = None,
) -> str:
    rows = []
    for event in events:
        rows.append(
            "<tr>"
            f"<td>{_esc(event.get('label_zh'))}</td>"
            f"<td>{_esc(STATE_LABELS_ZH.get(str(event.get('from_state')), event.get('from_state')))}</td>"
            f"<td><b>{_esc(STATE_LABELS_ZH.get(str(event.get('to_state')), event.get('to_state')))}</b></td>"
            f"<td>{_esc(event.get('value'))}</td>"
            f"<td>{_esc(event.get('observation_date'))}</td>"
            "</tr>"
        )
    cards = []
    if snapshot is not None and not snapshot.empty:
        for row in snapshot.to_dict("records"):
            cards.append(
                "<tr>"
                f"<td>{_esc(row.get('label_zh'))}</td>"
                f"<td>{_esc(STATE_LABELS_ZH.get(str(row.get('state')), row.get('state')))}</td>"
                f"<td>{_esc(row.get('value'))}</td>"
                f"<td>{_esc(row.get('observation_date'))}</td>"
                "</tr>"
            )
    return f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#0f172a">
      <h2>全球市场状态预警</h2>
      <p>当前总状态：<b>{_esc(STATE_LABELS_ZH.get(overall_state, overall_state))}</b>
      · 风险广度：<b>{_esc(breadth_zh or '—')}</b></p>
      <p style="color:#64748b">这是防守雷达，不是加仓信号。利率概率来自 Atlanta Fed 三个月平均 SOFR 分布，不是 CME FedWatch 下一次会议概率。</p>
      <h3>本次状态变化</h3>
      <table cellpadding="6" cellspacing="0" border="1" style="border-collapse:collapse;font-size:14px">
        <tr><th>指标</th><th>之前</th><th>现在</th><th>读数</th><th>观察日</th></tr>
        {''.join(rows) or '<tr><td colspan="5">无</td></tr>'}
      </table>
      <h3>当前面板</h3>
      <table cellpadding="6" cellspacing="0" border="1" style="border-collapse:collapse;font-size:14px">
        <tr><th>指标</th><th>状态</th><th>读数</th><th>观察日</th></tr>
        {''.join(cards)}
      </table>
    </body></html>
    """


def send_report(*, subject: str, body_html: str, recipient_override: str | None = None) -> None:
    config = load_gmail_config(recipient_override=recipient_override)
    msg = EmailMessage()
    msg["From"] = config["GMAIL_SENDER"]
    msg["To"] = config["GMAIL_RECIPIENTS"]
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("全球市场状态预警（请使用 HTML 查看）")
    msg.add_alternative(body_html, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
        smtp.login(config["GMAIL_SENDER"], config["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)
