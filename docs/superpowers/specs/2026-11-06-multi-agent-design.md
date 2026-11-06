# Đặc tả thiết kế: Multi-Agent Analyst – Validator – Critic

**Ngày:** 06/11/2026
**Trạng thái:** Chờ duyệt
**Phạm vi:** Thay lần gọi Gemini duy nhất trong `main.py` bằng chuỗi Analyst (LLM) → Validator (Python) → Critic (LLM) có điều phối.

---

## 1. Mục tiêu và bối cảnh

**Mục tiêu chính:** tăng độ chính xác, chặn số liệu bịa và khuyến nghị yếu trước khi tín hiệu được lưu hoặc gửi đi.

**Vấn đề thực tế đã gặp (06/11/2026):** với DXG, Gemini khuyến nghị MUA GOM với mục tiêu 12.0–12.5. Mọi mức giá được cung cấp đều dưới 11.0, nên mục tiêu này không có trong dữ liệu đầu vào. Hiện tại không có gì phát hiện được lỗi này.

**Ràng buộc:**
- Chi phí 0đ: Gemini free tier, thường xuyên gặp lỗi 503/504, mỗi lần gọi mất 8–12 giây.
- Tối đa 3 lần gọi LLM cho mỗi tín hiệu.
- Python 3.11+, không thêm thư viện runtime mới (`pytest` chỉ dùng để kiểm thử).

**Các quyết định đã chốt:**
1. Hướng A: Analyst + Validator Python + Critic (Critic chỉ chạy khi tín hiệu là MUA GOM).
2. Mục tiêu giá do Python tính sẵn. Analyst chỉ được chọn trong danh sách mốc được phép.
3. Khi Validator phát hiện lỗi: cho Analyst sửa 1 lần, nếu vẫn lỗi thì hạ xuống QUAN SAT.
4. Quyết định cuối cùng luôn do code Python đưa ra, không LLM nào có lời cuối.

**Ngoài phạm vi:** dữ liệu cơ bản/BCTC (FR-04, FR-05), Telegram, function calling.

---

## 2. Kiến trúc

```
Rule Engine (Python) ──tín hiệu──► Orchestrator
                                     │
             1. Analyst (LLM) ─► 2. Validator (Python) ─lỗi─► Analyst sửa 1 lần
                                     │ đạt                      │ vẫn lỗi → hạ QUAN SAT
                                     ▼
                         signal == MUA GOM ? ─có─► 3. Critic (LLM) ─► 4. Quyết định cuối (Python)
                                     │ không                                  │
                                     └────────────────────► signals.jsonl ◄───┘
```

### Quyền hạn

| Thành phần | Loại | Quyền |
|---|---|---|
| Analyst | LLM | Chỉ đề xuất |
| Validator | Python | Chặn (luật H), cảnh báo (luật S) |
| Critic | LLM | Chỉ được giảm độ tin cậy hoặc hạ MUA GOM → QUAN SAT |
| Quyết định cuối | Python | Áp dụng kết quả của Validator và Critic theo luật cố định |

### Cấu trúc file

| File | Nhiệm vụ | Phụ thuộc |
|---|---|---|
| `data_loader.py` | Lấy OHLCV (giữ nguyên) | `requests`, `pandas` |
| `indicators.py` | Chỉ báo + ATR(14), HIGH_60, HIGH_120 + `price_levels()` | `pandas`, `numpy` |
| `llm.py` | `generate(prompt, schema) -> LLMResult`: client Gemini, thử lại, model dự phòng, timeout, rate limiter (chuyển từ `main.py`) | `google-genai` |
| `agents.py` | Schema Pydantic + hàm tạo prompt cho Analyst và Critic | `pydantic` |
| `validator.py` | `validate(analysis, levels, metrics) -> ValidationResult`, code thuần | không có |
| `orchestrator.py` | `run_pipeline(symbol, metrics, levels, generate) -> dict` | `agents`, `validator` |
| `main.py` | Vòng quét, CLI, lưu `signals.jsonl` | các module trên |

`orchestrator.run_pipeline` nhận hàm `generate` qua tham số, để khi kiểm thử có thể thay bằng LLM giả, không cần gọi mạng.

---

## 3. Danh sách mốc giá được phép (`indicators.price_levels`)

Đầu vào là DataFrame đã tính chỉ báo. Đầu ra là danh sách các mốc `{name, price, groups}`, giá làm tròn 2 chữ số.

### Chỉ báo mới trong `compute_technical_indicators`
- `ATR`: ATR(14) chuẩn Wilder. `TR = max(high-low, |high-prev_close|, |low-prev_close|)`, sau đó `ewm(alpha=1/14, min_periods=14, adjust=False)`.
- `HIGH_60`, `HIGH_120`: `high.shift(1).rolling(60 / 120).max()`.
- `HISTORY_BARS` trong `main.py` tăng từ 120 lên **160**, đủ dữ liệu cho HIGH_120. `MIN_BARS` giữ nguyên 51. Mốc nào bị NaN thì bị bỏ qua.

### Các mốc (C = giá hiện tại)

| Tên | Giá trị |
|---|---|
| `CLOSE` | C |
| `MA20`, `EMA20`, `MA50` | giá trị chỉ báo |
| `SUPPORT_20` | đáy 20 phiên trước |
| `RESISTANCE_20` | đỉnh 20 phiên trước |
| `HIGH_60`, `HIGH_120` | đỉnh 60/120 phiên trước |
| `ATR_STOP` | C − 1.5 × ATR |
| `ATR_T2`, `ATR_T3` | C + 2 × ATR, C + 3 × ATR |
| `MEASURED_MOVE` | RESISTANCE_20 + (RESISTANCE_20 − SUPPORT_20) |

### Nhóm mốc (một mốc có thể thuộc nhiều nhóm)
- `entry`: chọn trong `CLOSE`, `MA20`, `EMA20`, `MA50`, `SUPPORT_20`, `RESISTANCE_20`, chỉ giữ mốc có giá ≤ C × 1.02.
- `stop`: chọn trong `SUPPORT_20`, `MA20`, `EMA20`, `MA50`, `ATR_STOP`, chỉ giữ mốc có giá < C.
- `target`: chọn trong `RESISTANCE_20`, `HIGH_60`, `HIGH_120`, `ATR_T2`, `ATR_T3`, `MEASURED_MOVE`, chỉ giữ mốc có giá > C.

Vì `ATR_T2` và `ATR_T3` luôn lớn hơn C, nhóm `target` luôn có ít nhất 2 mốc. Điều này giải quyết trường hợp giá đã vượt mọi kháng cự, như DXG.

---

## 4. Schema

### Analyst (`agents.AnalystResult`)

```json
{
  "symbol": "string",
  "signal": "MUA GOM | QUAN SAT | BO QUA",
  "confidence_score": 1.0,
  "orderflow_analysis": "string",
  "fundamental_analysis": "string",
  "red_flags": ["string"],
  "plan": {
    "entry_low":  {"level": "MA20", "price": 10.23},
    "entry_high": {"level": "RESISTANCE_20", "price": 10.8},
    "stop_loss":  {"level": "EMA20", "price": 10.29},
    "target_1":   {"level": "ATR_T2", "price": 11.9},
    "target_2":   {"level": "HIGH_120", "price": 12.4},
    "t_plus_risk": "string"
  }
}
```
- `confidence_score`: từ 1.0 đến 10.0.
- `target_2`: không bắt buộc (có thể là null).
- `level`: kiểu chuỗi. Python kiểm tra tên mốc. Không dùng Enum, vì danh sách mốc thay đổi theo từng mã.

### Critic (`agents.CriticResult`)

```json
{
  "verdict": "GIU_NGUYEN | GIAM_TIN_CAY | HA_CAP",
  "confidence_adjustment": -2.0,
  "counter_arguments": ["string"],
  "reason": "string"
}
```
- `confidence_adjustment`: từ −5.0 đến 0. Schema dùng `le=0`. Python cũng tự ép giá trị dương về 0.

---

## 5. Luật của Validator

Hằng số: `PRICE_TOLERANCE = 0.005` (0.5%), `MIN_RR = 1.5`, `MAX_CHASE = 1.02`, `MAX_STOP_PCT = 0.07`, `RSI_OVERBOUGHT = 75`.

### Luật chặn (lỗi, cần sửa)

| # | Luật | Áp dụng |
|---|---|---|
| H1 | Mỗi mốc trong `plan` phải có tên trong danh sách, và `|price − level.price| / level.price ≤ 0.5%` | Mọi tín hiệu |
| H2 | `stop_loss < entry_low ≤ entry_high < target_1`, và `target_1 < target_2` nếu có `target_2` | Mọi tín hiệu |
| H3 | `entry_*` thuộc nhóm `entry`, `stop_loss` thuộc nhóm `stop`, `target_*` thuộc nhóm `target` | Mọi tín hiệu |
| H4 | `(target_1 − entry_high) / (entry_high − stop_loss) ≥ 1.5` | Chỉ MUA GOM |
| H5 | `entry_high ≤ C × 1.02` (chống mua đuổi). Thực tế H3 đã đảm bảo điều này cho mọi tín hiệu, vì nhóm `entry` chỉ gồm các mốc ≤ C × 1.02. H5 vẫn được kiểm tra riêng để thông báo lỗi nói rõ là "mua đuổi" | Chỉ MUA GOM |

Mỗi lỗi là một câu tiếng Việt, cụ thể và hướng dẫn được cách sửa. Ví dụ: `"target_1: mốc 'TARGET_12' không tồn tại. Các mốc mục tiêu hợp lệ: ATR_T2=11.9, ATR_T3=12.4, ..."`. Các lỗi này được gửi lại nguyên văn cho Analyst ở lần sửa.

### Luật cảnh báo (không chặn, ghi vào `red_flags` của kết quả cuối)
- **S1:** `signal == MUA GOM` và RSI > 75: "RSI quá mua (x) nhưng khuyến nghị MUA GOM".
- **S2:** `(entry_high − stop_loss) / entry_high > 7%`: "Khoảng cắt lỗ x% lớn hơn một phiên giảm sàn HOSE".
- **S3:** chống ảo giác trong phần chữ.
  - Lấy mọi số thập phân (có dấu `.` hoặc `,`) trong `orderflow_analysis` và `red_flags`. Bỏ qua số nguyên, vì thường là số phiên hoặc số chu kỳ như 20, 14, T+2.
  - Mỗi số phải khớp (sai lệch ≤ 0.5%) với một giá trị trong: các trường của `metrics`, giá của các mốc, khối lượng chia cho 1e6, hoặc khối lượng chia cho 1e3.
  - Số nào không khớp thì cảnh báo: "Số liệu không có trong dữ liệu đầu vào: x".

---

## 6. Luồng điều phối (`orchestrator.run_pipeline`)

1. **Analyst**
   - Prompt gồm: metrics, bảng mốc giá theo nhóm, quy tắc chống ảo giác (như prompt hiện tại) và yêu cầu chỉ chọn mốc trong bảng.
   - Nếu lỗi ở mọi model, trả về `status = "ANALYST_FAILED"`. `main.py` sẽ không lưu tín hiệu và không đánh dấu đã phân tích, để lượt quét sau thử lại.
2. **Validator**
   - Nếu không có lỗi H, sang bước 3.
3. **Sửa lỗi** (chỉ chạy khi có lỗi H hoặc JSON sai schema)
   - Gọi lại Analyst với prompt cũ, kết quả trước đó và danh sách lỗi.
   - Kiểm tra lại. Nếu vẫn lỗi, hoặc lần gọi này thất bại:
     - Tín hiệu cuối là QUAN SAT.
     - `confidence_score = min(score, 5.0)`.
     - Thêm red_flag "Kế hoạch không qua kiểm tra: ...".
     - `status = "VALIDATION_FAILED"`.
4. **Critic** (chỉ chạy khi tín hiệu sau bước 2–3 là MUA GOM)
   - Prompt gồm: metrics, bảng mốc giá, kết quả của Analyst, các cảnh báo S, và vai trò "tìm lý do KHÔNG nên mua".
   - Nếu lỗi: hạ xuống QUAN SAT, thêm red_flag "Chưa được phản biện (Critic lỗi)", `status = "CRITIC_FAILED"`.
5. **Quyết định cuối** (Python)
   - `confidence = max(1.0, confidence + min(0, adjustment))`.
   - Nếu `verdict == HA_CAP` thì tín hiệu là QUAN SAT.
   - Gộp `counter_arguments` vào `red_flags`.
   - `status = "OK"` nếu không có lỗi nào.

Tối đa 3 lần gọi `generate`: Analyst, sửa lỗi, Critic. Việc thử lại và chuyển model dự phòng nằm bên trong `generate`.

### Bản ghi trả về và lưu vào `signals.jsonl`

```json
{
  "time": "...", "symbol": "DXG", "status": "OK | VALIDATION_FAILED | CRITIC_FAILED | ANALYST_FAILED",
  "metrics": {}, "levels": [],
  "final":      {"signal": "...", "confidence_score": 0, "plan": {}, "red_flags": [], "orderflow_analysis": "...", "fundamental_analysis": "..."},
  "analyst":    {"result": {}, "model": "...", "latency_sec": 0},
  "validation": {"passed": true, "errors": [], "warnings": [], "attempts": 1},
  "critic":     {"result": {}, "model": "...", "latency_sec": 0}
}
```
- `symbol` trong `final` luôn lấy từ code.
- `analyst.result` là kết quả của lần gọi Analyst cuối cùng.
- `critic` là `null` nếu Critic không chạy.

---

## 7. Xử lý lỗi

| Tình huống | Kết quả |
|---|---|
| Analyst lỗi ở mọi model | `ANALYST_FAILED`, không lưu, lượt quét sau thử lại |
| JSON sai schema | Xử lý như lỗi H: sửa 1 lần |
| Lần gọi sửa lỗi thất bại | `VALIDATION_FAILED`, hạ xuống QUAN SAT |
| Critic lỗi | `CRITIC_FAILED`, hạ xuống QUAN SAT |
| Mốc giá NaN (thiếu lịch sử) | Bỏ mốc đó khỏi danh sách |

---

## 8. Kiểm thử

Thư mục `tests/`, chạy bằng `pytest`, không cần mạng.

- `test_validator.py`:
  - Trường hợp DXG thật với `target_1 = 12.0`, tên mốc tự đặt: H1 phải báo lỗi.
  - Kế hoạch hợp lệ thì không có lỗi.
  - Sai thứ tự giá (H2), sai nhóm mốc (H3), R:R < 1.5 (H4), mua đuổi (H5).
  - S1, S2, S3, trong đó S3 phải bắt được số bịa và bỏ qua số nguyên.
- `test_levels.py`:
  - Kiểm tra ATR trên dữ liệu đã biết trước.
  - Mốc nằm sai phía giá hiện tại không xuất hiện trong nhóm.
  - Mốc NaN bị bỏ.
  - Nhóm `target` luôn có ít nhất 2 mốc.
- `test_orchestrator.py`, dùng `generate` giả trả về kết quả định sẵn:
  - Qua ngay (1 lần gọi khi QUAN SAT, 2 lần khi MUA GOM).
  - Sửa 1 lần thì qua.
  - Sửa vẫn lỗi: QUAN SAT và `VALIDATION_FAILED`.
  - Critic `HA_CAP` thì hạ cấp. Critic đề xuất `confidence_adjustment` dương thì bị bỏ qua.
  - Critic lỗi: `CRITIC_FAILED`.
  - Analyst lỗi: `ANALYST_FAILED`.
  - Không bao giờ quá 3 lần gọi.
- **Chạy thật:** `python main.py --once --force --symbols DXG HPG`, so sánh với kết quả ngày 06/11.

---

## 9. Thay đổi kèm theo

- `requirements.txt`: thêm `pytest` vào nhóm phát triển (ghi chú trong file).
- `.env.example`: không thêm biến mới. Các ngưỡng kiểm tra là hằng số trong `validator.py`.
- Tài liệu yêu cầu: cập nhật NFR-02 theo schema mới (plan dạng số có tên mốc, các trường status, final, analyst, validation, critic) và ghi chú kiến trúc multi-agent.
- Dữ liệu cũ trong `signals.jsonl` có định dạng khác. Đổi tên file cũ thành `signals_v1.jsonl` trước khi chạy phiên bản mới.
