"""short(縦の短尺動画)の作り方一式(clip_presets表)。

境界の理由: 1つの表のCRUDと、その列が取り得る値域の定義。値域をここに置くのは、同じ
定義を書き出し側(API)・画面・seedの3箇所が必要とするためで、離して持つと「画面は通すが
DBが弾く」種類のずれが生まれる。

lock契約: lock保持前提のmethodは ``_seed_clip_presets_locked`` だけ(呼び出し元は
``_migrate`` で、既に self._lock を保持している)。他は各methodが自分で self._lock を取る。

## なぜ設定表(settings)ではないのか

settingsは1 keyに1値しか持てない。「15〜60秒の型」と「30〜90秒の型」を併存させたい時点で
表現できず、key名へ番号を埋める形(clip_short1_*)は型の数をcode側で固定することになる。
"""
import time
from typing import Optional

# 列の値域。type は値の読み替えにも使う(boolはDBでは0/1)。
# min/max は「これを外れたら弾く」境界で、既定値はDB schema側のDEFAULTが持つ。
PRESET_FIELDS = {
    "min_seconds": {"type": float, "min": 1.0, "max": 600.0, "label": "尺の下限(秒)",
                    "note": "ここに届かない範囲は候補ごと捨てます。縮めて無理やり通すと話の途中で切れたshortが出ます。"},
    "target_seconds": {"type": float, "min": 1.0, "max": 600.0, "label": "狙いの尺(秒)",
                       "note": "範囲を作るときの目標です。山の前後へこの長さになるまで伸ばします。"},
    "max_seconds": {"type": float, "min": 1.0, "max": 600.0, "label": "尺の上限(秒)",
                    "note": "これを超える範囲は、間の詰め(無音カット)で収まらなければ捨てます。"},
    "peak_position": {"type": float, "min": 0.1, "max": 0.9, "label": "山を置く位置(0=頭 1=末尾)",
                      "note": "盛り上がりの中心を範囲内のどこへ置くかです。0.5で中央、大きいほど山が後ろに来て頭に助走が付きます。"},
    "snap_speech": {"type": bool, "label": "発話の切れ目へ端を寄せる",
                    "note": "文字起こしのsegment境界へ端を吸着させます。話の途中で始まるshortを防ぎます。"},
    "snap_silence": {"type": bool, "label": "無音へ端を寄せる",
                     "note": "音の切れ目(無音span)へ端を吸着させます。文字起こしが無い録画でも効きます。"},
    "snap_max_shift_seconds": {"type": float, "min": 0.0, "max": 30.0, "label": "吸着で動かしてよい秒数",
                               "note": "これより遠い吸着先しか無い端は動かしません。遠くの境界へ引っ張ると山を範囲の外へ押し出します。"},
    "chapter_clamp": {"type": bool, "label": "章の境界を跨がせない",
                      "note": "章立て(AI)がある録画で、範囲が2つの話題に跨るのを防ぎます。章が無い録画では何もしません。"},
    "tighten": {"type": bool, "label": "間(無音)を詰める",
                "note": "発話の合間の無音を落として繋ぎます。尺を上限へ収める手段でもあります。再encodeが入ります。"},
    "tighten_min_silence_seconds": {"type": float, "min": 0.2, "max": 10.0,
                                    "label": "詰める無音の下限(秒)",
                                    "note": "これより短い無音は残します。短い間まで詰めると発話が不自然に繋がります。"},
    "tighten_keep_seconds": {"type": float, "min": 0.0, "max": 5.0, "label": "詰めた後に残す間(秒)",
                             "note": "落とした無音の代わりに残す長さです。0にすると息継ぎが消えます。"},
    "subtitles": {"type": bool, "label": "字幕(telop)を焼く",
                  "note": "文字起こしを画面へ焼き込みます。時刻mapが古い文字起こししか無い録画では焼けません。"},
    "comments": {"type": bool, "label": "コメントを焼く",
                 "note": "既定でoffです。shortは画面が小さく、telopとコメントが同じ面積を奪い合います。"},
    "gifts": {"type": bool, "label": "ギフトを焼く",
              "note": "ギフトのアイコンと送り主を焼き込みます。コメントとは別に指定できます。"},
    "score_bar": {"type": bool, "label": "Battleのスコアバーを焼く",
                  "note": "Battle中の範囲でだけ描かれます。短い尺では点差の推移そのものが中身になります。"},
    "normalize_audio": {"type": bool, "label": "音量を揃える",
                        "note": "出力側だけを正規化します(再生時の音は変わりません)。"},
    "upscale": {"type": bool, "label": "AI高画質化を通す",
                "note": "投稿先がどのみち再encodeするので、上げても情報は増えません。GPUを実時間の数倍占有します。既定はoffです。"},
    "sfx": {"type": bool, "label": "効果音を入れる（作品のみ）",
            "note": "シーンの継ぎ目と、テロップが出る瞬間に効果音を置きます。時刻がミリ秒で分かっている場所だけに置くので、笑いの山には置きません（検出の刻みが1秒で、音を置ける精度に足りないため）。1シーンのshortには効きません。"},
    "safe_top_percent": {"type": float, "min": 0.0, "max": 40.0, "label": "上の安全域(%)",
                         "note": "投稿先のUIが被る帯です。この範囲にはtelopを置きません。"},
    "safe_bottom_percent": {"type": float, "min": 0.0, "max": 40.0, "label": "下の安全域(%)",
                            "note": "上と同じ理由の下側です。"},
}

# 表が空のときにだけ入れる初期の型。空のままだと自動生成が一度も動かせないため置くが、
# これは初期値であって既定の固定ではない — 作成後は行として編集・削除できる。
SEED_PRESETS = (
    {"name": "短尺 (15〜60秒)", "min_seconds": 15.0, "target_seconds": 35.0,
     "max_seconds": 60.0, "peak_position": 0.65, "tighten": 1},
    {"name": "中尺 (30〜90秒)", "min_seconds": 30.0, "target_seconds": 60.0,
     "max_seconds": 90.0, "peak_position": 0.60, "tighten": 0},
)


def coerce_preset_values(values: dict) -> dict:
    """client由来のdictを、列の値域へ収めた上でDBへ入る形へ直す。

    未知のkeyは黙って捨てる(列に無い指定を通すとSQLが組めない)。値域を外れた値は**丸めず
    に弾く**: 丸めると画面には入れた値が残り、DBには別の値が入るため、後から「効いていない
    設定」に見える。"""
    out: dict = {}
    for key, spec in PRESET_FIELDS.items():
        if key not in values:
            continue
        raw = values[key]
        if spec["type"] is bool:
            out[key] = 1 if int(raw) else 0
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{spec['label']}は数値で指定してください。")
        if number < spec["min"] or number > spec["max"]:
            raise ValueError(
                f"{spec['label']}は{spec['min']}〜{spec['max']}の範囲で指定してください。")
        out[key] = number
    return out


def validate_preset(row: dict) -> None:
    """列単独では判定できない、列どうしの整合を見る。"""
    if not (row["min_seconds"] <= row["target_seconds"] <= row["max_seconds"]):
        raise ValueError("尺は 下限 <= 狙い <= 上限 の順で指定してください。")


class ClipPresetsMixin:
    """short の作り方一式(clip_presets表)のCRUD。

    lockもDB接続も持たない。すべて Storage が所有する self._conn / self._lock を借りる。
    """

    def _seed_clip_presets_locked(self) -> int:
        """表が空のときだけ初期の型を入れる。呼び出し元が self._lock を保持していること。

        「1件も無い」ときにしか入れないので、利用者が全部消した状態は尊重される
        (消した型が起動のたびに復活すると、消す操作が効かない)。"""
        existing = self._conn.execute("SELECT COUNT(*) AS n FROM clip_presets").fetchone()["n"]
        if existing:
            return 0
        now = time.time()
        for position, preset in enumerate(SEED_PRESETS):
            columns = ["name", "position", "created_at"] + [
                k for k in preset if k != "name"]
            values = [preset["name"], position, now] + [
                preset[k] for k in preset if k != "name"]
            self._conn.execute(
                f"INSERT INTO clip_presets ({', '.join(columns)})"
                f" VALUES ({', '.join('?' * len(columns))})",
                values,
            )
        return len(SEED_PRESETS)

    def list_clip_presets(self) -> list:
        """並び順。positionがNULLの行(並べ替え前)は末尾へ落とす。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM clip_presets"
                " ORDER BY position IS NULL, position, id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_clip_preset(self, preset_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM clip_presets WHERE id = ?", (preset_id,)).fetchone()
        return dict(row) if row else None

    def default_clip_preset(self) -> Optional[dict]:
        """型を指定されなかったときに使う行(並びの先頭)。1件も無ければNone。

        呼び出し側はNoneを既定値で埋めないこと — 型が無い状態で自動生成を走らせると、
        どの尺で作ったのか誰も言えない成果物が出る。"""
        presets = self.list_clip_presets()
        return presets[0] if presets else None

    def create_clip_preset(self, name: str, values: dict) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("型の名前を入れてください。")
        fields = coerce_preset_values(values)
        missing = [k for k in ("min_seconds", "target_seconds", "max_seconds")
                   if k not in fields]
        if missing:
            raise ValueError("尺の下限・狙い・上限は必須です。")
        validate_preset(fields)
        with self._lock:
            position = self._conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM clip_presets"
            ).fetchone()["next"]
            columns = ["name", "position", "created_at", *fields]
            cursor = self._conn.execute(
                f"INSERT INTO clip_presets ({', '.join(columns)})"
                f" VALUES ({', '.join('?' * len(columns))})",
                [name, position, time.time(), *fields.values()],
            )
            self._conn.commit()
            return cursor.lastrowid

    def update_clip_preset(self, preset_id: int, name: Optional[str], values: dict) -> bool:
        """指定されたkeyだけを書き換える。整合の判定は、書き換え後の行全体で行う。"""
        fields = coerce_preset_values(values)
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM clip_presets WHERE id = ?", (preset_id,)).fetchone()
            if row is None:
                return False
            validate_preset({**dict(row), **fields})
            assignments = []
            params: list = []
            if name is not None:
                cleaned = name.strip()
                if not cleaned:
                    raise ValueError("型の名前を空にはできません。")
                assignments.append("name = ?")
                params.append(cleaned)
            for key, value in fields.items():
                assignments.append(f"{key} = ?")
                params.append(value)
            if not assignments:
                return True
            params.append(preset_id)
            self._conn.execute(
                f"UPDATE clip_presets SET {', '.join(assignments)} WHERE id = ?", params)
            self._conn.commit()
        return True

    def delete_clip_preset(self, preset_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM clip_presets WHERE id = ?", (preset_id,))
            self._conn.commit()
        return cursor.rowcount > 0

    def reorder_clip_presets(self, preset_ids: list) -> int:
        """渡された順にpositionを振り直す。listに無い行は後ろへ回す。"""
        with self._lock:
            known = {row["id"] for row in self._conn.execute("SELECT id FROM clip_presets")}
            ordered = [pid for pid in preset_ids if pid in known]
            rest = [pid for pid in sorted(known) if pid not in ordered]
            for position, preset_id in enumerate([*ordered, *rest]):
                self._conn.execute(
                    "UPDATE clip_presets SET position = ? WHERE id = ?", (position, preset_id))
            self._conn.commit()
        return len(ordered)
