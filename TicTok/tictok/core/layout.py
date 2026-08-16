"""録画ファイルの配信者別レイアウト解決。

録画は record root 直下に配信者フォルダを作り、その中を用途別に分ける:

    <root>/<streamer>/ts/<stem>/seg*.ts   ... HLSセグメント(セッションフォルダ)
    <root>/<streamer>/mp4/<stem>.mp4      ... 完成mp4と焼き込み(<stem>.overlay.mp4)・高画質化(<stem>.up.mp4)

    <root>/<streamer>/_clips/                ... 切り出し・reel・作品(動画の成果物)
    <root>/<streamer>/_screenshots/          ... スクショ・shortの表紙(静止画の成果物)

stem は ``NNNNN_<streamer>_YYYYMMDD_HHMMSS`` で、<streamer> は録画時の unique_id と一致する。

root 直下のfileは3種類あり、解決の基準が違う:

  録画ごとのartifact (.sidecars/) は ``record_root_of`` — mp4と同じrootに置き、
  mp4がfinal dirへ移送されれば一緒に移る。

  録画横断のpool (avatars/, emotes/, gift_icons/) は ``pool_root`` — mp4の位置とは無関係に
  work root ただ1つに置く。書き込むのは収集時のcollector(AvatarPool/GiftIconCache)で、
  そこはwork root固定であり、mp4の現在地では解決できない。

  切り出し成果物 (<streamer>/_clips/) は ``clip_output_dir`` — **作る先は常にwork root**で、
  録画の現在地では決めない。最終保存先へ運ぶのは「最終保存先へ移動」だけである
  (``tictok.api.disk``)。録画の位置で出力先を決めていた頃は、同じ操作の成果物が録画ごとに
  別のdriveへ出て、出来上がったfileの在り処が人には辿れなかった。

  静止画 (<streamer>/_screenshots/) は ``still_output_dir`` — 決め方は切り出しと同じ
  (work root固定・配信者folderの下)で、置き場だけを分ける。数百本の切り出しmp4に1枚ずつ
  pngが混ざると、探しているのがどちらでも目的の物に辿り着けない。分けても一覧・移動・容量は
  両方を見る(``iter_clip_dirs``)ので、画面から辿る口は1つのままである。
"""
import os
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


# session dir に置かれる録画実体のfile名。``seg*.ts`` は配信から刻まれたそのままの
# segment、``pack*.ts`` は解像度の切れ目ごとに束ね直したもの(tictok.record.hls_pack)。
# 「この録画に素材があるか」の判定は必ずここを通す: 束ね済みの録画をseg*.tsだけで見ると
# 素材が無いと誤判定し、再mp4化が拒否され、retentionはmp4を最後の1本と誤認する。
MEDIA_GLOBS = ("seg*.ts", "pack*.ts")


def media_files(session_dir) -> list:
    """その session dir に在る録画実体(.ts)。順序はglobごとに名前順。"""
    session_dir = Path(session_dir)
    found: list = []
    for pattern in MEDIA_GLOBS:
        found.extend(sorted(session_dir.glob(pattern)))
    return found


def has_media(session_dir) -> bool:
    """その session dir に録画実体が1本でも在るか。"""
    session_dir = Path(session_dir)
    return any(next(session_dir.glob(pattern), None) is not None for pattern in MEDIA_GLOBS)


# captureが書くHLS再生list。segmentの山だけではEXTINF順が分からず、再生も再構成もできない。
PLAYLIST_NAME = "index.m3u8"


def has_playable_media(session_dir) -> bool:
    """その session dir から再生・再構成ができるか(素材と再生listの両方が在る)。

    「素材が在るか」(``has_media``)と分けて持つ。再生経路がHLSになるかはこちらで決まり、
    再生経路は**時間軸**を決める(HLSはplaylistのEXTINF累積=media軸、mp4はPTS軸)。軸を
    決める側と再生を決める側が違う条件を見ると、検索hitの秒だけが別の軸に載る。"""
    session_dir = Path(session_dir)
    return has_media(session_dir) and (session_dir / PLAYLIST_NAME).is_file()


def mp4_dir(root, stem, streamer=None) -> Path:
    """この録画の mp4・overlay・up.mp4 を置くディレクトリ。"""
    root = Path(root)
    s = streamer or streamer_of(stem)
    return root / s / MP4_DIRNAME if s else root


def mp4_path(root, stem, streamer=None) -> Path:
    """この録画の完成 mp4 パス。"""
    return mp4_dir(root, stem, streamer) / f"{stem}.mp4"


CLIPS_DIRNAME = "_clips"
# 静止画(スクショ・shortの表紙)の置き場。切り出しと同じ規約で並ぶが、dirは分ける — 動画の
# 成果物とpngが同じdirに積み上がると、file名の規約(``_shot``)を知らない限りどちらも探せない。
STILLS_DIRNAME = "_screenshots"

# 成果物の置き場のdir名。一覧・移動・容量・片付けは**必ずこの両方**を見る。片方だけを見る
# 経路があると、そこからだけ静止画が消える(画面に並ばない・最終保存先へ随伴しない)。
ARTIFACT_DIRNAMES = (CLIPS_DIRNAME, STILLS_DIRNAME)

# root直下に置かれる、配信者folderではないdir。成果物のdir名が入っているのは、配信者を読み
# 取れないstemから出た成果物の受け皿(下記 ``clips_dir``)と、配信者folderの下へ移す前の
# 旧規約(``<root>/_clips/<配信者>/``)の実体が root直下にも在り得るためである。
NON_STREAMER_DIRS = {".sidecars", "avatars", "emotes", "gift_icons", "_backup",
                     *ARTIFACT_DIRNAMES}


def _artifact_dir(root, streamer, dirname: str) -> Path:
    """成果物の置き場。**配信者folderの下**(``<root>/<配信者>/<dirname>``)。

    録画(``ts``/``mp4``)と同じ配信者folderの中に置く。配信者ごとの片付け — folderごと消す・
    別driveへ移す・容量を見る — が、録画と成果物で別の場所を指さずに済む。

    ``streamer`` が読めないとき(規約外のstem)だけ root直下へ落とす。録画自体も同じ条件で
    root直下へ落ちる(``mp4_dir``)ので、決め方を揃える。"""
    root = Path(root)
    return root / streamer / dirname if streamer else root / dirname


def clips_dir(root, streamer=None) -> Path:
    """切り出し・reel・作品(動画)の置き場(``<root>/<配信者>/_clips``)。

    rootを引数で取るのは、**在るものを数える側**(一覧・移動先の算出)が両rootを見るため。
    新しく作る側は必ず :func:`clip_output_dir` を通す。"""
    return _artifact_dir(root, streamer, CLIPS_DIRNAME)


def stills_dir(root, streamer=None) -> Path:
    """スクショ・shortの表紙(静止画)の置き場(``<root>/<配信者>/_screenshots``)。

    決め方は :func:`clips_dir` と同じで、dirだけが違う。新しく作る側は必ず
    :func:`still_output_dir` を通す。"""
    return _artifact_dir(root, streamer, STILLS_DIRNAME)


def clip_output_dir(streamer=None) -> Path:
    """切り出し・reel・作品を**作る**先。常に一時保存先(work root)。

    録画がどちらのrootに在るかでは決めない。決めていた頃は、同じ「切り出す」操作でも
    録画の所在によって成果物がwork rootとfinal rootへ分かれ、file systemだけが台帳である
    以上、人は自分が作った物の在り処を知る手段を持たなかった。作る場所を1つに固定すれば
    「作った物はここに在る」が常に成り立ち、最終保存先へ運ぶかどうかは移動の操作が決める。
    """
    return clips_dir(work_root(), streamer)


def still_output_dir(streamer=None) -> Path:
    """静止画(スクショ・shortの表紙)を**作る**先。常に一時保存先(work root)。

    root の決め方は :func:`clip_output_dir` と同じ理由で work root 固定である。"""
    return stills_dir(work_root(), streamer)


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
    """その録画のartifact(.sidecars)を解決するための record root。

    入れ子レイアウト(<root>/<streamer>/{ts,mp4}/...)なら root を、
    そうでなければ(規約外・フラット)親ディレクトリを返す。

    録画横断のpool(avatars/emotes/gift_icons)には使わない。移送後のmp4に対しては
    final dir が返るが、poolはwork rootにしか存在しない(``pool_root``)。"""
    p = Path(path)
    parent = p.parent
    if parent.name in (TS_DIRNAME, MP4_DIRNAME):
        return parent.parent.parent
    return parent


_record_roots: list | None = None


def record_roots() -> list:
    """録画の実体を探す root の一覧(work root と final root)。先頭が work。

    録画は work root で生まれ、完成すると final root へ移送される。移送は素材とmp4を
    まとめて動かすが、途中で失敗すると**片方だけが移る**。実測でDBの331件中28件が
    その状態にあり、mp4のrootから素材を探す限りその28件は素材が無いことになっていた
    (mp4が原本だった頃は成果物が残るので露見しにくかったが、素材が原本になった今は
    録画が丸ごと見えないことを意味する)。

    ``pool_root`` と同じで、serverは起動時に自分が解決した値を渡す。単体で走る
    maintenance scriptにはそれが無いので、その場合だけDB設定から同じ順序で辿る。"""
    global _record_roots
    if _record_roots is None:
        db = config.get_db_path()
        work = Path(config.record_dir_from_db(db)).resolve()
        final = Path(config.final_record_dir_from_db(db)).resolve()
        _record_roots = [work] if work == final else [work, final]
    return _record_roots


def set_record_roots(roots) -> None:
    """探索するrootを明示指定する。serverが自分の RECORD_DIR / FINAL_DIR を渡す。"""
    global _record_roots
    seen: list = []
    for root in roots:
        resolved = Path(root).resolve()
        if resolved not in seen:
            seen.append(resolved)
    _record_roots = seen


def reset_record_roots() -> None:
    """``record_roots`` のcacheを捨てる。設定を差し替えるtestが使う。"""
    global _record_roots
    _record_roots = None


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


def work_root() -> Path:
    """録画が生まれるroot(一時保存先) = serverの RECORD_DIR。

    値は ``pool_root`` と同じだが、意味が違うので名前を分ける。あちらは「録画横断のpoolを
    置く場所」で、こちらは「録画も切り出しもまずここに出来る場所」である。解決の経路まで
    分けると、片方だけがDB設定を見るような食い違いが生まれる。"""
    return pool_root()


def iter_clip_dirs(root):
    """``root`` に実在する成果物の置き場(``_clips`` と ``_screenshots``)を辿る。

    置き場は配信者ごとに分かれた(``<root>/<配信者>/_clips``)ので、rootの下に1つではない。
    root直下の ``_clips`` / ``_screenshots`` も在れば返す — 配信者を読み取れない成果物の
    受け皿であり、配信者folderの下へ移す前の実体もそこに在る。

    動画と静止画で置き場は分かれたが、辿る側は分けない。一覧も移動も容量も「その配信者が
    作った物」を丸ごと相手にするので、ここで両方を返しておけば下流は置き場の数を知らずに
    済む(知る必要が出た経路だけが、静止画を取りこぼす)。"""
    root = Path(root)
    if not root.is_dir():
        return
    for dirname in ARTIFACT_DIRNAMES:
        shared = root / dirname
        if shared.is_dir():
            yield shared
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in NON_STREAMER_DIRS:
            continue
        for dirname in ARTIFACT_DIRNAMES:
            found = entry / dirname
            if found.is_dir():
                yield found


def clip_streamer_of(root, path):
    """成果物のpathから、**置き場が名乗る**配信者を返す。読めなければ None。

    file名からは読まない(名前が規約外でも置き場は配信者別である)。旧規約
    ``<root>/_clips/<配信者>/`` も読めるようにしてある — 移し損ねた実体を、持ち主不明として
    扱わないため。"""
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        return None
    if len(parts) > 2:
        if parts[1] in ARTIFACT_DIRNAMES:
            return parts[0]
        if parts[0] in ARTIFACT_DIRNAMES:
            return parts[1]
    return None


def is_clip_path(root, path) -> bool:
    """``path`` が ``root`` の成果物の置き場(``_clips`` / ``_screenshots``)の下に在るか。

    client由来の名前を実pathへ解いた後の照合に使う。rootの下に居ることだけを確かめると、
    同じrootに在る録画本体(``<配信者>/mp4/``)まで名前指定で配信・削除できてしまう。"""
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        return False
    return any(part in ARTIFACT_DIRNAMES for part in parts[:2])


def iter_clip_files(root):
    """``root`` の成果物の置き場に在るfileのpathを辿る。

    先頭が ``.`` のdirは入らない。そこに在るのは切り出し中の中間(``.clip_``/``.short_``等)と
    作品のシーンcache(``.scenes``)で、どちらも成果物ではない — 中間は落ちた回の残骸、cacheは
    次の焼き直しを速くするためだけの物なので、移動にも一覧にも載せない。"""
    for base in iter_clip_dirs(root):
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            here = Path(dirpath)
            for name in filenames:
                yield here / name


def avatar_pool_dir() -> Path:
    """capture時に保存したuser avatarのpool(``<work root>/avatars/by-id``)。"""
    return pool_root() / AVATAR_POOL_DIRNAME / "by-id"


def emote_pool_dir() -> Path:
    """downloadしたcustom emote画像のpool。"""
    return pool_root() / EMOTE_POOL_DIRNAME


def gift_icon_pool_dir() -> Path:
    """capture時に保存したgift iconのpool。"""
    return pool_root() / GIFT_ICON_POOL_DIRNAME
