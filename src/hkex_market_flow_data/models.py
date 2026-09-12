from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HkexDailyFlowObservation:
    trade_date: str
    southbound_buy_turnover_hkd_mln: float | None
    southbound_sell_turnover_hkd_mln: float | None
    southbound_net_inflow_hkd_mln: float | None
    northbound_buy_turnover_rmb_mln: float | None
    northbound_sell_turnover_rmb_mln: float | None
    northbound_net_inflow_rmb_mln: float | None
    total_market_turnover_hkd_mln: float | None
    southbound_turnover_share_pct: float | None
    short_selling_turnover_hkd_mln: float | None
    short_selling_ratio_pct: float | None
    fetched_at: str
    northbound_total_turnover_rmb_mln: float | None = None
    short_selling_turnover_rmb_mln: float | None = None
    short_selling_security_count: int | None = None
    short_selling_turnover_shares: float | None = None
    # The turnover columns on HKEX's Stock Connect short-selling file are
    # structurally zero across 2019-2026 -- the file publishes eligibility, not
    # realized shorting. "Remaining" (lendable inventory still available) is
    # the column that actually carries data, so it gets its own field rather
    # than being read into a turnover column it is not.
    short_selling_shares_available: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
