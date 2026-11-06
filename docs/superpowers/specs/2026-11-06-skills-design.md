# Đặc tả thiết kế: Cơ chế skill chuyên gia và skill Trend Template

**Ngày:** 06/11/2026
**Trạng thái:** Chờ duyệt
**Phụ thuộc:** kiến trúc multi-agent (`2026-11-06-multi-agent-design.md`) và phân tích cơ bản (`2026-11-06-fundamentals-design.md`), cả hai đã triển khai.

---

## 1. Mục tiêu và các quyết định đã chốt

**Mục tiêu:** thêm phương pháp phân tích của chuyên gia dưới dạng **skill cắm được**. Python tính toàn bộ dữ kiện của phương pháp. Gemini đánh giá theo bộ tiêu chí trong file `.md`. Mọi con số đều được Validator (luật S3) kiểm tra.

**Các quyết định đã chốt:**
1. **Đợt 1 chỉ làm skill Trend Template.**
2. **Cách xây:** mỗi skill là một thư mục gồm `skill.py`, `playbook.md` và `config.json`. Thêm skill mới không phải sửa orchestrator.
3. **Vai trò:** chủ yếu để tham khảo, kèm một luật cứng nhẹ do Python áp dụng. Luật này chỉ được giảm độ tin cậy, không được hạ hay nâng tín hiệu.
4. **Ngưỡng:** mặc định theo bản gốc, sửa được trong `config.json`.
5. **Không tăng số lần gọi Gemini:** vẫn tối đa 3 lần cho mỗi tín hiệu.

**Ngoài phạm vi:** VCP, CANSLIM, quản trị vốn, dòng tiền khối ngoại, kiểm chứng ngưỡng trên dữ liệu lịch sử (backtest).

---

## 2. Cơ chế skill

### Cấu trúc file

| File | Nhiệm vụ |
|---|---|
| `skills/__init__.py` | `load_skills(names: list[str]) -> list[Skill]` |
| `skills/base.py` | `SkillContext`, `Criterion`, `SkillResult`, lớp cơ sở `Skill`, `format_skill_block(result, playbook) -> str` |
| `skills/trend_template/skill.py` | `SKILL = TrendTemplateSkill()` |
| `skills/trend_template/playbook.md` | Bộ tiêu chí tiếng Việt (15–25 dòng) |
| `skills/trend_template/config.json` | Các ngưỡng |
| `data_loader.py` | Thêm `get_index_history(symbol="VNINDEX", count=300) -> pd.DataFrame`, gọi `.../chart-api/v2/ohlcs/index` |

### Giao diện (`skills/base.py`)

```
SkillContext:  symbol: str; df: pd.DataFrame (đã qua compute_technical_indicators); metrics: dict;
               fundamentals: dict | None; index_df: pd.DataFrame | None
Criterion:     key: str; label: str; passed: bool | None; detail: str
SkillResult:   name: str; title: str; facts: dict[str, float]; criteria: list[Criterion]
               + property passed_count -> int, total -> int
               + to_dict() -> dict
Skill:         name: str; title: str; config: dict (đọc từ config.json, gộp với DEFAULTS)
               playbook: str (đọc từ playbook.md, "" nếu không có)
               evaluate(ctx: SkillContext) -> SkillResult
               adjust(final: dict, result: SkillResult) -> list[str]   # mặc định trả về []
```

- `passed = None` nghĩa là không đủ dữ liệu.
- `adjust` sửa trực tiếp `final` và trả về danh sách ghi chú để đưa vào `red_flags`. Luật bất biến: sau `adjust`, `final["confidence_score"]` không lớn hơn trước, và `final["signal"]` không đổi.

### Nạp skill
- `.env`: `SKILLS=trend_template`. Bỏ trống thì không bật skill nào.
- `load_skills` import `skills.<name>.skill` và lấy biến `SKILL`. Tên không tồn tại thì ghi cảnh báo và bỏ qua.
- `config.json` thiếu khóa hoặc sai kiểu thì dùng giá trị trong `DEFAULTS` của skill và ghi cảnh báo.

### Luồng xử lý

1. `main.run_scan` lấy VN-Index **1 lần cho mỗi lượt quét** bằng `get_index_history`. Lỗi thì `index_df = None`.
2. Với mỗi mã có tín hiệu, `main` tạo `SkillContext` và gọi `run_skills(skills, ctx) -> list[SkillResult | dict]`. Skill phát sinh exception thì kết quả là `{"name", "error"}`.
3. `orchestrator.run_pipeline(..., skill_results: list | None = None)`:
   - `build_analyst_prompt` và `build_critic_prompt` thêm `format_skill_block` cho mỗi skill thành công.
   - `validate(..., extra_refs=...)`: các giá trị trong `facts` của mọi skill được thêm vào danh sách số tham chiếu của S3, kèm dạng ×100 (phần trăm).
   - Ở bước quyết định cuối, **sau** Critic, áp dụng hạ cấp và giới hạn của các bước trước, gọi `skill.adjust(final, result)` cho từng skill thành công, rồi gộp các ghi chú vào `red_flags`. `adjust` phát sinh lỗi thì bỏ qua và ghi log.
   - Bản ghi có thêm `skills: [result.to_dict() | {"name", "error"}]` và `skill_adjustments: [str]`.
4. `HISTORY_BARS` trong `main.py`: 160 → **300**.

### Khối prompt (`format_skill_block`)

```
PHƯƠNG PHÁP: <title> (đạt <passed_count>/<total> tiêu chí)
- [ĐẠT] T1 Giá > MA150 và MA200: 11.0 > 10.10 và 9.85
- [KHÔNG ĐẠT] T3 MA200 đi lên 22 phiên: 9.85 ≤ 9.90
- [KHÔNG ĐỦ DỮ LIỆU] T8 ...
<nội dung playbook.md>
```

Số trong khối không dùng dấu phân cách nghìn.

---

## 3. Skill Trend Template

### Ngưỡng (`config.json`, cũng là `DEFAULTS`)

```json
{"ma200_rising_days": 22, "min_above_low": 0.30, "max_below_high": 0.25,
 "week52_bars": 250, "rs_lookback": 126, "min_pass": 6, "confidence_cap": 6.0}
```

### Tiêu chí (C = giá đóng cửa mới nhất)

| Mã | Tiêu chí | Dữ liệu tối thiểu |
|---|---|---|
| T1 | C > MA150 và C > MA200 | 200 phiên |
| T2 | MA150 > MA200 | 200 phiên |
| T3 | MA200[hôm nay] > MA200[`ma200_rising_days` phiên trước] | 200 + 22 phiên |
| T4 | MA50 > MA150 và MA50 > MA200 | 200 phiên |
| T5 | C > MA50 | 50 phiên |
| T6 | C ≥ LOW_52W × (1 + `min_above_low`) | `week52_bars` phiên |
| T7 | C ≥ HIGH_52W × (1 − `max_below_high`) | `week52_bars` phiên |
| T8 | RET_6M > INDEX_RET_6M, trong đó RET = C / C[`rs_lookback` phiên trước] − 1 | `rs_lookback` + 1 phiên của cả mã và VN-Index |

- MA150 và MA200 là trung bình giá đóng cửa 150 và 200 phiên, tính trong skill (không thêm vào `indicators.py`).
- HIGH_52W và LOW_52W là max(high) và min(low) của `week52_bars` phiên gần nhất, **tính cả phiên hiện tại**.
- Thiếu dữ liệu thì tiêu chí có `passed = None`.
- **T8 là bản điều chỉnh.** Bản gốc dùng xếp hạng RS ≥ 70 so với toàn thị trường. `playbook.md` phải ghi rõ điểm khác này.
- T8: VN-Index được căn theo ngày (`date`). Nếu ngày cuối của VN-Index khác ngày cuối của mã thì dùng phiên chung gần nhất của cả hai.

### `facts`

`ma150`, `ma200`, `ma200_prev`, `high_52w`, `low_52w`, `pct_below_high` (= 1 − C/HIGH_52W), `pct_above_low` (= C/LOW_52W − 1), `ret_6m`, `index_ret_6m`, `passed_count`.

Giá làm tròn 2 chữ số, tỷ lệ làm tròn 4 chữ số. Khóa nào không tính được thì không có trong `facts`.

### Luật điều chỉnh (`adjust`)

- **Điều kiện:** `final["signal"] == "MUA GOM"` và `passed_count < min_pass`. Tiêu chí `None` được tính là không đạt.
- **Xử lý:**
  - `final["confidence_score"] = min(final["confidence_score"], confidence_cap)`.
  - Trả về ghi chú `"Trend Template chỉ đạt {passed_count}/{total} tiêu chí (cần ≥ {min_pass}): độ tin cậy tối đa {confidence_cap}"`.
- Nếu không thỏa điều kiện thì trả về `[]`.

### `playbook.md`

Viết bằng lời của dự án, không chép sách. Nội dung:
1. Mục đích: chỉ mua cổ phiếu đang trong xu hướng tăng rõ ràng (giai đoạn 2), tránh "bắt dao rơi".
2. Ý nghĩa của từng nhóm tiêu chí: cấu trúc các đường MA (T1, T2, T4, T5), độ dốc dài hạn (T3), vị trí trong biên độ 52 tuần (T6, T7), sức mạnh so với thị trường (T8, bản điều chỉnh so với VN-Index).
3. Lưu ý cho thị trường VN: biên độ ±7%, thanh toán T+2, cổ phiếu thanh khoản thấp có thể đạt tiêu chí "ảo".
4. Hướng dẫn cho Analyst: nêu rõ các tiêu chí không đạt trong `orderflow_analysis` hoặc `red_flags`, chỉ dùng số trong bảng, không tự tính MA.
5. Hướng dẫn cho Critic: nếu dưới 6/8 tiêu chí mà Analyst vẫn khuyến nghị MUA GOM thì phải phản biện.

---

## 4. Xử lý lỗi

| Tình huống | Kết quả |
|---|---|
| Lấy VN-Index thất bại | `index_df = None`, T8 = `None` |
| Lịch sử ngắn | Các tiêu chí thiếu dữ liệu = `None`, tính là không đạt trong luật `min_pass` |
| `evaluate` lỗi | `{"name", "error"}` trong `skills`, không có khối prompt, tín hiệu xử lý bình thường |
| `adjust` lỗi | Bỏ qua, ghi log |
| Tên skill không tồn tại | Cảnh báo, bỏ qua |
| `config.json` thiếu hoặc sai | Dùng `DEFAULTS`, ghi cảnh báo |
| Không có `playbook.md` | Khối prompt chỉ có bảng tiêu chí |

---

## 5. Kiểm thử

Dùng pytest, không gọi mạng.

- **`tests/skills/test_trend_template.py`:**
  - Dữ liệu giả xu hướng tăng đều 300 phiên, có VN-Index đi ngang: đạt 8/8.
  - Xu hướng giảm: T1, T2, T4, T5 không đạt.
  - Làm hỏng riêng từng tiêu chí T3, T6, T7, T8: chỉ tiêu chí đó không đạt.
  - Lịch sử 120 phiên: T1–T4, T6, T7, T8 là `None`, T5 vẫn được tính.
  - `index_df = None`: T8 là `None`.
  - Ngày của VN-Index lệch một phiên: dùng phiên chung gần nhất.
  - `config` với `max_below_high = 0.05`: T7 đổi thành không đạt.
  - Không khóa `facts` nào là NaN.
- **Luật `adjust`:**
  - MUA GOM, 5/8, độ tin cậy 8 → 6.0 và có ghi chú.
  - MUA GOM, 6/8 → không đổi.
  - QUAN SAT, 2/8 → không đổi.
  - Độ tin cậy 4, 5/8 → vẫn là 4.
  - Tín hiệu không bao giờ thay đổi.
- **`tests/skills/test_registry.py`:**
  - `load_skills(["trend_template"])` nạp được skill.
  - Tên sai thì bị bỏ qua.
  - `config.json` thiếu khóa thì dùng `DEFAULTS`.
  - Skill phát sinh lỗi trong `evaluate` thì `run_pipeline` vẫn trả `status = OK`.
- **Tích hợp** (`tests/skills/test_integration.py`):
  - Prompt của Analyst và Critic có `"PHƯƠNG PHÁP: Trend Template"`.
  - S3 không cảnh báo với MA150 đúng và `pct_below_high` dạng %, nhưng cảnh báo với MA200 bịa.
  - Bản ghi có `skills` và `skill_adjustments`.
  - Toàn bộ test cũ vẫn đạt.
- **`get_index_history`:** dùng response giả, trả về DataFrame cùng các cột như `get_stock_history`.
- **Chạy thật:** `python main.py --once --force --symbols DXG HPG`. Ghi lại kết quả 8 tiêu chí, đối chiếu tay MA200 và đỉnh 52 tuần với dữ liệu DNSE.

---

## 6. Thay đổi kèm theo

- `.env.example` và `.env`: thêm `SKILLS=trend_template`.
- Tài liệu yêu cầu: thêm mục "Skill chuyên gia" và cách thêm skill mới.
