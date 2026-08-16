# -*- coding: utf-8 -*-
"""
【Resolve の Console に貼る】Workspace > Console > Py3。手元で動かしても何も出ません。
字幕クリップの区切り位置でビデオ/オーディオを分割する。
元タイムラインを複製してから分割するので、字幕トラックは維持される。
endFrameの仕様・端数の落とし方・素材とタイムラインのフレームレート差は、
実行時に測ってから使う。測れなければ止める（既定を決めると隙間が黙って残る）。
無料版でも動く。
"""

import io
import math
import os

SPLIT_AUDIO = True  # オーディオも同じ位置で分割するか
PROBE_TIMELINE = "__probe_endframe__"  # 測定用タイムラインの名前

# 実行の記録を残す先。10_実務_字幕を装飾する.py と同じ file へ書く。
# Console の文字は Resolve ごと落ちると消えるので、何を測って何を置いたかが
# 残らないと、隙間が空いたときに原因を突き止められない。
LOG_PATH = r"C:\01_work\00_Git\toybox\TicTok\Davinci Resolve Script\実行ログ.txt"


def note(message):
    """Console と log file の両方へ書く。"""
    print(message)
    if not LOG_PATH:
        return
    try:
        with io.open(LOG_PATH, "a", encoding="utf-8", newline="") as handle:
            handle.write(message + os.linesep)
    except Exception as error:
        # log が書けないことで本題は止めない。ただし黙ると「落ちた」と見分けが付かない。
        if not getattr(note, "told", False):
            note.told = True
            print("log を書けません（%s: %s）。" % (type(error).__name__, error))


def get_resolve_obj():
    """Resolve内部実行時に用意されているResolveオブジェクトを取得する。"""
    g = globals()
    if "resolve" in g and g["resolve"] is not None:
        return g["resolve"]
    if "app" in g and g["app"] is not None:
        return g["app"].GetResolve()
    return None


def end_of(item):
    """クリップの終端（最終フレーム+1）を返す。

    `GetEnd()` は使わない。それが最終フレームを指すのか、その次を指すのかを
    測っていないため（doc/わかったこと.md に記録が無い）。1つずれると分割位置が
    1フレーム手前になり、切ったクリップの尻に隙間が開く。10_実務_字幕を装飾する.py は
    `GetStart() + GetDuration()` で同じ境目を出しているので、こちらへ揃える。
    """
    return int(item.GetStart()) + int(item.GetDuration())


def collect_split_points(timeline):
    """全字幕トラックのクリップ開始/終了フレームを昇順・重複なしで返す。"""
    points = set()
    for index in range(1, timeline.GetTrackCount("subtitle") + 1):
        for item in timeline.GetItemListInTrack("subtitle", index) or []:
            points.add(int(item.GetStart()))
            points.add(end_of(item))
    return sorted(points)


def gather_items(timeline, track_type):
    """指定種別の全トラックから (トラック番号, クリップ) の一覧を返す。"""
    result = []
    for index in range(1, timeline.GetTrackCount(track_type) + 1):
        for item in timeline.GetItemListInTrack(track_type, index) or []:
            if item.GetMediaPoolItem() is not None:  # 複合クリップ等は除外
                result.append((index, item))
    return result


def get_source_start(item):
    """クリップのソース側イン点フレームを取得する。"""
    try:
        return int(item.GetSourceStartFrame())
    except Exception:
        return int(item.GetLeftOffset())


def stop(message):
    """理由を名乗って止める。分からない値を推し量って動き続けない。"""
    note(message)
    raise SystemExit(1)


def first_placed(placed):
    """AppendToTimeline の戻りから、実体のある1本目を返す。無ければ None。

    リストは返るのに中身が None、という戻り方をする（doc/わかったこと.md）。
    `if not placed` だけでは通り抜ける。
    """
    for item in placed or []:
        if item is not None:
            return item
    return None


def rate_of(value):
    """フレームレートの設定値を数にする。読めなければ 0。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def probe_place(media_pool, media, src_start, length):
    """素材の src_start から length 本ぶん頼んで置き、置かれた尺を返す。置けなければ 0。

    ソースの先頭（フレーム0）ではなく、実際に使っているイン点から測る。素材の
    フレーム番号が0から始まるとは限らず、範囲外を頼むと Resolve が縮めて置くため。
    """
    placed = first_placed(media_pool.AppendToTimeline([{
        "mediaPoolItem": media,
        "startFrame": src_start,
        "endFrame": src_start + length - 1,
        "trackIndex": 1,
        "mediaType": 1,
    }]))
    return int(placed.GetDuration()) if placed is not None else 0


def placed_length(count, scale, rule):
    """ソースを count 本頼んだときに、タイムライン上で何フレームになるかを予想する。"""
    value = count * scale
    if rule == "floor":
        return int(math.floor(value + 1e-9))
    return int(math.floor(value + 0.5))


def source_count(duration, spec):
    """タイムライン上で duration フレームになるソースの本数を返す。無ければ 0。

    素材とタイムラインで1フレームの長さが違うと、頼んだ本数がそのまま尺にならない
    （25fpsの素材を24fpsのタイムラインへ置けば0.96倍）。頼む本数を1つ変えると尺は
    1/scale ずつ動くので、狙った尺になる本数は必ず在る。総当たりで選ぶ。
    """
    base = int(duration / spec["scale"])
    for count in range(max(1, base - 2), base + 3):
        if placed_length(count, spec["scale"], spec["rule"]) == duration:
            return count
    return 0


HYPOTHESES = [(True, "floor"), (True, "round"), (False, "floor"), (False, "round")]


def predict(length, inclusive, scale, rule):
    """length 本と頼んだときの、タイムライン上の尺を仮説ごとに予想する。"""
    return placed_length(length - (0 if inclusive else 1), scale, rule)


def probe_lengths(scale):
    """4つの仮説を見分けられる頼み方の組を選ぶ。

    どの長さでも見分けが付くわけではない。比が 25/24 のとき、10本と頼むと
    切り捨てでも四捨五入でも10フレームになって区別できない。予想が仮説ごとに
    分かれるまで長さを足す。比が1のときは切り捨てと四捨五入がどこまでも同じ値に
    なるので分かれないが、そのときはどちらを採っても結果が変わらない。
    """
    def groups(lengths):
        seen = set()
        for inclusive, rule in HYPOTHESES:
            seen.add(tuple(predict(n, inclusive, scale, rule) for n in lengths))
        return len(seen)

    chosen = []
    for length in range(8, 200):
        if len(chosen) >= 3 or (chosen and groups(chosen) == len(HYPOTHESES)):
            break
        if not chosen or groups(chosen + [length]) > groups(chosen):
            chosen.append(length)
    return chosen


def detect_placement(project, media_pool, media, src_start, work_timeline, restore_timeline):
    """テスト配置して、置かれ方を実測する。{inclusive, scale, rule} を返す。

    未知は3つある。endFrameが最終フレームを指すのか、素材とタイムラインで1フレームの
    長さが違わないか、端数をどう落とすか。比だけは実測から出さずにフレームレートで割る。
    実測の差から出すと、25/24 を 1.05 と読むような誤差が乗り、長い区間ほどずれるため。
    残る2つは、仮説ごとに答えが分かれる長さを選んで置き、その結果で絞る。

    測れなければ止める。既定を決めて進むと、切れ目ごとに隙間（黒コマ）が黙って残る。

    置き方は 10_実務_字幕を装飾する.py の実測で通った形に揃える。`trackIndex` を
    渡さないと、リストは返るのに中身が None になる（doc/わかったこと.md）。
    """
    media_rate = rate_of(media.GetClipProperty("FPS"))
    work_rate = rate_of(work_timeline.GetSetting("timelineFrameRate"))
    if not media_rate or not work_rate:
        stop("フレームレートを読めません（素材 %r / タイムライン %r）。"
             % (media.GetClipProperty("FPS"), work_timeline.GetSetting("timelineFrameRate")))

    probe = media_pool.CreateEmptyTimeline(PROBE_TIMELINE)
    if probe is None:
        stop("測定用タイムライン %r を作れません。前回の残りがあれば消してください。"
             % PROBE_TIMELINE)

    project.SetCurrentTimeline(probe)
    if (probe.GetTrackCount("video") or 0) < 1:
        probe.AddTrack("video")

    try:
        probe_rate = rate_of(probe.GetSetting("timelineFrameRate"))
        if not probe_rate:
            stop("測定用タイムラインのフレームレートを読めません。")
        # 測定用タイムラインは project の設定で作られるので、作業中のものと
        # フレームレートが違うことがある。測るときの比は測定用のもので考える。
        probe_scale = probe_rate / media_rate
        lengths = probe_lengths(probe_scale)
        got = [probe_place(media_pool, media, src_start, n) for n in lengths]
    finally:
        project.SetCurrentTimeline(restore_timeline)  # 現在のタイムラインは削除できない
        media_pool.DeleteTimelines([probe])

    note("測定: 比 %.6f（測定用 %s / 素材 %s）、%s"
         % (probe_scale, probe_rate, media_rate,
            " / ".join("%d本→%dフレーム" % pair for pair in zip(lengths, got))))
    if min(got) <= 0:
        stop("置かれ方を測れません（測定用クリップを置けませんでした）。")

    scale = work_rate / media_rate
    for inclusive, rule in HYPOTHESES:
        if [predict(n, inclusive, probe_scale, rule) for n in lengths] == got:
            note("判定: endFrameは%s / 端数は%s / 本番の比 %.6f（作業中 %s / 素材 %s）"
                 % ("最終フレーム" if inclusive else "最終フレームの次",
                    "切り捨て" if rule == "floor" else "四捨五入",
                    scale, work_rate, media_rate))
            return {"inclusive": inclusive, "scale": scale, "rule": rule}
    stop("置かれ方を説明できません（比 %.6f、%s）。\n"
         "endFrameの仕様と端数の落とし方が、測った値と噛み合いません。"
         % (probe_scale, " / ".join("%d本→%dフレーム" % pair for pair in zip(lengths, got))))


def build_infos(track_index, item, points, media_type, spec):
    """1クリップを分割点で区切り、AppendToTimeline用の辞書リストを返す。

    切り位置と尺はタイムラインのフレームで決まるが、`startFrame`/`endFrame` は
    ソースのフレームで渡す。1フレームの長さが違えば数が一致しないので、
    実測した比で換算する。比が1のときは元の計算と同じ結果になる。
    """
    media = item.GetMediaPoolItem()
    start = int(item.GetStart())
    end = end_of(item)  # 終端は排他的（最終フレーム+1）
    src_start = get_source_start(item)
    scale = spec["scale"]

    edges = [start] + [p for p in points if start < p < end] + [end]

    infos = []
    impossible = []
    for i in range(len(edges) - 1):
        seg_start = edges[i]
        duration = edges[i + 1] - seg_start
        count = source_count(duration, spec)
        if not count:
            impossible.append((seg_start, duration))
            continue
        in_frame = src_start + int(math.floor((seg_start - start) / scale + 0.5))
        out_frame = in_frame + count - 1 if spec["inclusive"] else in_frame + count
        infos.append({
            "mediaPoolItem": media,
            "startFrame": in_frame,
            "endFrame": out_frame,
            "recordFrame": seg_start,
            "trackIndex": track_index,
            "mediaType": media_type,  # 1=ビデオのみ 2=オーディオのみ
        })
    if impossible:
        note("タイムライン上の尺にできない区間が %d件あります（開始 / 尺）: %s"
             % (len(impossible), impossible[:5]))
        if scale > 1.0:
            stop("素材1本がタイムラインの %.3f フレームぶんになるためです（比 %.4f）。\n"
                 "1本より長いので尺は飛び飛びの値しか作れず、字幕の切れ目にちょうど\n"
                 "合わせられません。切る位置を1フレームずらすことになるので、\n"
                 "黙って進めずに止めます。素材よりタイムラインが粗ければ起きません。"
                 % (scale, scale))
        stop("頼める本数の中に、その尺になるものがありません。")
    return infos


def check_placed(timeline, infos, spec):
    """頼んだ位置と尺のとおりに置かれたかを読み返す。食い違ったものを返す。

    `AppendToTimeline` の戻りは「置けたかどうか」しか言わない。1フレームでも
    短く置かれると、そこだけ隙間になって黒が挟まる。頼んだ側だけを見て
    完了と名乗ると気づけないので、タイムラインから読み直して突き合わせる。
    """
    actual = {}
    for track_type, media_type in (("video", 1), ("audio", 2)):
        for index in range(1, timeline.GetTrackCount(track_type) + 1):
            for item in timeline.GetItemListInTrack(track_type, index) or []:
                actual[(media_type, index, int(item.GetStart()))] = int(item.GetDuration())

    off = []
    for info in infos:
        count = info["endFrame"] - info["startFrame"] + (1 if spec["inclusive"] else 0)
        want = placed_length(count, spec["scale"], spec["rule"])
        got = actual.get((info["mediaType"], info["trackIndex"], info["recordFrame"]))
        if got != want:
            off.append((info["recordFrame"], want, got))
    return off


def main():
    note("---- 区切り 実行開始 ----")
    resolve = get_resolve_obj()
    if resolve is None:
        note("Resolveオブジェクトを取得できません。")
        return

    project = resolve.GetProjectManager().GetCurrentProject()
    timeline = project.GetCurrentTimeline()
    media_pool = project.GetMediaPool()
    if timeline is None:
        note("タイムラインが開かれていません。")
        return

    points = collect_split_points(timeline)
    if not points:
        note("字幕クリップが見つかりません。")
        return
    note("分割点 %d箇所（%s 〜 %s）" % (len(points), points[0], points[-1]))

    # 元タイムラインを複製し、複製側だけを加工する（字幕はここに残る）
    new_timeline = timeline.DuplicateTimeline(timeline.GetName() + "_split")
    if new_timeline is None:
        note("タイムラインを複製できません。")
        return

    video_items = gather_items(new_timeline, "video")
    audio_items = gather_items(new_timeline, "audio") if SPLIT_AUDIO else []
    if not video_items and not audio_items:
        note("対象クリップがありません。")
        return

    sample_item = (video_items or audio_items)[0][1]
    sample = sample_item.GetMediaPoolItem()
    spec = detect_placement(project, media_pool, sample, get_source_start(sample_item),
                            new_timeline, new_timeline)

    infos = []
    targets = []
    for track_index, item in video_items:
        infos.extend(build_infos(track_index, item, points, 1, spec))
        targets.append(item)
    for track_index, item in audio_items:
        infos.extend(build_infos(track_index, item, points, 2, spec))
        targets.append(item)

    # 元のクリップを消してから、分割済みクリップを同じ位置に置き直す
    new_timeline.DeleteClips(targets, False)
    project.SetCurrentTimeline(new_timeline)
    created = [item for item in (media_pool.AppendToTimeline(infos) or []) if item is not None]
    note("完了: %d/%d クリップ" % (len(created), len(infos)))

    off = check_placed(new_timeline, infos, spec)
    if off:
        note("頼んだ位置・尺と違うものが %d件あります（開始 / 頼んだ尺 / 実際）:" % len(off))
        for start, want, got in off[:5]:
            note("  %d  %d  %s" % (start, want, "そこに無し" if got is None else got))
        note("ここが隙間（黒コマ）になります。")


main()
