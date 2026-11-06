import pytest

from fundamentals.ratios import compute_ratios, valuation
from tests.fundamentals.helpers import make_extraction


def q(**kw):
    return make_extraction("2026Q3", **kw)


def fy(**kw):
    return make_extraction("2025FY", **kw)


def test_ttm_q3_with_annual():
    r = compute_ratios(q(IS61={"ytd_current": 6e11, "ytd_prior": 5e11}), fy(IS61={"current": 8e11}), "CHUNG", "2026Q3")
    assert r["npat_parent_ttm"] == 9e11
    assert r["eps_ttm"] == pytest.approx(9e11 / 7e8)


def test_ttm_q4_without_annual():
    ex = make_extraction("2026Q4", IS61={"ytd_current": 9e11})
    assert compute_ratios(ex, None, "CHUNG", "2026Q4")["npat_parent_ttm"] == 9e11


def test_q3_without_annual():
    r = compute_ratios(q(), None, "CHUNG", "2026Q3")
    for k in ("eps_ttm", "roe_ttm", "roa_ttm", "revenue_ttm"):
        assert r[k] is None
    assert r["gross_margin_q"] == 0.25


def test_roe_average_equity():
    r = compute_ratios(q(BS400={"current": 5e12, "prior": 4e12}), fy(), "CHUNG", "2026Q3")
    assert r["roe_ttm"] == round(r["npat_parent_ttm"] / 4.5e12, 4)


def test_yoy():
    assert compute_ratios(q(IS10={"current": 2e12, "prior": 1.6e12}), None, "CHUNG", "2026Q3")["revenue_yoy_q"] == 0.25
    assert compute_ratios(q(IS10={"prior": 0.0}), None, "CHUNG", "2026Q3")["revenue_yoy_q"] is None


def test_interest_coverage_none_when_no_interest():
    assert compute_ratios(q(IS23={"current": 0.0}), None, "CHUNG", "2026Q3")["interest_coverage"] is None


def test_bds_keys():
    keys = {"customer_advances_to_equity", "customer_advances_change", "inventory_to_assets"}
    assert keys <= set(compute_ratios(q(), None, "BDS", "2026Q3"))
    assert not keys & set(compute_ratios(q(), None, "CHUNG", "2026Q3"))


def test_thep_inventory_days():
    ex = q(IS11={"ytd_current": 4.5e12, "ytd_prior": 3.5e12}, BS140={"current": 1.2e12, "prior": 1.2e12})
    r = compute_ratios(ex, fy(IS11={"current": 5e12}), "THEP", "2026Q3")
    assert r["inventory_days"] == pytest.approx(73.0)
    assert "gross_margin_change_yoy" in r


def test_zero_revenue():
    zero = {"current": 0.0, "prior": 0.0, "ytd_current": 0.0, "ytd_prior": 0.0}
    r = compute_ratios(q(IS10=zero), fy(), "BDS", "2026Q3")
    assert r["gross_margin_q"] is None and r["net_margin_q"] is None


def test_negative_equity():
    r = compute_ratios(q(BS400={"current": -1e12, "prior": -1e12}), fy(), "CHUNG", "2026Q3")
    assert r["roe_ttm"] is None and r["debt_to_equity"] is None and r["bvps"] is None
    assert valuation(r, 10.0)["pb"] is None


def test_valuation():
    v = valuation({"eps_ttm": 1000, "bvps": 10000}, 15.0)
    assert v["pe"] == 15.0 and v["pb"] == 1.5
    v2 = valuation({"eps_ttm": -5, "bvps": 10000}, 15.0)
    assert v2["pe"] is None and v2["pe_note"] == "EPS ≤ 0, P/E không có ý nghĩa"
