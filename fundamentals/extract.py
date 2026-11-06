"""
extract.py - Gửi PDF BCTC (mẫu TT200) cho Gemini để CHÉP số liệu theo mã số. Không tính toán gì ở đây.
"""
from pathlib import Path

import llm
from fundamentals.schema import CODES, Extraction

INLINE_LIMIT = 20 * 1024 * 1024  # PDF lớn hơn thì tải lên qua Files API


def build_extract_prompt(period: str) -> str:
    code_lines = "\n".join(f"- {code}: {name} (Mã số {code[2:]} trên bảng {code[:2]})"
                           for code, name in CODES.items())
    return f"""Bạn là kế toán viên. File PDF đính kèm là Báo cáo tài chính kỳ {period} theo mẫu Thông tư 200
(BS = Bảng cân đối kế toán B01-DN, IS = Báo cáo kết quả kinh doanh B02-DN, CF = Lưu chuyển tiền tệ B03-DN).

NHIỆM VỤ: chép lại đúng số in trong BCTC cho các mã số sau (dựa vào cột "Mã số" của từng bảng):
{code_lines}

QUY TẮC BẮT BUỘC:
- Chép đúng con số in trên BCTC, không tính toán, không làm tròn, không suy luận.
- Số in trong ngoặc (...) là số âm.
- Mã nào không có trong BCTC thì bỏ qua, không tự điền.
- Ghi số trang PDF (bắt đầu từ 1) chứa dòng đó vào "page".
- "unit": đơn vị tiền in ở đầu bảng (DONG, NGHIN_DONG hoặc TRIEU_DONG).
- "period_end": ngày kết thúc kỳ báo cáo (YYYY-MM-DD). "consolidated": true nếu là BCTC hợp nhất.
- Cột giá trị:
  * BS: "current" = số cuối kỳ, "prior" = số đầu năm.
  * IS của BCTC quý: "current" = quý này, "prior" = cùng quý năm trước,
    "ytd_current" = lũy kế từ đầu năm đến cuối quý này, "ytd_prior" = lũy kế cùng kỳ năm trước.
  * CF của BCTC quý: chỉ có lũy kế, ghi vào "ytd_current" và "ytd_prior".
  * BCTC năm: "current" = năm nay, "prior" = năm trước.
"""


def extract_statement(pdf_path: Path, period: str, generate=llm.generate,
                      client_factory=llm.get_client) -> Extraction:
    from google.genai import types

    pdf_path = Path(pdf_path)
    if pdf_path.stat().st_size <= INLINE_LIMIT:
        pdf_part = types.Part.from_bytes(data=pdf_path.read_bytes(), mime_type="application/pdf")
    else:
        pdf_part = client_factory().files.upload(file=pdf_path)
    result = generate([pdf_part, build_extract_prompt(period)], Extraction, temperature=0)
    return result.parsed
