"""filesystemから引いた事実のcacheと、その一括取得。

同じ問い(出力は在るか・素材は在るか・sidecarは在るか)を録画ごと・種別ごとに繰り返すと
一覧1回で数千のstatになる。ここはその答えをTTL付きで束ねる層で、無効化点は
``media_jobs._media_job_runner`` の1箇所に揃えてある。一括画面のstatus rollup cache
(``_bulk_status_cache``)を同居させているのも、捨てる契機がまったく同じだから。

依存は runtime / files。
"""

import os
import time
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from tictok.core import perf
from tictok.core import layout
from tictok.record.recorder import sidecar_dir
from tictok.media.thumbnails import thumbnail_artifact_paths
from tictok.media.loudness import gain_artifact_paths
from tictok.media.voice import voice_artifact_paths
from tictok.media.waveform import waveform_artifact_paths
from tictok.record import hls_pack
from tictok.record.upscale import upscale_done, upscale_output_path
from tictok.record.video_overlay import overlay_paths
from tictok.api import files
from tictok.api import runtime


def _output_done(path: Optional[str]) -> bool:
    """True when a burned-in output (overlay mp4) already exists for this recording.
    The rendered file on disk is the source of truth (it is settings-invalidated and
    can be cleaned up), so output state is derived from the filesystem, not the DB."""
    if not path:
        return False
    try:
        return overlay_paths(Path(path))[0].is_file()
    except OSError:
        return False


class _BoundedCache(dict):
    """件数上限つきのTTL cache。上限に達したら古い方から1/4を捨てる。

    TTLは「その値がまだ正しいか」しか見ておらず、期限切れのentryを消す者がいない。keyは
    録画のpath(と一括の要求種別)なので、放っておくとprocessが見たpathの数だけ単調に伸びる。

    dictを継承しているのは、書き込み側の1つ(``routes/bulk.py`` の ``_bulk_status_cache[key] =``)
    がこのmoduleの外に在るため。上限の判断を代入そのものへ載せておけば、書き込み点が増えても
    捨て忘れが起きない。``.get`` / ``.clear`` / ``in`` はdictのまま — 無効化点を
    ``media_jobs._media_job_runner`` の1箇所に揃えてある構造を変えない。

    捨てるのは**新しいkeyを載せるときだけ**。既存keyの更新ではdictは伸びないので、そこで
    捨てるとTTL内の生きたentryを巻き添えにhit率だけが落ちる(store/_common.pyの
    ``_USER_CACHE_MAX`` と同じ扱い。dictは挿入順を保つので古い方から捨てられる)。"""

    def __init__(self, max_entries: int) -> None:
        super().__init__()
        self._max_entries = max_entries

    def __setitem__(self, key, value) -> None:
        if key not in self and len(self) >= self._max_entries:
            for stale in list(self)[:self._max_entries // 4]:
                del self[stale]
        super().__setitem__(key, value)


# 録画pathをkeyにするcache(_fs_state_cache / _fs_bulk_cache)の上限件数。
#
# 上限は録画数を下回ってはいけない。一覧のpollは毎回**全録画**をstatしに来るので、上限が
# 録画数より小さいと同じpoll中に自分で自分を追い出し、cacheが防ぐはずだったstatの嵐へ戻る。
#
# 実測(tictok.db): 録画374本、43.1日で374本 = 8.68本/日。4000は現在の録画数の10倍強で、
# 増加ペースのまま**1年以上(約418日)連続稼働**しても最初の1件も捨てない。restartで空に
# 戻るので、これは「捨てる」ためではなく「際限なく伸びない」ための天井である。
#
# 代償はmemory。1 entryは実測で _fs_state_cache 264 byte / _fs_bulk_cache 1,110 byte
# (path 75文字 + facts 8項目)なので、上限まで埋まっても両方で約5.5MB。
_FS_FACTS_CACHE_MAX = 4000

# Disk remains the source of truth for output/upscale existence, but the session
# list re-stats every recording on each poll; a short TTL cache collapses those
# filesystem stat calls without duplicating the state into the DB.
_FS_STATE_TTL_SECONDS = 3.0
_fs_state_cache: dict = _BoundedCache(_FS_FACTS_CACHE_MAX)

# 一括画面は録画数ぶん「mp4のstat・出力fileのstat・HLS dirのglob」を種別ごと/呼び出しごとに
# 繰り返すため、pathをkeyにfact一式を束ねてTTLで持つ。job完了でfileが変わるので、そのとき
# _fs_bulk_cacheをclearして無効化する(外部での手動移動はTTLぶんだけ遅れて反映される)。
_FS_BULK_TTL_SECONDS = 30.0
_fs_bulk_cache: dict = _BoundedCache(_FS_FACTS_CACHE_MAX)

# 確定録画のHLS再生dir。segment 1本ごとに叩かれるrouteが、そのたびrecord rootの数だけ
# is_dir・素材のglob・playlistのstatを起こしていた(再生中ずっと毎秒)。答えは再生の間
# 変わらないので短いTTLで持つ。
#
# 消えた素材をcacheが在ると言い続けても実害は無い: 実際に返すfileは``_hls_member``が
# その場でstatするので、返せなければ404になる。逆(素材が現れたのにNoneを覚えている)は
# TTLぶんだけ遅れて解ける。
_HLS_DIR_TTL_SECONDS = 3.0
_hls_dir_cache: dict = _BoundedCache(_FS_FACTS_CACHE_MAX)


def recording_hls_dir(recording: dict) -> Optional[Path]:
    """``files._recording_hls_dir`` をTTL cache越しに引く。判定そのものは同じ。"""
    key = recording.get("path") or recording.get("filename") or ""
    now = time.time()
    if key:
        cached = _hls_dir_cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
    with perf.phase("fs.stat"):
        hls_dir = files._recording_hls_dir(recording)
    if key:
        _hls_dir_cache[key] = (now + _HLS_DIR_TTL_SECONDS, hls_dir)
    return hls_dir


def _recording_output_state(path: Optional[str]) -> tuple[bool, bool]:
    """(output_done, up_output_done) for a recording path, cached briefly to avoid
    re-stat'ing the same files on every session-list poll."""
    now = time.time()
    cached = _fs_state_cache.get(path)
    if cached is not None and cached[0] > now:
        return cached[1], cached[2]
    with perf.phase("fs.stat"):
        output_done = _output_done(path)
        # pathが無いのは録画中/finalize前の録画。Up出力の在り処が決まらないので「まだ無い」で
        # 正しい(pathを組み立てる側へNoneを渡さない)。
        up_output_done = upscale_done(Path(path)) if path else False
    _fs_state_cache[path] = (now + _FS_STATE_TTL_SECONDS, output_done, up_output_done)
    return output_done, up_output_done


def _recording_fs_facts(recording: dict) -> dict:
    """録画1本の、filesystemが正である事実一式を1回で引いてcacheする。

    一括画面(status/recordings/estimate)はこれを録画数ぶん回すので、mp4のstat・出力fileの
    stat・HLS dirのglobを種別ごと/呼び出しごとに繰り返さないよう、pathをkeyにまとめて持つ。
    無効化はjob完了時の_fs_bulk_cache.clear()に一本化する(filesystemが変わるのはそこだけ)。"""
    path = recording.get("path")
    now = time.time()
    # pathが空(録画中/finalize前)の録画は互いにpathを持たないので、keyにすると別録画のfactを
    # 取り違える。cacheはpathを持つ録画に限り、それ以外は都度算出する(件数が少なく安い)。
    cacheable = bool(path)
    if cacheable:
        cached = _fs_bulk_cache.get(path)
        if cached is not None and cached[0] > now:
            return cached[1]
    with perf.phase("fs.stat"):
        mp4 = files._existing_recording_file(recording)
        try:
            size = mp4.stat().st_size if mp4 is not None else 0
        except OSError:
            size = 0
    # has_hls(=.ts走査)はここでは引かない。全録画ぶんのHLS dir globは重く、再mp4化を見ていない
    # 間は不要。reprocessの判定に入ったときだけ_recording_has_hlsが遅延で引き、このdictへ書く。
    facts = {
        "has_file": mp4 is not None,
        "bytes": size,
        "overlay_done": _output_done(path),
        # 上と同じ: pathの無い録画(録画中/finalize前)はUp出力のpathが決まらないので未存在。
        "upscale_done": upscale_done(Path(path)) if path else False,
    }
    if cacheable:
        _fs_bulk_cache[path] = (now + _FS_BULK_TTL_SECONDS, facts)
    return facts


def _recording_has_hls(recording: dict) -> bool:
    """この録画に再生成元の.tsが残っているか。globを伴うので、再mp4化(reprocess)の判定に
    入ったときだけ遅延で引く。cache済みfacts dictへ書き戻し、同じTTL窓では1回に抑える。"""
    facts = _recording_fs_facts(recording)
    if "has_hls" not in facts:
        stem = Path(recording.get("filename") or recording.get("path") or "").stem
        facts["has_hls"] = bool(stem) and files._find_hls_root(stem) is not None
    return facts["has_hls"]


def _recording_packed(recording: dict) -> bool:
    """この録画の素材が既に束ね済み(pack*.ts)か。ts結合の判定に入ったときだけ遅延で引く。

    束ね済みかどうかは ``hls_pack.is_packed`` だけが答える(判定を写すと、束ねたfileの
    実在ではなくsnapshotの読めた/読めないで答えが変わる)。"""
    facts = _recording_fs_facts(recording)
    if "packed" not in facts:
        dirs = files._recording_media_dirs(recording)
        facts["packed"] = bool(dirs) and hls_pack.is_packed(dirs[0])
    return facts["packed"]


# 録画1本ぶんのsidecar cacheのfact名 → そのcacheを構成するpathを返すhelper。片方だけ在る
# 状態(decodeが途中で落ちた等)を済みと数えないため、種別ごとにfileを列挙で持つ。
_SIDECAR_ARTIFACTS = {
    "waveform_done": waveform_artifact_paths,
    "sprite_done": thumbnail_artifact_paths,
    "voice_done": voice_artifact_paths,
    "gain_done": gain_artifact_paths,
}

# sidecarを作るjobの種別 → その済みを表すfact名。sweepと一括が同じ対応を別々に持っていた
# 頃は、種別を足した側だけが増えて片方が古いまま残る形だった(実際に三項演算子で2種別を
# 書き分けていて、3つ目を足すと必ずどちらかへ倒れた)。
SIDECAR_JOB_FACTS = {
    "waveform": "waveform_done",
    "sprite": "sprite_done",
    "voice": "voice_done",
    "gain": "gain_done",
}

# sidecarを作るjobの種別 → 自動生成の本数を決める設定key。同じ理由で1箇所に置く: sweepの
# 定期投入(startup.SWEEP_LIMIT_SETTINGS)と、ts結合の完了に続けて積む経路
# (media_jobs._enqueue_sidecars_after_pack)が同じ対応を読む。0はその種別の自動生成を
# 行わない指定なので、両方の経路が同じように止まる必要がある。
SIDECAR_SWEEP_SETTINGS = {
    "waveform": "waveform_sweep_per_start",
    "sprite": "sprite_sweep_per_start",
    "voice": "voice_sweep_per_start",
    "gain": "gain_sweep_per_start",
}


def _recording_src(recording: dict) -> Optional[Path]:
    """sidecarの済みを判定するときに見る録画mp4のpath。**jobが実際に読むのと同じ解決**を通す。

    DBのpathは実体を指さないことがある(完了録画はfinal dirへ移動するため)。判定がDBのpathを
    そのまま信じ、実行(``media_jobs._run_sidecar_cache_job``)が
    ``files._resolved_recording_path`` で両rootから実体を探していた頃は、rootのずれた録画1本
    (rid=146)が**永久にsweepへ乗り続けた** —— jobは実体側の`.sidecars`にcache命中して20〜60msで
    completedになるのに、判定はDBのpath側の`.sidecars`を見て「未生成」のままなので、30分ごとに
    同じ4種別(waveform/sprite/voice/gain)が積み直される。台帳2,279行のうち627行(27.5%)が
    この1本だった。判定と実行が別々にpathを解くと、jobが成功しても事実が1bitも変わらない。"""
    path = recording.get("path")
    if not path:
        return None
    try:
        return files._resolved_recording_path(recording)
    except HTTPException:
        return None


def _memo_recording_src(recording: dict, memo: dict) -> Optional[Path]:
    """``_recording_src`` を走査1回ぶんのmemoに載せる。1録画につき4種別を判定するので、
    memoが無いとpath解決のstatが4倍になる。memoは ``_sidecar_names`` と同じdictを使う
    (keyがPathとtupleで重ならない)。"""
    key = ("src", recording.get("path"))
    if key not in memo:
        memo[key] = _recording_src(recording)
    return memo[key]


def _recording_sidecar_done(recording: dict, fact: str) -> bool:
    """この録画のsidecar cache(波形 / sprite / 声)が既に在るか。その判定に入ったときだけ
    遅延で引き、cache済みfacts dictへ書き戻す(has_hls・packedと同じ流儀)。

    見るのは実在だけで、cacheの指紋(mtime+size)までは照合しない。指紋が古いcacheの作り直しは
    再生画面が要求した時点で生成側が判断する — sweepの仕事は「一度も作られていない録画を
    無くすこと」であって、cacheの鮮度を追いかけることではない。"""
    facts = _recording_fs_facts(recording)
    if fact not in facts:
        src = _recording_src(recording)
        facts[fact] = bool(src) and all(
            p.is_file() for p in _SIDECAR_ARTIFACTS[fact](src))
    return facts[fact]


def _sidecar_names(directory: Path, memo: dict) -> set:
    """``directory``直下のfile名集合。``memo``にdir単位でcacheする。

    sidecarは録画ごとのdirではなくrecord root直下の単一 `.sidecars/` に集まる(recorder.
    sidecar_dir)ので、rootの数だけ読めば全録画ぶんの実在が分かる。読めないdirは空 = その
    rootのsidecarは未生成、で正しい。"""
    cached = memo.get(directory)
    if cached is None:
        cached = set()
        with perf.phase("fs.scan"):
            try:
                with os.scandir(directory) as it:
                    for entry in it:
                        if entry.is_file():
                            cached.add(entry.name)
            except OSError:
                pass
        memo[directory] = cached
    return cached


def _sidecar_done_in(recording: dict, fact: str, memo: dict) -> bool:
    """``_recording_sidecar_done`` と同じ判定を、個別statではなくdir一覧のmembershipで行う。
    判定するfileの集合は同一で、走査だけをdir単位に畳む。"""
    src = _memo_recording_src(recording, memo)
    if src is None:
        return False
    names = _sidecar_names(sidecar_dir(src), memo)
    return all(p.name in names for p in _SIDECAR_ARTIFACTS[fact](src))


def _bulk_sidecar_batch(recordings: list, facts_by_id: dict) -> None:
    """recordingsのsidecar系factを、録画ごとのstatではなく **.sidecars を1回 scandir** して
    埋める(_SIDECAR_ARTIFACTSの全て)。それらの判定に入るときだけ呼ぶ。"""
    memo: dict = {}
    for recording in recordings:
        facts = facts_by_id.get(recording["id"])
        if facts is None:
            continue
        for fact in _SIDECAR_ARTIFACTS:
            if fact not in facts:
                facts[fact] = _sidecar_done_in(recording, fact, memo)


def _fs_facts_from_dir_listing(recording: dict, files_in) -> dict:
    """1録画のfacts(has_hlsを除く)を、個別statではなくディレクトリ一覧から求める。

    元mp4・焼き込み・Up出力は同じ mp4_dir に同居する(layout)。存在確認は `_output_done` /
    `upscale_done` と**同じヘルパでpathを組み**、`.is_file()` の代わりに一覧(name→size)への
    membershipで判定する — 判定するfileの集合は個別stat版と同一で、走査だけをdir単位に畳む。"""
    path = recording.get("path")
    try:
        src = files._safe_recording_path(path or "") if path else None
    except HTTPException:
        src = None
    if src is None:
        return {"has_file": False, "bytes": 0, "overlay_done": False, "upscale_done": False}
    names = files_in(src.parent)
    overlay = overlay_paths(src)[0]
    overlay_done = overlay.name in names
    # upscale_input_pathと同値: 焼き込みが在ればそれを、無ければ元mp4を入力にする。
    upscale_out = upscale_output_path(overlay if overlay_done else src)
    return {
        "has_file": src.name in names,
        "bytes": names.get(src.name, 0),
        "overlay_done": overlay_done,
        "upscale_done": upscale_out.name in names,
    }


def _bulk_fs_facts_batch(recordings: list) -> dict:
    """recordings全部のfacts(has_hls除く)を、録画ごとのstatではなく**ディレクトリ単位のscandir**で
    まとめて引き、`{recording_id: facts}` を返す。

    録画数ぶんのstat(元mp4・焼き込み・Up出力で1本あたり数回)は数千本規模で効く。全variantは
    配信者ごとの単一dirに同居するので、dirを1回読めば存在と容量が全て分かる。結果は
    `_recording_fs_facts` と同形で `_fs_bulk_cache` に載せ、以降の個別呼び出し(reprocessの
    `_recording_has_hls` 等)と共有する。cacheが生きている録画はscandirを起こさない。"""
    now = time.time()
    listings: dict = {}

    def files_in(directory: Path) -> dict:
        cached = listings.get(directory)
        if cached is None:
            cached = {}
            # dirが無ければ空 = そのdirの録画は全て未存在。これは誤魔化しではなく正しい解釈。
            with perf.phase("fs.scan"):
                try:
                    with os.scandir(directory) as it:
                        for entry in it:
                            if not entry.is_file():
                                continue
                            try:
                                cached[entry.name] = entry.stat().st_size
                            except OSError:
                                cached[entry.name] = 0
                except OSError:
                    pass
            listings[directory] = cached
        return cached

    facts_by_id: dict = {}
    for recording in recordings:
        path = recording.get("path")
        if path:
            cached = _fs_bulk_cache.get(path)
            if cached is not None and cached[0] > now:
                facts_by_id[recording["id"]] = cached[1]
                continue
        facts = _fs_facts_from_dir_listing(recording, files_in)
        if path:
            _fs_bulk_cache[path] = (now + _FS_BULK_TTL_SECONDS, facts)
        facts_by_id[recording["id"]] = facts
    return facts_by_id


def bulk_media_kinds(recordings: list) -> dict:
    """recordings全部の実体の種別を `{recording_id: ["ts", "mp4"]}` の形でまとめて返す。

    ``files._recording_media_kinds`` を録画ごとに呼ぶのと同じ判定だが、あちらは1本ごとに
    glob(.ts)とstat(mp4)を起こす。録画一覧は画面を開くたび・配信者を変えるたびに全件ぶん
    回るので、dir単位に畳んだ一括版で引く。種別の綴りと順序は個別版と揃える(画面が
    2つの経路で違う名前を受け取らないようにする)。"""
    facts_by_id = _bulk_fs_facts_batch(recordings)
    _bulk_hls_batch(recordings, facts_by_id)
    kinds_by_id: dict = {}
    for recording in recordings:
        facts = facts_by_id.get(recording["id"]) or {}
        kinds = []
        if facts.get("has_hls"):
            kinds.append("ts")
        if facts.get("has_file"):
            kinds.append("mp4")
        kinds_by_id[recording["id"]] = kinds
    return kinds_by_id


def _bulk_hls_batch(recordings: list, facts_by_id: dict) -> None:
    """recordingsのhas_hlsを、録画ごとの is_dir ではなく **配信者ごとの ts/ を1回scandir**して
    足切りしてから埋める。reprocess判定に入るとき(kindにreprocessが要るとき)だけ呼ぶ。

    `_find_hls_root` と厳密に等価: seg dir が親(ts/)に在るか(=is_dir)を一覧のmembershipで見て、
    在るものだけ `_has_usable_media` で中身を確認する。retentionで.tsが消えた録画(=seg dirが
    無い)は親の一覧だけで即決し、録画ごとのstatを起こさない。結果は facts dict へ書き戻す。"""
    stem_dir_names: dict = {}

    def dirs_under(parent: Path) -> set:
        cached = stem_dir_names.get(parent)
        if cached is None:
            cached = set()
            with perf.phase("fs.scan"):
                try:
                    with os.scandir(parent) as it:
                        for entry in it:
                            if entry.is_dir():
                                cached.add(entry.name)
                except OSError:
                    pass
            stem_dir_names[parent] = cached
        return cached

    for recording in recordings:
        facts = facts_by_id.get(recording["id"])
        if facts is None or "has_hls" in facts:
            continue
        stem = Path(recording.get("filename") or recording.get("path") or "").stem
        has = False
        packed = False
        if stem:
            for root in runtime._RECORD_ROOTS:
                seg_dir = layout.session_dir(root, stem)
                # 親の一覧に無ければ seg dir 不在。在るものだけ中身(素材と再生list)を確認する。
                if seg_dir.name in dirs_under(seg_dir.parent) and files._has_usable_media(seg_dir):
                    has = True
                    # 束ね済みかはts結合の対象判定にしか要らないが、素材の在るdirは今ここで
                    # 開いている。別passで引き直すと同じdirをもう一度舐めることになる。
                    packed = hls_pack.is_packed(seg_dir)
                    break
        facts["has_hls"] = has
        facts["packed"] = packed

# 一括画面の集計は録画ごとのfile確認を伴うため、pollのたびに走らせない。cacheは要求種別の
# 組ごとに持つ(reprocessを含む集計と含まない集計は別物)。
_BULK_STATUS_TTL_SECONDS = 20.0
# 上限件数。keyは要求種別を並べた文字列なので、正当なkeyは BULK_KINDS(10種)の空でない
# 部分集合ぶん = 1023通りしかない。それでも天井が要るのは、keyが要求文字列から作られていて
# ``?kinds=overlay,overlay,...`` のような重複が別keyになるため — 正当な種別だけを並べても
# 長さの数だけkeyが増える。1023の2倍を上限にすれば、通常の利用で捨てることは無く、
# 重複による増殖だけが頭打ちになる。1 entryは実測4,365 byte(配信者3名ぶんの集計)。
# **種別を1つ足すと正当なkeyの数は倍になる**ので、ここも一緒に上げる
# (test_bulk_status_cache_cap_clears_the_legitimate_key_space が見張っている)。
_BULK_STATUS_CACHE_MAX = 2048
_bulk_status_cache: dict = _BoundedCache(_BULK_STATUS_CACHE_MAX)
