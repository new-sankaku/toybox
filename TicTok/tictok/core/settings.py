import logging
import os

from tictok.storage import Storage

logger = logging.getLogger("tictok.settings")

SETTING_DEFS = {
    "bucket_seconds": {
        "env": "TICTOK_BUCKET_SECONDS",
        "default": 10,
        "type": int,
        "min": 1,
        "max": 600,
        "label": "Timeline集計のbucket幅（秒）",
        "note": "次のSession開始から適用されます。",
    },
    "live_check_interval": {
        "env": "TICTOK_LIVE_CHECK_INTERVAL",
        "default": 60,
        "type": int,
        "min": 10,
        "max": 3600,
        "label": "配信開始の確認間隔（秒）",
        "note": "未配信のとき、この間隔でLIVE開始を確認します。短すぎるとTikTokのWAFにIP単位でブロックされます（実効レート=監視数×60÷間隔）。監視数が多いほど長めに設定してください。",
    },
    "live_check_max_per_min": {
        "env": "TICTOK_LIVE_CHECK_MAX_PER_MIN",
        "default": 2.0,
        "type": float,
        "min": 0.5,
        "max": 30.0,
        "label": "LIVE確認の総アクセス上限（回/分）",
        "note": "全監視を合計したTikTokへのアクセス回数の上限です。監視数が増えても合計がこの値を超えないよう確認間隔を自動で広げ、IP単位のブロックを防ぎます。小さいほど安全ですが、個々の配信開始の検出は遅くなります。",
    },
    "reconnect_max_attempts": {
        "env": "TICTOK_RECONNECT_MAX_ATTEMPTS",
        "default": 10,
        "type": int,
        "min": 0,
        "max": 100,
        "label": "自動再接続の最大試行回数",
        "note": "一時的な接続障害が続いた場合に諦めるまでの回数です。",
    },
    "reconnect_base_delay": {
        "env": "TICTOK_RECONNECT_BASE_DELAY",
        "default": 2.0,
        "type": float,
        "min": 0.5,
        "max": 300.0,
        "label": "再接続の初回待機秒数",
        "note": "exponential backoffの起点です（2→4→8…秒）。",
    },
    "reconnect_max_delay": {
        "env": "TICTOK_RECONNECT_MAX_DELAY",
        "default": 60.0,
        "type": float,
        "min": 1.0,
        "max": 3600.0,
        "label": "再接続待機秒数の上限",
        "note": "backoffがこの秒数を超えないように制限します。",
    },
    "connection_idle_timeout": {
        "env": "TICTOK_CONNECTION_IDLE_TIMEOUT",
        "default": 45,
        "type": int,
        "min": 10,
        "max": 600,
        "label": "受信途絶とみなす秒数（自動再接続）",
        "note": "接続中にこの秒数Dataの受信が途絶えた場合、配信側の電波切れ等で接続が応答不能（half-open）になったと判断し、自動で再接続します。短すぎると配信が静かなだけで不要な再接続が発生します。",
    },
    "event_history": {
        "env": "TICTOK_EVENT_HISTORY",
        "default": 200,
        "type": int,
        "min": 10,
        "max": 5000,
        "label": "画面再接続時に再送するEvent履歴件数",
        "note": "次のSession開始から適用されます。",
    },
    "auto_record": {
        "env": "TICTOK_AUTO_RECORD",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "配信開始時の自動録画",
        "note": "Server起動時・監視開始時・配信開始時にLIVE接続を検出するたびffmpegで自動録画します（ffmpegが必要）。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "battle_score_sample_seconds": {
        "env": "TICTOK_BATTLE_SCORE_SAMPLE_SECONDS",
        "default": 3,
        "type": int,
        "min": 1,
        "max": 60,
        "label": "Battleスコア推移の記録間隔（秒）",
        "note": "Battle中の自陣/敵陣スコアの時系列をこの間隔で記録し、各画面のBattleカードにスコア推移として表示します。短いほど細かく記録しますがDataが増えます。",
    },
    "monitor_opponent_rooms": {
        "env": "TICTOK_MONITOR_OPPONENT_ROOMS",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "Battle中に相手RoomのGiftも取得",
        "note": "PK(Battle)中、相手配信者のRoomにも一時的に接続し、相手陣の実弾(コイン)Giftを取得して貢献者別に表示します。Battle終了で切断します。相手の人数ぶんTikTokへの接続・確認が増えるため、監視数が多い環境ではWAFによるIP単位のブロックの可能性が上がります。ブロックが出る場合は無効化してください。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "battle_debug_capture": {
        "env": "TICTOK_BATTLE_DEBUG_CAPTURE",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "Battle生event記録（検証用）",
        "note": "Battle(PK)関連のevent(combo/倍率card・bonus task・notice・victory lap・罰game、および本体eventと陣営army)をTikTokから届いた生のまま logs/battle_raw_*.jsonl へ記録します。未使用fieldの実値を後から確認するための診断用で、通常運用では不要です。fileが増えるため検証時のみ有効化してください。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "league_probe": {
        "env": "TICTOK_LEAGUE_PROBE",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "配信者リーグの探索ログ（検証用）",
        "note": "配信者のリーグ帯(例:A1/B1)がTikTokのどのDataに載るかを特定するための診断です。LIVE接続時にgift list・room_info・ランキング系eventを走査し、名前がleague/ranking/grade系のfield、または『A1』『B1』形式の文字列値を見つけ次第 logs へ [league-probe] として出力します。特定できたら無効化してください。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "sample_capture": {
        "env": "TICTOK_SAMPLE_CAPTURE",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "実配信サンプルの保存",
        "note": "実LIVEで受信した各種event(Gift/Comment/Battleなど)を、構造(shape)が新しいものだけ1件ずつ samples/<kind>.jsonl に保存します。実データにどのfieldがどう入るか(例: ギフターLvの数値位置)を後から確認するための診断用です。同じ構造は重複保存せず、kindごとに件数上限があるため容量は限定的です。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "sample_capture_max_per_kind": {
        "env": "TICTOK_SAMPLE_CAPTURE_MAX_PER_KIND",
        "default": 40,
        "type": int,
        "min": 1,
        "max": 500,
        "label": "サンプル保存の上限件数（event種別ごと）",
        "note": "event種別(kind)ごとに保存する異なる構造サンプルの最大件数です。上限に達するとその種別は以降保存しません。大きいほど網羅性が上がりますが容量が増えます。",
    },
    "session_list_limit": {
        "env": "TICTOK_SESSION_LIST_LIMIT",
        "default": 100,
        "type": int,
        "min": 10,
        "max": 1000,
        "label": "履歴一覧の表示件数",
        "note": "履歴pageに表示するSessionの最大数です。",
    },
    "video_overlay_comments": {
        "env": "TICTOK_VIDEO_OVERLAY_COMMENTS",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: コメントを焼き込む",
        "note": "履歴詳細から録画をDownloadする際、収集したCommentを画面左下に積み上がるTikTok風のCommentとして動画へ焼き込みます(新着が下、古いものが上へscroll)。ffmpegでの再Encodeが必要なため、Downloadに時間がかかります。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "video_overlay_gifts": {
        "env": "TICTOK_VIDEO_OVERLAY_GIFTS",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: Gift演出を焼き込む",
        "note": "録画Download時にGift受信を、Gift Iconが左からslide-inするTikTok風の通知Card(送り主・Gift名・個数)として動画へ焼き込みます。Gift Iconは焼き込み時にTikTokから取得します。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "video_overlay_score_bar": {
        "env": "TICTOK_VIDEO_OVERLAY_SCORE_BAR",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: Battleスコアバーを焼き込む",
        "note": "録画Download時、Battle(PK)中だけ画面上部に自陣(左)/敵陣(右)のスコアバーをTikTok風に焼き込みます。スコアはBattleのスコア推移(score_series)から映像のtimeに合わせて時系列で描画します。1v1とチーム戦は陣営合計、個人マルチ(Nコラ)は自陣と首位相手の対比です。Battleが無い録画では何も表示しません。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "video_overlay_score_bar_hold_seconds": {
        "env": "TICTOK_VIDEO_OVERLAY_SCORE_BAR_HOLD_SECONDS",
        "default": 60,
        "type": int,
        "min": 0,
        "max": 600,
        "label": "動画化: Battle終了後にスコアバーを残す秒数",
        "note": "Battle(PK)終了後も、最終スコアと勝敗を表示したままスコアバーをこの秒数だけ画面に残します(勝利タイム/結果表示用)。終了と同時に消さず、既定では60秒残します。次のBattleが始まる場合・動画が終わる場合はそこで打ち切ります。0で終了と同時に消します。",
    },
    "video_overlay_real_avatars": {
        "env": "TICTOK_VIDEO_OVERLAY_REAL_AVATARS",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: Commentに実ユーザーアイコンを使う",
        "note": "Commentの丸アイコンに、収集時に保存した実ユーザーアイコン(円形)を焼き込みます。保存が無いUserは頭文字の色付き丸にfallbackします。「しない」で常に頭文字の丸になります。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "video_overlay_font_size": {
        "env": "TICTOK_VIDEO_OVERLAY_FONT_SIZE",
        "default": 14,
        "type": int,
        "min": 8,
        "max": 80,
        "label": "動画化: Commentの文字サイズ(px)",
        "note": "焼き込むCommentの基準文字サイズ(動画の縦1280pxを基準)です。Commentは画面左下の高さ約33%・幅80%の領域に表示し、長いCommentは折り返して全文を表示します(省略記号なし)。文字を小さくすると同時表示行数が増えます。古いCommentは上端でグラデーション的にfade outします。",
    },
    "video_overlay_icon_percent": {
        "env": "TICTOK_VIDEO_OVERLAY_ICON_PERCENT",
        "default": 7,
        "type": int,
        "min": 1,
        "max": 30,
        "label": "動画化: Gift Iconのサイズ(動画高さに対する%)",
        "note": "焼き込むGift Iconの大きさを、動画の縦pxに対する割合(%)で指定します。動画解像度に応じて動的に算出されます。",
    },
    "video_overlay_quality": {
        "env": "TICTOK_VIDEO_OVERLAY_QUALITY",
        "default": 21,
        "type": int,
        "min": 14,
        "max": 32,
        "label": "動画化: 出力画質(小さいほど高画質・大file)",
        "note": "焼き込み出力のEncode品質(CRF/CQ相当, おおよそ0〜51)。小さいほど高画質ですがfileは大きくなります。元配信が既に圧縮済みのため、14程度より下げても見た目はほぼ変わらずfileだけ肥大化します。GPU(NVENC)利用時もこの値を使います。",
    },
    "video_overlay_codec": {
        "env": "TICTOK_VIDEO_OVERLAY_CODEC",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 3,
        "label": "動画化: 出力codec",
        "note": "焼き込み出力の映像codecです。AV1はH.264比で同画質・約1/3のfileになりますが、再生にはAV1対応のplayer/端末(WindowsはAV1 Video Extension)が必要です。HEVCはH.264比で小さく互換性も比較的広い、H.264は最も互換性が高い代わりにfileが大きくなります。autoはこのPCで使えるGPU encoderのうち最も高圧縮なものを選びます(AV1>HEVC>H.264)。GPU非対応時はCPU encodeにfallbackします(低速)。画質は上の「出力画質」値をcodecごとに自動補正して使います。",
        "options": [
            {"value": 0, "label": "auto (高圧縮優先)"},
            {"value": 1, "label": "H.264 (最も互換)"},
            {"value": 2, "label": "HEVC/H.265"},
            {"value": 3, "label": "AV1 (最小file)"},
        ],
    },
    "video_overlay_timing_compare": {
        "env": "TICTOK_VIDEO_OVERLAY_TIMING_COMPARE",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: 同期方式の比較出力(到着時刻 と サーバ時刻)",
        "note": "焼き込み時、従来方式(到着時刻でComment/Battleを配置)に加えて、TikTokのサーバ時刻(create_time)で配置した比較用の動画(<name>.overlay.b.mp4)も同時に出力します。配信中に少しずつ生じる同期ズレの検証用です。create_timeを保存した録画でのみBが出力され、再Encodeが2回分かかります。明細は<name>.timing.debug.jsonに記録します。",
        "options": [
            {"value": 0, "label": "しない (従来の到着時刻のみ)"},
            {"value": 1, "label": "する (到着時刻 と サーバ時刻 を両方出力)"},
        ],
    },
    "video_overlay_comment_delay_seconds": {
        "env": "TICTOK_VIDEO_OVERLAY_COMMENT_DELAY_SECONDS",
        "default": 0,
        "type": int,
        "min": -30,
        "max": 30,
        "label": "動画化: Comment/Giftの時刻補正(秒)",
        "note": "焼き込むComment/Giftの表示time刻を一律でずらします。配信映像はCDNで数秒遅れて録画されるため、Commentが映像より先行して見える場合に+方向(例:+5)で後ろへずらして合わせます。逆に遅れて見える場合は-方向にします。0で補正なし。",
    },
    "video_overlay_gift_seconds": {
        "env": "TICTOK_VIDEO_OVERLAY_GIFT_SECONDS",
        "default": 4,
        "type": int,
        "min": 1,
        "max": 20,
        "label": "動画化: Gift演出の表示秒数",
        "note": "Gift通知Cardを表示し続ける秒数です。",
    },
    "video_overlay_gift_min_diamonds": {
        "env": "TICTOK_VIDEO_OVERLAY_GIFT_MIN_DIAMONDS",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 100000,
        "label": "動画化: Gift演出の最小diamonds",
        "note": "この値以上のdiamondsのGiftだけを演出表示します。0で全Giftを表示します。安価なGiftが多い配信で画面が埋まるのを防げます。",
    },
    "recording_keep_hls": {
        "env": "TICTOK_RECORDING_KEEP_HLS",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "録画: HLS中間data(.ts)を保持する",
        "note": "通常はmp4化が完了するとHLSの中間data(セグメント.ts/playlist)を削除します。「する」にすると削除せず保持します。Comment焼き込みの時刻ズレ調査など、mp4のPTSと元セグメントの対応を後から検証するための診断用です。録画ごとにmp4とほぼ同容量を追加で消費するため、調査時のみ有効化してください。",
        "options": [
            {"value": 0, "label": "しない(削除)"},
            {"value": 1, "label": "する(保持)"},
        ],
    },
}


class Settings:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._values: dict = {}
        self._load()

    def _env_default(self, key: str):
        definition = SETTING_DEFS[key]
        raw = os.environ.get(definition["env"])
        if raw is None:
            return definition["default"]
        return definition["type"](raw)

    def _load(self) -> None:
        stored = self._storage.get_settings()
        for key, definition in SETTING_DEFS.items():
            if key in stored:
                self._values[key] = definition["type"](stored[key])
            else:
                self._values[key] = self._env_default(key)

    def get(self, key: str):
        return self._values[key]

    def all_values(self) -> dict:
        return dict(self._values)

    def describe(self) -> list:
        described = []
        for key, definition in SETTING_DEFS.items():
            entry = {
                "key": key,
                "value": self._values[key],
                "label": definition["label"],
                "note": definition["note"],
                "min": definition["min"],
                "max": definition["max"],
                "step": 1 if definition["type"] is int else 0.5,
            }
            if "options" in definition:
                entry["options"] = definition["options"]
            described.append(entry)
        return described

    def update(self, values: dict) -> dict:
        validated = {}
        for key, value in values.items():
            if key not in SETTING_DEFS:
                raise ValueError(f"不明な設定key: {key}")
            definition = SETTING_DEFS[key]
            try:
                if (
                    definition["type"] is int
                    and isinstance(value, float)
                    and not value.is_integer()
                ):
                    # int(10.9)=10 と黙って切り捨てず、不正入力として拒否する。
                    raise ValueError(value)
                typed = definition["type"](value)
            except (TypeError, ValueError):
                raise ValueError(f"{definition['label']} の値が不正です: {value}")
            if not (definition["min"] <= typed <= definition["max"]):
                raise ValueError(
                    f"{definition['label']} は {definition['min']}〜{definition['max']} の範囲で指定してください。"
                )
            validated[key] = typed
        if validated:
            self._storage.set_settings(validated)
            self._values.update(validated)
            logger.info("settings updated: %s", validated)
        return self.all_values()
