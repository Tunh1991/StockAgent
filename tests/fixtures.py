"""Fixture DXG (lần chạy thật 06/11/2026, giả sử ATR = 0.3) dùng chung cho các test."""
import copy

from indicators import PriceLevel

C = 11.0
METRICS = {"date": "2026-11-06", "close": 11.0, "ma20": 10.23, "ma50": 10.52, "ema20": 10.29,
           "rsi": 64.8, "rsi_state": "TRUNG TINH", "vol_spike_ratio": 2.78, "volume": 31627400,
           "vol_projected": 31627400, "vol_ma20": 11365770, "support": 9.37, "resistance": 10.8,
           "macd": 0.0422, "macd_signal": -0.0665, "macd_hist": 0.1086,
           "trigger_reasons": ["Vượt đỉnh kháng cự 20 phiên"]}
LEVELS = [PriceLevel("CLOSE", 11.0, ("entry",)), PriceLevel("MA20", 10.23, ("entry", "stop")),
          PriceLevel("EMA20", 10.29, ("entry", "stop")), PriceLevel("MA50", 10.52, ("entry", "stop")),
          PriceLevel("SUPPORT_20", 9.37, ("entry", "stop")), PriceLevel("RESISTANCE_20", 10.8, ("entry",)),
          PriceLevel("ATR_STOP", 10.55, ("stop",)), PriceLevel("ATR_T2", 11.6, ("target",)),
          PriceLevel("ATR_T3", 11.9, ("target",)), PriceLevel("MEASURED_MOVE", 12.23, ("target",))]
VALID_PLAN = {"entry_low": {"level": "MA50", "price": 10.52},
              "entry_high": {"level": "RESISTANCE_20", "price": 10.8},
              "stop_loss": {"level": "EMA20", "price": 10.29},
              "target_1": {"level": "ATR_T3", "price": 11.9},
              "target_2": {"level": "MEASURED_MOVE", "price": 12.23}, "t_plus_risk": "Rủi ro T+2"}


def make(signal="MUA GOM", text="", red_flags=None, confidence=8.0, symbol="DXG",
         fundamental="Chưa có dữ liệu cơ bản - cần kiểm tra BCTC", **plan_overrides) -> dict:
    plan = copy.deepcopy(VALID_PLAN)
    plan.update(plan_overrides)
    return {"symbol": symbol, "signal": signal, "confidence_score": confidence,
            "orderflow_analysis": text, "fundamental_analysis": fundamental,
            "red_flags": list(red_flags or []), "plan": plan}
