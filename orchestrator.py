"""
orchestrator.py - Điều phối chuỗi agent cho một tín hiệu:
  1. Analyst (LLM) lập kế hoạch      2. Validator (Python) kiểm tra
  3. Analyst sửa lỗi tối đa 1 lần    4. Critic (LLM) phản biện khi MUA GOM
  5. Python ra quyết định cuối. Tối đa 3 lần gọi LLM.
"""
import logging
from typing import Callable

from pydantic import BaseModel, ValidationError

from agents import (AnalystResult, CriticResult, build_analyst_prompt, build_critic_prompt,
                    build_fix_prompt)
from skills.base import format_skill_block
from validator import BUY, check_text_numbers, validate

logger = logging.getLogger("stock_agent.orchestrator")

DOWNGRADE_SIGNAL = "QUAN SAT"
DOWNGRADE_MAX_CONFIDENCE = 5.0


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def _call(generate, prompt: str, schema: type[BaseModel]) -> dict:
    res = generate(prompt, schema)
    return {"result": res.parsed.model_dump(mode="json"), "model": res.model, "latency_sec": res.latency_sec}


def _apply_skill_adjustments(symbol: str, final: dict, ok_runs: list) -> list[str]:
    """Gọi adjust của từng skill; bất biến: không được tăng độ tin cậy, không được đổi tín hiệu."""
    notes = []
    for skill, res in ok_runs:
        before = (final["confidence_score"], final["signal"])
        try:
            got = list(skill.adjust(final, res) or [])
        except Exception:
            logger.exception("%s: adjust của skill %s lỗi", symbol, skill.name)
            final["confidence_score"], final["signal"] = before
            continue
        if final["confidence_score"] > before[0] or final["signal"] != before[1]:
            logger.error("%s: skill %s vi phạm bất biến adjust, khôi phục", symbol, skill.name)
            final["confidence_score"], final["signal"] = before
            continue
        notes += got
    return notes


def run_pipeline(symbol: str, metrics: dict, levels, generate: Callable, fundamentals: dict | None = None,
                 skill_runs: list | None = None) -> dict:
    skill_runs = skill_runs or []
    ok_runs = [(s, r) for s, r, _ in skill_runs if r is not None]
    skill_blocks = [format_skill_block(r, getattr(s, "playbook", "")) for s, r in ok_runs]
    # Số liệu hợp lệ cho S3 do từng skill khai báo: dạng gốc, và dạng % (chỉ khớp khi viết kèm "%")
    skill_refs, skill_pct = {}, []
    for s, r in ok_runs:
        try:
            plain, pct = s.reference_values(r)
        except Exception:
            logger.exception("%s: reference_values của skill %s lỗi", symbol, getattr(s, "name", "?"))
            continue
        skill_refs.update({f"{r.name}.{i}": v for i, v in enumerate(plain)})
        skill_pct += pct
    record = {"symbol": symbol, "status": "OK", "metrics": metrics,
              "levels": [lv.to_dict() for lv in levels], "final": None, "analyst": None,
              "validation": None, "critic": None,
              "skills": [r.to_dict() if r is not None else {"name": s.name, "error": e} for s, r, e in skill_runs],
              "skill_adjustments": []}
    base_prompt = build_analyst_prompt(symbol, metrics, levels, fundamentals, skill_blocks=skill_blocks)

    # 1. Analyst
    analyst, errors, warnings = None, [], []
    try:
        analyst = _call(generate, base_prompt, AnalystResult)
    except ValidationError as exc:
        errors = [f"JSON không đúng schema: {str(exc)[:300]}"]
    except Exception as exc:
        logger.error("%s: Analyst lỗi: %s", symbol, exc)
        record["status"] = "ANALYST_FAILED"
        return record

    # 2. Validator
    if analyst is not None:
        analyst["result"]["symbol"] = symbol
        v = validate(analyst["result"], levels, metrics, fundamentals, skill_refs, skill_pct)
        errors, warnings = v.errors, v.warnings
    attempts = 1

    # 3. Sửa lỗi 1 lần
    if errors:
        attempts = 2
        previous = analyst["result"] if analyst else None
        try:
            analyst = _call(generate, build_fix_prompt(base_prompt, previous, errors), AnalystResult)
            analyst["result"]["symbol"] = symbol
            v = validate(analyst["result"], levels, metrics, fundamentals, skill_refs, skill_pct)
            errors, warnings = v.errors, v.warnings
        except Exception as exc:
            logger.warning("%s: lần sửa lỗi thất bại: %s", symbol, exc)
            errors = errors + [f"Lần sửa lỗi thất bại: {str(exc)[:200]}"]

    if analyst is None:  # JSON sai ở lần 1 và lần sửa cũng thất bại: không có kết quả nào dùng được
        record["status"] = "ANALYST_FAILED"
        record["validation"] = {"passed": False, "errors": errors, "warnings": [], "attempts": attempts}
        return record

    result = analyst["result"]
    record["analyst"] = analyst
    record["validation"] = {"passed": not errors, "errors": errors, "warnings": warnings, "attempts": attempts}

    final = {k: result[k] for k in ("signal", "confidence_score", "plan", "orderflow_analysis",
                                     "fundamental_analysis")}
    final["symbol"] = symbol
    red_flags = list(result.get("red_flags") or []) + warnings

    if errors:
        record["status"] = "VALIDATION_FAILED"
        final["signal"] = DOWNGRADE_SIGNAL
        final["confidence_score"] = min(final["confidence_score"], DOWNGRADE_MAX_CONFIDENCE)
        red_flags.append("Kế hoạch không qua kiểm tra: " + "; ".join(errors))

    # 4. Critic (chỉ khi MUA GOM)
    elif final["signal"] == BUY:
        try:
            critic = _call(generate, build_critic_prompt(symbol, metrics, levels, result, warnings,
                                                            fundamentals, skill_blocks=skill_blocks), CriticResult)
            record["critic"] = critic
            c = critic["result"]
            # 5. Quyết định cuối: Critic chỉ được giảm, không được tăng
            final["confidence_score"] = round(
                max(1.0, final["confidence_score"] + min(0.0, c["confidence_adjustment"])), 2)
            if c["verdict"] == "HA_CAP":
                final["signal"] = DOWNGRADE_SIGNAL
            red_flags += c["counter_arguments"]
            red_flags += check_text_numbers(c["counter_arguments"] + [c.get("reason", "")],
                                            metrics, levels, fundamentals, skill_refs, skill_pct)
        except Exception as exc:
            logger.warning("%s: Critic lỗi: %s", symbol, exc)
            record["status"] = "CRITIC_FAILED"
            final["signal"] = DOWNGRADE_SIGNAL
            final["confidence_score"] = min(final["confidence_score"], DOWNGRADE_MAX_CONFIDENCE)
            red_flags.append("Chưa được phản biện (Critic lỗi)")

    # 6. Luật điều chỉnh của skill (sau mọi luật hạ cấp/giới hạn ở trên)
    record["skill_adjustments"] = _apply_skill_adjustments(symbol, final, ok_runs)
    red_flags += record["skill_adjustments"]

    final["red_flags"] = _dedupe(red_flags)
    record["final"] = final
    return record
