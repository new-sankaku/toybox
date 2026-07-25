"""運用log(ops_events)のkindを画面に出す日本語ラベル。

kindは記録側の機械key(collector.disconnected 等)で、これ自体は変えない。表に出すときだけ
ここのラベルを当てる。ラベルをFrontendに持たせないのは、jobの種類名(焼き込み・切り抜き…)が
kindとops_eventsのmessage文の両方に出るためで、2箇所に同じ訳語を置くと必ずずれる。

未知のkindには何も返さない。それらしいラベルを組み立てると、記録に無い名前が画面に出る。
呼び出し側はNoneのときkindの生値を出すこと(operatorが記録と突き合わせられる形を残す)。
"""

# 後処理jobの種類。kind(overlay.job_started)とmessage(「コメント焼き込みの処理を開始」)の
# 両方がこの表を引く。
JOB_DOMAIN_LABELS = {
    "overlay": "コメント焼き込み",
    "overlay_preview": "焼き込みのpreview",
    "clip": "切り抜きの書き出し",
    "audionorm": "音量の正規化",
    "upscale": "AI高画質化",
    "stt": "音声の転写",
    "semantic": "意味検索のindex",
}

# jobの終わり方。取り消しと対象なしは正常な終わり方で、失敗と区別して読めるようにする。
_JOB_ACTION_LABELS = {
    "job_started": "開始",
    "job_completed": "完了",
    "job_cancelled": "取り消し",
    "job_skipped": "対象なし",
    "job_failed": "失敗",
}

# DB保守。kindは maintenance.{操作}_failed / maintenance.{完了名} の2系統ある。
_MAINTENANCE_LABELS = {
    "backup": "DBの退避",
    "integrity_check": "DBの整合性check",
    "wal_checkpoint": "WALの書き戻し",
    "vacuum": "DBのVACUUM",
}

_STATIC_KIND_LABELS = {
    "session.started": "配信sessionの開始",
    "session.ended": "配信sessionの終了",
    "session.restricted": "限定配信のため録画不可",
    "collector.connected": "eventの接続",
    "collector.disconnected": "eventの切断",
    "collector.live_ended": "配信の終了を検知",
    "collector.stream_lost": "dataが届かず再接続",
    "collector.recording_stalled": "映像が増えず再接続",
    "collector.reconnect_exhausted": "再接続の試行が尽きた",
    "collector.reconnect_broadcast_ended": "再接続中に配信終了",
    "recording.started": "録画の開始",
    "recording.finalized": "録画の確定",
    "recording.empty_finalized": "録画が空で破棄",
    "recording.concat_failed": "mp4の組み立て失敗",
    "recording.validation_failed": "確定mp4の検証失敗",
    "media_queue.group_finished": "一括処理の終了",
    "media_queue.job_interrupted": "再起動でjobが中断",
    "capacity.forecast_low": "空き容量の見通し警告",
    "storage.relocated": "最終保存先への退避",
    "storage.scan_completed": "使用量scanの完了",
    "storage.recording_files_deleted": "録画fileの削除",
    "retention.previewed": "保持rulesの試算",
    "retention.applied": "保持rulesの適用",
    "retention.protection_changed": "保護setting変更",
    "retention.derived_removed": "派生fileの削除",
    "maintenance.backup_completed": "DBの退避完了",
    "maintenance.integrity_checked": "DBの整合性check",
    "maintenance.wal_checkpointed": "WALの書き戻し",
    "maintenance.vacuumed": "DBのVACUUM完了",
    "notify.test_sent": "通知testの送信",
    "notify.delivery_failed": "通知の送信失敗",
    "notify.queue_overflow": "通知queueの溢れ",
    "process.settings_updated": "設定の変更",
    "process.startup_recovery_completed": "起動時の復旧",
}


def _build() -> dict:
    labels = dict(_STATIC_KIND_LABELS)
    for domain, domain_label in JOB_DOMAIN_LABELS.items():
        for action, action_label in _JOB_ACTION_LABELS.items():
            labels[f"{domain}.{action}"] = f"{domain_label}・{action_label}"
    for op, op_label in _MAINTENANCE_LABELS.items():
        labels[f"maintenance.{op}_failed"] = f"{op_label}・失敗"
    return labels


KIND_LABELS = _build()


def job_domain_label(domain: str) -> str:
    """jobの種類名。未知のdomainはcode名のまま返す(訳語を作らない)。"""
    return JOB_DOMAIN_LABELS.get(domain, domain)


def maintenance_label(operation: str) -> str:
    """DB保守の操作名。未知の操作はcode名のまま返す。"""
    return _MAINTENANCE_LABELS.get(operation, operation)
