"""GPU rental prices for the dashboard's GPU page, from the gpu_prices pipeline's CSVs.

The three sources stay separate in the output. The canonical GPU table below
only says which source series describe the same chip; no series is joined,
spliced or averaged across sources.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

# Canonical GPUs. `gd` is the GetDeploying slug, `mittal` the (gpu, form factor)
# pair in the monthly history, `screener` the Compute Screener name. Specs are
# dense BF16 TFLOPS and on-package memory per GPU, from vendor datasheets,
# rounded; they have not yet been reviewed against a cited source.
GPUS = [
    {"id": "b300", "label": "B300", "vendor": "NVIDIA", "tier": "flagship", "gd": "nvidia-b300", "mittal": ["B300", "SXM"], "screener": "B300", "bf16": 2250, "mem": 288},
    {"id": "b200", "label": "B200", "vendor": "NVIDIA", "tier": "flagship", "gd": "nvidia-b200", "mittal": ["B200", "SXM"], "screener": "B200", "bf16": 2250, "mem": 180},
    {"id": "h200", "label": "H200", "vendor": "NVIDIA", "tier": "flagship", "gd": "nvidia-h200", "mittal": ["H200", "SXM"], "screener": "H200", "bf16": 989, "mem": 141},
    {"id": "h100", "label": "H100", "vendor": "NVIDIA", "tier": "flagship", "gd": "nvidia-h100", "mittal": ["H100", "SXM"], "screener": "H100", "bf16": 989, "mem": 80},
    {"id": "a100", "label": "A100", "vendor": "NVIDIA", "tier": "flagship", "gd": "nvidia-a100", "mittal": ["A100-80GB", "SXM"], "screener": "A100", "bf16": 312, "mem": 80},
    {"id": "mi355x", "label": "MI355X", "vendor": "AMD", "tier": "flagship", "gd": "amd-mi355x", "mittal": None, "screener": None, "bf16": 2500, "mem": 288},
    {"id": "mi325x", "label": "MI325X", "vendor": "AMD", "tier": "flagship", "gd": "amd-mi325x", "mittal": None, "screener": None, "bf16": 1307, "mem": 256},
    {"id": "mi300x", "label": "MI300X", "vendor": "AMD", "tier": "flagship", "gd": "amd-mi300x", "mittal": ["MI300X", "OAM"], "screener": "MI300X", "bf16": 1307, "mem": 192},
    {"id": "gb200", "label": "GB200", "vendor": "NVIDIA", "tier": "superchip", "gd": "nvidia-gb200", "mittal": ["GB200", "Superchip"], "screener": None, "bf16": None, "mem": None},
    {"id": "gh200", "label": "GH200", "vendor": "NVIDIA", "tier": "superchip", "gd": "nvidia-gh200", "mittal": ["GH200", "Superchip"], "screener": None, "bf16": None, "mem": None},
    {"id": "rtxpro6000", "label": "RTX PRO 6000", "vendor": "NVIDIA", "tier": "inference", "gd": "nvidia-rtx-pro-6000", "mittal": ["RTXPRO6000", "PCIe"], "screener": "RTX PRO 6000", "bf16": None, "mem": 96},
    {"id": "l40s", "label": "L40S", "vendor": "NVIDIA", "tier": "inference", "gd": "nvidia-l40s", "mittal": ["L40S", "PCIe"], "screener": "L40S", "bf16": 362, "mem": 48},
    {"id": "a6000", "label": "RTX A6000", "vendor": "NVIDIA", "tier": "inference", "gd": "nvidia-a6000", "mittal": ["A6000", "PCIe"], "screener": "RTX A6000", "bf16": None, "mem": 48},
    {"id": "l4", "label": "L4", "vendor": "NVIDIA", "tier": "inference", "gd": "nvidia-l4", "mittal": ["L4", "PCIe"], "screener": None, "bf16": None, "mem": 24},
]

TERMS = [("SPOT", None, "Spot"), ("ON_DEMAND", None, "On-demand"), ("RESERVATION", 1, "1M"), ("RESERVATION", 3, "3M"),
         ("RESERVATION", 6, "6M"), ("RESERVATION", 12, "12M"), ("RESERVATION", 24, "24M"), ("RESERVATION", 36, "36M")]


def _num(value):
    return None if pd.isna(value) else round(float(value), 4)


# Composite indices. Each is a chained, matched-model index: from one period to
# the next it moves by the weighted geometric mean of price relatives of the
# models priced in both periods, weighted by their provider count (the mean of
# the two periods). A model enters or leaves without moving the level, so the
# index tracks price change, not a shift in which GPUs are listed. Models with
# fewer than MIN_PROVIDERS in either period are left out of that link.
DATA_CENTER = {"nvidia-a100", "nvidia-h100", "nvidia-h200", "nvidia-b200", "nvidia-b300", "nvidia-gh200", "nvidia-a10",
               "nvidia-a10g", "nvidia-a30", "nvidia-a40", "nvidia-a16", "nvidia-l4", "nvidia-l40", "nvidia-l40s", "nvidia-t4",
               "nvidia-v100", "nvidia-v100s", "nvidia-p100", "amd-mi300x", "amd-mi325x", "amd-mi355x", "nvidia-rtx-pro-6000"}
FRONTIER = {"nvidia-h100", "nvidia-h200", "nvidia-b200", "nvidia-b300", "amd-mi300x", "amd-mi325x", "amd-mi355x"}
INDICES = [("all", "Data center", DATA_CENTER), ("frontier", "Frontier", FRONTIER), ("prior", "Prior gen", DATA_CENTER - FRONTIER)]
# The monthly history names the same chips differently.
MONTHLY_MAP = {"nvidia-a100": ["A100-40GB", "A100-80GB"], "nvidia-h100": ["H100"], "nvidia-h200": ["H200"], "nvidia-b200": ["B200"],
               "nvidia-b300": ["B300"], "nvidia-gh200": ["GH200"], "nvidia-a10": ["A10"], "nvidia-a10g": ["A10G"], "nvidia-a40": ["A40"],
               "nvidia-l4": ["L4"], "nvidia-l40": ["L40"], "nvidia-l40s": ["L40S"], "nvidia-t4": ["T4"], "nvidia-v100": ["V100", "V100-32GB"],
               "amd-mi300x": ["MI300X"], "nvidia-rtx-pro-6000": ["RTXPRO6000"]}
MIN_PROVIDERS = 2
MIN_MONTHLY_MODELS = 4


def chain_index(panel: pd.DataFrame, members: set[str]) -> dict:
    """panel: period, model, price, providers. Returns levels (first period = 100) and each model's log contribution per link."""
    wide_p = panel.loc[panel["model"].isin(members)].pivot_table(index="period", columns="model", values="price")
    wide_n = panel.loc[panel["model"].isin(members)].pivot_table(index="period", columns="model", values="providers")
    periods = list(wide_p.index)
    level, levels, counts, contrib = 100.0, [100.0], [None], []
    for prev, cur in zip(periods, periods[1:]):
        p0, p1, n0, n1 = wide_p.loc[prev], wide_p.loc[cur], wide_n.loc[prev], wide_n.loc[cur]
        ok = p0.notna() & p1.notna() & (p0 > 0) & (p1 > 0) & (n0 >= MIN_PROVIDERS) & (n1 >= MIN_PROVIDERS)
        if not ok.any():
            levels.append(None); counts.append(0); contrib.append({})
            continue
        w = ((n0[ok] + n1[ok]) / 2)
        w = w / w.sum()
        logs = w * np.log(p1[ok] / p0[ok])
        level *= float(np.exp(logs.sum()))
        levels.append(round(level, 3)); counts.append(int(ok.sum()))
        contrib.append({k: round(float(v), 6) for k, v in logs.items()})
    return {"periods": [str(p) for p in periods], "level": levels, "models": counts, "contrib": contrib}


def build_indices(gd: pd.DataFrame, mh: pd.DataFrame) -> dict:
    od = gd.loc[gd["billing_type"].eq("ON_DEMAND") & gd["reservation_months"].isna()]
    weekly = od.rename(columns={"date": "period", "gpu_slug": "model", "provider_median_price": "price", "provider_count": "providers"})
    weekly = weekly.dropna(subset=["price"])
    # Weekly: the last 53 weeks the source publishes in full for every model.
    first = sorted(weekly["period"].unique())[-53]
    weekly = weekly.loc[weekly["period"] >= first]
    # Monthly: neocloud on-demand medians; a chip with several variants takes the
    # provider-weighted mean of its variants' medians for the month.
    rev = {name: slug for slug, names in MONTHLY_MAP.items() for name in names}
    m = mh.loc[mh["segment"].eq("neocloud_on_demand") & mh["gpu"].isin(rev)].copy()
    m["model"] = m["gpu"].map(rev)
    m = m.dropna(subset=["median_usd_per_gpu_hour"])
    monthly = (m.groupby(["month", "model"])
               .apply(lambda g: pd.Series({"price": float(np.average(g["median_usd_per_gpu_hour"], weights=g["n_providers"].clip(lower=1))),
                                           "providers": int(g["n_providers"].sum())}), include_groups=False)
               .reset_index().rename(columns={"month": "period"}))
    out = {"weekly": {key: {"label": label, **chain_index(weekly, members)} for key, label, members in INDICES}, "monthly": {}}
    # The monthly history is thin early on (often one chip with two providers).
    # Start each monthly index at the first link with MIN_MONTHLY_MODELS chips
    # and rebase it there; an index with under a year at that breadth is omitted.
    for key, label, members in INDICES:
        idx = chain_index(monthly, members)
        start = next((i for i, n in enumerate(idx["models"]) if n and n >= MIN_MONTHLY_MODELS), None)
        if start is None or len(idx["periods"]) - start < 12:
            continue
        start -= 1
        base = idx["level"][start]
        out["monthly"][key] = {"label": label, "periods": idx["periods"][start:],
                               "level": [None if v is None else round(v / base * 100, 3) for v in idx["level"][start:]],
                               "models": [None] + idx["models"][start + 1:], "contrib": idx["contrib"][start:]}
    return out


def build(src: Path) -> dict:
    gd = pd.read_parquet(src / "getdeploying.parquet")
    mh = pd.read_parquet(src / "github_history.parquet")
    cs = pd.read_parquet(src / "compute_screener.parquet")
    run = json.loads((src / "latest_run.json").read_text())

    od = gd.loc[gd["billing_type"].eq("ON_DEMAND")].sort_values("date")
    weeks = sorted(od["date"].unique())

    # Every GetDeploying model, for the screener table.
    table = []
    for slug, grp in od.groupby("gpu_slug"):
        grp = grp.dropna(subset=["provider_median_price"])
        if grp.empty:
            continue
        table.append({
            "slug": slug,
            "dates": grp["date"].tolist(),
            "price": [_num(v) for v in grp["provider_median_price"]],
            "providers": [None if pd.isna(v) else int(v) for v in grp["provider_count"]],
        })

    recent = gd.loc[gd["date"] >= weeks[-4]]
    gpus = []
    for spec in GPUS:
        item = {k: v for k, v in spec.items() if k not in ("mittal",)}
        # Term structure: median of the last four weekly provider medians per term.
        terms = []
        for billing, months, label in TERMS:
            rows = recent.loc[(recent["gpu_slug"] == spec["gd"]) & (recent["billing_type"] == billing)]
            rows = rows.loc[rows["reservation_months"].isna()] if months is None else rows.loc[rows["reservation_months"].eq(months)]
            rows = rows.dropna(subset=["provider_median_price"])
            terms.append({"term": label, "price": _num(rows["provider_median_price"].median()) if len(rows) else None,
                          "providers": int(rows["provider_count"].median()) if len(rows) else 0})
        item["terms"] = terms
        if spec["mittal"]:
            name, form = spec["mittal"]
            m = mh.loc[(mh["gpu"] == name) & (mh["form_factor"] == form)]
            item["monthly"] = {
                seg: {"months": g["month"].tolist(), "median": [_num(v) for v in g["median_usd_per_gpu_hour"]],
                      "providers": [None if pd.isna(v) else int(v) for v in g["n_providers"]]}
                for seg, g in m.sort_values("month").groupby("segment")
            }
        if spec["screener"]:
            c = cs.loc[cs["gpu"] == spec["screener"]].sort_values("date")
            c = c.dropna(subset=["price_usd_per_hour"])
            item["daily"] = {"dates": c["date"].tolist(), "price": [_num(v) for v in c["price_usd_per_hour"]],
                             "weekly": [bool(v) for v in c["weekly"]], "final": [bool(v) if not pd.isna(v) else None for v in c["final"]]}
        gpus.append(item)

    return {
        "captured_at_utc": run.get("started_at_utc"),
        "latest_week": weeks[-1],
        "sources": {k: {kk: v.get(kk) for kk in ("status", "rows", "observed_from", "observed_through")} for k, v in run["sources"].items()},
        "gpus": gpus,
        "weekly": table,
        "indices": build_indices(gd, mh),
    }
