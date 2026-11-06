# Phân tích cơ bản từ PDF BCTC: Kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trích số liệu BCTC (mẫu TT200) từ PDF bằng Gemini, Python kiểm tra và tính chỉ số, rồi đưa vào Analyst, Validator và Critic.

**Architecture:**
- Package `fundamentals/` gồm 4 module: `schema` và `checks` là code thuần, `extract` gọi Gemini, `store` lưu JSON.
- `fundamentals_job.py` là CLI chạy theo quý. Extractor được truyền vào qua tham số để test không phải gọi mạng.
- Task 5 gắn kết quả vào multi-agent.

**Tech Stack:** Python 3.11, pydantic v2, google-genai, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-fundamentals-design.md`

**Điều kiện tiên quyết:**
- Task 1–4 chỉ cần `llm.py` của kế hoạch multi-agent (`docs/superpowers/plans/2026-11-06-multi-agent.md`, Task 4).
- Task 5 cần **toàn bộ** kế hoạch multi-agent đã hoàn thành.

**Commit:** thư mục chưa phải git repository. Bước cuối mỗi task là **checkpoint**: chạy `python -m pytest -q` và phải đạt hết.

## Global Constraints

- Không thêm thư viện runtime mới.
- Mọi giá trị tiền sau khi chuẩn hóa tính bằng **đồng**. Giá cổ phiếu trong hệ thống tính bằng **nghìn đồng**.
- `TOL = 0.001`. Hai số a, b khớp khi `|a − b| ≤ max(TOL × max(|a|, |b|), 1)`.
- Mệnh giá cổ phiếu 10.000 đồng. Số cổ phiếu hợp lệ nằm trong [1e6, 2e10].
- Mỗi file PDF gọi Gemini tối đa **4** lần: 2 lần trích ban đầu và 1 cặp trích lại.
- Gemini trích xuất với `temperature = 0`.
- Ngưỡng PDF gửi trực tiếp: `INLINE_LIMIT = 20 * 1024 * 1024`.
- Dữ liệu cũ khi `today − period_end > 200 ngày`.
- Ngành: `THEP`, `BDS`, `CHUNG`. Tên file khớp `^\d{4}(Q[1-4]|FY)\.pdf$` (không phân biệt hoa thường).
- Thông báo lỗi bằng tiếng Việt, bắt đầu bằng mã bước (`"F1: ..."` … `"F6: ..."`).
- Status của file: `OK`, `REJECTED`, `ERROR`. Status `ERROR` không được ghi vào `sources`.
- Chỉ số nào không tính được thì trả `None`, không phát sinh exception.

## Review Focus

1. **Giá vốn (IS11) hoặc giảm trừ (IS02) được Gemini trả về số âm** (vì BCTC in trong ngoặc) → lấy trị tuyệt đối trước khi kiểm tra đẳng thức, để không loại oan. IS52 được phép âm. *(Task 1: `test_cost_sign_normalized`)*
2. **Tên file viết thường, ví dụ `2026q3.PDF`** → vẫn được nhận. *(Task 4: `test_filename_case_insensitive`)*
3. **Thư mục có nhiều quý và nhiều năm** → chọn quý mới nhất, và chọn BCTC năm `(năm của quý − 1)FY`. Nếu chỉ có năm khác thì coi như không có BCTC năm. *(Task 4: `test_select_latest_quarter_and_prior_year`)*
4. **Doanh thu thuần (IS10) bằng 0** (doanh nghiệp BĐS chưa bàn giao) → các chỉ số biên lợi nhuận là `None`, không ZeroDivisionError. *(Task 2: `test_zero_revenue`)*
5. **Vốn chủ sở hữu ≤ 0** → `roe_ttm`, `debt_to_equity`, `bvps`, `pb` là `None`. *(Task 2: `test_negative_equity`)*

---

### Task 1: Schema và các bước kiểm tra

**Files:**
- Create: `fundamentals/__init__.py` (rỗng), `fundamentals/schema.py`, `fundamentals/checks.py`
- Test: `tests/fundamentals/__init__.py` (rỗng), `tests/fundamentals/helpers.py`, `tests/fundamentals/test_checks.py`

**Interfaces:**
- Produces trong `schema.py`:
  - `class Unit(str, Enum)`: `DONG`, `NGHIN_DONG`, `TRIEU_DONG`.
  - `LineItem(BaseModel)`: `code: str`; `current`, `prior`, `ytd_current`, `ytd_prior: float | None = None`; `page: int`.
  - `Extraction(BaseModel)`: `unit: Unit`; `period_end: str`; `consolidated: bool`; `items: list[LineItem]`. Có method `get(code) -> LineItem | None`.
  - `CODES: dict[str, str]`: 27 mã kèm tên tiếng Việt, đúng bảng ở spec mục 4.
  - `REQUIRED: frozenset[str]`: các mã đánh dấu ✔ trong spec.
  - `IDENTITIES: list[tuple[str, list[tuple[int, str]]]]`: 7 đẳng thức ở spec mục 5. Ví dụ `("IS20", [(1, "IS10"), (-1, "IS11")])`.
  - `PERIOD_END: dict[str, str]`: `{"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31", "FY": "12-31"}`.
- Produces trong `checks.py`:
  - `values_match(a: float, b: float) -> bool`
  - `compare_runs(a: Extraction, b: Extraction) -> list[str]` (F1)
  - `normalize_units(ex: Extraction) -> Extraction`: đổi về đồng, `unit = DONG`, lấy trị tuyệt đối cho IS11 và IS02.
  - `check_required(ex: Extraction) -> tuple[Extraction, list[str]]` (F3): gán 0 cho mã không bắt buộc bị thiếu.
  - `check_identities(ex: Extraction) -> list[str]` (F4)
  - `check_shares(ex: Extraction) -> list[str]` (F5)
  - `check_period(ex: Extraction, period: str) -> list[str]` (F6). `period` có dạng `"2026Q3"` hoặc `"2025FY"`.
  - `run_checks(a: Extraction, b: Extraction, period: str) -> tuple[Extraction | None, list[str]]`: chạy F1 → chuẩn hóa → F3 → F4 → F5 → F6. Trả về `(bản đã chuẩn hóa của a, [])` nếu đạt, `(None, lỗi)` nếu có lỗi.

**`tests/fundamentals/helpers.py`:** hàm `make_extraction(period="2026Q3", unit=Unit.DONG, **overrides) -> Extraction`. Hàm tạo một BCTC hợp lệ có đủ 27 mã, mọi đẳng thức đều đúng. Số liệu gốc gợi ý:
- BS100 = 6e12, BS200 = 4e12, BS270 = 1e13
- BS310 = 3e12, BS330 = 2e12, BS300 = 5e12, BS400 = 5e12, BS440 = 1e13
- BS411 = 7e12 (tức 700 triệu cổ phiếu)
- IS01 = 2.1e12, IS02 = 1e11, IS10 = 2e12, IS11 = 1.5e12, IS20 = 5e11
- IS50 = 3e11, IS51 = 6e10, IS52 = 0, IS60 = 2.4e11, IS61 = 2.2e11

`overrides` cho phép đổi từng cột của từng mã, hoặc xóa một mã.

- [ ] **Step 1: Viết test thất bại** trong `test_checks.py`:
  - `test_valid_passes`: `run_checks(ex, ex, "2026Q3")` trả về lỗi `[]`.
  - `test_compare_tolerance`: IS10 lệch 0.05% thì không có lỗi. Lệch 0.2% thì có lỗi bắt đầu bằng `"F1:"` và chứa `"IS10"`.
  - `test_compare_missing_code`: lần b thiếu BS140 thì có lỗi F1.
  - `test_unit_trieu`: `unit = TRIEU_DONG` và BS270 = 1e7 thì sau `normalize_units` thì BS270.current == 1e13.
  - `test_each_identity_detected`: lần lượt làm hỏng vế trái của từng đẳng thức trong `IDENTITIES`. Mỗi lần đều có lỗi `"F4:"` chứa đúng mã đó.
  - `test_cost_sign_normalized`: IS11 = −1.5e12 thì không có lỗi F4.
  - `test_missing_required`: xóa BS270 thì có lỗi `"F3:"`. Xóa BS140 thì không có lỗi, và BS140.current == 0.
  - `test_shares_out_of_range`: BS411 = 7e9 (tức 700 nghìn cổ phiếu) thì có lỗi `"F5:"`.
  - `test_period_mismatch`: `period_end = "2026-06-30"` với period `"2026Q3"` thì có lỗi `"F6:"`.

- [ ] **Step 2: Chạy** `python -m pytest tests/fundamentals/test_checks.py -q`. Kỳ vọng: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Cài đặt** `schema.py` và `checks.py` theo Interfaces. `check_identities` kiểm tra trên mọi cột mà tất cả các mã trong đẳng thức đều có giá trị khác None.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Checkpoint.**

---

### Task 2: Tính chỉ số

**Files:**
- Create: `fundamentals/ratios.py`
- Test: `tests/fundamentals/test_ratios.py`

**Interfaces:**
- Consumes: `Extraction`, `make_extraction` (Task 1).
- Produces:
  - `compute_ratios(quarter: Extraction, annual: Extraction | None, sector: str, period: str) -> dict`: các khóa đúng như bảng ở spec mục 6. Khóa riêng của BDS và THEP chỉ có mặt khi đúng ngành.
  - `valuation(ratios: dict, price: float) -> dict`: trả về `{"pe", "pb"}` và thêm `"pe_note"` khi EPS ≤ 0.

- [ ] **Step 1: Viết test thất bại**:
  - `test_ttm_q3_with_annual`: annual IS61.current = 8e11, quý có ytd_current = 6e11 và ytd_prior = 5e11. Kết quả `npat_parent_ttm == 9e11` và `eps_ttm == pytest.approx(9e11 / 7e8)`.
  - `test_ttm_q4_without_annual`: period `"2026Q4"`, `annual=None`, IS61.ytd_current = 9e11. Kết quả `npat_parent_ttm == 9e11`.
  - `test_q3_without_annual`: các khóa `eps_ttm`, `roe_ttm`, `roa_ttm`, `revenue_ttm` là None, còn `gross_margin_q == 0.25`.
  - `test_roe_average_equity`: BS400 current = 5e12, prior = 4e12, BS429 = 0 thì `roe_ttm == round(ttm / 4.5e12, 4)`.
  - `test_yoy`: IS10 current = 2e12, prior = 1.6e12 thì `revenue_yoy_q == 0.25`. Nếu prior = 0 thì None.
  - `test_interest_coverage_none_when_no_interest`: IS23 = 0 thì `interest_coverage` là None.
  - `test_bds_keys`: sector `"BDS"` thì có `customer_advances_to_equity`, `customer_advances_change`, `inventory_to_assets`. Sector `"CHUNG"` thì không có các khóa này.
  - `test_thep_inventory_days`: TTM(IS11) = 6e12, BS140 current = 1.2e12, prior = 1.2e12 thì `inventory_days == pytest.approx(73.0)`.
  - `test_zero_revenue`: IS10 = 0 (mọi cột) thì `gross_margin_q`, `net_margin_q` là None, không phát sinh exception.
  - `test_negative_equity`: BS400 = −1e12 thì `roe_ttm`, `debt_to_equity`, `bvps` là None. `valuation(..., 10.0)["pb"]` là None.
  - `test_valuation`: EPS = 1000, BVPS = 10000, giá 15.0 thì `pe == 15.0` và `pb == 1.5`. EPS = −5 thì `pe` là None và `pe_note == "EPS ≤ 0, P/E không có ý nghĩa"`.

- [ ] **Step 2: Chạy** `python -m pytest tests/fundamentals/test_ratios.py -q`. Kỳ vọng: FAIL.

- [ ] **Step 3: Cài đặt.** Làm tròn mọi tỷ lệ 4 chữ số. Mọi phép chia đi qua một hàm `_div(a, b)`, trả về None khi b là None hoặc b ≤ 0. Riêng các tỷ lệ YoY và biên lợi nhuận cũng trả None khi mẫu số ≤ 0.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Checkpoint.**

---

### Task 3: Trích xuất bằng Gemini

**Files:**
- Create: `fundamentals/extract.py`
- Modify: `llm.py`. Hàm `generate` đổi signature thành `generate(contents: str | list, schema: type[BaseModel], temperature: float = 0.2) -> LLMResult`, tương thích ngược với cách gọi `generate(prompt, schema)`.
- Test: `tests/fundamentals/test_extract.py`

**Interfaces:**
- Consumes: `llm.generate`, `llm.get_client`, `LLMResult` (multi-agent Task 4), `Extraction`, `CODES` (Task 1).
- Produces:
  - `build_extract_prompt(period: str) -> str`
  - `extract_statement(pdf_path: Path, period: str, generate=llm.generate, client_factory=llm.get_client) -> Extraction`

- [ ] **Step 1: Viết test thất bại**:
  - `test_prompt_lists_all_codes`: prompt chứa cả 27 mã trong `CODES`, chuỗi `"trong ngoặc"` (số âm), `"không tính toán"` và `"số trang"`.
  - `test_small_pdf_inline`: file 1 KB trong `tmp_path` và `generate` giả. `contents` truyền vào có một phần tử dạng Part với `mime_type == "application/pdf"`. `temperature == 0`. Không gọi `client_factory().files.upload`.
  - `test_large_pdf_uses_files_api`: monkeypatch `INLINE_LIMIT = 10` với file 1 KB. Có gọi `files.upload(file=pdf_path)` và kết quả upload nằm trong `contents`.
  - `test_returns_extraction`: `generate` giả trả `LLMResult(make_extraction(), "fake", 0.1)` thì hàm trả về đúng đối tượng `Extraction` đó.

- [ ] **Step 2: Chạy** `python -m pytest tests/fundamentals/test_extract.py -q`. Kỳ vọng: FAIL.

- [ ] **Step 3: Cài đặt.**
  - File nhỏ dùng `types.Part.from_bytes(data=..., mime_type="application/pdf")`. File lớn dùng `client.files.upload(file=path)`.
  - `contents = [pdf_part, prompt]`. Gọi `generate(contents, Extraction, temperature=0)`.
  - Sửa `llm.generate` để truyền `temperature` vào `GenerateContentConfig`.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS, kể cả các test cũ của `llm`.

- [ ] **Step 5: Checkpoint.**

---

### Task 4: Lưu trữ và job theo quý

**Files:**
- Create: `fundamentals/store.py`, `fundamentals_job.py`
- Modify: `.env.example`, thêm `SECTORS=HPG:THEP,DXG:BDS,FPT:CHUNG,MWG:CHUNG,VNM:CHUNG`.
- Test: `tests/fundamentals/test_job.py`

**Interfaces:**
- Consumes: `run_checks` (Task 1), `compute_ratios` (Task 2), `extract_statement` (Task 3), `Extraction`.
- Produces:
  - Trong `store.py`:
    - `DATA_DIR = BASE_DIR / "data" / "fundamentals"`
    - `load(symbol: str, data_dir: Path = DATA_DIR) -> dict | None`
    - `save(record: dict, data_dir: Path = DATA_DIR) -> None`
    - `sha256_file(path: Path) -> str`
  - Trong `fundamentals_job.py`:
    - `parse_sectors(value: str) -> dict[str, str]`
    - `select_files(symbol_dir: Path) -> tuple[tuple[Path, str] | None, tuple[Path, str] | None, list[str]]`: trả về (quý, năm, cảnh báo).
    - `process_file(path: Path, period: str, extract_fn) -> tuple[str, Extraction | None, list[str]]`: trả về (status, bản trích, lỗi).
    - `run_job(bctc_dir: Path, data_dir: Path, sectors: dict[str, str], extract_fn) -> int`: trả về exit code.
    - `main()`: CLI dùng `extract_statement`, `BASE_DIR/"data"/"bctc"` và `SECTORS` từ `.env`.

**Logic `process_file`** (dạng bảng vì test không tự xác định được thứ tự này):
1. Trích 2 lần, gọi `run_checks`.
2. Nếu có lỗi, trích thêm 2 lần và gọi `run_checks` với cặp mới.
3. Vẫn lỗi thì trả `REJECTED` kèm lỗi của lần sau.
4. Nếu `extract_fn` phát sinh exception thì trả ngay `("ERROR", None, [str(exc)])`.

**Logic `run_job`** cho mỗi mã có thư mục trong `bctc_dir`:
1. Mã không có trong `sectors` thì in "chưa hỗ trợ mẫu BCTC này" và bỏ qua.
2. Gọi `select_files`. Với mỗi file được chọn: nếu `sha256` trùng với `sources` đã lưu và status đã lưu là `OK` hoặc `REJECTED` thì bỏ qua, ngược lại gọi `process_file`.
3. Ghi `sources[file] = {sha256, status, errors}`, trừ khi status là `ERROR`.
4. Nếu file quý mới đạt `OK`, hoặc file năm mới đạt `OK` trong khi bản quý đã lưu là của đúng quý hiện tại: lấy bản quý (mới, hoặc `raw.quarter` đã lưu) và bản năm (mới, `raw.annual` đã lưu, hoặc None), tính lại `ratios` và cập nhật `period`, `period_end`, `annual_period`, `raw`, `status = "OK"`, `updated_at`.
5. Nếu file quý mới bị `REJECTED` thì giữ nguyên `ratios` và `raw` cũ. Nếu chưa từng có dữ liệu quý hợp lệ thì `status = "REJECTED"`.
6. Exit code là 1 nếu có ít nhất một file `ERROR`, ngược lại là 0.

- [ ] **Step 1: Viết test thất bại.** Dùng `tmp_path` với các file PDF giả (nội dung byte tùy ý). `extract_fn` giả trả về `make_extraction(period)` và đếm số lần gọi.
  - `test_new_files_ok`: có `DXG/2026Q3.pdf` và `DXG/2025FY.pdf`. File `DXG.json` có `status == "OK"`, `period == "2026Q3"`, `annual_period == "2025FY"`, `ratios` có khóa BDS. `extract_fn` được gọi 4 lần. Exit code 0.
  - `test_rerun_skips`: chạy lại lần 2 thì `extract_fn` không được gọi thêm.
  - `test_filename_case_insensitive`: file `2026q3.PDF` vẫn được xử lý.
  - `test_bad_filename_warned`: file `bctc_q3.pdf` bị bỏ qua và nằm trong danh sách cảnh báo của `select_files`.
  - `test_select_latest_quarter_and_prior_year`: có `2026Q2`, `2026Q3`, `2024FY`, `2025FY` thì chọn `2026Q3` và `2025FY`. Nếu chỉ có `2024FY` thì phần năm là None.
  - `test_retry_pair_then_ok`: lần trích thứ 2 lệch IS10 0.2%, lần 3 và 4 đúng. Status `OK`, tổng 4 lần gọi cho file quý.
  - `test_rejected_keeps_old`: chạy lần 1 OK. Thay nội dung `2026Q3.pdf` (mã băm đổi) và cho `extract_fn` trả dữ liệu sai đẳng thức. `sources["2026Q3.pdf"].status == "REJECTED"` và `ratios` vẫn giữ nguyên như lần 1.
  - `test_gemini_error_not_recorded`: `extract_fn` phát sinh `RuntimeError`. Exit code 1 và `"2026Q3.pdf"` không có trong `sources`.
  - `test_unsupported_sector_skipped`: thư mục `VCB/` không có trong sectors thì không có `VCB.json` và `extract_fn` không được gọi.

- [ ] **Step 2: Chạy** `python -m pytest tests/fundamentals/test_job.py -q`. Kỳ vọng: FAIL.

- [ ] **Step 3: Cài đặt** theo logic ở trên. Lưu `raw` bằng `model_dump(mode="json")` và đọc lại bằng `Extraction.model_validate`.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Checkpoint.**

---

### Task 5: Gắn vào multi-agent

> Chỉ làm khi kế hoạch multi-agent đã hoàn thành.

**Files:**
- Modify: `agents.py`, `validator.py`, `orchestrator.py`, `main.py`
- Test: `tests/fundamentals/test_integration.py`

**Interfaces:**
- Consumes: `store.load` (Task 4), `valuation` (Task 2), và các hàm của multi-agent.
- Produces (thay đổi signature, tham số mới đều có mặc định `None` để test cũ vẫn chạy):
  - `agents.format_fundamentals_block(f: dict | None, today: date) -> str`
  - `agents.build_analyst_prompt(symbol, metrics, levels, fundamentals: dict | None = None)`
  - `agents.build_critic_prompt(symbol, metrics, levels, analyst, warnings, fundamentals: dict | None = None)`
  - `validator.validate(analysis, levels, metrics, fundamentals: dict | None = None)`
  - `orchestrator.run_pipeline(symbol, metrics, levels, generate, fundamentals: dict | None = None)`
  - `main.scan_symbol` trả về `(metrics, levels, fundamentals)`. `fundamentals` là `{**record["ratios"], **valuation(record["ratios"], close), "period": ..., "period_end": ...}` khi `store.load` trả về bản ghi có `ratios`, ngược lại là None.

- [ ] **Step 1: Viết test thất bại**:
  - `test_block_none`: `format_fundamentals_block(None, ...)` trả về chuỗi chứa `"Chưa có dữ liệu cơ bản - cần kiểm tra BCTC"`.
  - `test_block_values`: dữ liệu `{"roe_ttm": 0.1234, "pe": 12.5, "period": "2026Q3", "period_end": "2026-09-30", "eps_ttm": None}`. Block chứa `"12.34%"`, `"12.5"`, `"2026Q3"` và không chứa `"eps_ttm"` (bỏ giá trị None).
  - `test_block_stale`: `period_end = "2026-03-31"` với `today = 2026-11-06` thì block chứa `"Dữ liệu cơ bản đã cũ"`.
  - `test_analyst_prompt_includes_block`: prompt của Analyst có fundamentals thì chứa `"DỮ LIỆU CƠ BẢN"`.
  - `test_s3_real_roe_ok`: `fundamental_analysis = "ROE 12.34%, P/E 12.5"` thì không có cảnh báo S3.
  - `test_s3_invented_roe_flagged`: `fundamental_analysis = "ROE 25.5%"` thì có cảnh báo S3 chứa `"25.5"`.
  - `test_pipeline_passes_fundamentals`: dùng `FakeGenerate` của multi-agent. Prompt đầu tiên chứa `"DỮ LIỆU CƠ BẢN"`.

- [ ] **Step 2: Chạy** `python -m pytest tests/fundamentals/test_integration.py -q`. Kỳ vọng: FAIL.

- [ ] **Step 3: Cài đặt.**
  - Định dạng trong block: tỷ lệ hiển thị theo % với 2 chữ số, P/E và P/B hiển thị theo lần, giá trị tiền hiển thị theo tỷ đồng.
  - Danh sách tham chiếu S3 lấy mọi giá trị số trong `fundamentals`, cùng dạng ×100 và ÷1e9.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS, toàn bộ test cũ của multi-agent vẫn đạt.

- [ ] **Step 5: Checkpoint.**

---

### Task 6: Tài liệu và chạy thật

**Files:**
- Modify: tài liệu yêu cầu `C:\Users\tnguyenhuu\Downloads\t_i_li_u_ti_n_y_u_c_u_h_th_ng_stock_agent.md`. Sửa FR-04, FR-05, thêm lệnh `python fundamentals_job.py` vào phần cách chạy và bổ sung bảng file.
- Modify: `.env`. Thêm `SECTORS` nếu chưa có.

- [ ] **Step 1:** người dùng đặt `data/bctc/DXG/2026Q3.pdf` và `data/bctc/DXG/2025FY.pdf`.
- [ ] **Step 2:** chạy `python fundamentals_job.py`. Kỳ vọng: `data/fundamentals/DXG.json` có `status` là `OK`. Nếu là `REJECTED`, ghi lại lỗi và báo cho người dùng, không sửa ngưỡng để ép kết quả qua.
- [ ] **Step 3:** so sánh thủ công BS270, BS400, IS10, IS61, CF20 trong `raw` với trang PDF được ghi trong `page`. Báo kết quả cho người dùng.
- [ ] **Step 4:** chạy `python main.py --once --force --symbols DXG`. Kỳ vọng: `final.fundamental_analysis` có số liệu thật và không có cảnh báo S3 cho các số đó.
- [ ] **Step 5:** cập nhật tài liệu yêu cầu, rồi checkpoint cuối.
