"""Company setup-state and official-change summaries for Control Tower.

These helpers are display-only. They never write into valuation or thesis
marts, and they do not emit buy/sell language.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pandas as pd

from market_monitor.technicals import compute_technicals
from .official_filings import _classify_hkex_title

SETUP_STATES = ("washout", "extended", "chop", "event_window", "neutral", "unavailable")

_PRIORITY_CLASSES = {"earnings_results"}
_ROUTINE_CLASSES = {"share_buyback", "share_scheme"}
_REPORT_CLASSES = {"period_report"}


@dataclass(frozen=True, slots=True)
class CompanySetup:
    state: str
    label: str
    reason: str
    rsi: float | None
    ma20_pct: float | None
    drawdown_60d: float | None
    realized_vol_20d: float | None
    event_window: bool
    next_event_title: str
    as_of: str
    source_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "label": self.label,
            "reason": self.reason,
            "rsi": self.rsi,
            "ma20_pct": self.ma20_pct,
            "drawdown_60d": self.drawdown_60d,
            "realized_vol_20d": self.realized_vol_20d,
            "event_window": self.event_window,
            "next_event_title": self.next_event_title,
            "as_of": self.as_of,
            "source_note": self.source_note,
        }


@dataclass(frozen=True, slots=True)
class OfficialChangeCard:
    bucket: str
    fact: str
    headline: str
    event_class: str
    published_at: str
    source_url: str
    needs_review: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "fact": self.fact,
            "headline": self.headline,
            "event_class": self.event_class,
            "published_at": self.published_at,
            "source_url": self.source_url,
            "needs_review": self.needs_review,
        }


_STATE_LABELS = {
    "washout": "Washout",
    "extended": "Extended",
    "chop": "Chop",
    "event_window": "Event window",
    "neutral": "Neutral",
    "unavailable": "Unavailable",
}


def _as_utc(value: object) -> pd.Timestamp | None:
    stamp = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(stamp):
        return None
    return pd.Timestamp(stamp)


def _close_series(price_bars: pd.DataFrame) -> pd.Series:
    if price_bars is None or price_bars.empty:
        return pd.Series(dtype=float)
    frame = price_bars.copy()
    if "bar_date" not in frame.columns:
        return pd.Series(dtype=float)
    frame["bar_date"] = pd.to_datetime(frame["bar_date"], errors="coerce")
    frame = frame.loc[frame["bar_date"].notna()]
    if frame.empty:
        return pd.Series(dtype=float)
    series_column = "adj_close" if "adj_close" in frame.columns and frame["adj_close"].notna().any() else "close"
    if series_column not in frame.columns:
        return pd.Series(dtype=float)
    frame = frame.loc[frame[series_column].notna(), ["bar_date", series_column]]
    frame = frame.sort_values("bar_date").drop_duplicates("bar_date", keep="last")
    return pd.Series(
        pd.to_numeric(frame[series_column], errors="coerce").to_numpy(),
        index=pd.DatetimeIndex(frame["bar_date"]),
        dtype=float,
    ).dropna()


def _upcoming_event_window(
    events: pd.DataFrame,
    *,
    now_utc: pd.Timestamp,
    horizon_days: int = 14,
) -> tuple[bool, str]:
    if events is None or events.empty:
        return False, ""
    work = events.copy()
    start = pd.to_datetime(work.get("starts_at"), errors="coerce", utc=True)
    work = work.assign(_starts=start).dropna(subset=["_starts"])
    if work.empty:
        return False, ""
    horizon = now_utc + pd.Timedelta(days=horizon_days)
    upcoming = work.loc[(work["_starts"] >= now_utc) & (work["_starts"] <= horizon)]
    if upcoming.empty:
        return False, ""
    row = upcoming.sort_values("_starts").iloc[0]
    title = str(row.get("title") or row.get("event_type") or "upcoming event").strip()
    when = pd.Timestamp(row["_starts"]).strftime("%Y-%m-%d")
    return True, f"{title} · {when}"


def classify_company_setup(
    price_bars: pd.DataFrame,
    *,
    events: pd.DataFrame | None = None,
    now_utc: pd.Timestamp | None = None,
) -> CompanySetup:
    """Map delayed daily bars onto a labelled setup state.

    Thresholds are descriptive, not a trading signal. Event windows overlay
    the technical state instead of replacing it in the evidence fields.
    """

    now = now_utc if now_utc is not None else pd.Timestamp.now(tz="UTC")
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    close = _close_series(price_bars)
    event_window, next_event = _upcoming_event_window(events if events is not None else pd.DataFrame(), now_utc=now)
    source_note = (
        "Delayed daily bars; RSI/MA/drawdown reuse the Asia Markets technical contract. "
        "This is a setup label, not a buy/sell recommendation."
    )
    if len(close) < 25:
        return CompanySetup(
            state="unavailable",
            label=_STATE_LABELS["unavailable"],
            reason="Need at least 25 daily closes before RSI/MA setup is labelled.",
            rsi=None,
            ma20_pct=None,
            drawdown_60d=None,
            realized_vol_20d=None,
            event_window=event_window,
            next_event_title=next_event,
            as_of="",
            source_note=source_note,
        )
    snapshot = compute_technicals(close)
    rsi = snapshot.get("rsi")
    ma20_pct = snapshot.get("ma20_pct")
    drawdown = snapshot.get("drawdown_60d")
    vol = snapshot.get("realized_vol_20d")
    as_of = close.index.max().date().isoformat()

    def _num(value: object) -> float | None:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    rsi_n = _num(rsi)
    ma20_n = _num(ma20_pct)
    dd_n = _num(drawdown)
    vol_n = _num(vol)
    if rsi_n is None or ma20_n is None or dd_n is None:
        return CompanySetup(
            state="unavailable",
            label=_STATE_LABELS["unavailable"],
            reason="Technical snapshot is incomplete for the latest session.",
            rsi=rsi_n,
            ma20_pct=ma20_n,
            drawdown_60d=dd_n,
            realized_vol_20d=vol_n,
            event_window=event_window,
            next_event_title=next_event,
            as_of=as_of,
            source_note=source_note,
        )

    if event_window:
        state = "event_window"
        reason = f"Confirmed catalyst within 14 days ({next_event}). Technicals remain visible as evidence."
    elif rsi_n >= 70 and ma20_n >= 5:
        state = "extended"
        reason = f"RSI {rsi_n:.1f} and price {ma20_n:+.1f}% vs 20-day average."
    elif rsi_n <= 35 and dd_n <= -12:
        state = "washout"
        reason = f"RSI {rsi_n:.1f} with 60-day drawdown {dd_n:.1f}%."
    elif vol_n is not None and vol_n >= 0.025 and abs(ma20_n) < 3 and 40 <= rsi_n <= 60:
        state = "chop"
        reason = f"20-day realized vol {vol_n:.1%} with RSI {rsi_n:.1f} near the 20-day average."
    else:
        state = "neutral"
        reason = f"RSI {rsi_n:.1f}, {ma20_n:+.1f}% vs 20-day average, 60-day drawdown {dd_n:.1f}%."
    return CompanySetup(
        state=state,
        label=_STATE_LABELS[state],
        reason=reason,
        rsi=rsi_n,
        ma20_pct=ma20_n,
        drawdown_60d=dd_n,
        realized_vol_20d=vol_n,
        event_window=event_window,
        next_event_title=next_event,
        as_of=as_of,
        source_note=source_note,
    )


def _event_class_for_row(row: Mapping[str, Any]) -> str:
    existing = str(row.get("event_class") or "").strip()
    if existing and existing not in {"", "general", "unclassified"}:
        return existing
    headline = str(row.get("headline") or row.get("title") or "")
    classified = _classify_hkex_title(headline).get("event_class")
    return str(classified or existing or "general")


def _bucket_for_event_class(event_class: str, headline: str) -> str:
    label = (event_class or "").lower()
    title = (headline or "").upper()
    if label in _PRIORITY_CLASSES or ("RESULTS" in title and "ENDED" in title):
        return "priority"
    if label in _REPORT_CLASSES or (
        ("INTERIM REPORT" in title or "ANNUAL REPORT" in title) and "ENDED" not in title
    ):
        return "reports"
    if label in _ROUTINE_CLASSES or "NEXT DAY DISCLOSURE" in title or "SHARE AWARD" in title or "SHARE OPTION" in title:
        return "routine"
    return "other"


def _format_amount(value: object, currency: str) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return ""
    amount = float(number)
    prefix = f"{currency} ".strip() + " "
    if abs(amount) >= 1e9:
        return f"{prefix}{amount/1e9:.2f}bn"
    if abs(amount) >= 1e6:
        return f"{prefix}{amount/1e6:.1f}m"
    return f"{prefix}{amount:,.0f}"


def official_fact_line(row: Mapping[str, Any]) -> str:
    """One official fact sentence. No thesis language."""

    headline = str(row.get("headline") or row.get("title") or "").strip()
    event_class = _event_class_for_row(row)
    published = _as_utc(row.get("published_at") or row.get("filing_date") or row.get("execution_date"))
    day = published.strftime("%Y-%m-%d") if published is not None else "date unavailable"
    if event_class == "share_buyback" or str(row.get("action_type") or "") == "buyback_execution":
        shares = pd.to_numeric(pd.Series([row.get("shares_affected")]), errors="coerce").iloc[0]
        paid = _format_amount(row.get("total_amount_paid"), str(row.get("currency") or "HKD"))
        share_txt = f"{int(shares):,} shares" if pd.notna(shares) else "shares undisclosed"
        paid_txt = f" / {paid}" if paid else ""
        return f"{day} · Buyback {share_txt}{paid_txt}"
    if event_class == "earnings_results":
        return f"{day} · {headline or 'Results announcement'}"
    if event_class == "period_report":
        return f"{day} · {headline or 'Period report'}"
    if event_class == "share_scheme":
        return f"{day} · {headline or 'Share scheme filing'}"
    return f"{day} · {headline or 'Official filing'}"


def build_official_change_cards(
    *,
    filings: pd.DataFrame | None = None,
    corporate_actions: pd.DataFrame | None = None,
    live_overlay: pd.DataFrame | None = None,
    limit: int = 8,
) -> list[OfficialChangeCard]:
    """Merge official sources into Inbox cards, routine buybacks last."""

    frames: list[pd.DataFrame] = []
    for frame, origin in (
        (live_overlay, "live"),
        (filings, "filings"),
        (corporate_actions, "actions"),
    ):
        if frame is None or frame.empty:
            continue
        work = frame.copy()
        work["_origin"] = origin
        frames.append(work)
    if not frames:
        return []
    combined = pd.concat(frames, ignore_index=True, sort=False)
    cards: list[OfficialChangeCard] = []
    seen: set[str] = set()
    for _, row in combined.iterrows():
        payload = row.to_dict()
        event_class = _event_class_for_row(payload)
        headline = str(payload.get("headline") or payload.get("title") or "").strip()
        if payload.get("_origin") == "actions" and str(payload.get("action_type") or "") == "buyback_execution":
            event_class = "share_buyback"
            if not headline:
                headline = "Next Day Disclosure Return - share buyback"
        bucket = _bucket_for_event_class(event_class, headline)
        url = str(payload.get("source_url") or "").strip()
        published = _as_utc(payload.get("published_at") or payload.get("filing_date"))
        key = url or f"{event_class}|{headline}|{published}"
        if key in seen:
            continue
        seen.add(key)
        cards.append(
            OfficialChangeCard(
                bucket=bucket,
                fact=official_fact_line({**payload, "event_class": event_class, "headline": headline}),
                headline=headline or "Official filing",
                event_class=event_class,
                published_at=published.isoformat() if published is not None else "",
                source_url=url,
                needs_review=bucket == "priority",
            )
        )
    prioritized = [card for card in cards if card.bucket != "routine"]
    routine = [card for card in cards if card.bucket == "routine"]
    prioritized.sort(key=lambda card: card.published_at, reverse=True)
    routine.sort(key=lambda card: card.published_at, reverse=True)
    selected = (prioritized + routine)[: max(limit, 0)]
    return selected
