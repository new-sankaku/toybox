"""手入力データの退避(tictok.core.tables_export)。

見ているのは「DBが無くても読める形で対象表が各保存先に残る」ことと、設定値の退避と同じ世代の
規則(同じ内容なら作らない・書けない先があっても書ける先には書く)で置かれることだけである。
"""
import json
from pathlib import Path

import pytest

from tictok.core import layout, settings_export, tables_export
from tictok.store.row_trash import ROW_TRASH_TABLES


@pytest.fixture
def roots(tmp_path):
    made = []
    for name in ("work", "final1", "final2"):
        path = (tmp_path / name).resolve()
        path.mkdir()
        made.append(path)
    return made


def _latest(root):
    latest = tables_export.latest_export(root)
    assert latest is not None
    return latest


def test_every_human_table_lands_in_every_root(tmp_db, roots, tmp_db_path):
    tmp_db.set_settings({"live_check_interval": "45"})
    tmp_db.add_monitored_target("alice", record_video=True)

    result = tables_export.export_tables(tmp_db, roots, tmp_db_path)

    assert result["created"] is True
    assert result["failed"] == []
    assert [item["root"] for item in result["written"]] == [str(root) for root in roots]
    for root in roots:
        payload = _latest(root)
        assert payload["digest"] == result["digest"]
        tables = payload["export"]["tables"]
        assert set(tables) == set(ROW_TRASH_TABLES)
        assert tables["monitored_targets"]["rows"][0]["unique_id"] == "alice"
        settings_rows = {row["key"]: row["value"] for row in tables["settings"]["rows"]}
        assert settings_rows["live_check_interval"] == "45"
        # 列名はそのまま。戻すときの材料なので、加工した瞬間に元の値が失われる。
        assert "record_video" in tables["monitored_targets"]["columns"]
    assert result["counts"]["monitored_targets"] == 1
    # 設定値の退避と同じ置き場に、別の接頭辞で並ぶ。
    name = Path(result["written"][0]["path"])
    assert name.parent == roots[0] / layout.CONFIG_DIRNAME
    assert name.name.startswith("tables-")
    assert settings_export.list_exports(roots[0]) == []


def test_same_content_makes_no_new_generation(tmp_db, roots, tmp_db_path):
    first = tables_export.export_tables(tmp_db, roots, tmp_db_path)
    second = tables_export.export_tables(tmp_db, roots, tmp_db_path)

    assert second["created"] is False
    assert second["unchanged"] == [str(root) for root in roots]
    assert all(len(tables_export.list_exports(root)) == 1 for root in roots)

    tmp_db.add_monitored_target("bob", record_video=False)
    third = tables_export.export_tables(tmp_db, roots, tmp_db_path)

    assert third["created"] is True
    assert third["digest"] != first["digest"]
    assert all(len(tables_export.list_exports(root)) == 2 for root in roots)
    assert _latest(roots[0])["counts"]["monitored_targets"] == 1


def test_an_unavailable_root_does_not_stop_the_others(tmp_db, roots, tmp_db_path):
    """設定値の退避と同じ判断: 元を消さない写しなので、書けない先があっても書ける先には書く。"""
    missing = roots[1]
    missing.rmdir()

    result = tables_export.export_tables(tmp_db, roots, tmp_db_path)

    assert [item["root"] for item in result["written"]] == [str(roots[0]), str(roots[2])]
    assert [item["root"] for item in result["failed"]] == [str(missing)]
    assert not missing.exists()
    kinds = [event["kind"] for event in tmp_db.list_ops_events(limit=10)]
    assert "backup.tables_exported" in kinds
    assert "backup.tables_export_failed" in kinds


def test_the_file_is_plain_json_readable_without_the_server(tmp_db, roots, tmp_db_path):
    tmp_db.add_monitored_target("alice", record_video=True)
    result = tables_export.export_tables(tmp_db, roots, tmp_db_path)

    raw = json.loads(Path(result["written"][0]["path"]).read_text(encoding="utf-8"))

    assert raw["exported_at"]
    assert raw["export"]["tables"]["monitored_targets"]["rows"] == [
        {"unique_id": "alice", "added_at": pytest.approx(raw["export"]["tables"]["monitored_targets"]["rows"][0]["added_at"]),
         "record_video": 1}]
