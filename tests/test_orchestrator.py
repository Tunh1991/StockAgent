import pytest
from pydantic import ValidationError

from agents import AnalystResult, CriticResult
from llm import LLMResult
from orchestrator import run_pipeline
from tests.fixtures import LEVELS, METRICS, make


class FakeGenerate:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.schemas, self.prompts = [], []

    def __call__(self, contents, schema, temperature=0.2):
        self.schemas.append(schema)
        self.prompts.append(contents)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return LLMResult(out, "fake", 0.1)


def analyst(**kw):
    return AnalystResult.model_validate(make(**kw))


def critic(verdict="GIU_NGUYEN", adj=0.0, args=None):
    return CriticResult(verdict=verdict, confidence_adjustment=adj, counter_arguments=args or [], reason="r")


BAD_TARGET = {"target_1": {"level": "TARGET", "price": 12.0}}


def json_error():
    try:
        AnalystResult.model_validate({})
    except ValidationError as e:
        return e


def run(gen):
    return run_pipeline("DXG", METRICS, LEVELS, gen)


def test_quan_sat_single_call():
    gen = FakeGenerate([analyst(signal="QUAN SAT")])
    r = run(gen)
    assert r["status"] == "OK" and len(gen.schemas) == 1 and r["critic"] is None


def test_mua_gom_with_critic_keep():
    gen = FakeGenerate([analyst(confidence=8), critic()])
    r = run(gen)
    assert len(gen.schemas) == 2 and gen.schemas[1] is CriticResult
    assert r["final"]["signal"] == "MUA GOM" and r["final"]["confidence_score"] == 8


def test_fix_once_then_pass():
    gen = FakeGenerate([analyst(signal="QUAN SAT", **BAD_TARGET), analyst(signal="QUAN SAT")])
    r = run(gen)
    assert r["validation"]["attempts"] == 2 and r["validation"]["passed"]
    assert "H1:" in gen.prompts[1]


def test_fix_fails_downgrades():
    gen = FakeGenerate([analyst(confidence=8, **BAD_TARGET), analyst(confidence=8, **BAD_TARGET)])
    r = run(gen)
    assert r["status"] == "VALIDATION_FAILED" and len(gen.schemas) == 2
    assert r["final"]["signal"] == "QUAN SAT" and r["final"]["confidence_score"] == 5.0
    assert any(f.startswith("Kế hoạch không qua kiểm tra") for f in r["final"]["red_flags"])


def test_fix_call_error_downgrades():
    gen = FakeGenerate([analyst(**BAD_TARGET), RuntimeError("down")])
    assert run(gen)["status"] == "VALIDATION_FAILED"


def test_invalid_json_triggers_fix():
    gen = FakeGenerate([json_error(), analyst(signal="QUAN SAT")])
    assert run(gen)["status"] == "OK"


def test_critic_ha_cap():
    gen = FakeGenerate([analyst(confidence=8), critic("HA_CAP", -2.0, ["Giá sát kháng cự"])])
    r = run(gen)
    assert r["final"]["signal"] == "QUAN SAT" and r["final"]["confidence_score"] == 6.0
    assert "Giá sát kháng cự" in r["final"]["red_flags"]


def test_critic_floor():
    gen = FakeGenerate([analyst(confidence=2), critic("GIAM_TIN_CAY", -5.0)])
    assert run(gen)["final"]["confidence_score"] == 1.0


def test_critic_error_downgrades():
    gen = FakeGenerate([analyst(), RuntimeError("down")])
    r = run(gen)
    assert r["status"] == "CRITIC_FAILED" and r["final"]["signal"] == "QUAN SAT"
    assert "Chưa được phản biện (Critic lỗi)" in r["final"]["red_flags"]


def test_analyst_failed():
    gen = FakeGenerate([RuntimeError("down")])
    r = run(gen)
    assert r["status"] == "ANALYST_FAILED" and len(gen.schemas) == 1


def test_max_three_calls():
    gen = FakeGenerate([analyst(**BAD_TARGET), analyst(), critic()])
    r = run(gen)
    assert len(gen.schemas) == 3 and r["status"] == "OK"


def test_symbol_from_code():
    gen = FakeGenerate([analyst(signal="QUAN SAT", symbol="XXX")])
    assert run(gen)["final"]["symbol"] == "DXG"


def test_warnings_merged():
    gen = FakeGenerate([analyst(signal="QUAN SAT", text="mục tiêu 12.75")])
    assert any(f.startswith("S3:") for f in run(gen)["final"]["red_flags"])


def test_confidence_rounded():
    gen = FakeGenerate([analyst(confidence=8.2), critic("GIAM_TIN_CAY", -1.5)])
    assert run(gen)["final"]["confidence_score"] == 6.7


def test_critic_numbers_checked():
    gen = FakeGenerate([analyst(confidence=8), critic("GIAM_TIN_CAY", -1.0, ["Dư địa tăng chỉ 3.3%"])])
    flags = run(gen)["final"]["red_flags"]
    assert any(f.startswith("S3:") and "3.3" in f for f in flags)


def test_m4_critic_error_caps_confidence():
    gen = FakeGenerate([analyst(confidence=9), RuntimeError("down")])
    assert run(gen)["final"]["confidence_score"] == 5.0
