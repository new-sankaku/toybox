import json
from pathlib import Path

import pytest

from tictok.core import config, layout, settings_export
from tictok.core.settings import Settings


@pytest.fixture
def roots(tmp_path):
    """一次保存先1つ・二次保存先2つを模したrootの並び。"""
    made = []
    for name in ("work", "final1", "final2"):
        path = (tmp_path / name).resolve()
        path.mkdir()
        made.append(path)
    return made


@pytest.fixture
def settings(tmp_db):
    return Settings(tmp_db)


def _payload(root):
    latest = settings_export.latest_export(root)
    assert latest is not None
    return latest


def _entry(payload, key):
    return next(item for item in payload["export"]["settings"] if item["key"] == key)


def test_placement_follows_layout(roots):
    """置き場のfolder名はlayoutが名乗る1つだけで、配信者folderとしては数えられない。

    落ちると2つ壊れる: 容量の内訳がこのfolderを配信者1人として数え、
    ``scripts/purge_streamers.py`` が監視外の配信者として削除の対象に入れる。"""
    assert settings_export.export_dir(roots[0]) == roots[0] / layout.CONFIG_DIRNAME
    assert layout.CONFIG_DIRNAME in layout.NON_STREAMER_DIRS


def test_writes_every_root(settings, roots, tmp_db_path):
    result = settings_export.export_settings(settings, roots, tmp_db_path)

    assert result["created"] is True
    assert result["failed"] == []
    assert [item["root"] for item in result["written"]] == [str(root) for root in roots]
    for root in roots:
        files = settings_export.list_exports(root)
        assert len(files) == 1
        assert files[0]["name"] == result["name"]
        payload = _payload(root)
        assert payload["digest"] == result["digest"]
        assert payload["export"]["db_path"] == str(tmp_db_path)
        # 実効値・出所・labelとnoteが読めること(この機能の目的そのもの)。
        entry = _entry(payload, "live_check_interval")
        assert entry["value"] == 60
        assert entry["source"] == "default"
        assert entry["label"] and entry["note"]


def test_same_content_makes_no_new_generation(settings, roots, tmp_db_path):
    first = settings_export.export_settings(settings, roots, tmp_db_path)
    second = settings_export.export_settings(settings, roots, tmp_db_path)

    assert second["created"] is False
    assert second["name"] is None
    assert second["digest"] == first["digest"]
    assert second["unchanged"] == [str(root) for root in roots]
    for root in roots:
        assert len(settings_export.list_exports(root)) == 1


def test_changed_value_makes_a_new_generation(settings, roots, tmp_db_path):
    first = settings_export.export_settings(settings, roots, tmp_db_path)
    settings.update({"live_check_interval": 120})

    second = settings_export.export_settings(settings, roots, tmp_db_path)

    assert second["created"] is True
    assert second["digest"] != first["digest"]
    for root in roots:
        assert len(settings_export.list_exports(root)) == 2
        payload = _payload(root)
        entry = _entry(payload, "live_check_interval")
        assert entry["value"] == 120
        # DBに入った値なので出所はdbになり、生の値も表のまま残る。
        assert entry["source"] == "db"
        assert payload["export"]["stored"]["live_check_interval"] == "120"


def test_unwritable_root_does_not_stop_the_others(settings, roots, tmp_db_path, monkeypatch):
    broken = settings_export.export_dir(roots[1])
    real_mkdir = Path.mkdir

    def _mkdir(self, *args, **kwargs):
        if self == broken:
            raise OSError("drive is not available")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _mkdir)
    result = settings_export.export_settings(settings, roots, tmp_db_path)

    assert [item["root"] for item in result["failed"]] == [str(roots[1])]
    assert [item["root"] for item in result["written"]] == [str(roots[0]), str(roots[2])]
    assert settings_export.list_exports(roots[1]) == []
    for root in (roots[0], roots[2]):
        assert len(settings_export.list_exports(root)) == 1


def test_missing_root_is_reported_and_not_created(settings, roots, tmp_path, tmp_db_path):
    absent = (tmp_path / "unmounted").resolve()

    result = settings_export.export_settings(settings, [roots[0], absent], tmp_db_path)

    assert [item["root"] for item in result["failed"]] == [str(absent)]
    assert not absent.exists()
    assert len(settings_export.list_exports(roots[0])) == 1


def test_dotenv_values_are_not_written(settings, roots, tmp_path, tmp_db_path, monkeypatch):
    fake_project = tmp_path / "project"
    fake_project.mkdir()
    (fake_project / ".env").write_text(
        "# comment\n"
        "TICTOK_EULER_API_KEY=super-secret-token\n"
        'TICTOK_NOTIFY_WEBHOOK_URL="https://example.invalid/hook/secret"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "PROJECT_ROOT", fake_project)

    settings_export.export_settings(settings, roots, tmp_db_path)

    path = Path(settings_export.list_exports(roots[0])[0]["path"])
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["export"]["dotenv_keys"] == [
        "TICTOK_EULER_API_KEY", "TICTOK_NOTIFY_WEBHOOK_URL"]
    assert "super-secret-token" not in text
    assert "example.invalid" not in text


def test_no_partial_file_is_left_behind(settings, roots, tmp_db_path, monkeypatch):
    result = settings_export.export_settings(settings, roots, tmp_db_path)
    assert result["created"] is True
    for root in roots:
        assert list(settings_export.export_dir(root).glob("*.partial")) == []

    # renameが落ちた回の残骸も残さない。
    settings.update({"live_check_interval": 90})
    failing_dir = settings_export.export_dir(roots[0])
    real_replace = Path.replace

    def _replace(self, target):
        if self.parent == failing_dir:
            raise OSError("rename failed")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", _replace)
    second = settings_export.export_settings(settings, roots, tmp_db_path)

    assert [item["root"] for item in second["failed"]] == [str(roots[0])]
    assert list(failing_dir.glob("*.partial")) == []
    assert len(settings_export.list_exports(roots[0])) == 1


def test_generations_are_pruned_to_the_limit(settings, roots, tmp_db_path, monkeypatch):
    monkeypatch.setattr(settings_export, "KEEP_GENERATIONS", 3)
    root = roots[0]
    for seconds in (30, 60, 90, 120, 150):
        settings.update({"live_check_interval": seconds})
        settings_export.export_settings(settings, [root], tmp_db_path)

    assert len(settings_export.list_exports(root)) == 3
    assert _entry(_payload(root), "live_check_interval")["value"] == 150


def test_same_second_generations_keep_their_order(settings, roots, tmp_db_path):
    """同じ秒に出来た世代でも、最新が最新として読めること。

    連番は ``-2`` のように付き、その ``-`` はfile名の文字列順では ``.json`` より前に来る。
    名前をそのまま並べると連番なしの1枚目が最新に化けるため、時刻と連番を分けて並べている。"""
    root = roots[0]
    for seconds in (30, 60, 90):
        settings.update({"live_check_interval": seconds})
        settings_export.export_settings(settings, [root], tmp_db_path)

    names = [item["name"] for item in settings_export.list_exports(root)]
    assert len(names) == 3
    assert _entry(_payload(root), "live_check_interval")["value"] == 90


def test_stored_rows_outside_the_definitions_are_kept(settings, tmp_db, roots, tmp_db_path):
    tmp_db.set_settings({"_migration:example": "done"})

    settings_export.export_settings(settings, roots, tmp_db_path)

    assert _payload(roots[0])["export"]["stored"]["_migration:example"] == "done"


def test_duplicate_roots_are_written_once(settings, roots, tmp_db_path):
    root = roots[0]

    result = settings_export.export_settings(settings, [root, root], tmp_db_path)

    assert len(result["written"]) == 1
    assert len(settings_export.list_exports(root)) == 1


def test_unreadable_latest_generation_still_exports(settings, roots, tmp_db_path):
    root = roots[0]
    settings_export.export_settings(settings, [root], tmp_db_path)
    Path(settings_export.list_exports(root)[0]["path"]).write_text("{ broken", encoding="utf-8")

    result = settings_export.export_settings(settings, [root], tmp_db_path)

    assert result["created"] is True
    assert len(settings_export.list_exports(root)) == 2
