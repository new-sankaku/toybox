"""切り抜き候補の算出。

盛り上がり判定(:mod:`tictok.core.spike`)と、そこへ載せる素材由来の指標(音量・笑い声・
笑顔・笑いcomment)の配線を持つ。

routeではなくここに置くのは、**候補を必要とするのが画面だけではない**ためである。short の
一括生成(:mod:`tictok.api.media_jobs`)は同じ候補から範囲を決めるので、routeの中に閉じて
いると job 側が route を呼ぶ形になり、依存の向きが逆転する(media_jobsのmodule docstring:
「routeはこの層を呼ぶ側で、逆向きは無い」)。画面とjobが別々の候補算出を持つのは論外で、
同じ配信に対して2つの答えが出る。
"""

import asyncio
from pathlib import Path
from typing import Awaitable, Callable, NamedTuple, Optional

from fastapi import HTTPException

from tictok.core import laugh_text, spike
from tictok.core.config import get_laugh_comment_min_w_run
from tictok.media import hls_source, laugh_audio, smile
from tictok.media.waveform import ensure_audio_profile, level_peak, silent_ratio
from tictok.record.video_overlay import _duration_seconds
from tictok.search import indexer
from tictok.api import files
from tictok.api import runtime


class _MaterialMetric(NamedTuple):
    """素材(録画そのもの)を解析して各bucketへ載せるper-bucket指標の登録項。

    diamonds/comments/laugh_commentはDBのeventだけで作れるが、音声・映像から作る指標は
    「有効かを設定で見る → 解析engineを回す → 判定できない録画では外す → 重みと下限を
    設定から引く」という同じ4手順を必ず踏む。指標ごとに候補APIの本体へifを積むと、
    その4手順が少しずつ違う枝に分かれて失敗の扱いが揃わなくなるため、登録表で持つ。

    ``attach`` は値を載せられたら None を、載せられなかったら理由(logのctx)を返す。
    載せられない場合に0で埋めてはならない — 「笑っていなかった」という観測を捏造する。
    """

    key: str
    setting: str
    weight_setting: str
    min_setting: str
    # どちらも呼ぶためのもの。``object`` のままだと型検査が「呼べない」と言う。
    label: Callable[[dict], str]
    attach: Callable[..., Awaitable[Optional[dict]]]


async def _attach_laugh_audio(path: Path, buckets: list, bucket_seconds: int,
                              to_pts) -> Optional[dict]:
    """各bucketへ ``laugh_audio``(窓内で笑い声が出ていた秒数)を載せる。

    確率列は動画時間軸なので、bucketの窓をwall-clockから動画時間へ写してから引く
    (audio_peakと同じ理由: 生の差分を使うと焼き込み動画とずれる)。

    modelが未配置・未導入のときは ``LaughAudioError`` がそのまま上がる。ここで捕まえて
    笑い抜きの候補を返すと、利用者は「笑いの無い配信」と読む — 呼び出し側で503にする。

    ``clip_candidate_laugh_audio_solo_only`` が立っていれば、画面に顔が2つ以上映って
    いる間の笑い声を数えない。コラボ中の笑いは共演者のものかもしれず、どの顔が配信者かを
    画面から決める手段が無いため(smile module docstringと同じ制約)。窓は映像から作る —
    DBの ``collab_windows`` はLinkMic channelの有無であって人数ではなく、実測で
    ``guests_max`` が811窓中805窓で0のままだった。
    """
    profile = await laugh_audio.ensure_laugh_profile(path)
    exclude_spans = None
    if int(runtime.settings.get("clip_candidate_laugh_audio_solo_only")):
        # 顔検出のmodelが無ければ SmileError がそのまま上がる。ここで黙って除外なしに
        # 落とすと、「コラボを外した候補」として外れていない候補を渡すことになる。
        faces_profile = await smile.ensure_smile_profile(path)
        exclude_spans = smile.multi_face_spans(faces_profile)
    seconds = [
        laugh_audio.laugh_seconds(profile, to_pts(bucket["start"]),
                                  to_pts(bucket["start"] + bucket_seconds),
                                  exclude_spans=exclude_spans)
        for bucket in buckets
    ]
    outside = next((i for i, value in enumerate(seconds) if value is None), None)
    if outside is not None:
        return {"bucket_start": buckets[outside]["start"],
                "laugh_duration_seconds": profile["duration_seconds"]}
    for bucket, value in zip(buckets, seconds):
        bucket["laugh_audio"] = value
    return None


async def _attach_smile(path: Path, buckets: list, bucket_seconds: int,
                        to_pts) -> Optional[dict]:
    """各bucketへ ``smile``(窓内で笑顔と判定できた秒数)を載せる。

    ``laugh_audio`` と同じく動画時間軸なので、bucketの窓を写してから引く。

    「笑顔」と名乗れるのは**顔がちょうど1つ映っている標本だけ**である(smile module
    docstring: 配信者を画面から特定する手段が無く、battle・collabでは複数の顔が映る)。
    判定できない標本は数えないので、そういう区間の値は実際より小さく出る。
    """
    profile = await smile.ensure_smile_profile(path)
    seconds = [
        smile.smile_seconds(profile, to_pts(bucket["start"]),
                            to_pts(bucket["start"] + bucket_seconds))
        for bucket in buckets
    ]
    outside = next((i for i, value in enumerate(seconds) if value is None), None)
    if outside is not None:
        return {"bucket_start": buckets[outside]["start"],
                "smile_duration_seconds": profile["duration_seconds"]}
    for bucket, value in zip(buckets, seconds):
        bucket["smile"] = value
    return None


# 素材由来のper-bucket指標。足すときはengine側を書いてからここへ1 entry追加する。
_MATERIAL_METRICS = (
    _MaterialMetric(
        key="laugh_audio",
        setting="clip_candidate_laugh_audio",
        weight_setting="clip_candidate_laugh_audio_weight",
        min_setting="clip_candidate_laugh_audio_min_seconds",
        label=lambda item: f"笑い声{item['laugh_audio']:g}秒",
        attach=_attach_laugh_audio,
    ),
    _MaterialMetric(
        key="smile",
        setting="clip_candidate_smile",
        weight_setting="clip_candidate_smile_weight",
        min_setting="clip_candidate_smile_min_seconds",
        label=lambda item: f"笑顔{item['smile']:g}秒",
        attach=_attach_smile,
    ),
)

# 候補badgeの文言。指標を足したらここも足すこと(素通りするとKeyErrorで気付ける)。
_CANDIDATE_LABELS = {
    "diamonds": lambda item: f"ダイヤ{item['diamonds']}",
    "comments": lambda item: f"コメント{item['comments']}",
    "audio_peak": lambda item: "音量",
    "laugh_comment": lambda item: f"笑い{item['laugh_comment']}",
    **{metric.key: metric.label for metric in _MATERIAL_METRICS},
}
# 窓が重なった候補を畳むときに、代表となった窓から引き継ぐkey。
_CANDIDATE_REPRESENTATIVE_KEYS = (
    "zscore", "metric", "diamonds", "comments", "ratio", "silent_ratio", "laugh_comment",
    *(metric.key for metric in _MATERIAL_METRICS),
)


def _attach_laugh_comments(session_id: int, buckets: list, bucket_seconds: int) -> None:
    """各bucketへ ``laugh_comment``(笑いcommentの件数)を載せる。

    bucketsへ列を足さないのは、判定patternを運用しながら調整するものだからで、patternを
    変えるたびにschema migrationと全session backfillが要る設計は誤りである。3時間・comment
    2万件でも正規表現の走査は数十msで済む。

    丸めは ``CAST(time / bs) * bs``(storage._rebuild_buckets_locked)と同じ式を使う。
    独自に丸めると既存bucketと1つずれる。
    """
    compiled = laugh_text.compile_patterns(min_w_run=get_laugh_comment_min_w_run())
    starts = {b["start"] for b in buckets}
    counts: dict = {}
    bodies = []
    rows = []
    for event in runtime.storage.iter_events(session_id, kinds=("comment",)):
        # 旧録画は text 列に入っている(storage側もCOALESCEで両方見ている)。
        body = (event.get("comment") or event.get("text") or "").strip()
        if not body:
            continue
        rows.append((int(event["time"] // bucket_seconds) * bucket_seconds, body))
        bodies.append(body)
    templates = laugh_text.template_bodies(bodies)
    for start, body in rows:
        if start not in starts or body in templates:
            continue
        if laugh_text.classify(body, compiled) is not None:
            counts[start] = counts.get(start, 0) + 1
    for bucket in buckets:
        bucket["laugh_comment"] = counts.get(bucket["start"], 0)


async def _attach_material_metrics(recording_id: int, path: Path, buckets: list,
                                   bucket_seconds: int, to_pts, metrics: tuple,
                                   weights: dict, min_values: dict) -> tuple:
    """有効になっている素材由来の指標を各bucketへ載せ、判定に使うmetricsを返した上で
    ``weights`` / ``min_values`` へその指標ぶんを書き込む。

    下限(min_values)は指標ごとに必須である。素材由来の指標はどれもほとんどの窓で0なので、
    下限が無いとごく僅かな検出が大きなz-scoreを叩いて候補を占領する(spike.detect_spikes)。
    """
    for metric in _MATERIAL_METRICS:
        if not int(runtime.settings.get(metric.setting)):
            continue
        try:
            skipped = await metric.attach(path, buckets, bucket_seconds, to_pts)
        except hls_source.SourceMissing as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except RuntimeError as exc:
            # 有効なのに解析できない(model未配置・engine未導入・解析失敗)ならここで失敗を
            # 返す。黙って先へ進めると「その指標では盛り上がりが無かった」結果と見分けが
            # 付かず、笑いを見ているつもりで見ていない候補一覧を渡すことになる。
            raise HTTPException(status_code=503, detail=str(exc))
        if skipped is not None:
            runtime.logger.info(
                "切り抜き候補: %s の指標をrecording %s では判定から外しました"
                "（解析した素材の外に出るbucketがあります）", metric.key, recording_id,
                extra={"event": "clip.material_metric_skipped",
                       "ctx": {"recording_id": recording_id, "metric": metric.key,
                               **skipped}},
            )
            continue
        metrics = metrics + (metric.key,)
        weights[metric.key] = float(runtime.settings.get(metric.weight_setting))
        min_values[metric.key] = float(runtime.settings.get(metric.min_setting))
    return metrics


def _merge_candidates(items: list) -> list:
    """時刻順に並んだ候補のうち、範囲が重なるものを1つへ畳む。移動窓は1 bucketずつずれた
    窓を連続で拾うため、畳まないと同じ盛り上がりが何本ものclipになる。"""
    merged: list = []
    for item in sorted(items, key=lambda c: c["start"]):
        if merged and item["start"] <= merged[-1]["end"]:
            prev = merged[-1]
            prev["end"] = max(prev["end"], item["end"])
            if item["zscore"] > prev["zscore"]:
                # 代表値は最も外れている窓のものを残す(合算すると窓の重なりを二重に数える)。
                prev.update({k: item[k] for k in _CANDIDATE_REPRESENTATIVE_KEYS
                             if k in item})
            continue
        merged.append(dict(item))
    return merged


async def compute_clip_candidates(recording_id: int) -> dict:
    """録画窓の盛り上がりから切り出し候補を出す。時刻は動画時間軸(秒)。

    判定は core.spike で、窓だけを設定の秒数へ広げる。窓に入るbucket数はsessionのbucket幅から導くので、bucket幅の違う
    session間でも窓の実長は揃う。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    window_seconds = int(runtime.settings.get("clip_candidate_window_seconds"))
    pad_before = int(runtime.settings.get("clip_pad_before_seconds"))
    pad_after = int(runtime.settings.get("clip_pad_after_seconds"))
    lead = int(runtime.settings.get("clip_candidate_lead_seconds"))
    empty = {"recording_id": recording_id, "window_seconds": window_seconds,
             "pad_before_seconds": pad_before, "pad_after_seconds": pad_after,
             "lead_seconds": lead, "candidates": []}
    session_id = recording.get("session_id")
    if session_id is None:
        return empty
    session = await asyncio.to_thread(runtime.storage.get_session, session_id)
    if session is None:
        return empty
    bucket_seconds = session.get("bucket_seconds")
    if not bucket_seconds:
        # bucket幅が無いsessionは窓のbucket数を出せない。推測で埋めると窓の実長が嘘になる。
        return empty
    started_at = recording["started_at"]
    ended_at = recording.get("ended_at")
    buckets = await asyncio.to_thread(
        runtime.storage.session_buckets,
        session_id,
        started_at,
        ended_at,
    )
    window_buckets = spike.window_bucket_count(bucket_seconds, window_seconds)
    path = files._resolved_recording_path(recording)
    to_pts = await asyncio.to_thread(
        indexer.build_time_mapper_sync, path, started_at, ended_at,
        indexer.mapper_video_duration(path, recording))
    # 指標は設定で増える(音声・映像・笑い)。要素数まで固定した型にすると、
    # 足すたびに型が変わったと言われる。
    metrics: tuple = spike.METRICS
    profile = None
    if int(runtime.settings.get("clip_candidate_audio")):
        try:
            profile = await ensure_audio_profile(path)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        # 音声は動画時間軸なので、各bucketの窓を動画時間へ写してからpeakを引く。
        # 録画の外へ落ちるbucketがあるとlevelの取れない窓ができるため、その録画では
        # 音声を判定から外す(0で埋めると「無音だった」という観測を作ってしまう)。
        outside = next((b for b in buckets
                        if level_peak(profile, to_pts(b["start"]),
                                      to_pts(b["start"] + bucket_seconds)) is None), None)
        if outside is None:
            for bucket in buckets:
                bucket["audio_peak"] = level_peak(
                    profile, to_pts(bucket["start"]),
                    to_pts(bucket["start"] + bucket_seconds))
            metrics = metrics + ("audio_peak",)
        else:
            runtime.logger.info(
                "切り抜き候補: 音声の指標をrecording %s では判定から外しました"
                "（録音の外に出るbucketがあります）", recording_id,
                extra={"event": "clip.audio_metric_skipped",
                       "ctx": {"recording_id": recording_id,
                               "bucket_start": outside["start"],
                               "audio_duration_seconds": profile["duration_seconds"]}},
            )
    weights: dict = {}
    min_values: dict = {}
    if int(runtime.settings.get("clip_candidate_laugh_comment")):
        await asyncio.to_thread(
            _attach_laugh_comments, session_id, buckets, bucket_seconds)
        metrics = metrics + ("laugh_comment",)
        weights["laugh_comment"] = float(runtime.settings.get("clip_candidate_laugh_weight"))
        # 笑いの系列はほぼ全てが0で標準偏差が極小になるため、下限を置かないと
        # 「ほとんど笑わない配信のたった1件」がzを叩いて候補を占領する。
        min_values["laugh_comment"] = float(
            runtime.settings.get("clip_candidate_laugh_min_comments"))
    metrics = await _attach_material_metrics(
        recording_id, path, buckets, bucket_seconds, to_pts, metrics, weights, min_values)
    found = spike.detect_spikes(
        buckets, window_buckets=window_buckets, metrics=metrics,
        zscore_min=float(runtime.settings.get("clip_candidate_zscore")),
        weights=weights or None, min_values=min_values or None)
    if not found:
        return empty
    video_seconds = await _duration_seconds(path)
    span = bucket_seconds * window_buckets
    items = []
    for candidate in found:
        start = to_pts(candidate["start"]) - lead - pad_before
        end = to_pts(candidate["start"] + span) + pad_after
        start = max(0.0, start)
        if video_seconds is not None:
            end = min(end, video_seconds)
        if end <= start:
            continue
        item = {
            "start": round(start, 2),
            "end": round(end, 2),
            "zscore": round(candidate["zscore"], 2),
            "metric": candidate["metric"],
            "ratio": round(candidate["ratio"], 2),
            "diamonds": int(candidate["values"]["diamonds"]),
            "comments": int(candidate["values"]["comments"]),
            # 生値を並記する。「なぜこの候補なのか」をその場で反証できる状態にしておく
            # (候補が的外れでも気付きにくい種類の機能なので、表示は検証手段でもある)。
            "laugh_comment": int(candidate["values"].get("laugh_comment", 0)),
        }
        # 素材由来の指標は、載せられた録画にだけkeyを付ける。判定していない録画でも0を
        # 入れると、画面には「笑い声0秒」と出て検出していないことが読めなくなる。
        for metric in _MATERIAL_METRICS:
            if metric.key in candidate["values"]:
                item[metric.key] = round(float(candidate["values"][metric.key]), 2)
        items.append(item)
    merged = _merge_candidates(items)
    merged.sort(key=lambda c: c["zscore"], reverse=True)
    limit = int(runtime.settings.get("clip_candidate_limit"))
    for item in merged:
        item["label"] = _CANDIDATE_LABELS[item["metric"]](item)
        if profile is not None:
            # 無音割合は畳んだ後の区間で測る。代表窓の値を引き継ぐと、窓が伸びた分の
            # 無音が数に入らず実態とずれる。判定できなければNoneのまま。
            item["silent_ratio"] = silent_ratio(profile, item["start"], item["end"])
    return {**empty, "candidates": merged[:limit]}
