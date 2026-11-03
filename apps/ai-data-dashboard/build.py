"""Build the AI data dashboard: a static site in dist/ for Cloudflare Pages.

Copies web/ to dist/ and writes each page's data.json from the normalized data
committed by the scraper workflows. The OpenRouter, Ramp, Semis and Downloads
numbers reuse the Streamlit dashboard's loaders and compute_* functions, so the
two show the same values; GPU comes from gpu.py. Run from the repository root:

    DATA_SOURCE=local PYTHONPATH=src:. python apps/ai-data-dashboard/build.py

Any page that fails to build fails the whole build, so a deploy never publishes
a site with a page missing. monthly_revenue_ntd is in NT$ thousands; /1e6 gives NT$ bn.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from dashboard.data import load_domain_datasets  # noqa: E402
from dashboard.sections import openrouter as orr  # noqa: E402
from dashboard.sections import provider_adoption as pa  # noqa: E402
from dashboard.sections import semiconductor as semi  # noqa: E402
from openrouter_arr_nowcast import build_arr_nowcast_summary  # noqa: E402

import gpu  # noqa: E402

ROOT = Path(".")
APP = Path(__file__).resolve().parent
OUT = APP / "dist"

# ECharts is served from the site itself, so a stalled CDN cannot blank every
# page. It is fetched at build time from the first mirror that answers and
# checked against this hash; .cache/ keeps a copy for offline rebuilds.
ECHARTS_VERSION = "5.5.1"
ECHARTS_SHA256 = "e84270bd0cd5bdf60fefc26d00c2a391cb2e81f4d26a7a9ee16185a54773a3cf"
ECHARTS_MIRRORS = [f"https://cdn.jsdelivr.net/npm/echarts@{ECHARTS_VERSION}/dist/echarts.min.js",
                   f"https://unpkg.com/echarts@{ECHARTS_VERSION}/dist/echarts.min.js"]


def clean(value):
    """JSON-safe scalars: NaN/inf to None, numpy to Python, timestamps to ISO dates."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, pd.Period):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return None if not math.isfinite(float(value)) else round(float(value), 6)
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def pivot_json(frame: pd.DataFrame, keep: list[str] | None = None, other: bool = False) -> dict:
    """{index: [...], series: {col: [...]}} with an optional 'Other' of the dropped columns."""
    frame = frame.sort_index()
    cols = keep if keep is not None else list(frame.columns)
    series = {c: frame[c].tolist() for c in cols if c in frame.columns}
    if other:
        rest = [c for c in frame.columns if c not in cols]
        if rest:
            series["Other"] = frame[rest].sum(axis=1, min_count=1).tolist()
    return {"index": [str(i)[:10] for i in frame.index], "series": series}


def top_columns(frame: pd.DataFrame, n: int, tail: int = 13) -> list[str]:
    return frame.sort_index().tail(tail).sum().sort_values(ascending=False).head(n).index.tolist()


def write(page: str, payload: dict) -> None:
    path = OUT / page / "data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB)")


# ---------------------------------------------------------------- OpenRouter
# Labs shown in the ARR views; the nowcast still runs over every target.
ARR_LABS = ["openai", "anthropic", "google", "x-ai", "deepseek", "z-ai", "moonshotai"]

def build_openrouter() -> None:
    ds = load_domain_datasets("openrouter_intelligence", base_dir=ROOT)
    derived = load_domain_datasets("openrouter_derived", base_dir=ROOT)
    views = orr.compute_openrouter_views(ds)

    # Tokens and estimated spend both come from the daily per-model revenue
    # estimates (the same table the ARR nowcast reads), so they cover the same
    # models and days. Labs are the ARR targets' names; anything else is Other.
    rev = derived["daily_provider_revenue_estimates"].frame.copy()
    rev["usage_date"] = pd.to_datetime(rev["usage_date"])
    names = orr.TARGET_ARR_PROVIDERS
    rev["lab"] = rev["provider_slug"].map(names).fillna("Other")
    last = rev["usage_date"].max()
    # The latest day is often a partial scrape; drop it from the charts when it is
    # under half the median of the seven days before (the nowcast handles it itself).
    totals = rev.groupby("usage_date")["total_tokens"].sum().sort_index()
    charted = rev.loc[rev["usage_date"] < last] if totals.iloc[-1] < 0.5 * totals.iloc[-8:-1].median() else rev
    # Monday weeks; a week missing any day (the first and the current one) is dropped.
    full = charted.assign(week=charted["usage_date"] - pd.to_timedelta(charted["usage_date"].dt.weekday, unit="D"))
    days_per_week = full.groupby("week")["usage_date"].nunique()
    complete = days_per_week[days_per_week == 7].index
    weekly = full.loc[full["week"].isin(complete)]
    weekly_tokens = weekly.pivot_table(index="week", columns="lab", values="total_tokens", aggfunc="sum")
    weekly_rev = weekly.pivot_table(index="week", columns="lab", values="estimated_revenue", aggfunc="sum")
    order = top_columns(weekly_tokens.drop(columns="Other", errors="ignore"), 9)
    daily_tokens = charted.pivot_table(index="usage_date", columns="lab", values="total_tokens", aggfunc="sum")
    daily_rev = charted.pivot_table(index="usage_date", columns="lab", values="estimated_revenue", aggfunc="sum")
    # Calendar months with every day observed.
    full["month"] = full["usage_date"].dt.to_period("M")
    days_per_month = full.groupby("month")["usage_date"].nunique()
    whole = [m for m, n in days_per_month.items() if n == m.days_in_month]
    monthly = full.loc[full["month"].isin(whole)]
    monthly_tokens = monthly.pivot_table(index="month", columns="lab", values="total_tokens", aggfunc="sum")
    monthly_rev = monthly.pivot_table(index="month", columns="lab", values="estimated_revenue", aggfunc="sum")

    # ARR: the dashboard's own monthly history and current-month nowcast.
    # The nowcast needs weekday and weekend days in the latest week, so for the
    # first days of a month it cannot run; show the last full month instead.
    try:
        summary = build_arr_nowcast_summary(rev, provider_column="provider_slug", targets=names)
    except ValueError:
        month_start = last.normalize().replace(day=1)
        summary = build_arr_nowcast_summary(rev.loc[rev["usage_date"] < month_start], provider_column="provider_slug", targets=names)
    hist = summary.history
    hist = hist.loc[hist["complete"].astype(bool) & (hist["month"] < summary.latest_period)]
    shown = [names[k] for k in ARR_LABS]
    arr = hist.pivot_table(index="month_label", columns="display_name", values="arr")[shown]
    nowcast = summary.nowcast_frame()
    nowcast = nowcast.loc[nowcast["display_name"].isin(shown)]

    # Models: last 7 days against the 7 before.
    recent = rev.loc[rev["usage_date"] > last - pd.Timedelta(days=60)]
    by_day = recent.groupby(["model_permaslug", "usage_date"], as_index=False)[["total_tokens", "estimated_revenue"]].sum()
    cur = by_day.loc[by_day["usage_date"] > last - pd.Timedelta(days=7)].groupby("model_permaslug")[["total_tokens", "estimated_revenue"]].sum()
    prev = by_day.loc[(by_day["usage_date"] <= last - pd.Timedelta(days=7)) & (by_day["usage_date"] > last - pd.Timedelta(days=14))].groupby("model_permaslug")["total_tokens"].sum()
    lab_of = rev.drop_duplicates("model_permaslug").set_index("model_permaslug")["lab"]
    top = cur.sort_values("total_tokens", ascending=False).head(40)
    days = pd.date_range(last - pd.Timedelta(days=59), last)
    models = []
    for slug, row in top.iterrows():
        daily = by_day.loc[by_day["model_permaslug"] == slug].set_index("usage_date")["total_tokens"].reindex(days)
        models.append({"slug": slug, "lab": lab_of.get(slug), "tokens_7d": row["total_tokens"], "revenue_7d": row["estimated_revenue"],
                       "growth_7d": row["total_tokens"] / prev.get(slug) - 1 if prev.get(slug) else None,
                       "daily": daily.tolist()})

    # Workloads: task spend history by macro category and the task table.
    ts = views["task_spend"]
    workloads = {}
    for basis in ("tokens", "spend"):
        history = ts["history_by_selection"][(basis, 30)]
        sel = ts["by_selection"][(basis, 30)]
        tasks = sel["task_summary"].sort_values("task_share_pct", ascending=False)
        model_rows = sel["model_rows"]
        task_rows = []
        for _, t in tasks.iterrows():
            leaders = model_rows.loc[model_rows["category_slug"] == t["category_slug"]].sort_values("rank").head(3)
            task_rows.append({"task": t["task_label"], "macro": t["macro_category"], "share": t["task_share_pct"],
                              "leaders": [{"model": r["model_permaslug"], "share": r["model_share_pct"]} for _, r in leaders.iterrows()]})
        workloads[basis] = {"history": pivot_json(history), "tasks": task_rows,
                            "macro": sel["macro_summary"].to_dict("records")}

    write("openrouter", {
        "as_of": str(last.date()),
        "tokens_weekly": pivot_json(weekly_tokens, order, other=True),
        "revenue_weekly": pivot_json(weekly_rev, order, other=True),
        "tokens_daily": pivot_json(daily_tokens, order, other=True),
        "revenue_daily": pivot_json(daily_rev, order, other=True),
        "tokens_monthly": pivot_json(monthly_tokens, order, other=True),
        "revenue_monthly": pivot_json(monthly_rev, order, other=True),
        "arr": {"months": [str(m) for m in arr.index], "series": {c: arr[c].tolist() for c in arr.columns},
                "latest_month": str(summary.latest_period),
                "observed_days": len(summary.observed_dates), "days_in_month": summary.latest_period.days_in_month,
                "complete": len(summary.observed_dates) == summary.latest_period.days_in_month,
                "nowcast": nowcast.to_dict("records")},
        "models": models,
        "model_days": [d.strftime("%Y-%m-%d") for d in days],
        "workloads": workloads,
        "task_snapshot": ts["latest_snapshot_date"],
    })


# ---------------------------------------------------------------- Ramp
MAKER_NAMES = {"anthropic": "Anthropic", "openai": "OpenAI", "google": "Google", "xai": "xAI", "deepseek": "DeepSeek",
               "alibaba": "Alibaba", "moonshot": "Moonshot", "zhipu": "Zhipu", "cursor": "Cursor", "nvidia": "NVIDIA",
               "minimax": "MiniMax", "meta": "Meta", "thinking-machines-lab": "Thinking Machines"}


def build_tokenomics() -> dict:
    """Ramp AI Index 'Tokenomics': weekly token spend and volume by model, and daily 7-day prices.

    Comes from Ramp's Token Spend Management customers, a sample that grows over
    time, so levels are shown indexed and the shares are the comparable series.
    """
    vol = pd.read_parquet(ROOT / "data/normalized/ramp/ramp_ai_token_activity.parquet")
    vol = vol.loc[vol["period_grain"].eq("weekly") & vol["dimension_type"].eq("model")]
    vol["maker"] = vol["model_maker"].map(MAKER_NAMES).fillna("Other")
    weekly = {}
    for metric in ("token_spend", "token_volume"):
        part = vol.loc[vol["metric_key"] == metric]
        weekly[metric] = part.pivot_table(index="period_end", columns="maker", values="metric_value", aggfunc="sum")
    order = top_columns(weekly["token_spend"].drop(columns="Other", errors="ignore"), 7)

    # Models: the last 4 weeks against the 4 before.
    weeks = sorted(vol["period_end"].unique())
    cur, prev = weeks[-4:], weeks[-8:-4]
    by_model = vol.pivot_table(index=["series_key", "series_label", "maker", "period_end"], columns="metric_key", values="metric_value", aggfunc="sum").reset_index()
    now = by_model.loc[by_model["period_end"].isin(cur)].groupby(["series_key", "series_label", "maker"])[["token_spend", "token_volume"]].sum(min_count=1)
    before = by_model.loc[by_model["period_end"].isin(prev)].groupby("series_key")[["token_spend", "token_volume"]].sum(min_count=1)
    now = now.reset_index().sort_values("token_spend", ascending=False)
    total_spend, total_vol = now["token_spend"].sum(), now["token_volume"].sum()
    spend_hist = by_model.pivot_table(index="period_end", columns="series_key", values="token_spend", aggfunc="sum")
    models = []
    for _, r in now.head(40).iterrows():
        b = before.loc[r["series_key"]] if r["series_key"] in before.index else None
        models.append({"model": r["series_label"], "maker": r["maker"], "spend_4w": r["token_spend"], "volume_4w": r["token_volume"],
                       "spend_share": r["token_spend"] / total_spend * 100, "volume_share": r["token_volume"] / total_vol * 100,
                       "first_week": str(spend_hist[r["series_key"]].first_valid_index())[:10] if r["series_key"] in spend_hist else None,
                       "spend_growth": r["token_spend"] / b["token_spend"] - 1 if b is not None and b["token_spend"] else None,
                       "weekly_spend": spend_hist[r["series_key"]].reindex(weeks[-26:]).tolist() if r["series_key"] in spend_hist else []})
    top_models = now.head(10)
    model_share = spend_hist[top_models["series_key"]].rename(columns=dict(zip(top_models["series_key"], top_models["series_label"])))
    model_share["Other"] = spend_hist.drop(columns=top_models["series_key"]).sum(axis=1, min_count=1)

    # Prices: $ per million tokens from the 7-day cost and count; "all_tokens" counts cached input.
    px = pd.read_parquet(ROOT / "data/normalized/ramp/ramp_ai_token_prices.parquet")
    both = px.groupby(["usage_date", "token_type"], as_index=False)[["token_cost_usd_7d", "token_count_7d"]].sum().assign(model_maker="combined")
    px = pd.concat([px, both])
    px["ppm"] = px["token_cost_usd_7d"] / px["token_count_7d"] * 1e6
    px["maker"] = px["model_maker"].map(MAKER_NAMES).fillna("OpenAI & Anthropic")
    prices = {tt: pivot_json(px.loc[px["token_type"] == tt].pivot_table(index="usage_date", columns="maker", values="ppm"))
              for tt in ("all_tokens", "uncached_input", "output")}

    return {"spend": pivot_json(weekly["token_spend"], order, other=True), "volume": pivot_json(weekly["token_volume"], order, other=True),
            "model_spend": pivot_json(model_share), "models": models, "model_weeks": [str(w)[:10] for w in weeks[-26:]],
            "prices": prices, "window": [cur[0], cur[-1]], "prior_window": [prev[0], prev[-1]]}


def build_ramp() -> None:
    ds = load_domain_datasets("ramp", base_dir=ROOT)
    f = lambda k: ds[k].frame.copy()  # noqa: E731

    overall = f("ramp_ai_adoption_overall").sort_values("date_month")
    by_vendor = f("ramp_ai_adoption_by_vendor").pivot_table(index="date_month", columns="vendor", values="adoption_rate_pct")
    by_size = f("ramp_ai_adoption_by_size").pivot_table(index="date_month", columns="business_size", values="adoption_rate_pct")
    by_sector = f("ramp_ai_adoption_by_sector").pivot_table(index="date_month", columns="naics_sector", values="adoption_rate_pct")
    pepm = f("ramp_ai_pepm_spend").sort_values("date_month")
    spend = f("ramp_ai_spend_breakdown").pivot_table(index="date_month", columns="spend_category", values="spend_usd", aggfunc="sum")
    mb = f("ramp_ai_model_breakdown")
    model_types = sorted(mb["model_spend_type"].dropna().unique().tolist()) if "model_spend_type" in mb else []
    models = {}
    for mt in model_types or [None]:
        part = mb if mt is None else mb.loc[mb["model_spend_type"] == mt]
        by_provider = part.pivot_table(index="date_month", columns="ai_provider", values="model_share", aggfunc="sum")
        by_model = part.pivot_table(index="date_month", columns="model_label", values="model_share", aggfunc="sum")
        models[mt or "all"] = {"provider": pivot_json(by_provider), "model": pivot_json(by_model, top_columns(by_model, 10, 3), other=True)}

    va = f("ramp_vendor_adoption_monthly")
    latest = va["spend_month"].max()
    cur = va.loc[va["spend_month"] == latest].sort_values("adoption_rate", ascending=False)
    lead = cur.head(60)
    hist = va.loc[va["vendor_slug"].isin(lead["vendor_slug"])].pivot_table(index="spend_month", columns="vendor_name", values="adoption_rate")
    vendors = [{"vendor": r["vendor_name"], "rate": r["adoption_rate"], "yoy": r.get("adoption_rate_yoy"), "rank": r.get("adoption_rank"),
                "rank_mom": r.get("adoption_rank_mom"), "ent": r.get("adoption_rate_ent"), "mm": r.get("adoption_rate_mm"),
                "history": hist[r["vendor_name"]].tail(24).tolist() if r["vendor_name"] in hist else []} for _, r in lead.iterrows()]

    jobs = f("ramp_ai_jobs_impact")
    write("ramp", {
        "overall": {"months": overall["date_month"].astype(str).str[:7].tolist(), "rate": overall["adoption_rate_pct"].tolist(),
                    "mom": overall["mom_change_pp"].tolist(), "yoy": overall["yoy_change_pp"].tolist()},
        "by_vendor": pivot_json(by_vendor), "by_size": pivot_json(by_size), "by_sector": pivot_json(by_sector),
        "pepm": {"months": pepm["date_month"].astype(str).str[:7].tolist(), "median": pepm["median_pepm"].tolist(),
                 "p90": pepm["p90_pepm"].tolist(), "top10": pepm["top_10_percent_median_pepm"].tolist(),
                 "businesses": pepm["business_count"].tolist(), "spend": pepm["spend_usd"].tolist()},
        "spend_by_category": pivot_json(spend),
        "models": models,
        "vendor_month": str(latest)[:7], "vendor_months": [str(m)[:7] for m in hist.sort_index().index[-24:]],
        "vendors": vendors,
        "jobs": jobs.to_dict("records"),
        "tokens": build_tokenomics(),
    })


# ---------------------------------------------------------------- Semis
TW_NAMES = {"2330": "TSMC", "2303": "UMC", "5347": "VIS", "2317": "Hon Hai", "2382": "Quanta", "3231": "Wistron", "6669": "Wiwynn",
            "2408": "Nanya Tech", "2344": "Winbond", "8299": "Phison", "6239": "Powertech"}
PPI_NAMES = {"ppi_component_pcu33443344_rebased": "Semiconductors & components", "ppi_component_pcu33423342_rebased": "Communications equipment",
             "ppi_component_pcu335313335313_rebased": "Switchgear", "ppi_component_pcu334111334111_rebased": "Computers",
             "ppi_component_pcu3341123341121_rebased": "Storage devices"}


def build_semis() -> None:
    ds = {}
    for dom in ("semiconductor_memory", "semiconductor_proxies", "taiwan_semiconductor_revenue", "us_census_trade"):
        ds.update(load_domain_datasets(dom, base_dir=ROOT))
    v = semi.compute_semiconductor_views(ds)

    tw = v["taiwan_revenue_df"].copy()
    tw["code"] = tw["company_code"].astype(str)
    companies = []
    for code, g in tw.sort_values("revenue_month").groupby("code"):
        g = g.drop_duplicates("revenue_month", keep="last")
        companies.append({"code": code, "name": TW_NAMES.get(code, code), "local": g["company_name"].iloc[-1], "industry": g["industry"].iloc[-1],
                          "months": g["revenue_month"].astype(str).str[:7].tolist(), "revenue": (g["monthly_revenue_ntd"] / 1e6).tolist(),
                          "yoy": g["yoy_pct"].tolist(), "ytd_yoy": g["ytd_yoy_pct"].tolist()})

    off = v["official_df"].copy()
    trade = []
    for (country, metric, cat), g in off.loc[off["metric_type"] != "trade_balance"].groupby(["country_name", "metric_type", "category_id"]):
        g = g.sort_values("period").drop_duplicates("period", keep="last").set_index("period")
        value = g["value"].astype(float)
        idx = pd.PeriodIndex(value.index, freq="M")
        yoy = value.values / pd.Series(value.values, index=idx).reindex(idx - 12).values - 1
        trade.append({"country": country, "metric": metric, "category": cat, "label": g["category_label"].iloc[-1], "unit": g["unit"].iloc[-1],
                      "periods": list(value.index), "value": value.tolist(), "yoy": list(yoy)})

    proxy = v["proxy_df"].sort_values("month")
    write("semis", {
        "taiwan_latest": v["latest_taiwan_revenue_month"],
        "companies": companies,
        "trade": trade,
        "ppi": {"months": proxy["month"].astype(str).str[:7].tolist(), "base": v["base_month"],
                "series": {PPI_NAMES.get(c, c): proxy[c].tolist() for c in v["component_columns"]}},
    })


# ---------------------------------------------------------------- Downloads
def build_downloads() -> None:
    ds = load_domain_datasets("provider_adoption", base_dir=ROOT)
    v = pa.compute_provider_adoption_views(ds)
    order = v["provider_order"]

    def daily(frame: pd.DataFrame, date: str, value: str, by: str = "provider_display_name") -> dict:
        p = frame.pivot_table(index=date, columns=by, values=value, aggfunc="sum").sort_index()
        p.index = pd.to_datetime(p.index).strftime("%Y-%m-%d")
        return pivot_json(p, [c for c in order if c in p.columns] + [c for c in p.columns if c not in order])

    npm = {cat: daily(g, "download_date", "downloads") for cat, g in v["npm_grouped"].groupby("package_category")}
    npm["all"] = daily(v["npm_grouped"], "download_date", "downloads")
    gh = v["rollup_daily"]
    write("downloads", {
        "order": order,
        "pypi": daily(v["pypi_grouped"], "download_date", "downloads"),
        "npm": npm,
        "npm_categories": v["npm_categories"],
        "hf": daily(v["hf_grouped"], "download_date", "downloads_daily_est"),
        "hf_30d": daily(v["hf_grouped"], "download_date", "downloads_30d"),
        "github": {k: daily(gh, "signal_date", k) for k in ("signal_repos", "import_repos", "manifest_repos")},
        "latest": {"pypi": v["latest_pypi_date"], "npm": v["latest_npm_date"], "hf": v["latest_hf_date"], "github": v["latest_github_date"]},
    })


def vendor_echarts() -> None:
    cache = APP / ".cache" / f"echarts-{ECHARTS_VERSION}.min.js"
    body = cache.read_bytes() if cache.exists() else None
    for url in ECHARTS_MIRRORS:
        if body is not None:
            break
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ai-data-dashboard-build"}), timeout=30) as resp:
                body = resp.read()
        except OSError as exc:
            print(f"warning: {url}: {exc}")
    if body is None or hashlib.sha256(body).hexdigest() != ECHARTS_SHA256:
        raise SystemExit(f"could not get ECharts {ECHARTS_VERSION} with the expected SHA-256")
    cache.parent.mkdir(exist_ok=True)
    cache.write_bytes(body)
    (OUT / "shared" / "echarts.min.js").write_bytes(body)


def build_gpu() -> None:
    write("gpu", gpu.build(ROOT / "data/normalized/gpu_price_history"))


def main() -> None:
    global OUT
    parser = argparse.ArgumentParser(description="Build the static AI data dashboard.")
    parser.add_argument("--out", type=Path, default=OUT)
    OUT = parser.parse_args().out.resolve()
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(APP / "web", OUT)
    vendor_echarts()
    for build in (build_openrouter, build_ramp, build_semis, build_downloads, build_gpu):
        build()


if __name__ == "__main__":
    main()
