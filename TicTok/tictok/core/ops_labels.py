"""運用log(ops_events)のkindを画面に出す日本語ラベル。

kindは記録側の機械key(collector.disconnected 等)で、これ自体は変えない。表に出すときだけ
ここのラベルを当てる。ラベルをFrontendに持たせないのは、jobの種類名(焼き込み・切り抜き…)が
kindとops_eventsのmessage文の両方に出るためで、2箇所に同じ訳語を置くと必ずずれる。

未知のkindには何も返さない。それらしいラベルを組み立てると、記録に無い名前が画面に出る。
呼び出し側はNoneのときkindの生値を出すこと(operatorが記録と突き合わせられる形を残す)。
"""

# 後処理jobの種類。kind(overlay.job_started)とmessage(「焼き込みを開始しました」)の両方が
# この表を引き、Job画面の種別labelと種別filterの選択肢もここから作る。訳語を置く場所は
# ここ1箇所だけで、画面側は受け取って引くだけにする(module docstringの理由)。
JOB_DOMAIN_LABELS = {
    "overlay": "焼き込み",
    "upscale": "Up出力",
    "reprocess": "再mp4化",
    "audionorm": "音量正規化",
    "pack": "ts結合",
    "waveform": "音声波形",
    # 実体は再生時に当てるgainの時系列(.gain.json)。録画そのものは書き換えない。
    "gain": "再生gain曲線",
    # 実体は声の在る区間の解析(.voice.json)で、無音skipと無言の早送りが同じものを使う。
    # 名前を用途側から付けているのは、探す人がその名前で探すため。
    "voice": "無音skipの解析",
    "sprite": "サムネ",
    "overlay_preview": "焼き込みプレビュー",
    "clip": "切り抜きの書き出し",
    "still": "スクショ",
    "clip_batch": "clip一括書き出し",
    "clip_overlay": "範囲焼き込み",
    "reel": "切り出しの連結",
    "work": "作品の書き出し",
    "short": "short一括生成",
    "stt": "文字起こし",
    "laugh": "笑い声分析",
    "semantic": "意味検索index",
    "storage": "容量scan",
    # file移動を「容量scan」として並べていたため、種別を根拠に読むと実体を取り違えた。
    "relocate": "最終保存先へ移動",
    "retention": "保持policy",
    "maintenance": "DB保守",
}

# session一括・配信者一括を1行へ畳んだときのdomain。実行の単位ではない(=ops_eventsのkindに
# はならない)が、Job画面には行として出るのでlabelが要る。畳む前後で語を変えないよう、元の
# 種別名をそのまま含める。
GROUP_DOMAIN_LABELS = {
    "session_overlay": "Session 焼き込み",
    "session_upscale": "Session Up出力",
    "bulk_overlay": "一括 焼き込み出力",
    "bulk_upscale": "一括 Up出力",
    "bulk_reprocess": "一括 再mp4化",
    "bulk_audionorm": "一括 音量正規化",
    "bulk_pack": "一括 ts結合",
}

# Job画面が引く全domain。並び順がそのまま種別filterの選択肢の順になる。
JOB_KIND_LABELS = {**JOB_DOMAIN_LABELS, **GROUP_DOMAIN_LABELS}

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
    "session.unsigned": "署名が通らず録画不可",
    "session.video_only": "署名が通らず映像のみ録画",
    "session.video_only_attached": "コメント受信の合流",
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
