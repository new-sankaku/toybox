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


_DOTENV_STATE: dict = {
    "present": False,
    "parsed": 0,
    "applied": 0,
    "overridden_by_env": 0,
}


def _load_dotenv() -> None:
    """Load TicTok/.env into os.environ for local secrets (e.g. the EulerStream
    API key) without committing them. Existing environment variables win, so an
    OS-level value overrides the file. Dependency-free so it works in venvs that
    were created before any new requirement was added."""
    env_path = PROJECT_ROOT / ".env"
    _DOTENV_STATE["present"] = env_path.exists()
    if not env_path.exists():
        return
    parsed = _parse_env_text(env_path.read_text(encoding="utf-8"))
    _DOTENV_STATE["parsed"] = len(parsed)
    for key, value in parsed.items():
        if key not in os.environ:
            os.environ[key] = value
            _DOTENV_STATE["applied"] += 1
        else:
            _DOTENV_STATE["overridden_by_env"] += 1


_load_dotenv()


def dotenv_summary() -> dict:
    """Counts from the import-time .env load, reported by the server once logging is
    configured. This module is imported by logging_setup itself, so the load runs before
    any handler exists and cannot log itself.

    Counts only, never keys or values: this file holds the sign-server API key and a log
    line is the wrong place for it. A non-zero 'overridden_by_env' is the answer to "I
    edited .env and nothing changed"."""
    return dict(_DOTENV_STATE)


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


def get_no_restore() -> bool:
    """監視対象を復元せずに起動するか。

    既定の起動は前回の監視対象をそのまま復元するため、「確認のためにserverを上げる」だけで
    実配信へ接続し、録画fileをdiskへ書く。同じ配信をuserのserverが録画していれば二重録画に
    なる。CI・静的解析・手動検証はこれを1に設定して起動する(監視の追加・削除操作そのものは
    通常どおり効くので、機能検証の妨げにはならない)。"""
    return os.environ.get("TICTOK_NO_RESTORE", "0").lower() in ("1", "true", "yes")


def get_record_dir() -> str:
    return os.environ.get(
        "TICTOK_RECORD_DIR", str(PROJECT_ROOT / "recordings")
    )


def _setting_from_db(db_path: str, key: str) -> str:
    """UI(DB)で設定された値。未設定・DB/表が無ければ空文字。"""
    import sqlite3

    row = None
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        row = None
    return str(row[0]).strip() if row and row[0] and str(row[0]).strip() else ""


def record_dir_from_db(db_path: str) -> str:
    """Effective record dir for out-of-band tools (maintenance scripts): the UI-set
    'record_dir' setting when present in the DB, else the TICTOK_RECORD_DIR env var,
    else the default. Mirrors how the server resolves it via Settings so a script
    targets the same folder the server records into. A missing DB/table resolves to
    the env/default (this is the unset case, not a masked failure)."""
    return _setting_from_db(db_path, "record_dir") or get_record_dir()


def final_record_dir_from_db(db_path: str) -> str:
    """完成mp4の移送先(final dir)。``record_dir_from_db`` と同じ順序(DB設定 > 環境変数)で
    解き、未設定なら record dir そのもの(=移送しない)を返す。serverの
    ``FINAL_DIR = record_dir_final or record_dir`` と同じ結論になるよう、script側に
    2つ目の解決規則を持たせないための関数。"""
    value = _setting_from_db(db_path, "record_dir_final") \
        or os.environ.get("TICTOK_RECORD_DIR_FINAL", "").strip()
    return value or record_dir_from_db(db_path)


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


# ---- Logging (see tictok/core/logging_setup.py) ----
# Rotation size, retention and formatting are deployment config, not constants in
# code. Files rotate to a timestamped name and are gzipped off-thread; text is
# compressed roughly 10:1, so a larger pre-rotation size costs little disk while
# widening how far back an incident can be traced.


def get_log_console_level() -> str:
    """Level for the console stream. Empty follows TICTOK_LOG_LEVEL; set this to
    keep the terminal quiet while the files stay verbose."""
    return os.environ.get("TICTOK_LOG_CONSOLE_LEVEL", "").strip()


def get_log_max_bytes() -> int:
    """Size at which a log file rotates."""
    return int(os.environ.get("TICTOK_LOG_MAX_BYTES", "20971520"))


def get_log_retention_days() -> int:
    """Days to keep rotated logs. 0 (default) disables pruning: logs are diagnostic
    assets and an unexplained deletion is worse than disk use, which compression
    already bounds. Set a value to cap growth on a small volume."""
    return int(os.environ.get("TICTOK_LOG_RETENTION_DAYS", "0"))


def get_log_compress() -> bool:
    """Gzip rotated files. Runs on a worker thread, never on the event loop."""
    return os.environ.get("TICTOK_LOG_COMPRESS", "1").lower() in ("1", "true", "yes")


def get_log_compress_level() -> int:
    """Gzip level for rotated files. 9 costs roughly double the CPU of 6 for a few
    percent on text."""
    return int(os.environ.get("TICTOK_LOG_COMPRESS_LEVEL", "6"))


def get_log_jsonl_enabled() -> bool:
    """Write the machine-readable JSONL stream alongside the text log."""
    return os.environ.get("TICTOK_LOG_JSONL_ENABLED", "1").lower() in ("1", "true", "yes")


def get_log_jsonl_level() -> str:
    """Level for the JSONL stream. Empty follows TICTOK_LOG_LEVEL; the two streams
    are kept identical by default so text and JSONL never disagree."""
    return os.environ.get("TICTOK_LOG_JSONL_LEVEL", "").strip()


def get_log_queue_enabled() -> bool:
    """Hand formatting and file writes to a listener thread so a log call on the
    event loop costs only a filter evaluation and a queue put. Disable to write
    synchronously when debugging the logging path itself."""
    return os.environ.get("TICTOK_LOG_QUEUE_ENABLED", "1").lower() in ("1", "true", "yes")


def get_log_dedup_window_seconds() -> int:
    """Window in which an identical repeating record is collapsed to a count. The
    first occurrence is always emitted and the count is always reported, so nothing
    is hidden. 0 disables suppression."""
    return int(os.environ.get("TICTOK_LOG_DEDUP_WINDOW_SECONDS", "60"))


def get_log_dedup_max_tracked() -> int:
    """Cap on distinct fingerprints held by the suppressor, bounding its memory."""
    return int(os.environ.get("TICTOK_LOG_DEDUP_MAX_TRACKED", "2000"))


def get_log_quiet_loggers() -> str:
    """Comma-separated logger=LEVEL floors for chatty third-party libraries. Not
    applied when running at DEBUG, where their traffic is the point."""
    return os.environ.get(
        "TICTOK_LOG_QUIET_LOGGERS",
        "httpx=WARNING,httpcore=WARNING,urllib3=WARNING,websockets=WARNING,PIL=INFO",
    )


def get_log_rotate_retry_attempts() -> int:
    """Rename attempts during rotation. On Windows a scanner or indexer can hold a
    just-closed file briefly; the final attempt raises rather than silently
    skipping the rotation."""
    return int(os.environ.get("TICTOK_LOG_ROTATE_RETRY_ATTEMPTS", "5"))


def get_log_rotate_retry_delay_seconds() -> float:
    return float(os.environ.get("TICTOK_LOG_ROTATE_RETRY_DELAY_SECONDS", "0.2"))


def get_log_shutdown_drain_seconds() -> float:
    """How long shutdown waits for in-flight compression before exiting."""
    return float(os.environ.get("TICTOK_LOG_SHUTDOWN_DRAIN_SECONDS", "10"))


def get_log_battle_raw_gzip() -> bool:
    """Gzip battle raw-event captures when their session closes. These are the
    largest files the app writes and compress roughly 35:1."""
    return os.environ.get("TICTOK_LOG_BATTLE_RAW_GZIP", "1").lower() in ("1", "true", "yes")


def get_log_progress_interval_seconds() -> float:
    """Minimum gap between periodic progress lines from long-running jobs. The gap
    grows geometrically per job so a very slow job does not emit proportionally
    more lines; DEBUG collapses it to every tick."""
    return float(os.environ.get("TICTOK_LOG_PROGRESS_INTERVAL_SECONDS", "60"))


def get_log_progress_interval_max_seconds() -> float:
    return float(os.environ.get("TICTOK_LOG_PROGRESS_INTERVAL_MAX_SECONDS", "600"))


def get_log_progress_interval_growth() -> float:
    """Factor the progress interval is multiplied by after each emitted line, up to
    the max above. A fixed interval is wrong for jobs whose speed spans orders of
    magnitude: the quality upscale path runs at ~0.23 fps (107x real time), where a
    fixed 60s gate would emit thousands of lines for one job. Growth keeps the early
    lines close together — so a job that dies in its first minutes still leaves a
    trace — and thins them out as the job proves long-running. 1.0 disables growth."""
    return float(os.environ.get("TICTOK_LOG_PROGRESS_INTERVAL_GROWTH", "1.6"))


def get_log_progress_percent_step() -> float:
    """Minimum completion percent a job must advance between two progress lines.
    This is what actually bounds the line count of an arbitrarily long job: the time
    interval alone cannot, since a job 100x slower than real time runs 100x longer.
    At the default a job emits at most ~100 progress lines regardless of duration.
    0 disables the completion gate, leaving only the time interval."""
    return float(os.environ.get("TICTOK_LOG_PROGRESS_PERCENT_STEP", "1.0"))


def get_log_slow_http_ms() -> float:
    """Request duration above which an HTTP request is logged. Successful fast
    requests are not logged at all: on a single-user deployment the polling
    endpoints would otherwise dominate the log with no diagnostic value."""
    return float(os.environ.get("TICTOK_LOG_SLOW_HTTP_MS", "1000"))


def get_log_slow_analytics_ms() -> float:
    """Analytics stage duration above which the stage is logged as slow."""
    return float(os.environ.get("TICTOK_LOG_SLOW_ANALYTICS_MS", "2000"))


def get_log_access_rollup_seconds() -> float:
    """Minimum gap between access-log lines sharing a route and status. Bounds a
    404 storm to a countable trickle without hiding a different route's failure."""
    return float(os.environ.get("TICTOK_LOG_ACCESS_ROLLUP_SECONDS", "60"))


def get_log_access_gate_max_keys() -> int:
    """Cap on distinct (route, status) pairs the access-log gate tracks, bounding its
    memory. The routed key space is the number of endpoints times a handful of failure
    statuses, so this default is far above normal use and is reached only when unmatched
    paths are being probed."""
    return int(os.environ.get("TICTOK_LOG_ACCESS_GATE_MAX_KEYS", "500"))


def get_log_slow_analytics_payload_ms() -> float:
    """Duration above which one session's analytics payload is reported on its own. A
    single request reduces hundreds of per-session payloads, so this must sit well below
    the whole-stage threshold to name the session responsible rather than only the stage
    that contains it."""
    return float(os.environ.get("TICTOK_LOG_SLOW_ANALYTICS_PAYLOAD_MS", "200"))


def get_log_ffmpeg_stderr_chars() -> int:
    """Characters of ffmpeg stderr retained on failure. The cause is at the tail."""
    return int(os.environ.get("TICTOK_LOG_FFMPEG_STDERR_CHARS", "800"))


def get_log_disk_low_bytes() -> int:
    """Free space below which a preflight check warns before starting a job that
    writes a large intermediate. Disk exhaustion has previously surfaced only as an
    unrelated-looking rendering failure."""
    return int(os.environ.get("TICTOK_LOG_DISK_LOW_BYTES", str(5 * 1024 * 1024 * 1024)))


def get_log_restriction_text_chars() -> int:
    """Characters of the TikTok restriction payload (message / prompts) retained in
    the log. The restriction *type* (18+ / members-only / rate limit) is only
    distinguishable from this wording, and it is carried in the first sentence, so a
    few hundred characters identify it while a full payload dump would burn rotation
    budget on a line that repeats for every blocked broadcast."""
    return int(os.environ.get("TICTOK_LOG_RESTRICTION_TEXT_CHARS", "800"))


def get_log_stream_url_expiry_warn_seconds() -> float:
    """Remaining lifetime of a TikTok pull URL below which launching a recording on
    it is flagged. Empty recordings are caused by a URL that expired between
    room_info and ffmpeg's first read; without this the log shows only "captured 0
    bytes" and the cause has to be guessed. TikTok issues these URLs with lifetimes
    measured in hours, so a URL with less than a couple of minutes left is already
    the anomaly rather than a tight-but-normal launch."""
    return float(os.environ.get("TICTOK_LOG_STREAM_URL_EXPIRY_WARN_SECONDS", "120"))


def get_log_live_wait_interval_seconds() -> float:
    """Minimum gap between "still waiting for a live to start" lines from one
    monitor. Separate from the generic progress interval and much longer: an offline
    streamer is the steady state of every monitor, so this line exists only to prove
    the watch loop is alive and to date the last probe, and at the generic 60s it
    would be the highest-volume line in the file. DEBUG collapses it to every poll."""
    return float(os.environ.get("TICTOK_LOG_LIVE_WAIT_INTERVAL_SECONDS", "900"))


def get_sample_dir() -> str:
    """Directory for deduplicated raw-event samples captured from real streams.
    Kept separate from logs so operators can inspect / clear proto samples on their
    own without touching diagnostic logs."""
    return os.environ.get(
        "TICTOK_SAMPLE_DIR", str(PROJECT_ROOT / "samples")
    )


def get_battle_gift_window_fallback_seconds() -> float:
    """Battle貢献のGift集計窓を閉じる長さ(秒)。終了時刻もdurationも次Battleの開始も
    分からない「終了済み・最終」Battle専用の最終手段で、同一sessionで実際に観測できた
    Battle長(中央値)が1件でも取れればそちらが優先される。窓を閉じないとBattle後の通常Gift
    が貢献へ合算され、連続PKでは同じGiftが複数Battleへ二重計上される。TikTok PKの標準尺
    (約5分)を既定値にしている。"""
    return float(os.environ.get("TICTOK_BATTLE_GIFT_WINDOW_FALLBACK_SECONDS", "300"))


def get_journal_enabled() -> bool:
    """Durable append-only event journal on disk. Every event/viewer sample is
    appended here at ingest time, independent of the batched SQLite writer, so a
    writer stall or crash cannot silently lose the raw stream: startup re-imports
    any journalled rows missing from the DB. On by default."""
    return os.environ.get("TICTOK_JOURNAL_ENABLED", "1").lower() in ("1", "true", "yes")


def get_journal_dir() -> str:
    """Directory for the durable event journal (daily-rotated NDJSON). Kept next
    to the DB so the backup lives on the same SSD as the data it protects."""
    return os.environ.get(
        "TICTOK_JOURNAL_DIR", str(PROJECT_ROOT / "journal")
    )


def get_journal_retention_days() -> int:
    """Days to keep journal files. Recovery runs every startup, so loss is caught
    within hours; this window only bounds disk use. 0 disables pruning."""
    return int(os.environ.get("TICTOK_JOURNAL_RETENTION_DAYS", "14"))


# ---- Database maintenance (snapshots / integrity, see tictok/core/dbmaint.py) ----
# The journal above protects the *event stream* against a writer stall; it does not
# protect the database file itself against corruption, a bad migration, or an operator
# mistake. A snapshot taken through SQLite's own backup API is the only thing that does,
# and it is the only correct way to copy a live WAL database — a file copy of tictok.db
# without its -wal is a torn, older image of the data.


def get_db_backup_dir() -> str:
    """Directory holding database snapshots. Next to the DB by default so a snapshot is
    found without configuration; point it at another volume to survive that disk."""
    return os.environ.get(
        "TICTOK_DB_BACKUP_DIR", str(PROJECT_ROOT / "backups")
    )


def get_db_backup_keep() -> int:
    """Snapshot generations kept per reason (manual / pre-migration), oldest pruned
    after a new one lands. A snapshot is a full copy of the database, so generations are
    counted in hundreds of MB each; three is enough to step back past a bad run without
    the folder outgrowing the data it protects. 0 disables pruning."""
    return int(os.environ.get("TICTOK_DB_BACKUP_KEEP", "3"))


def get_db_backup_min_free_ratio() -> float:
    """Free space required before a snapshot starts, as a multiple of the database plus
    its WAL. A snapshot that fills the volume takes the live database down with it, so
    the check refuses up front rather than failing halfway with a partial file."""
    return float(os.environ.get("TICTOK_DB_BACKUP_MIN_FREE_RATIO", "1.2"))


def get_db_backup_before_migration() -> bool:
    """Take a snapshot at startup when a destructive migration is about to rewrite
    existing rows (glove re-judgement / battle topology). Those rewrite battles in place
    and there is no undo; the snapshot is taken once per migration version, not on every
    restart."""
    return os.environ.get("TICTOK_DB_BACKUP_BEFORE_MIGRATION", "1").lower() in ("1", "true", "yes")


def get_db_integrity_check_max_errors() -> int:
    """Rows PRAGMA integrity_check is allowed to report before it stops. A corrupt file
    can produce an unbounded list, and the first handful already identify the damage."""
    return int(os.environ.get("TICTOK_DB_INTEGRITY_CHECK_MAX_ERRORS", "20"))


# ---- ops_events (Layer2 state-transition table, see tictok/storage.py) ----
# The DB layer of the two-layer diagnostic record: every state transition written
# through Storage.record_ops_event lands both in the log (Layer1) and in this
# table (Layer2), correlated by ops_id. Only state transitions are recorded, so
# the table stays in the hundreds of rows per day and these limits exist to bound
# pathological cases rather than normal growth.


def get_ops_events_retention_days() -> int:
    """Days of ops_events kept, pruned at startup. Long by default because this is
    the table an incident is reconstructed from months later, and a state-transition
    row is tiny; 0 disables pruning."""
    return int(os.environ.get("TICTOK_OPS_EVENTS_RETENTION_DAYS", "180"))


def get_ops_events_detail_max_chars() -> int:
    """Cap on the serialized detail JSON of one ops_event. A caller passing an
    unexpectedly large payload (an ffmpeg stderr dump, a full API response) must not
    turn the diagnostic table into the biggest table in the DB; the row is still
    written, with the payload truncated and marked as such."""
    return int(os.environ.get("TICTOK_OPS_EVENTS_DETAIL_MAX_CHARS", "4000"))


def get_ops_events_query_limit() -> int:
    """Default row count returned by an ops_events listing. Sized for one screen of
    incident history without paging."""
    return int(os.environ.get("TICTOK_OPS_EVENTS_QUERY_LIMIT", "200"))


def get_ops_badge_window_hours() -> int:
    """Lookback of the error badge in the page header. This answers "did anything
    break since I last looked", so it is a day rather than the full retention: a
    week-old failure that is already dealt with must not keep the badge lit."""
    return int(os.environ.get("TICTOK_OPS_BADGE_WINDOW_HOURS", "24"))


def get_storage_backlog_warn_rows() -> int:
    """Buffered row count at which the batch writer is reported as falling behind.
    A healthy drain carries roughly one batch (tens of rows); this default is two
    orders of magnitude above that, so it fires only on a real stall or on repeated
    re-queueing, not on a burst."""
    return int(os.environ.get("TICTOK_STORAGE_BACKLOG_WARN_ROWS", "5000"))


# ---- burn-in (video_overlay) diagnostics ----
# Thresholds used only to decide the severity / gating of burn-in log lines. They
# never change what is rendered.


def get_log_overlay_duration_tolerance_frames() -> float:
    """Frames a generated stream may fall SHORT of its reference before the shortfall
    is reported as a defect. The past failure ("burned-in comments disappear part-way
    through") is exactly a comment layer that ends earlier than the base, which
    ffmpeg's overlay eof_action=pass hides, so one frame is the threshold: anything
    larger is a real timeline divergence, not rounding. Only the short side is
    reported — a stream running long is discarded harmlessly at composite time, and
    the concat demuxer routinely leaves the layer a frame or two long."""
    return float(os.environ.get("TICTOK_LOG_OVERLAY_DURATION_TOLERANCE_FRAMES", "1"))


def get_log_overlay_drop_warn_ratio() -> float:
    """Share of events falling outside the video timeline above which the burn-in
    reports the drop as a defect rather than a normal trim. A few events legitimately
    sit outside (the window edges are inclusive of pre-roll/post-roll arrivals); a
    large share means the time origin is broken, which is what made the previous
    Mode B origin incident read as "there were no events"."""
    return float(os.environ.get("TICTOK_LOG_OVERLAY_DROP_WARN_RATIO", "0.05"))


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


def get_ai_chapter_chunk_chars() -> int:
    """Transcript characters per map-stage chat completion. Larger means fewer calls (and
    less wall time), but overflowing the local model's context truncates the reply and
    raises AIError."""
    return int(os.environ.get("TICTOK_AI_CHAPTER_CHUNK_CHARS", "12000"))


def get_ai_chapter_per_chunk() -> int:
    """Max chapter candidates taken from one map-stage chunk."""
    return int(os.environ.get("TICTOK_AI_CHAPTER_PER_CHUNK", "6"))


def get_ai_chapter_max() -> int:
    """Max chapters in the final table of contents."""
    return int(os.environ.get("TICTOK_AI_CHAPTER_MAX", "30"))


def get_ai_chapter_min_seconds() -> float:
    """Minimum gap between adjacent chapters. Closer ones are dropped: they stop reading
    as a table of contents, and platforms ignore chapter marks that short."""
    return float(os.environ.get("TICTOK_AI_CHAPTER_MIN_SECONDS", "60"))


def get_ai_comment_sample_windows() -> int:
    """Number of equal-time windows the session is split into before sampling comments.
    The sample is drawn proportionally from every window, so the reported sentiment is an
    estimate of the whole stream rather than of its final minutes. 1 disables the
    stratification (a single window = the plain tail sample)."""
    return int(os.environ.get("TICTOK_AI_COMMENT_SAMPLE_WINDOWS", "12"))


def get_ai_max_tokens() -> int:
    """Upper bound on the model's reply length. Local quantized models will happily run
    to their context limit on a long comment batch, and a reply cut off mid-object is
    unparseable JSON. 0 omits the field (server default).

    16384 rather than a few thousand because reasoning models spend this same budget on
    their thinking tokens before emitting any JSON: chapter generation measured a hard
    failure at 2048 and 4096, and only completed at 16384. The cut-off is not silent
    (_chat rejects finish_reason=length), so an over-generous ceiling costs nothing but
    a too-small one fails every call."""
    return int(os.environ.get("TICTOK_AI_MAX_TOKENS", "16384"))


def get_ai_json_schema_enabled() -> bool:
    """Send the expected shape as an OpenAI-compatible ``response_format`` json_schema so
    the endpoint constrains decoding instead of the reply being scraped for braces.
    llama.cpp server and Ollama both support it; disable for an endpoint that rejects
    the field (it answers HTTP 400 rather than degrading, which is the intended
    behaviour — there is no silent fallback)."""
    return os.environ.get("TICTOK_AI_JSON_SCHEMA", "1").lower() in ("1", "true", "yes")


def get_ai_review_min_observations() -> int:
    """Minimum n for a cross-session statistic to be offered to the review model as
    established rather than as provisional. Below this the figure is still passed, but
    flagged so the model is told not to draw a conclusion from it."""
    return int(os.environ.get("TICTOK_AI_REVIEW_MIN_OBSERVATIONS", "20"))


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


def get_stt_feature_block_frames() -> int:
    """Number of STFT frames computed per block during feature extraction. faster-whisper's
    numpy feature extractor computes the STFT of the whole waveform in one complex128 array,
    so a multi-hour recording needs gigabytes of contiguous memory and raises MemoryError
    before decoding starts. We compute the identical log-mel in frame blocks of this size to
    bound the transient buffer; the numerics are unchanged (frames are independent). At the
    default, one block's complex64 STFT buffer is ~100MB (block x (n_fft/2+1) x 8 bytes)."""
    return int(os.environ.get("TICTOK_STT_FEATURE_BLOCK_FRAMES", "65536"))


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


# ---- Mixed-resolution normalization (playback-compatibility re-encode at finalize) ----
# A live source that switches resolution mid-broadcast (adaptive bitrate on the
# streamer's side) yields HLS segments of differing sizes. Stream-copying them into one
# mp4 bakes multiple resolutions into a single video track: technically valid, but many
# players freeze/stutter/zoom at each switch point. When enabled (default), finalize
# re-encodes only such mixed-resolution recordings to a single resolution, preserving the
# original frame timestamps so the comment timing map stays valid. Uniform recordings are
# left as the fast, lossless stream-copy. This is not AI and has no external provider; the
# encoder is resolved by capability (GPU when present, else CPU) the same way the burn-in
# does, so it runs on Windows and Linux.


def get_normalize_mixed_resolution() -> bool:
    return os.environ.get("TICTOK_NORMALIZE_MIXED_RESOLUTION", "1").lower() in ("1", "true", "yes")


def get_normalize_codec() -> str:
    """Video codec family for the normalization re-encode: 'h264' (default), 'hevc',
    'av1', or 'auto'. Defaults to H.264 — the whole point of this pass is playback
    compatibility (the mixed-resolution track froze players), so the most universally
    decodable codec is the right default rather than the most space-efficient one
    ('auto' would pick AV1, which many players/hardware cannot decode). Same encoder
    resolution (GPU when available, else CPU) as the burn-in."""
    return os.environ.get("TICTOK_NORMALIZE_CODEC", "h264").strip()


def get_normalize_quality() -> int:
    """Encode quality on the H.264 CRF/CQ scale (lower = higher quality, larger file),
    auto-mapped per codec. This is the only re-encode a recording ever gets (uniform
    streams stay lossless stream-copies), so it favours quality: below ~14 mainly
    inflates size for no visible gain. Override with TICTOK_NORMALIZE_QUALITY."""
    return int(os.environ.get("TICTOK_NORMALIZE_QUALITY", "17"))


def get_overlay_prepass_quality() -> int:
    """焼き込みのCFR base pre-passのencode品質(H.264 CRF/CQ、低いほど高品質・大きい)。

    この中間fileは主passがもう一度encodeし直す**捨て物**で、必要なのは主passの入力として
    視覚的に透過であることだけ。2h43mの録画でCQ16は約17GB(実測14.1Mbps=source 5.9Mbpsの
    2.4倍)に達し、comment layerと合わせて同時38GBを占めていた。世代損失は1回だけなので、
    その1回を「見えない範囲で一番安く」置くのが正しい。TICTOK_OVERLAY_PREPASS_QUALITYで上書き。

    既定が20から14へ下がっているのは、pre-passが**元解像度のまま**焼くようになったため
    (拡大は主passのgraphへ移した)。同じCQでも画素数が数分の1になれば絶対的な誤差は増え、
    その中間fileを後から拡大するぶん誤差も一緒に拡大される。非圧縮の拡大を基準にした実測
    (31分の512x1024 → 1280x2560)では、旧経路(拡大→CQ20)のSSIM 0.9957に対し、新経路の
    CQ20は0.9935へ落ち、CQ14で0.9958と旧経路へ戻る。CQ14でもfileは旧経路の2844MBに対し
    1178MB、時間は178秒に対し35秒。"""
    return int(os.environ.get("TICTOK_OVERLAY_PREPASS_QUALITY", "14"))


def get_overlay_layer_fps_cap() -> float:
    """コメントlayer(alpha中間file)のfps上限。実効fpsは min(映像fps, この値)。

    layerは「内容が変わるframeだけPILで描き、CFRへ引き伸ばしてqtrleへ流す」構造で、実測では
    24万frame中3923(1.6%)しか内容が変わらないのにファイル全体を支配していた(13.7GB)。容量は
    frame数にほぼ比例するので、ここを下げれば直接効く。ただし**下げるとコメントのscrollが
    粗くなる**(出力の見た目が変わる)ため、既定は据え置き、確認した上で下げるための入口として
    設定にしてある。TICTOK_OVERLAY_LAYER_FPS_CAPで上書き。"""
    return float(os.environ.get("TICTOK_OVERLAY_LAYER_FPS_CAP", "30"))


def get_normalize_scale_mode() -> str:
    """How differing frames are fitted onto the single output canvas: 'pad' (preserve
    each rendition's aspect ratio, letterbox the difference — no geometric distortion,
    the safe default) or 'stretch' (fill the canvas, may distort renditions whose aspect
    ratio differs from the target)."""
    return os.environ.get("TICTOK_NORMALIZE_SCALE_MODE", "pad").strip().lower()


# ---- GPU admission control (shared by STT / Up出力 / avatar超解像 / 焼き込み) ----
# Those stages all run on the same device and share one CUDA context. Each serialises
# itself, but without a shared cap several of them can sit on the GPU at once and only
# slow each other down (or exhaust VRAM). tictok.core.gpu enforces the cap; these are its
# only tunables. The LLM stages are deliberately outside it — inference there is an HTTP
# call to an OpenAI-compatible endpoint in another process, which this cannot govern.


def get_gpu_concurrency() -> int:
    """How many GPU-bound media stages may run at once (minimum 1). One is right for a
    single consumer GPU: the stages are individually VRAM-hungry and overlapping them
    lengthens every job. Raise it only on hardware with headroom to spare."""
    return int(os.environ.get("TICTOK_GPU_CONCURRENCY", "1"))


def get_gpu_wait_timeout_seconds() -> float:
    """Give up after waiting this long for a GPU slot (0 = wait indefinitely, the
    default). A queue here is normal and long — a multi-hour Up出力 ahead of you is not
    an error — so the default never times out. Set a bound only when a stuck stage should
    surface as a failure rather than as an indefinite wait."""
    return float(os.environ.get("TICTOK_GPU_WAIT_TIMEOUT_SECONDS", "0"))


# ---- Long-running job registry (server-side progress, reload-tolerant) ----


def get_job_retention_seconds() -> float:
    """How long a finished media job stays in the server's job registry. A page that
    reloads (or opens) within this window still sees the completion or the failure
    instead of an empty list, which would read as 'nothing ever ran'."""
    return float(os.environ.get("TICTOK_JOB_RETENTION_SECONDS", "300"))


# ---- Media job queue (DB-backed, survives a restart) ----


def get_media_queue_poll_seconds() -> float:
    """How long the media job worker sleeps when the queue is empty. Enqueues wake it
    immediately; this only bounds how long a row written by another path (a migration,
    a manual DB edit) waits before it is noticed."""
    return float(os.environ.get("TICTOK_MEDIA_QUEUE_POLL_SECONDS", "5"))


def get_media_queue_workers() -> int:
    """同時に走らせる映像jobの本数(最小1)。

    1本のjobは常にGPUを使い切っているわけではない。再mp4化は前半のconcat(音声encodeと
    disk I/O)でGPUを一切使わず、後半の解像度normalizeでNVENCに張り付く。焼き込みも
    コメント層の描画はCPUで、その間NVENCは空く。直列のままだと、この空き時間ぶんだけ
    bulk全体が延びる。

    実測(RTX 4070 Ti / 46分の録画): NVENC単独76秒に対し、2本同時は1本あたり39秒・3本同時
    は38秒。2本でほぼ2倍の処理量が出て、そこから先は頭打ちになる。

    既定を2にしているのは、この本数までは**焼き込み同士が重ならない**ため。焼き込みはrender
    全体でGPU枠(TICTOK_GPU_CONCURRENCY、既定1)を握るので、2本目は枠待ちで止まり中間fileも
    作らない。つまり既定のままで増えるのは「GPU枠を取らない再mp4化」と「焼き込みの裏で走る
    別種のjob」の重なりだけで、diskの山は再mp4化2本ぶん(元mp4+変換中の一時file)に収まる。

    3以上や、焼き込み同士を重ねる(TICTOK_GPU_CONCURRENCYも上げる)場合は、中間fileの同時
    使用量が本数ぶん増える(焼き込みは1本あたりCFR base+コメント層で数GB〜数十GB)ので、
    空き容量と相談すること。"""
    return max(1, int(os.environ.get("TICTOK_MEDIA_QUEUE_WORKERS", "2")))


def get_job_progress_min_interval_seconds() -> float:
    """Minimum gap between two progress notifications that carry the same overall
    percent. The percent alone changes at most 100 times per job, but the stage detail
    (frame counters, encode position) changes continuously, and every notification is a
    DB write plus a websocket broadcast to every open page. This gate is what keeps a
    multi-hour job's detail text live without turning it into tens of thousands of
    writes. A change in percent is always sent immediately, regardless of this gap."""
    return float(os.environ.get("TICTOK_JOB_PROGRESS_MIN_INTERVAL_SECONDS", "2"))


def get_media_job_attempts() -> int:
    """Total runs of a media job before it is recorded as failed (1 = no retry).
    A burn-in dies on transient conditions that are gone seconds later — the output
    directory locked by an antivirus scan, an ffmpeg spawn refused while the disk is
    busy — and without a retry those land as a permanent failure that only a human
    re-queue undoes. The default keeps this to a single retry because the other class of
    failure (a genuine defect in the input) costs hours of GPU time per attempt."""
    return int(os.environ.get("TICTOK_MEDIA_JOB_ATTEMPTS", "2"))


def get_media_job_retry_backoff_seconds() -> float:
    """Base wait before re-running a failed media job; the Nth retry waits base * N.
    Long enough for a file lock or a disk-busy spike to clear."""
    return float(os.environ.get("TICTOK_MEDIA_JOB_RETRY_BACKOFF_SECONDS", "10"))


def get_media_job_defer_seconds() -> float:
    """Wait before a deferred media job becomes runnable again.

    A retry (get_media_job_attempts) answers a failure that is gone in seconds. It cannot
    answer a storage volume that went away: the final dir dropping off the bus takes it
    out for minutes, both attempts burn inside 10 seconds, and the job lands as failed
    with the recording left half-rebuilt. Deferring returns the job to the queue instead
    of consuming an attempt, so the run continues on its own once the volume is back."""
    return float(os.environ.get("TICTOK_MEDIA_JOB_DEFER_SECONDS", "60"))


def get_media_job_defer_timeout_seconds() -> float:
    """How long a job may stay deferred before it is recorded as failed. Waiting without
    a bound would leave a queue that looks alive while nothing can ever run."""
    return float(os.environ.get("TICTOK_MEDIA_JOB_DEFER_TIMEOUT_SECONDS", "7200"))


def get_media_job_auto_requeue_limit() -> int:
    """How many times a job interrupted by a server restart is put back on the queue by
    itself (0 disables). A bulk run spans hours, so a restart in the middle used to leave
    its remaining members as permanent holes that only a human noticed. The cap is what
    keeps a job that takes the process down with it from re-running on every boot."""
    return int(os.environ.get("TICTOK_MEDIA_JOB_AUTO_REQUEUE_LIMIT", "3"))


def get_transcribe_job_attempts() -> int:
    """Total runs of a transcription job before it is recorded as failed (1 = no retry).
    Higher than the media default: STT reads the file and holds the GPU for minutes
    rather than hours, so a retry is cheap, and a CUDA allocation refused while another
    job releases VRAM is exactly the transient this covers."""
    return int(os.environ.get("TICTOK_TRANSCRIBE_JOB_ATTEMPTS", "3"))


def get_transcribe_job_retry_backoff_seconds() -> float:
    """Base wait before re-running a failed transcription; the Nth retry waits base * N."""
    return float(os.environ.get("TICTOK_TRANSCRIBE_JOB_RETRY_BACKOFF_SECONDS", "10"))


def get_media_job_history_days() -> float:
    """How long finished media job rows stay in the DB for the job centre's history
    (0 = never prune). These rows are small and are the only record of what was asked
    for, so the default keeps a fortnight rather than minutes."""
    return float(os.environ.get("TICTOK_MEDIA_JOB_HISTORY_DAYS", "14"))


# ---- Spike detection (streamer highlights / clip candidates, see core/spike.py) ----


def get_highlight_zscore() -> float:
    """Threshold (in standard deviations above the session's own mean) at which a window
    counts as a highlight on the streamer page. The clip-candidate screen passes its own
    設定値 explicitly; this is the default the highlight list uses, and the two share one
    detector so the same moment is named on both screens."""
    return float(os.environ.get("TICTOK_HIGHLIGHT_ZSCORE", "2.0"))


# ---- Audio profile (silence / loudness, derived from the waveform decode) ----


def get_audio_profile_interval_seconds() -> float:
    """Resolution of the absolute-level series kept alongside the display waveform.
    The waveform decode already produces a 20ms peak series and throws it away; keeping
    it at this resolution costs a few kB per recording and means silence and loudness
    spikes are answerable without decoding the container again."""
    return float(os.environ.get("TICTOK_AUDIO_PROFILE_INTERVAL_SECONDS", "1.0"))


def get_audio_silence_dbfs() -> float:
    """Level (dBFS, full scale = 0) below which an interval counts as silent. Measured
    against full scale rather than against the recording's own peak, because a stream
    that is quiet throughout must not have its noise floor promoted to 'audible'."""
    return float(os.environ.get("TICTOK_AUDIO_SILENCE_DBFS", "-50"))


def get_audio_silence_min_seconds() -> float:
    """Shortest run of silent intervals reported as a silent span. Below this the gap is
    a pause between words, not a place a clip can be cut."""
    return float(os.environ.get("TICTOK_AUDIO_SILENCE_MIN_SECONDS", "2.0"))


# ---- Clip export ----


def get_clip_duration_tolerance_seconds() -> float:
    """How far a written clip may differ from the requested length before it is logged
    as a mismatch. Stream copy can only start on a keyframe, and keyframe spacing is set
    by the broadcaster, not by the 2s HLS segmenting: measured 2.1s-37.6s across real
    recordings. A copy clip therefore runs *long* by up to one GOP, which is normal and
    is not checked; only a clip shorter than requested trips this, which is what catches
    an audio filter silently changing the length."""
    return float(os.environ.get("TICTOK_CLIP_DURATION_TOLERANCE_SECONDS", "1.0"))


def get_clip_sidecar_enabled() -> bool:
    """Whether a clip export also writes the transcript/comment sidecars next to the mp4.
    The clip itself is a stream copy of a video+audio recording, so nothing about what was
    said or posted survives into the file; without the sidecars that material stays in the
    DB and the clip reaches an NLE as pictures and sound only."""
    return os.environ.get("TICTOK_CLIP_SIDECAR", "1").lower() in ("1", "true", "yes")


def get_comment_subtitle_seconds() -> float:
    """How long one comment cue stays on screen. Comments are point events (they have a
    post time and no duration), so a cue length has to come from somewhere; this is it.
    A cue is cut short when the next one opens, so this is an upper bound, not a fixed
    length."""
    return float(os.environ.get("TICTOK_COMMENT_SUBTITLE_SECONDS", "4.0"))


def get_comment_subtitle_max_lines() -> int:
    """How many comments may share one cue. Comments arriving while a cue is open are
    merged into it rather than opening an overlapping cue, because SRT cues are meant to
    be sequential and overlapping ones are dropped or mis-ordered by many parsers. Past
    this count the cue closes early so a burst does not become a wall of text."""
    return int(os.environ.get("TICTOK_COMMENT_SUBTITLE_MAX_LINES", "4"))


# ---- 通知(webhook) ----
# 宛先URLだけは設定画面(DB)ではなく.env/環境変数に置く。Discord/Slackのwebhook URLは
# それ自体が投稿権限を持つ資格情報であり、設定画面の値は(a)画面に平文で表示され、
# (b)変更時にsettings.updateがold->newをops_eventsへ書き込み保持期間ぶん残る。
# 資格情報の置き場は既にEulerStream API keyで .env と決まっているので、そこへ揃える。
# 閾値・有効無効・retry上限といった資格情報でない項目はSettings(設定画面)側にある。


def get_notify_webhook_urls() -> list:
    """通知の宛先webhook URL。カンマ区切りで複数指定でき、全宛先へ同じ通知を送る。
    空(未設定)なら通知は組み立てず送信もしない。"""
    raw = os.environ.get("TICTOK_NOTIFY_WEBHOOK_URL", "")
    return [url.strip() for url in raw.split(",") if url.strip()]


def get_notify_webhook_format() -> str:
    """webhookのpayload形式。Discord/Slack/汎用receiverでbodyのschemaが違うため、
    送信側が合わせる必要がある。既定の"auto"は宛先hostから判定する(判定できなければ
    汎用JSON)。host判定を使わず固定したい場合に discord / slack / generic を明示する。"""
    return os.environ.get("TICTOK_NOTIFY_WEBHOOK_FORMAT", "auto").strip().lower()


def get_notify_queue_max() -> int:
    """送信待ちalertの上限。通知は本体(収集・録画)から切り離したqueue越しに送るため、
    宛先が落ちている間もqueueは伸び続ける。上限に達したら新しいalertを捨て、捨てたことを
    ops_eventsへ残す(無音で溜め続けてmemoryを食う方が悪い)。"""
    return int(os.environ.get("TICTOK_NOTIFY_QUEUE_MAX", "500"))


def get_notify_shutdown_drain_seconds() -> float:
    """shutdown時に送信待ちを吐き切るのを待つ秒数。ここを無制限にすると宛先が落ちている
    ときにserverが終了できなくなる。"""
    return float(os.environ.get("TICTOK_NOTIFY_SHUTDOWN_DRAIN_SECONDS", "5.0"))
