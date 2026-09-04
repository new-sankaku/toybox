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

# TikTok本体から落としたhighlight(LIVE replayの切り抜き)の置き場。配信者ごとに分けるが、
# 中身は「録画の外から来た素材」なので録画folder(ts/mp4)とは別系統に置く。
HIGHLIGHT_DIRNAME = "highlights"
# 利用者が実際に使っている置き場のfolder名。**綴りはこのままにする** —— 実在するfolderの
# 名前であり、こちらの都合で直すと利用者が置いたfileを1本も見つけられなくなる。
# 正規の置き場(``HIGHLIGHT_DIRNAME``)へ移せと言う前に、在るものを在る場所で読む。
HIGHLIGHT_LEGACY_DIRNAME = "LiveHightlite"
# highlightを繋いだ成果物(gifterごとに1本)の置き場。**綴りはこのままにする** ——
# 利用者が名指しした名前であり、素材の置き場(``LiveHightlite``)の隣に並ぶことに意味がある。
# 素材と成果物を同じdirへ混ぜない: 素材はTikTokのvideo id、成果物は日付+コイン+表示名という
# 別々の名前の規約を持ち、混ざるとどちらを見ても目的の物へ辿り着けない。
MERGED_HIGHLIGHT_DIRNAME = "LiveHightlite_マージ済み"

# 成果物の置き場のdir名。一覧・移動・容量・片付けは**必ずこの全部**を見る。1つでも見落とす
# 経路があると、そこからだけ成果物が消える(画面に並ばない・最終保存先へ随伴しない)。
#
# highlightを繋いだ1本(``MERGED_HIGHLIGHT_DIRNAME``)もここに入る。素材のhighlightは**外から
# 来た物**なので置き場を分けてあるが(``HIGHLIGHT_DIRNAME`` はここに入れない)、繋いだ1本は
# 人がこのserverで作らせた成果物で、``_clips`` の切り出しと同じ種類の物である。入れないと
# ``/api/clips`` の一覧にも「最終保存先へ移動」にも出ず、容量では種別が「その他」に落ちる
# —— 数十本のmp4が、どの画面からも辿れないまま溜まることになる。
#
# 代償は、file名の規約(``parse_clip_name``)がこの出力の名前を読めないことである。一覧には
# 範囲もラベルも無い行として並ぶが、それは ``clips`` が元から持っている扱いで(読めない名前は
# 推測せず素性なしのまま並べる)、辿れないより遥かに良い。
ARTIFACT_DIRNAMES = (CLIPS_DIRNAME, STILLS_DIRNAME, MERGED_HIGHLIGHT_DIRNAME)

# テロップpresetの見本画像(``record.telop_preview``)。root直下の共有cacheで、録画とは無関係。
# 名前をここに置くのは、``NON_STREAMER_DIRS`` がこのmoduleに在り、telop_preview側が
# layoutをimportする向きだからである(逆向きにするとimportが循環する)。
TELOP_PREVIEW_DIRNAME = "telop_previews"

# 設定値の退避(``core.settings_export``)。一次保存先と全ての最終保存先の直下に置く。
CONFIG_DIRNAME = "_config"

# root直下に置かれる、配信者folderではないdir。成果物のdir名が入っているのは、配信者を読み
# 取れないstemから出た成果物の受け皿(下記 ``clips_dir``)と、配信者folderの下へ移す前の
# 旧規約(``<root>/_clips/<配信者>/``)の実体が root直下にも在り得るためである。
#
# **root直下へ新しいfolderを作るときは必ずここへ足すこと。** 落ちると2つ壊れる: 容量の内訳が
# そのfolderを配信者1人として数え(``record.disk_scan``)、``scripts/purge_streamers.py`` が
# 監視外の配信者folderとして削除の対象に入れる。実際 ``telop_previews`` は追加を落としていて、
# 両方に当てはまっていた(2026-09-02 修正)。
#
# ``HIGHLIGHT_DIRNAME`` はここに**入れない**。highlightの置き場は配信者folderの下だけで、
# root直下に ``highlights`` を作る経路はもう無い(:func:`highlight_dir`)。載せたままにすると、
# root直下も置き場の1つだと読める —— 実際には誰も書かず誰も読まない場所である。
NON_STREAMER_DIRS = {".sidecars", "avatars", "emotes", "gift_icons", "_backup",
                     TELOP_PREVIEW_DIRNAME, CONFIG_DIRNAME, *ARTIFACT_DIRNAMES}


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

# ``record_roots()`` が返すrootの名前。並びは同じで、先頭がwork。画面へ実pathを渡さずに
# 「どちらの保存先か」を名乗るための鍵で、``tictok.api.routes.clips`` のROOT_KEYSと同じ値。
RECORD_ROOT_KEYS = ("work", "final")


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


def highlight_dir(streamer) -> Path:
    """TikTok本体のhighlightを**置く**先(``<work root>/<配信者>/highlights``)。

    rootをwork root固定にするのは :func:`clip_output_dir` と同じ理由である。highlightは
    録画1本に属さない(1本のhighlightがどの録画のどこかは、突き合わせて初めて判る)ので、
    録画の所在では置き場を決められない。配信者だけが投入時に判っている手がかりになる。

    配信者folderの下に置くのは :func:`_artifact_dir` と同じ理由で、配信者ごとの片付け ——
    folderごと消す・別driveへ移す・容量を見る —— が、録画と素材で別の場所を指さずに済む
    からである。素材(``LiveHightlite``)も成果物(``LiveHightlite_マージ済み``)も同じ配信者
    folderの下に並ぶので、1人ぶんを丸ごと扱う操作が置き場の数を知らずに済む。

    **配信者が無ければ失敗させる。** 以前は :func:`_artifact_dir` の分岐で root直下
    (``<work root>/highlights``)へ落ちていたが、そこは廃止した置き場である。黙って落とすと、
    配信者を失った呼び出しが「誰も読まない場所」を指したまま進み、素材が見つからない理由が
    pathにしか現れない —— 切り出し(:func:`clips_dir`)が root直下へ落ちてよいのは、そこが
    今も走査される置き場だからで、highlightには当てはまらない。"""
    if not streamer:
        raise ValueError("highlightの置き場は配信者ごとです（配信者が空です）。")
    return _artifact_dir(pool_root(), streamer, HIGHLIGHT_DIRNAME)


def merged_highlight_dir(streamer) -> Path:
    """highlightを繋いだ成果物を**作る**先(``<work root>/<配信者>/LiveHightlite_マージ済み``)。

    rootをwork root固定にするのは :func:`clip_output_dir` と同じ理由である。**読む側**の
    :func:`highlight_dirs` が両rootを辿るのと対になっていて、作る側は場所が1つでなければ
    「自分が作った物がどこに在るか」を人が辿れない。

    素材(``LiveHightlite``)と同じ配信者folderの隣に並ぶが、dirは分ける。名前の規約が
    別物(素材はTikTokのvideo id、成果物は日付+コイン+表示名)なので、混ぜるとどちらを
    探していても目的の物に辿り着けない ―― ``_clips`` と ``_screenshots`` を分けたのと
    同じ判断である。"""
    return work_root() / streamer / MERGED_HIGHLIGHT_DIRNAME if streamer else \
        work_root() / MERGED_HIGHLIGHT_DIRNAME


def highlight_dirs(streamer) -> list:
    """その配信者のhighlightを**探す**置き場を、実在するものだけ順に返す。

    置き場は**配信者folderの下の2つだけ**で、順序は「正規の置き場 → 利用者の現行の置き場」:

    1. ``<root>/<配信者>/highlights``       … 今後の正規の置き場(:func:`highlight_dir`)
    2. ``<root>/<配信者>/LiveHightlite``    … 利用者が実際に使っている置き場

    どちらも work / final の**両rootを辿る**(:func:`record_roots`)。highlightは録画に随伴して
    最終保存先へ移り得るし、片方だけを見る経路は「在るのに見つからない」を静かに作る。

    ``<work root>/highlights/<配信者>`` (root直下)は**辿らない**。以前はそこも見ていたが、
    置き場を配信者folderの下へ一本化する判断が出たので外した。root直下の実体はPOCが作った
    合成素材だけで、実物のhighlightは1本も無い ―― 走査に残すと、その合成素材が台帳に並んで
    「TikTokから来た物」のふりをする。

    同じ置き場を2度返さない。final rootを持たない構成では ``record_roots`` が1つしか
    返さないので、そこで自然に畳まれる。

    **見つけた場所は呼び出し側が必ず持ち回ること。** 置き場が複数ある以上、一覧に並んだ
    fileがどこの物かを画面が名乗れなければ、利用者は自分が置いたfileへ戻れない
    (``tictok.api.routes.clips`` のmodule docstringと同じ約束)。"""
    found: list = []
    for dirname in (HIGHLIGHT_DIRNAME, HIGHLIGHT_LEGACY_DIRNAME):
        for root in record_roots():
            candidate = Path(root) / streamer / dirname
            if candidate.is_dir() and candidate not in found:
                found.append(candidate)
    return found


def highlight_subdirs(base) -> list:
    """置き場(:func:`highlight_dirs` の1つ)の下のfolderを、実在するものだけ深さ順・名前順で。

    利用者は置き場の下へ週ごとのfolder(``20260829-20260905`` など)を作って素材を仕分ける。
    走査はそこまで辿り(:meth:`tictok.store.highlights.Storage.scan_highlights`)、一覧は
    folderで畳んで出す。

    **1本も入っていないfolderも返す。** ここは「置き場に何が在るか」を答える場所で、
    どれを出すかは呼び手の判断である(一覧は中身も子孫も無い棚を出さない) —— ここで
    間引くと、呼び手はもう「在るのに空だ」と言えなくなる。
    """
    base = Path(base)
    if not base.is_dir():
        return []
    return sorted((path for path in base.rglob("*") if path.is_dir()),
                  key=lambda path: path.relative_to(base).parts)


def source_dir_of(path, root_key=None) -> str:
    """台帳が持つ「どこで見つけたか」の名乗り。record rootからの相対
    (``<配信者>/highlights`` / ``<配信者>/LiveHightlite/20260829-20260905`` 等)。

    folder名だけ(``highlights``)にしないのは、正規の置き場と旧規約の置き場が同じ名前で
    意味が違うためである(``<root>/<配信者>/highlights`` と ``<root>/highlights/<配信者>``)。
    rootの外に在るなら相対にできないので絶対pathをそのまま名乗る。

    **走査(台帳の行)も一覧(folderの名乗り)もここを通す。** 別々に組むと、同じfolderが
    2通りの文字列で現れて、画面がfolderごとに畳めなくなる(行と空folderが別の棚に並ぶ)。
    """
    if root_key is None:
        root_key = root_key_of(path)
    if root_key is None:
        return str(path)
    for key, root in zip(RECORD_ROOT_KEYS, record_roots()):
        if key != root_key:
            continue
        try:
            return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            return str(path)
    return str(path)


def highlight_streamers() -> list:
    """highlightの置き場を1つでも持つ配信者(名前順)。

    走査の入口が「配信者を指定しない」場合に、どの配信者を見ればよいかを決める。root直下を
    総なめにするのではなく、**置き場が在る配信者だけ**を返す —— rootには数TBの録画が同居して
    おり、探索の母集団を広げる理由が無い。"""
    names: set = set()
    for root in record_roots():
        root = Path(root)
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name in NON_STREAMER_DIRS:
                continue
            if any((entry / dirname).is_dir()
                   for dirname in (HIGHLIGHT_DIRNAME, HIGHLIGHT_LEGACY_DIRNAME)):
                names.add(entry.name)
    return sorted(names)


def root_key_of(path):
    """``path`` が どの record root の下に在るか('work' / 'final')。外なら None。

    画面へ返す名前(``<配信者>/<置き場>/<file名>``)はrootからの相対で組むので、rootを1つに
    決められないとfileの在り処が名乗れない。並びは ``record_roots()`` と同じ(先頭がwork)。"""
    resolved = Path(path).resolve()
    for key, root in zip(RECORD_ROOT_KEYS, record_roots()):
        try:
            resolved.relative_to(Path(root).resolve())
        except ValueError:
            continue
        return key
    return None
