"""Tạo BCTC giả hợp lệ (mọi đẳng thức kế toán đều đúng) cho test."""
from fundamentals.schema import Extraction, LineItem, PERIOD_END, Unit

BS = {"BS100": 6e12, "BS200": 4e12, "BS270": 1e13, "BS310": 3e12, "BS330": 2e12, "BS300": 5e12,
      "BS400": 5e12, "BS440": 1e13, "BS411": 7e12, "BS140": 1e12, "BS312": 5e11, "BS332": 2e11,
      "BS320": 1e12, "BS338": 5e11, "BS429": 0.0}
IS = {"IS01": 2.1e12, "IS02": 1e11, "IS10": 2e12, "IS11": 1.5e12, "IS20": 5e11, "IS23": 5e10,
      "IS50": 3e11, "IS51": 6e10, "IS52": 0.0, "IS60": 2.4e11, "IS61": 2.2e11}
CF = {"CF20": 4e11}

_SCALE = {Unit.DONG: 1, Unit.NGHIN_DONG: 1e3, Unit.TRIEU_DONG: 1e6}


def make_extraction(period: str = "2026Q3", unit: Unit = Unit.DONG, period_end: str | None = None,
                    **overrides) -> Extraction:
    """overrides: CODE={"current": ...} để đổi cột, hoặc CODE=None để xóa mã."""
    s = 1 / _SCALE[unit]
    is_fy = period.endswith("FY")
    items = {}
    for code, v in BS.items():
        items[code] = {"current": v * s, "prior": v * 0.9 * s}
    for code, v in IS.items():
        items[code] = ({"current": v * 4 * s, "prior": v * 3.2 * s} if is_fy else
                       {"current": v * s, "prior": v * 0.8 * s, "ytd_current": v * 3 * s, "ytd_prior": v * 2.4 * s})
    for code, v in CF.items():
        items[code] = ({"current": v * s, "prior": v * 0.8 * s} if is_fy else
                       {"ytd_current": v * s, "ytd_prior": v * 0.8 * s})
    for code, ov in overrides.items():
        if ov is None:
            items.pop(code, None)
        else:
            items.setdefault(code, {}).update(ov)
    end = period_end or f"{period[:4]}-{PERIOD_END[period[4:]]}"
    return Extraction(unit=unit, period_end=end, consolidated=True,
                      items=[LineItem(code=c, page=1, **cols) for c, cols in items.items()])
