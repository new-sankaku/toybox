"""録画ファイルの配信者別レイアウト解決。

録画は record root 直下に配信者フォルダを作り、その中を用途別に分ける:

    <root>/<streamer>/ts/<stem>/seg*.ts   ... HLSセグメント(セッションフォルダ)
    <root>/<streamer>/mp4/<stem>.mp4      ... 完成mp4と焼き込み(<stem>.overlay.mp4)・高画質化(<stem>.up.mp4)

stem は ``NNNNN_<streamer>_YYYYMMDD_HHMMSS`` で、<streamer> は録画時の unique_id と一致する。
avatars/emotes/gift_icons/.sidecars は従来どおり root 直下に置き、mp4 の位置ではなく
``record_root_of`` が返す root を基準に解決する。
"""
import re
from pathlib import Path

TS_DIRNAME = "ts"
MP4_DIRNAME = "mp4"

# 現行命名: 先頭session prefix(数字)＋中間の配信者(unique_id)＋末尾の日時2トークン。
# 配信者名自体が '_' や '.' を含むため単純splitではなくこの区切りで切り出す。
_STEM_RE = re.compile(r"^\d+_(?P<streamer>.+)_\d{8}_\d{6}$")
# 旧命名(session prefix なし): 配信者＋末尾の日時2トークン。現行命名も末尾一致する
# ため、必ず現行命名(_STEM_RE)を先に試し、外れた場合のみこちらを使う。
_LEGACY_STEM_RE = re.compile(r"^(?P<streamer>.+)_\d{8}_\d{6}$")


# artifact名は stem の後ろに多段のsuffix(.overlay.b.ass / .up.ffmpeg.log 等)が付くため、
# 末尾一致の _STEM_RE では拾えない。先頭から stem 部分だけを切り出して使う。
_ARTIFACT_RE = re.compile(r"^(?P<stem>\d+_(?P<streamer>.+?)_\d{8}_\d{6})(?=\.|$)")
_LEGACY_ARTIFACT_RE = re.compile(r"^(?P<stem>(?P<streamer>.+?)_\d{8}_\d{6})(?=\.|$)")


def streamer_of(stem: str):
    """stem から配信者(unique_id)を取り出す。規約に合わなければ None。"""
    name = Path(stem).name
    m = _STEM_RE.match(name) or _LEGACY_STEM_RE.match(name)
    return m.group("streamer") if m else None


def artifact_owner(name: str):
    """sidecar等のartifact file名から (stem, 配信者) を取り出す。規約外なら (None, None)。

    ``00042_user_20250101_120000.overlay.b.ass`` のように stem の後ろへ複数のsuffixが
    連なるため、``streamer_of`` の末尾一致では判定できない。容量内訳の配信者別集計が
    共有cacheと録画artifactを取り違えないために使う。"""
    base = Path(name).name
    m = _ARTIFACT_RE.match(base) or _LEGACY_ARTIFACT_RE.match(base)
    return (m.group("stem"), m.group("streamer")) if m else (None, None)


def session_dir(root, stem, streamer=None) -> Path:
    """この録画の HLS seg*.ts を保持するセッションディレクトリ。"""
    root = Path(root)
    s = streamer or streamer_of(stem)
    return root / s / TS_DIRNAME / stem if s else root / stem


def mp4_dir(root, stem, streamer=None) -> Path:
    """この録画の mp4・overlay・up.mp4 を置くディレクトリ。"""
    root = Path(root)
    s = streamer or streamer_of(stem)
    return root / s / MP4_DIRNAME if s else root


def mp4_path(root, stem, streamer=None) -> Path:
    """この録画の完成 mp4 パス。"""
    return mp4_dir(root, stem, streamer) / f"{stem}.mp4"


CLIPS_DIRNAME = "_clips"

NON_STREAMER_DIRS = {".sidecars", "avatars", "emotes", "gift_icons", "_backup", CLIPS_DIRNAME}


def clips_dir(root, streamer=None) -> Path:
    """切り出しクリップの置き場。root 直下の共有領域で、配信者フォルダとは区別される
    (iter_sessions は NON_STREAMER_DIRS として読み飛ばす)。"""
    root = Path(root) / CLIPS_DIRNAME
    return root / streamer if streamer else root


def iter_sessions(root):
    """Yield each recording's HLS session directory (<root>/<streamer>/ts/<stem>) under
    a record root, walking the per-streamer layout. Root-level shared caches are skipped.
    The paired mp4 is ``mp4_path(root, session_dir.name)``."""
    root = Path(root)
    if not root.is_dir():
        return
    for streamer in sorted(root.iterdir()):
        if not streamer.is_dir() or streamer.name in NON_STREAMER_DIRS:
            continue
        ts_root = streamer / TS_DIRNAME
        if not ts_root.is_dir():
            continue
        for session in sorted(ts_root.iterdir()):
            if session.is_dir():
                yield session


def record_root_of(path) -> Path:
    """root 直下の共有リソース(avatars/emotes/gift_icons/.sidecars)を解決するための record root。

    入れ子レイアウト(<root>/<streamer>/{ts,mp4}/...)なら root を、
    そうでなければ(規約外・フラット)親ディレクトリを返す。"""
    p = Path(path)
    parent = p.parent
    if parent.name in (TS_DIRNAME, MP4_DIRNAME):
        return parent.parent.parent
    return parent
