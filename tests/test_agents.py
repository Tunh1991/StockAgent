import json

import pytest
from pydantic import ValidationError

from agents import (AnalystResult, CriticResult, TradePlan, build_analyst_prompt,
                    build_critic_prompt, build_fix_prompt)
from tests.fixtures import LEVELS, METRICS, make


def test_analyst_confidence_bounds():
    data = make(confidence=11)
    with pytest.raises(ValidationError):
        AnalystResult.model_validate(data)


def test_target2_defaults_none():
    plan = make()["plan"]
    plan.pop("target_2")
    assert TradePlan.model_validate(plan).target_2 is None


def test_critic_adjustment_positive_rejected():
    with pytest.raises(ValidationError):
        CriticResult(verdict="GIU_NGUYEN", confidence_adjustment=1.0, counter_arguments=[], reason="x")


def test_analyst_prompt_lists_levels_by_group():
    p = build_analyst_prompt("DXG", METRICS, LEVELS)
    for s in ("ATR_T2", "11.6", "entry", "stop", "target",
              "Chưa có dữ liệu cơ bản - cần kiểm tra BCTC", "chỉ được chọn mốc trong bảng"):
        assert s in p


def test_fix_prompt_contains_errors():
    errs = ["H1: target_1: mốc 'TARGET' không tồn tại", "H4: R:R = 0.56 < 1.5"]
    p = build_fix_prompt("BASE", make(), errs)
    assert "BASE" in p and all(e in p for e in errs)


def test_critic_prompt_role():
    analyst = make()
    p = build_critic_prompt("DXG", METRICS, LEVELS, analyst, ["S1: x"])
    assert "KHÔNG nên mua" in p
    assert json.dumps(analyst, ensure_ascii=False) in p
