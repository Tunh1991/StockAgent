# Đặc tả thiết kế: Phân tích cơ bản từ PDF BCTC (giai đoạn 1: doanh nghiệp TT200)

**Ngày:** 06/11/2026
**Trạng thái:** Chờ duyệt
**Phụ thuộc:** `docs/superpowers/specs/2026-11-06-multi-agent-design.md`. Phần tích hợp (mục 7) chỉ làm được sau khi multi-agent hoàn thành.
**Phạm vi:** FR-04 (một phần) và FR-05 trong tài liệu yêu cầu.

---

## 1. Mục tiêu và bối cảnh

**Mục tiêu:** điền `fundamental_analysis` bằng số liệu thật, lấy từ BCTC. Gemini chỉ chép số từ PDF. Python kiểm tra và tính toàn bộ chỉ số, nhờ đó không có số liệu tài chính nào do LLM tự nghĩ ra (NFR-01).

**Bối cảnh:** các API công khai đã thử ngày 06/11/2026 đều không dùng được. TCBS trả lỗi 404, VNDirect không phản hồi. Vì vậy chọn nguồn là PDF BCTC chính thức.

**Các quyết định đã chốt:**
1. **Nguồn PDF:** người dùng tự tải thủ công vào `data/bctc/<MÃ>/`.
2. **Giai đoạn 1:** chỉ doanh nghiệp theo mẫu TT200 (HPG, FPT, MWG, VNM, DXG). Ngân hàng (VCB, TCB) và chứng khoán (SSI) để giai đoạn sau.
3. **Số file mỗi mã:** BCTC quý mới nhất và BCTC năm gần nhất. TTM tính từ hai file này.
4. **Cách trích xuất:** Gemini trích theo mã số TT200, chạy **2 lần độc lập** rồi so sánh. Python kiểm tra đẳng thức kế toán và tính chỉ số.

**Ngoài phạm vi:** tự động tải PDF, mẫu BCTC ngân hàng và chứng khoán, thuyết minh BCTC, trừ cổ phiếu quỹ.

---

## 2. Kiến trúc

```
[Người dùng, mỗi quý]  data/bctc/DXG/2026Q3.pdf, data/bctc/DXG/2025FY.pdf
                                   │
[python fundamentals_job.py]       ▼
 file mới (SHA-256) ─► extract × 2 ─► checks (so 2 lần, đẳng thức, đơn vị)
                                        │ lỗi → trích lại 1 cặp → vẫn lỗi → REJECTED, giữ dữ liệu cũ
                                        ▼ đạt
                         ratios ─► store: data/fundamentals/DXG.json
                                        │
[Trong phiên, khi có tín hiệu]          ▼
 main: load + định giá theo giá hiện tại ─► run_pipeline(..., fundamentals) ─► Analyst / Validator S3 / Critic
```

### Cấu trúc file

| File | Nhiệm vụ |
|---|---|
| `fundamentals/__init__.py` | Rỗng |
| `fundamentals/schema.py` | Pydantic: `LineItem`, `Extraction`. Hằng số: danh sách mã, mã bắt buộc, đẳng thức |
| `fundamentals/extract.py` | `extract_statement(pdf_path, period) -> Extraction`, gọi Gemini với PDF |
| `fundamentals/checks.py` | `compare_runs`, `check_identities`, `normalize_units`, `check_shares` |
| `fundamentals/ratios.py` | `compute_ratios(quarter, annual, sector) -> dict`, `valuation(ratios, price) -> dict` |
| `fundamentals/store.py` | Đọc/ghi `data/fundamentals/<MÃ>.json`, quản lý danh sách mã băm đã xử lý |
| `fundamentals_job.py` | CLI: quét `data/bctc/`, xử lý file mới, in tóm tắt |
| `.env` / `.env.example` | `SECTORS=HPG:THEP,DXG:BDS,FPT:CHUNG,MWG:CHUNG,VNM:CHUNG` |

Ngành hợp lệ ở giai đoạn 1: `THEP`, `BDS`, `CHUNG`. Mã không có trong `SECTORS`, hoặc thuộc ngành khác, bị bỏ qua với thông báo "chưa hỗ trợ mẫu BCTC này".

---

## 3. Quy ước file đầu vào

- Đường dẫn: `data/bctc/<MÃ>/<YYYY>Q<1-4>.pdf` (BCTC quý) và `data/bctc/<MÃ>/<YYYY>FY.pdf` (BCTC năm).
- Loại báo cáo: **BCTC hợp nhất**. Nếu công ty không có công ty con thì dùng BCTC riêng.
- File không khớp regex `^\d{4}(Q[1-4]|FY)\.pdf$` (không phân biệt hoa thường) bị bỏ qua và có cảnh báo.
- Mỗi mã chỉ dùng **quý mới nhất** và **năm gần nhất trước quý đó**. Ví dụ quý là 2026Q3 thì năm là 2025FY. Các file cũ hơn bị bỏ qua.

---

## 4. Trích xuất (`fundamentals/extract.py`)

### Mã số cần trích (mẫu TT200)

Mã được ghi kèm tiền tố bảng: `BS` (bảng cân đối kế toán, B01-DN), `IS` (kết quả kinh doanh, B02-DN), `CF` (lưu chuyển tiền tệ, B03-DN).

| Mã | Tên | Bắt buộc |
|---|---|---|
| BS100, BS200, BS270 | TS ngắn hạn, TS dài hạn, Tổng tài sản | ✔ |
| BS300, BS310, BS330 | Nợ phải trả, Nợ ngắn hạn, Nợ dài hạn | ✔ |
| BS400, BS411, BS440 | Vốn chủ sở hữu, Vốn góp của chủ sở hữu, Tổng nguồn vốn | ✔ |
| BS140 | Hàng tồn kho (thuần) | thiếu thì = 0 |
| BS312, BS332 | Người mua trả tiền trước ngắn hạn / dài hạn | thiếu thì = 0 |
| BS320, BS338 | Vay và nợ thuê tài chính ngắn hạn / dài hạn | thiếu thì = 0 |
| BS429 | Lợi ích cổ đông không kiểm soát | thiếu thì = 0 |
| IS01, IS10, IS11, IS20 | DT bán hàng, DT thuần, Giá vốn, LN gộp | ✔ |
| IS02 | Các khoản giảm trừ doanh thu | thiếu thì = 0 |
| IS50, IS51, IS60, IS61 | LN trước thuế, Thuế TNDN hiện hành, LNST, LNST cổ đông công ty mẹ | ✔ |
| IS52 | Thuế TNDN hoãn lại | thiếu thì = 0 |
| IS23 | Trong đó: chi phí lãi vay | thiếu thì = 0 |
| CF20 | Lưu chuyển tiền thuần từ hoạt động kinh doanh | ✔ |

Tổng cộng 27 mã: 15 mã BS, 11 mã IS, 1 mã CF. Với công ty không có công ty con, IS61 = IS60.

### Schema (`fundamentals/schema.py`)

```
LineItem:   code: str            # "BS270", "IS10"...
            current: float | None       # BS: cuối kỳ | IS quý: quý này | IS/CF năm: năm nay
            prior: float | None         # BS: đầu năm | IS quý: cùng quý năm trước | năm: năm trước
            ytd_current: float | None   # IS/CF của BCTC quý: lũy kế từ đầu năm (CF chỉ có lũy kế, ghi ở đây)
            ytd_prior: float | None     # lũy kế cùng kỳ năm trước
            page: int                   # trang PDF chứa dòng này
Extraction: unit: "DONG" | "NGHIN_DONG" | "TRIEU_DONG"
            period_end: str             # "2026-09-30", do Gemini đọc từ PDF
            consolidated: bool
            items: list[LineItem]
```
Với BCTC năm, CF20 ghi ở `current` và `prior`. Với BCTC quý, CF20 ghi ở `ytd_current` và `ytd_prior`.

### Gọi Gemini
- Prompt: liệt kê 25 mã kèm tên. Yêu cầu chép **đúng số in trong BCTC**, số trong ngoặc là số âm, không tính toán, không làm tròn. Mã nào không có trong BCTC thì bỏ qua. Phải ghi số trang và đơn vị in ở đầu bảng.
- Cấu hình: `temperature = 0`, `response_schema = Extraction`. Dùng cùng model chính, danh sách model dự phòng và cơ chế thử lại trong `llm.py`.
- PDF ≤ 20 MB gửi trực tiếp trong request (`types.Part.from_bytes`, `application/pdf`). PDF > 20 MB tải lên qua `client.files.upload` trước.
- Signature: `extract_statement(pdf_path: Path, period: str) -> Extraction`.

---

## 5. Kiểm tra (`fundamentals/checks.py`)

Ngưỡng: `TOL = 0.001` (0.1%). Hai số a, b được coi là khớp khi `|a − b| ≤ max(TOL × max(|a|, |b|), 1 đơn vị)`.

Các bước, theo thứ tự:
1. **`compare_runs(a, b) -> list[str]`:** so sánh 2 lần trích. Phải giống nhau về `unit` và `period_end`. Mỗi mã có ở một lần thì phải có ở lần kia. Mỗi cột phải khớp.
2. **`normalize_units(ex) -> Extraction`:** quy đổi mọi giá trị về đồng (×1, ×1.000, ×1.000.000).
3. **Mã bắt buộc:** thiếu mã bắt buộc thì báo lỗi. Mã không bắt buộc bị thiếu thì gán 0.
4. **`check_identities(ex) -> list[str]`:** kiểm tra trên mọi cột có dữ liệu.
   - `BS270 = BS100 + BS200`
   - `BS440 = BS300 + BS400`
   - `BS270 = BS440`
   - `BS300 = BS310 + BS330`
   - `IS10 = IS01 − IS02`
   - `IS20 = IS10 − IS11`
   - `IS60 = IS50 − IS51 − IS52`
5. **`check_shares(ex) -> list[str]`:** số cổ phiếu = `BS411.current / 10_000`, phải nằm trong [1e6, 2e10]. Ngoài khoảng này thì báo lỗi "nghi đọc sai đơn vị".
6. **Kỳ báo cáo:** `period_end` phải khớp với tên file. Q1 → `YYYY-03-31`, Q2 → `-06-30`, Q3 → `-09-30`, Q4 và FY → `-12-31`. Giả định năm tài chính trùng năm dương lịch, đúng với cả 5 mã trong giai đoạn 1.

Mỗi lỗi là một chuỗi tiếng Việt có mã bước, ví dụ `"F4: IS20 ≠ IS10 − IS11 (cột current): 1.234 ≠ 1.300"`.

**Xử lý khi có lỗi:** trích lại thêm 1 cặp (2 lần gọi) và kiểm tra lại từ đầu. Nếu vẫn lỗi thì file bị `REJECTED`. Mỗi file tốn tối đa 4 lần gọi.

---

## 6. Chỉ số (`fundamentals/ratios.py`)

Đầu vào: `quarter: Extraction` (đã chuẩn hóa), `annual: Extraction | None`, `sector: str`. Đầu ra là dict. Chỉ số nào không tính được thì có giá trị `None`, không phát sinh lỗi.

`TTM(code)`:
- Nếu quý là Q4: `ytd_current`.
- Nếu không: `annual.current + quarter.ytd_current − quarter.ytd_prior`.
- Nếu không có `annual` (và không phải Q4) thì là `None`.

| Khóa | Công thức |
|---|---|
| `period`, `period_end` | ví dụ "2026Q3" |
| `shares` | BS411.current / 10.000 |
| `eps_ttm` | TTM(IS61) / shares |
| `bvps` | (BS400 − BS429).current / shares |
| `roe_ttm` | TTM(IS61) / trung bình của (BS400 − BS429) cuối kỳ và đầu năm |
| `roa_ttm` | TTM(IS61) / trung bình của BS270 cuối kỳ và đầu năm |
| `revenue_ttm`, `npat_parent_ttm` | TTM(IS10), TTM(IS61) |
| `gross_margin_q`, `gross_margin_q_prior` | IS20/IS10 ở cột current và cột prior |
| `net_margin_q` | IS60/IS10 (current) |
| `revenue_yoy_q`, `npat_parent_yoy_q` | current/prior − 1. Nếu prior ≤ 0 thì `None` |
| `debt_to_equity` | (BS320 + BS338)/BS400 (current) |
| `current_ratio` | BS100/BS310 (current) |
| `interest_coverage` | (IS50 + IS23)/IS23 (current). Nếu IS23 = 0 thì `None` |
| `ocf_to_npat_ytd` | CF20.ytd_current / IS60.ytd_current. Với Q4 dùng ytd_current. Nếu IS60 = 0 thì `None` |
| **BDS:** `customer_advances_to_equity`, `customer_advances_change` | (BS312 + BS332)/BS400 (current), và (current/prior − 1) của (BS312 + BS332) |
| **BDS:** `inventory_to_assets` | BS140/BS270 (current) |
| **THEP:** `inventory_days` | 365 / (TTM(IS11) / trung bình BS140 cuối kỳ và đầu năm) |
| **THEP:** `gross_margin_change_yoy` | gross_margin_q − gross_margin_q_prior |

Mọi chỉ số dạng tỷ lệ được làm tròn 4 chữ số.

`valuation(ratios: dict, price: float) -> dict`:
- `price` theo nghìn đồng.
- `pe = price × 1000 / eps_ttm`. Nếu `eps_ttm ≤ 0` hoặc None thì `pe = None` và thêm `pe_note = "EPS ≤ 0, P/E không có ý nghĩa"`.
- `pb = price × 1000 / bvps`.
- Hàm này được gọi khi có tín hiệu, không lưu vào file.

---

## 7. Lưu trữ và tích hợp

### `data/fundamentals/<MÃ>.json`

```json
{"symbol": "DXG", "sector": "BDS", "status": "OK | REJECTED",
 "period": "2026Q3", "period_end": "2026-09-30", "annual_period": "2025FY",
 "ratios": {}, "raw": {"quarter": {}, "annual": {}},
 "sources": {"2026Q3.pdf": {"sha256": "...", "status": "OK", "errors": []}, "2025FY.pdf": {}},
 "updated_at": "..."}
```
- `raw` là các `Extraction` đã chuẩn hóa, có số trang, để đối chiếu với PDF gốc.
- Khi một file mới bị `REJECTED`, chỉ cập nhật `sources[file]`. `ratios` và `raw` hợp lệ trước đó được giữ nguyên.
- Một file đã xử lý được bỏ qua khi `sha256` không đổi và status là `OK` hoặc `REJECTED`. File bị lỗi do Gemini không phản hồi thì **không** được ghi vào `sources`, nên lần chạy sau sẽ thử lại.

### Tích hợp với multi-agent

- **`main.scan_symbol`:** đọc `store.load(symbol)`. Nếu có `ratios`, ghép thêm `valuation(ratios, close)` rồi truyền vào `run_pipeline(..., fundamentals=dict | None)`.
- **`agents.build_analyst_prompt` và `build_critic_prompt`:** nhận thêm `fundamentals: dict | None`.
  - Nếu có dữ liệu: thêm khối "DỮ LIỆU CƠ BẢN (kỳ ..., BCTC hợp nhất)" liệt kê các chỉ số không phải `None`, theo dạng %, lần hoặc tỷ đồng. Quy tắc: `fundamental_analysis` chỉ dùng các số trong khối này.
  - Nếu không có dữ liệu: giữ câu "Chưa có dữ liệu cơ bản - cần kiểm tra BCTC".
- **Dữ liệu cũ:** nếu `today − period_end > 200 ngày`, khối dữ liệu có thêm dòng "⚠ Dữ liệu cơ bản đã cũ (kỳ ...)".
- **`validator.validate`:** nhận thêm `fundamentals: dict | None = None`.
  - S3 quét thêm phần chữ `fundamental_analysis`.
  - Danh sách tham chiếu được bổ sung mọi giá trị số trong `fundamentals`, kèm dạng ×100 (phần trăm) và ÷1e9 (tỷ đồng).

---

## 8. Xử lý lỗi

| Tình huống | Kết quả |
|---|---|
| Tên file sai quy ước | Bỏ qua, in cảnh báo |
| Ngành chưa hỗ trợ | Bỏ qua, in "chưa hỗ trợ mẫu BCTC này" |
| Kiểm tra vẫn sai sau khi trích lại | `REJECTED` kèm lý do, giữ dữ liệu cũ |
| Gemini lỗi ở mọi model | Không ghi vào `sources`, job báo lỗi cho file đó và xử lý tiếp file khác |
| Thiếu BCTC năm | Các chỉ số TTM là `None`, chỉ số theo quý vẫn tính |
| Chưa có file `<MÃ>.json` | `fundamentals = None`, multi-agent chạy như cũ |

`fundamentals_job.py` trả exit code khác 0 nếu có file lỗi do Gemini, để người dùng biết cần chạy lại.

---

## 9. Kiểm thử

Thư mục `tests/fundamentals/`, dùng pytest, không gọi mạng.

- **`test_checks.py`:**
  - Đẳng thức đúng thì không có lỗi. Mỗi đẳng thức sai đều được phát hiện.
  - Hai lần trích lệch 0.2% thì báo lỗi, lệch 0.05% thì khớp.
  - Thiếu một mã ở một trong hai lần trích thì báo lỗi.
  - Quy đổi `TRIEU_DONG` nhân 1e6.
  - Số cổ phiếu ngoài khoảng hợp lệ thì báo lỗi.
  - `period_end` không khớp tên file thì báo lỗi.
  - Thiếu mã bắt buộc thì báo lỗi. Thiếu mã không bắt buộc thì gán 0.
- **`test_ratios.py`:**
  - TTM ở Q3 có BCTC năm, TTM ở Q4 không cần BCTC năm.
  - Q3 không có BCTC năm thì các chỉ số TTM là `None`.
  - EPS âm thì `pe` là None và có `pe_note`.
  - IS23 = 0 thì `interest_coverage` là None.
  - Có chỉ số riêng cho BDS và THEP. Ngành `CHUNG` không có các khóa riêng.
- **`test_extract.py`:**
  - Dùng client giả, trả về `Extraction`.
  - File 21 MB (giả lập kích thước bằng monkeypatch) đi qua Files API, file nhỏ gửi trực tiếp.
- **`test_job.py`** (dùng `tmp_path`, extractor giả):
  - File mới thì status `OK`, có ghi file JSON.
  - Chạy lại thì bỏ qua, không gọi extractor.
  - File sai tên bị bỏ qua.
  - File `REJECTED` vẫn giữ `ratios` cũ.
  - Gemini lỗi thì không ghi vào `sources` và exit code khác 0.
  - Mã ngân hàng bị bỏ qua.
  - Trích lại một cặp khi lần đầu lệch, tổng cộng 4 lần gọi.
- **Tích hợp** (thêm vào test của multi-agent):
  - Prompt có khối dữ liệu cơ bản khi có dữ liệu, có dòng cảnh báo khi dữ liệu cũ.
  - S3 không cảnh báo với P/E thật hoặc ROE thật ở dạng %, nhưng cảnh báo với ROE bịa.
- **Chạy thật:**
  - Người dùng đặt `data/bctc/DXG/2026Q3.pdf` và `data/bctc/DXG/2025FY.pdf`, sau đó chạy `python fundamentals_job.py`.
  - So sánh thủ công 5 số (BS270, BS400, IS10, IS61, CF20) với trang PDF được ghi trong `raw`.
  - Chạy `python main.py --once --force --symbols DXG` để xem `fundamental_analysis` có số liệu thật.

---

## 10. Thay đổi kèm theo

- `.env.example`: thêm `SECTORS`.
- `.gitignore` (nếu dùng git): thêm `data/bctc/`, vì PDF có kích thước lớn.
- Tài liệu yêu cầu:
  - FR-04 chuyển sang "Giai đoạn 1: doanh nghiệp TT200".
  - FR-05 chuyển sang "Đã triển khai: Gemini Flash đọc PDF, tải thủ công".
  - Thêm `fundamentals_job.py` vào hướng dẫn chạy.
