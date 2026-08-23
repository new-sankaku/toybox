import sqlite3
import time

import pytest

from tictok.core import layout
from tictok.paths import PROJECT_ROOT

# 本番資産を指し得るenv。testでは常にtmpへ差し替える(値の中身は見ない)。
_REDIRECTED_ENV = (
    "TICTOK_DB_PATH",
    "TICTOK_RECORD_DIR",
    "TICTOK_LOG_DIR",
    "TICTOK_JOURNAL_DIR",
    "TICTOK_SAMPLE_DIR",
)

_PRODUCTION_PATHS = (
    PROJECT_ROOT / "tictok.db",
    PROJECT_ROOT / "semantic_index.db",
    PROJECT_ROOT / "semantic_vectors.bin",
    PROJECT_ROOT / "recordings",
    PROJECT_ROOT / "logs",
    PROJECT_ROOT / "journal",
    PROJECT_ROOT / "models",
    PROJECT_ROOT / "samples",
    # fonts.FONT_DIR の実体。env で切り替えられないので font_guard で別途逃がす。
    PROJECT_ROOT / "assets",
)


def pytest_unconfigure(config):
    """終了時のlog flushがpytestの閉じたcapture streamへ書くのを止める。

    tictok.storage は「同一logの繰り返しをまとめ、終了時に件数を出す」抑制機構を持つ。
    これがatexitで走るとpytestは既にstderrを閉じており、summary行が数百行の
    'Logging error' に埋もれる(結果自体は正しい)。handlerを外して黙らせる。
    """
    import logging

    logging.raiseExceptions = False
    names = ["", *logging.root.manager.loggerDict.keys()]
    for name in names:
        logger = logging.getLogger(name)
        for handler in list(getattr(logger, "handlers", [])):
            logger.removeHandler(handler)
    logging.disable(logging.CRITICAL)


def _is_under_production(path) -> bool:
    from pathlib import Path

    p = Path(path).resolve()
    for prod in _PRODUCTION_PATHS:
        try:
            if p == prod or prod in p.parents:
                return True
        except OSError:
            continue
    return False


@pytest.fixture(autouse=True)
def env_guard(tmp_path, monkeypatch):
    """TICTOK_* のpath系envをtmpへ隔離する。

    tictok.core.config は import 時に PROJECT_ROOT/.env を os.environ へ流し込むため、
    testが何もしないと本番のDB/logs/journalを掴む。値の中身に関係なく必ず上書きする。
    """
    # tictok.core.config が読み込んだ PROJECT_ROOT/.env の値が os.environ に残っており、
    # 閾値・STT・log系のenvがtestの期待へ黙って影響する。既定値経路をtestできるよう、
    # sandboxを張る前にTICTOK_*を一掃する(必要なものは以下で明示的に入れ直す)。
    import os

    for name in [k for k in os.environ if k.startswith("TICTOK_")]:
        monkeypatch.delenv(name, raising=False)

    sandbox = tmp_path / "sandbox"
    dirs = {
        "TICTOK_RECORD_DIR": sandbox / "recordings",
        "TICTOK_LOG_DIR": sandbox / "logs",
        "TICTOK_JOURNAL_DIR": sandbox / "journal",
        "TICTOK_SAMPLE_DIR": sandbox / "samples",
        # 退避先もsandboxへ。既定はDBの隣(config.get_db_backup_dir)なので、TICTOK_DB_PATHを
        # sandboxへ向けている以上ここは既に安全だが、明示しておく — 既定の導き方が将来また
        # project root固定へ戻っても、本番の backups/ を汚さない。かつて固定だったとき、
        # 1.85GBのmigration前退避がtest 1回の実行で消えた(doc/DB_MAINTENANCE.md)。
        "TICTOK_DB_BACKUP_DIR": sandbox / "backups",
    }
    for name, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(path))
    monkeypatch.setenv("TICTOK_DB_PATH", str(sandbox / "tictok.db"))
    # 実配信への接続・監視復元・外部keyの誤使用を止める。
    monkeypatch.setenv("TICTOK_NO_RESTORE", "1")
    monkeypatch.setenv("TICTOK_SIMULATION", "0")
    monkeypatch.setenv("TICTOK_EULER_API_KEY", "")
    monkeypatch.setenv("TICTOK_AI_ENABLED", "0")

    for name in _REDIRECTED_ENV:
        import os

        assert not _is_under_production(os.environ[name]), f"{name} still points at production"

    # layoutのroot cacheはprocess全体で1つ。envをtmpへ張り替えてもcacheは前のtestの
    # tmp dirを指したまま残るため、次のtestが**前のtestのsandbox**の中に素材を見つける
    # (実際にそれで1件が誤って通った)。前後どちらでも落として、探索を必ずこのtestの
    # sandboxだけに閉じる。
    from tictok.core import layout as _layout

    _layout.reset_pool_root()
    _layout.reset_record_roots()
    yield sandbox
    _layout.reset_pool_root()
    _layout.reset_record_roots()


@pytest.fixture(autouse=True)
def font_guard(env_guard, monkeypatch):
    """fonts.FONT_DIR を tmp へ逃がす。

    FONT_DIR は PROJECT_ROOT/'assets'/'fonts' 固定でenvから動かせないため、
    ensure_fonts()/_fetch() を通るtestは放置すると本番assetsへ書き込む。
    _ensured latch も戻さないとtest間で取得済み扱いが漏れる。
    """
    from tictok.record import fonts

    font_dir = env_guard / "fonts"
    font_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fonts, "FONT_DIR", font_dir)
    monkeypatch.setattr(fonts, "_ensured", False, raising=False)
    return font_dir


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """testがnetworkへ出たら待たずに即失敗させる。

    font/avatar/gift iconの取得経路は本物のURLを持っているため、monkeypatch漏れが
    あると「遅いtest」ではなく「実際にdownloadするtest」になる。socket層で止める。
    """
    import socket

    real_socket = socket.socket.connect

    def _blocked(self, address, *args, **kwargs):
        # AF_UNIX / loopback は localhost の TestClient などが使うので通す。
        host = address[0] if isinstance(address, tuple) else None
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_socket(self, address, *args, **kwargs)
        raise RuntimeError(f"test attempted a network connection to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


@pytest.fixture
def tmp_db_path(env_guard):
    return env_guard / "tictok.db"


@pytest.fixture
def tmp_db(tmp_db_path):
    """本物のschema(SCHEMA + _migrate)を張った Storage。

    tictok.storage.Storage は writer thread を起こすので必ず close する。
    add_event/add_viewer_sample は buffer 経由なので、SQLを直接読む前に flush() が要る。
    """
    from tictok.storage import Storage

    storage = Storage(str(tmp_db_path))
    try:
        yield storage
    finally:
        storage.close()


@pytest.fixture
def db_read(tmp_db, tmp_db_path):
    """tmp_db と同じfileを読む独立connection。呼ぶ前に tmp_db.flush() する。"""
    conn = sqlite3.connect(str(tmp_db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def tmp_root(env_guard):
    """recordings layout を模した root。<root>/<streamer>/{ts,mp4}/ を作る。"""
    return env_guard / "recordings"


@pytest.fixture
def make_recording(tmp_root):
    """layout規約どおりの録画成果物を tmp_root に作り、(stem, mp4_path) を返す。"""
    counter = {"n": 0}

    def _make(streamer="tester", when="20260101_120000", segments=2, mp4_bytes=b"\x00" * 16):
        counter["n"] += 1
        stem = f"{counter['n']:05d}_{streamer}_{when}"
        session = layout.session_dir(tmp_root, stem, streamer)
        session.mkdir(parents=True, exist_ok=True)
        for i in range(segments):
            (session / f"seg{i:05d}.ts").write_bytes(b"\x47" * 188)
        mp4 = layout.mp4_path(tmp_root, stem, streamer)
        mp4.parent.mkdir(parents=True, exist_ok=True)
        mp4.write_bytes(mp4_bytes)
        return stem, mp4

    return _make


@pytest.fixture
def make_session(tmp_db):
    def _make(unique_id="tester", bucket_seconds=60, status=None):
        session_id = tmp_db.create_session(unique_id, bucket_seconds)
        if status:
            tmp_db.update_session(session_id, status)
        return session_id

    return _make


@pytest.fixture
def event_builder():
    """storage.add_event が受ける entry dict を組む。DBには入れない。"""
    clock = {"t": 1000.0}

    def _user(user_id="u1", unique_id="viewer1", nickname="Viewer One", **extra):
        user = {
            "user_id": user_id,
            "unique_id": unique_id,
            "nickname": nickname,
            "avatar": "",
            "fans_level": 0,
            "gifter_level": 0,
            "gifter_badge": "",
            "member_badge": "",
        }
        user.update(extra)
        return user

    def _make(kind="comment", at=None, user=None, **fields):
        if at is None:
            clock["t"] += 1.0
            at = clock["t"]
        entry = {"time": at, "kind": kind, "user": user if user is not None else _user()}
        entry.update(fields)
        return entry

    _make.user = _user
    return _make


@pytest.fixture
def gift_builder(event_builder):
    def _make(gift_name="Rose", diamonds=1, repeat_count=1, at=None, user=None, **fields):
        return event_builder(
            "gift", at=at, user=user, gift_name=gift_name, diamonds=diamonds,
            repeat_count=repeat_count, gift_id=5655, **fields,
        )

    return _make


@pytest.fixture
def frozen_now():
    return time.time()
