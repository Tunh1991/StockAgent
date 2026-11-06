# Multi-Agent Analyst – Validator – Critic: Kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay lần gọi Gemini duy nhất bằng chuỗi Analyst (LLM) → Validator (Python) → Critic (LLM, chỉ khi MUA GOM), trong đó Python có quyết định cuối.

**Architecture:** `indicators.py` tính thêm ATR, đỉnh 60/120 phiên và danh sách mốc giá được phép. `validator.py` là code thuần, kiểm tra kế hoạch giao dịch theo luật H1–H5 và S1–S3. `orchestrator.py` điều phối các agent qua một hàm `generate` được truyền vào, nên kiểm thử được bằng LLM giả. `main.py` chỉ còn vòng quét và CLI.

**Tech Stack:** Python 3.11, pandas, numpy, pydantic v2, google-genai, pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-multi-agent-design.md`

**Lưu ý về commit:** thư mục `Stock` chưa phải git repository. Bước cuối của mỗi task là **checkpoint**: chạy toàn bộ test (`python -m pytest -q`) và phải đạt hết. Nếu người dùng chạy `git init` trước, hãy commit tại mỗi checkpoint.

## Global Constraints

- Python 3.11+. Không thêm thư viện runtime mới. `pytest` chỉ dùng để kiểm thử.
- Tối đa **3** lần gọi `generate` cho mỗi tín hiệu (Analyst, sửa lỗi, Critic).
- `PRICE_TOLERANCE = 0.005`, `MIN_RR = 1.5`, `MAX_CHASE = 1.02`, `MAX_STOP_PCT = 0.07`, `RSI_OVERBOUGHT = 75`.
- Giá theo đơn vị nghìn đồng, làm tròn 2 chữ số.
- Tín hiệu chỉ có 3 giá trị `MUA GOM`, `QUAN SAT`, `BO QUA`. Kết quả của Critic chỉ có 3 giá trị `GIU_NGUYEN`, `GIAM_TIN_CAY`, `HA_CAP`.
- `confidence_score` nằm trong [1.0, 10.0]. `confidence_adjustment` nằm trong [−5.0, 0].
- Status chỉ có 4 giá trị: `OK`, `VALIDATION_FAILED`, `CRITIC_FAILED`, `ANALYST_FAILED`.
- Mọi thông báo lỗi và cảnh báo viết bằng tiếng Việt, bắt đầu bằng mã luật (`"H1: ..."`, `"S3: ..."`).
- `symbol` trong kết quả luôn lấy từ code, không lấy từ LLM.
- Không gọi mạng trong test.

## Review Focus

1. **Analyst bỏ trống `target_2` (null)** → bỏ qua phần so sánh `target_1 < target_2`, không được crash. *(Task 2: `test_target2_optional`)*
2. **Tên mốc khác chữ hoa/thường hoặc có khoảng trắng (`" ma20"`)** → chuẩn hóa bằng `strip().upper()` trước khi so khớp. *(Task 2: `test_level_name_normalized`)*
3. **Số trong phần chữ dùng dấu phẩy thập phân (`"10,8"`)** → hiểu là 10.8, khớp với số liệu, không cảnh báo S3. *(Task 2: `test_s3_comma_decimal`)*
4. **`entry_high == stop_loss`** (R:R chia cho 0) → báo lỗi H2, không được ZeroDivisionError. *(Task 2: `test_rr_zero_risk_no_crash`)*
5. **Lịch sử ngắn làm ATR hoặc HIGH_120 bị NaN** → `price_levels` bỏ các mốc NaN. Nhóm `target` vẫn có ít nhất 2 mốc khi ATR có giá trị. *(Task 1: `test_nan_levels_dropped`)*

---

### Task 1: Chỉ báo mới và danh sách mốc giá

**Files:**
- Modify: `indicators.py` (`compute_technical_indicators`, thêm `PriceLevel` và `price_levels`)
- Test: `tests/test_levels.py`
- Create: `tests/__init__.py` (rỗng), `conftest.py` ở thư mục gốc (rỗng, để pytest import được module ở gốc)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class PriceLevel: name: str; price: float; groups: tuple[str, ...]`, kèm `to_dict() -> dict` trả về `{"name", "price", "groups": list}`.
  - `price_levels(df: pd.DataFrame) -> list[PriceLevel]`, dùng hàng cuối của df đã qua `compute_technical_indicators`.
  - Cột mới: `ATR`, `HIGH_60`, `HIGH_120`.

- [ ] **Step 1: Viết test thất bại** trong `tests/test_levels.py`:
  - `test_atr_wilder`: df 30 phiên với `high = close + 1`, `low = close − 1` và `close` không đổi, nên TR luôn bằng 2. Kiểm tra `ATR.iloc[-1] == pytest.approx(2.0)` và `ATR.iloc[12]` là NaN.
  - `test_high_60_excludes_current`: 70 phiên `high = 10`, phiên cuối `high = 20`. Kiểm tra `HIGH_60.iloc[-1] == 10`.
  - `test_groups_by_side_of_close`: 130 phiên có xu hướng tăng. Mọi mốc trong nhóm `"stop"` có `price < close`, mọi mốc trong `"target"` có `price > close`, mọi mốc trong `"entry"` có `price <= close * 1.02`. `CLOSE` thuộc nhóm `entry`.
  - `test_target_has_atr_levels`: tên `ATR_T2` và `ATR_T3` luôn có trong nhóm `target`, đúng bằng `round(C + 2*ATR, 2)` và `round(C + 3*ATR, 2)`.
  - `test_measured_move`: `MEASURED_MOVE == round(R + (R − S), 2)` với R = `RESISTANCE`, S = `SUPPORT`, chỉ khi giá trị này > C. Nếu không thì không có mốc này.
  - `test_nan_levels_dropped`: df 60 phiên, nên `HIGH_120` là NaN. Không có mốc nào tên `HIGH_120` và không mốc nào có giá NaN.

- [ ] **Step 2: Chạy** `python -m pytest tests/test_levels.py -q`. Kỳ vọng: FAIL (ImportError `price_levels`).

- [ ] **Step 3: Cài đặt** trong `indicators.py`:
  - ATR theo spec mục 3: `TR = max(high−low, |high−prev_close|, |low−prev_close|)`, `ewm(alpha=1/14, min_periods=14, adjust=False)`.
  - `HIGH_60` và `HIGH_120` dùng `high.shift(1).rolling(n).max()`.
  - Ứng viên và tên nhóm lấy đúng như bảng ở spec mục 3. Nhóm `entry` lọc `≤ C × MAX_CHASE`, nhóm `stop` lọc `< C`, nhóm `target` lọc `> C`. Mốc không thuộc nhóm nào thì bỏ.
  - Thêm hằng số `MAX_CHASE = 1.02` vào `indicators.py`.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Checkpoint.**

---

### Task 2: Validator

**Files:**
- Create: `validator.py`
- Test: `tests/test_validator.py`

**Interfaces:**
- Consumes: `PriceLevel` (Task 1).
- Produces:
  - `@dataclass class ValidationResult: errors: list[str]; warnings: list[str]`, kèm property `passed -> bool` (đúng khi `not errors`).
  - `validate(analysis: dict, levels: list[PriceLevel], metrics: dict) -> ValidationResult`. `analysis` là `AnalystResult.model_dump(mode="json")`, schema ở Task 3. Các khóa dùng tới: `signal`, `orderflow_analysis`, `red_flags`, `plan.{entry_low, entry_high, stop_loss, target_1, target_2}`, mỗi mốc có dạng `{level, price}`.
  - Các hằng số trong Global Constraints, định nghĩa ở đầu `validator.py`.

**Fixture DXG** (đặt trong test, lấy từ lần chạy thật 06/11, giả sử ATR = 0.3):
```python
C = 11.0
METRICS = {"close": 11.0, "ma20": 10.23, "ma50": 10.52, "ema20": 10.29, "rsi": 64.8,
           "vol_spike_ratio": 2.78, "volume": 31627400, "vol_projected": 31627400,
           "vol_ma20": 11365770, "support": 9.37, "resistance": 10.8,
           "macd": 0.0422, "macd_signal": -0.0665, "macd_hist": 0.1086}
LEVELS = [PriceLevel("CLOSE", 11.0, ("entry",)), PriceLevel("MA20", 10.23, ("entry", "stop")),
          PriceLevel("EMA20", 10.29, ("entry", "stop")), PriceLevel("MA50", 10.52, ("entry", "stop")),
          PriceLevel("SUPPORT_20", 9.37, ("entry", "stop")), PriceLevel("RESISTANCE_20", 10.8, ("entry",)),
          PriceLevel("ATR_STOP", 10.55, ("stop",)), PriceLevel("ATR_T2", 11.6, ("target",)),
          PriceLevel("ATR_T3", 11.9, ("target",)), PriceLevel("MEASURED_MOVE", 12.23, ("target",))]
VALID_PLAN = {"entry_low": {"level": "MA50", "price": 10.52},
              "entry_high": {"level": "RESISTANCE_20", "price": 10.8},
              "stop_loss": {"level": "EMA20", "price": 10.29},
              "target_1": {"level": "ATR_T3", "price": 11.9},
              "target_2": {"level": "MEASURED_MOVE", "price": 12.23}, "t_plus_risk": "..."}
```
Hàm hỗ trợ trong test: `make(signal="MUA GOM", text="", **plan_overrides)`, trả về dict analysis.

- [ ] **Step 1: Viết test thất bại**:
  - `test_valid_plan_passes`: `passed` là True, `errors == []`.
  - `test_dxg_invented_target_blocked`: `target_1 = {"level": "TARGET", "price": 12.0}`. Có lỗi bắt đầu bằng `"H1:"` và chứa `"target_1"` cùng `"ATR_T2=11.6"`, tức thông báo liệt kê các mốc mục tiêu hợp lệ.
  - `test_h1_price_mismatch`: `target_1 = {"level": "ATR_T3", "price": 12.1}` (lệch 1.7%). Có lỗi `"H1:"`.
  - `test_h1_price_within_tolerance`: `price` 11.93 (lệch 0.25%). Không có lỗi H1.
  - `test_h2_order`: đổi chỗ `entry_low` và `entry_high`. Có lỗi `"H2:"`.
  - `test_h3_wrong_group`: `stop_loss = {"level": "ATR_T2", "price": 11.6}`. Có lỗi `"H3:"` chứa `"stop_loss"`.
  - `test_h4_rr`: `stop_loss = SUPPORT_20 9.37` và `target_1 = ATR_T2 11.6`, R:R ≈ 0.56. Có lỗi `"H4:"`. Cùng kế hoạch đó với `signal = "QUAN SAT"` thì không có lỗi H4.
  - `test_h5_chase`: `entry_high = {"level": "ATR_T2", "price": 11.6}` với MUA GOM. Có lỗi `"H5:"`.
  - `test_s1_rsi`: `metrics["rsi"] = 80`, MUA GOM. Có cảnh báo `"S1:"`. Kết quả vẫn `passed`.
  - `test_s2_wide_stop`: `stop_loss = SUPPORT_20 9.37`, `target_1 = MEASURED_MOVE 12.23`, `target_2 = None`. Có cảnh báo `"S2:"` (khoảng cắt lỗ 13.2%).
  - `test_s3_invented_number`: text `"Giá 11.0 vượt 10.8 trong 20 phiên, khối lượng 31.62 triệu, gấp 2.78 lần, mục tiêu 12.75"`. Đúng 1 cảnh báo S3 và cảnh báo đó chứa `"12.75"`.
  - `test_s3_comma_decimal`: text `"vượt 10,8"`. Không có cảnh báo S3.
  - `test_s3_scans_red_flags`: `red_flags = ["chốt lời tại 13.5"]`. Có cảnh báo S3 chứa `"13.5"`.
  - `test_target2_optional`: `target_2 = None`. `passed` là True.
  - `test_level_name_normalized`: `entry_low = {"level": " ma50", "price": 10.52}`. `passed` là True.
  - `test_rr_zero_risk_no_crash`: `stop_loss = {"level": "MA50", "price": 10.52}` và `entry_low = entry_high = MA50`. Có lỗi `"H2:"` và không phát sinh exception.

- [ ] **Step 2: Chạy** `python -m pytest tests/test_validator.py -q`. Kỳ vọng: FAIL (ModuleNotFoundError).

- [ ] **Step 3: Cài đặt `validate`** theo spec mục 5.
  - Chỉ tính R:R (H4) khi H2 đạt, để tránh chia cho 0.
  - Số liệu tham chiếu cho S3: mọi giá trị số trong `metrics`, giá của các mốc, `volume`/`vol_projected`/`vol_ma20` chia cho 1e6 và cho 1e3.
  - Regex lấy số thập phân: `r"\d+[.,]\d+"`, đổi `,` thành `.`. Không xét số nguyên.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Checkpoint.**

---

### Task 3: Schema và prompt của các agent

**Files:**
- Create: `agents.py`
- Test: `tests/test_agents.py`

**Interfaces:**
- Consumes: `PriceLevel` (Task 1).
- Produces:
  - Enum `Signal(str, Enum)` gồm `MUA GOM`, `QUAN SAT`, `BO QUA`. Enum `Verdict(str, Enum)` gồm `GIU_NGUYEN`, `GIAM_TIN_CAY`, `HA_CAP`.
  - `PriceRef(BaseModel): level: str; price: float`.
  - `TradePlan(BaseModel)`: `entry_low`, `entry_high`, `stop_loss`, `target_1: PriceRef`; `target_2: PriceRef | None = None`; `t_plus_risk: str`.
  - `AnalystResult(BaseModel)`: các trường như spec mục 4. `confidence_score: float = Field(ge=1.0, le=10.0)`.
  - `CriticResult(BaseModel)`: `verdict: Verdict`, `confidence_adjustment: float = Field(ge=-5.0, le=0.0)`, `counter_arguments: list[str]`, `reason: str`.
  - `build_analyst_prompt(symbol: str, metrics: dict, levels: list[PriceLevel]) -> str`.
  - `build_fix_prompt(base_prompt: str, previous: dict | None, errors: list[str]) -> str`.
  - `build_critic_prompt(symbol: str, metrics: dict, levels: list[PriceLevel], analyst: dict, warnings: list[str]) -> str`.

- [ ] **Step 1: Viết test thất bại**:
  - `test_analyst_confidence_bounds`: `confidence_score = 11` gây `ValidationError`.
  - `test_target2_defaults_none`: `TradePlan` không có `target_2` thì `target_2` là `None`.
  - `test_critic_adjustment_positive_rejected`: `confidence_adjustment = 1.0` gây `ValidationError`.
  - `test_analyst_prompt_lists_levels_by_group`: prompt chứa `"ATR_T2"`, `"11.6"`, tiêu đề cho cả 3 nhóm (`"entry"`, `"stop"`, `"target"`), chuỗi `"Chưa có dữ liệu cơ bản - cần kiểm tra BCTC"`, và yêu cầu chỉ dùng mốc trong bảng.
  - `test_fix_prompt_contains_errors`: prompt chứa nguyên văn từng lỗi trong danh sách.
  - `test_critic_prompt_role`: prompt chứa `"KHÔNG nên mua"` và nội dung JSON của Analyst.

- [ ] **Step 2: Chạy** `python -m pytest tests/test_agents.py -q`. Kỳ vọng: FAIL.

- [ ] **Step 3: Cài đặt.**
  - Prompt Analyst giữ các quy tắc chống ảo giác của `main.build_prompt` hiện tại: đơn vị nghìn đồng, câu cố định cho phần cơ bản, rủi ro T+2. Thêm bảng mốc giá theo nhóm và yêu cầu mỗi mốc trong plan phải ghi đúng `level` và `price` lấy từ bảng.
  - Prompt Critic: vai trò phản biện, chỉ được giảm điểm (adjustment từ −5 đến 0), và chỉ dùng số liệu được cung cấp.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Checkpoint.**

---

### Task 4: Tách `llm.py` khỏi `main.py`

**Files:**
- Create: `llm.py`. Chuyển nguyên từ `main.py`: `load_env`, `RateLimiter`, `get_client`, `_is_retryable`, `_is_model_unavailable`, `_generate`, cùng các hằng số `GEMINI_*` và `LATENCY_TARGET_SEC`.
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces:
  - `@dataclass class LLMResult: parsed: BaseModel; model: str; latency_sec: float`.
  - `generate(prompt: str, schema: type[BaseModel]) -> LLMResult`.
    - Gặp lỗi tạm thời thì thử lại và chuyển model dự phòng, như hiện tại.
    - Nếu `response.parsed` không phải instance của `schema` thì dùng `schema.model_validate_json(response.text)`. JSON sai schema sẽ phát sinh `pydantic.ValidationError`.
    - Khi mọi model đều thất bại thì phát sinh `RuntimeError`.
- `load_env(BASE_DIR / ".env")` chạy khi import `llm.py`.

- [ ] **Step 1: Viết test thất bại**, dùng `monkeypatch` thay `llm.get_client` bằng client giả có `models.generate_content`. Đặt `GEMINI_RETRY_BASE_SEC = 0` và `gemini_limiter.min_interval = 0`:
  - `test_retry_then_success`: lần 1 phát sinh `errors.ServerError(503, {...})`, lần 2 trả response có `.parsed`. `LLMResult.model` là model chính.
  - `test_fallback_on_404`: model chính trả lỗi 404. Kết quả dùng model dự phòng đầu tiên.
  - `test_all_fail_raises`: mọi lần gọi đều 503 thì phát sinh `RuntimeError`.
  - `test_invalid_json_raises`: `.parsed = None`, `.text = "{}"` thì phát sinh `pydantic.ValidationError`.

- [ ] **Step 2: Chạy** `python -m pytest tests/test_llm.py -q`. Kỳ vọng: FAIL.

- [ ] **Step 3: Cài đặt.** Chuyển code từ `main.py` sang `llm.py`. Hàm `generate` thay cho phần gọi Gemini trong `analyze_with_gemini`. Chưa xóa gì trong `main.py`, việc đó làm ở Task 6.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Checkpoint.**

---

### Task 5: Orchestrator

**Files:**
- Create: `orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes:
  - `validate`, `ValidationResult` (Task 2).
  - `AnalystResult`, `CriticResult`, các hàm `build_*_prompt` (Task 3).
  - `LLMResult` (Task 4).
  - `PriceLevel.to_dict()` (Task 1).
- Produces: `run_pipeline(symbol: str, metrics: dict, levels: list[PriceLevel], generate: Callable[[str, type[BaseModel]], LLMResult]) -> dict`. Trả về bản ghi đúng như spec mục 6, chưa có khóa `time` (do `main.py` thêm).

**Test double:** lớp `FakeGenerate(outputs: list)`. Mỗi lần gọi lấy phần tử tiếp theo: nếu là Exception thì phát sinh, nếu là model thì bọc vào `LLMResult(obj, "fake", 0.1)`. Lớp này ghi lại danh sách `schema` đã được yêu cầu. Dùng lại fixture DXG từ Task 2, chuyển sang `tests/fixtures.py`.

- [ ] **Step 1: Viết test thất bại**:
  - `test_quan_sat_single_call`: Analyst QUAN SAT hợp lệ. `status == "OK"`, có 1 lần gọi, `critic` là None.
  - `test_mua_gom_with_critic_keep`: Analyst MUA GOM hợp lệ (confidence 8), Critic `GIU_NGUYEN` với adjustment 0. Có 2 lần gọi, `final.signal == "MUA GOM"`, confidence 8.
  - `test_fix_once_then_pass`: Analyst lần đầu có target bịa, lần sau hợp lệ, kết quả QUAN SAT. `validation.attempts == 2`, `validation.passed` là True. Prompt của lần gọi thứ 2 chứa `"H1:"`.
  - `test_fix_fails_downgrades`: cả 2 lần đều có target bịa, tín hiệu MUA GOM với confidence 8. `status == "VALIDATION_FAILED"`, `final.signal == "QUAN SAT"`, `final.confidence_score == 5.0`, có red_flag bắt đầu bằng `"Kế hoạch không qua kiểm tra"`. Không gọi Critic, tổng 2 lần gọi.
  - `test_fix_call_error_downgrades`: lần 2 phát sinh `RuntimeError`. Kết quả `VALIDATION_FAILED`.
  - `test_invalid_json_triggers_fix`: lần 1 phát sinh `pydantic.ValidationError`, lần 2 hợp lệ. `status == "OK"`.
  - `test_critic_ha_cap`: Critic `HA_CAP` với adjustment −2. `final.signal == "QUAN SAT"`, confidence 6.0, `counter_arguments` được gộp vào `red_flags`.
  - `test_critic_floor`: confidence 2, adjustment −5. Confidence cuối là 1.0.
  - `test_critic_error_downgrades`: Critic phát sinh `RuntimeError`. `status == "CRITIC_FAILED"`, kết quả QUAN SAT, có red_flag `"Chưa được phản biện (Critic lỗi)"`.
  - `test_analyst_failed`: lần 1 phát sinh `RuntimeError`. `status == "ANALYST_FAILED"`, chỉ 1 lần gọi.
  - `test_max_three_calls`: lần 1 sai, lần 2 sửa thành MUA GOM hợp lệ, Critic chạy. Đúng 3 lần gọi.
  - `test_symbol_from_code`: Analyst trả `symbol = "XXX"` thì `final.symbol == "DXG"`.
  - `test_warnings_merged`: text có số bịa thì `final.red_flags` chứa cảnh báo `"S3:"`.

- [ ] **Step 2: Chạy** `python -m pytest tests/test_orchestrator.py -q`. Kỳ vọng: FAIL.

- [ ] **Step 3: Cài đặt** theo spec mục 6.
  - Lỗi khi gọi lần 1 chia làm hai loại: `ValidationError` (JSON sai) thì vào nhánh sửa lỗi, mọi exception khác thì trả `ANALYST_FAILED`.
  - Áp dụng Critic: `max(1.0, conf + min(0, adj))`.
  - `final.red_flags` = red_flags của Analyst + các cảnh báo S + các counter_arguments, bỏ trùng và giữ nguyên thứ tự.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Checkpoint.**

---

### Task 6: Tích hợp `main.py`, tài liệu và chạy thật

**Files:**
- Modify: `main.py`
  - Xóa phần đã chuyển sang `llm.py` và `agents.py` (schema cũ, `build_prompt`, `analyze_with_gemini`).
  - `scan_symbol` trả về `(metrics, levels)`.
  - `run_scan` gọi `run_pipeline(symbol, metrics, levels, llm.generate)`.
  - `HISTORY_BARS = 160`.
- Modify: `requirements.txt` (thêm `pytest` với ghi chú chỉ dùng để kiểm thử).
- Modify: `C:\Users\tnguyenhuu\Downloads\t_i_li_u_ti_n_y_u_c_u_h_th_ng_stock_agent.md` (NFR-02 schema mới, bảng file, mục kiến trúc multi-agent).
- Rename: `signals.jsonl` → `signals_v1.jsonl`.
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `run_pipeline` (Task 5), `llm.generate` (Task 4), `price_levels` (Task 1).

- [ ] **Step 1: Viết test thất bại**, dùng `monkeypatch` thay `main.get_stock_history` (trả df giả 160 phiên có breakout) và `main.run_pipeline` (trả bản ghi giả):
  - `test_ok_record_saved_and_marked`: status `OK`. Một dòng được ghi vào file signals (đã monkeypatch `SIGNALS_FILE` sang `tmp_path`), dòng đó có khóa `time`, và `(symbol, date)` có trong `analyzed_today`.
  - `test_analyst_failed_not_saved`: status `ANALYST_FAILED`. Không ghi file, không đánh dấu `analyzed_today`.
  - `test_validation_failed_saved`: status `VALIDATION_FAILED`. Có ghi file và có đánh dấu.

- [ ] **Step 2: Chạy** `python -m pytest tests/test_main.py -q`. Kỳ vọng: FAIL.

- [ ] **Step 3: Cài đặt.** Khi in ra console, in `record["final"]` cùng `status`.

- [ ] **Step 4: Chạy** `python -m pytest -q`. Kỳ vọng: PASS.

- [ ] **Step 5: Kiểm tra dry-run:** `python main.py --once --dry-run --symbols HPG DXG`. Kỳ vọng: không lỗi, log in ra metrics.

- [ ] **Step 6: Chạy thật:** `python main.py --once --force --symbols DXG HPG`. Kỳ vọng với mỗi mã: có bản ghi trong `signals.jsonl`. Nếu status là `OK` thì mọi mốc trong `final.plan` thuộc danh sách `levels`. So sánh DXG với kết quả cũ (mục tiêu bịa 12.0–12.5) và ghi nhận model, độ trễ của từng bước. Nếu Gemini quá tải (`ANALYST_FAILED`), ghi lại kết quả đó; không coi là lỗi của code.

- [ ] **Step 7: Cập nhật tài liệu yêu cầu** theo spec mục 9, rồi checkpoint cuối.
