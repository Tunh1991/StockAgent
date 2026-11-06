from fundamentals.checks import check_required, normalize_units, run_checks
from fundamentals.schema import IDENTITIES, Unit
from tests.fundamentals.helpers import make_extraction


def codes(errs, code):
    return [e for e in errs if e.startswith(code + ":")]


def test_valid_passes():
    ex = make_extraction()
    norm, errs = run_checks(ex, ex, "2026Q3")
    assert errs == [] and norm is not None


def test_compare_tolerance():
    a = make_extraction()
    b = make_extraction(IS10={"current": 2e12 * 1.0005})
    assert run_checks(a, b, "2026Q3")[1] == []
    c = make_extraction(IS10={"current": 2e12 * 1.002})
    f1 = codes(run_checks(a, c, "2026Q3")[1], "F1")
    assert f1 and "IS10" in f1[0]


def test_compare_missing_code():
    assert codes(run_checks(make_extraction(), make_extraction(BS140=None), "2026Q3")[1], "F1")


def test_unit_trieu():
    ex = normalize_units(make_extraction(unit=Unit.TRIEU_DONG))
    assert ex.unit == Unit.DONG and ex.get("BS270").current == 1e13


def test_each_identity_detected():
    for lhs, _ in IDENTITIES:
        bad = make_extraction(**{lhs: {"current": 123.0}})
        f4 = codes(run_checks(bad, bad, "2026Q3")[1], "F4")
        assert any(lhs in e for e in f4), lhs


def test_cost_sign_normalized():
    ex = make_extraction(IS11={"current": -1.5e12})
    assert not codes(run_checks(ex, ex, "2026Q3")[1], "F4")


def test_missing_required():
    ex = make_extraction(BS270=None)
    assert codes(run_checks(ex, ex, "2026Q3")[1], "F3")
    ex2, errs = check_required(make_extraction(BS140=None))
    assert errs == [] and ex2.get("BS140").current == 0


def test_shares_out_of_range():
    ex = make_extraction(BS411={"current": 7e9})
    assert codes(run_checks(ex, ex, "2026Q3")[1], "F5")


def test_period_mismatch():
    ex = make_extraction(period_end="2026-06-30")
    assert codes(run_checks(ex, ex, "2026Q3")[1], "F6")


def test_m3_cost_sign_differs_between_runs():
    a = make_extraction(IS11={"current": -1.5e12})
    b = make_extraction()
    assert not codes(run_checks(a, b, "2026Q3")[1], "F1")
