from types import SimpleNamespace

from fundamentals import extract
from fundamentals.schema import CODES, Extraction
from llm import LLMResult
from tests.fundamentals.helpers import make_extraction


class FakeGen:
    def __init__(self):
        self.calls = []

    def __call__(self, contents, schema, temperature=0.2):
        self.calls.append({"contents": contents, "schema": schema, "temperature": temperature})
        return LLMResult(make_extraction(), "fake", 0.1)


class FakeFiles:
    def __init__(self):
        self.uploaded = []

    def upload(self, file):
        self.uploaded.append(file)
        return "UPLOADED"


def setup(tmp_path):
    pdf = tmp_path / "2026Q3.pdf"
    pdf.write_bytes(b"%PDF-1.4 " + b"x" * 1024)
    files = FakeFiles()
    return pdf, files, (lambda: SimpleNamespace(files=files))


def test_prompt_lists_all_codes():
    p = extract.build_extract_prompt("2026Q3")
    assert all(c in p for c in CODES)
    for s in ("trong ngoặc", "không tính toán", "số trang"):
        assert s in p


def test_small_pdf_inline(tmp_path):
    pdf, files, factory = setup(tmp_path)
    gen = FakeGen()
    extract.extract_statement(pdf, "2026Q3", generate=gen, client_factory=factory)
    call = gen.calls[0]
    assert call["temperature"] == 0 and call["schema"] is Extraction
    assert any(getattr(getattr(c, "inline_data", None), "mime_type", None) == "application/pdf"
               for c in call["contents"])
    assert files.uploaded == []


def test_large_pdf_uses_files_api(tmp_path, monkeypatch):
    pdf, files, factory = setup(tmp_path)
    monkeypatch.setattr(extract, "INLINE_LIMIT", 10)
    gen = FakeGen()
    extract.extract_statement(pdf, "2026Q3", generate=gen, client_factory=factory)
    assert files.uploaded == [pdf] and "UPLOADED" in gen.calls[0]["contents"]


def test_returns_extraction(tmp_path):
    pdf, _, factory = setup(tmp_path)
    assert extract.extract_statement(pdf, "2026Q3", generate=FakeGen(), client_factory=factory) == make_extraction()
