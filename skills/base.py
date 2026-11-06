"""
base.py - Giao diện chung cho skill chuyên gia.

Mỗi skill nằm trong skills/<tên>/ gồm:
  skill.py     lớp con của Skill, biến SKILL = <Lớp>(Path(__file__).parent)
  playbook.md  bộ tiêu chí tiếng Việt đưa vào prompt (sửa được, không cần sửa code)
  config.json  các ngưỡng (sửa được), gộp với DEFAULTS
Python tính mọi con số (evaluate); adjust chỉ được giảm độ tin cậy, không đổi tín hiệu.
"""
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger("stock_agent.skills")


@dataclass
class SkillContext:
    symbol: str
    df: pd.DataFrame | None
    metrics: dict
    fundamentals: dict | None = None
    index_df: pd.DataFrame | None = None


@dataclass
class Criterion:
    key: str
    label: str
    passed: bool | None  # None = không đủ dữ liệu
    detail: str


@dataclass
class SkillResult:
    name: str
    title: str
    facts: dict[str, float] = field(default_factory=dict)
    criteria: list[Criterion] = field(default_factory=list)

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.criteria if c.passed is True)

    @property
    def total(self) -> int:
        return len(self.criteria)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["passed_count"], d["total"] = self.passed_count, self.total
        return d


class Skill:
    name = "base"
    title = "Base"
    DEFAULTS: dict = {}

    def __init__(self, folder: Path):
        folder = Path(folder)
        self.config = self._load_config(folder / "config.json")
        pb = folder / "playbook.md"
        self.playbook = pb.read_text(encoding="utf-8").strip() if pb.exists() else ""

    def _load_config(self, path: Path) -> dict:
        config = dict(self.DEFAULTS)
        if not path.exists():
            return config
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("%s: không đọc được config.json (%s), dùng mặc định", self.name, exc)
            return config
        for key, value in raw.items():
            if key not in self.DEFAULTS:
                logger.warning("%s: bỏ qua khóa lạ trong config.json: %s", self.name, key)
                continue
            default = self.DEFAULTS[key]
            ok_type = isinstance(value, type(default)) and not isinstance(value, bool)
            if isinstance(default, float) and isinstance(value, int) and not isinstance(value, bool):
                ok_type = True
            if ok_type:
                config[key] = value
            else:
                logger.warning("%s: %s=%r sai kiểu, dùng mặc định %r", self.name, key, value, default)
        return config

    def evaluate(self, ctx: SkillContext) -> SkillResult:
        raise NotImplementedError

    def adjust(self, final: dict, result: SkillResult) -> list[str]:
        return []


_STATUS = {True: "[ĐẠT]", False: "[KHÔNG ĐẠT]", None: "[KHÔNG ĐỦ DỮ LIỆU]"}


def format_skill_block(result: SkillResult, playbook: str) -> str:
    lines = [f"PHƯƠNG PHÁP: {result.title} (đạt {result.passed_count}/{result.total} tiêu chí)"]
    lines += [f"- {_STATUS[c.passed]} {c.key} {c.label}: {c.detail}" for c in result.criteria]
    if playbook:
        lines += ["", playbook]
    return "\n".join(lines)


def run_skills(skills: list[Skill], ctx: SkillContext) -> list[tuple[Skill, SkillResult | None, str | None]]:
    out = []
    for skill in skills:
        try:
            out.append((skill, skill.evaluate(ctx), None))
        except Exception as exc:
            logger.exception("%s: skill %s lỗi", ctx.symbol, skill.name)
            out.append((skill, None, str(exc)))
    return out
