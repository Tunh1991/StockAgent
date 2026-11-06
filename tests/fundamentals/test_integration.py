from datetime import date

from agents import build_analyst_prompt, build_critic_prompt, format_fundamentals_block
from orchestrator import run_pipeline
from tests.fixtures import LEVELS, METRICS, make
from tests.test_orchestrator import FakeGenerate, analyst
from validator import validate

TODAY = date(2026, 11, 6)
FUND = {"roe_ttm": 0.1234, "pe": 12.5, "period": "2026Q3", "period_end": "2026-09-30", "eps_ttm": None,
        "revenue_ttm": 8.5e12}


def test_block_none():
    assert "Chưa có dữ liệu cơ bản - cần kiểm tra BCTC" in format_fundamentals_block(None, TODAY)


def test_block_values():
    b = format_fundamentals_block(FUND, TODAY)
    assert "12.34%" in b and "12.5" in b and "2026Q3" in b and "eps_ttm" not in b
    assert "8,500.0 tỷ" in b or "8500.0 tỷ" in b


def test_block_stale():
    assert "Dữ liệu cơ bản đã cũ" in format_fundamentals_block({**FUND, "period_end": "2026-03-31"}, TODAY)


def test_analyst_prompt_includes_block():
    assert "DỮ LIỆU CƠ BẢN" in build_analyst_prompt("DXG", METRICS, LEVELS, FUND)
    assert "DỮ LIỆU CƠ BẢN" in build_critic_prompt("DXG", METRICS, LEVELS, make(), [], FUND)


def test_s3_real_roe_ok():
    r = validate(make(fundamental="ROE 12.34%, P/E 12.5, doanh thu 8500.0 tỷ"), LEVELS, METRICS, FUND)
    assert not [w for w in r.warnings if w.startswith("S3:")]


def test_s3_invented_roe_flagged():
    r = validate(make(fundamental="ROE 25.5%"), LEVELS, METRICS, FUND)
    assert any(w.startswith("S3:") and "25.5" in w for w in r.warnings)


def test_pipeline_passes_fundamentals():
    gen = FakeGenerate([analyst(signal="QUAN SAT")])
    run_pipeline("DXG", METRICS, LEVELS, gen, fundamentals=FUND)
    assert "DỮ LIỆU CƠ BẢN" in gen.prompts[0]
