import pytest
import numpy as np

def test_minimax_c_end_revenue_arithmetic():
    mau = 75e6 # 75M MAU
    conversion = 0.02 # 2.0%
    arppu_annual = 45.0 # $45/year
    
    paid_users = mau * conversion
    assert paid_users == 1.5e6, f"Expected 1.5M paid users, got {paid_users}"
    
    annual_c_revenue = paid_users * arppu_annual
    assert annual_c_revenue == 67.5e6, f"Expected $67.5M, got {annual_c_revenue}"
    assert annual_c_revenue / 1e6 == 67.5

def test_minimax_api_revenue_arithmetic():
    daily_tokens = 85e9 # 85B tokens/day
    days = 365
    price_per_million = 0.45 # $0.45 per 1M tokens
    
    annual_tokens = daily_tokens * days
    assert annual_tokens == 31.025e12, f"Expected 31.025T tokens, got {annual_tokens}"
    
    million_token_units = annual_tokens / 1e6
    assert million_token_units == 31.025e6, f"Expected 31.025M million-token units, got {million_token_units}"
    
    annual_api_revenue = million_token_units * price_per_million
    assert np.isclose(annual_api_revenue, 13.96125e6), f"Expected $13.96M, got {annual_api_revenue}"
    assert np.isclose(annual_api_revenue / 1e6, 13.96125)

def test_minimax_bottom_up_valuation_cascade():
    c_rev = 67.5e6
    api_rev = 13.96125e6
    ent_rev = 180.0e6
    
    rev_2030 = c_rev + api_rev + ent_rev
    assert np.isclose(rev_2030 / 1e6, 261.46125), f"Expected $261.46M, got {rev_2030/1e6}"
    
    rev_2026 = 180.0e6
    cagr_4y = ((rev_2030 / rev_2026) ** (1/4) - 1) * 100
    assert np.isclose(cagr_4y, 9.775, atol=0.01), f"Expected ~9.78% CAGR, got {cagr_4y}"
    
    exit_multiple = 8.0
    wacc = 0.12
    discount_factor = (1 + wacc) ** 4
    interim_cash_burn_pv = 0.400e9 # $400M
    market_ev = 12.75e9 # $12.75B
    
    ev_2030 = rev_2030 * exit_multiple
    pv_ev = ev_2030 / discount_factor
    fair_ev = pv_ev - interim_cash_burn_pv
    
    assert np.isclose(fair_ev / 1e9, 0.9293, atol=0.01), f"Expected Fair EV ~$0.93B, got {fair_ev/1e9}"
    
    val_gap = (fair_ev / market_ev - 1) * 100
    assert np.isclose(val_gap, -92.71, atol=0.1), f"Expected Valuation Gap ~ -92.7%, got {val_gap}"

def test_relative_spread_reversal():
    zai_market_ev = 57.61e9
    zai_rev_2030 = 2.136e9
    zai_ev_2030 = zai_rev_2030 * 8.0
    zai_pv_ev = zai_ev_2030 / (1.12 ** 4)
    zai_fair_ev = zai_pv_ev - 0.800e9
    zai_val_gap = (zai_fair_ev / zai_market_ev - 1) * 100
    
    mm_val_gap = -92.71
    spread = mm_val_gap - zai_val_gap
    
    assert zai_val_gap < -80.0
    assert spread < 0, f"Expected negative spread (MiniMax more overvalued), got {spread}"
    assert np.isclose(spread, -10.17, atol=0.5), f"Expected spread ~ -10.2 pp, got {spread}"
