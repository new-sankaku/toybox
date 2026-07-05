import os
from pathlib import Path

from tictok.paths import PROJECT_ROOT


def _parse_env_text(text: str) -> dict:
    """Parse .env file text into a dict. Skips blank lines, comments, and lines
    without '='; trims whitespace and a single layer of surrounding quotes."""
    result: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def _load_dotenv() -> None:
    """Load TicTok/.env into os.environ for local secrets (e.g. the EulerStream
    API key) without committing them. Existing environment variables win, so an
    OS-level value overrides the file. Dependency-free so it works in venvs that
    were created before any new requirement was added."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for key, value in _parse_env_text(env_path.read_text(encoding="utf-8")).items():
        if key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def get_host() -> str:
    return os.environ.get("TICTOK_HOST", "127.0.0.1")


def get_port() -> int:
    return int(os.environ.get("TICTOK_PORT", "8520"))


def get_log_level() -> str:
    return os.environ.get("TICTOK_LOG_LEVEL", "INFO")


def get_db_path() -> str:
    return os.environ.get(
        "TICTOK_DB_PATH", str(PROJECT_ROOT / "tictok.db")
    )


def get_timeline_limit() -> int:
    return int(os.environ.get("TICTOK_TIMELINE_LIMIT", "2160"))


def get_simulation() -> bool:
    return os.environ.get("TICTOK_SIMULATION", "0").lower() in ("1", "true", "yes")


def get_record_dir() -> str:
    return os.environ.get(
        "TICTOK_RECORD_DIR", str(PROJECT_ROOT / "recordings")
    )


def get_locale_lang() -> str:
    return os.environ.get("TICTOK_LOCALE_LANG", "ja")


def get_locale_country() -> str:
    return os.environ.get("TICTOK_LOCALE_COUNTRY", "JP")


def get_locale_lang_country() -> str:
    return os.environ.get("TICTOK_LOCALE_LANG_COUNTRY", "ja-JP")


def get_locale_tz() -> str:
    return os.environ.get("TICTOK_LOCALE_TZ", "Asia/Tokyo")


def get_resolver_headless() -> bool:
    return os.environ.get("TICTOK_RESOLVER_HEADLESS", "1").lower() in ("1", "true", "yes")


def get_resolver_timeout_ms() -> int:
    return int(os.environ.get("TICTOK_RESOLVER_TIMEOUT_MS", "20000"))


def get_sign_api_key() -> str:
    """EulerStream sign server API key. Empty string means anonymous tier."""
    return os.environ.get("TICTOK_EULER_API_KEY", "").strip()


def get_log_dir() -> str:
    """Directory for persisted log files. Defaults to TicTok/logs so that
    best-effort failures (e.g. avatar persist) survive past the console session
    and can be diagnosed later."""
    return os.environ.get(
        "TICTOK_LOG_DIR", str(PROJECT_ROOT / "logs")
    )


def get_sample_dir() -> str:
    """Directory for deduplicated raw-event samples captured from real streams.
    Kept separate from logs so operators can inspect / clear proto samples on their
    own without touching diagnostic logs."""
    return os.environ.get(
        "TICTOK_SAMPLE_DIR", str(PROJECT_ROOT / "samples")
    )


def get_avatar_fetch_concurrency() -> int:
    """Max simultaneous avatar downloads. Caps the burst when many comments
    arrive at once so fetches do not exhaust the connection pool and time out."""
    return int(os.environ.get("TICTOK_AVATAR_FETCH_CONCURRENCY", "6"))


def get_avatar_fetch_attempts() -> int:
    """Total avatar download attempts (1 = no retry) for transient failures."""
    return int(os.environ.get("TICTOK_AVATAR_FETCH_ATTEMPTS", "3"))


def get_avatar_fetch_backoff_seconds() -> float:
    """Base back-off between avatar download retries. The Nth retry waits
    base * N seconds so a transiently failing CDN is not hammered (which risks
    rate-limit blocking)."""
    return float(os.environ.get("TICTOK_AVATAR_FETCH_BACKOFF_SECONDS", "1.5"))


# ---- Local AI (OpenAI-compatible endpoint: Ollama / llama.cpp server / LM Studio) ----
# Provider/model/endpoint are NOT hard-coded into logic; they are deployment config so
# the same code runs against any local quantized model. AI is opt-in (disabled by default)
# and there is no fallback: when disabled or unreachable the feature reports unavailable
# rather than substituting a fake result.


def get_ai_enabled() -> bool:
    return os.environ.get("TICTOK_AI_ENABLED", "0").lower() in ("1", "true", "yes")


def get_ai_base_url() -> str:
    """Base URL of an OpenAI-compatible chat API. Default targets a local Ollama
    instance; override for llama.cpp server, LM Studio, or a remote provider."""
    return os.environ.get("TICTOK_AI_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")


def get_ai_model() -> str:
    """Model name to request (e.g. a quantized GGUF tag served by Ollama). Empty by
    default so no specific model is baked in; must be set to use AI features."""
    return os.environ.get("TICTOK_AI_MODEL", "").strip()


def get_ai_api_key() -> str:
    """API key for the endpoint. Local servers (Ollama/llama.cpp) ignore it; a
    placeholder keeps OpenAI-compatible clients happy."""
    return os.environ.get("TICTOK_AI_API_KEY", "").strip()


def get_ai_timeout_seconds() -> float:
    """Request timeout. Local inference of a long comment batch can take a while."""
    return float(os.environ.get("TICTOK_AI_TIMEOUT_SECONDS", "120"))


def get_ai_comment_sample() -> int:
    """Max comments sent to the model per analysis (caps prompt size / latency)."""
    return int(os.environ.get("TICTOK_AI_COMMENT_SAMPLE", "300"))


# ---- Local speech-to-text (faster-whisper / CTranslate2, GPU-accelerated) ----
# Opt-in; the faster-whisper package is an optional dependency loaded lazily, so the
# base app runs without it. No fallback: if disabled or the package/model is missing
# the feature reports unavailable rather than returning a fake transcript.


def get_stt_enabled() -> bool:
    return os.environ.get("TICTOK_STT_ENABLED", "0").lower() in ("1", "true", "yes")


def get_stt_model() -> str:
    """Whisper model id/size (e.g. large-v3, large-v3-turbo, or a local CTranslate2
    model path / kotoba-whisper repo). Config-driven so no model is baked into logic."""
    return os.environ.get("TICTOK_STT_MODEL", "large-v3-turbo").strip()


def get_stt_device() -> str:
    """faster-whisper device: 'cuda', 'cpu', or 'auto'."""
    return os.environ.get("TICTOK_STT_DEVICE", "auto").strip()


def get_stt_compute_type() -> str:
    """Quantization/precision: e.g. float16, int8_float16, int8 (or 'auto')."""
    return os.environ.get("TICTOK_STT_COMPUTE_TYPE", "auto").strip()


def get_stt_language() -> str:
    """Spoken language hint (empty = autodetect)."""
    return os.environ.get("TICTOK_STT_LANGUAGE", "ja").strip()


def get_stt_beam_size() -> int:
    return int(os.environ.get("TICTOK_STT_BEAM_SIZE", "5"))


def get_stt_condition_on_previous_text() -> bool:
    """Whisper feeds the previous segment's text back as the next segment's prompt.
    Whisper's default (True) self-reinforces repetition: once it emits a phrase in a
    low-confidence span (silence/BGM/cheering) it keeps repeating it across segments.
    Default False here to break that loop. Real repeated speech is unaffected."""
    return os.environ.get("TICTOK_STT_CONDITION_ON_PREVIOUS_TEXT", "0").lower() in ("1", "true", "yes")


def get_stt_no_repeat_ngram_size() -> int:
    """Block re-emitting any n-gram of this length during decoding (0 = off). Caps
    in-segment and cross-segment repetition loops. 3 is a conservative default."""
    return int(os.environ.get("TICTOK_STT_NO_REPEAT_NGRAM_SIZE", "3"))


# ---- Local AI video upscaling (super-resolution via spandrel + torch, GPU) ----
# Opt-in; torch/spandrel are optional dependencies loaded lazily so the base app runs
# without them. The model is a deployment-provided weights file (any super-resolution
# architecture spandrel can load, e.g. Real-ESRGAN); nothing is baked into logic and
# there is no fallback: when disabled, unconfigured, or the model fails to load the
# feature reports unavailable instead of substituting a non-upscaled result.


def get_upscale_enabled() -> bool:
    return os.environ.get("TICTOK_UPSCALE_ENABLED", "0").lower() in ("1", "true", "yes")


def get_upscale_model_path() -> str:
    """Path to the super-resolution model weights file (.pth/.safetensors). Empty by
    default so no model is baked in; must be set to use the upscale feature."""
    return os.environ.get("TICTOK_UPSCALE_MODEL_PATH", "").strip()


def get_upscale_device() -> str:
    """Inference device: 'cuda', 'cpu', or 'auto' (cuda when available)."""
    return os.environ.get("TICTOK_UPSCALE_DEVICE", "auto").strip()


def get_upscale_compute_type() -> str:
    """Precision: float16, float32, or 'auto' (float16 on CUDA when the model
    supports it, else float32). An explicit float16 on an unsupported model errors
    rather than silently degrading."""
    return os.environ.get("TICTOK_UPSCALE_COMPUTE_TYPE", "auto").strip()


def get_upscale_tile() -> int:
    """Tile edge (source pixels) for tiled inference; caps VRAM usage on large
    frames. 0 runs the whole frame at once."""
    return int(os.environ.get("TICTOK_UPSCALE_TILE", "512"))


def get_upscale_tile_overlap() -> int:
    """Overlap (source pixels) between neighbouring tiles, hiding seam artifacts at
    tile borders."""
    return int(os.environ.get("TICTOK_UPSCALE_TILE_OVERLAP", "16"))


def get_upscale_max_height() -> int:
    """Cap on the output height. A model whose scale would exceed this (e.g. 4x on a
    1440px source) is downscaled to the cap after inference, keeping encode time and
    file size bounded."""
    return int(os.environ.get("TICTOK_UPSCALE_MAX_HEIGHT", "2160"))
