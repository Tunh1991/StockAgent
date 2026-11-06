from types import SimpleNamespace

import requests

import data_loader


def fake_get(calls, payload=None, exc=None):
    def _get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params})
        if exc:
            raise exc
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    return _get


PAYLOAD = {"t": [1762300800, 1762128000, 1762214400], "o": [3, 1, 2], "h": [3, 1, 2],
           "l": [3, 1, 2], "c": [1700.5, 1690.1, 1695.2], "v": [10, 20, 30]}


def test_index_parsed(monkeypatch):
    monkeypatch.setattr(data_loader.requests, "get", fake_get([], PAYLOAD))
    df = data_loader.get_index_history("VNINDEX", 10)
    assert len(df) == 3 and {"date", "open", "high", "low", "close", "volume"} <= set(df.columns)
    assert list(df["close"]) == [1690.1, 1695.2, 1700.5]


def test_index_url(monkeypatch):
    calls = []
    monkeypatch.setattr(data_loader.requests, "get", fake_get(calls, PAYLOAD))
    data_loader.get_index_history()
    assert calls[0]["url"].endswith("/ohlcs/index") and calls[0]["params"]["symbol"] == "VNINDEX"


def test_index_error_empty(monkeypatch):
    monkeypatch.setattr(data_loader.requests, "get", fake_get([], exc=requests.ConnectionError("x")))
    assert data_loader.get_index_history().empty


def test_stock_unchanged(monkeypatch):
    calls = []
    monkeypatch.setattr(data_loader.requests, "get", fake_get(calls, PAYLOAD))
    df = data_loader.get_stock_history("hpg", 2)
    assert calls[0]["url"].endswith("/ohlcs/stock") and calls[0]["params"]["symbol"] == "HPG" and len(df) == 2
