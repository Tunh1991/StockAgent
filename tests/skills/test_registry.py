import json

import pytest

from skills import load_skills
from skills.base import Criterion, Skill, SkillContext, SkillResult, format_skill_block, run_skills


class DummySkill(Skill):
    name = "dummy"
    title = "Dummy"
    DEFAULTS = {"min_pass": 6, "cap": 6.0}

    def evaluate(self, ctx):
        return SkillResult(self.name, self.title, {}, [])


class BoomSkill(DummySkill):
    def evaluate(self, ctx):
        raise ValueError("x")


def folder(tmp_path, config=None, playbook=None):
    if config is not None:
        (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    if playbook is not None:
        (tmp_path / "playbook.md").write_text(playbook, encoding="utf-8")
    return tmp_path


def test_config_merge_defaults(tmp_path):
    assert DummySkill(folder(tmp_path, {"cap": 5.0})).config == {"min_pass": 6, "cap": 5.0}


def test_config_bad_type_uses_default(tmp_path):
    assert DummySkill(folder(tmp_path, {"min_pass": "6"})).config["min_pass"] == 6


def test_config_int_for_float_ok(tmp_path):
    assert DummySkill(folder(tmp_path, {"cap": 5})).config["cap"] == 5


def test_config_missing_file(tmp_path):
    s = DummySkill(tmp_path)
    assert s.config == DummySkill.DEFAULTS and s.playbook == ""


def test_format_block():
    r = SkillResult("dummy", "Dummy", {}, [Criterion("A", "a", True, "1 > 0"), Criterion("B", "b", False, "0 > 1"),
                                           Criterion("C", "c", None, "thiếu")])
    b = format_skill_block(r, "PLAYBOOK TEXT")
    for s in ("PHƯƠNG PHÁP: Dummy", "(đạt 1/3 tiêu chí)", "[ĐẠT]", "[KHÔNG ĐẠT]", "[KHÔNG ĐỦ DỮ LIỆU]", "PLAYBOOK TEXT"):
        assert s in b


def test_run_skills_catches_error(tmp_path):
    s = BoomSkill(tmp_path)
    assert run_skills([s], SkillContext("DXG", None, {})) == [(s, None, "x")]


def test_load_skills_unknown_skipped():
    assert load_skills(["khong_ton_tai", ""]) == []


def test_load_skills_normalizes_names():
    pytest.importorskip("skills.trend_template.skill")
    skills = load_skills([" Trend_Template "])
    assert len(skills) == 1 and skills[0].name == "trend_template"
