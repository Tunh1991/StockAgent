import json
import math
from datetime import date, timedelta

import pandas as pd

from skills.base import Criterion, SkillContext, SkillResult
from skills.trend_template.skill import SKILL, TrendTemplateSkill

START = date(2025, 1, 1)


def make_df(n, start, step, first_day=START, closes=None):
    close = closes if closes is not None else [start + step * i for i in range(n)]
    return pd.DataFrame({"date": [first_day + timedelta(days=i) for i in range(len(close))],
                         "open": close, "high": [c * 1.01 for c in close], "low": [c * 0.99 for c in close],
                         "close": close, "volume": [1000] * len(close)})


def evaluate(df, index=None, skill=SKILL):
    return skill.evaluate(SkillContext("DXG", df, {"close": float(df["close"].iloc[-1])}, None, index))


def by_key(result):
    return {c.key: c.passed for c in result.criteria}


def flat_index(n=300):
    return make_df(n, 1000, 0)


def test_uptrend_all_pass():
    r = evaluate(make_df(300, 10, 0.05), flat_index())
    assert r.passed_count == 8 and r.total == 8


def test_downtrend_fails_ma_structure():
    k = by_key(evaluate(make_df(300, 30, -0.05), flat_index()))
    assert k["T1"] is False and k["T2"] is False and k["T4"] is False and k["T5"] is False


def test_t3_ma200_flat_fails():
    closes = [10 + 0.05 * i for i in range(250)] + [12.0] * 50
    assert by_key(evaluate(make_df(0, 0, 0, closes=closes), flat_index()))["T3"] is False


def custom(tmp_path, **cfg):
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return TrendTemplateSkill(tmp_path)


def test_t6_t7_thresholds(tmp_path):
    closes = [10 + 0.05 * i for i in range(290)] + [0.9 * (10 + 0.05 * 289)] * 10
    df = make_df(0, 0, 0, closes=closes)
    assert by_key(evaluate(df, flat_index(), custom(tmp_path, max_below_high=0.05)))["T7"] is False
    assert by_key(evaluate(df, flat_index(), custom(tmp_path, min_above_low=10.0)))["T6"] is False


def test_t8_underperform_index():
    r = evaluate(make_df(300, 10, 0.05), make_df(300, 1000, 10))
    assert by_key(r)["T8"] is False and "index_ret_6m" in r.facts


def test_t8_uses_common_date():
    assert by_key(evaluate(make_df(300, 10, 0.05), flat_index(299)))["T8"] is not None


def test_t8_no_common_date():
    idx = make_df(300, 1000, 0, first_day=START + timedelta(days=1000))
    assert by_key(evaluate(make_df(300, 10, 0.05), idx))["T8"] is None


def test_short_history():
    k = by_key(evaluate(make_df(120, 10, 0.05), flat_index()))
    assert all(k[t] is None for t in ("T1", "T2", "T3", "T4", "T6", "T7", "T8")) and k["T5"] is not None


def test_no_index():
    assert by_key(evaluate(make_df(300, 10, 0.05), None))["T8"] is None


def test_facts_no_nan():
    r = evaluate(make_df(300, 10, 0.05), flat_index())
    assert r.facts and all(math.isfinite(v) for v in r.facts.values())


def test_unsorted_input_same_result():
    df = make_df(300, 10, 0.05)
    shuffled = df.sample(frac=1, random_state=1).reset_index(drop=True)
    a, b = evaluate(df, flat_index()), evaluate(shuffled, flat_index())
    assert a.facts == b.facts and by_key(a) == by_key(b)


def test_zero_low_no_crash():
    df = make_df(300, 10, 0.05)
    df.loc[100, "low"] = 0.0
    assert by_key(evaluate(df, flat_index()))["T6"] is None


def result_with(passed: int, total: int = 8) -> SkillResult:
    crit = [Criterion(f"T{i + 1}", "x", i < passed, "") for i in range(total)]
    return SkillResult("trend_template", "Trend Template", {}, crit)


def test_adjust_caps_buy():
    final = {"signal": "MUA GOM", "confidence_score": 8.0}
    notes = SKILL.adjust(final, result_with(5))
    assert final["confidence_score"] == 6.0 and len(notes) == 1 and "5/8" in notes[0]


def test_adjust_keeps_when_enough():
    final = {"signal": "MUA GOM", "confidence_score": 8.0}
    assert SKILL.adjust(final, result_with(6)) == [] and final["confidence_score"] == 8.0


def test_adjust_ignores_non_buy():
    final = {"signal": "QUAN SAT", "confidence_score": 8.0}
    assert SKILL.adjust(final, result_with(2)) == [] and final["confidence_score"] == 8.0


def test_adjust_never_raises_confidence():
    final = {"signal": "MUA GOM", "confidence_score": 4.0}
    SKILL.adjust(final, result_with(5))
    assert final == {"signal": "MUA GOM", "confidence_score": 4.0}


def test_playbook_loaded():
    assert "VN-Index" in SKILL.playbook and "T+2" in SKILL.playbook
