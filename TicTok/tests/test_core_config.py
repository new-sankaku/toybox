import os
import sqlite3
from itertools import groupby

import pytest

from tictok.core import config, layout, settings as settings_mod
from tictok.core.settings import CATEGORY_LABELS, SETTING_DEFS, Settings
from tictok.paths import PROJECT_ROOT


# ---------------- config: .env parsing ----------------


def test_parse_env_text_skips_blank_comment_and_keyless_lines():
    parsed = config._parse_env_text(
        "\n"
        "# a comment\n"
        "   \n"
        "NOEQUALS\n"
        "  KEY  =  value  \n"
    )
    assert parsed == {"KEY": "value"}


def test_parse_env_text_keeps_equals_inside_value():
    assert config._parse_env_text("URL=http://h/?a=1&b=2") == {"URL": "http://h/?a=1&b=2"}


def test_parse_env_text_strips_surrounding_quotes():
    parsed = config._parse_env_text('A="quoted"\nB=\'quoted\'\nC=plain')
    assert parsed == {"A": "quoted", "B": "quoted", "C": "plain"}


def test_parse_env_text_keeps_inline_hash_as_part_of_value():
    # コメント除去は行頭のみ。'#' を含む鍵をコメントとして削らないこと。
    assert config._parse_env_text("KEY=abc#def") == {"KEY": "abc#def"}


def test_parse_env_text_empty_value_and_empty_key():
    assert config._parse_env_text("KEY=\n=orphan\n") == {"KEY": ""}


def test_parse_env_text_last_duplicate_wins():
    assert config._parse_env_text("K=1\nK=2") == {"K": "2"}


def test_load_dotenv_applies_missing_keys_and_yields_to_existing_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("NEW_KEY=from_file\nEXISTING_KEY=from_file\n", encoding="utf-8")
    monkeypatch.setattr(os, "environ", {"EXISTING_KEY": "from_os"})
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        config, "_DOTENV_STATE",
        {"present": False, "parsed": 0, "applied": 0, "overridden_by_env": 0},
    )

    config._load_dotenv()

    assert os.environ["NEW_KEY"] == "from_file"
    assert os.environ["EXISTING_KEY"] == "from_os"
    assert config.dotenv_summary() == {
        "present": True, "parsed": 2, "applied": 1, "overridden_by_env": 1,
    }


def test_load_dotenv_absent_file_reports_not_present(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {})
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        config, "_DOTENV_STATE",
        {"present": False, "parsed": 0, "applied": 0, "overridden_by_env": 0},
    )

    config._load_dotenv()

    assert config.dotenv_summary()["present"] is False
    assert config.dotenv_summary()["parsed"] == 0


def test_dotenv_summary_returns_a_copy():
    summary = config.dotenv_summary()
    summary["parsed"] = 999999
    assert config.dotenv_summary()["parsed"] != 999999


# ---------------- config: getters ----------------


@pytest.mark.parametrize(
    "raw, expected",
    [("1", True), ("true", True), ("TRUE", True), ("Yes", True), ("on", True), ("  1  ", True),
     ("0", False), ("no", False), ("off", False), ("False", False)],
)
def test_bool_getters_accept_the_documented_token_sets(monkeypatch, raw, expected):
    monkeypatch.setenv("TICTOK_SIMULATION", raw)
    assert config.get_simulation() is expected


@pytest.mark.parametrize("raw", ["2", "", "   ", "ture", "no!"])
def test_bool_getter_rejects_unknown_token_instead_of_reading_it_as_false(monkeypatch, raw):
    """真token以外を黙って偽と読むと、``ture`` の1文字違いが機能を丸ごと無効にしながら
    何も言わない。真偽値も数値と同じく、解釈できない値は例外にする。"""
    monkeypatch.setenv("TICTOK_SIMULATION", raw)
    with pytest.raises(config.ConfigError):
        config.get_simulation()


def test_bool_getter_defaults(monkeypatch):
    for name in ("TICTOK_SIMULATION", "TICTOK_NO_RESTORE", "TICTOK_AI_ENABLED",
                 "TICTOK_STT_ENABLED", "TICTOK_UPSCALE_ENABLED", "TICTOK_JOURNAL_ENABLED",
                 "TICTOK_NORMALIZE_MIXED_RESOLUTION"):
        monkeypatch.delenv(name, raising=False)
    assert config.get_simulation() is False
    assert config.get_no_restore() is False
    assert config.get_ai_enabled() is False
    assert config.get_stt_enabled() is False
    assert config.get_upscale_enabled() is False
    # 既定でONのもの(取りこぼし防止側)は逆
    assert config.get_journal_enabled() is True
    assert config.get_normalize_mixed_resolution() is True


def test_numeric_getters_use_documented_defaults(monkeypatch):
    for name in ("TICTOK_PORT", "TICTOK_TIMELINE_LIMIT", "TICTOK_GPU_CONCURRENCY",
                 "TICTOK_MEDIA_JOB_ATTEMPTS", "TICTOK_HIGHLIGHT_ZSCORE",
                 "TICTOK_AUDIO_SILENCE_DBFS"):
        monkeypatch.delenv(name, raising=False)
    assert config.get_port() == 8520
    assert config.get_timeline_limit() == 2160
    assert config.get_gpu_concurrency() == 1
    assert config.get_media_job_attempts() == 2
    assert config.get_highlight_zscore() == 2.0
    assert config.get_audio_silence_dbfs() == -50.0


def test_numeric_getter_env_override_is_typed(monkeypatch):
    monkeypatch.setenv("TICTOK_PORT", "9001")
    monkeypatch.setenv("TICTOK_AUDIO_SILENCE_DBFS", "-42.5")
    assert config.get_port() == 9001
    assert isinstance(config.get_port(), int)
    assert config.get_audio_silence_dbfs() == -42.5


def test_numeric_getter_rejects_garbage_instead_of_falling_back(monkeypatch):
    # No fallback: 不正なenvは既定値へ黙って戻らず例外にする。
    monkeypatch.setenv("TICTOK_PORT", "not-a-port")
    with pytest.raises(ValueError):
        config.get_port()


# ---------------- config: env varの型検証 ----------------


def test_config_error_is_a_value_error():
    """helper化前は int()/float() の素のValueErrorが出ていた。既にValueErrorを
    捕まえている呼び出し側の挙動を変えないこと。"""
    assert issubclass(config.ConfigError, ValueError)


@pytest.mark.parametrize("raw", ["not-a-port", "", "   ", "80.5", "8_000円"])
def test_int_getter_rejects_unparsable_values(monkeypatch, raw):
    monkeypatch.setenv("TICTOK_PORT", raw)
    with pytest.raises(config.ConfigError):
        config.get_port()


@pytest.mark.parametrize("raw", ["abc", "", "1,5"])
def test_float_getter_rejects_unparsable_values(monkeypatch, raw):
    monkeypatch.setenv("TICTOK_HIGHLIGHT_ZSCORE", raw)
    with pytest.raises(config.ConfigError):
        config.get_highlight_zscore()


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf"])
def test_float_getter_rejects_non_finite_values(monkeypatch, raw):
    """nan/infはfloat()を通ってしまう。閾値にすると比較が常に偽になり、
    「閾値が効いていない」ことは出力を見ても分からない。"""
    monkeypatch.setenv("TICTOK_SMILE_THRESHOLD", raw)
    with pytest.raises(config.ConfigError):
        config.get_smile_threshold()


def test_numeric_getters_tolerate_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv("TICTOK_PORT", "  9001 ")
    monkeypatch.setenv("TICTOK_HIGHLIGHT_ZSCORE", " 2.5 ")
    assert config.get_port() == 9001
    assert config.get_highlight_zscore() == 2.5


def test_invalid_env_names_the_key_the_value_and_the_default(monkeypatch, caplog):
    """例外はjobの深い場所で握り潰されうるので、原因は必ずlogにも残す。"""
    monkeypatch.setenv("TICTOK_PORT", "not-a-port")
    with caplog.at_level("ERROR", logger="tictok.config"):
        with pytest.raises(config.ConfigError):
            config.get_port()

    record = caplog.records[-1]
    assert record.event == "process.config_env_invalid"
    assert record.ctx == {
        "key": "TICTOK_PORT", "raw": "not-a-port", "expected": "整数", "default": 8520,
    }
    assert "TICTOK_PORT" in record.getMessage() and "not-a-port" in record.getMessage()


def test_int_and_float_getters_return_their_declared_types(monkeypatch):
    monkeypatch.setenv("TICTOK_LOG_SHUTDOWN_DRAIN_SECONDS", "10")
    monkeypatch.delenv("TICTOK_MEDIA_JOB_HISTORY_DAYS", raising=False)
    assert isinstance(config.get_log_shutdown_drain_seconds(), float)
    # 既定値も実型で持つ("14"のような文字列既定はもう無い)
    assert isinstance(config.get_media_job_history_days(), float)
    assert isinstance(config.get_media_queue_workers(), int)


def test_clamped_getters_keep_their_floor(monkeypatch):
    monkeypatch.setenv("TICTOK_MEDIA_QUEUE_WORKERS", "0")
    monkeypatch.setenv("TICTOK_MEDIA_QUEUE_SWEEP_CONCURRENCY", "-3")
    assert config.get_media_queue_workers() == 1
    assert config.get_media_queue_sweep_concurrency() == 0


# ---------------- config.validate_env ----------------


def test_validate_env_passes_on_a_clean_environment():
    assert config.validate_env() == []


def test_validate_env_reports_every_bad_key_at_once(monkeypatch, caplog):
    """1件直しては再起動、を繰り返させない。最初の1件で止めず全getterを回すこと。"""
    monkeypatch.setenv("TICTOK_PORT", "not-a-port")
    monkeypatch.setenv("TICTOK_AI_ENABLED", "ture")
    monkeypatch.setenv("TICTOK_SMILE_THRESHOLD", "high")

    with caplog.at_level("ERROR", logger="tictok.config"):
        with pytest.raises(config.ConfigError) as raised:
            config.validate_env()

    for key in ("TICTOK_PORT", "TICTOK_AI_ENABLED", "TICTOK_SMILE_THRESHOLD"):
        assert key in str(raised.value)

    summary = [r for r in caplog.records
               if getattr(r, "event", "") == "process.config_env_invalid_summary"]
    assert len(summary) == 1
    assert summary[0].ctx["count"] == 3


def test_validate_env_skips_getters_that_need_an_argument(monkeypatch):
    """record_dir_from_db 等はDB pathを要求するので環境変数だけでは解決できない。
    引数付きgetterを呼びに行かないこと(呼ぶとTypeErrorで検証自体が落ちる)。"""
    calls = []
    monkeypatch.setattr(
        config, "get_media_queue_workers", lambda: calls.append("no-arg") or 1
    )
    monkeypatch.setattr(
        config, "get_broken_for_test", lambda required: calls.append("with-arg"), raising=False
    )

    assert config.validate_env() == []
    assert calls == ["no-arg"]


def test_ai_base_url_default_and_trailing_slashes_removed(monkeypatch):
    monkeypatch.delenv("TICTOK_AI_BASE_URL", raising=False)
    assert config.get_ai_base_url() == "http://127.0.0.1:11434/v1"
    monkeypatch.setenv("TICTOK_AI_BASE_URL", "http://host:8080/v1///")
    assert config.get_ai_base_url() == "http://host:8080/v1"


def test_secret_and_model_getters_are_stripped(monkeypatch):
    monkeypatch.setenv("TICTOK_EULER_API_KEY", "  key-123  ")
    monkeypatch.setenv("TICTOK_AI_MODEL", "  qwen2.5:14b  ")
    assert config.get_sign_api_key() == "key-123"
    assert config.get_ai_model() == "qwen2.5:14b"


def test_ai_model_and_upscale_model_default_to_empty(monkeypatch):
    monkeypatch.delenv("TICTOK_AI_MODEL", raising=False)
    monkeypatch.delenv("TICTOK_UPSCALE_MODEL_PATH", raising=False)
    assert config.get_ai_model() == ""
    assert config.get_upscale_model_path() == ""


def test_path_getters_fall_back_to_project_root(monkeypatch):
    for name in ("TICTOK_DB_PATH", "TICTOK_RECORD_DIR", "TICTOK_LOG_DIR",
                 "TICTOK_JOURNAL_DIR", "TICTOK_SAMPLE_DIR"):
        monkeypatch.delenv(name, raising=False)
    assert config.get_db_path() == str(PROJECT_ROOT / "tictok.db")
    assert config.get_record_dir() == str(PROJECT_ROOT / "recordings")
    assert config.get_log_dir() == str(PROJECT_ROOT / "logs")
    assert config.get_journal_dir() == str(PROJECT_ROOT / "journal")
    assert config.get_sample_dir() == str(PROJECT_ROOT / "samples")


def test_disk_low_bytes_default_is_five_gib(monkeypatch):
    monkeypatch.delenv("TICTOK_LOG_DISK_LOW_BYTES", raising=False)
    assert config.get_log_disk_low_bytes() == 5 * 1024 * 1024 * 1024


# ---------------- config.record_dir_from_db ----------------


def _settings_db(path, value=None):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    if value is not None:
        conn.execute("INSERT INTO settings VALUES ('record_dir', ?)", (value,))
    conn.commit()
    conn.close()


def test_record_dir_from_db_prefers_stored_value(tmp_path, monkeypatch):
    monkeypatch.setenv("TICTOK_RECORD_DIR", str(tmp_path / "from_env"))
    db = tmp_path / "s.db"
    _settings_db(db, "  D:\\rec_ssd  ")
    assert config.record_dir_from_db(str(db)) == "D:\\rec_ssd"


@pytest.mark.parametrize("stored", [None, "", "   "])
def test_record_dir_from_db_falls_back_to_env_when_unset(tmp_path, monkeypatch, stored):
    monkeypatch.setenv("TICTOK_RECORD_DIR", str(tmp_path / "from_env"))
    db = tmp_path / f"s_{stored!r}.db"
    _settings_db(db, stored)
    assert config.record_dir_from_db(str(db)) == str(tmp_path / "from_env")


def test_record_dir_from_db_tolerates_missing_db_and_missing_table(tmp_path, monkeypatch):
    monkeypatch.setenv("TICTOK_RECORD_DIR", str(tmp_path / "from_env"))
    empty = tmp_path / "no_table.db"
    sqlite3.connect(str(empty)).close()
    assert config.record_dir_from_db(str(empty)) == str(tmp_path / "from_env")
    assert config.record_dir_from_db(str(tmp_path / "nope.db")) == str(tmp_path / "from_env")

    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"this is not a database" * 100)
    assert config.record_dir_from_db(str(garbage)) == str(tmp_path / "from_env")


# ---------------- layout: stem parsing ----------------


@pytest.mark.parametrize(
    "stem, expected",
    [
        ("00042_user_20250101_120000", "user"),
        ("00042_a_b.c_20250101_120000", "a_b.c"),
        ("user_20250101_120000", "user"),
        ("12345_20250101_120000", "12345"),
        ("00042_user_2025010_120000", None),
        ("00042_user_20250101_12000", None),
        ("plainname", None),
        ("", None),
    ],
)
def test_streamer_of(stem, expected):
    assert layout.streamer_of(stem) is expected or layout.streamer_of(stem) == expected


def test_streamer_of_uses_only_the_basename(tmp_root):
    stem = "00042_user_20250101_120000"
    assert layout.streamer_of(str(tmp_root / "ts" / stem)) == "user"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("00042_user_20250101_120000.overlay.b.ass", ("00042_user_20250101_120000", "user")),
        ("00042_user_20250101_120000.mp4", ("00042_user_20250101_120000", "user")),
        ("00042_user_20250101_120000", ("00042_user_20250101_120000", "user")),
        ("00042_a_b_20250101_120000.up.ffmpeg.log", ("00042_a_b_20250101_120000", "a_b")),
        ("user_20250101_120000.mp4", ("user_20250101_120000", "user")),
        ("avatars", (None, None)),
        ("00042_user_20250101_120000_extra.mp4", (None, None)),
    ],
)
def test_artifact_owner(name, expected):
    assert layout.artifact_owner(name) == expected


def test_artifact_owner_agrees_with_streamer_of_on_bare_stems():
    for stem in ("00001_user_20250101_120000", "user_20250101_120000",
                 "00001_a_b.c_20251231_235959"):
        assert layout.artifact_owner(stem) == (stem, layout.streamer_of(stem))


# ---------------- layout: path resolution ----------------


def test_nested_paths_derive_streamer_from_stem(tmp_root):
    stem = "00042_user_20250101_120000"
    assert layout.session_dir(tmp_root, stem) == tmp_root / "user" / "ts" / stem
    assert layout.mp4_dir(tmp_root, stem) == tmp_root / "user" / "mp4"
    assert layout.mp4_path(tmp_root, stem) == tmp_root / "user" / "mp4" / f"{stem}.mp4"


def test_explicit_streamer_overrides_the_stem(tmp_root):
    stem = "00042_user_20250101_120000"
    assert layout.mp4_path(tmp_root, stem, "other") == tmp_root / "other" / "mp4" / f"{stem}.mp4"
    # 空文字はstemからの導出にフォールバックする(誤ってroot直下へ書かない)
    assert layout.mp4_path(tmp_root, stem, "") == tmp_root / "user" / "mp4" / f"{stem}.mp4"


def test_non_conforming_stem_falls_back_to_flat_layout(tmp_root):
    assert layout.session_dir(tmp_root, "garbage") == tmp_root / "garbage"
    assert layout.mp4_dir(tmp_root, "garbage") == tmp_root
    assert layout.mp4_path(tmp_root, "garbage") == tmp_root / "garbage.mp4"


def test_clips_dir_lives_under_the_streamer_folder(tmp_root):
    """置き場は配信者folderの下。録画(ts/mp4)と同じ階層に並べる。"""
    assert layout.clips_dir(tmp_root, "user") == tmp_root / "user" / "_clips"
    # 配信者が読めないときだけroot直下へ落ちる(mp4_dirと同じ決め方)。root直下の ``_clips``
    # を配信者folderと取り違えないよう、名前は共有dirのままにしておく。
    assert layout.clips_dir(tmp_root) == tmp_root / "_clips"
    assert layout.CLIPS_DIRNAME in layout.NON_STREAMER_DIRS


def test_stills_dir_is_separate_from_the_clips_dir(tmp_root):
    """静止画は動画と別のdirへ出す。決め方(配信者folderの下・root直下への落ち方)は同じ。"""
    assert layout.stills_dir(tmp_root, "user") == tmp_root / "user" / "_screenshots"
    assert layout.stills_dir(tmp_root) == tmp_root / "_screenshots"
    assert layout.stills_dir(tmp_root, "user") != layout.clips_dir(tmp_root, "user")
    assert layout.STILLS_DIRNAME in layout.NON_STREAMER_DIRS


def test_iter_clip_dirs_finds_every_placement(tmp_root):
    """走査は配信者ごとの置き場と、root直下の受け皿の両方を見る。

    片方しか見ない実装は、移行の途中や規約外stemの成果物を「どこにも無い」と言う。
    静止画の置き場も同じ理由でここが返す — 分けたのはdirだけで、一覧・移動・容量が
    見る範囲は分けていない。"""
    layout.clips_dir(tmp_root, "alice").mkdir(parents=True)
    layout.clips_dir(tmp_root, "bob").mkdir(parents=True)
    layout.clips_dir(tmp_root).mkdir(parents=True)
    layout.stills_dir(tmp_root, "alice").mkdir(parents=True)
    layout.stills_dir(tmp_root).mkdir(parents=True)
    (tmp_root / "alice" / layout.MP4_DIRNAME).mkdir(parents=True)

    assert set(layout.iter_clip_dirs(tmp_root)) == {
        tmp_root / "_clips",
        tmp_root / "_screenshots",
        tmp_root / "alice" / "_clips",
        tmp_root / "alice" / "_screenshots",
        tmp_root / "bob" / "_clips",
    }


def test_clip_streamer_of_reads_the_placement_not_the_name(tmp_root):
    """配信者は置き場から読む。旧規約(root直下)の実体も持ち主不明にしない。"""
    assert layout.clip_streamer_of(
        tmp_root, layout.clips_dir(tmp_root, "alice") / "メモ.mp4") == "alice"
    assert layout.clip_streamer_of(
        tmp_root, layout.stills_dir(tmp_root, "alice") / "メモ.png") == "alice"
    assert layout.clip_streamer_of(
        tmp_root, tmp_root / "_clips" / "bob" / "メモ.mp4") == "bob"
    assert layout.clip_streamer_of(tmp_root, tmp_root / "_clips" / "メモ.mp4") is None
    assert layout.clip_streamer_of(tmp_root, tmp_root / "alice" / "mp4" / "x.mp4") is None


def test_is_clip_path_rejects_the_recordings_beside_it(tmp_root):
    """置き場の外は扱わない。rootの下に居ることだけでは録画本体まで通ってしまう。"""
    assert layout.is_clip_path(tmp_root, layout.clips_dir(tmp_root, "alice") / "x.mp4")
    assert layout.is_clip_path(tmp_root, layout.stills_dir(tmp_root, "alice") / "x.png")
    assert layout.is_clip_path(tmp_root, tmp_root / "_clips" / "x.mp4")
    assert layout.is_clip_path(tmp_root, tmp_root / "_screenshots" / "x.png")
    assert not layout.is_clip_path(tmp_root, tmp_root / "alice" / "mp4" / "x.mp4")
    assert not layout.is_clip_path(tmp_root, tmp_root.parent / "x.mp4")


def test_record_root_of_resolves_shared_root_from_nested_artifacts(tmp_root):
    stem = "00042_user_20250101_120000"
    assert layout.record_root_of(layout.mp4_path(tmp_root, stem)) == tmp_root
    assert layout.record_root_of(layout.session_dir(tmp_root, stem)) == tmp_root


def test_record_root_of_flat_path_returns_parent(tmp_root):
    assert layout.record_root_of(tmp_root / "loose.mp4") == tmp_root


def test_iter_sessions_yields_session_dirs_sorted_and_pairs_with_mp4(make_recording, tmp_root):
    stem_b, mp4_b = make_recording(streamer="bob", when="20250101_120000")
    stem_a, mp4_a = make_recording(streamer="alice", when="20250102_130000")

    found = list(layout.iter_sessions(tmp_root))

    assert [p.name for p in found] == [stem_a, stem_b]
    assert [p.parent.parent.name for p in found] == ["alice", "bob"]
    assert layout.mp4_path(tmp_root, found[0].name) == mp4_a
    assert layout.mp4_path(tmp_root, found[1].name) == mp4_b


def test_iter_sessions_skips_shared_dirs_files_and_streamers_without_ts(make_recording, tmp_root):
    stem, _ = make_recording(streamer="alice")
    for shared in layout.NON_STREAMER_DIRS:
        (tmp_root / shared / layout.TS_DIRNAME / "00099_x_20250101_120000").mkdir(parents=True)
    (tmp_root / "mp4only" / layout.MP4_DIRNAME).mkdir(parents=True)
    (tmp_root / "stray.mp4").write_bytes(b"")

    assert [p.name for p in layout.iter_sessions(tmp_root)] == [stem]


def test_iter_sessions_on_missing_root_is_empty(tmp_root):
    assert list(layout.iter_sessions(tmp_root / "does_not_exist")) == []


# ---------------- settings: definition table invariants ----------------


def test_every_setting_def_is_structurally_complete():
    seen_env = {}
    for key, definition in SETTING_DEFS.items():
        assert definition["category"] in CATEGORY_LABELS, key
        assert definition["env"].startswith("TICTOK_"), key
        assert definition["env"] not in seen_env, (key, seen_env.get(definition["env"]))
        seen_env[definition["env"]] = key
        assert definition["label"] and definition["note"], key
        assert definition["type"] in (int, float, str), key
        if definition["type"] is str:
            assert isinstance(definition["default"], str), key
        else:
            assert definition["min"] <= definition["default"] <= definition["max"], key


def test_setting_options_stay_inside_the_declared_range():
    for key, definition in SETTING_DEFS.items():
        for option in definition.get("options", []):
            assert isinstance(option["value"], definition["type"]), key
            # 範囲は数値の設定にしか意味が無い。optionsを持つstrは列挙で、min/maxを持たない。
            if definition["type"] is not str:
                assert definition["min"] <= option["value"] <= definition["max"], key
            assert option["label"], key


def test_category_labels_and_used_categories_match_exactly():
    used = {d["category"] for d in SETTING_DEFS.values()}
    assert used == set(CATEGORY_LABELS)


def test_each_category_occupies_exactly_one_contiguous_run():
    """categoryごとの出現は1連続でなければならない。

    設定画面(static/settings.js)はcategoryが切り替わるたびheaderを差し込むだけなので、
    同じcategoryが離れた位置に現れると同じheaderが二度描画され、検索filterも
    dataset.category重複により空のheaderを残す。定義順そのものが不変条件。
    """
    runs = [category for category, _ in groupby(d["category"] for d in SETTING_DEFS.values())]
    duplicated = [c for c in set(runs) if runs.count(c) > 1]
    assert not duplicated, f"categoryが分断されています: {duplicated} (出現順: {runs})"


# ---------------- settings: resolution order ----------------


def test_settings_resolution_order_db_beats_env_beats_default(tmp_db, monkeypatch):
    monkeypatch.delenv("TICTOK_BUCKET_SECONDS", raising=False)
    monkeypatch.delenv("TICTOK_EVENT_HISTORY", raising=False)
    monkeypatch.setenv("TICTOK_EVENT_HISTORY", "321")
    monkeypatch.setenv("TICTOK_SESSION_LIST_LIMIT", "50")
    tmp_db.set_settings({"session_list_limit": 77})

    resolved = Settings(tmp_db)

    assert resolved.get("bucket_seconds") == SETTING_DEFS["bucket_seconds"]["default"]
    assert resolved.get("event_history") == 321
    assert resolved.get("session_list_limit") == 77


def test_settings_values_are_typed_not_raw_strings(tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_RECONNECT_BASE_DELAY", "3")
    tmp_db.set_settings({"bucket_seconds": "15"})

    resolved = Settings(tmp_db)

    assert resolved.get("reconnect_base_delay") == 3.0
    assert isinstance(resolved.get("reconnect_base_delay"), float)
    assert resolved.get("bucket_seconds") == 15
    assert isinstance(resolved.get("bucket_seconds"), int)


def test_all_values_is_a_snapshot_copy(tmp_db):
    resolved = Settings(tmp_db)
    snapshot = resolved.all_values()
    snapshot["bucket_seconds"] = -1
    assert resolved.get("bucket_seconds") != -1


# ---------------- settings: DB値の検証 ----------------
# DBへはupdate()経由でしか入らない建前だが、SETTING_DEFSのtype/min/max/optionsを後から
# 変更すると、保存された時点では正しかった既存行がその建前を破る。


@pytest.mark.parametrize("stored", ["abc", "10.9", ""])
def test_unreadable_db_value_stops_startup_naming_the_key(tmp_db, stored, caplog):
    """型として読めない値は走らせる値が無いので起動を止める。ただし素の
    「invalid literal for int()」で死なせず、keyと値と直し方を名指しすること。"""
    tmp_db.set_settings({"bucket_seconds": stored})

    with caplog.at_level("ERROR", logger="tictok.settings"):
        with pytest.raises(ValueError, match="bucket_seconds"):
            Settings(tmp_db)

    record = [r for r in caplog.records
              if getattr(r, "event", "") == "process.settings_db_unreadable"][-1]
    assert record.ctx["key"] == "bucket_seconds"
    assert record.ctx["stored"] == stored
    assert record.ctx["builtin_default"] == SETTING_DEFS["bucket_seconds"]["default"]


@pytest.mark.parametrize(
    "key, stored",
    [
        ("bucket_seconds", 99999),          # 範囲外(上)
        ("bucket_seconds", -5),             # 範囲外(下)
        ("clip_default_mode", "no-such-mode"),  # optionsに無い
        ("record_dir", "relative/dir"),     # 絶対パスでない
    ],
)
def test_out_of_definition_db_value_keeps_running_and_is_reported(tmp_db, key, stored, caplog):
    """定義に反する保存値を既定値へ差し替えない(No fallback)。差し替えると画面には既定値が
    現在値として並び、operatorは自分の設定が捨てられたことを知る術がない。"""
    tmp_db.set_settings({key: stored})

    with caplog.at_level("ERROR", logger="tictok.settings"):
        resolved = Settings(tmp_db)

    assert resolved.get(key) == SETTING_DEFS[key]["type"](stored)
    assert resolved.get(key) != SETTING_DEFS[key]["default"]
    assert key in resolved.invalid_values()

    record = [r for r in caplog.records
              if getattr(r, "event", "") == "process.settings_db_invalid"][0]
    assert record.ctx["key"] == key
    assert record.ctx["stored"] == str(stored)
    assert record.ctx["reason"]


def test_invalid_db_value_keeps_the_settings_screen_openable(tmp_db):
    """DB値の修正tool は設定画面そのもの。envと違い、範囲が動っただけで起動を拒むと
    直す画面ごと止まる。画面は開いたまま、該当keyに理由を添えて提示すること。"""
    tmp_db.set_settings({"bucket_seconds": 99999})

    resolved = Settings(tmp_db)
    described = {entry["key"]: entry for entry in resolved.describe()}

    assert described["bucket_seconds"]["value"] == 99999
    assert "範囲" in described["bucket_seconds"]["invalid"]
    # 適合しているkeyはfield自体を持たない
    assert "invalid" not in described["session_list_limit"]


def test_invalid_db_value_is_recorded_as_an_ops_event(tmp_db):
    tmp_db.set_settings({"bucket_seconds": 99999})

    Settings(tmp_db)

    kinds = [row["kind"] for row in tmp_db.list_ops_events(limit=20)]
    assert "process.settings_db_invalid" in kinds


def test_saving_a_valid_value_clears_the_invalid_mark(tmp_db):
    tmp_db.set_settings({"bucket_seconds": 99999})
    resolved = Settings(tmp_db)
    assert "bucket_seconds" in resolved.invalid_values()

    resolved.update({"bucket_seconds": 30})

    assert resolved.invalid_values() == {}
    described = {entry["key"]: entry for entry in resolved.describe()}
    assert "invalid" not in described["bucket_seconds"]


def test_invalid_values_is_a_snapshot_copy(tmp_db):
    tmp_db.set_settings({"bucket_seconds": 99999})
    resolved = Settings(tmp_db)
    snapshot = resolved.invalid_values()
    snapshot.clear()
    assert "bucket_seconds" in resolved.invalid_values()


def test_valid_db_values_are_not_marked_invalid(tmp_db, caplog):
    tmp_db.set_settings({"bucket_seconds": 15, "session_list_limit": 77})

    with caplog.at_level("ERROR", logger="tictok.settings"):
        resolved = Settings(tmp_db)

    assert resolved.invalid_values() == {}
    assert resolved.get("bucket_seconds") == 15
    assert not [r for r in caplog.records
                if getattr(r, "event", "").startswith("process.settings_db_")]


def test_rows_outside_the_definition_are_ignored_without_noise(tmp_db, caplog):
    """settings表は移行済みmarker(``_migration:<name>``)も持つ共有の表。定義に無いkeyは
    読まないだけで、残骸として騒がないこと(markerと見分ける手段が無い)。"""
    tmp_db.set_settings({"bucket_seconds": 15, "removed_setting": "1"})

    with caplog.at_level("WARNING", logger="tictok.settings"):
        resolved = Settings(tmp_db)

    assert "removed_setting" not in resolved.all_values()
    assert resolved.get("bucket_seconds") == 15
    assert [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")] == []


# ---------------- settings: update validation ----------------


def test_update_rejects_unknown_key(tmp_db):
    with pytest.raises(ValueError, match="不明な設定key"):
        Settings(tmp_db).update({"no_such_setting": 1})


@pytest.mark.parametrize("value", [0, 601, -1])
def test_update_rejects_out_of_range(tmp_db, value):
    with pytest.raises(ValueError):
        Settings(tmp_db).update({"bucket_seconds": value})


def test_update_rejects_fractional_value_for_int_setting(tmp_db):
    resolved = Settings(tmp_db)
    with pytest.raises(ValueError):
        resolved.update({"bucket_seconds": 10.9})
    # 整数値のfloatは切り捨てが発生しないので受け入れる
    assert resolved.update({"bucket_seconds": 10.0})["bucket_seconds"] == 10


def test_update_rejects_non_numeric_value(tmp_db):
    with pytest.raises(ValueError, match="値が不正です"):
        Settings(tmp_db).update({"bucket_seconds": "abc"})


def test_update_accepts_boundary_values(tmp_db):
    resolved = Settings(tmp_db)
    low = SETTING_DEFS["bucket_seconds"]["min"]
    high = SETTING_DEFS["bucket_seconds"]["max"]
    assert resolved.update({"bucket_seconds": low})["bucket_seconds"] == low
    assert resolved.update({"bucket_seconds": high})["bucket_seconds"] == high


def test_update_persists_to_db_and_survives_a_reload(tmp_db):
    Settings(tmp_db).update({"session_list_limit": 42})
    assert Settings(tmp_db).get("session_list_limit") == 42


def test_update_of_path_setting_requires_absolute_and_creates_dir(tmp_db, tmp_path):
    target = tmp_path / "rec root" / "nested"
    resolved = Settings(tmp_db)

    assert resolved.update({"record_dir": f'"{target}"'})["record_dir"] == str(target)
    assert target.is_dir()

    with pytest.raises(ValueError, match="絶対パス"):
        resolved.update({"record_dir": "relative/dir"})


def test_update_of_path_setting_rejects_empty_unless_allowed(tmp_db):
    resolved = Settings(tmp_db)
    with pytest.raises(ValueError, match="指定してください"):
        resolved.update({"record_dir": "   "})
    assert resolved.update({"record_dir_final": "  "})["record_dir_final"] == ""


def test_update_of_multiple_keys_is_all_or_nothing(tmp_db):
    resolved = Settings(tmp_db)
    before = resolved.get("bucket_seconds")
    with pytest.raises(ValueError):
        resolved.update({"bucket_seconds": 30, "event_history": 999999})
    assert resolved.get("bucket_seconds") == before
    assert Settings(tmp_db).get("bucket_seconds") == before


# ---------------- settings: describe ----------------


def test_describe_marks_env_overridden_defaults(tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_SESSION_LIST_LIMIT", "250")
    monkeypatch.delenv("TICTOK_BUCKET_SECONDS", raising=False)

    described = {entry["key"]: entry for entry in Settings(tmp_db).describe()}

    env_entry = described["session_list_limit"]
    assert env_entry["default"] == 250
    assert env_entry["default_source"] == "env"
    assert env_entry["builtin_default"] == SETTING_DEFS["session_list_limit"]["default"]

    builtin_entry = described["bucket_seconds"]
    assert builtin_entry["default_source"] == "builtin"
    assert builtin_entry["default"] == builtin_entry["builtin_default"]


def test_describe_shapes_text_and_numeric_entries_differently(tmp_db):
    described = {entry["key"]: entry for entry in Settings(tmp_db).describe()}

    assert described["record_dir"]["kind"] == "text"
    assert "min" not in described["record_dir"]
    assert described["bucket_seconds"]["step"] == 1
    assert described["reconnect_base_delay"]["step"] == 0.5
    assert described["auto_record"]["options"] == SETTING_DEFS["auto_record"]["options"]


def test_describe_covers_every_key_with_a_resolvable_category_label(tmp_db):
    described = Settings(tmp_db).describe()
    assert [entry["key"] for entry in described] == list(SETTING_DEFS)
    for entry in described:
        assert entry["category_label"] == CATEGORY_LABELS[entry["category"]]


@pytest.mark.parametrize("raw", ["99999", "0", "abc"])
def test_env_default_out_of_range_is_rejected_at_load(tmp_db, monkeypatch, raw):
    """範囲外のenvは既定値へ黙って落とさず(No fallback)、起動時に例外にする。"""
    monkeypatch.setenv("TICTOK_BUCKET_SECONDS", raw)
    with pytest.raises(ValueError):
        Settings(tmp_db)


def test_env_default_is_rejected_even_when_db_overrides_the_key(tmp_db, monkeypatch):
    """DB値が勝つkeyでもenvは検証する。describe()が同じ解決を行うため、
    見逃すと起動は通るのに設定画面だけが開けなくなる。"""
    tmp_db.set_settings({"bucket_seconds": 15})
    monkeypatch.setenv("TICTOK_BUCKET_SECONDS", "99999")
    with pytest.raises(ValueError):
        Settings(tmp_db)


def test_env_default_within_range_is_accepted(tmp_db, monkeypatch):
    monkeypatch.setenv("TICTOK_BUCKET_SECONDS", "600")
    monkeypatch.setenv("TICTOK_RECONNECT_BASE_DELAY", "0.5")
    resolved = Settings(tmp_db)
    assert resolved.get("bucket_seconds") == 600
    assert resolved.get("reconnect_base_delay") == 0.5


def test_described_default_is_always_acceptable_to_update(tmp_db, tmp_path, monkeypatch):
    """画面の「既定値へ戻す」→「保存」が422で弾かれないこと。

    describe()のdefaultはそのままupdate()へ送られる値なので、両者の検証は同じ。
    path系(kind=text)も除外しない。除外すると、唯一まだ壊れうる種別を見逃す。
    """
    monkeypatch.setenv("TICTOK_SESSION_LIST_LIMIT", "250")
    # 本番の録画先をupdate()のmkdir/W_OK checkに晒さないため、tmpへ向ける。
    monkeypatch.setenv("TICTOK_RECORD_DIR", str(tmp_path / "rec"))
    resolved = Settings(tmp_db)
    for entry in resolved.describe():
        assert resolved.update({entry["key"]: entry["default"]})[entry["key"]] == entry["default"]


@pytest.mark.parametrize("bad", ["relative/dir", "   ", ""])
def test_path_env_default_out_of_shape_is_rejected_at_load(tmp_db, monkeypatch, bad):
    """path系のenv既定値も検証する。素通しすると相対path等がそのまま実行値かつ
    describe()のdefaultになり、「既定値へ戻す」→「保存」がupdate()側で弾かれる。"""
    monkeypatch.setenv("TICTOK_RECORD_DIR", bad)
    with pytest.raises(ValueError):
        Settings(tmp_db)


def test_path_env_default_allowing_empty_still_accepts_empty(tmp_db, monkeypatch):
    """allow_empty のkeyは空を許す(未設定を意味する正当な値)。"""
    monkeypatch.setenv("TICTOK_RECORD_DIR_FINAL", "")
    assert Settings(tmp_db).get("record_dir_final") == ""


def test_default_record_dir_matches_config_default(monkeypatch):
    monkeypatch.delenv("TICTOK_RECORD_DIR", raising=False)
    assert settings_mod._DEFAULT_RECORD_DIR == config.get_record_dir()


# ---------------- api.fsfacts: cacheの上限 ----------------
# fsfactsのcacheはTTLで「まだ正しいか」しか見ておらず、期限切れを消す者がいなかったため、
# processが見たpathの数だけ単調に伸びていた。上限の根拠を実測値で固定する。
#
# 実測(tictok.db, 2026-07-29): 録画374本。43.1日で374本 = 8.68本/日。
_MEASURED_RECORDINGS = 374
_MEASURED_RECORDINGS_PER_DAY = 8.68


@pytest.fixture
def fsfacts(env_guard):
    """env_guardを効かせてからimportする(tictok.api.runtimeはimport時にStorage/instance
    lock/record dirを掴むため、順序が逆だと本番を掴む)。cacheはprocess共有なので必ず戻す。"""
    from tictok.api import fsfacts as module

    for cache in (module._fs_state_cache, module._fs_bulk_cache, module._bulk_status_cache):
        cache.clear()
    yield module
    for cache in (module._fs_state_cache, module._fs_bulk_cache, module._bulk_status_cache):
        cache.clear()


def test_fs_caches_hold_the_whole_recording_population_without_evicting(fsfacts):
    """1回のpollは**全録画**をstatしに来る。上限が録画数を下回ると同じpoll中に自分で自分を
    追い出し、cacheが防ぐはずだったstatの嵐へ戻る。実測の録画数に、実測の増加ペースで1年
    ぶんを足しても捨てないこと。"""
    working_set = _MEASURED_RECORDINGS + int(_MEASURED_RECORDINGS_PER_DAY * 365)

    for index in range(working_set):
        fsfacts._fs_state_cache[f"K:\rec\s\mp4\{index:05d}_user_20250101_120000.mp4"] = (
            0.0, False, False)

    assert working_set < fsfacts._FS_FACTS_CACHE_MAX
    assert len(fsfacts._fs_state_cache) == working_set


@pytest.mark.parametrize("name", ["_fs_state_cache", "_fs_bulk_cache", "_bulk_status_cache"])
def test_caches_stop_growing_at_their_cap(fsfacts, name):
    cache = getattr(fsfacts, name)
    cap = cache._max_entries

    for index in range(cap * 2):
        cache[f"key-{index}"] = (0.0, index)

    assert len(cache) <= cap
    # 捨てるのは上限に達したときに古い方から1/4。丸ごと空にはしない(直後のpollが全件
    # 引き直しになる)。
    assert len(cache) > cap // 2


def test_cache_evicts_the_oldest_entries_first(fsfacts):
    cache = fsfacts._fs_state_cache
    cap = cache._max_entries
    for index in range(cap):
        cache[f"key-{index}"] = (0.0, index)

    cache["key-new"] = (0.0, -1)

    assert "key-0" not in cache
    assert f"key-{cap - 1}" in cache
    assert "key-new" in cache
    assert len(cache) == cap - cap // 4 + 1


def test_updating_an_existing_key_never_evicts(fsfacts):
    """既存keyの入れ替えではdictは伸びない。そこで捨てるとTTL内の生きたentryを巻き添えに
    hit率だけが落ちる(store/_common.pyの_USER_CACHE_MAXと同じ扱い)。"""
    cache = fsfacts._fs_state_cache
    cap = cache._max_entries
    for index in range(cap):
        cache[f"key-{index}"] = (0.0, index)

    for _ in range(100):
        cache["key-0"] = (1.0, "更新")

    assert len(cache) == cap
    assert cache["key-0"] == (1.0, "更新")


def test_bulk_status_cache_cap_clears_the_legitimate_key_space(fsfacts):
    """正当なkeyは BULK_KINDS の空でない部分集合ぶんしか無い。上限がそれを下回ると、
    重複入りの要求が来なくても通常利用で捨て合うことになる。"""
    from tictok.api.routes.bulk import BULK_KINDS

    legitimate_keys = 2 ** len(BULK_KINDS) - 1
    assert fsfacts._BULK_STATUS_CACHE_MAX > legitimate_keys


def test_caches_stay_bounded_after_clear(fsfacts):
    """無効化(_media_job_runner等)はclear()で行う。clearでただのdictに戻らないこと。"""
    fsfacts._fs_bulk_cache.clear()
    cap = fsfacts._fs_bulk_cache._max_entries
    for index in range(cap + 10):
        fsfacts._fs_bulk_cache[f"key-{index}"] = (0.0, {})

    assert len(fsfacts._fs_bulk_cache) <= cap
