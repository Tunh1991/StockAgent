import json
from datetime import date

import pandas as pd
import pytest

import main


def fake_history(symbol, count=160):
    n = 160
    close = [10.0 + 0.01 * (i % 3) for i in range(n - 1)] + [11.0]
    return pd.DataFrame({"date": [date(2026, 1, 1)] * n, "open": close, "high": [c + 0.1 for c in close],
                         "low": [c - 0.1 for c in close], "close": close, "volume": [1000] * (n - 1) + [3000]})


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "get_stock_history", fake_history)
    monkeypatch.setattr(main, "SIGNALS_FILE", tmp_path / "signals.jsonl")
    monkeypatch.setattr(main.data_limiter, "min_interval", 0)
    calls = {}

    def install(status):
        def fake_pipeline(symbol, metrics, levels, generate, fundamentals=None):
            calls["levels"] = levels
            return {"symbol": symbol, "status": status, "final": {"signal": "QUAN SAT"}}
        monkeypatch.setattr(main, "run_pipeline", fake_pipeline)
        return calls
    return install, tmp_path / "signals.jsonl"


def run(analyzed):
    main.run_scan(["DXG"], analyzed, dry_run=False, force=False)


def test_ok_record_saved_and_marked(env):
    install, path = env
    calls = install("OK")
    analyzed = set()
    run(analyzed)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and "time" in json.loads(lines[0])
    assert len(analyzed) == 1 and calls["levels"]


def test_analyst_failed_not_saved(env):
    install, path = env
    install("ANALYST_FAILED")
    analyzed = set()
    run(analyzed)
    assert not path.exists() and not analyzed


def test_validation_failed_saved(env):
    install, path = env
    install("VALIDATION_FAILED")
    analyzed = set()
    run(analyzed)
    assert path.exists() and len(analyzed) == 1


def test_fundamentals_loaded_and_valued(env, monkeypatch):
    install, _ = env
    seen = {}

    def fake_pipeline(symbol, metrics, levels, generate, fundamentals=None):
        seen["f"] = fundamentals
        return {"symbol": symbol, "status": "OK", "final": {}}
    monkeypatch.setattr(main, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(main.store, "load", lambda s: {"status": "OK", "period": "2026Q3",
                                                      "period_end": "2026-09-30",
                                                      "ratios": {"eps_ttm": 1000.0, "bvps": 10000.0}})
    run(set())
    assert seen["f"]["pe"] == 11.0 and seen["f"]["period"] == "2026Q3"


def test_no_fundamentals_file(env, monkeypatch):
    install, _ = env
    seen = {}

    def fake_pipeline(symbol, metrics, levels, generate, fundamentals=None):
        seen["f"] = fundamentals
        return {"symbol": symbol, "status": "OK", "final": {}}
    monkeypatch.setattr(main, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(main.store, "load", lambda s: None)
    run(set())
    assert seen["f"] is None
