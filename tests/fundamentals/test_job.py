import fundamentals_job as job
from fundamentals import store
from tests.fundamentals.helpers import make_extraction

SECTORS = {"DXG": "BDS", "HPG": "THEP"}


class FakeExtract:
    """outputs[period] = danh sách kết quả lần lượt (Extraction hoặc Exception); hết thì trả bản hợp lệ."""

    def __init__(self, outputs=None):
        self.outputs = {k: list(v) for k, v in (outputs or {}).items()}
        self.calls = {}

    def __call__(self, path, period):
        self.calls[period] = self.calls.get(period, 0) + 1
        queue = self.outputs.get(period)
        out = queue.pop(0) if queue else make_extraction(period)
        if isinstance(out, Exception):
            raise out
        return out

    @property
    def total(self):
        return sum(self.calls.values())


def setup(tmp_path, names=("2026Q3.pdf", "2025FY.pdf"), symbol="DXG"):
    bctc = tmp_path / "bctc"
    d = bctc / symbol
    d.mkdir(parents=True)
    for n in names:
        (d / n).write_bytes(n.encode())
    return bctc, tmp_path / "fundamentals"


def test_new_files_ok(tmp_path):
    bctc, data = setup(tmp_path)
    fx = FakeExtract()
    assert job.run_job(bctc, data, SECTORS, fx) == 0
    rec = store.load("DXG", data)
    assert rec["status"] == "OK" and rec["period"] == "2026Q3" and rec["annual_period"] == "2025FY"
    assert "customer_advances_to_equity" in rec["ratios"] and fx.total == 4


def test_rerun_skips(tmp_path):
    bctc, data = setup(tmp_path)
    job.run_job(bctc, data, SECTORS, FakeExtract())
    fx = FakeExtract()
    job.run_job(bctc, data, SECTORS, fx)
    assert fx.total == 0


def test_filename_case_insensitive(tmp_path):
    bctc, _ = setup(tmp_path, names=("2026q3.PDF",))
    quarter, annual, _ = job.select_files(bctc / "DXG")
    assert quarter[1] == "2026Q3" and annual is None


def test_bad_filename_warned(tmp_path):
    bctc, _ = setup(tmp_path, names=("bctc_q3.pdf", "2026Q3.pdf"))
    _, _, warnings = job.select_files(bctc / "DXG")
    assert any("bctc_q3.pdf" in w for w in warnings)


def test_select_latest_quarter_and_prior_year(tmp_path):
    bctc, _ = setup(tmp_path, names=("2026Q2.pdf", "2026Q3.pdf", "2024FY.pdf", "2025FY.pdf"))
    quarter, annual, _ = job.select_files(bctc / "DXG")
    assert quarter[1] == "2026Q3" and annual[1] == "2025FY"
    (bctc / "DXG" / "2025FY.pdf").unlink()
    assert job.select_files(bctc / "DXG")[1] is None


def test_retry_pair_then_ok(tmp_path):
    bctc, data = setup(tmp_path)
    off = make_extraction("2026Q3", IS10={"current": 2e12 * 1.002})
    fx = FakeExtract({"2026Q3": [make_extraction("2026Q3"), off]})
    job.run_job(bctc, data, SECTORS, fx)
    assert store.load("DXG", data)["status"] == "OK" and fx.calls["2026Q3"] == 4


def test_rejected_keeps_old(tmp_path):
    bctc, data = setup(tmp_path)
    job.run_job(bctc, data, SECTORS, FakeExtract())
    old = store.load("DXG", data)["ratios"]
    (bctc / "DXG" / "2026Q3.pdf").write_bytes(b"new content")
    bad = make_extraction("2026Q3", IS20={"current": 1.0})
    job.run_job(bctc, data, SECTORS, FakeExtract({"2026Q3": [bad] * 4}))
    rec = store.load("DXG", data)
    assert rec["sources"]["2026Q3.pdf"]["status"] == "REJECTED" and rec["ratios"] == old


def test_gemini_error_not_recorded(tmp_path):
    bctc, data = setup(tmp_path)
    code = job.run_job(bctc, data, SECTORS, FakeExtract({"2026Q3": [RuntimeError("down")]}))
    rec = store.load("DXG", data)
    assert code == 1 and "2026Q3.pdf" not in rec["sources"]


def test_unsupported_sector_skipped(tmp_path):
    bctc, data = setup(tmp_path, symbol="VCB")
    fx = FakeExtract()
    job.run_job(bctc, data, SECTORS, fx)
    assert fx.total == 0 and store.load("VCB", data) is None


def test_parse_sectors():
    assert job.parse_sectors("HPG:THEP, dxg:bds") == {"HPG": "THEP", "DXG": "BDS"}


def test_annual_kept_when_quarter_fails_first_run(tmp_path):
    bctc, data = setup(tmp_path)
    job.run_job(bctc, data, SECTORS, FakeExtract({"2026Q3": [RuntimeError("503")]}))
    job.run_job(bctc, data, SECTORS, FakeExtract())
    rec = store.load("DXG", data)
    assert rec["status"] == "OK" and rec["annual_period"] == "2025FY" and rec["ratios"]["eps_ttm"] is not None
