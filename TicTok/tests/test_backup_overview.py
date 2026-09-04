"""退避の状況を1枚に束ねる層(``api.routes.backup``)。

ここで確かめるのは**経路の状態の決め方**だけである。周期の判定は ``api.startup`` が、世代と
行数の見張りは ``core.dbmaint`` が持っていて、それぞれのtestが在る。この層の失敗は
「動いているのに止まって見える / 止まっているのに動いて見える」のどちらかで、どちらも
画面を見ている人には区別が付かない ―― 退避は結果を毎日確かめる物ではないので、
見え方が間違っていること自体が長く残る。

状態には優先順位が在る。1本の経路は同時に複数当てはまり得るが(止めてあり、かつ届かない)、
人が知りたいのは常に重い方である。
"""
import pytest


@pytest.fixture
def routes(env_guard):
    """``env_guard`` を先に効かせてから import する(``tictok.api.runtime`` は import時に
    Storage と instance lock を掴むため)。"""
    from tictok.api.routes import backup as module

    return module


def step(**over) -> dict:
    base = {"enabled": True, "pending": 0, "overdue": False, "failures": 0,
            "retry_in_seconds": 0.0, "mark_at": None, "pending_oldest_at": None,
            "grace_seconds": 1200.0}
    base.update(over)
    return base


def dest(reachable=True) -> dict:
    return {"path": "U:\\TicTokDB", "exists": reachable, "reachable": reachable,
            "volume": "U:"}


def test_caught_up_is_ok(routes):
    assert routes._lane_state(step(), [dest()], {"ts": 100.0}, {}) == routes.STATE_OK


def test_pending_work_is_not_a_problem(routes):
    """写す物が控えているのは正常な途中経過。周期は60秒なので、控えを警告にすると
    毎分その色が点く。"""
    assert routes._lane_state(step(pending=3), [dest()], {"ts": 100.0}, {}) \
        == routes.STATE_WORKING


def test_pending_past_the_grace_is_late(routes):
    assert routes._lane_state(step(pending=3, overdue=True), [dest()], {"ts": 100.0}, {}) \
        == routes.STATE_LATE


def test_a_newer_failure_outranks_an_older_success(routes):
    """成否は時刻で決める。失敗の記録が在るだけで失敗と読むと、直った経路が永久に赤くなる。"""
    assert routes._lane_state(step(), [dest()], {"ts": 100.0}, {"ts": 200.0}) \
        == routes.STATE_FAILING
    assert routes._lane_state(step(), [dest()], {"ts": 300.0}, {"ts": 200.0}) \
        == routes.STATE_OK


def test_a_pending_retry_counts_as_failing(routes):
    """再試行待ちは失敗である。記録がまだ無くても、backoffが立っている時点で止まっている。"""
    assert routes._lane_state(step(failures=2, retry_in_seconds=240.0), [dest()], {}, {}) \
        == routes.STATE_FAILING


def test_an_unreachable_destination_outranks_a_stale_success(routes):
    """driveが外れた直後は、まだ失敗の記録が無い(録画が終わって初めて退避が走る)。
    退避先へ届かないこと自体を状態にしないと、その間ずっと正常に見える。"""
    assert routes._lane_state(step(), [dest(reachable=False)], {"ts": 100.0}, {}) \
        == routes.STATE_UNREACHABLE


def test_one_reachable_destination_is_enough(routes):
    """設定値の書き出しは、書ける保存先にだけ書く。1つでも届くなら経路は生きている。"""
    assert routes._lane_state(step(), [dest(False), dest(True)], {"ts": 100.0}, {}) \
        == routes.STATE_OK


def test_a_disabled_backup_is_never_an_alert(routes):
    """止めてある退避は、届かなくても失敗していても「止めてある」である。設定どおりの
    状態を障害として並べると、本当に落ちている経路がその中に埋もれる。"""
    assert routes._lane_state(step(enabled=False, failures=3, overdue=True),
                              [dest(reachable=False)], {}, {"ts": 200.0}) \
        == routes.STATE_OFF


def test_the_badge_reports_only_the_heaviest_state(routes):
    """badgeは1つしか出せない。軽い方を採ると重い方が隠れる。"""
    assert routes._ALERT_STATES[0] == routes.STATE_UNREACHABLE
    assert routes.STATE_OK not in routes._ALERT_STATES
    assert routes.STATE_WORKING not in routes._ALERT_STATES
    assert routes.STATE_OFF not in routes._ALERT_STATES


def test_mirror_needs_two_final_dirs_to_count_as_a_lane(routes):
    """二重化は周期に乗らない。1系統しか無ければ「二重ではない」であって、遅れでも
    失敗でもない。"""
    lane = next(item for item in routes._LANES if item["key"] == "mirror")
    schedule = {"steps": {}}
    assert routes._lane_step(lane, schedule, ["K:\\a"])["enabled"] is False
    assert routes._lane_step(lane, schedule, ["K:\\a", "J:\\a"])["enabled"] is True
    # 印を持たないので、控えとして数えられることも無い。
    assert routes._lane_step(lane, schedule, ["K:\\a", "J:\\a"])["pending"] == 0


def test_the_latest_of_several_kinds_wins(routes):
    """1つの経路が複数のkindで成功を名乗る(設定値と手入力データ)。新しい方を採らないと、
    片方が書けなかった回の古い時刻が最終成功として残る。"""
    latest = {"backup.settings_exported": {"kind": "a", "ts": 100.0},
              "backup.tables_exported": {"kind": "b", "ts": 300.0}}
    assert routes._latest_of(latest, ("backup.settings_exported",
                                      "backup.tables_exported"))["ts"] == 300.0
    assert routes._latest_of(latest, ("record_backup.job_completed",)) == {}


def test_a_destination_whose_parent_is_gone_is_unreachable(routes, tmp_path):
    """退避先の folder が未作成なだけなら、次の退避が自分で作る。**親ごと無い**のが
    「届いていない」で、この2つを混ぜると driveが在るのに赤くなる。"""
    parent = tmp_path / "drive"
    parent.mkdir()
    assert routes._dest_facts(parent / "TicTokDB")["reachable"] is True
    assert routes._dest_facts(parent / "TicTokDB")["exists"] is False
    assert routes._dest_facts(tmp_path / "gone" / "TicTokDB")["reachable"] is False


def check(**over) -> dict:
    base = {"at": 1000.0, "final_dirs": ["K:\\a", "J:\\a"], "missing_items": 0,
            "missing_bytes": 0, "missing_by_dst": {}, "diverged": 0, "errors": 0,
            "stale": False, "enabled": True}
    base.update(over)
    return base


def test_a_verified_gap_outranks_a_successful_relocation(routes):
    """移送は必ず全系統へ書くので、成功の記録だけを見ている限り片方が古いことは永久に
    現れない。突き合わせた結果を入れなければ、543GB欠けた系統を抱えたまま緑のままになる。"""
    assert routes._lane_state(step(), [dest()], {"ts": 100.0}, {}, gap=True)         == routes.STATE_DEGRADED
    assert routes._lane_reason(
        next(item for item in routes._LANES if item["key"] == "mirror"),
        routes.STATE_DEGRADED, [dest()], ["K:\\a", "J:\\a"],
    )["key"] == routes.REASON_UNSYNCED


def test_a_gap_never_outranks_a_failure(routes):
    """欠けていることと止まっていることは同時に起こる。直しに行く先が違うので、
    重い方(止まっている)を出す。"""
    assert routes._lane_state(step(failures=1), [dest()], {}, {}, gap=True)         == routes.STATE_FAILING
    assert routes._lane_state(step(enabled=False), [dest()], {}, {}, gap=True)         == routes.STATE_OFF


def test_an_unchecked_pair_is_not_a_gap(routes):
    """一度も突き合わせていない構成を欠けとして立てると常時赤になり、本当に欠けた日の
    警報と見分けが付かなくなる。未確認であることは画面が別に名乗る。"""
    assert routes._mirror_gap(check(at=None, missing_items=12293)) is False
    assert routes._mirror_gap(check(missing_items=0, diverged=0)) is False


def test_a_gap_found_by_a_scan_is_a_gap(routes):
    """欠けと食い違いは別の事実で、どちらも「揃っていない」である。"""
    assert routes._mirror_gap(check(missing_items=12293)) is True
    assert routes._mirror_gap(check(diverged=3)) is True


def test_a_stale_result_is_not_a_gap(routes):
    """再同期の直後に残っている件数は**実行前の**姿である。それを現在の欠けとして
    立てると、埋め終わった直後の画面が埋める前の件数で赤くなる。"""
    assert routes._mirror_gap(check(missing_items=12293, stale=True)) is False
