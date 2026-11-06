import math

import numpy as np
import pandas as pd
import pytest

from indicators import compute_technical_indicators, price_levels


def make_df(close, high=None, low=None, volume=None):
    n = len(close)
    close = list(close)
    high = list(high) if high is not None else [c + 0.1 for c in close]
    low = list(low) if low is not None else [c - 0.1 for c in close]
    volume = list(volume) if volume is not None else [1000] * n
    return pd.DataFrame({"date": range(n), "open": close, "high": high, "low": low,
                         "close": close, "volume": volume})


def by_name(levels):
    return {lv.name: lv for lv in levels}


def test_atr_wilder():
    close = [10.0] * 30
    df = compute_technical_indicators(make_df(close, [c + 1 for c in close], [c - 1 for c in close]))
    assert df["ATR"].iloc[-1] == pytest.approx(2.0)
    assert math.isnan(df["ATR"].iloc[12])


def test_high_60_excludes_current():
    close = [9.0] * 71
    high = [10.0] * 70 + [20.0]
    df = compute_technical_indicators(make_df(close, high, [8.0] * 71))
    assert df["HIGH_60"].iloc[-1] == 10


def trending_df(n=130):
    close = [10 + 0.05 * i + 0.3 * np.sin(i / 3) for i in range(n)]
    return compute_technical_indicators(make_df(close, [c + 0.2 for c in close], [c - 0.2 for c in close]))


def test_groups_by_side_of_close():
    df = trending_df()
    c = df["close"].iloc[-1]
    levels = price_levels(df)
    for lv in levels:
        if "stop" in lv.groups:
            assert lv.price < c
        if "target" in lv.groups:
            assert lv.price > c
        if "entry" in lv.groups:
            assert lv.price <= c * 1.02
    assert "entry" in by_name(levels)["CLOSE"].groups


def test_target_has_atr_levels():
    df = trending_df()
    c = df["close"].iloc[-1]
    atr = df["ATR"].iloc[-1]
    lv = by_name(price_levels(df))
    assert "target" in lv["ATR_T2"].groups and "target" in lv["ATR_T3"].groups
    assert lv["ATR_T2"].price == round(c + 2 * atr, 2)
    assert lv["ATR_T3"].price == round(c + 3 * atr, 2)


def test_measured_move():
    df = trending_df()
    c = df["close"].iloc[-1]
    r, s = df["RESISTANCE"].iloc[-1], df["SUPPORT"].iloc[-1]
    mm = round(r + (r - s), 2)
    lv = by_name(price_levels(df))
    if mm > c:
        assert lv["MEASURED_MOVE"].price == mm
    else:
        assert "MEASURED_MOVE" not in lv


def test_nan_levels_dropped():
    df = trending_df(60)
    levels = price_levels(df)
    assert "HIGH_120" not in by_name(levels)
    assert all(not math.isnan(lv.price) for lv in levels)


def test_to_dict():
    lv = price_levels(trending_df())[0]
    d = lv.to_dict()
    assert set(d) == {"name", "price", "groups"} and isinstance(d["groups"], list)
