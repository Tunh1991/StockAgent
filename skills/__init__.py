"""skills - Skill chuyên gia cắm được. Bật qua biến môi trường SKILLS=trend_template,..."""
import importlib
import logging
import re

logger = logging.getLogger("stock_agent.skills")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def load_skills(names: list[str]) -> list:
    skills = []
    for raw in names:
        name = (raw or "").strip().lower()
        if not name:
            continue
        if not _NAME_RE.match(name):
            logger.warning("Tên skill không hợp lệ: %r", raw)
            continue
        try:
            module = importlib.import_module(f"skills.{name}.skill")
            skills.append(module.SKILL)
        except (ImportError, AttributeError) as exc:
            logger.warning("Không nạp được skill %r: %s", name, exc)
    return skills
