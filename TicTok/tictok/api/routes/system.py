"""server自身の設定・通知・運用event(ops)・性能計測・DB保守。

録画や配信者ではなく「serverの状態」を扱うroute。DB保守は同時実行を1本に絞るため、
lockもここが持つ。
"""

import asyncio
import time
from contextlib import contextmanager
from typing import Optional
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from tictok.core.config import (get_db_backup_before_migration, get_db_backup_keep,
    get_db_path, get_log_slow_http_ms, get_ops_badge_window_hours,
    get_ops_events_detail_max_chars, get_ops_events_query_limit, get_ops_events_retention_days)
from tictok.core import dbmaint
from tictok.core import ops_labels
from tictok.core import perf
from tictok.record import telop_preview, telop_styles
from tictok.storage import OPS_ERROR, OPS_INFO, OPS_WARNING
from fastapi import APIRouter
from tictok.api import runtime

router = APIRouter()


@router.get("/api/settings")
async def get_settings_api() -> dict:
    return {"settings": runtime.settings.describe()}


@router.get("/api/settings/telop-preview/{value}.png")
async def telop_preview_image(value: int) -> FileResponse:
    """テロップpresetの見本画像。設定画面が選択肢ごとに読みに来る。

    本番と同じlibass経路で焼く(telop_preview参照)。初回は書体の取得とffmpegが走るぶん
    数百msかかるが、以降はcacheをそのまま返す。"""
    try:
        style = telop_styles.style_for(value)
    except ValueError:
        raise HTTPException(status_code=404, detail="そのテロップpresetはありません。")
    try:
        path = await telop_preview.ensure_preview(style)
    except RuntimeError as exc:
        # 書体を取得できない・ffmpegが無い。serverの不具合ではないので、画面が
        # 「見本を出せない」と分かる形で返す(見本が出ないだけでpresetは選べる)。
        raise HTTPException(status_code=503, detail=str(exc))
    # 定義が変わればfile名の署名が変わるので、cacheさせて構わない。
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.put("/api/settings")
async def update_settings_api(values: dict) -> dict:
    try:
        updated = runtime.settings.update(values)
    except ValueError as exc:
        # The operator's intended change did not take effect. Info, not warning: the
        # request is rejected with the reason and nothing in the system is degraded.
        # Keys only — the rejected value is already in the message.
        runtime.logger.info(
            "設定の更新を却下しました: %s", exc,
            extra={"event": "process.settings_update_rejected",
                   "ctx": {"keys": sorted(values), "reason": str(exc)}},
        )
        raise HTTPException(status_code=422, detail=str(exc))
    return {"settings": runtime.settings.describe(), "values": updated}


# ---- 通知(webhook) ----
# 宛先URLは.env側にあるので画面からは変更できない。画面が答えられる必要があるのは
# 「宛先は設定されているか」「実際に届くか」の2つだけで、後者は実送信でしか確かめられない。


@router.get("/api/notify/status")
async def notify_status_api() -> dict:
    try:
        return runtime.notifier.status()
    except ValueError as exc:
        # TICTOK_NOTIFY_WEBHOOK_FORMAT が不正。既定へ黙って倒すと、届かない理由が画面から
        # 一切見えなくなる。理由をそのまま返す。
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/api/notify/test")
async def notify_test_api() -> dict:
    try:
        return await runtime.notifier.send_test()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---- 運用log(ops_events viewer) ----
# 録画失敗・接続断・設定変更・jobの開始完了は全てops_eventsへ貯まっているが、これまで
# 読み出す導線が無かった。表はFKを張らずsession削除後も行が残るため、session_unique_idが
# NULLの行(=対象が削除済み)が正常に存在する。
OPS_SEVERITIES = (OPS_ERROR, OPS_WARNING, OPS_INFO)
# 設定変更履歴。同じendpointをkind前方一致で絞って使う。
OPS_SETTINGS_KIND = "process.settings_updated"


@router.get("/api/ops/events")
async def list_ops_events_api(
    severity: str = "",
    min_severity: str = "",
    kind_prefix: str = "",
    unique_id: str = "",
    session_id: Optional[int] = None,
    job_id: str = "",
    since: Optional[float] = None,
    until: Optional[float] = None,
    limit: Optional[int] = None,
    before_ts: Optional[float] = None,
    before_id: Optional[int] = None,
) -> dict:
    # severityは1段だけを見る指定、min_severityは「warning以上」の閾値指定。用途が違うので
    # 別のparameterにする(片方に寄せると"error のみ"が表現できない)。
    for name, value in (("severity", severity), ("min_severity", min_severity)):
        if value and value not in OPS_SEVERITIES:
            raise HTTPException(status_code=422,
                                detail=f"不明な{name}: {value}")
    max_page_size = max(1, get_ops_events_query_limit())
    page_size = max(1, min(int(limit), max_page_size)) if limit else max_page_size
    events = await asyncio.to_thread(
        runtime.storage.list_ops_events,
        limit=page_size,
        severity=severity or None,
        min_severity=min_severity or None,
        kind_prefix=kind_prefix or None,
        unique_id=unique_id or None,
        session_id=session_id,
        job_id=job_id or None,
        since=since,
        until=until,
        before_ts=before_ts,
        before_id=before_id,
    )
    # 次ページのkeyset。最後の行の(ts,id)を渡してもらう方式にし、offsetは使わない
    # (この表は末尾に行が増え続けるのでoffsetでは境界が重複・欠落する)。
    last = events[-1] if events else None
    return {
        "events": events,
        "limit": page_size,
        "next": ({"before_ts": last["ts"], "before_id": last["id"]}
                 if last is not None and len(events) >= page_size else None),
        "severities": list(OPS_SEVERITIES),
        "detail_max_chars": get_ops_events_detail_max_chars(),
        "retention_days": get_ops_events_retention_days(),
        "settings_kind": OPS_SETTINGS_KIND,
        # kindは機械key。画面に出す日本語はここから引く(表に無いkindは生値のまま出す)。
        "kind_labels": ops_labels.KIND_LABELS,
    }


@router.get("/api/ops/kinds")
async def list_ops_kinds_api(hours: Optional[float] = None) -> dict:
    """絞り込みの候補(種別・配信者)。どちらも実データから出し、候補を捏造しない。
    同じ観測窓の候補を2度requestしないよう1つのendpointで返す。"""
    since = time.time() - float(hours) * 3600 if hours else None
    kinds = await asyncio.to_thread(runtime.storage.ops_event_kinds, since=since)
    unique_ids = await asyncio.to_thread(runtime.storage.ops_event_unique_ids, since=since)
    return {"kinds": kinds, "unique_ids": unique_ids, "since": since,
            "kind_labels": ops_labels.KIND_LABELS}


@router.get("/api/ops/summary")
async def ops_summary_api(hours: Optional[float] = None) -> dict:
    """header badge用の軽量COUNT。DB照会に失敗したらここで500を返す。0件として握り潰すと
    「何も壊れていない」という嘘の表示になる。"""
    window = float(hours) if hours else float(get_ops_badge_window_hours())
    since = time.time() - window * 3600
    counts = await asyncio.to_thread(
        runtime.storage.count_ops_events_by_severity, since=since)
    return {
        "since": since,
        "window_hours": window,
        "counts": {level: int(counts.get(level, 0)) for level in OPS_SEVERITIES},
    }


# ---- API所要時間 ----
# route別の計測は process内のメモリにしか無い(DBへ落とすと、測っている本人が一番重い
# 書き込みを増やす)。再起動で消えるのは仕様で、「今のprocessが何に時間を使っているか」
# だけを答える。長期の記録が要るならJSONL logのhttp.perf_rollup行が残っている。


@router.get("/api/perf")
async def perf_api(limit: int = 0) -> dict:
    """route別の所要時間。合計時間の降順(＝直すと効く順)で返す。"""
    return {**perf.snapshot(limit=limit), "config": perf.env_summary(),
            "slow_http_ms": get_log_slow_http_ms()}


@router.delete("/api/perf")
async def perf_reset_api() -> dict:
    """計測を捨てて測り直す。修正の前後を比べるときは、これで区間を切ってから操作する
    (起動からの累計のままだと、直した後の速い呼び出しが古い遅い呼び出しに薄められる)。"""
    result = await asyncio.to_thread(perf.reset)
    runtime.logger.info(
        "API所要時間の計測をresetしました（route %d件）", result["cleared_routes"],
        extra={"event": "http.perf_reset", "ctx": result},
    )
    return result


# ---- DB保守(退避・健全性check・VACUUM) ----
# 録画mp4は失えば再取得できないが作り直せる導線がある。DBは違い、eventも解析結果も設定も
# ここにしか無い。退避はSQLiteのbackup APIで無停止に取り、file copyはしない(WAL mode では
# tictok.db単体のcopyは古い・破れた像になる)。
# lockはruntimeが持つ。配信終了後の自動退避(startup)も同じlockを取るためで、ここだけの
# lockにすると自動のsnapshotと手動のVACUUMが重なる。
_maintenance_lock = runtime.maintenance_lock


class VacuumRequest(BaseModel):
    # 既定がFalseなのは意図的。bodyを付け忘れたrequestで、全書き込みを止めるVACUUMが
    # 走ってはならない。
    confirm: bool = False


def _maintenance_busy() -> None:
    if _maintenance_lock.locked():
        raise HTTPException(status_code=409, detail="DB保守の処理が既に実行中です。")


@contextmanager
def _maintenance_failure(kind: str, job_id: str):
    """保守操作の失敗をops_eventsへ残してから500にする。

    ここで握らずに素通しすると、DBが壊れている・容量が無いという最も残したい失敗だけが
    表に1行も残らない。stack traceはlog側(exc_info)へ出す。"""
    try:
        yield
    except Exception as exc:
        runtime.storage.record_ops_event(
            runtime.logger, f"maintenance.{kind}_failed",
            f"{ops_labels.maintenance_label(kind)}に失敗しました: {exc}",
            severity=OPS_ERROR, job_id=job_id,
            detail={"error": type(exc).__name__}, exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/api/maintenance/status")
async def maintenance_status_api() -> dict:
    db = await asyncio.to_thread(runtime.storage.db_file_status)
    backups = await asyncio.to_thread(dbmaint.list_backups)
    # 見張りと世代の層はどちらもfile(退避先の台帳・退避folderの一覧)を読む。event loopの
    # 上で読むとnetwork driveの退避先で止まるので、他と同じくthreadへ逃がす。
    guard = await asyncio.to_thread(dbmaint.guard_status)
    scheduled = await asyncio.to_thread(dbmaint.scheduled_layers)
    return {
        "db": db,
        "backups": backups,
        "backup_dir": str(dbmaint.backup_dir()),
        "keep": get_db_backup_keep(),
        "before_migration": get_db_backup_before_migration(),
        "premigration": getattr(runtime.storage, "premigration_backup", None),
        "running": _maintenance_lock.locked(),
        # 行数の見張り(凍結状態と前回の行数)と、暦で層化した自動世代の内訳。
        # 凍結中は世代が増え続けるので、画面がそれを名乗れないと「退避folderが減らない」
        # という別の症状として現れる。
        "guard": guard,
        "scheduled": scheduled,
    }


@router.post("/api/maintenance/backup")
async def maintenance_backup_api() -> dict:
    """稼働中のままsnapshotを1世代取る。SQLiteのbackup APIで読むので収集は止まらない。"""
    _maintenance_busy()
    async with _maintenance_lock:
        async with runtime._tracked_job("maintenance", "DB退避") as job_id:
            # 退避はbuffer済みのrowを含んだ像であるべきなので、batch writerを先に吐き切らせる。
            await asyncio.to_thread(runtime.storage.flush)
            with _maintenance_failure("backup", job_id):
                result = await asyncio.to_thread(
                    dbmaint.create_backup, get_db_path(), reason=dbmaint.REASON_MANUAL
                )
            await asyncio.to_thread(
                runtime.storage.record_ops_event,
                runtime.logger,
                "maintenance.backup_completed",
                "DBの退避を書き出しました: {name}（{gb:.2f}GB）".format(
                    name=result["name"], gb=result["bytes"] / (1024 ** 3)),
                job_id=job_id,
                duration_ms=result["duration_ms"],
                detail={"path": result["path"], "bytes": result["bytes"],
                        "reason": result["reason"], "pruned": result["pruned"]},
            )
            # 行数の急減・刈り取りの凍結はops_eventsへ。record_backup_ops_events に集めて
            # あるのは、退避を呼ぶ経路(画面・migration前・録画確定)のどれから取っても同じ
            # 行が残るようにするため。
            await asyncio.to_thread(
                dbmaint.record_backup_ops_events,
                runtime.storage, runtime.logger, result, job_id=job_id,
            )
    return {"backup": result, "backups": await asyncio.to_thread(dbmaint.list_backups)}


@router.post("/api/maintenance/unfreeze")
async def maintenance_unfreeze_api() -> dict:
    """行数の急減で止めた「古い世代の刈り取り」を再開する。

    人の操作でしか解けない。減った理由が正常(録画の削除・retention)だったのか事故だったのか
    を決められるのは人だけで、時間や次回のsnapshotで自動解除すると、気付く前に解けて気付く
    前に世代が回る —— 凍結を置いた理由がそのまま消える。"""
    _maintenance_busy()
    async with _maintenance_lock:
        async with runtime._tracked_job("maintenance", "退避の刈り取り凍結の解除") as job_id:
            with _maintenance_failure("unfreeze", job_id):
                result = await asyncio.to_thread(dbmaint.unfreeze_prune)
            if result["was_frozen"]:
                await asyncio.to_thread(
                    runtime.storage.record_ops_event,
                    runtime.logger,
                    "maintenance.prune_unfrozen",
                    "退避の刈り取りの凍結を解除しました: {reason}".format(
                        reason=(result["frozen"] or {}).get("reason", "")),
                    job_id=job_id,
                    detail={"frozen": result["frozen"]},
                )
    return {**result, "guard": await asyncio.to_thread(dbmaint.guard_status)}


@router.post("/api/maintenance/integrity-check")
async def maintenance_integrity_api() -> dict:
    """live DBのPRAGMA integrity_check。読み取り専用なので収集中でも安全に走る。"""
    _maintenance_busy()
    async with _maintenance_lock:
        async with runtime._tracked_job("maintenance", "DB健全性check") as job_id:
            with _maintenance_failure("integrity_check", job_id):
                verdict = await asyncio.to_thread(runtime.storage.integrity_check)
            await asyncio.to_thread(
                runtime.storage.record_ops_event,
                runtime.logger,
                "maintenance.integrity_checked",
                "DBの整合性checkは問題なしでした" if verdict["ok"]
                else "DBの整合性checkで問題が見つかりました（{n}件）".format(
                    n=len(verdict["problems"])),
                severity=OPS_INFO if verdict["ok"] else OPS_ERROR,
                job_id=job_id,
                duration_ms=verdict["duration_ms"],
                detail={"ok": verdict["ok"], "problems": verdict["problems"]},
            )
    return verdict


@router.post("/api/maintenance/checkpoint")
async def maintenance_checkpoint_api() -> dict:
    """WALをDB本体へ書き戻してWAL fileを切り詰める。"""
    _maintenance_busy()
    async with _maintenance_lock:
        async with runtime._tracked_job("maintenance", "WAL checkpoint") as job_id:
            with _maintenance_failure("wal_checkpoint", job_id):
                result = await asyncio.to_thread(runtime.storage.wal_checkpoint)
            await asyncio.to_thread(
                runtime.storage.record_ops_event,
                runtime.logger,
                "maintenance.wal_checkpointed",
                "WALを書き戻しました（TRUNCATE）: busy={busy} / {pages}page / "
                "WAL {mb:.1f}MB".format(
                    busy=result["busy"], pages=result["checkpointed_pages"],
                    mb=result["wal_bytes"] / (1024 ** 2)),
                # busy=1は「readerが居て全部は書き戻せなかった」。成功として記録すると、
                # 後でWALが縮んでいない理由が追えなくなる。
                severity=OPS_INFO if result["busy"] == 0 else OPS_WARNING,
                job_id=job_id,
                duration_ms=result["duration_ms"],
                detail=result,
            )
    return result


@router.post("/api/maintenance/vacuum")
async def maintenance_vacuum_api(request: VacuumRequest) -> dict:
    """DB fileを作り直して空き領域を回収する。手動・明示confirmのみ。

    VACUUMは実行中DB全体をexclusive lockで押さえるため、収集中の書き込みが最後まで待たされ、
    一時的にDBとほぼ同じ大きさの作業領域も要る。自動実行の経路は用意しない。"""
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail="VACUUMは実行中の書き込みを全て待たせます。内容を確認してから実行してください。",
        )
    _maintenance_busy()
    async with _maintenance_lock:
        async with runtime._tracked_job("maintenance", "DB VACUUM") as job_id:
            with _maintenance_failure("vacuum", job_id):
                result = await asyncio.to_thread(runtime.storage.vacuum)
            await asyncio.to_thread(
                runtime.storage.record_ops_event,
                runtime.logger,
                "maintenance.vacuumed",
                "DBをVACUUMしました（{gb:.2f}GBを回収）".format(
                    gb=result["freed_bytes"] / (1024 ** 3)),
                job_id=job_id,
                duration_ms=result["duration_ms"],
                detail=result,
            )
    return result
