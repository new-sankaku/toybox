"""容量・空き・退避(final dirへの移送)・保持policyの計算。

「今どれだけ使っているか」「何をどの順で消すか」「どれを最終保管先へ移すか」を、
routeから切り離して置く。route側(``tictok.api.routes.storage``)は lock と job台帳と
応答整形だけを持つ。

依存は runtime / files / fsfacts。
"""

import time
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from tictok.paths import PROJECT_ROOT
from tictok.core.config import get_db_path, get_log_dir
from tictok.core import layout
from tictok.record.recorder import disk_free_by_volume, is_finalizing, Recorder
from tictok.record import retention
from tictok.record.upscale import cleanup_upscale_files
from tictok.core import cancel, capacity
from tictok.storage import OPS_WARNING
from tictok.record.video_overlay import cleanup_overlay_files
from tictok.api import files as api_files
from tictok.api import fsfacts
from tictok.api import runtime


def _disk_volume_paths() -> list:
    """Every volume the running install writes to: the working dir (HLS + capture),
    the final dir (relocation target and where outputs are generated), the DB and the
    logs. These routinely sit on different drives, so only a per-volume reading says
    which one is about to fill up."""
    return [runtime.RECORD_DIR, runtime.FINAL_DIR, get_db_path(), get_log_dir()]


def _disk_min_free_bytes() -> int:
    """Free-space floor below which heavy outputs are refused. Deliberately separate
    from the log-only preflight threshold (get_log_disk_low_bytes): that one warns,
    this one blocks, and an operator who wants a louder warning must not thereby
    change what is allowed to run."""
    return int(runtime.settings.get("disk_min_free_gb")) * 1024 * 1024 * 1024


def _disk_report(paths=None) -> dict:
    """Per-volume free space with the volumes that are already below the floor named.
    ``low_volumes`` is empty when the gate is disabled (floor 0), which keeps the
    "blocked" state and the "measured" state distinguishable in the UI."""
    report = disk_free_by_volume(_disk_volume_paths() if paths is None else paths)
    floor = _disk_min_free_bytes()
    low = sorted(v for v, info in report.items() if info["free_bytes"] < floor) if floor else []
    return {"volumes": report, "min_free_bytes": floor, "low_volumes": low}


def _require_disk_space(paths, stage: str, **ctx) -> None:
    """Refuse to start a job that writes a large intermediate when a volume it needs is
    below the configured floor. Disk exhaustion has surfaced here as symptoms with no
    visible relation to disk (avatars vanishing from a burn-in, emoji turning
    monochrome), so the check runs before the work rather than after the damage."""
    floor = _disk_min_free_bytes()
    if floor <= 0:
        return
    report = disk_free_by_volume(paths)
    low = sorted(v for v, info in report.items() if info["free_bytes"] < floor)
    if not low:
        return
    runtime.logger.warning(
        "%s を拒否しました: %s の空き容量が設定の下限を下回っています", stage, ", ".join(low),
        extra={"event": "disk.gate_blocked",
               "ctx": {"volumes": report, "low_volumes": low, "min_free_bytes": floor,
                       "stage": stage, **ctx}},
    )
    shortest = min(report[v]["free_bytes"] for v in low)
    raise HTTPException(
        status_code=507,
        detail=(f"空き容量が不足しています（{', '.join(low)}: 残り{shortest / (1024 ** 3):.1f}GB / "
                f"下限{floor / (1024 ** 3):.0f}GB）。不要なfileを削除するか、設定の"
                f"「出力を拒否する空き容量の下限（GB）」を見直してください。"),
    )


# ---- 容量の時系列と予測 ------------------------------------------------------------
# 日次のsnapshotを貯めて増加速度から満杯までを見積もる。sampleはfilesystemを走査しない:
# drive空きはO(1)、録画量とDB行数はDBから引ける(実測 全部で48ms)。分単位かかる
# /api/storage/scan とは別物で、あちらを日次で回すことはしない。

def _backup_dir_bytes() -> dict:
    """backups/ の合計。DBのbackupは1本が数百MB規模まで育ち、消し忘れると効いてくる。
    走査対象はbackup先の直下だけなので件数は数十で、日次sampleに含めても安い。"""
    root = PROJECT_ROOT / "backups"
    if not root.is_dir():
        return {"bytes": 0, "files": 0}
    total = 0
    files = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
                files += 1
        except OSError:
            # 走査中に消えたbackupは数えないだけでよい。容量sampleを失敗させる理由はない。
            continue
    return {"bytes": total, "files": files}


def _capacity_snapshot() -> dict:
    """1時点ぶんの容量snapshot。filesystem走査なしで採れるものだけで構成する。"""
    return {
        "disk": _disk_report(),
        "db_files": runtime.storage.db_file_bytes(),
        "backups": _backup_dir_bytes(),
        **runtime.storage.capacity_db_counts(),
    }


def _volume_series(samples: list) -> dict:
    """volume別に (時刻, 空きbytes) の列へ組み替える。"""
    series: dict = {}
    for sample in samples:
        volumes = ((sample.get("payload") or {}).get("disk") or {}).get("volumes") or {}
        for name, info in volumes.items():
            free = info.get("free_bytes")
            if free is None:
                continue
            series.setdefault(name, []).append((sample["sampled_at"], float(free)))
    return series


def _capacity_report() -> dict:
    """容量の現況・時系列・予測・完了率を1つにまとめる。

    予測は必ず区間で返す(core.capacity)。観測が数日しかない段階で「あとX日」と言い切ると、
    それは観測から出た値ではなく作った値になる。
    """
    now_snapshot = _capacity_snapshot()
    samples = runtime.storage.list_capacity_samples(limit=runtime.CAPACITY_HISTORY_LIMIT)
    min_samples = int(runtime.settings.get("capacity_forecast_min_samples"))
    max_extrapolation = float(runtime.settings.get("capacity_forecast_max_extrapolation"))

    forecasts = {}
    volumes_now = now_snapshot["disk"]["volumes"]
    for name, points in _volume_series(samples).items():
        free_now = volumes_now.get(name, {}).get("free_bytes")
        if free_now is None:
            continue
        forecasts[name] = capacity.forecast_days_to_full(
            points, float(free_now),
            min_samples=min_samples, max_extrapolation=max_extrapolation,
        )
    # sampleがまだ無いvolumeも「予測不能」として必ず出す。行が消えていると、
    # 「予測が出ていない」のか「そのvolumeを見ていない」のか区別できない。
    for name, info in volumes_now.items():
        forecasts.setdefault(name, {
            "status": capacity.STATUS_INSUFFICIENT, "n": 0, "observed_days": 0.0,
            "free_bytes": info.get("free_bytes"), "min_samples": min_samples,
            "max_extrapolation": max_extrapolation,
        })

    counts = now_snapshot
    completed = next(
        (r["n"] for r in counts["recordings_by_status"] if r["status"] == "completed"), 0)
    transcribed = counts["transcribed_completed"]
    overlay_done = sum(
        j["n"] for j in counts["media_jobs"]
        if j["kind"] == "overlay" and j["state"] == "completed")
    return {
        "now": now_snapshot,
        "sampled_at": samples[-1]["sampled_at"] if samples else None,
        "samples": samples,
        "forecasts": forecasts,
        # 録画の増加実績はsampleを待たずに遡って出せる(recordingsが最初から持っている)。
        # sample由来の系列とは由来が違うので、payloadでも分けて返す。
        "recording_daily": runtime.storage.recording_bytes_by_day(runtime.CAPACITY_HISTORY_LIMIT),
        # 完了録画がどちらの保存先に何本あるかと、一時保存先の取り残し。容量の話なので
        # ここに載せる。常時見えていれば「移動が呼ばれていない」状態に気付ける。
        "placement": _relocation_summary(),
        "completion": {
            "completed_recordings": completed,
            "transcribed": transcribed,
            "transcribed_rate": capacity.completion_rate(transcribed, completed),
            "overlay_done": overlay_done,
            "overlay_rate": capacity.completion_rate(overlay_done, completed),
        },
    }


def _capacity_alert_check(report: dict) -> None:
    """満杯が近いvolumeをops_eventとして記録する。

    通知経路は新設しない。ops_eventはstorage.set_ops_observer経由で既存の通知rule
    (notify_rule_ops)がそのまま拾うので、severityを正しく付けるだけでよい。
    """
    threshold_days = float(runtime.settings.get("capacity_alert_days"))
    if threshold_days <= 0:
        return
    for name, forecast in report["forecasts"].items():
        if forecast.get("status") != capacity.STATUS_OK:
            continue
        # 区間の下限(最も早く尽きる側)で判定する。点推定で判定すると、区間の下限が
        # 既に閾値を割っていても黙ることになる。
        days_low = forecast.get("days_low")
        if days_low is None or days_low >= threshold_days:
            continue
        runtime.storage.record_ops_event(
            runtime.logger, "capacity.forecast_low",
            "{name} は {low:.0f}〜{high:.0f}日で満杯になる見通しです"
            "（観測 {obs:.1f}日）".format(
                name=name, low=days_low, high=forecast.get("days_high", days_low),
                obs=forecast.get("observed_days", 0.0)),
            severity=OPS_WARNING,
            detail={"volume": name, "days_low": days_low,
                    "days_high": forecast.get("days_high"),
                    "observed_days": forecast.get("observed_days"),
                    "free_bytes": forecast.get("free_bytes"),
                    "threshold_days": threshold_days},
        )


# ---- 最終保存先への移動 ------------------------------------------------------------
# 移送はここが唯一の入口である。finalizeは移送しない: 確定した録画は一時保存先に残り、
# いつ最終保存先へ移すかはこの画面から人が決める。移送の実体は recorder の
# _move_recording_files を使う(moverを二重に持たない)。自動で動く経路が無い以上、
# 一時保存先は放っておけば増え続けるので、本数と容量を容量画面に常時出して気付けるようにする。

def _relocation_enabled() -> bool:
    """退避先が別に設定されているときだけ機能を出す。同一なら移す先が無い。"""
    return runtime.FINAL_DIR != runtime.RECORD_DIR


def _is_under(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def _relocation_plan() -> dict:
    """working dir に残っている完了録画の一覧(dry-run)と、完了録画の所在の内訳。

    mp4が在る録画の容量は**DBのbytesではなく実fileのsize**で出す。実測では16本がDB値と1KB
    以上ずれており、移送量として読むならディスク上の実体が正しい(素材だけの録画は後述の
    とおりDB値で出す)。

    「実体が無い」の判定はmp4の実在では行わない。finalizeはmp4を作らなくなり、録画の実体は
    session dirの ``.ts`` である。mp4だけを見ていたため、**素材しか無い録画は移送計画に一度も
    載らなかった**(実測2026-07-26、finalizeの移送に失敗した1本が作業先に残ったまま、画面の
    「まだ移していない」にも現れなかった)。mp4も素材も無い行だけを除く。実測では working dir
    を指す完了録画132本のうち82本がこれ(retention削除済み)で、件数に混ぜると「82本移せる」
    という嘘になる。
    """
    plan: list = []
    total_bytes = 0
    skipped_missing = 0
    skipped_bytes_unknown = 0
    enabled = _relocation_enabled()
    # 所在の内訳(どちらの保存先に何本あるか)はDBのbytesで出し、fileのstatは取らない。
    # 完了録画は数千本あり、画面を開くたび全件statすると容量画面が数秒待たされる。実測が
    # 要るのは移動対象(作業先の取り残し)だけで、そちらは下で実sizeを測る。
    locations = {key: {"items": 0, "bytes": 0, "unknown_bytes": 0}
                 for key in ("work", "final", "outside")}

    for row in runtime.storage.completed_recordings_with_paths():
        src = Path(row["path"])
        under_work = _is_under(src, runtime.RECORD_DIR)
        if under_work:
            where = "work"
        elif enabled and _is_under(src, runtime.FINAL_DIR):
            where = "final"
        else:
            # record root の外を指す行。移動もretentionも触らないので、内訳では別に数える。
            where = "outside"
        bucket = locations[where]
        bucket["items"] += 1
        if row["bytes"]:
            bucket["bytes"] += int(row["bytes"])
        else:
            # bytes未記録の行。0として足すと内訳が実態より小さく見えるので件数で断る。
            bucket["unknown_bytes"] += 1
        if not enabled or not under_work:
            continue
        stem = Path(row["filename"]).stem
        try:
            size = src.stat().st_size
        except OSError:
            size = 0
        if not size:
            # mp4が無くても素材(.ts)が在れば移す対象である。見るのは**作業先の**session dir
            # だけで、両rootを見る ``_recording_media_dirs`` は使わない(素材が既に最終保存先に
            # 在る録画まで対象に混ざる)。素材だけの録画のsizeはDBのbytesで出す: session dirは
            # 束ね前で数千fileあり、候補ぶん走査すると容量画面が待たされる(所在の内訳をDB値で
            # 出しているのと同じ理由)。
            media_dir = layout.session_dir(runtime.RECORD_DIR, stem)
            if not api_files._has_usable_media(media_dir):
                # mp4も素材も無い(retention削除など)。移すものが無いので数えない。
                skipped_missing += 1
                continue
            size = int(row["bytes"] or 0)
            if not size:
                # bytesを持たない行だけは実測する。0のまま出すと移送量が桁で狂う(実測:
                # bytes未記録の5本に2.7〜4.4時間の録画が混じっていた)。走査するのはこの
                # 数本だけなので、候補ぶん走査するのとは費用が違う。
                size = api_files._dir_usage(media_dir)[0]
        dst = layout.mp4_path(runtime.FINAL_DIR, stem)
        if dst.exists() or layout.has_media(layout.session_dir(runtime.FINAL_DIR, stem)):
            # 退避先に同名が既に居る。上書きすると既に退避済みの実体を壊すので触らない
            # (素材だけの録画では衝突するのはmp4ではなくsession dirの方である)。
            skipped_bytes_unknown += 1
            continue
        plan.append({
            "recording_id": row["id"],
            "unique_id": row["unique_id"],
            "filename": row["filename"],
            "src": str(src),
            "dst": str(dst),
            "bytes": size,
            "started_at": row["started_at"],
        })
        total_bytes += size

    by_streamer: dict = {}
    for item in plan:
        entry = by_streamer.setdefault(
            item["unique_id"], {"unique_id": item["unique_id"], "items": 0, "bytes": 0})
        entry["items"] += 1
        entry["bytes"] += item["bytes"]
    return {
        "enabled": enabled,
        "items": plan,
        "total_items": len(plan),
        "total_bytes": total_bytes,
        "skipped_missing": skipped_missing,
        "skipped_existing_at_destination": skipped_bytes_unknown,
        "by_streamer": sorted(by_streamer.values(), key=lambda e: -e["bytes"]),
        "locations": locations,
        "record_dir": str(runtime.RECORD_DIR),
        "final_dir": str(runtime.FINAL_DIR),
    }


def _relocate_one(item: dict) -> Optional[str]:
    """1本を退避する。成功でNone、失敗で理由の文字列。

    status='recording' への再確認はここでは行わない(呼び出し側が実行直前に見る)。
    移送に成功したときだけDBのpathを書き換える。順序が逆だと、移送に失敗した録画のpathが
    存在しないfileを指す。
    """
    src = Path(item["src"])
    dst = Path(item["dst"])
    # mp4は録画の身元で、実在するとは限らない(finalizeはもう作らない)。移す実体は素材の
    # session dirなので、在るかどうかは両方で見る。
    if not src.is_file() and not layout.has_media(
            layout.session_dir(layout.record_root_of(src), src.stem)):
        return "移送元が見つかりません"
    if dst.exists() or layout.has_media(
            layout.session_dir(layout.record_root_of(dst), dst.stem)):
        return "退避先に同名のfileが既にあります"
    try:
        Recorder._move_recording_files(src, dst)
    except OSError as exc:
        # working dirに残す。working dirも許可されたrecord rootなので再生も出力も続く。
        runtime.logger.warning(
            "%s の移送に失敗したため %s に残しました", item["filename"], src,
            extra={"event": "recording.manual_relocation_failed",
                   "ctx": {"recording_id": item["recording_id"], "path": str(src),
                           "dst": str(dst), "size_bytes": item["bytes"]}},
            exc_info=True,
        )
        return str(exc)
    if not runtime.storage.update_recording_path(item["recording_id"], str(dst)):
        # 行が消えている(session削除と競合)。fileは既に移動済みなので位置だけ記録に残す。
        runtime.logger.warning(
            "%s を移送しましたがrecordingの行が消えています（fileの位置: %s）",
            item["filename"], dst,
            extra={"event": "recording.manual_relocation_orphaned",
                   "ctx": {"recording_id": item["recording_id"], "path": str(dst)}},
        )
    return None


def _run_relocation(plan: dict, on_item=None) -> dict:
    """planを順に移送する。1本の失敗で全体を止めない。

    1本がlockされているだけで残り全部を諦めるのは、この機能の目的(取り残しを減らす)に
    反する。失敗は数えて報告し、次へ進む。
    """
    moved = 0
    moved_bytes = 0
    failures: list = []
    total = len(plan["items"])
    for index, item in enumerate(plan["items"]):
        cancel.check_cancelled()
        if on_item is not None:
            on_item(index, total, item)
        # 実行直前に status を見る。dry-run から実行までの間に録画が始まった録画IDを
        # 掴んでいた場合、書き込み中のfileを動かすことになる。
        current = runtime.storage.get_recording(item["recording_id"])
        if current is None or current["status"] != "completed":
            failures.append({"filename": item["filename"], "reason": "状態が変わりました"})
            continue
        # 素材(.ts)ごと動かすので、その素材を読み書きしている処理が居る間は触らない。
        # 移送は元を消す片道の操作で、読み手の足元を抜くと双方が壊れる。
        if is_finalizing(item["recording_id"]):
            failures.append({"filename": item["filename"], "reason": "確定処理中です"})
            continue
        if item["recording_id"] in {rid for _kind, rid in runtime.storage.pending_media_job_keys()}:
            failures.append({"filename": item["filename"], "reason": "他の処理が使用中です"})
            continue
        error = _relocate_one(item)
        if error is None:
            moved += 1
            moved_bytes += item["bytes"]
        else:
            failures.append({"filename": item["filename"], "reason": error})
    if on_item is not None:
        on_item(total, total, None)
    return {"moved": moved, "moved_bytes": moved_bytes, "failures": failures}


def _relocation_summary() -> dict:
    """容量画面へ常時出す所在の内訳と取り残しの要約。録画の一覧は含めない。"""
    plan = _relocation_plan()
    return {
        "enabled": plan["enabled"],
        "items": plan["total_items"],
        "bytes": plan["total_bytes"],
        "locations": plan["locations"],
        "skipped_missing": plan["skipped_missing"],
        "skipped_existing_at_destination": plan["skipped_existing_at_destination"],
        "record_dir": plan["record_dir"],
        "final_dir": plan["final_dir"],
    }


def _retention_rules() -> dict:
    """保持policyの設定値。閾値はすべてSETTING_DEFS側にあり、ここは読み替えのみ。"""
    return {
        "transient_hours": int(runtime.settings.get("retention_transient_hours")),
        "derived_days": int(runtime.settings.get("retention_derived_days")),
        "source_days": int(runtime.settings.get("retention_source_days")),
        "source_enabled": bool(runtime.settings.get("retention_source_enabled")),
    }


def _retention_path(recording: dict) -> Optional[Path]:
    """録画pathをrecord root配下へ解決する。範囲外・不正pathは削除候補にしない。"""
    raw = recording.get("path")
    if not raw:
        return None
    try:
        return api_files._safe_recording_path(raw)
    except HTTPException:
        return None


def _retention_free_target_bytes() -> int:
    return int(runtime.settings.get("retention_free_target_gb")) * 1024 * 1024 * 1024


def _retention_free_reached() -> bool:
    """全volumeが打ち切り目標の空き容量に達したか。目標0(=打ち切らない)は常にFalse。

    読めなかったvolumeは判定へ入れない。空き容量が不明なものを「足りている」とみなすと、
    削除を止めるべき場面で止まらなくなる。"""
    target = _retention_free_target_bytes()
    if target <= 0:
        return False
    report = disk_free_by_volume(_disk_volume_paths())
    if not report:
        return False
    return all(info["free_bytes"] >= target for info in report.values())


def _retention_media_usage(recording: dict) -> dict:
    """この録画の素材(.ts)がdiskに占める実体量。原本phaseの候補にだけ効く。

    dir丸ごとの走査を伴うため、素材を原本と見なした録画に限って呼ぶ(既定OFFの③が有効に
    なったときだけ通る)。"""
    total = files = 0
    newest = 0.0
    for seg_dir in api_files._recording_media_dirs(recording):
        size, count, mtime = api_files._dir_usage(seg_dir)
        total += size
        files += count
        newest = max(newest, mtime)
    return {"bytes": total, "files": files, "mtime": newest}


def _build_retention_plan() -> dict:
    recordings = runtime.storage.recordings_for_retention()
    # 素材の有無は録画ごとにdirを叩くと重い(数千本)。一括画面と同じ、配信者ごとのts/を1回
    # scandirする経路で先に埋め、判定そのものは _bulk_classify(delete_mp4) と同じ事実を使う。
    facts_by_id = fsfacts._bulk_fs_facts_batch(recordings)
    fsfacts._bulk_hls_batch(recordings, facts_by_id)

    def has_media(recording: dict) -> bool:
        facts = facts_by_id.get(recording["id"])
        return bool(facts and facts.get("has_hls"))

    plan = retention.build_plan(
        recordings, runtime._RECORD_ROOTS, _retention_path, _retention_rules(), time.time(),
        has_media=has_media, media_usage=_retention_media_usage,
    )
    plan["rules"] = _retention_rules()
    plan["free_target_bytes"] = _retention_free_target_bytes()
    plan["protected_count"] = sum(1 for rec in recordings if rec.get("protected"))
    return plan


def _delete_transient_item(item: dict) -> int:
    """中断したrenderの残骸を1件削除し、解放bytesを返す。個々の失敗は握り潰さずlogへ残す。"""
    path = Path(item["path"])
    try:
        path.unlink(missing_ok=True)
    except OSError:
        runtime.logger.warning(
            "孤児になったrenderの中間file %s を削除できません", path.name,
            extra={"event": "retention.remove_failed",
                   "ctx": {"path": str(path), "phase": retention.PHASE_TRANSIENT}},
            exc_info=True,
        )
        return 0
    return int(item["bytes"])


def _delete_derived_item(item: dict) -> int:
    """1録画分の派生物(焼き込み・Up出力)を、削除endpointと同じcleanup関数で消す。

    素材(.ts)が残る録画ではmp4本体も派生物なので、一括削除(delete-mp4)と同じ
    ``_delete_source_mp4`` で消す。**planを組んだ時点の判定は使わず、消す直前にもう一度
    素材を確かめる** — その間に素材が消えていれば、そのmp4はもう最後の1本である。job が
    掴んでいる録画を外すのも一括削除と同じ理由で、走っているffmpegの入力を抜くことになる。"""
    src = Path(item["path"])
    freed = int(item["bytes"])
    cleanup_overlay_files(src)
    cleanup_upscale_files(src)
    if not item.get("includes_source"):
        return freed
    source_bytes = int(item.get("source_bytes") or 0)
    recording = runtime.storage.get_recording(item["recording_id"])
    reason = ""
    if recording is None:
        reason = "gone"
    elif not api_files._recording_media_dirs(recording):
        reason = "no_media"
    elif item["recording_id"] in runtime.storage.busy_recording_ids():
        reason = "busy"
    else:
        _, reason = api_files._delete_source_mp4(recording)
    if reason:
        runtime.logger.warning(
            "自動削除でrecording %s のmp4を残しました: %s",
            item["recording_id"], reason,
            extra={"event": "retention.source_kept",
                   "ctx": {"recording_id": item["recording_id"], "path": item["path"],
                           "reason": reason, "phase": retention.PHASE_DERIVED}},
        )
        return freed - source_bytes
    return freed


def _delete_source_item(item: dict) -> int:
    """再取得不能な原本を消し、録画行も落とす(単体削除endpointと同じ後始末)。

    素材(.ts)が残る録画では原本は素材の方なので、mp4と派生物に加えて素材dirも消す。
    ここまで来た時点でこの録画は復元手段を持たなくなる — ②までと違い、実行は設定の明示的な
    有効化とoperatorの確認を経たときだけである。"""
    recording = runtime.storage.get_recording(item["recording_id"])
    if recording is None:
        return 0
    api_files._remove_recording_files(recording)
    if item.get("media"):
        api_files._remove_recording_ts(recording)
    runtime.storage.delete_recording(item["recording_id"])
    return int(item["bytes"])


_RETENTION_DELETERS = {
    retention.PHASE_TRANSIENT: _delete_transient_item,
    retention.PHASE_DERIVED: _delete_derived_item,
    retention.PHASE_SOURCE: _delete_source_item,
}


def _apply_retention(plan: dict, on_item=None) -> dict:
    """planを実行順(transient -> derived -> source)に消す。打ち切り目標に達したら停止する。

    実行のたびにfileが消えて空きが増えるので、目標判定はphaseの区切りで測り直す。

    ``on_item(phase, done, total)`` は同期callback(この関数自体がto_threadの中で回る)。
    以前はjob行を作るだけで進捗を一度も報告せず、画面に永久に0%の行が残っていた。"""
    removed = {phase: {"items": 0, "bytes": 0} for phase in retention.PHASE_ORDER}
    stopped = ""
    for phase in plan["phases"]:
        key = phase["phase"]
        if not phase["enabled"]:
            continue
        deleter = _RETENTION_DELETERS[key]
        total = len(phase["items"])
        for index, item in enumerate(phase["items"]):
            if on_item is not None:
                on_item(key, index, total)
            if _retention_free_reached():
                stopped = key
                break
            freed = deleter(item)
            if freed:
                removed[key]["items"] += 1
                removed[key]["bytes"] += freed
        if on_item is not None:
            on_item(key, total, total)
        if stopped:
            break
    return {"removed": removed, "stopped_at": stopped,
            "freed_bytes": sum(entry["bytes"] for entry in removed.values()),
            "removed_items": sum(entry["items"] for entry in removed.values())}
