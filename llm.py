"""
llm.py - Kết nối Gemini dùng chung cho mọi agent:
  thử lại khi lỗi tạm thời, chuyển model dự phòng, timeout, rate limiter, đọc cấu hình .env.
"""
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("stock_agent.llm")


def load_env(path: Path) -> None:
    """Đọc file .env đơn giản (KEY=VALUE), không cần thư viện ngoài."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(BASE_DIR / ".env")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# Model dự phòng khi model chính quá tải (503) hoặc hết hạn ngạch (429), theo thứ tự ưu tiên
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.5-flash,gemini-3.5-flash-lite").split(",") if m.strip()]
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "2"))  # số lần thử cho mỗi model
GEMINI_RETRY_BASE_SEC = float(os.getenv("GEMINI_RETRY_BASE_SEC", "2"))  # chờ 2s, 4s, ...
GEMINI_TIMEOUT_SEC = int(os.getenv("GEMINI_TIMEOUT_SEC", "30"))
GEMINI_MIN_INTERVAL_SEC = float(os.getenv("GEMINI_MIN_INTERVAL_SEC", "6"))  # ~10 request/phút
LATENCY_TARGET_SEC = 3.0  # NFR-03


class RateLimiter:
    """Đảm bảo khoảng cách tối thiểu giữa 2 lần gọi để không vượt hạn ngạch."""

    def __init__(self, min_interval_sec: float):
        self.min_interval = min_interval_sec
        self._last = 0.0

    def wait(self) -> None:
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


gemini_limiter = RateLimiter(GEMINI_MIN_INTERVAL_SEC)
_client = None


@dataclass
class LLMResult:
    parsed: BaseModel
    model: str
    latency_sec: float


def get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Thiếu GEMINI_API_KEY. Tạo file .env từ .env.example.")
        # Timeout (ms) để 1 request treo không chặn cả vòng quét
        _client = genai.Client(api_key=api_key,
                               http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_SEC * 1000))
    return _client


def _is_retryable(exc: Exception) -> bool:
    """Lỗi tạm thời: quá tải (503), lỗi máy chủ (5xx), vượt hạn ngạch (429), lỗi mạng."""
    import httpx
    from google.genai import errors

    if isinstance(exc, errors.APIError):
        return exc.code == 429 or exc.code >= 500
    # httpx.TransportError bao gồm timeout và lỗi kết nối
    return isinstance(exc, (httpx.TransportError, ConnectionError, TimeoutError))


def _should_skip_model(exc: Exception) -> bool:
    """404: model không còn mở; 429: hết hạn ngạch của model này -> thử lại cùng model là vô ích."""
    from google.genai import errors

    return isinstance(exc, errors.APIError) and exc.code in (404, 429)


def generate(contents, schema: type[BaseModel], temperature: float = 0.2) -> LLMResult:
    """
    Gọi Gemini với structured output theo `schema`.
    Thử lại với backoff và chuyển model dự phòng khi gặp lỗi tạm thời.
    Raise pydantic.ValidationError nếu JSON sai schema, RuntimeError nếu mọi model thất bại.
    """
    from google.genai import types

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
    last_exc: Exception | None = None

    for model in models:
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            gemini_limiter.wait()
            started = time.perf_counter()
            try:
                response = get_client().models.generate_content(model=model, contents=contents, config=config)
            except Exception as exc:
                if _should_skip_model(exc) and model != models[-1]:
                    logger.warning("Model %s không dùng được hoặc hết hạn ngạch (%s), chuyển model khác",
                                   model, getattr(exc, "code", ""))
                    last_exc = exc
                    break
                if not _is_retryable(exc):
                    raise
                last_exc = exc
                logger.warning("%s lỗi tạm thời (lần %d/%d): %s", model, attempt, GEMINI_MAX_RETRIES, str(exc)[:120])
                if attempt < GEMINI_MAX_RETRIES:
                    time.sleep(GEMINI_RETRY_BASE_SEC * 2 ** (attempt - 1))
                continue

            latency = time.perf_counter() - started
            if latency > LATENCY_TARGET_SEC:
                logger.warning("Gemini %s phản hồi %.2fs (vượt mục tiêu %.0fs)", model, latency, LATENCY_TARGET_SEC)
            parsed = response.parsed
            if not isinstance(parsed, schema):
                parsed = schema.model_validate_json(response.text or "")
            return LLMResult(parsed, model, round(latency, 2))
        logger.warning("Chuyển sang model dự phòng sau khi %s thất bại", model)

    raise RuntimeError(f"Tất cả model đều thất bại: {', '.join(models)}") from last_exc
