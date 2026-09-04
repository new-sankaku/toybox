"""最終保存先(二次保存)を2系統で同じ内容に保つための複製と突き合わせ。

二次保存先が2つあるのは**振り分けではなく相互mirror**である。1台のdiskが壊れても二次保存の
dataが残るようにするためのもので、両系統は常に同じ内容でなければならない。したがってこの
moduleは「どちらへ書くか」を選ばない。行うのは**全系統へ書く**か、1つでも書けないなら
**何も動かさない**かのどちらかだけである。片側だけが最新という状態は、次の障害で気付かない
ままdataを失う唯一の経路であり、それを作らないことがこの機能の全部である。

移送(``tictok.api.disk``)がここを使う順序は「全系統へcopy → 検証 → 元を消す」で固定する。
1系統目へmoveしてから2系統目へcopyすると、2系統目で失敗した時点で元がもう無い。copyを先に
済ませておけば、どこで失敗しても元は手元に残っている。

**検証はfileごとのsizeと本数の一致だけで、内容のhashは取らない。** 理由は2つある。1つは費用の
構造で、hashを取るとは書いた物を全部読み直すことであり、**複製にかかった時間をもう一度払う**
ことになる(2系統なら「読み1・書き2」に「読み2」が乗る)。対象の量は実測(2026-09-02)で
最終保存先1 ``K:\\80_Tiktok`` が 12,340 file / 0.59TB である。

もう1つの理由の方が重い: それで捕まえられるのは「書き込みが成功を返したのに内容だけが違う」
場合だけである。ここで実際に起きた失敗はdriveがbusから落ちる類で、それはerrorか短いfileとして
現れ、fsync後のsize照合で捕まる。sizeの照合が根拠になるのは :func:`copy_file` が fsync を
済ませてから測るからで、OSのcacheではなくdiskへ着いた実体を見ている ——
``Recorder._move_session_dir`` が「元を消してよい」の根拠にしているのと同じ判断である。同じ
証拠で元を消している経路が既に在る以上、こちらだけ別の基準を持つ理由が無い。
"""

import logging
import os
import shutil
from pathlib import Path

from tictok.core import layout
from tictok.record.recorder import _copy_durable, relocatable_artifact_paths

logger = logging.getLogger("tictok.mirror")

# 再同期で突き合わせないroot直下のdir。
#   avatars / emotes / gift_icons … 録画横断のpoolで、置き場はwork rootただ1つである
#     (``layout.pool_root``)。最終保存先に在るとすればdriveを丸ごと写した頃の名残で、
#     二次保存のdataではない。片方へ複製しても誰も読まない。
#   _backup … 刈り取り前提の退避で、二次保存すべき実体そのものではない(実測307GB)。
#     ここを混ぜると、消してよい物を消せない場所へもう1部増やすことになる。
SKIP_ROOT_DIRS = frozenset({
    layout.AVATAR_POOL_DIRNAME, layout.EMOTE_POOL_DIRNAME, layout.GIFT_ICON_POOL_DIRNAME,
    "_backup",
})


def copy_file(src: Path, dst: Path) -> int:
    """1 fileを複製し、着いたsizeを確かめてbytes数を返す。

    fsyncまでするcopyは ``Recorder`` が既に持っているのでそれを使う。二重に持つと、片方だけが
    fsyncを落としたときに「着いた」の意味が経路によって変わる。

    失敗したときは書きかけのdstを消してから送出する。書きかけを残すと、両系統に同名で
    sizeの違うfileが在る状態 —— 人の判断を待つべき「食い違い」として再同期に現れる状態 ——
    を、こちらの失敗で作り出すことになる。
    """
    expected = src.stat().st_size
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        _copy_durable(src, dst)
        arrived = dst.stat().st_size
    except OSError:
        _discard(dst)
        raise
    if arrived != expected:
        _discard(dst)
        raise OSError(f"{dst} のsizeが一致しません（{arrived} bytes / 元は {expected} bytes）")
    return expected


def _discard(path: Path) -> None:
    """書きかけのfileを消す。消せなければlogに残すだけで、元の失敗を隠さない。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "複製に失敗した %s を消せませんでした", path,
            extra={"event": "mirror.discard_failed", "ctx": {"path": str(path)}},
            exc_info=True,
        )


def recording_pairs(src_mp4: Path, dst_mp4: Path) -> list:
    """1録画の実体すべてを ``(移送元, 移送先)`` の組で並べる。

    並びは素材(.ts) → mp4 → 派生file。``Recorder._move_recording_files`` と同じ順序で、
    理由も同じである: 素材は大きく遅い側で、diskが埋まる・I/Oが落ちるといった失敗が実際に
    起きるのはそこなので、先に通す。

    在るものだけを返す。mp4はfinalizeがもう作らないので多くの録画で存在せず、派生fileも
    録画ごとに有無が違う。
    """
    stem = src_mp4.stem
    src_dir = layout.session_dir(layout.record_root_of(src_mp4), stem)
    dst_dir = layout.session_dir(layout.record_root_of(dst_mp4), stem)
    pairs: list = []
    if src_dir.is_dir() and src_dir != dst_dir:
        for path in sorted(src_dir.iterdir()):
            if path.is_file():
                pairs.append((path, dst_dir / path.name))
    if src_mp4.is_file():
        pairs.append((src_mp4, dst_mp4))
    for src_path, dst_path in zip(relocatable_artifact_paths(src_mp4),
                                  relocatable_artifact_paths(dst_mp4)):
        if src_path.is_file():
            pairs.append((src_path, dst_path))
    return pairs


def copy_recording_files(src_mp4: Path, dst_mp4: Path) -> tuple:
    """1録画の実体すべて(素材・mp4・派生file)を移送先のrootへ複製する。

    戻り値は ``(本数, bytes)``。1つでも失敗したら、**このrootへ書いた分を消してから**
    OSErrorを送出する。書けた分を残すと、その録画だけが片系統に在る状態になり、mirrorの
    前提(両系統は常に同じ)がその1本について崩れる。元はまだ消していないので、消して失う物は
    無い —— これが「copyを先に全部済ませる」順序を採った理由でもある。

    派生file(``.timing.json``・サムネ・波形など)も必須として扱う。単系統の移送
    (``Recorder._move_recording_files``)は派生fileの失敗を致命的でないものとして飛ばすが、
    2系統では飛ばせない: 飛ばした瞬間に両系統の内容が食い違い、しかもそれを人が知る手段は
    再同期の突き合わせだけになる。作り直せる物であっても、食い違いは食い違いである。
    """
    written: list = []
    files = 0
    total = 0
    try:
        for src, dst in recording_pairs(src_mp4, dst_mp4):
            written.append(dst)
            total += copy_file(src, dst)
            files += 1
    except OSError:
        undo(written)
        raise
    return files, total


def undo(paths) -> list:
    """複製の途中で失敗したときに、書いてしまった物を消す。消せなかったpathを返す。

    空になったdirも畳む。素材のsession dirが空のまま残ると、``layout.has_media`` では
    「素材なし」でも人の目には移送済みに見え、次に見る人の判断を狂わせる。
    """
    stuck: list = []
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            stuck.append(path)
    for parent in {path.parent for path in paths}:
        try:
            parent.rmdir()
        except OSError:
            # 空でない(他の録画のfileが同居している)dirはそのまま残す。
            pass
    if stuck:
        logger.warning(
            "複製の巻き戻しで %d件のfileを消せませんでした", len(stuck),
            extra={"event": "mirror.rollback_failed",
                   "ctx": {"paths": [str(path) for path in stuck[:5]],
                           "count": len(stuck)}},
        )
    return stuck


def remove_recording_files(mp4: Path) -> tuple:
    """全系統へ複製し終えた録画の**元**を消す。戻り値は ``(消した本数, 消せなかったpath)``。

    呼んでよいのは :func:`copy_recording_files` が全系統で成功した後だけである。

    消せないfileが在っても例外にしない。その時点で二次保存は全系統に揃っており、移送は
    成立している —— ここで失敗を名乗ると、実体が両系統に在るのに「移送できなかった」と
    報告することになり、次の実行が「退避先に同名が既にある」で止まる。残ったのは元の側の
    余りなので、pathを返して報告に載せる。
    """
    stem = mp4.stem
    session = layout.session_dir(layout.record_root_of(mp4), stem)
    removed = 0
    stuck: list = []
    if session.is_dir():
        removed += sum(1 for path in session.iterdir() if path.is_file())
        shutil.rmtree(session, ignore_errors=True)
        if session.is_dir():
            stuck.append(session)
            removed = 0
    for path in [mp4, *relocatable_artifact_paths(mp4)]:
        if not path.is_file():
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            stuck.append(path)
    if stuck:
        logger.warning(
            "全系統へ複製した %s の元を %d件消せませんでした", mp4.name, len(stuck),
            extra={"event": "recording.mirror_source_kept",
                   "ctx": {"stem": stem, "paths": [str(path) for path in stuck[:5]],
                           "count": len(stuck)}},
        )
    return removed, stuck


def compare_roots(roots) -> dict:
    """全系統を突き合わせ、片方に欠けているfileと、同名でsizeの違うfileを返す。

    戻り値は ``{"groups": [...], "diverged": [...], "errors": [...]}``。``groups`` の1件は
    「あるdirの、ある向き(src -> dst)へ複製するfileの束」である。

    dir単位で降りるのは、**比べる相手が同じdirの中にしか居ない**からである。突き合わせるのは
    rootからの相対pathが同じfileどうしなので、1つのdirを両rootで読んだ時点でそのdirの答えは
    確定する。先に両rootの全一覧を作ってから比べても結果は同じで、走査の費用も同じ(どのみち
    全dirをscandirする)まま、作り終えるまで何も分からない時間が増えるだけである。dirで区切って
    いるおかげで、束ねた1件がそのまま実行の単位(複製の向きが同じfileの束)と進捗の単位になる。

    memoryは理由にならない。実測(2026-09-02)で最終保存先1 ``K:\\80_Tiktok`` は 12,340 file /
    0.59TB で、rootごとに一覧をdictで持っても数MBである —— **今の規模ならdictでも持てる**。
    dir単位にしたのは上の理由による選択であって、memoryに迫られた必要ではない。それでもfile数に
    比例する持ち方を選ばないのは、比例する持ち方は増えるほど成り立たなくなるからで、走査の費用は
    どちらでも同じである以上、選ばない側に費用が無い。

    欠けているfileをdir単位で束ねるのは応答の大きさのため。file単位で返すと、初回の再同期
    (片方が空)の応答は実測の 12,340 file がそのまま並ぶ明細になる。

    同名でsizeが違うfileは**複製しない**。どちらが正しいかはここでは決められず(新しい方が
    正しいとは限らない — 途中で切れた書き込みの方が新しいこともある)、上書きは取り返しが
    つかない。件数と実例を返し、人が判断する。
    """
    roots = [Path(root) for root in roots]
    groups: list = []
    diverged: list = []
    errors: list = []
    pending: list = [()]
    while pending:
        rel = pending.pop()
        sizes_by_name: dict = {}
        subdirs: set = set()
        for index, root in enumerate(roots):
            here = root.joinpath(*rel)
            try:
                entries = list(os.scandir(here))
            except FileNotFoundError:
                # その系統にこのdirがまだ無いだけ。中身は「全部欠けている」として下で出る。
                continue
            except OSError as exc:
                errors.append({"path": str(here), "error": str(exc)})
                logger.warning(
                    "再同期の突き合わせで %s を読めませんでした", here,
                    extra={"event": "mirror.scan_failed", "ctx": {"path": str(here)}},
                    exc_info=True,
                )
                continue
            for entry in entries:
                try:
                    if entry.is_dir():
                        if not rel and entry.name in SKIP_ROOT_DIRS:
                            continue
                        subdirs.add(entry.name)
                    elif entry.is_file():
                        sizes_by_name.setdefault(entry.name, {})[index] = entry.stat().st_size
                except OSError as exc:
                    errors.append({"path": entry.path, "error": str(exc)})
        for name in sorted(subdirs):
            pending.append((*rel, name))
        missing: dict = {}
        for name in sorted(sizes_by_name):
            sizes = sizes_by_name[name]
            if len(sizes) == len(roots):
                if len(set(sizes.values())) > 1:
                    diverged.append({
                        "rel": "/".join((*rel, name)),
                        "sizes": {str(roots[index]): size for index, size in sorted(sizes.items())},
                    })
                continue
            # 在る方のうち先頭(設定順)を写す元にする。順序に意味があるのは読み出しだけなので、
            # どれを元にしても結果は同じ —— 決め方を固定して、実行ごとに変わらないようにする。
            src_index = min(sizes)
            for index in range(len(roots)):
                if index not in sizes:
                    missing.setdefault((src_index, index), []).append((name, sizes[src_index]))
        for (src_index, dst_index), entries in sorted(missing.items()):
            groups.append({
                "rel": "/".join(rel),
                "src": str(roots[src_index]),
                "dst": str(roots[dst_index]),
                "files": [name for name, _size in entries],
                "count": len(entries),
                "bytes": sum(size for _name, size in entries),
            })
    groups.sort(key=lambda group: (group["dst"], group["rel"]))
    return {"groups": groups, "diverged": diverged, "errors": errors}
