"""store.py - Đọc/ghi dữ liệu cơ bản đã xử lý: data/fundamentals/<MÃ>.json"""
import hashlib
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "fundamentals"


def load(symbol: str, data_dir: Path = DATA_DIR) -> dict | None:
    path = Path(data_dir) / f"{symbol.upper()}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save(record: dict, data_dir: Path = DATA_DIR) -> None:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{record['symbol'].upper()}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # ghi nguyên tử, tránh hỏng file nếu bị ngắt giữa chừng


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
