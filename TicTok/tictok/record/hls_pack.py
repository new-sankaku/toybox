"""録画のHLS segmentを、解像度が連続する塊ごとに1 fileへ束ねる。

配信は2秒ごとにsegmentを刻むので、3時間の録画で5,794本になる。中身はそのままで構わない
のにfileだけが増え、走査・backup・移送のすべてがfile数に比例して重くなる。ここは**再encode
せず**にbyte連結し、playlistは ``#EXT-X-BYTERANGE`` で束ねたfileの中を指すようにする。実測
(00302, 3.3時間)で 5,794 file -> 41 file、byte差 0、video packet 235,238本と尺11589.042998s
がいずれも結合前と完全一致した。

**解像度の切れ目で束を切る**。1 fileの中で解像度が変わると、hls.jsがそのfile用に作るinit
segmentの寸法が全域に適用され、切替前の区間へseekした時に縦横比が崩れる(実測: 720x1280が
720x1440として描画された)。切れ目で切ればこれは起きない。ただし**segment 1本の内部で解像度
が変わることがある**(実測: 変化40回のうち29回)。その1本はどう切っても単一解像度にならないので
単独fileとして隔離する。隔離したものは結合しない現状と同じ挙動になる(対照実験で確認済み)。

束ねると各segmentのfile自体が消える。``Recorder._playlist_segments`` はそのmtimeを
timing mapのwall軸に、mtime差をPTS不連続の判定に、size 0を欠損segmentの検出に使っている。
消える前にそれらを ``segments.json`` へ固定し、以後はそちらを権威とする。これを省くと、
結合後に再mp4化した録画のwall軸が束ごとに1点へ潰れ、コメントの時刻が静かにずれる。
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Optional

from tictok.core import cancel, ffprobe

logger = logging.getLogger("tictok.hls_pack")

SNAPSHOT_NAME = "segments.json"
SNAPSHOT_VERSION = 1
PACK_SUFFIX = ".ts"
PACK_PREFIX = "pack"
PACK_TMP_SUFFIX = ".packing"

HLS_INPUT_ARGS = ("-allowed_extensions", "ALL",
                  "-protocol_whitelist", "file,crypto,data")


def snapshot_path(hls_dir) -> Path:
    return Path(hls_dir) / SNAPSHOT_NAME


def is_packed(hls_dir) -> bool:
    """この録画が束ね済みか。判定は ``segments.json`` ではなく**束ねたfileの実在**で行う。

    snapshotが読めないことと束ねていないことは別事象で、混同すると危険である: 束ねた後は
    元のsegment fileがもう無いので、snapshotが壊れているのをplaylist経由の読み方へ流すと
    全entryが「fileが無い」となり、**素材ごと失われた録画**に見える。"""
    return next(Path(hls_dir).glob(PACK_PREFIX + "*" + PACK_SUFFIX), None) is not None


def read_snapshot(hls_dir) -> Optional[dict]:
    """束ね済みlayoutの権威。無い(=未結合)か壊れていればNone。"""
    try:
        data = json.loads(snapshot_path(hls_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        return None
    return data


def parse_playlist(text: str, keep_unmeasured: bool = False) -> list:
    """playlistから ``[{"name","extinf","disc"}, ...]`` を順に取る。

    ``disc`` はこのentryの直前に ``#EXT-X-DISCONTINUITY`` が立っていたか。捨てると
    demuxerがtimestampの飛びを経過時間として多重計上する。

    ``#EXTINF`` の無いentryはmedia軸に長さを持たないので既定では落とす。``keep_unmeasured``
    を立てると ``extinf=None`` のまま返す — 録画の確定は「使えないentryが何本あったか」を
    数え、その次のentryを不連続として扱う必要があるため、落とされては困る。"""
    out: list = []
    extinf: Optional[float] = None
    disc = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "#EXT-X-DISCONTINUITY":
            disc = True
        elif line.startswith("#EXTINF:"):
            try:
                extinf = float(line[len("#EXTINF:"):].split(",", 1)[0])
            except ValueError:
                extinf = None
        elif line and not line.startswith("#"):
            if extinf is not None or keep_unmeasured:
                out.append({"name": line, "extinf": extinf, "disc": disc})
            extinf = None
            disc = False
    return out


def plan_packs(resolutions: list) -> list:
    """各segmentの解像度listから、束ねる単位(segment indexのlist)を組む。

    ``resolutions[i]`` はそのsegmentに現れた解像度を出現順に並べたもの。要素が1種類だけの
    segmentは、直前と同じ解像度なら同じ束に足す。2種類以上あるsegment(内部で切り替わって
    いる)と、解像度を判定できなかったsegmentは、それぞれ単独の束にする。純粋関数。"""
    packs: list = []
    current_res = None
    for i, res in enumerate(resolutions):
        distinct = list(dict.fromkeys(res or []))
        if len(distinct) != 1:
            packs.append([i])
            current_res = None
            continue
        if packs and current_res == distinct[0] and len(packs[-1]) > 0:
            packs[-1].append(i)
        else:
            packs.append([i])
            current_res = distinct[0]
    return packs


# 上限の実体は core.ffprobe。既存の公開名は呼び出し側のために残す。
PROBE_TIMEOUT_SECONDS = ffprobe.DEFAULT_TIMEOUT_SECONDS

# csvのparseも core.ffprobe に一本化した。ffprobeの実出力の癖(行ごとに末尾separatorが
# 付いたり付かなかったり)へ追随する場所が2つあると、片方だけが直って静かに食い違う。
_parse_res_csv = ffprobe.parse_resolution_csv


async def _run(args: list, timeout: float = PROBE_TIMEOUT_SECONDS) -> str:
    """ffprobeを1本走らせて標準出力を返す。失敗・timeoutは空文字。

    timeoutを付けるのは、終端されていないplaylist(``#EXT-X-ENDLIST`` の無いcapture index)を
    渡すとffprobeがlive streamと見なして**永久に待つ**ため。呼び出し側は終端済みのplaylistを
    渡す約束だが、破れたときに黙って固まるより打ち切って失敗として扱う。

    走っているffprobeの取り消し登録は ``core.ffprobe`` が行う。束ねの所要時間の大半は
    ここの繰り返しなので、登録しないとuserが押した取り消しが次のphaseまで届かない。"""
    result = await ffprobe.run(args, timeout=timeout)
    return result.stdout if result.ok else ""


async def probe_segment_resolutions(path: Path) -> list:
    """そのsegmentに現れる解像度を出現順に返す。

    keyframe単位で見る。解像度の変更は新しいSPSを伴うのでkeyframeにしか現れないが、
    **segmentの先頭1frameだけでは足りない**: 内部で切り替わる1本を単一解像度と誤判定する。"""
    return _parse_res_csv(
        await _run(ffprobe.keyframe_resolution_args(path)))


async def _resolutions_for(hls_dir: Path, entries: list, concurrency: int = 4,
                           on_done=None) -> list:
    """全segmentの解像度を求める。segmentごとにffprobeを起こすので、同時数だけ絞る。

    ``on_done(済み件数)`` は1本測るごとに呼ぶ。ここは録画1本のts結合で最も長い区間で、
    進んだ件数以外に「動いていること」を示せる材料が無い。"""
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(name: str) -> list:
        nonlocal done
        async with sem:
            cancel.check_cancelled()
            found = await probe_segment_resolutions(hls_dir / name)
        done += 1
        if on_done is not None:
            await on_done(done)
        return found

    return list(await asyncio.gather(*(one(e["name"]) for e in entries)))


def build_snapshot(hls_dir: Path, entries: list, packs: list, placement: dict) -> dict:
    """束ねる直前のsegmentごとの事実を固定する。file自体はこの後消える。"""
    segments = []
    for i, entry in enumerate(entries):
        pack_name, offset, length = placement[i]
        segments.append({
            "name": entry["name"],
            "extinf": entry["extinf"],
            "disc": bool(entry["disc"]),
            "wall": entry["wall"],
            "size": entry["size"],
            "pack": pack_name,
            "offset": offset,
            "length": length,
        })
    return {
        "version": SNAPSHOT_VERSION,
        "packed_at": time.time(),
        "packs": len(packs),
        "segments": segments,
    }


def render_source_playlist(entries: list) -> str:
    """結合前のsegmentを指す**終端済み**VOD playlist。検証の「前」側に使う。

    録画dirの ``index.m3u8`` は録画中にffmpegが追記し続けるcapture indexで、停止が強制終了
    なので ``#EXT-X-ENDLIST`` が付かない。それをそのままffprobeへ渡すとlive streamと見なされ、
    次のsegmentを待って返ってこない。前後を同じ条件で測るためにも、ここで組み直す。"""
    target = max(int(e["extinf"]) + 1 for e in entries)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        "#EXT-X-TARGETDURATION:%d" % target,
    ]
    for e in entries:
        if e["disc"]:
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append("#EXTINF:%.6f," % e["extinf"])
        lines.append(e["name"])
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


async def _probe_packets_and_duration(playlist: Path):
    """playlist全体のvideo packet数と尺。結合の前後で突き合わせる。

    packet数は「1本も落ちていないこと」を、尺は「media軸が伸び縮みしていないこと」を見る。
    どちらもdecodeせずcontainerを読むだけなので、1.25GBでも数秒で終わる。"""
    text = await _run([
        "ffprobe", "-v", "error", *HLS_INPUT_ARGS, "-select_streams", "v:0",
        "-count_packets", "-show_entries", "stream=nb_read_packets:format=duration",
        "-of", "csv=p=0", "-i", str(playlist),
    ])
    fields = [f for f in text.replace("\n", ",").split(",") if f.strip()]
    if len(fields) < 2:
        return None, None
    try:
        return int(fields[0]), float(fields[-1])
    except ValueError:
        return None, None


def _pack_name(index: int) -> str:
    return "%s%03d%s" % (PACK_PREFIX, index, PACK_SUFFIX)


def _pack_tmp_name(index: int) -> str:
    """組み立て中の束の名前。``pack*.ts`` にも ``seg*.ts`` にも当たらない綴りにする。

    束は最終名で書いてはいけない。数GBのbyte連結は分単位かかり、その最中にprocessが
    強制終了されると「pack fileは在るがcommit前」というdirが残る(実測1件)。``is_packed``
    はfileの実在で判定するのでTrueになる一方 ``segments.json`` はまだ無く、下流はその録画を
    「素材無し」と読む — playlistは元のseg*.tsを指したままで、実際には1 byteも欠けて
    いないのにである。一時名なら、殺されても残るのはどのglobにも当たらないゴミだけになる。

    **``pack`` で始めてはいけない。** ``is_packed`` のglobは ``pack*.ts`` なので、
    ``packingpack000.ts`` のような名前は依然として当たる(実際にそう書いて検出された)。
    先頭のドットで ``pack*``/``seg*`` のどちらからも外す。"""
    return ".%s%03d%s" % (PACK_TMP_SUFFIX.lstrip("."), index, PACK_SUFFIX)


def _write_pack(hls_dir: Path, entries: list, indices: list, dst: Path) -> list:
    """1束を1 fileへbyte連結し、``[(entry index, offset, length), ...]`` を返す。

    再encodeしない。MPEG-TSはsegmentごとにPAT/PMTを持つ自己完結したstreamなので、
    そのまま連結しても各segmentの中身は1 bitも変わらない(実測で映像・音声のbitstreamが
    結合前後で完全一致)。"""
    placed = []
    offset = 0
    with open(dst, "wb") as out:
        for i in indices:
            data = (hls_dir / entries[i]["name"]).read_bytes()
            out.write(data)
            placed.append((i, offset, len(data)))
            offset += len(data)
    return placed


def _remove_sources(hls_dir: Path, entries: list) -> tuple:
    """束ね終えた元segmentを消す。(解放bytes, 消せなかった名前) を返す。threadで走る。"""
    freed = 0
    orphans: list = []
    for entry in entries:
        try:
            (hls_dir / entry["name"]).unlink(missing_ok=True)
            freed += entry["size"]
        except OSError:
            orphans.append(entry["name"])
    return freed, orphans


async def pack_session(hls_dir, playlist_name: str = "index.m3u8",
                       on_progress=None) -> dict:
    """1録画のsegmentを解像度の切れ目ごとに束ね直す。結果のdictを返す。

    元のsegmentは**3段の検証を全て通ってから**消す。束ねたfileのbyte数が構成segmentの
    合計と一致すること、束が単一解像度であること(隔離した1本を除く)、そして束ね後のplaylist
    が束ね前とvideo packet数・尺の両方で一致すること。ひとつでも欠ければ束ねたfileを捨てて
    元をそのまま残す。

    解像度はsegmentごとにffprobeする。playlist全体を1 passで走査して変化時刻から逆算する
    方が速いが、実測でその対応付けは41束中17束を取り違えた(segment内部で変わる1本を
    どちらの束にも寄せられないため)。ここは速度より正しさを取る。3時間の録画で1〜2分。

    ``on_progress(段階key, 達成率0.0-1.0, 詳細)`` は ``core.progress.PACK_PHASES`` の段階名で
    呼ぶ。%を直接渡さないのは、段階ごとの重み付けが呼び出し側(job)の関心であり、ここが
    「解像度判定は全体の何%か」を決めるべきではないため。"""
    hls_dir = Path(hls_dir)
    playlist = hls_dir / playlist_name
    result = {"packed": False, "reason": "", "segments": 0, "packs": 0, "bytes": 0}
    if read_snapshot(hls_dir) is not None:
        result["reason"] = "already_packed"
        return result
    try:
        entries = parse_playlist(playlist.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        result["reason"] = "no_playlist"
        return result

    usable = []
    for entry in entries:
        try:
            st = (hls_dir / entry["name"]).stat()
        except OSError:
            continue
        usable.append({**entry, "wall": st.st_mtime, "size": st.st_size})
    if not usable:
        result["reason"] = "no_segments"
        return result
    result["segments"] = len(usable)

    async def report(key: str, frac: float, detail: Optional[str] = None) -> None:
        if on_progress is not None:
            await on_progress(key, frac, detail)

    total_segments = len(usable)

    async def probed(done: int) -> None:
        await report("probe", done / total_segments,
                     f"{done:,} / {total_segments:,}本")

    await report("probe", 0.0, f"0 / {total_segments:,}本")
    resolutions = await _resolutions_for(hls_dir, usable, on_done=probed)
    packs = plan_packs(resolutions)

    await report("measure", 0.0)
    source_playlist = hls_dir / ("source" + PACK_TMP_SUFFIX + ".m3u8")
    source_playlist.write_text(render_source_playlist(usable), encoding="utf-8")
    try:
        before_packets, before_seconds = await _probe_packets_and_duration(source_playlist)
    finally:
        source_playlist.unlink(missing_ok=True)
    await report("measure", 1.0)

    placement: dict = {}
    placement_tmp: dict = {}
    written: list = []
    final_names: dict = {}
    try:
        for n, indices in enumerate(packs):
            cancel.check_cancelled()
            await report("write", n / len(packs), f"{n + 1:,} / {len(packs):,}束")
            # 組み立ては一時名で行い、検証を全部通してからcommit直前に最終名へ改名する
            # (``_pack_tmp_name`` 参照)。placementには**最終名**を入れる: snapshotとplaylist
            # は改名後の世界を書くものなので、一時名が混ざると読めない参照が残る。
            dst = hls_dir / _pack_tmp_name(n)
            final_names[dst] = _pack_name(n)
            written.append(dst)
            # byte連結はGB規模になる。event loop上で回すと、その間serverの全requestと
            # WSが止まる(実測対象で1録画2.5GB)。threadへ逃がす。
            placed = await asyncio.to_thread(_write_pack, hls_dir, usable, indices, dst)
            for i, offset, length in placed:
                # 検証は改名前に走るので一時名を、commitするsnapshot/playlistには最終名を。
                placement_tmp[i] = (dst.name, offset, length)
                placement[i] = (final_names[dst], offset, length)
            expected = sum(usable[i]["size"] for i in indices)
            actual = dst.stat().st_size
            if actual != expected:
                raise OSError("pack %s is %d bytes, expected %d" % (dst.name, actual, expected))
            if len(indices) > 1:
                found = await probe_segment_resolutions(dst)
                if len(set(found)) > 1:
                    raise OSError("pack %s carries %d resolutions (%s)"
                                  % (dst.name, len(set(found)), sorted(set(found))))
        await report("write", 1.0, f"{len(packs):,} / {len(packs):,}束")
        await report("verify", 0.0)
        snapshot = build_snapshot(hls_dir, usable, packs, placement)
        # 一時名でも ``.m3u8`` で終わらせる。ffprobe/ffmpegは拡張子でHLSと判別するので、
        # ``index.m3u8.packing`` のような名前にすると形式を見つけられず計測が空で返る。
        packed_playlist = hls_dir / (Path(playlist_name).stem + PACK_TMP_SUFFIX + ".m3u8")
        packed_playlist.write_text(render_playlist(snapshot), encoding="utf-8")
        written.append(packed_playlist)
        # 計測は**一時名を指すplaylist**で行う。束はまだ改名していないので、最終名の
        # playlistを読ませるとfileが見つからず、中身ではなく名前の都合で検証が落ちる。
        verify_playlist = hls_dir / ("verify" + PACK_TMP_SUFFIX + ".m3u8")
        verify_playlist.write_text(
            render_playlist(build_snapshot(hls_dir, usable, packs, placement_tmp)),
            encoding="utf-8")
        written.append(verify_playlist)
        after_packets, after_seconds = await _probe_packets_and_duration(verify_playlist)
        verify_playlist.unlink(missing_ok=True)
        written.remove(verify_playlist)
        if before_packets is None or after_packets is None:
            raise OSError("could not measure the playlist before/after packing")
        if after_packets != before_packets:
            raise OSError("packing changed the video packet count: %d -> %d"
                          % (before_packets, after_packets))
        if abs((after_seconds or 0.0) - (before_seconds or 0.0)) > 0.001:
            raise OSError("packing changed the duration: %.3fs -> %.3fs"
                          % (before_seconds or 0.0, after_seconds or 0.0))
        await report("verify", 1.0)
    except (OSError, ValueError) as exc:
        for path in written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        logger.error(
            "%s のts結合に失敗したため元のまま残しました: %s", hls_dir.name, exc,
            extra={"event": "hls.pack_failed",
                   "ctx": {"stem": hls_dir.name, "path": str(hls_dir),
                           "segments": len(usable), "packs": len(packs)}},
            exc_info=True,
        )
        result["reason"] = str(exc)
        return result

    # ここからがcommit。改名は連続で走る名前の付け替えだけなので、途中で殺される窓は
    # 組み立て(分単位)と比べて無視できる。snapshotを先に置くのは、pack fileが現れた瞬間に
    # ``is_packed`` がTrueになるためで、順序を逆にすると「packはあるがsnapshotが無い」
    # 状態がまた作れてしまう。
    await report("commit", 0.0, f"{len(usable):,}本")
    snapshot_path(hls_dir).write_text(json.dumps(snapshot), encoding="utf-8")
    for tmp, final in final_names.items():
        tmp.replace(hls_dir / final)
    packed_playlist.replace(playlist)
    # 数千回のunlinkもthreadへ。ここまで来れば検証は全て通っており、取り消しはもう受けない
    # (元segmentを消し始めた後で止めると、束ねたfileと元が半端に同居する)。
    freed, orphans = await asyncio.to_thread(_remove_sources, hls_dir, usable)
    for name in orphans:
        logger.warning(
            "%s のts結合は済みましたが元のsegment %s を削除できません", hls_dir.name, name,
            extra={"event": "hls.source_segment_orphaned",
                   "ctx": {"stem": hls_dir.name, "path": str(hls_dir / name)}},
        )
    await report("commit", 1.0, f"{len(usable):,}本")
    result.update(packed=True, packs=len(packs), bytes=freed)
    logger.info(
        "%s のts結合が完了しました: segment %d 件 -> file %d 件",
        hls_dir.name, len(usable), len(packs),
        extra={"event": "hls.packed",
               "ctx": {"stem": hls_dir.name, "path": str(hls_dir),
                       "segments": len(usable), "packs": len(packs),
                       "packets": before_packets, "media_seconds": before_seconds}},
    )
    return result


def render_playlist(snapshot: dict) -> str:
    """束ねたfileをbyte rangeで指す再生用playlist。hls.jsはこれをそのまま再生できる。"""
    segments = snapshot["segments"]
    target = max(int(s["extinf"]) + 1 for s in segments)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:6",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-INDEPENDENT-SEGMENTS",
        "#EXT-X-TARGETDURATION:%d" % target,
    ]
    for s in segments:
        if s["disc"]:
            lines.append("#EXT-X-DISCONTINUITY")
        lines.append("#EXTINF:%.6f," % s["extinf"])
        lines.append("#EXT-X-BYTERANGE:%d@%d" % (s["length"], s["offset"]))
        lines.append(s["pack"])
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"
