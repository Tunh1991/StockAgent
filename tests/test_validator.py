from tests.fixtures import LEVELS, METRICS, make
from validator import validate


def codes(msgs, code):
    return [m for m in msgs if m.startswith(code + ":")]


def run(analysis, metrics=METRICS):
    return validate(analysis, LEVELS, metrics)


def test_valid_plan_passes():
    r = run(make())
    assert r.passed and r.errors == []


def test_dxg_invented_target_blocked():
    r = run(make(target_1={"level": "TARGET", "price": 12.0}))
    h1 = codes(r.errors, "H1")
    assert h1 and any("target_1" in e and "ATR_T2=11.6" in e for e in h1)


def test_h1_price_mismatch():
    assert codes(run(make(target_1={"level": "ATR_T3", "price": 12.1})).errors, "H1")


def test_h1_price_within_tolerance():
    assert not codes(run(make(target_1={"level": "ATR_T3", "price": 11.93})).errors, "H1")


def test_h2_order():
    r = run(make(entry_low={"level": "RESISTANCE_20", "price": 10.8},
                 entry_high={"level": "MA50", "price": 10.52}))
    assert codes(r.errors, "H2")


def test_h3_wrong_group():
    r = run(make(stop_loss={"level": "ATR_T2", "price": 11.6}))
    assert any("stop_loss" in e for e in codes(r.errors, "H3"))


def test_h4_rr():
    plan = dict(stop_loss={"level": "SUPPORT_20", "price": 9.37},
                target_1={"level": "ATR_T2", "price": 11.6}, target_2=None)
    assert codes(run(make(**plan)).errors, "H4")
    assert not codes(run(make(signal="QUAN SAT", **plan)).errors, "H4")


def test_h5_chase():
    r = run(make(entry_high={"level": "ATR_T2", "price": 11.6}, target_1={"level": "ATR_T3", "price": 11.9},
                 target_2=None))
    assert codes(r.errors, "H5")


def test_s1_rsi():
    r = run(make(), {**METRICS, "rsi": 80})
    assert codes(r.warnings, "S1") and r.passed


def test_s2_wide_stop():
    r = run(make(stop_loss={"level": "SUPPORT_20", "price": 9.37},
                 target_1={"level": "MEASURED_MOVE", "price": 12.23}, target_2=None))
    assert codes(r.warnings, "S2")


def test_s3_invented_number():
    text = "Giá 11.0 vượt 10.8 trong 20 phiên, khối lượng 31.62 triệu, gấp 2.78 lần, mục tiêu 12.75"
    s3 = codes(run(make(text=text)).warnings, "S3")
    assert len(s3) == 1 and "12.75" in s3[0]


def test_s3_comma_decimal():
    assert not codes(run(make(text="vượt 10,8")).warnings, "S3")


def test_s3_scans_red_flags():
    s3 = codes(run(make(red_flags=["chốt lời tại 13.5"])).warnings, "S3")
    assert s3 and "13.5" in s3[0]


def test_target2_optional():
    assert run(make(target_2=None)).passed


def test_level_name_normalized():
    assert run(make(entry_low={"level": " ma50", "price": 10.52})).passed


def test_rr_zero_risk_no_crash():
    mid = {"level": "MA50", "price": 10.52}
    r = run(make(stop_loss=mid, entry_low=mid, entry_high=mid))
    assert codes(r.errors, "H2")


def test_s3_negative_numbers_ok():
    assert not codes(run(make(text="MACD Signal -0.0665, giảm −0.0665")).warnings, "S3")


def test_s3_scans_fundamental_text_without_data():
    s3 = codes(run(make(fundamental="P/E 8.5 hấp dẫn")).warnings, "S3")
    assert s3 and "8.5" in s3[0]


def test_m1_thousands_separator_ok():
    fund = {"eps_ttm": 3450.0, "revenue_ttm": 8.5e12}
    r = validate(make(fundamental="EPS 3.450 đồng, EPS 3,450 đồng"), LEVELS, METRICS, fund)
    assert not codes(r.warnings, "S3")


def test_m1_thousands_separator_invented_flagged():
    r = validate(make(fundamental="EPS 9.999 đồng"), LEVELS, METRICS, {"eps_ttm": 3450.0})
    assert codes(r.warnings, "S3")


def test_m2_rounded_value_ok():
    assert not codes(run(make(text="MACD 0.04, Histogram 0.11, RSI 64.80")).warnings, "S3")


def test_m2_rounding_does_not_hide_invention():
    assert codes(run(make(text="mục tiêu 13.4")).warnings, "S3")
