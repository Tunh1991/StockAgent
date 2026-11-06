"""
schema.py - Schema trích xuất BCTC mẫu TT200 và các hằng số dùng chung.
Mã có tiền tố bảng: BS (B01-DN cân đối kế toán), IS (B02-DN kết quả kinh doanh), CF (B03-DN lưu chuyển tiền tệ).
"""
from enum import Enum

from pydantic import BaseModel, Field


class Unit(str, Enum):
    DONG = "DONG"
    NGHIN_DONG = "NGHIN_DONG"
    TRIEU_DONG = "TRIEU_DONG"


UNIT_SCALE = {Unit.DONG: 1.0, Unit.NGHIN_DONG: 1e3, Unit.TRIEU_DONG: 1e6}
COLUMNS = ("current", "prior", "ytd_current", "ytd_prior")


class LineItem(BaseModel):
    code: str = Field(description="Mã có tiền tố bảng, ví dụ BS270, IS10, CF20")
    current: float | None = Field(None, description="BS: cuối kỳ | IS quý: quý này | BCTC năm: năm nay")
    prior: float | None = Field(None, description="BS: đầu năm | IS quý: cùng quý năm trước | BCTC năm: năm trước")
    ytd_current: float | None = Field(None, description="BCTC quý: lũy kế từ đầu năm đến cuối quý này")
    ytd_prior: float | None = Field(None, description="BCTC quý: lũy kế cùng kỳ năm trước")
    page: int = Field(description="Số trang PDF chứa dòng này")


class Extraction(BaseModel):
    unit: Unit = Field(description="Đơn vị tiền in ở đầu bảng")
    period_end: str = Field(description="Ngày kết thúc kỳ báo cáo, dạng YYYY-MM-DD")
    consolidated: bool = Field(description="True nếu là BCTC hợp nhất")
    items: list[LineItem]

    def get(self, code: str) -> LineItem | None:
        return next((i for i in self.items if i.code == code), None)


CODES: dict[str, str] = {
    "BS100": "Tài sản ngắn hạn", "BS200": "Tài sản dài hạn", "BS270": "Tổng cộng tài sản",
    "BS300": "Nợ phải trả", "BS310": "Nợ ngắn hạn", "BS330": "Nợ dài hạn",
    "BS400": "Vốn chủ sở hữu", "BS411": "Vốn góp của chủ sở hữu", "BS440": "Tổng cộng nguồn vốn",
    "BS140": "Hàng tồn kho (thuần)", "BS312": "Người mua trả tiền trước ngắn hạn",
    "BS332": "Người mua trả tiền trước dài hạn", "BS320": "Vay và nợ thuê tài chính ngắn hạn",
    "BS338": "Vay và nợ thuê tài chính dài hạn", "BS429": "Lợi ích cổ đông không kiểm soát",
    "IS01": "Doanh thu bán hàng và cung cấp dịch vụ", "IS02": "Các khoản giảm trừ doanh thu",
    "IS10": "Doanh thu thuần", "IS11": "Giá vốn hàng bán", "IS20": "Lợi nhuận gộp",
    "IS23": "Trong đó: Chi phí lãi vay", "IS50": "Tổng lợi nhuận kế toán trước thuế",
    "IS51": "Chi phí thuế TNDN hiện hành", "IS52": "Chi phí thuế TNDN hoãn lại",
    "IS60": "Lợi nhuận sau thuế TNDN", "IS61": "Lợi nhuận sau thuế của cổ đông công ty mẹ",
    "CF20": "Lưu chuyển tiền thuần từ hoạt động kinh doanh",
}

REQUIRED: frozenset[str] = frozenset({
    "BS100", "BS200", "BS270", "BS300", "BS310", "BS330", "BS400", "BS411", "BS440",
    "IS01", "IS10", "IS11", "IS20", "IS50", "IS51", "IS60", "IS61", "CF20",
})

# (vế trái, [(dấu, mã vế phải), ...])
IDENTITIES: list[tuple[str, list[tuple[int, str]]]] = [
    ("BS270", [(1, "BS100"), (1, "BS200")]),
    ("BS440", [(1, "BS300"), (1, "BS400")]),
    ("BS270", [(1, "BS440")]),
    ("BS300", [(1, "BS310"), (1, "BS330")]),
    ("IS10", [(1, "IS01"), (-1, "IS02")]),
    ("IS20", [(1, "IS10"), (-1, "IS11")]),
    ("IS60", [(1, "IS50"), (-1, "IS51"), (-1, "IS52")]),
]

# Các mã BCTC in trong ngoặc nhưng mang nghĩa dương trong đẳng thức
ABS_CODES = frozenset({"IS02", "IS11"})

PERIOD_END = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31", "FY": "12-31"}
