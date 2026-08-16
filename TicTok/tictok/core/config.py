import inspect
import logging
import math
import os
from pathlib import Path
from typing import NoReturn

from tictok.paths import PROJECT_ROOT

logger = logging.getLogger("tictok.config")


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


# ---- 環境変数の型付き読み出し ----
# この下のgetterはどれも「環境変数を1つ読み、型を付け、未設定なら既定値を返す」だけだが、
# その型付けは以前すべて手書きで、int()/float()が107箇所あって ValueError の処理は0箇所
# だった。結果、.env の打ち間違い1つが**起動時ではなくその設定を最初に読む時点**で例外に
# なる。値の多くはmedia jobの実行中にしか読まれないので、1文字の誤りが数時間後のjob失敗や
# 深い場所の500として現れ、原因が環境変数だとは分からなかった。
#
# 不正値は「何が不正で・どう直すかを含むlogを残した上で例外」に統一する。黙って既定値へ
# 落とすfallbackは持たない: 設定したつもりの値が効かないまま動き続けるのは、打ち間違いより
# 質の悪い状態(例えば TICTOK_AI_ENABLED=ture は機能を丸ごと無効にしながら何も言わない)。
# そのうえで validate_env() が起動時に全getterを1度呼び、不正なkeyをまとめて報告する。
#
# 範囲(最小/最大)の検証はここでは行わない。範囲を持つ設定は SETTING_DEFS 側にあり、
# Settings._env_default が同じ方針(logを残して例外)で検証している。ここが見るのは型だけ。

_TRUE_TOKENS = ("1", "true", "yes", "on")
_FALSE_TOKENS = ("0", "false", "no", "off")


class ConfigError(ValueError):
    """環境変数の値が要求された型として読めないことを表す。

    ValueError を継承しているのは、この失敗が以前 int()/float() の素の ValueError として
    出ていたため。既に ValueError を捕まえている呼び出し側の挙動を変えないまま、config由来
    かどうかを isinstance で区別できるようにする。"""


def _reject(key: str, raw: str, expected: str, default) -> NoReturn:
    """不正なenv varを報告して例外にする。

    logは例外を投げる側で出す。この失敗はjobの深い場所で起きうるので、例外だけだと呼び出し
    経路の都合で握り潰されたり、どのkeyが原因かを含まないmessageに化けたりする。dedupは
    logging側の抑制器(TICTOK_LOG_DEDUP_WINDOW_SECONDS)に任せ、ここでは状態を持たない。"""
    logger.error(
        "環境変数の値が%sとして読めません: %s=%r（既定値は %r。この行を削除すれば既定値に戻ります）",
        expected, key, raw, default,
        extra={"event": "process.config_env_invalid",
               "ctx": {"key": key, "raw": raw, "expected": expected, "default": default}},
    )
    raise ConfigError(
        f"環境変数 {key} の値が{expected}として読めません: {raw!r}（既定値 {default!r}）"
    )


def _env_int(key: str, default: int) -> int:
    """整数のenv var。未設定なら default、読めなければ ConfigError。"""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except ValueError:
        _reject(key, raw, "整数", default)


def _env_float(key: str, default: float) -> float:
    """実数のenv var。未設定なら default、読めなければ ConfigError。

    nan / inf は float() を通ってしまうが弾く。閾値として使うと比較が常に偽になり、
    「その閾値が効いていない」ことは出力を見ても気付けない。"""
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        _reject(key, raw, "実数", default)
    if not math.isfinite(value):
        _reject(key, raw, "有限の実数", default)
    return value


def _env_bool(key: str, default: bool) -> bool:
    """真偽値のenv var。未設定なら default、解釈できない値なら ConfigError。

    受理するtokenは 1/true/yes/on(真) と 0/false/no/off(偽)、大文字小文字と前後の空白は
    問わない。以前は真tokenに一致するかだけを見ていたため、``ture`` のような打ち間違いは
    静かに偽になっていた。"""
    raw = os.environ.get(key)
    if raw is None:
        return default
    token = raw.strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    _reject(key, raw, f"真偽値({'/'.join(_TRUE_TOKENS)} または {'/'.join(_FALSE_TOKENS)})", default)


def validate_env() -> list:
    """全設定を1度ずつ解決し、不正なenv varをまとめて報告してから例外にする。

    serverの起動直後、logging設定の**後**に1度呼ぶ。個々のgetterは呼ばれた時点で例外に
    するが、それだけでは「その設定を最初に使う機能」を動かすまで打ち間違いに気付けない。
    ここで全部呼べば起動の時点で分かり、しかも全件まとめて分かる — 1つ直しては再起動して
    次の1つを見つける、を繰り返させないため、最初の1件で止めずに全getterを回してから
    投げる。

    import時に自動実行しないのは、このmoduleが logging_setup 自身からimportされるため
    (dotenv_summary の説明と同じ理由)。import時点ではhandlerがまだ無く、「どのkeyがどう
    不正か」を伝えるlogが出力先を持たない — 起動が理由の分からないtracebackで死ぬ。

    引数を取るgetter(DB pathを要求するもの)は環境変数だけでは解決できないので除く。
    戻り値は問題が無かったときの空list。"""
    problems = []
    for name in sorted(globals()):
        if not name.startswith("get_"):
            continue
        getter = globals()[name]
        if not callable(getter):
            continue
        parameters = inspect.signature(getter).parameters.values()
        if any(parameter.default is inspect.Parameter.empty for parameter in parameters):
            continue
        try:
            getter()
        except ConfigError as exc:
            problems.append(str(exc))
    if problems:
        logger.error(
            "環境変数の設定値が%d件不正です。起動前に .env を修正してください: %s",
            len(problems), " / ".join(problems),
            extra={"event": "process.config_env_invalid_summary",
                   "ctx": {"count": len(problems), "problems": problems}},
        )
        raise ConfigError(
            f"環境変数の設定値が{len(problems)}件不正です: " + " / ".join(problems)
        )
    logger.info(
        "環境変数の設定値を検証しました（問題なし）",
        extra={"event": "process.config_env_validated"},
    )
    return problems


def get_host() -> str:
    return os.environ.get("TICTOK_HOST", "127.0.0.1")


def get_port() -> int:
    return _env_int("TICTOK_PORT", 8520)


def get_log_level() -> str:
    return os.environ.get("TICTOK_LOG_LEVEL", "INFO")


def get_db_path() -> str:
    return os.environ.get(
        "TICTOK_DB_PATH", str(PROJECT_ROOT / "tictok.db")
    )


def get_timeline_limit() -> int:
    return _env_int("TICTOK_TIMELINE_LIMIT", 2160)


def get_simulation() -> bool:
    return _env_bool("TICTOK_SIMULATION", False)


def get_no_restore() -> bool:
    """監視対象を復元せずに起動するか。

    既定の起動は前回の監視対象をそのまま復元するため、「確認のためにserverを上げる」だけで
    実配信へ接続し、録画fileをdiskへ書く。同じ配信をuserのserverが録画していれば二重録画に
    なる。CI・静的解析・手動検証はこれを1に設定して起動する(監視の追加・削除操作そのものは
    通常どおり効くので、機能検証の妨げにはならない)。"""
    return _env_bool("TICTOK_NO_RESTORE", False)


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
    return _env_bool("TICTOK_RESOLVER_HEADLESS", True)


def get_resolver_timeout_ms() -> int:
    return _env_int("TICTOK_RESOLVER_TIMEOUT_MS", 20000)


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
    return _env_int("TICTOK_LOG_MAX_BYTES", 20971520)


def get_log_retention_days() -> int:
    """Days to keep rotated logs. 0 (default) disables pruning: logs are diagnostic
    assets and an unexplained deletion is worse than disk use, which compression
    already bounds. Set a value to cap growth on a small volume."""
    return _env_int("TICTOK_LOG_RETENTION_DAYS", 0)


def get_log_compress() -> bool:
    """Gzip rotated files. Runs on a worker thread, never on the event loop."""
    return _env_bool("TICTOK_LOG_COMPRESS", True)


def get_log_compress_level() -> int:
    """Gzip level for rotated files. 9 costs roughly double the CPU of 6 for a few
    percent on text."""
    return _env_int("TICTOK_LOG_COMPRESS_LEVEL", 6)


def get_log_jsonl_enabled() -> bool:
    """Write the machine-readable JSONL stream alongside the text log."""
    return _env_bool("TICTOK_LOG_JSONL_ENABLED", True)


def get_log_jsonl_level() -> str:
    """Level for the JSONL stream. Empty follows TICTOK_LOG_LEVEL; the two streams
    are kept identical by default so text and JSONL never disagree."""
    return os.environ.get("TICTOK_LOG_JSONL_LEVEL", "").strip()


def get_log_queue_enabled() -> bool:
    """Hand formatting and file writes to a listener thread so a log call on the
    event loop costs only a filter evaluation and a queue put. Disable to write
    synchronously when debugging the logging path itself."""
    return _env_bool("TICTOK_LOG_QUEUE_ENABLED", True)


def get_log_dedup_window_seconds() -> int:
    """Window in which an identical repeating record is collapsed to a count. The
    first occurrence is always emitted and the count is always reported, so nothing
    is hidden. 0 disables suppression."""
    return _env_int("TICTOK_LOG_DEDUP_WINDOW_SECONDS", 60)


def get_log_dedup_max_tracked() -> int:
    """Cap on distinct fingerprints held by the suppressor, bounding its memory."""
    return _env_int("TICTOK_LOG_DEDUP_MAX_TRACKED", 2000)


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
    return _env_int("TICTOK_LOG_ROTATE_RETRY_ATTEMPTS", 5)


def get_log_rotate_retry_delay_seconds() -> float:
    return _env_float("TICTOK_LOG_ROTATE_RETRY_DELAY_SECONDS", 0.2)


def get_log_shutdown_drain_seconds() -> float:
    """How long shutdown waits for in-flight compression before exiting."""
    return _env_float("TICTOK_LOG_SHUTDOWN_DRAIN_SECONDS", 10.0)


def get_log_battle_raw_gzip() -> bool:
    """Gzip battle raw-event captures when their session closes. These are the
    largest files the app writes and compress roughly 35:1."""
    return _env_bool("TICTOK_LOG_BATTLE_RAW_GZIP", True)


def get_log_progress_interval_seconds() -> float:
    """Minimum gap between periodic progress lines from long-running jobs. The gap
    grows geometrically per job so a very slow job does not emit proportionally
    more lines; DEBUG collapses it to every tick."""
    return _env_float("TICTOK_LOG_PROGRESS_INTERVAL_SECONDS", 60.0)


def get_log_progress_interval_max_seconds() -> float:
    return _env_float("TICTOK_LOG_PROGRESS_INTERVAL_MAX_SECONDS", 600.0)


def get_log_progress_interval_growth() -> float:
    """Factor the progress interval is multiplied by after each emitted line, up to
    the max above. A fixed interval is wrong for jobs whose speed spans orders of
    magnitude: the quality upscale path runs at ~0.23 fps (107x real time), where a
    fixed 60s gate would emit thousands of lines for one job. Growth keeps the early
    lines close together — so a job that dies in its first minutes still leaves a
    trace — and thins them out as the job proves long-running. 1.0 disables growth."""
    return _env_float("TICTOK_LOG_PROGRESS_INTERVAL_GROWTH", 1.6)


def get_log_progress_percent_step() -> float:
    """Minimum completion percent a job must advance between two progress lines.
    This is what actually bounds the line count of an arbitrarily long job: the time
    interval alone cannot, since a job 100x slower than real time runs 100x longer.
    At the default a job emits at most ~100 progress lines regardless of duration.
    0 disables the completion gate, leaving only the time interval."""
    return _env_float("TICTOK_LOG_PROGRESS_PERCENT_STEP", 1.0)


def get_log_slow_http_ms() -> float:
    """Request duration above which an HTTP request is logged. Successful fast
    requests are not logged at all: on a single-user deployment the polling
    endpoints would otherwise dominate the log with no diagnostic value."""
    return _env_float("TICTOK_LOG_SLOW_HTTP_MS", 1000.0)


def get_log_slow_analytics_ms() -> float:
    """Analytics stage duration above which the stage is logged as slow."""
    return _env_float("TICTOK_LOG_SLOW_ANALYTICS_MS", 2000.0)


def get_log_access_rollup_seconds() -> float:
    """Minimum gap between access-log lines sharing a route and status. Bounds a
    404 storm to a countable trickle without hiding a different route's failure."""
    return _env_float("TICTOK_LOG_ACCESS_ROLLUP_SECONDS", 60.0)


def get_log_access_gate_max_keys() -> int:
    """Cap on distinct (route, status) pairs the access-log gate tracks, bounding its
    memory. The routed key space is the number of endpoints times a handful of failure
    statuses, so this default is far above normal use and is reached only when unmatched
    paths are being probed."""
    return _env_int("TICTOK_LOG_ACCESS_GATE_MAX_KEYS", 500)


def get_log_slow_analytics_payload_ms() -> float:
    """Duration above which one session's analytics payload is reported on its own. A
    single request reduces hundreds of per-session payloads, so this must sit well below
    the whole-stage threshold to name the session responsible rather than only the stage
    that contains it."""
    return _env_float("TICTOK_LOG_SLOW_ANALYTICS_PAYLOAD_MS", 200.0)


def get_log_ffmpeg_stderr_chars() -> int:
    """Characters of ffmpeg stderr retained on failure. The cause is at the tail."""
    return _env_int("TICTOK_LOG_FFMPEG_STDERR_CHARS", 800)


def get_ffmpeg_loglevel() -> str:
    """``-loglevel`` given to the long media renders. ``error`` は不足だった: 出力の片側
    streamが途中で終わる障害はffmpegが**rc=0のまま**返し、痕跡はwarning段
    (decode error/non-monotonous DTS/packet corrupt) にしか出ない。stderrはfileへ
    向けるので、既定をwarningへ上げても端末は汚れない。"""
    return os.environ.get("TICTOK_FFMPEG_LOGLEVEL", "warning")


def get_ffmpeg_log_keep_on_success() -> bool:
    """Keep the render's ffmpeg stderr log even when it succeeds. 既定は破棄(成功logは
    録画1本あたり無制限に溜まる)。片側streamの尾切れを追う調査中だけ 1 にして、正常だった
    回のlogも突き合わせられるようにする。不足を検出した回のlogは、この値に関わらず残る。"""
    return _env_bool("TICTOK_FFMPEG_LOG_KEEP_ON_SUCCESS", False)


def get_log_disk_low_bytes() -> int:
    """Free space below which a preflight check warns before starting a job that
    writes a large intermediate. Disk exhaustion has previously surfaced only as an
    unrelated-looking rendering failure."""
    return _env_int("TICTOK_LOG_DISK_LOW_BYTES", 5 * 1024 * 1024 * 1024)


def get_log_restriction_text_chars() -> int:
    """Characters of the TikTok restriction payload (message / prompts) retained in
    the log. The restriction *type* (18+ / members-only / rate limit) is only
    distinguishable from this wording, and it is carried in the first sentence, so a
    few hundred characters identify it while a full payload dump would burn rotation
    budget on a line that repeats for every blocked broadcast."""
    return _env_int("TICTOK_LOG_RESTRICTION_TEXT_CHARS", 800)


def get_log_stream_url_expiry_warn_seconds() -> float:
    """Remaining lifetime of a TikTok pull URL below which launching a recording on
    it is flagged. Empty recordings are caused by a URL that expired between
    room_info and ffmpeg's first read; without this the log shows only "captured 0
    bytes" and the cause has to be guessed. TikTok issues these URLs with lifetimes
    measured in hours, so a URL with less than a couple of minutes left is already
    the anomaly rather than a tight-but-normal launch."""
    return _env_float("TICTOK_LOG_STREAM_URL_EXPIRY_WARN_SECONDS", 120.0)


def get_log_live_wait_interval_seconds() -> float:
    """Minimum gap between "still waiting for a live to start" lines from one
    monitor. Separate from the generic progress interval and much longer: an offline
    streamer is the steady state of every monitor, so this line exists only to prove
    the watch loop is alive and to date the last probe, and at the generic 60s it
    would be the highest-volume line in the file. DEBUG collapses it to every poll."""
    return _env_float("TICTOK_LOG_LIVE_WAIT_INTERVAL_SECONDS", 900.0)


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
    return _env_float("TICTOK_BATTLE_GIFT_WINDOW_FALLBACK_SECONDS", 300.0)


def get_journal_enabled() -> bool:
    """Durable append-only event journal on disk. Every event/viewer sample is
    appended here at ingest time, independent of the batched SQLite writer, so a
    writer stall or crash cannot silently lose the raw stream: startup re-imports
    any journalled rows missing from the DB. On by default."""
    return _env_bool("TICTOK_JOURNAL_ENABLED", True)


def get_journal_dir() -> str:
    """Directory for the durable event journal (daily-rotated NDJSON). Kept next
    to the DB so the backup lives on the same SSD as the data it protects."""
    return os.environ.get(
        "TICTOK_JOURNAL_DIR", str(PROJECT_ROOT / "journal")
    )


def get_journal_retention_days() -> int:
    """Days to keep journal files. Recovery runs every startup, so loss is caught
    within hours; this window only bounds disk use. 0 disables pruning."""
    return _env_int("TICTOK_JOURNAL_RETENTION_DAYS", 14)


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
    return _env_int("TICTOK_DB_BACKUP_KEEP", 3)


def get_db_backup_min_free_ratio() -> float:
    """Free space required before a snapshot starts, as a multiple of the database plus
    its WAL. A snapshot that fills the volume takes the live database down with it, so
    the check refuses up front rather than failing halfway with a partial file."""
    return _env_float("TICTOK_DB_BACKUP_MIN_FREE_RATIO", 1.2)


def get_db_backup_before_migration() -> bool:
    """Take a snapshot at startup when a destructive migration is about to rewrite
    existing rows (glove re-judgement / battle topology). Those rewrite battles in place
    and there is no undo; the snapshot is taken once per migration version, not on every
    restart."""
    return _env_bool("TICTOK_DB_BACKUP_BEFORE_MIGRATION", True)


def get_db_integrity_check_max_errors() -> int:
    """Rows PRAGMA integrity_check is allowed to report before it stops. A corrupt file
    can produce an unbounded list, and the first handful already identify the damage."""
    return _env_int("TICTOK_DB_INTEGRITY_CHECK_MAX_ERRORS", 20)


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
    return _env_int("TICTOK_OPS_EVENTS_RETENTION_DAYS", 180)


def get_ops_events_detail_max_chars() -> int:
    """Cap on the serialized detail JSON of one ops_event. A caller passing an
    unexpectedly large payload (an ffmpeg stderr dump, a full API response) must not
    turn the diagnostic table into the biggest table in the DB; the row is still
    written, with the payload truncated and marked as such."""
    return _env_int("TICTOK_OPS_EVENTS_DETAIL_MAX_CHARS", 4000)


def get_ops_events_query_limit() -> int:
    """Default row count returned by an ops_events listing. Sized for one screen of
    incident history without paging."""
    return _env_int("TICTOK_OPS_EVENTS_QUERY_LIMIT", 200)


def get_ops_badge_window_hours() -> int:
    """Lookback of the error badge in the page header. This answers "did anything
    break since I last looked", so it is a day rather than the full retention: a
    week-old failure that is already dealt with must not keep the badge lit."""
    return _env_int("TICTOK_OPS_BADGE_WINDOW_HOURS", 24)


# ---- API perf (core.perf) ----
# 計測そのものの設定。どれも「何を測るか」ではなく「どれだけ憶えておくか / いつ書き出すか」
# だけを決める。閾値を変えても応答の中身は変わらない。


def get_perf_enabled() -> bool:
    """Whether per-route timing is collected at all. On is the default: the cost is
    one ContextVar read plus a perf_counter per instrumented step, and without it the
    only evidence of a slow screen is the single slow-request line, which names the
    route but never where inside it the time went."""
    return _env_bool("TICTOK_PERF_ENABLED", True)


def get_perf_sample_window() -> int:
    """Recent durations kept per route for the percentiles. Percentiles need the
    individual samples, not a running total, and keeping every sample of a polling
    endpoint would grow without bound; this window is what "p95" is measured over,
    so it must be wide enough that one slow reload does not own the number."""
    return _env_int("TICTOK_PERF_SAMPLE_WINDOW", 512)


def get_perf_rollup_seconds() -> float:
    """Gap between the periodic per-route summary lines. This is the line that says
    which API dominated the interval, so it is deliberately far apart from the
    per-request slow line: it answers "what is costing the most overall", which no
    amount of individual slow lines adds up to. 0 disables the summary."""
    return _env_float("TICTOK_PERF_ROLLUP_SECONDS", 300.0)


def get_perf_rollup_top() -> int:
    """Routes named in one summary line, ranked by total time in the interval. The
    remainder is still counted in the line's totals, only not named."""
    return _env_int("TICTOK_PERF_ROLLUP_TOP", 8)


def get_perf_max_routes() -> int:
    """Cap on distinct routes tracked. The key is the endpoint function name, so the
    real key space is the number of endpoints; this sits far above it and is reached
    only if something starts inventing keys."""
    return _env_int("TICTOK_PERF_MAX_ROUTES", 400)


def get_perf_loop_lag_interval_seconds() -> float:
    """Sleep of the event-loop lag probe. The probe measures how much longer than
    this its own sleep actually took, which is the time some coroutine held the loop
    without awaiting — the failure that makes every screen slow at once while each
    individual request still looks fast."""
    return _env_float("TICTOK_PERF_LOOP_LAG_INTERVAL_SECONDS", 0.5)


def get_perf_loop_lag_warn_ms() -> float:
    """Loop lag above which the probe reports, naming the requests in flight at that
    moment. Below this, blocking is short enough to be indistinguishable from normal
    scheduling and OS timer granularity."""
    return _env_float("TICTOK_PERF_LOOP_LAG_WARN_MS", 500.0)


def get_storage_backlog_warn_rows() -> int:
    """Buffered row count at which the batch writer is reported as falling behind.
    A healthy drain carries roughly one batch (tens of rows); this default is two
    orders of magnitude above that, so it fires only on a real stall or on repeated
    re-queueing, not on a burst."""
    return _env_int("TICTOK_STORAGE_BACKLOG_WARN_ROWS", 5000)


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
    return _env_float("TICTOK_LOG_OVERLAY_DURATION_TOLERANCE_FRAMES", 1.0)


def get_overlay_output_tolerance_seconds() -> float:
    """成果物の**stream別**の尺が、期待尺および相互から離れてよい上限(秒)。

    これは診断ではなく合否判定である。焼き込みは実測でrc=0のまま片側streamだけが
    3割前後で終わることがあり(video 4859s/audio 12252s 等)、container尺は長い側を
    名乗るため ``format=duration`` では素通りする。正常な回のv/a差は実測0.3秒未満
    (mp4のtrack終端の量子化ぶん)なので、1桁の秒で誤検知は起きない。"""
    return _env_float("TICTOK_OVERLAY_OUTPUT_TOLERANCE_SECONDS", 2.0)


def get_log_overlay_drop_warn_ratio() -> float:
    """Share of events falling outside the video timeline above which the burn-in
    reports the drop as a defect rather than a normal trim. A few events legitimately
    sit outside (the window edges are inclusive of pre-roll/post-roll arrivals); a
    large share means the time origin is broken, which is what made the previous
    Mode B origin incident read as "there were no events"."""
    return _env_float("TICTOK_LOG_OVERLAY_DROP_WARN_RATIO", 0.05)


def get_avatar_fetch_concurrency() -> int:
    """Max simultaneous avatar downloads. Caps the burst when many comments
    arrive at once so fetches do not exhaust the connection pool and time out."""
    return _env_int("TICTOK_AVATAR_FETCH_CONCURRENCY", 6)


def get_avatar_fetch_attempts() -> int:
    """Total avatar download attempts (1 = no retry) for transient failures."""
    return _env_int("TICTOK_AVATAR_FETCH_ATTEMPTS", 3)


def get_avatar_fetch_backoff_seconds() -> float:
    """Base back-off between avatar download retries. The Nth retry waits
    base * N seconds so a transiently failing CDN is not hammered (which risks
    rate-limit blocking)."""
    return _env_float("TICTOK_AVATAR_FETCH_BACKOFF_SECONDS", 1.5)


# ---- capture時のasset先行取得 (tictok.media.asset_prefetch) ----


def get_asset_prefetch_enabled() -> bool:
    """配信中にgift icon / user avatar / custom emoteをpoolへ先行取得するか。

    既定ON。切ると、これらのassetはCDN URLが新鮮な間に保存されなくなる。URLは配信終了後
    403になるため後から取り直せず、焼き込みのavatarは頭文字円盤へ、emoteは透明な余白へ
    縮退し、履歴とbrowser proxyのavatarも同時に失われる。帯域を絞る目的で切る場合は
    その代償を承知した上で切ること。"""
    return _env_bool("TICTOK_ASSET_PREFETCH_ENABLED", True)


def get_asset_prefetch_concurrency() -> int:
    """先行取得のworker本数 = 同時download数の上限。コメントが殺到しても実際にCDNを叩く
    本数はここで頭打ちになる。1件あたりの取得は数百msなので、既定でも毎秒数十件を捌ける。"""
    return _env_int("TICTOK_ASSET_PREFETCH_CONCURRENCY", 8)


def get_asset_prefetch_queue_size() -> int:
    """先行取得queueの上限件数。溢れたぶんは捨てて(logへ残して)収集を止めない。取得待ちが
    この件数を超えるのは、CDNが応答しないか配信が桁違いに荒れている場合だけで、そこで
    queueを伸ばしても取得は追いつかず、event処理の側がmemoryを食うだけになる。"""
    return _env_int("TICTOK_ASSET_PREFETCH_QUEUE_SIZE", 4000)


def get_asset_prefetch_rate_per_second() -> float:
    """先行取得が要求を開始してよい毎秒件数の上限。worker本数とは別の軸で、短時間に
    集中した取得がCDNのrate limitに当たるのを防ぐ。0以下で無制限。"""
    return _env_float("TICTOK_ASSET_PREFETCH_RATE_PER_SECOND", 16.0)


# ---- Local AI (OpenAI-compatible endpoint: Ollama / llama.cpp server / LM Studio) ----
# Provider/model/endpoint are NOT hard-coded into logic; they are deployment config so
# the same code runs against any local quantized model. AI is opt-in (disabled by default)
# and there is no fallback: when disabled or unreachable the feature reports unavailable
# rather than substituting a fake result.


def get_ai_enabled() -> bool:
    return _env_bool("TICTOK_AI_ENABLED", False)


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
    return _env_float("TICTOK_AI_TIMEOUT_SECONDS", 120.0)


def get_ai_comment_sample() -> int:
    """Max comments sent to the model per analysis (caps prompt size / latency)."""
    return _env_int("TICTOK_AI_COMMENT_SAMPLE", 300)


def get_ai_chapter_chunk_chars() -> int:
    """Transcript characters per map-stage chat completion. Larger means fewer calls (and
    less wall time), but overflowing the local model's context truncates the reply and
    raises AIError."""
    return _env_int("TICTOK_AI_CHAPTER_CHUNK_CHARS", 12000)


def get_ai_chapter_per_chunk() -> int:
    """Max chapter candidates taken from one map-stage chunk."""
    return _env_int("TICTOK_AI_CHAPTER_PER_CHUNK", 6)


def get_ai_chapter_max() -> int:
    """Max chapters in the final table of contents."""
    return _env_int("TICTOK_AI_CHAPTER_MAX", 30)


def get_ai_chapter_min_seconds() -> float:
    """Minimum gap between adjacent chapters. Closer ones are dropped: they stop reading
    as a table of contents, and platforms ignore chapter marks that short."""
    return _env_float("TICTOK_AI_CHAPTER_MIN_SECONDS", 60.0)


def get_ai_clip_title_chars() -> int:
    """Max characters in a generated short title. Override with
    TICTOK_AI_CLIP_TITLE_CHARS.

    Enforced twice: stated in the prompt and clamped after decoding. Local models
    routinely overshoot a stated limit, and the cached value has to be the one the screen
    shows — truncating at display time would leave the two disagreeing."""
    return _env_int("TICTOK_AI_CLIP_TITLE_CHARS", 30)


def get_ai_clip_description_chars() -> int:
    """Max characters in a generated short description. Override with
    TICTOK_AI_CLIP_DESCRIPTION_CHARS."""
    return _env_int("TICTOK_AI_CLIP_DESCRIPTION_CHARS", 120)


def get_ai_clip_hashtag_max() -> int:
    """Max hashtags generated per short. Override with TICTOK_AI_CLIP_HASHTAG_MAX."""
    return _env_int("TICTOK_AI_CLIP_HASHTAG_MAX", 5)


def get_ai_comment_sample_windows() -> int:
    """Number of equal-time windows the session is split into before sampling comments.
    The sample is drawn proportionally from every window, so the reported sentiment is an
    estimate of the whole stream rather than of its final minutes. 1 disables the
    stratification (a single window = the plain tail sample)."""
    return _env_int("TICTOK_AI_COMMENT_SAMPLE_WINDOWS", 12)


def get_ai_max_tokens() -> int:
    """Upper bound on the model's reply length. Local quantized models will happily run
    to their context limit on a long comment batch, and a reply cut off mid-object is
    unparseable JSON. 0 omits the field (server default).

    16384 rather than a few thousand because reasoning models spend this same budget on
    their thinking tokens before emitting any JSON: chapter generation measured a hard
    failure at 2048 and 4096, and only completed at 16384. The cut-off is not silent
    (_chat rejects finish_reason=length), so an over-generous ceiling costs nothing but
    a too-small one fails every call."""
    return _env_int("TICTOK_AI_MAX_TOKENS", 16384)


def get_ai_json_schema_enabled() -> bool:
    """Send the expected shape as an OpenAI-compatible ``response_format`` json_schema so
    the endpoint constrains decoding instead of the reply being scraped for braces.
    llama.cpp server and Ollama both support it; disable for an endpoint that rejects
    the field (it answers HTTP 400 rather than degrading, which is the intended
    behaviour — there is no silent fallback)."""
    return _env_bool("TICTOK_AI_JSON_SCHEMA", True)


def get_ai_review_min_observations() -> int:
    """Minimum n for a cross-session statistic to be offered to the review model as
    established rather than as provisional. Below this the figure is still passed, but
    flagged so the model is told not to draw a conclusion from it."""
    return _env_int("TICTOK_AI_REVIEW_MIN_OBSERVATIONS", 20)


# ---- Local speech-to-text (faster-whisper / CTranslate2, GPU-accelerated) ----
# Opt-in; the faster-whisper package is an optional dependency loaded lazily, so the
# base app runs without it. No fallback: if disabled or the package/model is missing
# the feature reports unavailable rather than returning a fake transcript.


def get_stt_enabled() -> bool:
    return _env_bool("TICTOK_STT_ENABLED", False)


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
    return _env_int("TICTOK_STT_BEAM_SIZE", 5)


def get_stt_condition_on_previous_text() -> bool:
    """Whisper feeds the previous segment's text back as the next segment's prompt.
    Whisper's default (True) self-reinforces repetition: once it emits a phrase in a
    low-confidence span (silence/BGM/cheering) it keeps repeating it across segments.
    Default False here to break that loop. Real repeated speech is unaffected."""
    return _env_bool("TICTOK_STT_CONDITION_ON_PREVIOUS_TEXT", False)


def get_stt_no_repeat_ngram_size() -> int:
    """Block re-emitting any n-gram of this length during decoding (0 = off). Caps
    in-segment and cross-segment repetition loops. 3 is a conservative default."""
    return _env_int("TICTOK_STT_NO_REPEAT_NGRAM_SIZE", 3)


def get_stt_feature_block_frames() -> int:
    """Number of STFT frames computed per block during feature extraction. faster-whisper's
    numpy feature extractor computes the STFT of the whole waveform in one complex128 array,
    so a multi-hour recording needs gigabytes of contiguous memory and raises MemoryError
    before decoding starts. We compute the identical log-mel in frame blocks of this size to
    bound the transient buffer; the numerics are unchanged (frames are independent). At the
    default, one block's complex64 STFT buffer is ~100MB (block x (n_fft/2+1) x 8 bytes)."""
    return _env_int("TICTOK_STT_FEATURE_BLOCK_FRAMES", 65536)


# ---- Local AI video upscaling (super-resolution via spandrel + torch, GPU) ----
# Opt-in; torch/spandrel are optional dependencies loaded lazily so the base app runs
# without them. The model is a deployment-provided weights file (any super-resolution
# architecture spandrel can load, e.g. Real-ESRGAN); nothing is baked into logic and
# there is no fallback: when disabled, unconfigured, or the model fails to load the
# feature reports unavailable instead of substituting a non-upscaled result.


def get_upscale_enabled() -> bool:
    return _env_bool("TICTOK_UPSCALE_ENABLED", False)


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


def get_bgm_remove_enabled() -> bool:
    """Enable BGM/effect removal (speech enhancement) as an output option."""
    return _env_bool("TICTOK_BGM_REMOVE_ENABLED", False)


def get_bgm_remove_python() -> str:
    """Interpreter of the venv that has torch + clearvoice, run as a child process.
    Empty by default; PROJECT_ROOT-relative paths are accepted. It must NOT be the
    server's own venv — clearvoice replaces torch with the CPU build, which would
    cost the upscale path its GPU (see tictok.record.bgm_child)."""
    return os.environ.get("TICTOK_BGM_REMOVE_PYTHON", "").strip()


def get_bgm_remove_model() -> str:
    """Speech-enhancement model name resolved by ClearerVoice-Studio. The default is
    the only 48kHz-native one, so the recording's own sample rate survives untouched."""
    return os.environ.get("TICTOK_BGM_REMOVE_MODEL", "MossFormer2_SE_48K").strip()


def get_bgm_remove_task() -> str:
    """ClearerVoice-Studio task the model belongs to."""
    return os.environ.get("TICTOK_BGM_REMOVE_TASK", "speech_enhancement").strip()


def get_bgm_remove_device() -> str:
    """Inference device: 'cuda', 'cpu', or 'auto' (cuda when available). CPU is
    rejected by the child rather than silently taking tens of times longer."""
    return os.environ.get("TICTOK_BGM_REMOVE_DEVICE", "auto").strip()


def get_upscale_tile() -> int:
    """Tile edge (source pixels) for tiled inference; caps VRAM usage on large
    frames. 0 runs the whole frame at once."""
    return _env_int("TICTOK_UPSCALE_TILE", 512)


def get_upscale_tile_overlap() -> int:
    """Overlap (source pixels) between neighbouring tiles, hiding seam artifacts at
    tile borders."""
    return _env_int("TICTOK_UPSCALE_TILE_OVERLAP", 16)


def get_upscale_max_height() -> int:
    """Cap on the output height. A model whose scale would exceed this (e.g. 4x on a
    1440px source) is downscaled to the cap after inference, keeping encode time and
    file size bounded."""
    return _env_int("TICTOK_UPSCALE_MAX_HEIGHT", 2160)


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
    return _env_bool("TICTOK_NORMALIZE_MIXED_RESOLUTION", True)


def get_normalize_codec() -> str:
    """Video codec family for the normalization re-encode: 'av1' (default), 'h264',
    'hevc', or 'auto'.

    H.264 was the default while this pass was assumed to be a compatibility fix whose
    output nobody would keep for long. Measured on real recordings it was neither: the
    normalized mp4 **is** the archived recording, and at the old h264/cq17 default it ran
    5-7.6 Mbps against a source that arrives at 0.86-1.2 Mbps — 6.2x the source across 16
    recordings (17.5GB of .ts -> 107.6GB of mp4). Most of that is spent re-encoding the
    source's own compression noise, and on content upscaled to the largest rendition seen
    (in one recording 45% of the frames were 432x864 blown up to 720x1280).

    AV1 is the default because the burn-in already outputs AV1 on this machine and those
    files play fine, so the compatibility argument the H.264 default rested on no longer
    holds here. Measured on a 10-minute slice carrying a real 640/720 switch: h264 cq17 =
    3.22 Mbps, av1 cq33 = 1.13 Mbps (1.32x the source, against 3.75x before), same
    passthrough timing, same encode speed. Same encoder resolution (GPU when available,
    else CPU) as the burn-in."""
    return os.environ.get("TICTOK_NORMALIZE_CODEC", "av1").strip()


def get_normalize_quality() -> int:
    """Encode quality on the H.264 CRF/CQ scale (lower = higher quality, larger file),
    auto-mapped per codec — 17 here becomes AV1 cq33 via the +16 offset in
    video_overlay._CODEC_QUALITY.

    Deliberately two steps above the burn-in's own quality (video_overlay_quality=19 ->
    AV1 cq35): this output is both the archived recording and the burn-in's input, so
    matching the burn-in here would stack two generations of loss at the same quality.
    Override with TICTOK_NORMALIZE_QUALITY."""
    return _env_int("TICTOK_NORMALIZE_QUALITY", 17)


def get_short_codec() -> str:
    """Video codec family for the short (vertical clip) output: 'h264' (default), 'av1',
    'hevc', or 'auto'.

    Unlike the normalization pass, this output **leaves the machine**. The archived
    recording only has to play back here, which is why that pass defaults to AV1 for its
    3x size win; a short is uploaded, and AV1-in-MP4 is still refused or silently
    re-encoded by parts of that path. H.264 High + AAC is the combination every consumer
    accepts, and at a 60-second clip the size argument that justified AV1 upstream is
    worth a few megabytes. Override with TICTOK_SHORT_CODEC."""
    return os.environ.get("TICTOK_SHORT_CODEC", "h264").strip()


def get_short_quality() -> int:
    """Encode quality for the short output on the H.264 CRF/CQ scale (lower = higher
    quality), auto-mapped per codec like every other encode here.

    One step above the normalization pass because a short is the last generation before
    upload and the platform re-encodes it again. Override with TICTOK_SHORT_QUALITY."""
    return _env_int("TICTOK_SHORT_QUALITY", 19)


def get_short_fps() -> float:
    """Frame rate the short output is folded to. Override with TICTOK_SHORT_FPS.

    Shorts must be CFR: the recordings are VFR HLS, and every operation here that renumbers
    frames (the silence tightening's ``setpts=N/FRAME_RATE/TB``) produces timestamps that
    disagree with the real frame spacing unless the input was folded first."""
    return _env_float("TICTOK_SHORT_FPS", 30.0)


def get_short_batch_limit() -> int:
    """How many shorts one auto-generation run produces from a single recording by
    default. Override with TICTOK_SHORT_BATCH_LIMIT.

    The bound exists because the ranking is only meaningful at the top: candidates are
    ordered by how far the moment sits from that stream's own baseline, and past the first
    handful the z-scores flatten into ordinary conversation."""
    return _env_int("TICTOK_SHORT_BATCH_LIMIT", 5)


def get_short_gate_tolerance_seconds() -> float:
    """How far the short's two tracks may disagree, and how far the output may fall short
    of what was asked for, before the gate refuses it. Override with
    TICTOK_SHORT_GATE_TOLERANCE_SECONDS.

    The failure this catches is measured, not hypothetical: ffmpeg returns rc=0 with one
    track ending at 30-40% of the other, and the container reports the longer one (see
    doc/OVERLAY_OUTPUT_INTEGRITY.md). Normal separation there was 0.05-0.06s against
    7,000s+ when broken, so a sub-second bound is nowhere near the noise."""
    return _env_float("TICTOK_SHORT_GATE_TOLERANCE_SECONDS", 0.5)


def get_short_gate_silent_ratio() -> float:
    """Fraction of a short that may be silence before the gate refuses it (default 0.9).
    Override with TICTOK_SHORT_GATE_SILENT_RATIO.

    Not 1.0: a clip whose audio is entirely missing and one that is 97% silence are the
    same defect from the viewer's side, and the second is the one that actually happens
    (the range landed on a lull rather than the moment)."""
    return _env_float("TICTOK_SHORT_GATE_SILENT_RATIO", 0.9)


def get_short_gate_black_ratio() -> float:
    """Fraction of a short that may be black frames before the gate refuses it
    (default 0.5). Override with TICTOK_SHORT_GATE_BLACK_RATIO.

    Lower than the silence bound because black video has no benign cause here — the
    source is a live camera feed, so sustained black means the stream dropped or the
    encode produced nothing."""
    return _env_float("TICTOK_SHORT_GATE_BLACK_RATIO", 0.5)


def get_overlay_encode_chunks() -> int:
    """焼き込み本encodeの時間分割並列数。既定1(分割なし)。

    実測(00302, AV1 NVENC): 2分割の並列sessionはNVENCの合計処理量を分け合うだけで
    wallは縮まない(各chunkがちょうど半速になった)。engine 2基の活用は分割ではなく
    単一sessionのsplit-frame encode(video_overlay._split_encode_args)が担い、そちらは
    1.81倍の実測。分割機構そのものは配信中の追いかけ焼き込みが将来使うために残している。
    TICTOK_OVERLAY_ENCODE_CHUNKSで上書き。"""
    return max(1, _env_int("TICTOK_OVERLAY_ENCODE_CHUNKS", 1))


def get_overlay_layer_save_workers() -> int:
    """comment層のdistinct frame書き出し(composite+PNG encode)のworker thread数。
    0(既定)はCPU数から自動(video_overlay._layer_save_workers)。PILのcompositeとzlibは
    GILを解放するので、threadで実並列になる。TICTOK_OVERLAY_LAYER_SAVE_WORKERSで上書き。"""
    return _env_int("TICTOK_OVERLAY_LAYER_SAVE_WORKERS", 0)


def get_overlay_layer_fps_cap() -> float:
    """コメントlayer(alpha中間file)のfps上限。実効fpsは min(映像fps, この値)。

    layerは「内容が変わるframeだけPILで描き、CFRへ引き伸ばしてqtrleへ流す」構造で、実測では
    24万frame中3923(1.6%)しか内容が変わらないのにファイル全体を支配していた(13.7GB)。容量は
    frame数にほぼ比例するので、ここを下げれば直接効く。ただし**下げるとコメントのscrollが
    粗くなる**(出力の見た目が変わる)ため、既定は据え置き、確認した上で下げるための入口として
    設定にしてある。TICTOK_OVERLAY_LAYER_FPS_CAPで上書き。"""
    return _env_float("TICTOK_OVERLAY_LAYER_FPS_CAP", 30.0)


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
    return _env_int("TICTOK_GPU_CONCURRENCY", 1)


def get_gpu_wait_timeout_seconds() -> float:
    """Give up after waiting this long for a GPU slot (0 = wait indefinitely, the
    default). A queue here is normal and long — a multi-hour Up出力 ahead of you is not
    an error — so the default never times out. Set a bound only when a stuck stage should
    surface as a failure rather than as an indefinite wait."""
    return _env_float("TICTOK_GPU_WAIT_TIMEOUT_SECONDS", 0.0)


# ---- Live update channel (websocket broadcast) ----


def get_websocket_send_timeout_seconds() -> float:
    """1接続へのbroadcast送信を諦めるまでの秒数(0で無制限に待つ)。

    broadcastは接続数ぶんの送信をまとめて行うが、TCPの送信bufferが埋まったclientへの
    送信は相手が読むまで返らない。上限が無いと、1枚の応答しないtabが**他の全clientと
    呼び出し元(収集中のcollector)**を道連れにする。超えた接続は応答しないものとして
    切り離す — browserは自分で張り直すので、失うのはその1接続の1 messageだけである。"""
    return _env_float("TICTOK_WEBSOCKET_SEND_TIMEOUT_SECONDS", 5.0)


# ---- Long-running job registry (server-side progress, reload-tolerant) ----


def get_job_retention_seconds() -> float:
    """How long a finished media job stays in the server's job registry. A page that
    reloads (or opens) within this window still sees the completion or the failure
    instead of an empty list, which would read as 'nothing ever ran'."""
    return _env_float("TICTOK_JOB_RETENTION_SECONDS", 300.0)


# ---- Media job queue (DB-backed, survives a restart) ----


def get_media_queue_poll_seconds() -> float:
    """How long the media job worker sleeps when the queue is empty. Enqueues wake it
    immediately; this only bounds how long a row written by another path (a migration,
    a manual DB edit) waits before it is noticed."""
    return _env_float("TICTOK_MEDIA_QUEUE_POLL_SECONDS", 5.0)


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
    return max(1, _env_int("TICTOK_MEDIA_QUEUE_WORKERS", 2))


def get_media_queue_instant_workers() -> int:
    """即時lane(``media_queue.INSTANT_KINDS``)専用のworker本数。0でlaneを持たない。

    通常のworkerは既定2本で、しかも同じ録画で走っているjobがある間は次を拾わない。人が
    その場で待つ数秒のjob(スクショ)をその列へ入れると、長い焼き込み・Up出力の裏で押した
    1枚が数時間保存されない。laneが拾うのは録画へ書き込まない種別だけなので、本体のjobと
    重なっても互いの足元を抜かない(``claim_next_pending_media_job`` 参照)。

    1本で足りるのは、この種別が1枚あたり数秒で終わるためである。"""
    return max(0, _env_int("TICTOK_MEDIA_QUEUE_INSTANT_WORKERS", 1))


def get_media_queue_sweep_concurrency() -> int:
    """起動時sweepが積んだjobを同時に何本走らせるか(0で無制限)。

    sweepは人が待っていない自動投入で、しかも起動のたびに数十本積まれる。workerの全枠
    (既定2)をsweepが埋めると、その直後に人が投げた焼き込みはsweepが1本終わるまで始まらない。
    既定の1は「sweepは常に1本ずつ、残りの枠は人の投入のために空けておく」という意味で、
    workerが1本しか無い構成でも待たされるのはsweep 1本ぶんに収まる。

    上限は本数であって順番ではない。順番は priority で下げてあるので、待機列に人の投入が
    あれば必ずそちらが先に始まる。"""
    return max(0, _env_int("TICTOK_MEDIA_QUEUE_SWEEP_CONCURRENCY", 1))


def get_job_progress_min_interval_seconds() -> float:
    """Minimum gap between two progress notifications that carry the same overall
    percent. The percent alone changes at most 100 times per job, but the stage detail
    (frame counters, encode position) changes continuously, and every notification is a
    DB write plus a websocket broadcast to every open page. This gate is what keeps a
    multi-hour job's detail text live without turning it into tens of thousands of
    writes. A change in percent is always sent immediately, regardless of this gap."""
    return _env_float("TICTOK_JOB_PROGRESS_MIN_INTERVAL_SECONDS", 2.0)


def get_media_job_group_emit_min_interval_seconds() -> float:
    """同じgroupの進捗まとめを続けて配るときの最小間隔。

    group行の進捗はDBからgroup全件を引き直して作る。一括投入はgroup 1つに数百本入るので、
    投入中も実行中も、1件動くたびに数百行のqueryがevent loop上で走る(N本の投入でN²)。
    ここで間引く対象はgroupのまとめ行だけで、個々のjob行は従来どおり即座に配る。

    間隔中に落ちた更新は捨てず、間隔明けの次の配信が最新のgroup状態を運ぶ。groupの
    終了(全件完了/失敗)は間隔に関わらず即座に配る — そこを遅らせると「終わったのに
    終わらない」表示になる。"""
    return _env_float("TICTOK_MEDIA_JOB_GROUP_EMIT_MIN_INTERVAL_SECONDS", 2.0)


def get_media_job_attempts() -> int:
    """Total runs of a media job before it is recorded as failed (1 = no retry).
    A burn-in dies on transient conditions that are gone seconds later — the output
    directory locked by an antivirus scan, an ffmpeg spawn refused while the disk is
    busy — and without a retry those land as a permanent failure that only a human
    re-queue undoes. The default keeps this to a single retry because the other class of
    failure (a genuine defect in the input) costs hours of GPU time per attempt."""
    return _env_int("TICTOK_MEDIA_JOB_ATTEMPTS", 2)


def get_media_job_retry_backoff_seconds() -> float:
    """Base wait before re-running a failed media job; the Nth retry waits base * N.
    Long enough for a file lock or a disk-busy spike to clear."""
    return _env_float("TICTOK_MEDIA_JOB_RETRY_BACKOFF_SECONDS", 10.0)


def get_media_job_defer_seconds() -> float:
    """Wait before a deferred media job becomes runnable again.

    A retry (get_media_job_attempts) answers a failure that is gone in seconds. It cannot
    answer a storage volume that went away: the final dir dropping off the bus takes it
    out for minutes, both attempts burn inside 10 seconds, and the job lands as failed
    with the recording left half-rebuilt. Deferring returns the job to the queue instead
    of consuming an attempt, so the run continues on its own once the volume is back."""
    return _env_float("TICTOK_MEDIA_JOB_DEFER_SECONDS", 60.0)


def get_media_job_defer_timeout_seconds() -> float:
    """How long a job may stay deferred before it is recorded as failed. Waiting without
    a bound would leave a queue that looks alive while nothing can ever run."""
    return _env_float("TICTOK_MEDIA_JOB_DEFER_TIMEOUT_SECONDS", 7200.0)


def get_media_job_auto_requeue_limit() -> int:
    """How many times a job interrupted by a server restart is put back on the queue by
    itself (0 disables). A bulk run spans hours, so a restart in the middle used to leave
    its remaining members as permanent holes that only a human noticed. The cap is what
    keeps a job that takes the process down with it from re-running on every boot."""
    return _env_int("TICTOK_MEDIA_JOB_AUTO_REQUEUE_LIMIT", 3)


def get_transcribe_job_attempts() -> int:
    """Total runs of a transcription job before it is recorded as failed (1 = no retry).
    Higher than the media default: STT reads the file and holds the GPU for minutes
    rather than hours, so a retry is cheap, and a CUDA allocation refused while another
    job releases VRAM is exactly the transient this covers."""
    return _env_int("TICTOK_TRANSCRIBE_JOB_ATTEMPTS", 3)


def get_transcribe_job_retry_backoff_seconds() -> float:
    """Base wait before re-running a failed transcription; the Nth retry waits base * N."""
    return _env_float("TICTOK_TRANSCRIBE_JOB_RETRY_BACKOFF_SECONDS", 10.0)


def get_media_job_history_days() -> float:
    """How long finished media job rows stay in the DB for the job centre's history
    (0 = never prune). These rows are small and are the only record of what was asked
    for, so the default keeps a fortnight rather than minutes."""
    return _env_float("TICTOK_MEDIA_JOB_HISTORY_DAYS", 14.0)


# ---- Spike detection (clip candidates, see core/spike.py) ----


def get_highlight_zscore() -> float:
    """Threshold (in standard deviations above the session's own mean) at which a window
    counts as a highlight on the streamer page. The clip-candidate screen passes its own
    設定値 explicitly; this is the default the highlight list uses, and the two share one
    detector so the same moment is named on both screens."""
    return _env_float("TICTOK_HIGHLIGHT_ZSCORE", 2.0)


# ---- Audio profile (silence / loudness, derived from the waveform decode) ----


def get_audio_profile_interval_seconds() -> float:
    """Resolution of the absolute-level series kept alongside the display waveform.
    The waveform decode already produces a 20ms peak series and throws it away; keeping
    it at this resolution costs a few kB per recording and means silence and loudness
    spikes are answerable without decoding the container again."""
    return _env_float("TICTOK_AUDIO_PROFILE_INTERVAL_SECONDS", 1.0)


def get_audio_silence_dbfs() -> float:
    """Level (dBFS, full scale = 0) below which an interval counts as silent. Measured
    against full scale rather than against the recording's own peak, because a stream
    that is quiet throughout must not have its noise floor promoted to 'audible'."""
    return _env_float("TICTOK_AUDIO_SILENCE_DBFS", -50.0)


def get_audio_silence_min_seconds() -> float:
    """Shortest run of silent intervals reported as a silent span. Below this the gap is
    a pause between words, not a place a clip can be cut."""
    return _env_float("TICTOK_AUDIO_SILENCE_MIN_SECONDS", 2.0)


# ---- Clip export ----


def get_clip_keyframe_scan_seconds() -> float:
    """How far back a cut may look for the keyframe that lets it start without losing the
    requested content.

    Handing the requested time straight to ``-ss`` makes video start at the keyframe
    *after* it on HLS input, dropping up to one GOP of the requested range (measured on a
    real recording: requested 301.402, video began 302.082, while keyframe 300.121
    existed). The cut therefore aims at the last keyframe at or before the request, and
    this is how far back it is allowed to look for it. Measured keyframe spacing on the
    current recordings is up to 6.08s, and 37.6s was recorded historically; 45s covers
    both. Too small a window is not a silent degradation - the cut fails and says so."""
    return _env_float("TICTOK_CLIP_KEYFRAME_SCAN_SECONDS", 45.0)


def get_clip_duration_tolerance_seconds() -> float:
    """How far a written clip may differ from the requested length before it is logged
    as a mismatch. Stream copy can only start on a keyframe, and keyframe spacing is set
    by the broadcaster, not by the 2s HLS segmenting: measured 2.1s-37.6s across real
    recordings. A copy clip therefore runs *long* by up to one GOP, which is normal and
    is not checked; only a clip shorter than requested trips this, which is what catches
    an audio filter silently changing the length."""
    return _env_float("TICTOK_CLIP_DURATION_TOLERANCE_SECONDS", 1.0)


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
    return _env_int("TICTOK_NOTIFY_QUEUE_MAX", 500)


def get_notify_shutdown_drain_seconds() -> float:
    """shutdown時に送信待ちを吐き切るのを待つ秒数。ここを無制限にすると宛先が落ちている
    ときにserverが終了できなくなる。"""
    return _env_float("TICTOK_NOTIFY_SHUTDOWN_DRAIN_SECONDS", 5.0)


# ---- 笑い声検出 (AudioSet audio tagging via onnxruntime, CPU) ----
# Opt-in。onnxruntime は optional dependency で lazy import する。weights は
# deployment が置く file を path で受け、model 名も class 名も logic に焼かない。
# Fallback は持たない: 無効・未導入・model/label 不備・推論失敗はいずれも
# LaughAudioError で返し、「笑いが無かった」ように見える結果を黙って返さない。
# 実行するdeviceは TICTOK_LAUGH_AUDIO_DEVICE で選ぶ(既定 cpu)。cuda は別processで
# 走らせる — 同居させない理由は laugh_worker.py の docstring を参照。


def get_laugh_audio_enabled() -> bool:
    return _env_bool("TICTOK_LAUGH_AUDIO_ENABLED", False)


def get_laugh_audio_model_path() -> str:
    """音声tagging modelのONNX file path(相対はproject root基準)。既定は空で、
    modelを焼き込まない。設定しない限りこの機能は使えない。"""
    return os.environ.get("TICTOK_LAUGH_AUDIO_MODEL_PATH", "").strip()


def get_laugh_audio_labels_path() -> str:
    """modelの出力indexとclass名の対応表(AudioSetの class_labels_indices.csv、または
    JSONのlist/dict)。model側の出力順は weights ごとに違うので、対応表も weights と
    対にして設定する。"""
    return os.environ.get("TICTOK_LAUGH_AUDIO_LABELS_PATH", "").strip()


def get_laugh_audio_classes() -> list:
    """笑いとみなすclass名。区切りは ``|``。AudioSetのclass名自体が
    "Chuckle, chortle" のようにカンマを含むため、カンマ区切りにすると壊れる。"""
    raw = os.environ.get(
        "TICTOK_LAUGH_AUDIO_CLASSES",
        "Laughter|Giggle|Snicker|Belly laugh|Chuckle, chortle",
    )
    return [name.strip() for name in raw.split("|") if name.strip()]


def get_laugh_audio_window_seconds() -> float:
    """1回の推論が見る音声の長さ。短すぎると笑いの立ち上がりだけを見て取りこぼし、
    長すぎると笑いの位置が窓の中で曖昧になる。"""
    return _env_float("TICTOK_LAUGH_AUDIO_WINDOW_SECONDS", 2.0)


def get_laugh_audio_hop_seconds() -> float:
    """窓を進める間隔。そのまま確率列の刻み(=時間分解能)になる。"""
    return _env_float("TICTOK_LAUGH_AUDIO_HOP_SECONDS", 1.0)


def get_laugh_audio_threshold() -> float:
    """笑い有りとみなす確率の下限。sidecarには閾値を掛ける**前**の生確率を保存するので、
    この値を変えても再解析は要らない(問い合わせ時にのみ適用される)。"""
    return _env_float("TICTOK_LAUGH_AUDIO_THRESHOLD", 0.35)


def get_laugh_audio_batch() -> int:
    """1回のsession.runへ渡す窓の数。modelがbatchを固定してexportされている場合は
    そちらが優先される。"""
    return _env_int("TICTOK_LAUGH_AUDIO_BATCH", 32)


def get_laugh_index_merge_gap_seconds() -> float:
    """検索indexへ入れるとき、笑いの刻みをひと続きとみなす隙間の上限(秒)。

    笑い声は一定ではなく、息継ぎで確率が1〜2刻みだけ閾値を割る。0にすると1回の笑いが
    数行に割れ、検索結果が同じ場面で埋まる。"""
    return _env_float("TICTOK_LAUGH_INDEX_MERGE_GAP_SECONDS", 2.0)


def get_laugh_index_min_seconds() -> float:
    """検索indexへ入れる窓の最短の長さ(秒)。これ未満の窓は行にしない。

    1刻みだけ閾値を超える点は録画1本で数百個出る。全部を検索結果へ出すと、本当に笑って
    いる場面がその中に埋もれる(切り出し候補側の下限と同じ理由)。"""
    return _env_float("TICTOK_LAUGH_INDEX_MIN_SECONDS", 2.0)


# 検索indexから外す共演の範囲。indexの中身を決める値なので、変えたら入れ直しが要る
# (笑い声分析の済み判定がこの値を見るので、一括処理が自動で対象へ戻す)。
LAUGH_INDEX_COOP_MODES = ("none", "collab", "coop")


def get_laugh_index_exclude_coop() -> str:
    """検索indexへ入れる笑い声から、共演中の窓を外すか。

    ``coop``(既定) = コラボ(非BattleのLinkMic)とBattleの両方を外す / ``collab`` =
    コラボだけ外す / ``none`` = 外さない。

    外すのは、共演中の音声には相手の声が混ざっており、**どの笑い声が配信者のものかを
    音から決める手段が無い**ため。一覧は「この配信者が笑った場面」として読まれるので、
    共演者の笑いが混ざると根拠が別人だったという壊れ方をする(smileのmodule docstringが
    映像側で同じ結論を書いている)。

    窓の出所はDB(collab_windows / battles)である。映像の顔の数
    (:func:`tictok.media.smile.multi_face_spans`)を使わないのは、こちらが音の話だから:
    カメラを外している間もゲーム画面を映している間も相手の声は乗り続けるので、画面に
    顔が2つ映っている区間だけでは足りない。"""
    raw = os.environ.get("TICTOK_LAUGH_INDEX_EXCLUDE_COOP")
    if raw is None:
        return "coop"
    value = raw.strip().lower()
    if value not in LAUGH_INDEX_COOP_MODES:
        _reject("TICTOK_LAUGH_INDEX_EXCLUDE_COOP", raw,
                "/".join(LAUGH_INDEX_COOP_MODES) + " のいずれか", "coop")
    return value


def get_laugh_audio_device() -> str:
    """推論を走らせるdevice: ``cpu``(既定) か ``cuda``。

    既定をcpuにしているのは、cudaがonnxruntime-gpuとCUDA runtimeの配置に依存し、
    どちらも欠けている環境が普通にあるため。ここでcudaを既定にすると、未導入の環境で
    「動いているのに遅い」でも「明示的に失敗」でもなく、**onnxruntimeが黙ってCPUへ
    落ちた状態**になる(実測: 要求したproviderが作れないとget_providersがCPUだけを
    返す)。laugh_audio側はその落下を検出して例外にするので、cudaと書いた環境では
    必ずcudaで走るか失敗するかのどちらかになる。

    実測(RTX 4070 Ti / ced-tiny 2秒窓): CPU 393 window/s に対し CUDA 12,733 window/s
    (32倍)。cudaのときは音声decodeの方が律速になる(実測 833倍速)。"""
    return os.environ.get("TICTOK_LAUGH_AUDIO_DEVICE", "cpu").strip().lower()


def get_laugh_audio_threads() -> int:
    """onnxruntimeのintra-op thread数。0はonnxruntimeの既定(論理coreの半分)に任せる。
    録画中に走らせると録画・文字起こしとCPUを奪い合うため、絞れるようにしておく。"""
    return _env_int("TICTOK_LAUGH_AUDIO_THREADS", 0)


def get_laugh_audio_activation() -> str:
    """modelの出力に掛ける活性化: ``sigmoid``(既定) か ``none``。AudioSetは多labelなので
    素のexportはlogitsを出し、確率にするにはsigmoidが要る。activationまで含めて
    exportされたmodelに二重掛けすると値が [0.5, 0.73] へ潰れるが、その差は結果を見ても
    気付けない — modelの契約なので推測せず設定で明示する。"""
    return os.environ.get("TICTOK_LAUGH_AUDIO_ACTIVATION", "sigmoid").strip().lower()


def get_laugh_comment_min_w_run() -> int:
    """笑いとみなす連続wの最小長。

    既定が1(単発wを含む)なのは実測による: 単発wのみで当たった3,468件のうち、ASCII英単語を
    含むもの88件を全数目視して誤検出0件だった(前後のlookaroundが new / wow / w/ を弾く)。
    2にすると笑いcommentの41%を捨てる。視聴者層が変われば見直す余地があるので設定にする。"""
    return _env_int("TICTOK_LAUGH_COMMENT_MIN_W_RUN", 1)


# ---- 笑顔検出 (顔検出 → 表情分類の2段、onnxruntime、CPU) ----
# Opt-in。onnxruntime は optional dependency で lazy import する。weights は deployment が
# 置く file を path で受け、model 名も class 名も logic に焼かない。既定は無効。
# Fallback は持たない: 無効・未導入・model不備・推論失敗はいずれも SmileError で返す。
# 実行は常に CPU(laugh_audio と同じ理由。GPU 12GB は文字起こしと超解像が奪い合っている)。
#
# 前処理の定数(mean/scale)と活性化は **model の契約** であって好みの値ではない。既定値は
# doc/SMILE_MODEL.md に書いた参照exportに合わせてあり、別のweightsを置くなら必ず上書きする
# — 推測で合わせると確率が静かに壊れ、出力を見ても気付けない。


def get_smile_enabled() -> bool:
    return _env_bool("TICTOK_SMILE_ENABLED", False)


def get_smile_sample_seconds() -> float:
    """frameを1枚見る間隔(秒)。そのまま判定列の刻み(=時間分解能)になる。

    全frameは見ない。3時間の録画は30fpsで32万frameあり、顔検出を全部に掛けるのは
    「後から一括で回す解析」の予算に収まらない。笑顔は数秒続く表情なので、2秒刻みで
    立ち上がりを取りこぼす確率は低い。"""
    return _env_float("TICTOK_SMILE_SAMPLE_SECONDS", 2.0)


def get_smile_work_width() -> int:
    """解析に使うframeの横幅(px)。原寸のままpipeで受けると3時間で15GBを運ぶことになり、
    逆に顔検出modelの入力寸(320x240等)まで落とすと表情分類へ渡す顔が潰れる。中間の枠を
    1つ置き、顔検出へはそこからletterboxして渡す。源より大きくは引き伸ばさない。"""
    return _env_int("TICTOK_SMILE_WORK_WIDTH", 480)


def get_smile_face_model_path() -> str:
    """顔検出modelのONNX file path(相対はproject root基準)。既定は空でmodelを焼き込まない。"""
    return os.environ.get("TICTOK_SMILE_FACE_MODEL_PATH", "").strip()


def get_smile_face_score_activation() -> str:
    """顔検出modelのscore出力に掛ける活性化: ``none``(既定) か ``softmax``。

    参照exportはgraph内でsoftmaxまで済ませて確率を出すので既定は ``none``。素のlogitsを
    出すexportに ``none`` を掛けると閾値の意味が変わる(logitsは0.7を軽く超える)ので、
    その場合は ``softmax`` を指定する。二重掛けも同じだけ壊れるため推測しない。"""
    return os.environ.get("TICTOK_SMILE_FACE_SCORE_ACTIVATION", "none").strip().lower()


def get_smile_face_score_index() -> int:
    """顔検出modelのscore 2列のうち「顔」の列。参照exportは[背景, 顔]で index 1。

    ここを外すと背景の確率を顔の確率として読み、検出が全反転する。反転した結果は
    「顔がほとんど無い録画」に見えるだけなので出力からは気付けない。設定で明示する。"""
    return _env_int("TICTOK_SMILE_FACE_SCORE_INDEX", 1)


def get_smile_face_mean() -> float:
    """顔検出modelの入力から引く値。参照exportは ``(pixel - 127) / 128``。"""
    return _env_float("TICTOK_SMILE_FACE_MEAN", 127.0)


def get_smile_face_scale() -> float:
    """顔検出modelの入力を割る値。参照exportは ``(pixel - 127) / 128``。"""
    return _env_float("TICTOK_SMILE_FACE_SCALE", 128.0)


def get_smile_face_threshold() -> float:
    """顔とみなすscoreの下限。低くすると背景の模様まで顔になり、「顔が複数」として
    判定を捨てる標本が増える(=coverageが下がる)。参照実装の既定と同じ0.7から始める。"""
    return _env_float("TICTOK_SMILE_FACE_THRESHOLD", 0.7)


def get_smile_face_nms_iou() -> float:
    """顔検出の重複除去(NMS)のIoU閾値。同じ顔に複数の枠が残ると「顔が複数」と数えられ、
    その標本が判定不能になる。参照実装の既定と同じ0.3。"""
    return _env_float("TICTOK_SMILE_FACE_NMS_IOU", 0.3)


def get_smile_face_min_height_ratio() -> float:
    """顔とみなす枠の高さの下限(frame高に対する比)。配信画面に映り込んだ写真・背景の
    ポスター・小さなアイコンを顔として数えると、配信者が1人で映っている標本まで
    「顔が複数」として捨てることになる。表情が読める大きさより下は最初から数えない。"""
    return _env_float("TICTOK_SMILE_FACE_MIN_HEIGHT_RATIO", 0.06)


def get_smile_model_path() -> str:
    """表情分類modelのONNX file path(相対はproject root基準)。既定は空。"""
    return os.environ.get("TICTOK_SMILE_MODEL_PATH", "").strip()


def get_smile_labels() -> list:
    """表情分類modelの出力index順のclass名。区切りは ``|``(class名がカンマを含み得る)。

    出力順はweightsごとに違うので、weightsと対にして設定する。既定は
    doc/SMILE_MODEL.md の参照exportの順。"""
    raw = os.environ.get(
        "TICTOK_SMILE_LABELS",
        "neutral|happiness|surprise|sadness|anger|disgust|fear|contempt",
    )
    return [name.strip() for name in raw.split("|") if name.strip()]


def get_smile_positive_classes() -> list:
    """笑顔・喜びとみなすclass名。区切りは ``|``。

    既定を happiness だけにしてあるのは surprise が「驚き顔」であって喜びとは限らないため。
    見どころ判定で驚きも拾いたいなら足せるが、そのときは fold の意味も確認すること。"""
    raw = os.environ.get("TICTOK_SMILE_POSITIVE_CLASSES", "happiness")
    return [name.strip() for name in raw.split("|") if name.strip()]


def get_smile_activation() -> str:
    """表情分類modelの出力に掛ける活性化: ``softmax``(既定)、``sigmoid``、``none``。

    FER系の表情分類は排他多classなので素のexportはlogitsを出し、確率にするにはsoftmaxが
    要る。activation込みでexportされたmodelに二重掛けすると値が潰れるが、その差は出力を
    見ても気付けない — modelの契約なので推測せず設定で明示する。"""
    return os.environ.get("TICTOK_SMILE_ACTIVATION", "softmax").strip().lower()


def get_smile_fold() -> str:
    """positive classが複数のときの畳み方: ``sum``(既定) か ``max``。

    softmax(排他多class)では各classの確率は排他なので、「どれかのpositive classである
    確率」は和が正しい(1.0でclampする)。sigmoid(多label)のexportでは和は1を超えるうえ
    「似た表情が2つある」ことを「もっと笑っている」と読み替えるので ``max`` にする。"""
    return os.environ.get("TICTOK_SMILE_FOLD", "sum").strip().lower()


def get_smile_mean() -> float:
    """表情分類modelの入力から引く値。参照exportは0〜255のまま渡す(mean=0, scale=1)。"""
    return _env_float("TICTOK_SMILE_MEAN", 0.0)


def get_smile_scale() -> float:
    """表情分類modelの入力を割る値。参照exportは0〜255のまま渡す(mean=0, scale=1)。"""
    return _env_float("TICTOK_SMILE_SCALE", 1.0)


def get_smile_crop_margin() -> float:
    """顔の枠を表情分類へ渡す前に広げる比率。検出枠は目〜口に寄っており、そのまま切ると
    表情分類の学習画像(額と顎を含む)と画角が合わない。"""
    return _env_float("TICTOK_SMILE_CROP_MARGIN", 0.15)


def get_smile_threshold() -> float:
    """笑顔ありとみなす確率の下限。sidecarには閾値を掛ける**前**の生確率を保存するので、
    この値を変えても再解析は要らない(問い合わせ時にのみ適用される)。"""
    return _env_float("TICTOK_SMILE_THRESHOLD", 0.5)


def get_smile_bucket_seconds() -> float:
    """``smile.aggregate`` が既定で使うbucket幅(秒)。sessionのbucket幅を持っている
    呼び出し側はそちらを渡すこと(この値はbucketを持たない解析の既定)。"""
    return _env_float("TICTOK_SMILE_BUCKET_SECONDS", 60.0)


def get_smile_threads() -> int:
    """onnxruntimeのintra-op thread数。0はonnxruntimeの既定に任せる。録画中に走らせると
    録画・文字起こしとCPUを奪い合うため、絞れるようにしておく。"""
    return _env_int("TICTOK_SMILE_THREADS", 0)
