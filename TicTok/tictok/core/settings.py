import logging
import os
from pathlib import Path

from tictok.paths import PROJECT_ROOT
from tictok.storage import Storage

logger = logging.getLogger("tictok.settings")

_DEFAULT_RECORD_DIR = str(PROJECT_ROOT / "recordings")

# 設定画面のsection。SETTING_DEFSのkey順は既に論理clusterに並んでいるので、順序は変えず
# 各項目にcategoryを持たせ、画面側はcategoryが切り替わる位置にheaderを差し込むだけにする。
# 新しい設定を足すときは、同じcategoryの項目の隣へ置くこと(離れた位置へ置くと同じheaderが
# 二度出る)。焼き込みが2つに分かれているのは既存のkey順がそうなっているためで、順序を
# 変えないという方針を優先した結果である。
CATEGORY_LABELS = {
    "paths": "保存先",
    "collect": "収集と接続",
    "record": "録画とBattle収集",
    "diagnostic": "診断・sample採取",
    "ui": "画面表示",
    "overlay": "焼き込み: 表示要素と画質",
    "audio": "音量正規化",
    "clip": "切り出し(clip)",
    "overlay_timing": "焼き込み: 時刻合わせとプレビュー",
    "storage": "容量と保持policy",
}

SETTING_DEFS = {
    "record_dir": {
        "category": "paths",
        "env": "TICTOK_RECORD_DIR",
        "default": _DEFAULT_RECORD_DIR,
        "type": str,
        "label": "録画の一時保存先(SSD想定)",
        "note": "録画中の書き込み先の絶対パスです(例: D:\\rec_ssd)。HLSセグメント・変換中のmp4・ライブ再生・avatar/gift iconキャッシュはここに置かれます。SSDなど高速なドライブを推奨します。変更はサーバー再起動後の録画から有効です。空欄で環境変数TICTOK_RECORD_DIR、無ければ既定のrecordingsを使います。",
    },
    "record_dir_final": {
        "category": "paths",
        "env": "TICTOK_RECORD_DIR_FINAL",
        "default": "",
        "type": str,
        "allow_empty": True,
        "label": "録画の最終保存先(HDD想定)",
        "note": "録画完了後にmp4を退避する絶対パスです(例: K:\\80_Tiktok)。一時保存先で録画→変換し、完了したmp4とtimingをここへ移動します。出力(焼き込み・AI高画質化)もここに生成されます。大容量のHDDを推奨します。空欄なら一時保存先と同じ(退避せず)になります。変更はサーバー再起動後の録画から有効です。",
    },
    "bucket_seconds": {
        "category": "collect",
        "env": "TICTOK_BUCKET_SECONDS",
        "default": 10,
        "type": int,
        "min": 1,
        "max": 600,
        "label": "Timeline集計のbucket幅（秒）",
        "note": "次のSession開始から適用されます。",
    },
    "live_check_interval": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_INTERVAL",
        "default": 60,
        "type": int,
        "min": 10,
        "max": 3600,
        "label": "配信開始の確認間隔（秒）",
        "note": "未配信のとき、この間隔でLIVE開始を確認します。短すぎるとTikTokのWAFにIP単位でブロックされます（実効レート=監視数×60÷間隔）。監視数が多いほど長めに設定してください。",
    },
    "live_check_max_per_min": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_MAX_PER_MIN",
        "default": 2.0,
        "type": float,
        "min": 0.5,
        "max": 30.0,
        "label": "LIVE確認の総アクセス上限（回/分）",
        "note": "全監視を合計したTikTokへのアクセス回数の上限です。監視数が増えても合計がこの値を超えないよう確認間隔を自動で広げ、IP単位のブロックを防ぎます。小さいほど安全ですが、個々の配信開始の検出は遅くなります。",
    },
    "restricted_recheck_interval": {
        "category": "collect",
        "env": "TICTOK_RESTRICTED_RECHECK_INTERVAL",
        "default": 60,
        "type": int,
        "min": 60,
        "max": 7200,
        "label": "録画不可判定の再確認間隔（秒）",
        "note": "メンバー限定/年齢制限と判定した配信を再確認する最初の間隔です。制限応答が一時的なものなら数分で解けることが多いため、この間隔で数回続けてから、以降は上限まで倍々に広げます。確認は署名サーバーを消費しない軽量な問い合わせ1回だけです。短いほど復帰は速くなりますが、TikTokへのアクセス回数が増え、制限が解けたと判定した回数だけ接続(=署名)が発生します。",
    },
    "restricted_recheck_max_interval": {
        "category": "collect",
        "env": "TICTOK_RESTRICTED_RECHECK_MAX_INTERVAL",
        "default": 900,
        "type": int,
        "min": 60,
        "max": 7200,
        "label": "録画不可判定の再確認間隔の上限（秒）",
        "note": "再確認の間隔を倍々に広げていく際の上限です。本当にメンバー限定/年齢制限の配信は放送が終わるまで解けないため、粘るほど無駄なアクセスになります。上限に達した後はその間隔を保ち続けます(60秒には戻しません)。",
    },
    "reconnect_max_attempts": {
        "category": "collect",
        "env": "TICTOK_RECONNECT_MAX_ATTEMPTS",
        "default": 10,
        "type": int,
        "min": 0,
        "max": 100,
        "label": "自動再接続の最大試行回数",
        "note": "一時的な接続障害が続いた場合に諦めるまでの回数です。",
    },
    "reconnect_base_delay": {
        "category": "collect",
        "env": "TICTOK_RECONNECT_BASE_DELAY",
        "default": 2.0,
        "type": float,
        "min": 0.5,
        "max": 300.0,
        "label": "再接続の初回待機秒数",
        "note": "exponential backoffの起点です（2→4→8…秒）。",
    },
    "reconnect_max_delay": {
        "category": "collect",
        "env": "TICTOK_RECONNECT_MAX_DELAY",
        "default": 60.0,
        "type": float,
        "min": 1.0,
        "max": 3600.0,
        "label": "再接続待機秒数の上限",
        "note": "backoffがこの秒数を超えないように制限します。",
    },
    "connection_idle_timeout": {
        "category": "collect",
        "env": "TICTOK_CONNECTION_IDLE_TIMEOUT",
        "default": 45,
        "type": int,
        "min": 10,
        "max": 600,
        "label": "受信途絶とみなす秒数（自動再接続）",
        "note": "接続中にこの秒数Dataの受信が途絶えた場合、配信側の電波切れ等で接続が応答不能（half-open）になったと判断し、自動で再接続します。短すぎると配信が静かなだけで不要な再接続が発生します。",
    },
    "recording_stall_timeout": {
        "category": "collect",
        "env": "TICTOK_RECORDING_STALL_TIMEOUT",
        "default": 40,
        "type": int,
        "min": 15,
        "max": 600,
        "label": "録画停止とみなす秒数（自動再接続）",
        "note": "Event受信は続いているのに録画segmentがこの秒数増えない場合、動画のstream URLが無音停止(ffmpegが死んだURLをretry継続)したと判断し、再接続してroom_infoを取り直し録画を再開します。ffmpeg内蔵reconnect(30s)より長くしないと自力回復と競合します。正常な配信はsegment間隔が数秒を超えません。",
    },
    "event_history": {
        "category": "collect",
        "env": "TICTOK_EVENT_HISTORY",
        "default": 200,
        "type": int,
        "min": 10,
        "max": 5000,
        "label": "画面再接続時に再送するEvent履歴件数",
        "note": "次のSession開始から適用されます。",
    },
    "contributor_sample_seconds": {
        "category": "collect",
        "env": "TICTOK_CONTRIBUTOR_SAMPLE_SECONDS",
        "default": 30,
        "type": int,
        "min": 5,
        "max": 600,
        "label": "貢献者Rankingの記録間隔（秒）",
        "note": "TikTokが配信中に配信するRoom上位貢献者のRanking（TikTok側が算出した累積スコア）を、この間隔で記録します。内容が前回と同じ場合は記録しません。自前のGift集計と突き合わせて取りこぼし量を測るためのDataです。短いほど細かく記録しますがDataが増えます。",
    },
    "auto_record": {
        "category": "record",
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
        "category": "record",
        "env": "TICTOK_BATTLE_SCORE_SAMPLE_SECONDS",
        "default": 3,
        "type": int,
        "min": 1,
        "max": 60,
        "label": "Battleスコア推移の記録間隔（秒）",
        "note": "Battle中の自陣/敵陣スコアの時系列をこの間隔で記録し、各画面のBattleカードにスコア推移として表示します。短いほど細かく記録しますがDataが増えます。",
    },
    "battle_score_endgame_seconds": {
        "category": "record",
        "env": "TICTOK_BATTLE_SCORE_ENDGAME_SECONDS",
        "default": 20,
        "type": int,
        "min": 0,
        "max": 300,
        "label": "Battle終盤とみなす残り時間（秒）",
        "note": "Battle終了時刻までの残りがこの秒数を切ったあいだ、スコア推移を「Battle終盤のスコア記録間隔」で細かく記録します。決着はこの区間で付くため、通常の間隔のままだと逆転の瞬間が1点に潰れます。0にすると終盤の細分化を行いません（Battleの終了時刻が届かない場合も細分化しません）。",
    },
    "battle_score_endgame_sample_seconds": {
        "category": "record",
        "env": "TICTOK_BATTLE_SCORE_ENDGAME_SAMPLE_SECONDS",
        "default": 0.5,
        "type": float,
        "min": 0.1,
        "max": 10.0,
        "label": "Battle終盤のスコア記録間隔（秒）",
        "note": "「Battle終盤とみなす残り時間」の区間で使う記録間隔です。通常の記録間隔より短い値にしてください。",
    },
    "monitor_opponent_rooms": {
        "category": "record",
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
        "category": "diagnostic",
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
        "category": "diagnostic",
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
        "category": "diagnostic",
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
        "category": "diagnostic",
        "env": "TICTOK_SAMPLE_CAPTURE_MAX_PER_KIND",
        "default": 40,
        "type": int,
        "min": 1,
        "max": 500,
        "label": "サンプル保存の上限件数（event種別ごと）",
        "note": "event種別(kind)ごとに保存する異なる構造サンプルの最大件数です。上限に達するとその種別は以降保存しません。大きいほど網羅性が上がりますが容量が増えます。",
    },
    "session_list_limit": {
        "category": "ui",
        "env": "TICTOK_SESSION_LIST_LIMIT",
        "default": 100,
        "type": int,
        "min": 10,
        "max": 1000,
        "label": "履歴一覧の表示件数",
        "note": "履歴pageに表示するSessionの最大数です。",
    },
    "video_overlay_comments": {
        "category": "overlay",
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
        "category": "overlay",
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
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_SCORE_BAR",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: Battleスコアバーを焼き込む",
        "note": "録画Download時、Battle(PK)中だけ画面上部にスコアバーをTikTok風に焼き込みます。スコアはBattleのスコア推移(score_series)から映像のtimeに合わせて時系列で描画します。分割はWeb表示と同じで、1v1は自陣(左)/敵陣(右)の2分割、チーム戦NvMは自陣/敵陣の2極を各memberのsub-segment(同系色の濃淡)へ分割、個人マルチ(Nコラ)は参加者ごとにN分割します。2極表示(1v1/チーム戦)の両端には配信者アバターを合成します(取得不可時はイニシャル表示)。Battleが無い録画では何も表示しません。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "video_overlay_score_bar_hold_seconds": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_SCORE_BAR_HOLD_SECONDS",
        "default": 60,
        "type": int,
        "min": 0,
        "max": 600,
        "label": "動画化: Battle終了後にスコアバーを残す秒数",
        "note": "Battle(PK)終了後も、最終スコアと勝敗を表示したままスコアバーをこの秒数だけ画面に残します(勝利タイム/結果表示用)。終了と同時に消さず、既定では60秒残します。次のBattleが始まる場合・動画が終わる場合はそこで打ち切ります。0で終了と同時に消します。",
    },
    "video_overlay_real_avatars": {
        "category": "overlay",
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
    "video_overlay_avatar_upscale": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_AVATAR_UPSCALE",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: 実アイコンをAI超解像で高精細化",
        "note": "焼き込む実ユーザーアイコンを合成前にAI超解像modelで高精細化します。TikTokが返すComment/GiftのアイコンはCDN上限が72x72の強圧縮画像で、拡大するとぼやけるため、これを補います(配信者アイコンはより高解像度を取得済み)。上記「Commentに実ユーザーアイコンを使う」が有効な場合のみ作用します。AI超解像model(TICTOK_UPSCALE_MODEL_PATH)とtorch/spandrelの導入が必要で、未導入時は元の低解像アイコンで焼き込みます(logに記録)。超解像結果はUser単位でcacheします。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "video_overlay_min_height": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_MIN_HEIGHT",
        "default": 2560,
        "type": int,
        "min": 720,
        "max": 2560,
        "label": "動画化: 焼き込みの最低出力高さ(px)",
        "note": "焼き込む文字・絵文字・アイコンは出力解像度で描画されるため、sourceがこの高さより低い場合は先に拡大(lanczos)してから焼き込みます。TikTokのsourceは720x1280が上限なので、既定の2560では約2倍の大きさで描画され、アイコンの円は46px→94pxになります(実ユーザーアイコンはAI超解像で288px以上まで高精細化済みのため、拡大しても実detailが増えます)。映像本体はlanczos拡大なので鮮明にはならず、file sizeは1280比で約2.2倍・焼き込み時間は約1.7倍になります。保存容量を優先する場合は1280(拡大なし)にしてください。",
        "options": [
            {"value": 1280, "label": "1280 (拡大しない)"},
            {"value": 1920, "label": "1920 (1.5倍)"},
            {"value": 2560, "label": "2560 (2倍)"},
        ],
    },
    "video_overlay_font_size": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_FONT_SIZE",
        "default": 14,
        "type": int,
        "min": 8,
        "max": 80,
        "label": "動画化: Commentの文字サイズ(px)",
        "note": "焼き込むCommentの基準文字サイズ(動画の縦1280pxを基準)です。Commentは画面左下の高さ約33%・幅80%の領域に表示し、長いCommentは折り返して全文を表示します(省略記号なし)。文字を小さくすると同時表示行数が増えます。古いCommentは上端でグラデーション的にfade outします。",
    },
    "video_overlay_icon_percent": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_ICON_PERCENT",
        "default": 7,
        "type": int,
        "min": 1,
        "max": 30,
        "label": "動画化: Gift Iconのサイズ(動画高さに対する%)",
        "note": "焼き込むGift Iconの大きさを、動画の縦pxに対する割合(%)で指定します。動画解像度に応じて動的に算出されます。",
    },
    "video_overlay_quality": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_QUALITY",
        "default": 21,
        "type": int,
        "min": 14,
        "max": 32,
        "label": "動画化: 出力画質(小さいほど高画質・大file)",
        "note": "焼き込み出力のEncode品質(CRF/CQ相当, おおよそ0〜51)。小さいほど高画質ですがfileは大きくなります。元配信が既に圧縮済みのため、14程度より下げても見た目はほぼ変わらずfileだけ肥大化します。GPU(NVENC)利用時もこの値を使います。",
    },
    "video_overlay_codec": {
        "category": "overlay",
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
    "video_overlay_subtitles": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_SUBTITLES",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: 文字起こし字幕を焼き込む",
        "note": "文字起こし済みの録画に対して、そのsegmentを字幕として動画へ焼き込みます。字幕の時刻は元録画mp4のmedia軸(PTS)基準で、Comment/Gift/Battleとは別の座標帯に描きます。文字起こしが無い録画・古い時刻mapで作られた文字起こしの録画は、ズレた字幕を恒久的に焼き込まないため出力を拒否します(先に文字起こしをやり直してください)。誤認識をそのまま焼き込む点に注意し、修正したい場合は焼き込みではなく字幕fileの書き出し(履歴の文字起こし画面)を使ってください。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "video_overlay_subtitle_font_size": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_SUBTITLE_FONT_SIZE",
        "default": 26,
        "type": int,
        "min": 8,
        "max": 96,
        "label": "動画化: 字幕の文字サイズ(px)",
        "note": "焼き込む字幕の基準文字サイズ(動画の縦1280pxを基準)です。実際のサイズは動画の解像度に応じて自動で拡大縮小します。長い字幕は画面幅に合わせて折り返します。",
    },
    "video_overlay_subtitle_position_percent": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_SUBTITLE_POSITION_PERCENT",
        "default": 58,
        "type": int,
        "min": 5,
        "max": 95,
        "label": "動画化: 字幕の縦位置(画面上端からの%)",
        "note": "字幕の中心を、動画の縦方向のどの位置に置くかを%で指定します。既定の58%はCommentの表示帯(下から約33%)の直上で、CommentともBattleスコアバーとも重なりません。値を大きくするとCommentの表示帯へ、小さくするとGift演出の帯へ近づくので、重ねたくない要素に応じて調整してください。",
    },
    "video_output_normalize_audio": {
        "category": "audio",
        "env": "TICTOK_VIDEO_OUTPUT_NORMALIZE_AUDIO",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: 出力の音量を正規化する(焼き込み出力・Up出力)",
        "note": "焼き込み出力とUp出力の音声を、下の目標値へ揃えて出力します。配信ごとの音量差を投稿前に手作業で直す必要がなくなります。音声だけを再encodeし、映像の扱いは変わりません。設定を変えると焼き込みの出力cacheは無効になり、次に出力を押したときに作り直します。描くもの(Comment/Gift/スコアバー/字幕)が1つも無い録画でも、映像はそのままcopyして音声だけを再encodeした出力を作ります。上の焼き込み設定を全てOFFにした場合は出力自体を行わないため、正規化もかかりません。切り出し(clip)側の正規化は切り出し時に個別に選べます。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "audio_normalize_lufs": {
        "category": "audio",
        "env": "TICTOK_AUDIO_NORMALIZE_LUFS",
        "default": -14.0,
        "type": float,
        "min": -40.0,
        "max": -5.0,
        "label": "音量正規化: 目標音量(LUFS)",
        "note": "音量正規化(loudnorm)の目標となる統合ラウドネスです。切り出し・焼き込み出力・Up出力で共通に使います。-14 LUFSは各SNSの配信でおおむね標準的な値で、小さくするほど静かになります。",
    },
    "audio_normalize_true_peak": {
        "category": "audio",
        "env": "TICTOK_AUDIO_NORMALIZE_TRUE_PEAK",
        "default": -1.5,
        "type": float,
        "min": -9.0,
        "max": 0.0,
        "label": "音量正規化: 上限ピーク(dBTP)",
        "note": "音量正規化の際に許す最大の真のピークです。0に近いほど音圧を保てますが、再encode時に歪みやすくなります。",
    },
    "audio_normalize_bitrate_kbps": {
        "category": "audio",
        "env": "TICTOK_AUDIO_NORMALIZE_BITRATE_KBPS",
        "default": 192,
        "type": int,
        "min": 64,
        "max": 512,
        "label": "音量正規化: 音声のbitrate(kbps)",
        "note": "音量正規化は音声の再encode(AAC)を伴うため、その品質を指定します。録画時の変換と同じ192kbpsが既定です。正規化しない場合、音声はそのまま複製されるのでこの値は使いません。",
    },
    "clip_normalize_audio": {
        "category": "clip",
        "env": "TICTOK_CLIP_NORMALIZE_AUDIO",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し: 音量正規化の既定",
        "note": "動画画面の切り出しで「音量を正規化」を最初からONにしておくかどうかです。切り出しのたびに画面側で変更できます。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "clip_pad_before_seconds": {
        "category": "clip",
        "env": "TICTOK_CLIP_PAD_BEFORE_SECONDS",
        "default": 8,
        "type": int,
        "min": 0,
        "max": 60,
        "label": "切り出し候補: 前paddingの秒数",
        "note": "切り出し候補の開始を、検出した区間の何秒前から始めるかです。stream copyでの切り出しはkeyframe単位(録画のsegmentは2秒)でしか切れないため、paddingが無いと出だしが欠けます。",
    },
    "clip_pad_after_seconds": {
        "category": "clip",
        "env": "TICTOK_CLIP_PAD_AFTER_SECONDS",
        "default": 5,
        "type": int,
        "min": 0,
        "max": 60,
        "label": "切り出し候補: 後paddingの秒数",
        "note": "切り出し候補の終了を、検出した区間の何秒後まで伸ばすかです。",
    },
    "clip_candidate_window_seconds": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_WINDOW_SECONDS",
        "default": 30,
        "type": int,
        "min": 5,
        "max": 600,
        "label": "切り出し候補: 検出窓の長さ(秒)",
        "note": "盛り上がりを測る移動窓の長さです。各配信のTimeline集計bucket幅から窓に入るbucket数を導くため、bucket幅の異なる配信の間でも同じ長さで比較できます。bucket幅より短い値を指定してもbucket 1個ぶんが下限です。",
    },
    "clip_candidate_zscore": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_ZSCORE",
        "default": 2.0,
        "type": float,
        "min": 0.5,
        "max": 10.0,
        "label": "切り出し候補: 検出のしきい値(z)",
        "note": "配信内の平均からの外れ具合(標準偏差の何倍か)がこの値以上の窓を候補にします。配信者pageの「ハイライト」と同じ判定で、既定の2.0もそこと同じです。小さくすると候補は増えますが、平凡な場面も混ざります。",
    },
    "clip_candidate_lead_seconds": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LEAD_SECONDS",
        "default": 10,
        "type": int,
        "min": 0,
        "max": 120,
        "label": "切り出し候補: 先行秒数(lead)",
        "note": "候補の開始をこの秒数だけ前へずらします。ギフトもコメントも「出来事への反応」なので、反応が始まった時刻から切ると原因の場面が入りません。Commentと映像の時刻ズレの補正ではありません(そちらは変換側で解決済みです)。",
    },
    "clip_candidate_audio": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_AUDIO",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し候補: 音声の盛り上がりも見る",
        "note": "ギフトとコメントに加えて、音量の急上昇も候補の判定に使います。歓声や笑い声はギフトにもコメントにも現れないことがあるため、それらを拾えます。各候補には無音の割合も付きます。初回は録画の音声を最後まで読むため長尺で90秒級かかります(波形表示と同じ処理で、一度作れば以後は再利用します)。",
        "options": [
            {"value": 0, "label": "しない (ギフトとコメントのみ)"},
            {"value": 1, "label": "する (音量の急上昇も候補にする)"},
        ],
    },
    "clip_candidate_limit": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LIMIT",
        "default": 20,
        "type": int,
        "min": 1,
        "max": 200,
        "label": "切り出し候補: 表示する上限件数",
        "note": "1つの録画について、盛り上がりの大きい順に何件まで候補を出すかです。",
    },
    "video_overlay_timing_compare": {
        "category": "overlay_timing",
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
        "category": "overlay_timing",
        "env": "TICTOK_VIDEO_OVERLAY_COMMENT_DELAY_SECONDS",
        "default": 0,
        "type": int,
        "min": -30,
        "max": 30,
        "label": "動画化: Comment/Giftの時刻補正(秒)",
        "note": "焼き込むComment/Giftの表示time刻を一律でずらします。配信映像はCDNで数秒遅れて録画されるため、Commentが映像より先行して見える場合に+方向(例:+5)で後ろへずらして合わせます。逆に遅れて見える場合は-方向にします。0で補正なし。",
    },
    "video_overlay_gift_seconds": {
        "category": "overlay_timing",
        "env": "TICTOK_VIDEO_OVERLAY_GIFT_SECONDS",
        "default": 4,
        "type": int,
        "min": 1,
        "max": 20,
        "label": "動画化: Gift演出の表示秒数",
        "note": "Gift通知Cardを表示し続ける秒数です。",
    },
    "video_overlay_gift_min_diamonds": {
        "category": "overlay_timing",
        "env": "TICTOK_VIDEO_OVERLAY_GIFT_MIN_DIAMONDS",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 100000,
        "label": "動画化: Gift演出の最小diamonds",
        "note": "この値以上のdiamondsのGiftだけを演出表示します。0で全Giftを表示します。安価なGiftが多い配信で画面が埋まるのを防げます。",
    },
    "video_overlay_preview_seconds": {
        "category": "overlay_timing",
        "env": "TICTOK_VIDEO_OVERLAY_PREVIEW_SECONDS",
        "default": 30,
        "type": int,
        "min": 5,
        "max": 300,
        "label": "動画化: プレビュー動画の尺(秒)",
        "note": "焼き込み設定を確認するためのプレビュー動画の長さです。プレビューは本出力と同じ解像度・codec・qualityで焼き込み、尺だけをここで切ります(costを決めるのは解像度ではなく尺なので、短いほど速く確認できます)。切り出す区間はComment/Gift/Battleが最も多い場所を自動で選びます。この設定は本出力には一切影響せず、変更しても既存の焼き込みは作り直しになりません。",
    },
    "recording_keep_hls": {
        "category": "storage",
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
    "disk_min_free_gb": {
        "category": "storage",
        "env": "TICTOK_DISK_MIN_FREE_GB",
        "default": 20,
        "type": int,
        "min": 0,
        "max": 4096,
        "label": "出力を拒否する空き容量の下限（GB）",
        "note": "焼き込み・AI高画質化(Up出力)を開始する前に出力先ドライブの空き容量を確認し、この値を下回っていれば開始を拒否します。中間fileが多層に積み上がるため、元動画の数倍の空きが必要です。0で拒否しません(確認だけ行います)。診断log用のしきい値(TICTOK_LOG_DISK_LOW_BYTES)とは別で、こちらは実際に処理を止めます。",
    },
    "retention_transient_hours": {
        "category": "storage",
        "env": "TICTOK_RETENTION_TRANSIENT_HOURS",
        "default": 24,
        "type": int,
        "min": 0,
        "max": 8760,
        "label": "保持policy: 中間fileを削除するまでの経過時間（時間）",
        "note": "焼き込みの途中file(CFR base・comment layer)は正常終了すると自動で消えますが、途中で落ちるとdiskに残り続けます。最終更新からこの時間が過ぎた残骸を削除対象にします。実行中のrenderのfileを巻き込まないための猶予なので、短くしすぎないでください。0でこの段階を実行しません。削除は設定だけでは起きず、設定画面「保持policy」の「削除内容を確認（削除しません）」→「確認した内容を削除する」を押したときのみ実行します。",
    },
    "retention_derived_days": {
        "category": "storage",
        "env": "TICTOK_RETENTION_DERIVED_DAYS",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 3650,
        "label": "保持policy: 派生物を削除するまでの日数",
        "note": "焼き込み(.overlay.mp4)とAI高画質化(.up.mp4)は元録画と収集eventから作り直せる派生物です。最終更新からこの日数が過ぎたものを削除対象にします(元録画は残ります)。保護flagを立てた録画は対象外です。0でこの段階を実行しません。削除は設定画面「保持policy」の「削除内容を確認（削除しません）」→「確認した内容を削除する」を押したときのみ実行します。",
    },
    "retention_source_enabled": {
        "category": "storage",
        "env": "TICTOK_RETENTION_SOURCE_ENABLED",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "保持policy: 生録画の自動削除",
        "note": "生録画のmp4は唯一の再取得不能なdataで、消すと再mp4化・再出力・文字起こし・切り出し・盛り上がり解析がまとめて復旧不能になります(文字起こし結果も録画と一緒に消えます)。既定は無効です。有効にしても、実行前に必ず削除内容の一覧(dry-run)が表示され、確認するまで削除しません。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "retention_source_days": {
        "category": "storage",
        "env": "TICTOK_RETENTION_SOURCE_DAYS",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 3650,
        "label": "保持policy: 生録画を削除するまでの日数",
        "note": "上の「生録画の自動削除」が有効な場合に限り、配信終了からこの日数が過ぎた録画を削除対象にします。保護flagを立てた録画は対象外です。0でこの段階を実行しません。",
    },
    "retention_free_target_gb": {
        "category": "storage",
        "env": "TICTOK_RETENTION_FREE_TARGET_GB",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 4096,
        "label": "保持policy: 削除を打ち切る空き容量（GB）",
        "note": "保持policyの実行中、対象driveの空き容量がこの値に達した時点で以降の削除を打ち切ります。古いものから順に消すため、必要な分だけ空けて残りは保持できます。0で打ち切らず、条件に合うものをすべて削除します。",
    },
}


class Settings:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._values: dict = {}
        self._load()

    def _env_default(self, key: str):
        """Resolve the default for one key, honouring an environment override.

        An env value becomes both the running value and the value the UI offers as
        「既定値へ戻す」, so it has to clear the same bar as anything typed into the form.
        Without that, an out-of-range env value is accepted at start and then rejected
        with a 422 the moment the operator saves it back. No fallback: an invalid value
        is reported and raised, not quietly replaced by the built-in default.
        """
        definition = SETTING_DEFS[key]
        raw = os.environ.get(definition["env"])
        if raw is None:
            return definition["default"]
        try:
            if definition["type"] is str:
                return self._check_path_shape(definition, raw)
            return self._validate_number(definition, raw)
        except ValueError as exc:
            logger.error(
                "invalid setting from environment: %s=%s (%s)",
                definition["env"], raw, exc,
                extra={"event": "process.settings_env_invalid",
                       "ctx": {"key": key, "env": definition["env"], "reason": str(exc)}},
            )
            raise

    def _load(self) -> None:
        """Resolve every setting from DB > env > built-in default.

        Only the per-source counts are logged, never the values: the full set is
        available from the settings API and dumping ~30 lines of it at every start
        would crowd out the startup sequence it sits in. The counts still answer the
        question this log exists for — whether the running values come from the UI, the
        environment, or nothing at all.
        """
        stored = self._storage.get_settings()
        sources = {"from_db": 0, "from_env": 0, "from_default": 0}
        for key, definition in SETTING_DEFS.items():
            # DBが勝つ場合もenv既定値は解決しておく。describe()が後から同じ解決を行うため、
            # 不正なenvはここで起動を止め、設定画面が開けなくなる形で露見させない。
            env_default = self._env_default(key)
            if key in stored:
                self._values[key] = definition["type"](stored[key])
                sources["from_db"] += 1
            else:
                self._values[key] = env_default
                if os.environ.get(definition["env"]) is None:
                    sources["from_default"] += 1
                else:
                    sources["from_env"] += 1
        logger.info(
            "settings loaded (db=%d env=%d default=%d)",
            sources["from_db"], sources["from_env"], sources["from_default"],
            extra={"event": "process.settings_loaded",
                   "ctx": {"total": len(SETTING_DEFS), **sources}},
        )

    def get(self, key: str):
        return self._values[key]

    def all_values(self) -> dict:
        return dict(self._values)

    def describe(self) -> list:
        """画面へ渡す設定の定義一覧。

        defaultは「今この環境で『既定値へ戻す』を押したときに入る値」なので、環境変数で
        上書きされていればその値になる。built-in定数だけを返すと、env運用中に嘘の既定値を
        提示することになるため、default_sourceとbuiltin_defaultも併せて返して画面が
        「環境変数で上書き中」を表示できるようにする。
        """
        described = []
        for key, definition in SETTING_DEFS.items():
            from_env = os.environ.get(definition["env"]) is not None
            entry = {
                "key": key,
                "value": self._values[key],
                "label": definition["label"],
                "note": definition["note"],
                "category": definition["category"],
                "category_label": CATEGORY_LABELS[definition["category"]],
                "default": self._env_default(key),
                "default_source": "env" if from_env else "builtin",
                "builtin_default": definition["default"],
                "env": definition["env"],
            }
            if definition["type"] is str:
                entry["kind"] = "text"
            else:
                entry["min"] = definition["min"]
                entry["max"] = definition["max"]
                entry["step"] = 1 if definition["type"] is int else 0.5
            if "options" in definition:
                entry["options"] = definition["options"]
            described.append(entry)
        return described

    def _check_path_shape(self, definition: dict, value) -> str:
        """Shape-only check for a directory-path setting: non-empty (unless allow_empty)
        and absolute. Kept free of side effects so it can also gate env defaults, which
        are resolved on every describe() — mkdir/W_OK there would touch the filesystem
        on every settings read."""
        text = str(value).strip().strip('"')
        if not text:
            if definition.get("allow_empty"):
                return ""
            raise ValueError(f"{definition['label']} を指定してください。")
        if not Path(text).is_absolute():
            raise ValueError(
                f"{definition['label']} は絶対パスで指定してください（例: K:\\80_Tiktok）。"
            )
        return text

    def _validate_path(self, definition: dict, value) -> str:
        """Validate a directory-path setting: it must be a non-empty absolute path that
        can be created and written to. Rejects invalid input (no silent fallback) so the
        operator gets immediate feedback rather than a broken record dir at next start."""
        text = self._check_path_shape(definition, value)
        if not text:
            return ""
        path = Path(text)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"{definition['label']} のフォルダを作成できません: {exc}")
        if not os.access(path, os.W_OK):
            raise ValueError(f"{definition['label']} に書き込みできません: {path}")
        return str(path)

    def _validate_number(self, definition: dict, value):
        """Coerce and range-check one numeric setting. Shared by update() and the env
        default resolution so both gates accept exactly the same set of values."""
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
        return typed

    def update(self, values: dict) -> dict:
        """Validate and persist a settings change.

        A settings change is a state transition worth reconstructing months later
        ("did the recording stall start when the stall timeout was lowered?"), so the
        accepted diff goes to ops_events as well as the log, and it carries the old
        value alongside the new one — knowing a key changed is useless without knowing
        what it changed from. Rejected input stays at info: the operator already gets a
        422 with the reason, and the request itself is recorded by the access log
        (see the ValueError handler in the settings endpoint).
        """
        validated = {}
        for key, value in values.items():
            if key not in SETTING_DEFS:
                raise ValueError(f"不明な設定key: {key}")
            definition = SETTING_DEFS[key]
            if definition["type"] is str:
                validated[key] = self._validate_path(definition, value)
                continue
            validated[key] = self._validate_number(definition, value)
        if validated:
            changes = {
                key: [self._values.get(key), value]
                for key, value in validated.items()
                if self._values.get(key) != value
            }
            self._storage.set_settings(validated)
            self._values.update(validated)
            self._storage.record_ops_event(
                logger,
                "process.settings_updated",
                "settings updated: " + (
                    ", ".join(f"{k}: {old} -> {new}" for k, (old, new) in changes.items())
                    or "no effective change"
                ),
                detail={"changes": changes, "changed": len(changes),
                        "submitted": len(validated)},
            )
        return self.all_values()
