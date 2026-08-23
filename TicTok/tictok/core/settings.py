import logging
import os
from pathlib import Path

from tictok.paths import PROJECT_ROOT
from tictok.record import telop_styles
from tictok.storage import OPS_ERROR, Storage

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
    "notify": "通知(webhook)",
    "discovery": "配信者の発見",
    "fans": "Fan台帳",
    "capacity": "容量予測",
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
    "live_check_schedule_enabled": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_SCHEDULE_ENABLED",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "options": [{"value": 0, "label": "しない"}, {"value": 1, "label": "する"}],
        "label": "配信しやすい時間帯へLIVE確認を寄せる",
        "note": "過去の配信開始時刻から配信者ごとの時間帯の偏りを推定し、確率の高い時間帯の確認間隔を詰め、低い時間帯を広げます。総アクセス数は変わりません。既定でoffなのは、確認の総量が上限に達している状態では時間帯間に融通できる余剰が無く、実測で検出の速さがほとんど変わらないためです。上限に余裕がある場合のみ効果があります。",
    },
    "live_check_schedule_floor": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_SCHEDULE_FLOOR",
        "default": 0.35,
        "type": float,
        "min": 0.0,
        "max": 1.0,
        "label": "時間帯推定の平滑化(一様分布との混合比)",
        "note": "推定した時間帯分布を、どれだけ一様分布へ寄せるかです。大きいほど過去の偏りを信用せず全時間帯を平等に扱います。履歴が少ないうちに特定の時間帯へ寄せすぎるのを防ぎます。",
    },
    "live_check_schedule_min_factor": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_SCHEDULE_MIN_FACTOR",
        "default": 0.5,
        "type": float,
        "min": 0.1,
        "max": 1.0,
        "label": "確認間隔を詰められる下限の倍率",
        "note": "配信しやすい時間帯で、確認間隔をどこまで短くしてよいかの下限です。0.5なら通常の半分までです。",
    },
    "live_check_schedule_max_factor": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_SCHEDULE_MAX_FACTOR",
        "default": 2.0,
        "type": float,
        "min": 1.0,
        "max": 8.0,
        "label": "確認間隔を広げられる上限の倍率",
        "note": "配信しにくい時間帯でも、確認間隔をこの倍率までしか広げません。予測が外れたときに配信を取り逃さないための保証です。",
    },
    "live_check_schedule_min_sessions": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_SCHEDULE_MIN_SESSIONS",
        "default": 8,
        "type": int,
        "min": 1,
        "max": 200,
        "label": "時間帯推定に必要な過去の配信本数",
        "note": "この本数に満たない配信者は推定せず、全時間帯を平等に確認します。少ない履歴から偏りを決めつけないためです。",
    },
    "live_check_schedule_window_days": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_SCHEDULE_WINDOW_DAYS",
        "default": 90,
        "type": int,
        "min": 7,
        "max": 365,
        "label": "時間帯推定に使う過去の日数",
        "note": "何日前までの配信履歴を推定に使うかです。長いほど安定しますが、配信時間帯が変わった場合の追従は遅くなります。",
    },
    "live_check_schedule_refresh_seconds": {
        "category": "collect",
        "env": "TICTOK_LIVE_CHECK_SCHEDULE_REFRESH_SECONDS",
        "default": 3600,
        "type": int,
        "min": 60,
        "max": 86400,
        "label": "時間帯推定の再計算間隔（秒）",
        "note": "推定を何秒ごとに作り直すかです。短くすると新しい配信がすぐ反映されますが、その都度DBを読みます。",
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
    "sign_block_attempts": {
        "category": "collect",
        "env": "TICTOK_SIGN_BLOCK_ATTEMPTS",
        "default": 5,
        "type": int,
        "min": 1,
        "max": 100,
        "label": "署名が通らない配信を諦めるまでの回数",
        "note": "接続に必要な署名が続けて失敗したとき、その配信を「署名できない配信」と判定するまでの連続回数です。署名サーバーの一時的な不調は数回で復旧しますが、その配信だけが署名できない状態は何度撃っても変わらないため、この回数で再接続を打ち切り、以降は「録画不可判定の再確認間隔」に従って間隔を広げながら撃ち直します。判定はまだ一度も接続できていない配信にのみ適用されるため、録画中の配信が切れた場合の再接続は打ち切りません。",
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
    "ws_recent_events": {
        "category": "collect",
        "env": "TICTOK_WS_RECENT_EVENTS",
        "default": 200,
        "type": int,
        "min": 0,
        "max": 5000,
        "label": "WS接続時に1度に送るEvent件数",
        "note": "画面を開いた時に届くsnapshotへ載せるEventの件数です。上のEvent履歴件数はcollectorが手元に抱える深さで、こちらは1通のmessageに載せる量です。画面が使うのは末尾ぶんだけ（監視画面のfeedは200件、一覧画面は最新のGift/Commentのみ）なので、履歴を深くしてもここは増やす必要がありません。大きくすると画面を開くたびに数MBのmessageを組み立てることになり、その画面が続けて出すAPIがすべてその後ろに並びます。0で送りません。",
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
    "gifter_league_enabled": {
        "category": "collect",
        "env": "TICTOK_GIFTER_LEAGUE_ENABLED",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "options": [{"value": 0, "label": "しない"}, {"value": 1, "label": "する"}],
        "label": "ギフターの配信者リーグ帯を取得する",
        "note": "Giftを投げた視聴者が自分でも配信しているかを確認し、配信者リーグ帯（A1/B3など）を取得します。取得できた人は名前の横にリーグが表示されます。TikTokへのアクセスを伴うため待ち行列に積んで1件ずつ流します。offにすると新規の取得を止めます（取得済みの表示は残ります）。",
    },
    "gifter_league_interval_seconds": {
        "category": "collect",
        "env": "TICTOK_GIFTER_LEAGUE_INTERVAL_SECONDS",
        "default": 15,
        "type": int,
        "min": 5,
        "max": 600,
        "label": "リーグ取得の間隔（秒／1人あたり）",
        "note": "待ち行列から1人を処理する間隔です。短すぎるとTikTok側に一時的なアクセス制限を掛けられ、しばらく応答が読めなくなります（2秒間隔・約250件で発生を実測）。LIVE確認の上限とは別枠のアクセスです。",
    },
    "gifter_league_min_coin": {
        "category": "collect",
        "env": "TICTOK_GIFTER_LEAGUE_MIN_COIN",
        "default": 1000,
        "type": int,
        "min": 1,
        "max": 1000000,
        "label": "リーグ取得の対象にするコイン数",
        "note": "その日にこのコイン数以上を投げた視聴者だけを待ち行列に積みます。小さくすると対象が急増し、1件ずつ流すため行列が滞留します。実データでは通算1000コイン以上の770人でギフト全体の98.2%を占め、そこから全員まで広げても0.9ポイントしか増えません（人数は9倍）。",
    },
    "gifter_league_recheck_days": {
        "category": "collect",
        "env": "TICTOK_GIFTER_LEAGUE_RECHECK_DAYS",
        "default": 5,
        "type": int,
        "min": 1,
        "max": 365,
        "label": "リーグを取り直す間隔（日）",
        "note": "リーグ帯は日々変動します。一度確認した人は、この日数を過ぎてから再びGiftを投げたときに取り直します。",
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
    "linklayer_raw_capture": {
        "category": "diagnostic",
        "env": "TICTOK_LINKLAYER_RAW_CAPTURE",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "コラボ判定の生Event記録",
        "note": "コラボ(LinkMic)のLinkLayer eventを、重複除外なしで全件 samples/raw/LinkLayerEvent_<session>.jsonl へ時刻つきに保存します。コラボ窓の判定ruleが実配信の届き方と合っているかを、録画映像と突き合わせて検証するための診断用です。1配信ぶん取れたら無効化してください（有効な間はコラボの多い配信で数万行になります）。",
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
    "asset_archive_ticket_ttl_seconds": {
        "category": "ui",
        "env": "TICTOK_ASSET_ARCHIVE_TICKET_TTL_SECONDS",
        "default": 600,
        "type": int,
        "min": 30,
        "max": 86400,
        "label": "素材のまとめDownload: 引換券の有効期限（秒）",
        "note": "素材pageで「まとめてDownload」を押すと、serverはZIPの中身を数えて引換券を発行し、browserがその券でZIP本体を取りに来ます。券をどれだけ保持するかです。期限が切れた券は404になり、画面は選び直しを促します。短すぎると、対象を数えている間に期限が切れます(Userアイコン全件は22万fileを数えるので数秒かかります)。長くしても増えるのはserverが覚えている券の数だけで、ZIPそのものはこの間作られません。",
    },
    "asset_archive_max_ids": {
        "category": "ui",
        "env": "TICTOK_ASSET_ARCHIVE_MAX_IDS",
        "default": 5000,
        "type": int,
        "min": 1,
        "max": 100000,
        "label": "素材のまとめDownload: 一度に選べる件数",
        "note": "素材を個別に選んでまとめる場合の上限です。これを超えると、押した時点で理由を表示して断ります(数え始めてから断ると待たせた末の失敗になります)。「全件」を選んだ場合はこの上限を受けません(選んだ物を持ち回る必要が無いためです)。",
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
        "note": "文字起こし済みの録画に対して、そのsegmentを字幕として動画へ焼き込みます。字幕の時刻は素材の再生軸(media軸)基準で、Comment/Gift/Battleとは別の座標帯に描きます。文字起こしが無い録画・古い時刻mapで作られた文字起こしの録画・文字起こしの尺が素材の実尺と合わない録画は、ズレた字幕を恒久的に焼き込まないため出力を拒否します(先に文字起こしをやり直してください)。誤認識をそのまま焼き込む点に注意し、修正したい場合は焼き込みではなく字幕fileの書き出し(履歴の文字起こし画面)を使ってください。",
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
    "video_overlay_subtitle_style": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_SUBTITLE_STYLE",
        "default": telop_styles.DEFAULT_STYLE_VALUE,
        "type": int,
        "min": min(telop_styles.STYLE_VALUES),
        "max": max(telop_styles.STYLE_VALUES),
        "label": "動画化: 字幕(テロップ)の見た目",
        "note": "焼き込む字幕の書体・色・フチ・動きの組み合わせを選びます。見本はいずれも本番と同じ描画経路で焼いた実物で、背景のgradientは暗い映像・明るい映像の両方でどう見えるかを確かめるためのものです(文字の大きさは見本用に拡大してあり、実際の大きさは下の設定で決まります)。書体は同梱fontを直接読ませるので、動かすmachineに何のfontが入っていても出力は同じになります(初回だけ配布元からの取得が走ります)。取得できない場合は別の書体で代替せず焼き込みを止めます。",
        "options": telop_styles.settings_options(),
        # 選択肢ごとの見本画像。画面はこのtemplateの {value} を選択肢の値へ差し替えて読む
        # (どのkeyが画像を持つかを画面側にhard-codeさせないため)。
        "option_image": "/api/settings/telop-preview/{value}.png",
    },
    "video_overlay_subtitle_animation": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_SUBTITLE_ANIMATION",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "動画化: 字幕の出入りの動き",
        "note": "見た目で選んだpresetが持つfade(淡い出入り)と、出だしの拡大popを付けるかどうかです。書体・色・フチはそのままに動きだけを止められます。素材として別の編集softへ持ち込む場合など、動きが邪魔になるときにOFFにしてください。",
        "options": [
            {"value": 0, "label": "止める"},
            {"value": 1, "label": "付ける"},
        ],
    },
    "video_overlay_subtitle_max_lines": {
        "category": "overlay",
        "env": "TICTOK_VIDEO_OVERLAY_SUBTITLE_MAX_LINES",
        "default": 4,
        "type": int,
        "min": 1,
        "max": 6,
        "label": "動画化: 字幕の最大行数",
        "note": "1つの字幕が画面幅で折り返した結果この行数を超えた場合、超えた行は描きません(字幕が画面を覆うのを防ぐため)。short動画のテロップは2行までが読みやすい一方、行数を絞るほど長い発話の後半が焼き込まれなくなります。捨てた行数はlogと焼き込みの診断に残ります。",
    },
    # 表示単位(cue)の寸法。焼き込み・切り抜きの添付字幕・録画丸ごとの書き出しが同じ値を使う。
    # ここを画面ごとに分けると、同じ文字起こしから出した字幕の切れ目が経路ごとに変わる。
    "subtitle_chars_per_line": {
        "category": "overlay",
        "env": "TICTOK_SUBTITLE_CHARS_PER_LINE",
        "default": 16,
        "type": int,
        "min": 8,
        "max": 40,
        "label": "字幕: 1行の文字数(全角換算)",
        "note": "字幕1行に載せる文字数の上限です(半角は0.5字として数えます)。縦画面(1080x1920)で幅の9割を使うと、読める大きさのテロップは1行あたり全角15〜16字になります。SRT/VTTは書体を持たない書式なので、読み手が何で描くか分からず、この字数が唯一の目安になります。増やすと1枚に多く載りますが、投稿先の画面幅を超えると端が切れます。",
    },
    "subtitle_wrap_lines": {
        "category": "overlay",
        "env": "TICTOK_SUBTITLE_WRAP_LINES",
        "default": 2,
        "type": int,
        "min": 1,
        "max": 4,
        "label": "字幕: 1枚の行数",
        "note": "字幕1枚を何行まで折り返すかです。1行の文字数と掛けたものが1枚の文字予算になり、これを超える発話は次の枚へ送ります。TikTok・Shortsのような縦画面では2行までが読みやすく、3行以上は映像を覆います。折り返す位置は形態素解析で文の切れ目を選ぶので、行数を増やしても語の途中では切れません。",
    },
    "subtitle_safe_margin_percent": {
        "category": "overlay",
        "env": "TICTOK_SUBTITLE_SAFE_MARGIN_PERCENT",
        "default": 6.0,
        "type": float,
        "min": 0.0,
        "max": 30.0,
        "label": "字幕: 行の端に空ける余白(%)",
        "note": "1行の幅のうち、端に空けておく割合です。上限ちょうどまで詰めた行は、読み手の書体・字間・player側の内側余白が想定と少し違うだけで端が切れます。SRT/VTTは読み手が何で描くか分からない書式なので、上限そのものを守っても収まる保証がありません。焼き込みも同じ割合を実測した幅から引くので、どの書式で出しても折り返す位置は揃います。増やすほど安全ですが、1行に載る文字が減って枚数が増えます。",
    },
    "subtitle_max_seconds": {
        "category": "overlay",
        "env": "TICTOK_SUBTITLE_MAX_SECONDS",
        "default": 3.0,
        "type": float,
        "min": 1.0,
        "max": 10.0,
        "label": "字幕: 1枚を出しておく秒数の上限",
        "note": "字幕1枚が画面に出ている時間の上限です。これを超える発話は次の枚へ送ります。上限が長いほど画面の文と喋っている言葉が食い違う時間が伸び、短いほど枚が細かく入れ替わります。実際の表示時間は発話が終わった時点で終わるので、この値まで必ず出るわけではありません。",
    },
    "video_output_normalize_audio": {
        "category": "audio",
        "env": "TICTOK_VIDEO_OUTPUT_NORMALIZE_AUDIO",
        # 既定でON。録画の原本(.ts)は無加工で、再生もその原本をそのまま流すため、音量が
        # 揃うのは出力を作ったときだけになる。出力は投稿・視聴に回すものなので、既定を
        # OFFにしておくと配信ごとの音量差がそのまま成果物に残る。
        "default": 1,
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
    "reprocess_normalize_audio": {
        "category": "audio",
        "env": "TICTOK_REPROCESS_NORMALIZE_AUDIO",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "再mp4化: 元録画の音量も正規化する",
        "note": "再mp4化(.tsからのmp4作り直し)のついでに、録画そのものの音量を下の目標値へ揃えます。再mp4化はもともと音声をAACへ再encodeしているため、正規化を足しても所要時間はほとんど変わりません。元のmp4は_backup/へ退避され、.tsも残っているので作り直せます。単体で音量だけを揃えたい録画には、動画画面の「音量正規化」を使ってください。",
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
        "note": "音量正規化(loudnorm)の目標となる統合ラウドネスです。切り出し・焼き込み出力・Up出力・音量正規化・再mp4化で共通に使います。-14 LUFSは各SNSの配信でおおむね標準的な値で、小さくするほど静かになります。",
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
    "clip_remove_bgm": {
        "category": "clip",
        "env": "TICTOK_CLIP_REMOVE_BGM",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し: BGM除去の既定",
        "note": "動画画面の切り出しで「BGMを除去」を最初からONにしておくかどうかです。切り出しのたびに画面側で変更できます。話し声だけを残すため、BGMのほかにgift SE・battleの効果音・歓声も消えます。出力はmonoになり、切り出しの後に音声を作り直す時間（60秒で約9秒、10分で約45秒）が加わります。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "clip_subtitles": {
        "category": "clip",
        "env": "TICTOK_CLIP_SUBTITLES",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し: 字幕fileの既定",
        "note": "動画画面の切り出しで「字幕fileも出す」を最初からONにしておくかどうかです。切り出したmp4の隣へ同じ名前の字幕fileを置きます（映像は書き換えないので、文言も書体も後から直せます）。時刻は切り抜きの先頭を0秒とした軸で、元録画から切ったものにだけ添えます（焼き込み出力・Up出力は再encodeで時刻の一致が保証できません）。文字起こしが無い録画や、時刻mapが古い文字起こしには出しません。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "clip_subtitle_formats": {
        "category": "clip",
        "env": "TICTOK_CLIP_SUBTITLE_FORMATS",
        "default": "srt,ass",
        "type": str,
        "label": "切り出し: 字幕fileの書式",
        "note": "SRTはどの編集ソフト・投稿siteも読む素の文字で、装飾は持ちません。ASSは焼き込みのテロップ書体（色・縁・発光・影・出入りの動き・画面上の位置）をそのまま持ちますが、読ませる側にその書体が入っている必要があります（同梱fontはassets/fonts）。VTTはWeb player向けです。",
        "options": [
            {"value": "srt", "label": "SRTのみ（装飾なし・どこでも読める）"},
            {"value": "srt,ass", "label": "SRT + ASS（装飾つきも併せて出す）"},
            {"value": "ass", "label": "ASSのみ（装飾つき）"},
            {"value": "srt,vtt,ass", "label": "SRT + VTT + ASS（全て）"},
        ],
    },
    "clip_subtitle_anchor": {
        "category": "clip",
        "env": "TICTOK_CLIP_SUBTITLE_ANCHOR",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し: 字幕fileの先頭に錨のcueを置く",
        "note": "頭が無音の切り抜きで、0秒に空のcue（半角空白1つ・最長0.5秒）を1件足すかどうかです。DaVinci Resolveは字幕fileをtimelineへdragで置くと先頭cueを落とした位置へ吸着させるため、これが無いと頭の無音ぶん（実測2.584秒）だけ全cueが早くなります。0秒に錨があれば先頭cueの位置が動画の先頭と一致するので、dragでも時刻で差し込んでも同じ結果になります。空白のcueなので字は出ず、発話を捏造しません。SRTとVTTにだけ効きます（ASSは吸着しません）。",
        "options": [
            {"value": 0, "label": "置かない"},
            {"value": 1, "label": "置く"},
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
        "note": "切り出し候補の開始を、検出した区間の何秒前から始めるかです。盛り上がりに至るまでの流れを含めるためのもので、これが無いと文脈の無いところから始まります。なお出だしの欠けを防ぐためのものではありません(切り出しは指定時刻以前のkeyframeから始め、着地を毎回実測で確かめるため、paddingが0でも指定範囲は欠けません)。",
    },
    "clip_keyframe_scan_seconds": {
        "category": "clip",
        "env": "TICTOK_CLIP_KEYFRAME_SCAN_SECONDS",
        "default": 45,
        "type": int,
        "min": 2,
        "max": 300,
        "label": "切り出し: keyframe走査窓の秒数",
        "note": "切り出しの開始位置を決めるとき、指定時刻の何秒前までkeyframeを探すかです。指定時刻をそのままffmpegへ渡すと映像は**その直後**のkeyframeから始まり、指定した範囲の頭を最大1 GOP失います(実録画で実測)。そのため指定時刻以前のkeyframeを探してそこから切ります。現行の録画で実測したkeyframe間隔は最大6.1秒、過去には37.6秒の例があるため既定45秒はどちらも収まります。短すぎる値は黙って劣化せず、切り出しが失敗して理由を表示します。",
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
    "clip_default_mode": {
        "category": "clip",
        "env": "TICTOK_CLIP_DEFAULT_MODE",
        "default": "copy",
        "type": str,
        "label": "切り出しの既定の方式",
        "note": "高速: stream copyで数秒。切れ目はkeyframeまで手前へ伸びるため、指定より最大数十秒長くなります（素材として渡すなら前後の余白は扱いやすい面もあります）。smart: 先頭のGOPだけ再encodeして指定どおりのIN点で切ります。copyより数秒重いだけで、劣化するのは先頭の1 GOPに限られます。精密: 全編を再encodeします。範囲が1 GOPに収まる短い切り出しではsmartより速いことがあります。",
        "options": [
            {"value": "copy", "label": "高速 (前置きあり)"},
            {"value": "smart", "label": "smart (要求どおりのIN点)"},
            {"value": "precise", "label": "精密 (全編再encode)"},
        ],
    },
    "clip_candidate_laugh_comment": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LAUGH_COMMENT",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し候補: Commentの笑いも見る",
        "note": "「草」「w」「笑」「😂」などの笑いCommentの多さを候補の判定に使います。Comment全体の数とは別の指標で、実測ではCommentの多い窓と8割が別の時刻を指しました(相関 0.29)。ギフトが跳ねた窓では逆に笑いが減るため、ギフト連打と笑いを区別できます。追加のinstallも解析時間も不要です。",
        "options": [
            {"value": 0, "label": "見ない"},
            {"value": 1, "label": "見る"},
        ],
    },
    "clip_candidate_laugh_weight": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LAUGH_WEIGHT",
        "default": 1.0,
        "type": float,
        "min": 0.0,
        "max": 3.0,
        "label": "切り出し候補: 笑いの重視度",
        "note": "笑い指標のz-scoreに掛ける倍率です。1.0で上位20件のうち笑い由来が中央値25%になります(実測)。2.0にすると6割が笑い由来になり、0.5では ほぼ従来どおりです。",
    },
    "clip_candidate_laugh_min_comments": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LAUGH_MIN_COMMENTS",
        "default": 2,
        "type": int,
        "min": 0,
        "max": 100,
        "label": "切り出し候補: 笑いCommentの最小件数",
        "note": "窓内の笑いCommentがこの件数に満たない場合は候補にしません。笑いはほとんどの窓で0件のため、下限を置かないと「ほとんど笑いの無い配信のたった1件」が統計的に大きく見えて候補を占領します。3以上にすると実測で候補が89%消えます。",
    },
    "clip_candidate_laugh_audio": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LAUGH_AUDIO",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し候補: 笑い声(音声)も見る",
        "note": "録画の音声から笑い声そのものを検出し、笑っていた秒数を候補の判定に使います。配信者と参加者の笑いはCommentにもギフトにも現れないことがあり、これはその瞬間を直接拾える唯一の指標です。ONNXのaudio tagging modelとlabel fileを別途配置し、TICTOK_LAUGH_AUDIO_ENABLED / _MODEL_PATH / _LABELS_PATH の設定が必要です(入手手順は doc/LAUGH_AUDIO_MODEL.md)。modelが無い状態でこれをONにすると候補の算出は失敗します(笑い0件として黙って算出しません)。初回は録画の音声を最後まで読むためCPUで数十秒〜数分かかり、結果は録画ごとに再利用します。",
        "options": [
            {"value": 0, "label": "見ない"},
            {"value": 1, "label": "見る (音声から笑い声を検出)"},
        ],
    },
    "clip_candidate_laugh_audio_weight": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LAUGH_AUDIO_WEIGHT",
        "default": 1.0,
        "type": float,
        "min": 0.0,
        "max": 3.0,
        "label": "切り出し候補: 笑い声の重視度",
        "note": "笑い声指標のz-scoreに掛ける倍率です。Commentの笑いの重視度と同じ意味で、大きくすると候補の上位が笑い声由来で占められ、0.0にすると判定には効かなくなります(値は候補の根拠として表示されます)。",
    },
    "clip_candidate_laugh_audio_solo_only": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LAUGH_AUDIO_SOLO_ONLY",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し候補: コラボ中の笑い声は数えない",
        "note": "画面に顔が2つ以上映っている間の笑い声を候補の判定から外します。コラボ中の笑いは共演者のものかもしれず、配信者を画面から特定する手段が無いためです。判定には映像の顔検出を使うので、笑顔の設定と同じmodel(TICTOK_SMILE_FACE_MODEL_PATH / TICTOK_SMILE_MODEL_PATH)の配置が要ります。実測では多人数のコラボが多い配信で素材の91%がこれに当たり、単独は8%でした。顔が0個の標本(ゲーム画面・カメラ外し)は除外しません。DBのコラボ窓を使わないのは、あちらが記録しているのが人数ではなくLinkMic channelの有無だからです(811窓中805窓でguest数が0のまま)。",
        "options": [
            {"value": 0, "label": "コラボ中も数える"},
            {"value": 1, "label": "コラボ中は数えない (顔が2つ以上)"},
        ],
    },
    "clip_candidate_laugh_audio_min_seconds": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_LAUGH_AUDIO_MIN_SECONDS",
        "default": 3.0,
        "type": float,
        "min": 0.0,
        "max": 60.0,
        "label": "切り出し候補: 笑い声の最小秒数",
        "note": "窓内で笑い声が出ていた秒数がこの値に満たない場合は候補にしません。笑い声もほとんどの窓で0秒のため、下限を置かないと「ほとんど笑いの無い配信の1刻みぶん」が統計的に大きく見えて候補を占領します。刻みの幅は TICTOK_LAUGH_AUDIO_HOP_SECONDS(既定1秒)です。",
    },
    "clip_candidate_smile": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_SMILE",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "切り出し候補: 笑顔(映像)も見る",
        "note": "録画の映像から顔を探し、笑顔と判定できた秒数を候補の判定に使います。**顔がちょうど1つ映っている場面しか判定できません** — 画面のどれが配信者かを決める手段が無いため、battle・collabで画面が分割されている間は判定を捨てます(その区間の値は実際より小さく出ます)。顔検出と笑顔判定のONNX modelを別途配置し、TICTOK_SMILE_ENABLED / _FACE_MODEL_PATH / _MODEL_PATH の設定が必要です(入手手順は doc/SMILE_MODEL.md)。modelが無い状態でこれをONにすると候補の算出は失敗します(笑顔0件として黙って算出しません)。初回は録画をsamplingしながら復号するためCPUで数分かかり、結果は録画ごとに再利用します。",
        "options": [
            {"value": 0, "label": "見ない"},
            {"value": 1, "label": "見る (映像から笑顔を検出)"},
        ],
    },
    "clip_candidate_smile_weight": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_SMILE_WEIGHT",
        "default": 1.0,
        "type": float,
        "min": 0.0,
        "max": 3.0,
        "label": "切り出し候補: 笑顔の重視度",
        "note": "笑顔指標のz-scoreに掛ける倍率です。笑い声・Commentの笑いの重視度と同じ意味で、大きくすると候補の上位が笑顔由来で占められ、0.0にすると判定には効かなくなります(値は候補の根拠として表示されます)。",
    },
    "clip_candidate_smile_min_seconds": {
        "category": "clip",
        "env": "TICTOK_CLIP_CANDIDATE_SMILE_MIN_SECONDS",
        "default": 5.0,
        "type": float,
        "min": 0.0,
        "max": 60.0,
        "label": "切り出し候補: 笑顔の最小秒数",
        "note": "窓内で笑顔と判定できた秒数がこの値に満たない場合は候補にしません。下限を置かないと、笑顔のほとんど無い配信で1標本ぶんの検出が統計的に大きく見えて候補を占領します。標本の刻みは TICTOK_SMILE_SAMPLE_SECONDS です。",
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
    "backup_keep_days": {
        "category": "storage",
        "env": "TICTOK_BACKUP_KEEP_DAYS",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 365,
        "label": "差し替え前の元動画(_backup)を残す日数",
        "note": "再mp4化・音量正規化は元のmp4を_backupフォルダへ退避してから差し替えます。退避は失敗を巻き戻すためのもので、成功して中身を確認できた時点で役目を終えます。0なら、その録画の処理が完走し、出来たmp4が退避と同じだけのフレーム数を持つことを確認した直後に消します(退避フォルダは膨らみません)。1以上にすると、その日数のあいだ残します。フレーム数では見えない不具合(コメントのズレ・音の異常)に後から気付いて戻したい場合の猶予です。過去に積み上がったぶんは scripts/prune_backup_mp4.py で確認しながら消せます。",
    },
    "pack_sweep_per_start": {
        "category": "storage",
        "env": "TICTOK_PACK_SWEEP_PER_START",
        "default": 10,
        "type": int,
        "min": 0,
        "max": 500,
        "label": "ts結合: 1回のsweepで自動結合する録画の本数",
        "note": "録画1本は数千個の.tsで出来ています(実測で3.1時間の配信が5,628個)。これを解像度の切れ目ごとに1本へ束ね直すと、走査・backup・移送のfile数が二桁減ります(実測293,437個→数百個)。中身は再encodeせずbyteをそのまま連結するので、画質も尺も1 bitも変わりません。sweep(起動時と、下の「繰り返す間隔」ごと)1回につきこの本数だけqueueへ積みます。1本あたり30〜220秒かかりdiskを占有するため、大きくするとdiskが長時間塞がります。録画中の録画と、直近に書き込みのあった録画は対象外です。0でこの自動処理を行いません(画面の「ts結合」から手動で実行できます)。",
    },
    "pack_sweep_quiet_minutes": {
        "category": "storage",
        "env": "TICTOK_PACK_SWEEP_QUIET_MINUTES",
        "default": 15,
        "type": int,
        "min": 1,
        "max": 1440,
        "label": "起動時sweep: 直近に書き込みのあった録画を避ける時間（分）",
        "note": "捕捉中のffmpegはindex.m3u8を書き続けるため、その最中に束ねるとplaylistを差し替えた直後に上書きされ、消したsegmentを指すplaylistが残ります。録画中かどうかはDBの状態で判断しますが、DBに載る前の録画や捕捉processだけが生きている状態も避けるため、最後の書き込みからこの時間が経っていない録画は対象外にします。ts結合は素材そのものを書き換えるためfileの更新時刻で判定し、音声波形・サムネ・文字起こしは素材を読むだけなので録画の終了時刻で判定します(読むだけの処理が早すぎても、出来るのは作り直せるcacheであって壊れた素材ではありません)。",
    },
    "waveform_sweep_per_start": {
        "category": "storage",
        "env": "TICTOK_WAVEFORM_SWEEP_PER_START",
        "default": 10,
        "type": int,
        "min": 0,
        "max": 5000,
        "label": "音声波形: 1回のsweepで自動生成する録画の本数",
        "note": "seek barの下に敷く音声波形と、無音判定・盛り上がり判定に使う音量の時系列です。作られていない録画では再生画面で波形を開いた人が生成の完了を待つことになり、3.9時間の録画で90秒級かかります。sweep(起動時と、下の「繰り返す間隔」ごと)1回につきこの本数だけqueueへ積んで、待たずに出る状態へ寄せます。音声だけをdecodeする処理でGPUは使いませんが、録画fileを丸ごと読むためdiskを占有します。0でこの自動処理を行いません。",
    },
    "sprite_sweep_per_start": {
        "category": "storage",
        "env": "TICTOK_SPRITE_SWEEP_PER_START",
        "default": 10,
        "type": int,
        "min": 0,
        "max": 5000,
        "label": "サムネ: 1回のsweepで自動生成する録画の本数",
        "note": "seek barにカーソルを合わせたとき出る縮小画像の一覧(sprite)です。音声波形と同じく、無ければ最初に見た人が生成を待ちます。sweep(起動時と、下の「繰り返す間隔」ごと)1回につきこの本数だけqueueへ積みます。映像をdecodeするので音声波形より重く、diskも長く占有します。0でこの自動処理を行いません。",
    },
    "voice_sweep_per_start": {
        "category": "storage",
        "env": "TICTOK_VOICE_SWEEP_PER_START",
        "default": 10,
        "type": int,
        "min": 0,
        "max": 5000,
        "label": "無音skipの解析: 1回のsweepで自動生成する録画の本数",
        "note": "再生画面の「無音を飛ばす」と「無言を早送り」が使う、声の在る区間の解析です(音声のVAD)。無ければ最初に使った人がその場で待つのは音声波形と同じですが、こちらは40〜84分の録画で6〜13秒と軽く、GPUも使いません。sweep(起動時と、下の「繰り返す間隔」ごと)1回につきこの本数だけqueueへ積みます。閾値は問い合わせのたびに掛けるので、設定を変えても解析はやり直しになりません。0でこの自動処理を行いません。",
    },
    "transcribe_sweep_enabled": {
        "category": "storage",
        "env": "TICTOK_TRANSCRIBE_SWEEP_ENABLED",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "文字起こし: sweepで文字起こしのない録画をすべてqueueへ積む",
        "note": "本数で区切らないのは、文字起こしがGPUを1本ずつ直列に使い、queue(Job画面の種別「文字起こし」)が再起動をまたいで残るためです。全部積んでも同時に走るのは常に1本で、終わらなかったぶんは次のsweepや次の起動でそのまま続きます。文字起こし済みの録画と、既に待機・実行中の録画は積み直しません(積むのは文字起こしのないものだけです)。1本あたり数十分かかるので、貯まっている録画が多いと数日ぶんのGPU作業がqueueに並びます。0でこの自動処理を行いません。",
    },
    "sweep_interval_minutes": {
        "category": "storage",
        "env": "TICTOK_SWEEP_INTERVAL_MINUTES",
        "default": 30,
        "type": int,
        "min": 0,
        "max": 1440,
        "label": "自動生成のsweep: 起動後に繰り返す間隔（分）",
        "note": "上の自動生成(ts結合・音声波形・サムネ・無音skipの解析・文字起こし)をqueueへ積む処理を、起動時だけでなくこの間隔で繰り返します。serverを起動したまま何日も録画を続けると、次に再起動するまで新しい録画の波形も文字起こしも作られないためです。配信が終わってから積まれるまでの待ち時間は、この間隔と「直近に書き込みのあった録画を避ける時間」の合計が目安になります。2回目以降は前回のsweep以降に終わった録画だけを見ます(全録画の走査は録画ごとにfileの確認を伴うため)。ただし上限まで積んだ回の次は、積み残しを拾うために全件を見ます。0でこの繰り返しを行いません(起動時の1回だけになります)。",
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
        "label": "保持policy: 原本の自動削除",
        "note": "録画の原本は唯一の再取得不能なdataで、消すと再mp4化・再出力・文字起こし・切り出し・盛り上がり解析がまとめて復旧不能になります(文字起こし結果も録画と一緒に消えます)。原本とは、素材(.ts)が残っている録画ではその素材、素材が残っていない録画ではmp4本体です(mp4は素材から作り直せるため、素材がある録画では派生物として扱われます)。既定は無効です。有効にしても、実行前に必ず削除内容の一覧(dry-run)が表示され、確認するまで削除しません。",
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
    # 通知の宛先webhook URLはここに置かない。URL自体が投稿権限を持つ資格情報であり、この表の
    # 値は設定画面に平文で表示され、変更時にupdate()がold->newをops_eventsへ書き残す。宛先は
    # .env(TICTOK_NOTIFY_WEBHOOK_URL)側にあり、ここには資格情報でない項目だけを置く。
    "notify_enabled": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_ENABLED",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "通知を送る",
        "note": "配信開始・障害・盛り上がりをwebhook(Discord/Slack/汎用receiver)へ送ります。宛先はTicTok/.envのTICTOK_NOTIFY_WEBHOOK_URLで指定します(資格情報のため設定画面には置いていません)。宛先が未設定の場合、有効にしても送信は行われません。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "notify_rule_live_started": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_RULE_LIVE_STARTED",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "通知: 監視中の配信者のLIVE開始",
        "note": "待機中の監視対象が配信を開始し、Sessionが始まった時点で通知します。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "notify_rule_ops": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_RULE_OPS",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "通知: 障害・状態遷移(運用log連動)",
        "note": "運用logに記録される状態遷移(接続断・録画停止・再接続の打ち切り・録画不可判定・job中断など)を通知します。どこまで拾うかは下の「通知する最低severity」で決めます。この機構は運用logを唯一の口として使うので、通知のために別の判定を持ちません。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "notify_ops_min_severity": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_OPS_MIN_SEVERITY",
        "default": 1,
        "type": int,
        "min": 0,
        "max": 2,
        "label": "通知する最低severity",
        "note": "上の「障害・状態遷移」で通知する範囲です。infoまで含めると正常時のjob開始完了まで届くため、既定はwarning以上です。",
        "options": [
            {"value": 0, "label": "errorのみ"},
            {"value": 1, "label": "warning以上"},
            {"value": 2, "label": "info以上（多い）"},
        ],
    },
    "notify_rule_battle_started": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_RULE_BATTLE_STARTED",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "通知: Battle開始",
        "note": "Battleが始まった時点で通知します。1戦ごとに1回だけで、同じBattleの途中経過では通知しません。Battleの多い配信者を監視していると件数が多くなるため既定は無効です。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "notify_rule_coin_rate": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_RULE_COIN_RATE",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 1,
        "label": "通知: coin急増",
        "note": "直近1分のcoin(diamond)量が下の閾値を超えた瞬間に通知します。閾値を超えている間は鳴り続けず、下回ってから再度超えたときに次の通知を出します。",
        "options": [
            {"value": 0, "label": "しない"},
            {"value": 1, "label": "する"},
        ],
    },
    "notify_coin_rate_threshold": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_COIN_RATE_THRESHOLD",
        "default": 10000,
        "type": int,
        "min": 0,
        "max": 100000000,
        "label": "coin急増と判定する量（coin/分）",
        "note": "直近1分の合計coinがこの値以上になったら急増と判定します。配信者ごとに規模が桁で違うため、監視している配信者の平常時の値を見て決めてください(全体解析・履歴で確認できます)。0でこの判定を行いません。",
    },
    "notify_refractory_seconds": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_REFRACTORY_SECONDS",
        "default": 300,
        "type": int,
        "min": 0,
        "max": 86400,
        "label": "同一事象を再通知しない秒数（不応期）",
        "note": "同じ配信者の同じ事象について、この秒数のあいだは2件目以降を送りません。再接続を短時間に繰り返すような状況で通知が洪水になるのを防ぎます。0で抑止しません(非推奨)。",
    },
    "notify_retry_max": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_RETRY_MAX",
        "default": 3,
        "type": int,
        "min": 0,
        "max": 10,
        "label": "送信失敗時の再試行回数",
        "note": "webhookの送信に失敗したときに再試行する回数です(初回送信は回数に含みません)。待ち時間は倍々に広がります。宛先URLが誤っている等の再試行しても変わらない失敗は、回数を待たずに打ち切ります。回数を使い切った送信失敗は運用logにerrorとして必ず残ります。",
    },
    "notify_retry_base_delay": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_RETRY_BASE_DELAY",
        "default": 2.0,
        "type": float,
        "min": 0.5,
        "max": 60.0,
        "label": "再試行の初回待機秒数",
        "note": "exponential backoffの起点です（2→4→8…秒）。",
    },
    "notify_timeout_seconds": {
        "category": "notify",
        "env": "TICTOK_NOTIFY_TIMEOUT_SECONDS",
        "default": 10.0,
        "type": float,
        "min": 1.0,
        "max": 120.0,
        "label": "webhook送信のtimeout（秒）",
        "note": "1回の送信を待つ上限です。送信は収集・録画とは別に動くため、ここで待っても本体の処理は止まりません。変更はServer再起動後に有効です。",
    },
    "discovery_min_contacts": {
        "category": "discovery",
        "env": "TICTOK_DISCOVERY_MIN_CONTACTS",
        "default": 3,
        "type": int,
        "min": 1,
        "max": 100,
        "label": "候補に出す最小のBattle対戦数",
        "note": "過去のBattleでこの回数以上当たった未監視の配信者だけを候補にします。1にすると一度きりの対戦相手まで並び、候補が数百件になります。",
    },
    "discovery_half_life_days": {
        "category": "discovery",
        "env": "TICTOK_DISCOVERY_HALF_LIFE_DAYS",
        "default": 14.0,
        "type": float,
        "min": 1.0,
        "max": 365.0,
        "label": "接触の重みが半分になる日数（半減期）",
        "note": "候補の順位は「時間減衰つき対戦数」で決めます。この日数だけ前の対戦は1回を0.5回として数え、その倍の日数前なら0.25回になります。短くすると直近によく当たる相手が上位に、長くすると通算で多く当たった相手が上位に来ます。",
    },
    "discovery_limit": {
        "category": "discovery",
        "env": "TICTOK_DISCOVERY_LIMIT",
        "default": 30,
        "type": int,
        "min": 1,
        "max": 500,
        "label": "候補を表示する最大件数",
        "note": "上位から何件まで出すかです。条件を満たす候補の総数は一覧の見出しに表示されます。",
    },
    "fan_min_diamonds": {
        "category": "fans",
        "env": "TICTOK_FAN_MIN_DIAMONDS",
        "default": 0,
        "type": int,
        "min": 0,
        "max": 10000000,
        "label": "台帳に載せる最小のcoin額",
        "note": "通算でこの額以上を投じた視聴者だけを台帳に載せます。0でgiftを1回でも送った視聴者を全員載せます。台帳はgiftを送った視聴者だけが対象で、commentのみの視聴者は含みません(全視聴者は数万人規模になり一覧として使えないためです)。",
    },
    "fan_limit": {
        "category": "fans",
        "env": "TICTOK_FAN_LIMIT",
        "default": 100,
        "type": int,
        "min": 1,
        "max": 2000,
        "label": "台帳に表示する最大件数",
        "note": "上位から何件まで出すかです。条件を満たす視聴者の総数は一覧の見出しに表示されます。",
    },
    "capacity_sample_interval_hours": {
        "category": "capacity",
        "env": "TICTOK_CAPACITY_SAMPLE_INTERVAL_HOURS",
        "default": 24,
        "type": int,
        "min": 1,
        "max": 168,
        "label": "容量snapshotを記録する間隔（時間）",
        "note": "drive空き・DB size・録画量を記録する間隔です。filesystemの走査は行わず1回あたり0.05秒程度なので、収集の妨げにはなりません。短くすると予測が早く立ち上がりますが、記録が増えるだけで精度が上がるわけではありません（増加速度は日単位の現象のため）。",
    },
    "capacity_forecast_min_samples": {
        "category": "capacity",
        "env": "TICTOK_CAPACITY_FORECAST_MIN_SAMPLES",
        "default": 3,
        "type": int,
        "min": 3,
        "max": 100,
        "label": "満杯予測に必要な最小の記録数",
        "note": "これより記録が少ない間は「あと何日」を表示しません。2点では傾きのばらつきが評価できず、幅のない予測になってしまうため下限は3です。",
    },
    "capacity_forecast_max_extrapolation": {
        "category": "capacity",
        "env": "TICTOK_CAPACITY_FORECAST_MAX_EXTRAPOLATION",
        "default": 3.0,
        "type": float,
        "min": 1.0,
        "max": 20.0,
        "label": "観測期間の何倍先まで予測を出すか",
        "note": "観測が7日しかない状態で「あと1000日」と出すのは、算術としては正しくても観測が保証していない値です。予測がこの倍率を超えたら数値を伏せ、「少なくとも○日先までは持つ」とだけ表示します。大きくすると遠い先まで数値が出ますが、その数値の裏付けは観測期間ぶんしかありません。",
    },
    "capacity_alert_days": {
        "category": "capacity",
        "env": "TICTOK_CAPACITY_ALERT_DAYS",
        "default": 14,
        "type": int,
        "min": 0,
        "max": 365,
        "label": "満杯まで何日を切ったら通知するか",
        "note": "満杯までの見積り幅の下限（最も早く尽きる側）がこの日数を割ったら運用logへ記録し、通知設定に従って送信します。0で通知しません。点推定ではなく下限で判定するのは、幅の下限が既に閾値を割っている状況で黙らないためです。",
    },
}


class Settings:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._values: dict = {}
        self._invalid: dict = {}
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
            if self._is_choice(definition):
                return self._validate_choice(definition, raw)
            if definition["type"] is str:
                return self._check_path_shape(definition, raw)
            return self._validate_number(definition, raw)
        except ValueError as exc:
            logger.error(
                "環境変数の設定値が不正です: %s=%s（%s）",
                definition["env"], raw, exc,
                extra={"event": "process.settings_env_invalid",
                       "ctx": {"key": key, "env": definition["env"], "reason": str(exc)}},
            )
            raise

    @staticmethod
    def _coerce(definition: dict, value):
        """宣言された型へ変換するだけ。範囲・選択肢・pathのshapeは見ない。

        「制約に反しているが値はある」と「そもそも値として読めない」を分けるために要る。
        前者はoperatorが保存した値そのもので走らせられるが、後者は走らせる値が存在しない。"""
        if definition["type"] is str:
            return str(value).strip().strip('"')
        return definition["type"](value)

    def _stored_value(self, key: str, definition: dict, raw):
        """DBに保存済みの1件を、update()と同じgateへ通して解決する。戻り値は (値, 不正の理由)。

        DBへはupdate()経由でしか入らない建前だが、SETTING_DEFSのtype/min/max/optionsを後から
        変更すると、その時点で正しかった既存行が建前を破る。素のcastのままでは範囲外・選択肢外・
        相対pathが黙って実行値になり(update()なら422で拒否される値)、型として読めない値は
        keyを名指ししない ValueError で起動を殺していた。

        不正だった場合も**保存された値を既定値へ差し替えない**。差し替えは黙って別の値で走る
        ということで、画面には既定値が現在値として並び、operatorは自分の設定が捨てられたことを
        知る術がない(No fallback)。値はそのまま走らせ、logとops_eventsと画面へ「どのkeyのどの値が
        なぜ不正か」を出す。

        起動を止めるのは型として読めないときだけ。env側(``_env_default``)が不正で即座に止めるのは、
        .envの修正にserverが要らないからで、DB値の修正tool は設定画面そのものである。範囲が動いた
        だけで起動を拒むと、その値を直す唯一の画面ごと止まり、sqlite を直接叩く以外に復旧手段が
        無くなる。「設定画面が開けなくなる形で露見させない」という_load側の方針を、DB値では
        「設定画面が開ける形で露見させる」として引き継ぐ(不正なDB値はdescribe()を壊さないので、
        画面は開いたまま該当keyを直せる)。"""
        try:
            if self._is_choice(definition):
                return self._validate_choice(definition, raw), None
            if definition["type"] is str:
                return self._check_path_shape(definition, raw), None
            return self._validate_number(definition, raw), None
        except ValueError as exc:
            reason = str(exc)
        try:
            typed = self._coerce(definition, raw)
        except (TypeError, ValueError) as exc:
            logger.error(
                "保存済みの設定値が読めません: %s=%r（%s / %s）。設定画面で保存し直すか、"
                "settings表の該当行を削除すると組み込みの既定値(%r)に戻ります。",
                key, raw, definition["label"], exc, definition["default"],
                extra={"event": "process.settings_db_unreadable",
                       "ctx": {"key": key, "stored": str(raw), "reason": str(exc),
                               "builtin_default": definition["default"]}},
            )
            raise ValueError(
                f"保存済みの設定値が読めません: {key}={raw!r}（{definition['label']}）"
            ) from exc
        logger.error(
            "保存済みの設定値が現在の定義に適合しません: %s=%r（%s）。この値のまま実行しますが、"
            "設定画面から保存し直してください。",
            key, raw, reason,
            extra={"event": "process.settings_db_invalid",
                   "ctx": {"key": key, "stored": str(raw), "reason": reason,
                           "builtin_default": definition["default"]}},
        )
        return typed, reason

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
                value, reason = self._stored_value(key, definition, stored[key])
                self._values[key] = value
                if reason:
                    self._invalid[key] = reason
                sources["from_db"] += 1
            else:
                self._values[key] = env_default
                if os.environ.get(definition["env"]) is None:
                    sources["from_default"] += 1
                else:
                    sources["from_env"] += 1
        # settings表にはSETTING_DEFS以外の行も入る(store/maintenance.pyが移行済みmarkerを
        # ``_migration:<name>`` で置く)。定義に無いkeyは読まないだけで、残骸として報告はしない
        # — markerと「消えた設定の残り」をkey名から見分ける手段が無く、prefixの決め打ちは
        # 命名が変わった時に黙って壊れる。
        logger.info(
            "設定値を読み込みました（db=%d env=%d 既定=%d）",
            sources["from_db"], sources["from_env"], sources["from_default"],
            extra={"event": "process.settings_loaded",
                   "ctx": {"total": len(SETTING_DEFS), **sources,
                           "invalid": len(self._invalid)}},
        )
        if self._invalid:
            self._storage.record_ops_event(
                logger,
                "process.settings_db_invalid",
                "保存済みの設定値が現在の定義に適合しません（%d件）: %s" % (
                    len(self._invalid),
                    ", ".join(f"{key}={self._values[key]!r}" for key in self._invalid),
                ),
                severity=OPS_ERROR,
                detail={"invalid": {key: {"value": self._values[key], "reason": reason}
                                    for key, reason in self._invalid.items()}},
            )

    def get(self, key: str):
        return self._values[key]

    def all_values(self) -> dict:
        return dict(self._values)

    def invalid_values(self) -> dict:
        """起動時に現在の定義へ適合しなかった保存済み設定の {key: 理由}。

        値そのものは ``get`` / ``all_values`` が返すものが実行値(既定値へは差し替えない)。
        ここにkeyが載っている間、そのkeyは設定画面から保存し直すまで不正なまま走り続ける。"""
        return dict(self._invalid)

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
            if "option_image" in definition:
                entry["option_image"] = definition["option_image"]
            if key in self._invalid:
                # 保存済みの値が現在の定義に反しているkey。画面がその場で直せるよう、値を
                # 黙って差し替える代わりに理由を添えて出す。適合している間はfield自体を出さない
                # (「不正でない」を毎回名乗る必要は無い)。
                entry["invalid"] = self._invalid[key]
            described.append(entry)
        return described

    @staticmethod
    def _is_choice(definition: dict) -> bool:
        """optionsを持つstrは**列挙**であって path ではない。

        strをpath決め打ちで検証していたのは、当初strの設定がrecord_dirしか無かったため。
        列挙を足すたびに「絶対パスで指定してください」と拒否されるので、ここで型を分ける。
        """
        return definition["type"] is str and bool(definition.get("options"))

    def _validate_choice(self, definition: dict, value) -> str:
        """optionsに無い値は拒否する。近い値へ寄せない — 綴り違いを黙って別の設定として
        受けると、画面の表示と実際の挙動が食い違う。"""
        text = str(value).strip()
        allowed = [option["value"] for option in definition["options"]]
        if text not in allowed:
            raise ValueError(
                f"{definition['label']} は次のいずれかを指定してください: {', '.join(allowed)}"
            )
        return text

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
            if self._is_choice(definition):
                validated[key] = self._validate_choice(definition, value)
                continue
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
            # 保存できた=同じgateを通ったので、そのkeyの「定義に適合しない」印は解ける。
            for key in validated:
                self._invalid.pop(key, None)
            self._storage.record_ops_event(
                logger,
                "process.settings_updated",
                "設定を変更しました: " + (
                    ", ".join(f"{k}: {old} → {new}" for k, (old, new) in changes.items())
                    or "実質的な変更はありません"
                ),
                detail={"changes": changes, "changed": len(changes),
                        "submitted": len(validated)},
            )
        return self.all_values()
