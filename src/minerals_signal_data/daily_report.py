from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path
import os
import smtplib
import ssl
import tempfile

import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd
from PIL import Image

from minerals_signal_data.market_data import fetch_public_stock_prices


TUNGSTEN_TICKERS = ["002842.SZ", "000657.SZ", "002378.SZ", "600397.SH", "600549.SH"]
MOLYBDENUM_TICKERS = ["601958.SH", "603993.SH", "3993.HK"]
CHINESE_STOCK_NAMES = {
    "000657.SZ": "中钨高新",
    "002378.SZ": "章源钨业",
    "002842.SZ": "翔鹭钨业",
    "600397.SH": "江钨装备",
    "600549.SH": "厦门钨业",
    "601958.SH": "金钼股份",
    "603993.SH": "洛阳钼业",
    "3993.HK": "洛阳钼业",
}


@dataclass(frozen=True)
class ReportSpec:
    mineral_id: str
    mineral_name: str
    mineral_file: str
    mineral_series: tuple[tuple[str, str], ...]
    stock_tickers: tuple[str, ...]
    mineral_title: str
    stock_title: str


REPORT_SPECS = (
    ReportSpec(
        mineral_id="tungsten",
        mineral_name="钨",
        mineral_file="tungsten_chinatungsten.csv",
        mineral_series=(
            ("apt", "APT"),
            ("wolframite_concentrate", "黑钨精矿"),
            ("ferrotungsten", "钨铁"),
        ),
        stock_tickers=tuple(TUNGSTEN_TICKERS),
        mineral_title="钨产品价格走势",
        stock_title="钨相关股票走势",
    ),
    ReportSpec(
        mineral_id="molybdenum",
        mineral_name="钼",
        mineral_file="molybdenum_chinatungsten.csv",
        mineral_series=(
            ("molybdenum_concentrate", "钼精矿"),
            ("ferromolybdenum", "钼铁"),
            ("ammonium_heptamolybdate", "七钼酸铵"),
        ),
        stock_tickers=tuple(MOLYBDENUM_TICKERS),
        mineral_title="钼产品价格走势",
        stock_title="钼相关股票走势",
    ),
)


def _configure_font() -> None:
    candidates = (
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False


def _stock_mapping(tickers: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        market = "HK" if ticker.endswith(".HK") else "CN_A"
        rows.append({"ticker_normalized": ticker, "market": market})
    return pd.DataFrame(rows)


def _load_config(base_dir: Path) -> dict[str, str]:
    values = {
        key: os.environ[key]
        for key in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD", "GMAIL_RECIPIENT")
        if os.environ.get(key)
    }
    config_path = base_dir / ".config"
    if config_path.exists():
        for raw in config_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    missing = [key for key in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD", "GMAIL_RECIPIENT") if not values.get(key)]
    if missing:
        raise RuntimeError("Missing Gmail configuration: " + ", ".join(missing))
    return values


def _load_mineral_frame(base_dir: Path, spec: ReportSpec) -> pd.DataFrame:
    path = base_dir / "data" / "raw" / "minerals_signal_data" / spec.mineral_file
    if not path.exists():
        raise FileNotFoundError(f"Missing mineral price data: {path}")
    frame = pd.read_csv(path, parse_dates=["date"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame.dropna(subset=["date"]).sort_values("date")


def _save_plot(fig: plt.Figure, path: Path, *, right_margin: int = 40) -> None:
    fig.savefig(path, dpi=160, bbox_inches="tight", pad_inches=0, facecolor="white")
    plt.close(fig)
    image = Image.open(path).convert("RGB")
    padded = Image.new("RGB", (image.width + right_margin, image.height), "white")
    padded.paste(image, (0, 0))
    padded.save(path, format="PNG", optimize=True)


def _build_mineral_chart(
    frame: pd.DataFrame,
    spec: ReportSpec,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    path: Path,
    mobile: bool,
) -> pd.Timestamp:
    fig, ax = plt.subplots(figsize=(10.3, 8.5) if mobile else (13.53, 6.5), dpi=120)
    latest_dates: list[pd.Timestamp] = []
    for column, label in spec.mineral_series:
        values = frame[["date", column]].copy() if column in frame.columns else pd.DataFrame()
        if values.empty:
            continue
        values[column] = pd.to_numeric(values[column], errors="coerce")
        values = values.dropna(subset=[column])
        if values.empty:
            continue
        base = float(values[column].iloc[0])
        ax.plot(values["date"], values[column] / base * 100, marker="o", markersize=2.5, linewidth=2.5, label=label)
        latest_dates.append(values["date"].max())
    ax.set_ylabel("价格指数")
    ax.grid(True, color="#c7c7c7", linewidth=1.0)
    ax.legend(loc="upper left", frameon=False, ncol=3 if mobile else 3, handlelength=2.8)
    ax.set_xlim(start, end)
    fig.subplots_adjust(left=0.10, right=0.98, bottom=0.10, top=1.0)
    _save_plot(fig, path)
    return max(latest_dates) if latest_dates else pd.NaT


def _build_stock_chart(
    frame: pd.DataFrame,
    spec: ReportSpec,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    path: Path,
    mobile: bool,
) -> pd.Timestamp:
    fig, ax = plt.subplots(figsize=(10.3, 8.5) if mobile else (13.53, 6.5), dpi=120)
    latest_dates: list[pd.Timestamp] = []
    for ticker, group in frame.groupby("ticker_normalized", sort=True):
        values = group.dropna(subset=["adj_close"]).sort_values("date")
        if values.empty:
            continue
        base = float(values["adj_close"].iloc[0])
        label = f"{CHINESE_STOCK_NAMES.get(ticker, ticker)} ({ticker})"
        ax.plot(values["date"], values["adj_close"] / base * 100, linewidth=2.5, label=label)
        latest_dates.append(values["date"].max())
    ax.set_ylabel("复权收盘价指数")
    ax.grid(True, color="#c7c7c7", linewidth=1.0)
    ax.legend(loc="upper left", frameon=False, ncol=1, handlelength=2.8)
    ax.set_xlim(start, end)
    fig.subplots_adjust(left=0.10, right=0.98, bottom=0.10, top=1.0)
    _save_plot(fig, path)
    return max(latest_dates) if latest_dates else pd.NaT


def _source_summary(stock_prices: pd.DataFrame) -> str:
    sources = stock_prices.get("price_source", pd.Series(dtype=str)).dropna().astype(str).unique().tolist()
    labels = {
        "tencent": "Tencent",
        "akshare_eastmoney": "AKShare/Eastmoney",
        "yfinance": "Yahoo Finance",
    }
    ordered = [source for source in ("tencent", "akshare_eastmoney", "yfinance") if source in sources]
    ordered.extend(source for source in sources if source not in ordered)
    return ", ".join(labels.get(source, source) for source in ordered) or "—"


def _build_email_html(
    spec: ReportSpec,
    *,
    report_date: str,
    mineral_date: str,
    stock_date: str,
    source_summary: str,
    mineral_cid: str,
    stock_cid: str,
) -> str:
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#fff;font-family:Arial,Helvetica,sans-serif;color:#17324d;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;margin:0;padding:0;background:#fff;">
<tr><td style="padding:8px 10px 5px;font-size:21px;line-height:25px;font-weight:700;color:#17324d;">{spec.mineral_name}每日图表简报</td></tr>
<tr><td style="padding:0 10px;font-size:16px;line-height:20px;font-weight:700;color:#17324d;">{spec.mineral_title} · {mineral_date}</td></tr>
<tr><td style="padding:0;margin:0;line-height:0;font-size:0;"><img src="cid:{mineral_cid}" alt="{spec.mineral_title}" style="display:block;width:100%;height:auto;border:0;margin:0;padding:0;"></td></tr>
<tr><td style="padding:7px 10px 0;font-size:16px;line-height:20px;font-weight:700;color:#17324d;">{spec.stock_title} · {stock_date}</td></tr>
<tr><td style="padding:0;margin:0;line-height:0;font-size:0;"><img src="cid:{stock_cid}" alt="{spec.stock_title}" style="display:block;width:100%;height:auto;border:0;margin:0;padding:0;"></td></tr>
<tr><td style="padding:5px 10px 10px;font-size:11px;line-height:14px;color:#667085;">矿产价格：CTIA；股票价格：{source_summary}。高清原图已作为附件。</td></tr>
</table></body></html>'''


def _send_email(
    config: dict[str, str],
    *,
    spec: ReportSpec,
    report_date: str,
    mineral_date: str,
    stock_date: str,
    source_summary: str,
    mobile_mineral: Path,
    mobile_stock: Path,
    original_mineral: Path,
    original_stock: Path,
) -> None:
    mineral_cid = f"{spec.mineral_id}-mineral-mobile"
    stock_cid = f"{spec.mineral_id}-stock-mobile"
    html_body = _build_email_html(
        spec,
        report_date=report_date,
        mineral_date=mineral_date,
        stock_date=stock_date,
        source_summary=source_summary,
        mineral_cid=mineral_cid,
        stock_cid=stock_cid,
    )
    plain_body = (
        f"{spec.mineral_name}每日图表简报\n\n"
        f"{spec.mineral_title} · {mineral_date}\n"
        f"{spec.stock_title} · {stock_date}\n\n"
        f"矿产价格：CTIA；股票价格：{source_summary}。\n"
        "高清原图已作为附件。\n"
    )
    message = EmailMessage()
    message["From"] = config["GMAIL_SENDER"]
    message["To"] = config["GMAIL_RECIPIENT"]
    message["Date"] = formatdate(localtime=True)
    message["Subject"] = f"{spec.mineral_name}每日图表简报 | {report_date}"
    message.set_content(plain_body)
    message.add_alternative(html_body, subtype="html")
    html_part = message.get_payload()[-1]
    for path, cid in ((mobile_mineral, mineral_cid), (mobile_stock, stock_cid)):
        html_part.add_related(path.read_bytes(), maintype="image", subtype="png", cid=f"<{cid}>", filename=path.name)
    for path in (original_mineral, original_stock):
        html_part.add_attachment(path.read_bytes(), maintype="image", subtype="png", filename=path.name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(config["GMAIL_SENDER"], config["GMAIL_APP_PASSWORD"])
        smtp.send_message(message)


def send_daily_reports(
    base_dir: str | Path,
    *,
    report_date: str | None = None,
    output_dir: str | Path | None = None,
    send_email: bool = True,
) -> dict[str, dict[str, str]]:
    """Build and send the daily Tungsten and Molybdenum Gmail reports."""
    base = Path(base_dir).resolve()
    _configure_font()
    local_today = pd.Timestamp.now(tz="Asia/Shanghai").normalize().tz_localize(None)
    run_date = pd.Timestamp(report_date).normalize() if report_date else local_today
    start = run_date.replace(month=1, day=1)
    end = run_date
    config = _load_config(base) if send_email else {}
    temp_context = tempfile.TemporaryDirectory(prefix="minerals-daily-report-") if output_dir is None else None
    output = Path(output_dir) if output_dir is not None else Path(temp_context.name)
    output.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, str]] = {}
    try:
        for spec in REPORT_SPECS:
            mineral = _load_mineral_frame(base, spec)
            mineral = mineral.loc[mineral["date"].between(start, end)].copy()
            mapping = _stock_mapping(spec.stock_tickers)
            stock = fetch_public_stock_prices(mapping, start_date=start.date().isoformat())
            stock["date"] = pd.to_datetime(stock["date"], errors="coerce")
            stock = stock.dropna(subset=["date", "adj_close"])
            all_dates = [start, end]
            if not mineral.empty:
                all_dates.append(mineral["date"].max())
            if not stock.empty:
                all_dates.append(stock["date"].max())
            chart_end = max(all_dates)
            prefix = spec.mineral_id
            mobile_mineral = output / f"{prefix}_mineral_mobile.png"
            mobile_stock = output / f"{prefix}_stock_mobile.png"
            original_mineral = output / f"{prefix}_mineral_original.png"
            original_stock = output / f"{prefix}_stock_original.png"
            mineral_date = _build_mineral_chart(mineral, spec, start=start, end=chart_end, path=mobile_mineral, mobile=True)
            _build_mineral_chart(mineral, spec, start=start, end=chart_end, path=original_mineral, mobile=False)
            stock_date = _build_stock_chart(stock, spec, start=start, end=chart_end, path=mobile_stock, mobile=True)
            _build_stock_chart(stock, spec, start=start, end=chart_end, path=original_stock, mobile=False)
            mineral_date_text = pd.Timestamp(mineral_date).date().isoformat() if not pd.isna(mineral_date) else "—"
            stock_date_text = pd.Timestamp(stock_date).date().isoformat() if not pd.isna(stock_date) else "—"
            if send_email:
                _send_email(
                    config,
                    spec=spec,
                    report_date=run_date.date().isoformat(),
                    mineral_date=mineral_date_text,
                    stock_date=stock_date_text,
                    source_summary=_source_summary(stock),
                    mobile_mineral=mobile_mineral,
                    mobile_stock=mobile_stock,
                    original_mineral=original_mineral,
                    original_stock=original_stock,
                )
            results[spec.mineral_id] = {
                "mineral_date": mineral_date_text,
                "stock_date": stock_date_text,
                "stock_sources": _source_summary(stock),
            }
    finally:
        if temp_context is not None:
            temp_context.cleanup()
    return results
