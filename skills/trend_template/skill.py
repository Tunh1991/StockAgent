"""
Trend Template - bộ 8 tiêu chí xác định cổ phiếu đang trong xu hướng tăng (giai đoạn 2).
T8 là bản điều chỉnh: so lợi nhuận 6 tháng với VN-Index thay cho xếp hạng RS toàn thị trường.
"""
from pathlib import Path

import pandas as pd

from skills.base import Criterion, Skill, SkillContext, SkillResult

BUY = "MUA GOM"


def _f(x: float) -> str:
    return f"{x:.2f}"


def _pct(x: float) -> str:
    return f"{x * 100:.2f}%"


class TrendTemplateSkill(Skill):
    name = "trend_template"
    title = "Trend Template"
    DEFAULTS = {"ma200_rising_days": 22, "min_above_low": 0.30, "max_below_high": 0.25,
                "week52_bars": 250, "rs_lookback": 126, "min_pass": 6, "confidence_cap": 6.0}

    def evaluate(self, ctx: SkillContext) -> SkillResult:
        cfg = self.config
        df = (ctx.df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True))
        close = df["close"].astype(float)
        n = len(df)
        c = float(close.iloc[-1])

        def ma(window: int, back: int = 0):
            return float(close.iloc[n - back - window:n - back].mean()) if n - back >= window else None

        ma50, ma150, ma200 = ma(50), ma(150), ma(200)
        ma200_prev = ma(200, cfg["ma200_rising_days"])
        wb = cfg["week52_bars"]
        high52 = float(df["high"].iloc[-wb:].max()) if n >= wb else None
        low52 = float(df["low"].iloc[-wb:].min()) if n >= wb else None
        ret, idx_ret = self._returns(df, ctx.index_df, cfg["rs_lookback"])

        crit = []

        def add(key, label, ok, detail):
            crit.append(Criterion(key, label, None if ok is None else bool(ok), detail))

        if None in (ma150, ma200):
            add("T1", "Giá > MA150 và Giá > MA200", None, "không đủ 200 phiên")
            add("T2", "MA150 > MA200", None, "không đủ 200 phiên")
        else:
            add("T1", "Giá > MA150 và Giá > MA200", c > ma150 and c > ma200, f"{_f(c)} so với {_f(ma150)} và {_f(ma200)}")
            add("T2", "MA150 > MA200", ma150 > ma200, f"{_f(ma150)} so với {_f(ma200)}")

        days = cfg["ma200_rising_days"]
        if None in (ma200, ma200_prev):
            add("T3", f"MA200 đi lên {days} phiên", None, f"không đủ {200 + days} phiên")
        else:
            add("T3", f"MA200 đi lên {days} phiên", ma200 > ma200_prev,
                f"MA200 {_f(ma200)} so với {days} phiên trước {_f(ma200_prev)}")

        if None in (ma50, ma150, ma200):
            add("T4", "MA50 > MA150 và MA50 > MA200", None, "không đủ 200 phiên")
        else:
            add("T4", "MA50 > MA150 và MA50 > MA200", ma50 > ma150 and ma50 > ma200,
                f"{_f(ma50)} so với {_f(ma150)} và {_f(ma200)}")

        if ma50 is None:
            add("T5", "Giá > MA50", None, "không đủ 50 phiên")
        else:
            add("T5", "Giá > MA50", c > ma50, f"{_f(c)} so với {_f(ma50)}")

        lo = cfg["min_above_low"]
        if low52 is None or low52 <= 0:
            add("T6", f"Giá cao hơn đáy 52 tuần ít nhất {_pct(lo)}", None, "không đủ dữ liệu 52 tuần")
        else:
            add("T6", f"Giá cao hơn đáy 52 tuần ít nhất {_pct(lo)}", c >= low52 * (1 + lo),
                f"giá {_f(c)}, đáy 52 tuần {_f(low52)}, cao hơn {_pct(c / low52 - 1)}")

        hi = cfg["max_below_high"]
        if high52 is None or high52 <= 0:
            add("T7", f"Giá cách đỉnh 52 tuần không quá {_pct(hi)}", None, "không đủ dữ liệu 52 tuần")
        else:
            add("T7", f"Giá cách đỉnh 52 tuần không quá {_pct(hi)}", c >= high52 * (1 - hi),
                f"giá {_f(c)}, đỉnh 52 tuần {_f(high52)}, thấp hơn {_pct(1 - c / high52)}")

        lb = cfg["rs_lookback"]
        if ret is None or idx_ret is None:
            add("T8", f"Lợi nhuận {lb} phiên cao hơn VN-Index", None, "không đủ dữ liệu của mã hoặc VN-Index")
        else:
            add("T8", f"Lợi nhuận {lb} phiên cao hơn VN-Index", ret > idx_ret,
                f"mã {_pct(ret)} so với VN-Index {_pct(idx_ret)}")

        facts = {"ma150": ma150, "ma200": ma200, "ma200_prev": ma200_prev, "high_52w": high52, "low_52w": low52}
        facts = {k: round(v, 2) for k, v in facts.items() if v is not None}
        if high52:
            facts["pct_below_high"] = round(1 - c / high52, 4)
        if low52 and low52 > 0:
            facts["pct_above_low"] = round(c / low52 - 1, 4)
        if ret is not None and idx_ret is not None:
            facts["ret_6m"], facts["index_ret_6m"] = round(ret, 4), round(idx_ret, 4)
        result = SkillResult(self.name, self.title, facts, crit)
        facts["passed_count"] = result.passed_count
        return result

    @staticmethod
    def _returns(df: pd.DataFrame, index_df: pd.DataFrame | None, lookback: int):
        """Lợi nhuận `lookback` phiên của mã và VN-Index, tính trên các phiên chung (căn theo ngày)."""
        if index_df is None or len(index_df) == 0:
            return None, None
        idx = index_df.sort_values("date").drop_duplicates("date", keep="last")[["date", "close"]]
        merged = df[["date", "close"]].merge(idx, on="date", suffixes=("", "_idx"))
        if len(merged) < lookback + 1:
            return None, None
        s, i = merged["close"].astype(float), merged["close_idx"].astype(float)
        s0, i0 = s.iloc[-1 - lookback], i.iloc[-1 - lookback]
        if s0 <= 0 or i0 <= 0:
            return None, None
        return float(s.iloc[-1] / s0 - 1), float(i.iloc[-1] / i0 - 1)

    def adjust(self, final: dict, result: SkillResult) -> list[str]:
        min_pass, cap = self.config["min_pass"], float(self.config["confidence_cap"])
        if final.get("signal") != BUY or result.passed_count >= min_pass:
            return []
        if final["confidence_score"] > cap:
            final["confidence_score"] = cap
        return [f"Trend Template chỉ đạt {result.passed_count}/{result.total} tiêu chí "
                f"(cần ≥ {min_pass}): độ tin cậy tối đa {cap}"]


SKILL = TrendTemplateSkill(Path(__file__).parent)
