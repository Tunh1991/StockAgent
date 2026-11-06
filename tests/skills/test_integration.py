from agents import build_analyst_prompt, build_critic_prompt
from orchestrator import run_pipeline
from skills.base import Criterion, SkillResult, format_skill_block
from skills.trend_template.skill import SKILL
from tests.fixtures import LEVELS, METRICS, make
from tests.test_orchestrator import FakeGenerate, analyst, critic
from validator import validate

FACTS = {"ma150": 10.1, "ma200": 9.85, "pct_below_high": 0.035}


def result(passed=8, total=8):
    crit = [Criterion(f"T{i + 1}", "x", i < passed, "d") for i in range(total)]
    return SkillResult("trend_template", "Trend Template", dict(FACTS), crit)


def test_prompts_include_skill_block():
    block = format_skill_block(result(), SKILL.playbook)
    assert "PHƯƠNG PHÁP: Trend Template" in build_analyst_prompt("DXG", METRICS, LEVELS, skill_blocks=[block])
    assert "PHƯƠNG PHÁP: Trend Template" in build_critic_prompt("DXG", METRICS, LEVELS, make(), [],
                                                                skill_blocks=[block])


def s3(text, res=None):
    gen = FakeGenerate([analyst(signal="QUAN SAT", text=text)])
    rec = run_pipeline("DXG", METRICS, LEVELS, gen, skill_runs=[(SKILL, res or result(), None)])
    return [f for f in rec["final"]["red_flags"] if f.startswith("S3:")]


def test_s3_skill_facts_ok():
    assert s3("MA150 10.1, cách đỉnh 52 tuần 3.5%") == []


def test_s3_threshold_as_price_flagged():
    assert any("30.00" in f for f in s3("kháng cự 30.00"))


def test_s3_price_fact_x100_not_reference():
    assert any("985.0" in f for f in s3("mức 985.0"))


def test_s3_passed_count_not_reference():
    assert any("8.00" in f for f in s3("mục tiêu 8.00"))


def test_s3_invented_ma200_flagged():
    r = validate(make(text="MA200 15.75"), LEVELS, METRICS, extra_refs=FACTS)
    assert any(w.startswith("S3:") and "15.75" in w for w in r.warnings)


def test_pipeline_s3_uses_skill_facts():
    gen = FakeGenerate([analyst(signal="QUAN SAT", text="MA150 10.1")])
    rec = run_pipeline("DXG", METRICS, LEVELS, gen, skill_runs=[(SKILL, result(), None)])
    assert not [f for f in rec["final"]["red_flags"] if f.startswith("S3:")]
    assert "PHƯƠNG PHÁP: Trend Template" in gen.prompts[0]


def test_adjust_applied_after_critic():
    gen = FakeGenerate([analyst(confidence=9), critic()])
    rec = run_pipeline("DXG", METRICS, LEVELS, gen, skill_runs=[(SKILL, result(5), None)])
    assert rec["final"]["confidence_score"] == 6.0 and len(rec["skill_adjustments"]) == 1
    assert rec["skill_adjustments"][0] in rec["final"]["red_flags"]
    assert rec["skills"][0]["passed_count"] == 5


def test_skill_error_does_not_break():
    gen = FakeGenerate([analyst(signal="QUAN SAT")])
    rec = run_pipeline("DXG", METRICS, LEVELS, gen, skill_runs=[(SKILL, None, "boom")])
    assert rec["status"] == "OK" and rec["skills"] == [{"name": "trend_template", "error": "boom"}]


class BadAdjust:
    name = "bad"
    playbook = ""

    def adjust(self, final, res):
        raise RuntimeError("x")


class RaisingAdjust:
    name = "raiser"
    playbook = ""

    def adjust(self, final, res):
        final["confidence_score"] = 10.0
        final["signal"] = "MUA GOM"
        return ["tăng"]


def test_adjust_error_ignored():
    gen = FakeGenerate([analyst(signal="QUAN SAT")])
    rec = run_pipeline("DXG", METRICS, LEVELS, gen, skill_runs=[(BadAdjust(), result(), None)])
    assert rec["status"] == "OK"


def test_adjust_cannot_raise_or_change_signal():
    gen = FakeGenerate([analyst(signal="QUAN SAT", confidence=4)])
    rec = run_pipeline("DXG", METRICS, LEVELS, gen, skill_runs=[(RaisingAdjust(), result(), None)])
    assert rec["final"]["confidence_score"] == 4 and rec["final"]["signal"] == "QUAN SAT"


def test_s3_skill_thresholds_not_flagged():
    gen = FakeGenerate([analyst(signal="QUAN SAT", text="cần cao hơn đáy 30.00%, cách đỉnh không quá 25.00%")])
    rec = run_pipeline("DXG", METRICS, LEVELS, gen, skill_runs=[(SKILL, result(), None)])
    assert not [f for f in rec["final"]["red_flags"] if f.startswith("S3:")]
