from types import SimpleNamespace

import pytest
from google.genai import errors
from pydantic import ValidationError

import llm
from agents import CriticResult

OK = CriticResult(verdict="GIU_NGUYEN", confidence_adjustment=0, counter_arguments=[], reason="ok")


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "temperature": config.temperature})
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


@pytest.fixture
def fake(monkeypatch):
    def install(outcomes):
        models = FakeModels(outcomes)
        monkeypatch.setattr(llm, "get_client", lambda: SimpleNamespace(models=models))
        monkeypatch.setattr(llm, "GEMINI_RETRY_BASE_SEC", 0)
        monkeypatch.setattr(llm, "GEMINI_MAX_RETRIES", 2)
        monkeypatch.setattr(llm, "GEMINI_FALLBACK_MODELS", ["fb-1", "fb-2"])
        monkeypatch.setattr(llm.gemini_limiter, "min_interval", 0)
        return models
    return install


def err(code):
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": "x", "status": "X"}})


def resp(parsed=OK, text=""):
    return SimpleNamespace(parsed=parsed, text=text)


def test_retry_then_success(fake):
    models = fake([err(503), resp()])
    r = llm.generate("p", CriticResult)
    assert r.model == llm.GEMINI_MODEL and r.parsed == OK and len(models.calls) == 2


def test_fallback_on_404(fake):
    fake([err(404), resp()])
    assert llm.generate("p", CriticResult).model == "fb-1"


def test_all_fail_raises(fake):
    fake([err(503)] * 6)
    with pytest.raises(RuntimeError):
        llm.generate("p", CriticResult)


def test_invalid_json_raises(fake):
    fake([resp(parsed=None, text="{}")])
    with pytest.raises(ValidationError):
        llm.generate("p", CriticResult)


def test_temperature_passed(fake):
    models = fake([resp()])
    llm.generate("p", CriticResult, temperature=0)
    assert models.calls[0]["temperature"] == 0


def test_quota_429_skips_to_next_model(fake):
    models = fake([err(429), resp()])
    r = llm.generate("p", CriticResult)
    assert r.model == "fb-1" and len(models.calls) == 2
