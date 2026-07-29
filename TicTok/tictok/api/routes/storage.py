"""容量・空き・退避・保持policyのroute。計算は ``tictok.api.disk`` にある。

ここが持つのは同時実行を防ぐlockと、進捗を出すためのjob登録と、応答の形。
"""

import asyncio
import time
from typing import Optional
from fastapi import HTTPException
from pydantic import BaseModel
from tictok.record import disk_scan, retention
from tictok.record.upscale import cleanup_upscale_files, upscale_artifact_paths
from tictok.core.progress import JobProgress, RETENTION_PHASES
from tictok.storage import OPS_INFO, OPS_WARNING
from tictok.record.video_overlay import (cleanup_overlay_files, overlay_artifact_paths,
    overlay_transient_paths)
from fastapi import APIRouter
from tictok.api import disk
from tictok.api import files
from tictok.api import fsfacts
from tictok.api import media_jobs
from tictok.api import runtime

router = APIRouter()


@router.get("/api/storage/relocate")
async def relocation_plan_api() -> dict:
    """working dir に残っている完了録画の一覧(dry-run)。実行はPOSTのみ。"""
    return await asyncio.to_thread(disk._relocation_plan)


class RelocateRequest(BaseModel):
    confirm: bool = False


@router.post("/api/storage/relocate")
async def relocate_api(request: RelocateRequest) -> dict:
    """完了録画を最終保存先へ退避する。confirmが無ければdry-runの結果だけを返す。"""
    if not disk._relocation_enabled():
        raise HTTPException(
            status_code=409,
            detail="最終保存先が設定されていません（作業先と同じため退避先がありません）。")
    plan = await asyncio.to_thread(disk._relocation_plan)
    if not request.confirm:
        return {"applied": False, "plan": plan}
    if not plan["items"]:
        return {"applied": False, "plan": plan}
    async with runtime._tracked_job("storage", "最終保存先へ退避") as job_id:
        loop = asyncio.get_running_loop()

        def _on_item(done: int, total: int, item: Optional[dict]) -> None:
            pct = int(done * 100 / total) if total else 100
            label = f"{done:,}/{total:,}本"
            if item is not None:
                label += f"  {item['filename']}"
            asyncio.run_coroutine_threadsafe(runtime.jobs.progress(job_id, pct, stage=label), loop)

        result = await asyncio.to_thread(disk._run_relocation, plan, _on_item)
        await asyncio.to_thread(
            runtime.storage.record_ops_event,
            runtime.logger,
            "storage.relocated",
            "{moved}本の録画（{gb:.1f}GB）を最終保存先へ退避しました{failed}".format(
                moved=result["moved"], gb=result["moved_bytes"] / (1024 ** 3),
                failed=f"。{len(result['failures'])}本は失敗しました" if result["failures"] else ""),
            severity=OPS_WARNING if result["failures"] else OPS_INFO,
            job_id=job_id,
            detail={"moved": result["moved"], "moved_bytes": result["moved_bytes"],
                    "failures": result["failures"], "final_dir": str(runtime.FINAL_DIR)},
        )
    return {"applied": True, "result": result,
            "plan": await asyncio.to_thread(disk._relocation_plan)}


@router.get("/api/capacity")
async def capacity_api() -> dict:
    """容量の現況・時系列・満杯予測(区間)・転写/出力の完了率。"""
    return await asyncio.to_thread(disk._capacity_report)


@router.post("/api/capacity/sample")
async def capacity_sample_api() -> dict:
    """容量snapshotを1件記録する。日次の自動sampleと同じ内容を手動で採る。"""
    payload = await asyncio.to_thread(disk._capacity_snapshot)
    sample = await asyncio.to_thread(runtime.storage.add_capacity_sample, payload)
    report = await asyncio.to_thread(disk._capacity_report)
    await asyncio.to_thread(disk._capacity_alert_check, report)
    return {"sampled_at": sample["sampled_at"], "report": report}


@router.get("/api/disk")
async def disk_status_api() -> dict:
    """録画・出力が使うdrive別の空き容量と、出力を拒否する下限。画面に常時表示する。"""
    return disk._disk_report()


# ---- 容量内訳と保持policy(retention) ----------------------------------------------
# 走査は数TB規模のHDDで分単位かかるblocking I/O。GETは常にDBのcacheを返し、再走査は
# operatorの明示操作だけが起こす。削除も同様で、設定値だけでは何も消えない: 必ずdry-run
# (POST /api/storage/retention) の結果を見せ、確認付きのapplyでのみ実行する。
_storage_scan_lock = asyncio.Lock()
_retention_lock = asyncio.Lock()


class RetentionRequest(BaseModel):
    # 既定がdry-runなのは意図的。bodyを付け忘れたrequestが削除を走らせてはならない。
    apply: bool = False
    confirm: bool = False


class ProtectRequest(BaseModel):
    protected: bool


@router.get("/api/storage/usage")
async def storage_usage_api() -> dict:
    """保存済みの容量内訳(配信者別・種別別)。まだ走査していなければ scan は null で返す。"""
    cached = await asyncio.to_thread(runtime.storage.get_storage_scan)
    return {
        "scan": cached,
        "roots": [str(root) for root in runtime._RECORD_ROOTS],
        "disk": disk._disk_report(),
        "scanning": _storage_scan_lock.locked(),
    }


@router.post("/api/storage/scan")
async def storage_scan_api() -> dict:
    """録画root配下を走査し直して容量内訳のcacheを更新する。数TB規模では分単位かかる。"""
    if _storage_scan_lock.locked():
        raise HTTPException(status_code=409, detail="容量の再scanが既に実行中です。")
    async with _storage_scan_lock:
        async with runtime._tracked_job("storage", "容量scan") as job_id:
            started = time.monotonic()
            usage = await asyncio.to_thread(disk_scan.scan_roots, runtime._RECORD_ROOTS)
            duration_ms = (time.monotonic() - started) * 1000
            await asyncio.to_thread(runtime.storage.save_storage_scan, usage, duration_ms)
            await asyncio.to_thread(
                runtime.storage.record_ops_event,
                runtime.logger,
                "storage.scan_completed",
                "使用量のscanが完了しました: {files}file / {gb:.1f}GB".format(
                    files=usage["total_files"], gb=usage["total_bytes"] / (1024 ** 3)),
                job_id=job_id,
                duration_ms=duration_ms,
                detail={"total_bytes": usage["total_bytes"],
                        "total_files": usage["total_files"],
                        "streamers": len(usage["streamers"]),
                        "errors": len(usage["errors"])},
            )
    return await storage_usage_api()


@router.post("/api/storage/retention")
async def storage_retention_api(request: RetentionRequest) -> dict:
    """保持policyのdry-run(既定)と実行。実行には apply と confirm の両方が要る。

    削除順序は (1)中断renderの残骸 (2)作り直せる派生物 (3)再取得不能な原本 で固定する。原本を
    先に消すと再出力も文字起こしも復旧できなくなるため、順序は入れ替えない。どのfileが原本かは
    録画ごとに違う(素材が残る録画では原本は.tsで、mp4は②の派生物)。"""
    if _retention_lock.locked():
        raise HTTPException(status_code=409, detail="保持policyの処理が既に実行中です。")
    async with _retention_lock:
        plan = await asyncio.to_thread(disk._build_retention_plan)
        if not request.apply:
            await asyncio.to_thread(
                runtime.storage.record_ops_event,
                runtime.logger,
                "retention.previewed",
                "保持rulesの試算: {items}件 / {gb:.1f}GBが削除対象です（fileは消していません）".format(
                    items=plan["total_items"], gb=plan["total_bytes"] / (1024 ** 3)),
                detail={"rules": plan["rules"], "total_bytes": plan["total_bytes"],
                        "by_phase": {p["phase"]: {"items": len(p["items"]),
                                                  "bytes": p["bytes"],
                                                  "enabled": p["enabled"]}
                                     for p in plan["phases"]}},
            )
            return {"applied": False, "plan": plan}
        if not request.confirm:
            raise HTTPException(status_code=400,
                                detail="削除内容の確認が取れていません。dry-runの結果を確認してから実行してください。")
        # 焼き込みが動いている間のsidecarは「残骸」ではなく実行中のfileなので、GPU jobの
        # 有無を見て中断renderの掃除を丸ごと見送る(経過時間の猶予だけでは足りない)。
        if media_jobs._media_job_running():
            raise HTTPException(status_code=409,
                                detail="焼き込み/Up出力の実行中は保持policyを実行できません。完了後に再実行してください。")
        async with runtime._tracked_job("retention", "保持policyの実行") as job_id:
            loop = asyncio.get_running_loop()

            async def _retention_progress(pct: int, stage: str) -> None:
                await runtime.jobs.progress(job_id, pct, stage=stage)

            progress = JobProgress(_retention_progress, RETENTION_PHASES)
            for phase in plan["phases"]:
                # 無効なphase・対象0件のphaseを重みに残すと、実行するphaseだけでは
                # 100%へ届かない。
                if not phase["enabled"] or not phase["items"]:
                    progress.disable(phase["phase"])

            def _on_item(key: str, done: int, total: int) -> None:
                asyncio.run_coroutine_threadsafe(
                    progress.set(key, done / total if total else 1.0,
                                 f"{done:,}/{total:,}件"), loop)

            result = await asyncio.to_thread(disk._apply_retention, plan, _on_item)
            # 消したのはmp4・派生物・素材で、いずれも一括画面が種別ごとに数えているfile。
            # TTL cacheを残すと、消えたものを在るものとして数え続ける。
            fsfacts._fs_state_cache.clear()
            fsfacts._fs_bulk_cache.clear()
            fsfacts._bulk_status_cache.clear()
            await progress.finish("削除結果を集計中")
            await asyncio.to_thread(
                runtime.storage.record_ops_event,
                runtime.logger,
                "retention.applied",
                "保持rulesを適用しました: {items}件を削除し {gb:.1f}GBを空けました{stop}".format(
                    items=result["removed_items"], gb=result["freed_bytes"] / (1024 ** 3),
                    stop=f"（{result['stopped_at']} で打ち切り）" if result["stopped_at"] else ""),
                job_id=job_id,
                detail={"rules": plan["rules"], "removed": result["removed"],
                        "stopped_at": result["stopped_at"],
                        "free_target_bytes": plan["free_target_bytes"]},
            )
    return {"applied": True, "plan": plan, "result": result, "disk": disk._disk_report()}


@router.post("/api/recordings/{recording_id}/protect")
async def protect_recording(recording_id: int, request: ProtectRequest) -> dict:
    """保持policyの自動削除からこの録画を除外する(または除外を解除する)。"""
    if not await asyncio.to_thread(
            runtime.storage.set_recording_protected, recording_id, request.protected):
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    await asyncio.to_thread(
        runtime.storage.record_ops_event,
        runtime.logger,
        "retention.protection_changed",
        f"録画の保護を{'有効' if request.protected else '解除'}にしました",
        recording_id=recording_id,
        detail={"protected": request.protected},
    )
    return {"recording_id": recording_id, "protected": request.protected}


@router.delete("/api/recordings/{recording_id}/derived")
async def delete_recording_derived(recording_id: int) -> dict:
    """この録画の派生物(焼き込み・Up出力・renderの中間file)だけを消し、元録画は残す。

    既存のDELETEは元録画ごと消すため、容量を空けたいだけの操作にはこちらを使う。"""
    recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="録画が見つかりません。")
    path = files._safe_recording_path(recording["path"])
    freed = await asyncio.to_thread(
        retention.artifact_bytes,
        overlay_artifact_paths(path) + overlay_transient_paths(path)
        + upscale_artifact_paths(path),
    )
    await asyncio.to_thread(cleanup_overlay_files, path)
    await asyncio.to_thread(cleanup_upscale_files, path)
    await asyncio.to_thread(
        runtime.storage.record_ops_event,
        runtime.logger,
        "retention.derived_removed",
        f"録画 {files._recording_label(recording)} の派生file（焼き込み・切り抜き等）を削除しました",
        recording_id=recording_id,
        detail={"freed_bytes": freed, "stem": path.stem},
    )
    return {"recording_id": recording_id, "freed_bytes": freed}
