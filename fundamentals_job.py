"""
fundamentals_job.py - Xử lý BCTC theo quý (chạy ngoài giờ giao dịch).

Đặt PDF vào data/bctc/<MÃ>/<YYYY>Q<n>.pdf (BCTC quý) và data/bctc/<MÃ>/<YYYY>FY.pdf (BCTC năm), rồi chạy:
  python fundamentals_job.py
Mỗi file: Gemini trích 2 lần -> kiểm tra (so sánh, đẳng thức kế toán, đơn vị) -> lưu data/fundamentals/<MÃ>.json
"""
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import llm  # đọc .env khi import
from fundamentals import store
from fundamentals.checks import run_checks
from fundamentals.ratios import compute_ratios
from fundamentals.schema import Extraction

BASE_DIR = Path(__file__).resolve().parent
BCTC_DIR = BASE_DIR / "data" / "bctc"
SUPPORTED_SECTORS = {"THEP", "BDS", "CHUNG"}
FILE_RE = re.compile(r"^(\d{4})(Q[1-4]|FY)\.pdf$", re.IGNORECASE)
logger = logging.getLogger("stock_agent.fundamentals")


def parse_sectors(value: str) -> dict[str, str]:
    out = {}
    for part in value.split(","):
        if ":" in part:
            sym, sector = part.split(":", 1)
            out[sym.strip().upper()] = sector.strip().upper()
    return out


def select_files(symbol_dir: Path):
    """Chọn BCTC quý mới nhất và BCTC năm (năm của quý - 1). Trả về (quý, năm, cảnh báo)."""
    quarters, annuals, warnings = [], {}, []
    for f in sorted(Path(symbol_dir).iterdir()):
        if not f.is_file():
            continue
        m = FILE_RE.match(f.name)
        if not m:
            warnings.append(f"Bỏ qua file sai quy ước tên (cần YYYYQn.pdf hoặc YYYYFY.pdf): {f.name}")
            continue
        year, kind = int(m.group(1)), m.group(2).upper()
        if kind == "FY":
            annuals[year] = (f, f"{year}FY")
        else:
            quarters.append(((year, int(kind[1])), (f, f"{year}{kind}")))
    if not quarters:
        return None, None, warnings
    (year, q), quarter = max(quarters)
    # Q4: lũy kế của quý 4 đã là cả năm, TTM không cần BCTC năm trước -> không tốn lượt gọi Gemini
    return quarter, (None if q == 4 else annuals.get(year - 1)), warnings


def process_file(path: Path, period: str, extract_fn):
    """Trích 2 lần + kiểm tra; lỗi thì trích lại 1 cặp. Trả về (status, Extraction | None, lỗi)."""
    errors = []
    try:
        for _ in range(2):
            a, b = extract_fn(path, period), extract_fn(path, period)
            ex, errors = run_checks(a, b, period)
            if ex is not None:
                return "OK", ex, []
            logger.warning("%s: kiểm tra không đạt: %s", path.name, "; ".join(errors[:3]))
    except Exception as exc:
        logger.error("%s: lỗi khi gọi Gemini: %s", path.name, exc)
        return "ERROR", None, [str(exc)]
    return "REJECTED", None, errors


def run_job(bctc_dir: Path, data_dir: Path, sectors: dict[str, str], extract_fn) -> int:
    had_error = False
    bctc_dir = Path(bctc_dir)
    if not bctc_dir.exists():
        logger.warning("Chưa có thư mục %s", bctc_dir)
        return 0

    for symbol_dir in sorted(p for p in bctc_dir.iterdir() if p.is_dir()):
        symbol = symbol_dir.name.upper()
        sector = sectors.get(symbol)
        if sector not in SUPPORTED_SECTORS:
            logger.info("%s: chưa hỗ trợ mẫu BCTC này, bỏ qua", symbol)
            continue

        quarter, annual, warnings = select_files(symbol_dir)
        for w in warnings:
            logger.warning("%s: %s", symbol, w)
        if quarter is None:
            logger.warning("%s: chưa có BCTC quý", symbol)
            continue

        rec = store.load(symbol, data_dir) or {"symbol": symbol, "sector": sector, "status": "NO_DATA",
                                                "sources": {}, "raw": {}}
        rec["sector"] = sector
        new_ok: dict[str, Extraction] = {}

        for kind, chosen in (("quarter", quarter), ("annual", annual)):
            if chosen is None:
                continue
            path, period = chosen
            digest = store.sha256_file(path)
            old = rec["sources"].get(path.name)
            if old and old["sha256"] == digest and old["status"] in ("OK", "REJECTED"):
                continue
            status, ex, errors = process_file(path, period, extract_fn)
            logger.info("%s %s: %s", symbol, path.name, status)
            if status == "ERROR":
                had_error = True
                continue
            rec["sources"][path.name] = {"sha256": digest, "status": status, "errors": errors,
                                         "period": period, "kind": kind}
            if status == "OK":
                new_ok[kind] = ex
                # Lưu mọi bản trích OK theo file, kể cả khi file còn lại lỗi -> lần chạy sau dùng lại được
                rec.setdefault("extractions", {})[path.name] = ex.model_dump(mode="json")

        def stored(chosen):
            """Bản trích OK đã lưu của đúng file (cùng mã băm) đang được chọn."""
            if chosen is None:
                return None
            src = rec["sources"].get(chosen[0].name)
            raw = rec.get("extractions", {}).get(chosen[0].name)
            if src and src["status"] == "OK" and raw and src["sha256"] == store.sha256_file(chosen[0]):
                return Extraction.model_validate(raw)
            return None

        q_period, a_period = quarter[1], annual[1] if annual else None
        q_ex = new_ok.get("quarter") or stored(quarter)
        a_ex = new_ok.get("annual") or stored(annual)

        # Đánh dấu khi BCTC quý đang chọn bị loại, để main/Analyst biết đang dùng số liệu kỳ cũ
        q_src = rec["sources"].get(quarter[0].name)
        if q_src and q_src["status"] == "REJECTED":
            rec["rejected_period"] = q_period
        elif q_ex is not None:
            rec.pop("rejected_period", None)

        if new_ok and q_ex is not None:
            rec.update({
                "status": "OK", "period": q_period, "period_end": q_ex.period_end,
                "annual_period": a_period if a_ex is not None else None,
                "ratios": compute_ratios(q_ex, a_ex, sector, q_period),
                "raw": {"quarter": q_ex.model_dump(mode="json"),
                        "annual": a_ex.model_dump(mode="json") if a_ex is not None else None},
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
        elif rec.get("status") != "OK":
            q_src = rec["sources"].get(quarter[0].name)
            rec["status"] = "REJECTED" if q_src and q_src["status"] == "REJECTED" else "NO_DATA"
        store.save(rec, data_dir)
    return 1 if had_error else 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from fundamentals.extract import extract_statement

    sectors = parse_sectors(os.getenv("SECTORS", "HPG:THEP,DXG:BDS,FPT:CHUNG,MWG:CHUNG,VNM:CHUNG"))
    sys.exit(run_job(BCTC_DIR, store.DATA_DIR, sectors, extract_statement))


if __name__ == "__main__":
    main()
