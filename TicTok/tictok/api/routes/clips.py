"""切り出し成果物(``_clips`` / ``_screenshots``)の一覧・再生・削除。

並ぶのは切り出したmp4と、再生画面から撮ったスクショ(png)と、切り抜きへ添えた字幕file
(srt/vtt/ass — :mod:`tictok.media.clip_subtitles`)である。いずれもDBに行を持たない。
台帳はfile systemそのもので、動画は ``<root>/<配信者>/_clips/``、静止画は
``<root>/<配信者>/_screenshots/`` に置かれる(``tictok.core.layout.clips_dir`` /
``stills_dir``)。置き場は分かれても一覧は1つで、辿るのは ``layout.iter_clip_dirs`` が返す
置き場すべてである。**作る先は常に一時保存先**であり
(``layout.clip_output_dir``)、最終保存先へ移るのは容量画面の「最終保存先へ移動」で録画に
随伴したときだけである。したがってここは今も両rootを見る: 一時保存先には新しく作った物、
最終保存先には録画ごと移し終えた物が在る。画面から辿る口が無い間、利用者は出来上がったfileの
在り処を知る手段を持たなかった(単発の切り出しが応答で返すpathだけが唯一の手掛かりで、
一括書き出しはそれすら返していなかった)。

ここが持つのは「file systemに在るものを、在るとおりに名乗る」責務だけである。範囲もラベルも
file名から読み戻す(:func:`tictok.media.clipper.parse_clip_name`)ので、読めない名前は
推測せず素性なしのまま並べる。録画への紐付けはstemの一致だけで行い、当たらなければ
``recording_id`` は付けない — 消えた録画の切り出しも成果物としては実在するので、隠さない。

削除はfile 1本ずつの明示操作に限る。保持policy(retention)へ載せていないのは、切り出しが
「人が範囲を選んで作った成果物」で、日数で自動的に捨ててよい派生物ではないためである。
"""

import asyncio
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from tictok.api import runtime
from tictok.core import layout
from tictok.media import clip_subtitles, clipper
from tictok.media.clipper import parse_clip_name
from tictok.media import work

router = APIRouter()

# 画面が指してよいroot。実pathを受け取る形にすると、client側から任意のdirを名乗れてしまう。
# 並びは ``layout.record_roots()`` と同じ(先頭がwork)。
ROOT_KEYS = ("work", "final")
ROOT_LABELS = {"work": "一時保存先", "final": "最終保存先"}

# 切り出し中の中間dir。出力と同じvolumeへ置く決まりなので置き場の中にも現れる
# (clipper._copy_clip / _smart_clip / short.make_short / work.make_work)。正常終了なら
# 消えるため、残っていれば落ちた回の残骸。
LEFTOVER_PREFIXES = (".clip_", ".smartcut-", ".precise_", ".short_", ".work_")

# 作品のシーンcache(work.SCENE_CACHE_DIR)。**残骸ではない** — 次に作り直すときに変わって
# いないシーンを焼き直さずに済ませるための、意図して残す中間である。成果物として並べも
# しない(1本の作品の材料であって、それ自体を配ったり観たりする物ではない)。
# 消えても正しさは変わらず、焼き直しの時間だけが戻る。
CACHE_DIRS = (work.SCENE_CACHE_DIR,)

# ここが成果物として並べる拡張子。スクショ(png)も字幕file(srt/vtt/ass)も同じ置き場に出る
# 成果物なので、mp4だけを見ていると「作ったのに画面から辿れない」fileが増える。
CLIP_EXTENSIONS = (".mp4", clipper.STILL_EXT, *clip_subtitles.SUBTITLE_EXTENSIONS)

# 配信するときのContent-Type。拡張子で決める(中身は見ない)。字幕fileの綴りは書き出した側
# (clip_subtitles.FORMATS)から採る — 同じ拡張子で別のtypeを名乗ると読み手が食い違う。
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    clipper.STILL_EXT: "image/png",
    **{suffix: media_type for suffix, media_type, _enc in clip_subtitles.FORMATS.values()},
}


def _roots() -> dict:
    """key -> その record root。final を持たない構成では work だけを返す。

    rootそのものを持つのは、置き場が配信者folderの下(``<root>/<配信者>/_clips``)に分かれた
    ため、rootの下に ``_clips`` は1つではないからである。成果物の名前も root からの相対で
    名乗る(``<配信者>/_clips/<file名>``)。"""
    return {key: Path(root) for key, root in zip(ROOT_KEYS, layout.record_roots())}


def _resolve(root: str, name: str) -> Path:
    """``root`` の切り出し置き場の下にあることを確かめた上で実pathを返す。

    ``name`` はclient由来なので、解決した後に必ず成果物の置き場の下に居ることを照合する
    (``..`` やdrive付きのpathを渡された場合に、root外のfileを配信・削除しないため)。
    rootの下に居ることだけでは足りない — 同じrootには録画本体(``<配信者>/mp4/``)も在る。"""
    base = _roots().get(root)
    if base is None:
        raise HTTPException(status_code=400, detail=f"未知の保存先です: {root}")
    resolved_base = base.resolve()
    target = (base / name).resolve()
    try:
        target.relative_to(resolved_base)
    except ValueError:
        raise HTTPException(status_code=400, detail="保存先の外を指すpathは扱えません。")
    if not layout.is_clip_path(resolved_base, target):
        raise HTTPException(status_code=400, detail="切り出しの置き場の外は扱えません。")
    # 扱うのは一覧に並ぶ種類のfileだけに限る。一覧に出ないfile(中間・log等)を配信・削除
    # できる口を残すと、画面から辿れない物を名前指定で消せてしまう。
    if target.suffix.lower() not in MEDIA_TYPES:
        raise HTTPException(status_code=400, detail=f"扱えない種類のfileです: {target.name}")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="この切り出しfileはもうありません。")
    return target


def _scan_root(root: str, base: Path, by_stem: dict) -> tuple:
    """1つのrootの置き場を全て走査して (成果物list, 残骸の集計, cacheの集計) を返す。

    歩くのは ``layout.iter_clip_dirs`` が返す置き場だけで、rootを丸ごとは歩かない。
    録画本体(``ts``/``mp4``)は成果物ではないうえ、数TB規模を毎回歩くことになる。

    残骸とcacheを分けて数えるのは、片方は消すべきfileで、もう片方は**消さない方が得な**
    fileだからである。同じ数字に混ぜると、画面はどちらの意味でも読めない量を出すことになる。
    """
    items: list = []
    leftovers = {"count": 0, "bytes": 0}
    cache = {"count": 0, "bytes": 0}
    for clips in layout.iter_clip_dirs(base):
        for dirpath, _dirnames, filenames in os.walk(clips):
            here = Path(dirpath)
            for name in filenames:
                path = here / name
                try:
                    stat = path.stat()
                except OSError:
                    continue
                # 名前はrootからの相対(``<配信者>/_clips/<file名>``)。置き場がrootの下に
                # 複数在るので、置き場ごとの相対では同じ名前が別のrootの別fileを指す。
                relative = path.relative_to(base)
                rel = relative.as_posix()
                parents = relative.parts[:-1]
                if any(part in CACHE_DIRS for part in parents):
                    cache["count"] += 1
                    cache["bytes"] += stat.st_size
                    continue
                if any(part.startswith(LEFTOVER_PREFIXES) for part in parents):
                    leftovers["count"] += 1
                    leftovers["bytes"] += stat.st_size
                    continue
                if not name.lower().endswith(CLIP_EXTENSIONS):
                    continue
                parsed = parse_clip_name(name) or {}
                owner = by_stem.get(parsed.get("stem") or "") or {}
                items.append({
                    "root": root,
                    "name": rel,
                    "filename": name,
                    # 配信者は置き場を先に採る。file名が規約外でも、置き場は必ず配信者別。
                    "unique_id": (layout.clip_streamer_of(base, path)
                                  or parsed.get("streamer") or ""),
                    "stem": parsed.get("stem") or "",
                    "kind": parsed.get("kind") or "unknown",
                    "start": parsed.get("start"),
                    "end": parsed.get("end"),
                    "label": parsed.get("label") or "",
                    "parts": parsed.get("parts"),
                    # 字幕fileだけが持つ書式(srt/vtt/ass)。空なら字幕fileではない。
                    "subtitle_format": parsed.get("subtitle_format") or "",
                    "recording_id": owner.get("recording_id"),
                    "recording_started_at": owner.get("started_at"),
                    "bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "path": str(path),
                    # 配信者名にもラベルにも記号・日本語が入る。組み立てた側で符号化して
                    # おく(画面側で組み直させると、片方が忘れた時だけ再生できないfileが出る)。
                    "url": f"/api/clips/file?root={root}&name={quote(rel)}",
                })
    return items, leftovers, cache


@router.get("/api/clips")
async def list_clips_api() -> dict:
    """両rootの切り出し置き場に実在する成果物を並べる。

    file systemの走査とDBの引き当てを1回のthread呼び出しへまとめる。件数ぶんの stat が
    loop上で走ると、成果物が増えるほどserverが止まる時間が伸びる。"""
    def _collect() -> dict:
        by_stem = runtime.storage.recordings_by_stem()
        roots: list = []
        items: list = []
        for key, base in _roots().items():
            found, leftovers, cache = _scan_root(key, base, by_stem)
            items.extend(found)
            roots.append({
                # pathはrootそのもの。置き場は配信者ごとに分かれた(``<root>/<配信者>/_clips``)
                # ので、この保存先を代表する1つのdirはrootしかない。
                "key": key, "label": ROOT_LABELS[key], "path": str(base),
                "exists": base.is_dir(), "count": len(found),
                "bytes": sum(item["bytes"] for item in found),
                "leftover_count": leftovers["count"], "leftover_bytes": leftovers["bytes"],
                # 作品のシーンcache。残骸と別に出すのは、消すべき物ではないからである
                # (消せば次の焼き直しが遅くなるだけで、正しさは変わらない)。
                "cache_count": cache["count"], "cache_bytes": cache["bytes"],
            })
        # 新しい順。出来上がりの確認は直前に出したものから始まる。
        items.sort(key=lambda item: item["modified_at"], reverse=True)
        return {"roots": roots, "items": items,
                "total_bytes": sum(item["bytes"] for item in items)}

    return await asyncio.to_thread(_collect)


@router.get("/api/clips/file")
async def clip_file(root: str, name: str) -> FileResponse:
    """成果物をそのまま配信する。FileResponseはRangeを解するので画面上でseekできる。"""
    path = await asyncio.to_thread(_resolve, root, name)
    return FileResponse(path, media_type=MEDIA_TYPES[path.suffix.lower()],
                        headers={"Cache-Control": "no-store"})


@router.delete("/api/clips/file")
async def delete_clip_file(root: str, name: str) -> dict:
    """成果物を1本消す。元録画にも見どころの行にも触れない(同じ範囲を出し直せる)。

    mp4を消すときは、そのmp4に添えた字幕fileも一緒に消す。字幕fileは単独では使い道が無く
    (時刻が対のmp4の軸に載っている)、残すと消えた動画の字幕だけが一覧に並び続ける。逆向き
    (字幕fileを消してもmp4は残る)は成り立つので、そちらは1本ずつのままである。
    """
    path = await asyncio.to_thread(_resolve, root, name)

    def _remove() -> tuple:
        size = path.stat().st_size
        path.unlink()
        companions: list = []
        if path.suffix.lower() == ".mp4":
            for suffix in clip_subtitles.SUBTITLE_EXTENSIONS:
                sidecar = path.with_suffix(suffix)
                if not sidecar.is_file():
                    continue
                size += sidecar.stat().st_size
                sidecar.unlink()
                companions.append(sidecar.name)
        return size, companions

    try:
        freed, sidecars = await asyncio.to_thread(_remove)
    except OSError as exc:
        runtime.logger.warning(
            "切り出しfileの削除に失敗しました: %s", path, exc_info=True,
            extra={"event": "clip.delete_failed", "ctx": {"path": str(path)}})
        raise HTTPException(status_code=500, detail=f"削除できませんでした: {exc}")
    runtime.logger.info(
        "切り出しfileを削除しました: %s", path,
        extra={"event": "clip.deleted",
               "ctx": {"path": str(path), "bytes": freed, "subtitles": sidecars}})
    return {"deleted": True, "freed_bytes": freed, "path": str(path),
            "subtitle_files": sidecars}
