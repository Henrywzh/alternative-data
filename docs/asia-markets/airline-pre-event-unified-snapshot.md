# Unified Airline Pre-Event Snapshot (1H2026)

Status: 2026-08-11.  This file documents the locked reconciliation view for
the mainland airline 1H2026 report cycle.  It is designed to stop the
research stack from presenting several different forecast layers as one
undifferentiated prediction.

## Artifact

- Data: `data/normalized/hk_transport/airline_pre_event_unified_snapshot.csv`
- Module: `src/hk_transport/sources/airline_pre_event_unified_snapshot.py`
- CLI: `run-airline-pre-event-unified-snapshot`
- Tests: `tests/test_hk_transport_airline_pre_event_unified_snapshot.py`

## What is reconciled

Each carrier row keeps four separate layers:

1. **v3 baseline**: locked FY2026 financial bridge, H1 ASK/RPK and flat-yield
   revenue anchor, with USD profit and consensus comparison.
2. **v4 live**: frozen H1 revenue/EPS decomposition using
   `ASK x LF_f x Yield_f`, bounded residual yield and the labelled Spring
   recovery overlay.
3. **Consensus sanity**: EPS, three-year H1 seasonality adjustment,
   consensus age/freshness and one-off flags.
4. **Decision evaluation**: the separate walk-forward integrated model's
   annualised profit, historical MAE-based uncertainty and Monte-Carlo beat
   probability.

The output includes `v3_model_version`, `v4_model_version` and
`decision_model_version` on every row.  Native RMB fields are labelled
`native_mn` or `rmb`; v3 profit fields are USD million to preserve the
existing locked-baseline convention.

## Vintage and lock rules

The current lock is 2026-08-11 with KPI data cutoff 2026-08-01.  The corrected
v4 snapshot is stored at:

`data/normalized/hk_transport/snapshots/airline_v4_pre_event_20260811.csv`

The prior 2026-08-10 v4 file remains unchanged as an audit reference.  The
unified artifact is a reconciliation view and does not overwrite any source
forecast layer.  Once the interim reports are published, actual KPI/profit,
guidance, analyst revisions and T+1/T+5 returns must be recorded in the H1
validation playbook and post-earnings tracker instead.

This artifact is not a historical strategy backtest: it contains no entry
price, exit price, transaction cost, borrow cost or realised P&L.
