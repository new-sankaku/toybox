"""録画ファイルの配信者別レイアウト解決。

録画は record root 直下に配信者フォルダを作り、その中を用途別に分ける:

    <root>/<streamer>/ts/<stem>/seg*.ts   ... HLSセグメント(セッションフォルダ)
    <root>/<streamer>/mp4/<stem>.mp4      ... 完成mp4と焼き込み(<stem>.overlay.mp4)・高画質化(<stem>.up.mp4)

stem は ``NNNNN_<streamer>_YYYYMMDD_HHMMSS`` で、<streamer> は録画時の unique_id と一致する。

root 直下のfileは2種類あり、解決の基準が違う:

  録画ごとのartifact (.sidecars/, _clips/) は ``record_root_of`` — mp4と同じrootに置き、
  mp4がfinal dirへ移送されれば一緒に移る。

  録画横断のpool (avatars/, emotes/, gift_icons/) は ``pool_root`` — mp4の位置とは無関係に
  work root ただ1つに置く。書き込むのは収集時のcollector(AvatarPool/GiftIconCache)で、
  そこはwork root固定であり、mp4の現在地では解決できない。
"""
import re
from pathlib import Path

from tictok.core import config

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
    """その録画のartifact(.sidecars/_clips)を解決するための record root。

    入れ子レイアウト(<root>/<streamer>/{ts,mp4}/...)なら root を、
    そうでなければ(規約外・フラット)親ディレクトリを返す。

    録画横断のpool(avatars/emotes/gift_icons)には使わない。移送後のmp4に対しては
    final dir が返るが、poolはwork rootにしか存在しない(``pool_root``)。"""
    p = Path(path)
    parent = p.parent
    if parent.name in (TS_DIRNAME, MP4_DIRNAME):
        return parent.parent.parent
    return parent


AVATAR_POOL_DIRNAME = "avatars"
EMOTE_POOL_DIRNAME = "emotes"
GIFT_ICON_POOL_DIRNAME = "gift_icons"

_pool_root: Path | None = None


def pool_root() -> Path:
    """録画横断のpool(avatars/emotes/gift_icons)を置く単一のroot = work record dir。

    poolを書くのは収集時のcollectorで、書き込み先はwork record dir固定。読む側が
    ``record_root_of(src)`` で解くと、final dirへ移送された録画だけが存在しないpoolを
    見に行き、avatarもemoteも1件も解決できない(署名付きCDN URLは期限切れで再取得もできず、
    黙ってイニシャル円盤へ縮退する)。読み書きの基準をここへ一本化する。

    server processでは起動時に ``set_pool_root(RECORD_DIR)`` が入る(serverが解決した値と
    ずれないよう、推測ではなく実物を受け取る)。単体で走るmaintenance scriptにはそれが無いので、
    その場合だけ ``config.record_dir_from_db`` で同じ順序(DB設定 > 環境変数 > 既定)を辿る。"""
    global _pool_root
    if _pool_root is None:
        _pool_root = Path(config.record_dir_from_db(config.get_db_path())).resolve()
    return _pool_root


def set_pool_root(root) -> None:
    """poolのrootを明示指定する。serverが自分の RECORD_DIR を渡すために使う。"""
    global _pool_root
    _pool_root = Path(root).resolve()


def reset_pool_root() -> None:
    """``pool_root`` のcacheを捨てる。設定を差し替えるtestが使う。"""
    global _pool_root
    _pool_root = None


def avatar_pool_dir() -> Path:
    """capture時に保存したuser avatarのpool(``<work root>/avatars/by-id``)。"""
    return pool_root() / AVATAR_POOL_DIRNAME / "by-id"


def emote_pool_dir() -> Path:
    """downloadしたcustom emote画像のpool。"""
    return pool_root() / EMOTE_POOL_DIRNAME


def gift_icon_pool_dir() -> Path:
    """capture時に保存したgift iconのpool。"""
    return pool_root() / GIFT_ICON_POOL_DIRNAME
