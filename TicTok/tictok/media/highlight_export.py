"""照合済みhighlightから、gift付きのgift演出だけを高額順に繋いだ1本を書き出す。

TikTok本体のhighlight(LIVE replayの切り抜き)は**montage**で、実測では平均6秒(最短2.5秒)の
gift演出が10個ほど繋がっている。そのうちgift地点は一部でしかない(実測10個中7個)。突き合わせ
(:mod:`tictok.media.highlight_match`)がgift演出ごとにgiftとgifterを割り出した後、ここが
「見せたいgift演出だけを、見せたい順に並べた1本」にする。

**素材はhighlightのmp4であって録画ではない。** ギフト演出は視聴者のclientが描くもので、
こちらのHLS録画には映らない(``doc/HIGHLIGHT_MATCH.md``)。録画から同じ区間を切り出すと
演出の無い画になるので、切るのは必ずhighlight側である。録画側から来るのは「誰が投げたか」
と「いくらか」という**並べ替えの材料だけ**で、画は1 frameも使わない。

## gift演出の選び方

除くのは4種類。``excluded=1`` のgift演出(人が外した)、``dropped=1`` のgift演出(再照合で出なく
なった残骸で、人の入力を保つためだけに残っている行)、``gift_event_id`` を持たないgift演出
(gift地点ではない = 並べる基準を持たない)、``min_diamonds`` 未満のgift演出である。

``min_diamonds`` の既定は「画面に演出が出る」下限
(:func:`tictok.core.config.get_highlight_effect_coin_floor`、既定98💎)である。0ではない ――
実物のhighlightで99💎の階層(LIVE On Air / Singing Mushroom 等)にも演出が出ることを確認して
おり、そこが下限になる。**これ未満のgiftは小さなbannerしか出さないので、切り出しても
見せ場にならない。**

**照合側の同名の値とは別物である。** あちら(``highlight_match``)の ``min_diamonds`` は
「gift窓を張る候補の下限」で、highlightがどこから来たのかを**探す範囲**を決める。こちらは
「出来上がりの1本へ載せる下限」で、**成果物の中身**を決める。既定値が同じなのは、どちらも
「演出が出るか」という同じ事実を根拠にしているからであって、片方を動かしてももう一方は
動かない。

**同じgiftが複数のhighlightに入る。** TikTokは同じ瞬間を別のhighlightにも入れることが
あり、そのまま繋ぐと同じ演出が2回流れる。突き合わせから見ればどちらも「正しいgift演出」なので
一致の質では落とせない ―― 落とす基準は素材ではなく**giftの側**にしか無い。1つのgiftは
1回しか投げられていない以上、``gift_event_id`` が同じ行は**同じ1回**を指す。よってここで
重複排除する。

残す1本の決め方は、**そのgift演出が誰の見せ場か**を先に見る:

0. **人が選んだ1本(``chosen``)**。以下はすべて「そのgiftのアニメが映っているのはどれか」を
   機械が当てる代用なので、人が実物を観て選んだ答えがあるならそちらが勝つ。画面(検証tab)の
   候補の切り替えがこの印を立てる。
1. ``confidence`` が高い方。そのgift演出がその瞬間だと言い切れる度合い。
2. **自分の見せ場を持つ方**(``show_start``/``show_end``)。そのgiftの演出が映っている区間
   そのもので、下の ``is_primary`` はその弱い代用である。代用より本物が先に来る。
3. **``is_primary`` が立っている方**。同じ瞬間に複数人のgiftが飛ぶと、TikTokは**gift 1件に
   つき1つのgift演出**を作るが、こちらの帰属はどのgift演出にも「その窓に入った全員」を載せる ――
   その中で、実際にそのgift演出に映っているアニメは主の1件だけである。
4. ``inside`` が立っている方。主がどこにも立たないとき(誰かの巻き添えでしか出ていないgift)
   の弱い版で、そのgiftの瞬間がgift演出の窓の中に在るか。
5. 尺の長い方。演出の頭から尻までが入っている見込みが高い。
6. ``(highlight_id, idx)`` の若い方 ―― 結果を毎回同じにするためだけの規則である。

**3番目が無かったために、別人の演出がその人のfileへ入った。** 実測: おニャンコ🐢💤の
Travel with You 999💎(media 7317.1s)は、あきと🐢💤の Strong Finish 6000💎(7313.7s)と
るきしろ🐢💤の Singing Mushroom 99💎(7312.8s)の直後に飛んでいる。TikTokはこの4.2秒から
gift演出を2つ作った —— Strong Finish のgift演出(F1のマシンが走る演出)と、Travel with You のgift演出
(黄色い車が椰子の木の道を走る演出)である。帰属はどちらのgift演出にも3件とも載る(窓が重なる)が、
``is_primary`` は正しく別々に立っていた。にもかかわらず尺で選んでいたため、7.46秒の
Strong Finish のgift演出が6.17秒の Travel with You のgift演出に勝ち、**おニャンコのfileにF1の演出が
入った**。PKの終盤のようにgiftが集中する場面では、これは例外ではなく普通に起きる。

## 出力はgifterごとに1本

**1本にまとめない。** 出来るのは「この人がこの週に投げたgiftの場面だけを、高額順に繋いだ
1本」で、対象のgifterの数だけfileが出来る。

対象は**その週の合計が1,000💎以上のgifter**だけである。週の境界(土曜7時〜次の土曜7時)も
閾値も名寄せも :meth:`tictok.store.streamers.StreamersMixin.streamer_mention_week` に
実装済みで、**ここで書き直さない** —— 配信者画面のメンション一覧と「誰が対象か」が
食い違うのが、この機能で最悪の結末である。閾値の数字も応答の ``post_min`` を使う。

**束ねる鍵は ``identity_key``、file名に出すのは表示名。** 同じ人が期間の途中で表示名を
変えれば表示名で束ねた1人は2本に割れ、別人が同じ表示名を名乗れば別人が1本に混ざる。

``order`` が決めるのは**1本の中の並び**だけである。

- ``diamonds`` 高額順(既定)。同額は ``(highlight_id, idx)`` で決める
- ``time``     配信上の時系列。軸は**録画側の秒**(``recording_id``, ``media_start``)で、
  highlightの並び順ではない ―― highlightは配信の順に出るとは限らず、1本の中のgift演出の順も
  配信の順とは限らない

**並びは窓の畳み方まで決める**(:func:`build_cuts`)。同じhighlightの中で隣り合うgift演出を1つの
窓へ畳むと、その中は必ず時系列で流れる ―― 高額順を指定していても、畳まれた塊の中だけは
時系列に戻る。実測でそれが起きた: よい🐢💤 ｻｲｺｳｯ! の1本は 99💎 → 4999💎(Guardian's Pledge)
→ 99💎 の3件のgift演出が接していたため0.0〜17.79秒の1つの窓へ畳まれ、**99💎から始まる1本**が
出来上がった。よって高額順では**gift演出を跨いで畳まない**。畳むのは同じgift演出に乗った連投だけで、
余白で重なった分は高額な側を丸ごと残して安い側を削る(同じ映像は二度入らない)。時系列順では
従来どおり接した窓も畳む ―― あちらは畳んだ方が繋ぎ目が減り、しかも並びは変わらない。

## 置き場とfile名

置き場は ``<work root>/<配信者>/LiveHightlite_マージ済み/``
(:func:`tictok.core.layout.merged_highlight_dir`)。素材(``LiveHightlite``)の隣に並ぶが
dirは分ける —— 名前の規約が別物なので、混ぜるとどちらを探していても辿り着けない。

file名は ``yymmdd-yymmdd_coin<週合計>_<gifterの表示名>_story.mp4``。**2つの尺度が同居する**
(:func:`export_filename` に詳しく書いた): コイン数は**週の合計**、日付範囲は**その1本に
実際に入っているgift演出の幅**である。置き場が ``unique_id``、file名が表示名で、冗長ではなく
補い合う —— 1本だけ別の場所へ運ばれても、名前だけで誰のものか判る。

## 切り出しは再encodeする(copyでは繋げない)

**実測: highlightのGOPは1.0秒**(7本すべて、keyframeがちょうど1秒ごと)。一方これが繋ぐgift演出は
2.5〜10秒級である。stream copyはkeyframeからしか始められないので、要求した始点より最大1秒
手前 ―― 2.5秒のgift演出なら**尺の40%ぶん**手前から始まる。

短いだけなら許せるが、**手前に写っているのは同じ場面の続きではない**。highlightはmontageで、
gift演出の境目は無関係な場面同士のハードカットである。copy経路で1秒手前へ伸ばすと、前のgift演出の
尻(=別の場面)が毎回頭に付く。「高額順に並べた」出力の各項の頭に、その項とは関係のない映像が
1秒ずつ入ることになる。

そこで既定は :data:`DEFAULT_PRECISE` = True、つまり**frame精度の再encode**である。

実物7本から7件のgift演出(2.5〜5.5秒、要求合計26.33秒)を繋いだ実測:

=====================  ==================  ==================
指標                   copy                再encode(既定)
=====================  ==================  ==================
出力の尺               28.66秒(+2.33)      26.51秒(+0.18)
要求外の前置き         0.000〜0.667秒/gift演出  0秒(定義どおり)
                       合計1.70秒
所要                   2.4秒               7.7秒
容量                   6.6MB               22.5MB
=====================  ==================  ==================

**捨てたのは容量と5秒で、買ったのはgift演出の頭である。** copyの最悪だったgift演出は3.50秒の
要求に対し0.667秒(19%)が前のgift演出の映像で、しかもその中身はTikTok自身の場面転換
(画面が畳まれて次の場面へ切り替わる途中)だった。再encode版は7件のgift演出すべてが要求時刻の
frameから始まることを、素材側の同時刻frameと突き合わせて確認してある。

再encodeの実費が小さいのは素材が720x1280・数秒だからで、この経路が扱うのは常にその大きさ
である(録画3時間から切る clipper とは前提が違う)。

**原本を直接 ``-ss`` する形をここでは使える。** :mod:`tictok.media.clipper` が粗い中間を挟む
のは、3時間級のHLS録画に対して出力側 ``-ss`` が開始位置に比例して遅くなり、入力側 ``-ss`` は
HLSが前方のsegmentへ飛ぶためである。highlightは**mp4で最長61秒**なので、どちらの理由も当て
はまらない ―― 出力側 ``-ss``(復号して捨てる)の実費は最悪でも61秒ぶんの復号で、frame精度は
定義どおり出る。

## 混在した素材

highlight同士は同じ解像度・fpsのはずだが、そうでない日が来ても黙って壊れてはいけない。
連結の可否は :func:`tictok.media.concat.mismatch_reasons` で毎回照合する。食い違ったときは
**失敗させずに正規化して繋ぐ** ―― copy経路(:mod:`tictok.media.reel`)は原本画質が目的なので
失敗させるのが正しいが、こちらは元々全gift演出を再encodeするので、揃える先を1つ決めれば済む。
揃える先は :func:`_encode_target` が決める1組で、frameはaspectを保ったままscaleしてpadする。
潰れた画を黙って出さないための ``setsar=1`` まで含めて1つのfilterにする。**解像度だけを
揃えても足りない** ―― mp4は先頭fileのcodec設定を1つだけ書くので、audioのrate/channelや
profileがgift演出ごとに違うと、繋いだ後は先頭以外が誤った設定で復号される(実測で「48kHz mono
として鳴る」出力が rc=0 で出来た)。焼き上がったpartは繋ぐ前に
:func:`tictok.media.concat.check_compatible` でもう一度照合する。

## 出来上がりは実測で検証する

rc=0 のまま**片側のstreamだけが途中で終わる**事故が過去にある。containerの ``duration`` は
長い方のstreamの尺なので、その事故を隠す。よって :func:`tictok.media.concat.stream_spans` で
video/audio両方のpacket時刻を測り、どちらも期待尺に届いていることを確かめる
(:func:`_verify_output`)。届いていなければ出力を消して失敗させる。

上の7件のgift演出での実測は video 789 frame(要求26.33秒 x 30fps = 789.9)・audio 1,144 packetで、
音声の穴は0秒、接合ごとに映像へ入る間隔は24〜57msだった(A/Vの終端差は18ms)。

## 素性の判らないmp4を作らせない

**実際に起きた事故がこの節の理由である。** ``highlight_videos`` が1行も無い状態で、手で
組んだgift演出の定義から7本のmp4が書き出された。素材の範囲はあるhighlightから、gifterの名前は
**別のhighlight**の真値から採られており、``あきと`` の名前を持つfileの中身は
``よい`` が投げた Guardian's Pledge だった。**別人のfileに別人のgiftが入っていた。**

file名は「誰の・いつの・いくらぶんか」を名乗るが、**中身がそのとおりである保証は名前の側に
何も無い。** 出来上がったmp4を見ても、どのhighlightの何秒からどのgiftとして切られたのかは
判らない。合っているかどうかを後から辿れないことが、この事故で最も悪かった点である。
そこで次の3つを不変条件にした。

1. **書き出しはDBに保存された実照合結果からしか行えない。** 素材(``highlight_videos``)の
   ``status`` が ``matched`` でない行は :func:`_fetch_segments` が弾く。その上で、切る直前に
   gift演出1件ずつをDBへ引き直して照合する(:func:`verify_item`)—— gift演出の行が実在すること、
   切る素材が**そのgift演出が属するhighlightのfileそのもの**であること、``gift_event_id`` が
   ``events`` の実在するgiftを指し、💎・gift名・``identity_key`` がgift演出の列と一致すること、
   そしてそのgiftのgifterが**このfileの持ち主と同じ人**であること。今回の事故は最後の2つの
   どちらでも落ちる。``recording_id`` や ``gift_event_id`` を持たない行も同様に失敗させる ――
   **黙って書き出さない。**
2. **出来た1本ごとに素性を隣へ残す。** ``<file名>.json`` に、gift演出1つずつの
   「どのhighlight(id・file名)の何秒から / どのgift event(id・名前・💎)として / どの録画の
   何秒に当たるか」を書く(:func:`provenance_record`)。人がfileを開かずに真偽を辿れる唯一の
   手掛かりで、mp4を消せば一緒に消える(``tictok.api.routes.clips``)。
3. **検証用の道は製品の口から通らない。** :func:`export_highlights` の
   ``verification_rows`` だけが手で組んだgift演出を受け取る。HTTPからは届かない
   (``HighlightExportRequest`` は未知のfieldを弾き、jobは ``EXPORT_OPTION_KEYS`` しか渡さない)。
   この経路の出力はfile名に :data:`UNVERIFIED_MARK` が入り、素性のJSONは ``verified: false``
   を名乗る。逆向きにも縛る —— 検証済みでない素性で印の無い名前へ書こうとしたら、
   :func:`render_segments` が書き出しそのものを失敗させる。
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import shutil
import tempfile
import time

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from tictok.core import config, layout
from tictok.media import concat, hls_source
from tictok.record import media_queue
from tictok.media.clipper import _profile_arg, _smart_encoder
# 週の境界は :mod:`tictok.store.streamers` の1箇所だけを使う。**再実装しない** —— 配信者画面の
# メンション一覧と「どの週か」が食い違うのが、この機能で最悪の結末である。privateな名前だが、
# 同じ規則を2つ持つよりは1つを共有する方が壊れない。
from tictok.store.streamers import WEEK_SATURDAY, _period_bounds
# 照合が終わった行の綴り。台帳が使っている値をそのまま読む —— ここへ文字列を書き写すと、
# 台帳側で綴りが変わった日に「照合済みのはずのhighlightから書き出せない」が起きる。
from tictok.store.highlights import (HIGHLIGHT_STATUS_MATCHED, gift_cut,
                                     gift_unit_diamonds)
from tictok.record.video_overlay import (
    _duration_seconds,
    _encoder_args,
    _mapped_quality,
    ffmpeg_available,
)

logger = logging.getLogger(__name__)

# **1本の中の**並びの選択肢。fileを分ける軸(gifter)はここには無い —— 出力は必ずgifterごとに
# 1本なので、選べる余地が無い(:func:`plan_exports`)。以前あった ``gifter`` は「1本の中で
# gifter単位に束ねる」並びで、出力が1本だった頃のものである。
ORDER_DIAMONDS = "diamonds"
ORDER_TIME = "time"
ORDER_CHOICES = (ORDER_DIAMONDS, ORDER_TIME)
DEFAULT_ORDER = ORDER_DIAMONDS

# frame精度で切るか。既定でTrueにする理由はmodule docstring(GOP 1.0秒 対 gift演出2.5秒)。
DEFAULT_PRECISE = True

# gift演出の前後へ足せる余白(秒)。既定は0 —— gift演出の範囲は照合が決めた「その演出の区間」なので、
# 何も言われていないのに広げる理由が無い。
DEFAULT_PAD_LEAD = 0.0
DEFAULT_PAD_TAIL = 0.0

# gift演出の前後へ足せる余白の上限(秒)。gift演出自体が2.5秒級なので、これ以上足すと隣のgift演出
# (=無関係な場面)へ食い込む。上限を持たないと、画面から大きな値が来たときに黙って食い込む。
MAX_PAD_SECONDS = 3.0

# 高額順で窓の重なりを削った後、これ以下しか残らない窓は切らない(秒)。余白の指定で窓が
# 重なると、安い側には端切れしか残らないことがある —— 0.2秒のgift演出は場面として読めず、
# 繋ぎ目が1つ増えるだけである。giftの記録はその端切れを吸った窓の側に残る
# (:func:`_priority_cuts`)ので、件数も💎も落ちない。
MIN_CUT_SECONDS = 0.25

# 照合の確からしさ(``highlight_segments.confidence``)の強さ。DBの値は "high"/"low"/"none"の
# **文字列**なので、重複を畳むときの順序をここで与える。表に無い綴りは最下位に置く ――
# 使うのは順序だけで、値そのものを計算に入れる訳ではない。
CONFIDENCE_RANK = {"high": 2, "low": 1, "none": 0}

# file名の固定部分。``yymmdd-yymmdd_coin<週合計>_<表示名>_story.mp4``。読み手は
# :func:`tictok.media.clipper.parse_clip_name` で、**対で守る**(往復のtestが在る)。
COIN_PREFIX = "coin"
STORY_SUFFIX = "_story"
STORY_EXT = ".mp4"

# 検証用の経路(:func:`export_highlights` の ``verification_rows``)を通った出力の印。
# ``..._story.検証用.mp4`` になる。
#
# **印は名前に置く。** 素性のJSONにも ``verified: false`` を書くが、JSONは隣に在るだけの
# 別fileで、mp4を1本だけ別の場所へ運べば付いて行かない。file名なら中身と一緒に動く。
#
# 印の付いた名前は ``parse_clip_name`` が読めない(``_story`` で終わらない)ので、切り出し
# 一覧には**素性なし**として並ぶ。これは意図した結果である —— 検証用の出力は成果物では
# ないので、成果物の顔をして並ぶ方が悪い。
UNVERIFIED_MARK = ".検証用"

# 出力の素性を書き残すfileの拡張子と、その書式の版。``<file名>.mp4.json`` になる。
# 版を持つのは、後から読む側が「この形で読める」と判断する手掛かりが要るためである。
PROVENANCE_EXT = ".json"
PROVENANCE_SCHEMA = 1

# file名に置けない文字。Windowsの予約文字と制御文字(DELを含む)で、clipperのlabelと同じ集合。
# **絵文字は入れない** —— NTFSはそのまま置けるし、落とすと表示名が別人に見える。
_UNSAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]+')

# 切り詰めた末尾に**残ると壊れる**符号だけを持つ。ZWJ(U+200D)は次の文字と繋ぐためのもので、
# 末尾に来ると繋ぐ先が無い。地域表示記号(U+1F1E6〜U+1F1FF)は2つで1つの旗なので、奇数個で
# 終わると片割れになる。
#
# **異体字選択子・肌色・結合文字はここに入れない。** どれも直前の文字を修飾するもので、
# 末尾に在っても列としては完結している。落とすと ``👍🏽`` が ``👍`` になるなど、
# 切り詰めていない名前まで書き換えることになる。
_ZWJ = "‍"
_REGIONAL = frozenset(chr(c) for c in range(0x1F1E6, 0x1F200))

# 表示名に使ってよい文字数と、切り詰めた印。印を付けるのは、黙って短くすると別人の名前へ
# 化けても気付けないためである。
NICKNAME_MAX_CHARS = 48
TRUNCATION_MARK = "…"

# Windowsの既定APIが扱えるpath長。長いpathを有効にしていない環境が前提なので、ここへ
# 収まらない名前は作らない(:func:`_fit_path`)。
MAX_PATH_CHARS = 259


class NoSegments(RuntimeError):
    """条件に合うgift演出が1つも残らなかった。"""


class NoDisplayName(RuntimeError):
    """表示名がfile名に使える文字を持たない。**``unique_id`` で埋めない。**"""


class NotMatched(RuntimeError):
    """照合が終わっていないhighlightから書き出そうとした。"""


class NotVerified(RuntimeError):
    """切ろうとしているgift演出が、DBに保存された実照合結果と一致しない。

    「一致しない」には、DBに行が無い・素材が別のhighlightのfile・giftのgifterがこのfileの
    持ち主と別人、のいずれもが含まれる。**どれも黙って書き出してはいけない。**"""


def defaults() -> dict:
    """``export_highlights`` を引数無しで呼んだときに**実際に効く**値。

    Serverが出力側の既定値を名乗る口はここ1つにする。route側や画面が数字を書き写すと、
    設定画面で変えた値と画面が表示する既定が別々に動く。

    ``min_diamonds`` だけは設定値なので**呼ぶたびに引き直す** —— module levelのdictにすると、
    設定を変えてもserverを再起動するまで古い値を名乗る
    (``highlight_match.defaults`` と同じ形)。

    ``week`` は入れない。未指定のときの週は「その配信者に記録のある最新の週」で、配信者ごとに
    違う値になる ―― 決めているのは ``streamer_mention_week`` なので、そちらの応答
    (``week`` / ``weeks[]``)が名乗る。

    週合計の下限(``post_min``)も入れない。あれは書き出しの引数ではなく
    ``streamer_mention_week`` が持つ値で、応答の ``post_min`` が名乗る。ここへ書き写すと
    同じ数字が2箇所に出る。"""
    return {"order": DEFAULT_ORDER, "precise": DEFAULT_PRECISE,
            "pad_lead": DEFAULT_PAD_LEAD, "pad_tail": DEFAULT_PAD_TAIL,
            "min_diamonds": config.get_highlight_effect_coin_floor(),
            "order_choices": list(ORDER_CHOICES),
            "max_pad_seconds": MAX_PAD_SECONDS}


def _diamonds(row) -> int:
    """そのgiftの💎。並べ替えの基準そのものなので、読めない値は0にしない。"""
    value = row.get("diamonds")
    if value is None:
        raise RuntimeError(
            f"giftに💎がありません（highlight {row.get('highlight_id')} / "
            f"gift演出 {row.get('segment_id')} / gift {row.get('gift_event_id')}）。"
            "並べ替えの基準が無いため書き出せません。")
    return int(value)


def _unit_diamonds(row) -> int:
    """そのgift **1個あたり**の💎。下限の判定はこの値だけで行う。

    ``diamonds`` はまとめ投げの合計で、30💎を9個投げた1 eventは270💎になる。合計で下限を
    判定すると、演出の出ない小さなgiftが「98💎以上の高額gift」として1本に載る
    (:func:`tictok.store.highlights.gift_unit_diamonds`)。並べ替えと合計額は
    ``diamonds`` のまま —— その人が実際に払った額はそちらである。"""
    return gift_unit_diamonds(_diamonds(row), row.get("gift_count"))


def _tie_break(row) -> tuple:
    """並びを**必ず一意へ落とす**ための最後の鍵。意味は無い。

    ``(highlight_id, gift演出のidx, gift演出の中のgiftのidx)``。gift演出1つが複数のgiftを持つように
    なったので、gift演出までの2つでは同点が残る —— 同じgift演出の中の連投(実測でHearts 199💎×6)は
    💎もgift演出も同じで、ここが無いと並びが実行のたびに入れ替わる。"""
    return (int(row.get("highlight_id") or 0), int(row.get("segment_idx") or 0),
            int(row.get("gift_idx") or 0))


def _order_key_diamonds(row) -> tuple:
    """高額順の並び。同額は :func:`_tie_break` で決めて、結果を毎回同じにする。"""
    return (-_diamonds(row), *_tie_break(row))


def _order_key_time(row) -> tuple:
    """配信上の時系列。軸は**録画側**(``recording_id``, ``media_start``)。

    highlightの並びで代用してはいけない。highlightが配信の順に出る保証は無く、1本の中の
    gift演出が配信の順に並ぶ保証も無い。軸を持たない行は時系列に置けないので、推測せず失敗
    させる ―― gift付きのgift演出は必ず録画へ突き合わせて出来ているので、実際には起きない。

    同じgift演出の中のgiftは ``gift_media_time`` で分ける。連投は投げられた順に並ぶ ――
    **起きたとおりに映るのがこの並びの意味**である。"""
    recording_id, media_start = row.get("recording_id"), row.get("media_start")
    if recording_id is None or media_start is None:
        raise RuntimeError(
            f"gift演出が録画に紐づいていないため時系列に並べられません"
            f"（highlight {row.get('highlight_id')} / gift演出 {row.get('segment_id')}）。")
    gift_at = row.get("gift_media_time")
    return (int(recording_id), float(media_start),
            float(gift_at) if gift_at is not None else 0.0, *_tie_break(row))


def dedup_by_gift(rows: list) -> tuple:
    """**同じgiftを指す行**を1つへ畳む。``(残した並び, 落とした件数)``。

    畳む理由と、残す1本の決め方はmodule docstringにある。**そのgift演出の主(``is_primary``)か
    どうかが尺より先**なのがここの要点で、同じ瞬間に複数人のgiftが飛んだとき、尺で選ぶと
    別人のアニメが映っているgift演出を掴む。``gift_event_id`` を持たない行はここへ来ない
    (呼び出し側が先に落とす)。

    **人が選んだ1本(``chosen``)はそのどれよりも先である。** 以下の順位はすべて「そのgiftの
    アニメが映っているのはどれか」を機械が当てる代用で、代用が外れる形は実測で出ている
    (Whale diving 2,150💎 は3本すべてで同席と判定され、本人のアニメが映っている11.1秒の
    1本は代表にならなかった)。人が実物を観て選んだのなら、代用を先に立てる理由は無い。

    **畳む対象は「同じgiftが複数のhighlightに入っていた」場合だけである。** 1つのhighlightの
    中では、同じ ``gift_event_id`` が2つのgift演出に現れることはない(照合側の ``_assign_gifts``
    が保証し、DBも ``UNIQUE(segment_id, gift_event_id)`` で押さえている)。連投は
    ``gift_event_id`` が別なので**ここでは1件も落ちない** —— 落とすのは記録を捨てることで、
    それは利用者の指示(連投はそのまま並べる)に反する。同じ場面が二度映らないようにするのは
    切り出しの窓の側(:func:`build_cuts`)の仕事である。"""
    best: dict = {}
    dropped = 0
    for row in rows:
        key = row["gift_event_id"]
        rank = (1 if row.get("chosen") else 0,
                CONFIDENCE_RANK.get(str(row.get("confidence") or ""), -1),
                # 自分の見せ場を持つ行が先。**主かどうかより強い** —— 見せ場を持つ行は
                # 「そのgiftの演出が映っている区間」そのもので、主は「そのgift演出で一番よく
                # 映っている人」という弱い代用である。割れた側が在るなら代用は要らない。
                1 if has_show(row) else 0,
                1 if row.get("is_primary") else 0,
                1 if row.get("inside") else 0,
                float(row["end"]) - float(row["start"]),
                *(-value for value in _tie_break(row)))
        current = best.get(key)
        if current is None:
            best[key] = (rank, row)
            continue
        dropped += 1
        if rank > current[0]:
            best[key] = (rank, row)
    return [row for _, row in best.values()], dropped


def has_show(row) -> bool:
    """その行が**自分の見せ場**を持っているか(照合がそのgift演出を割れた行)。

    見せ場を持つ行は、そのgift演出に他人が同席していても**他人の演出が1 frameも入らない**
    窓を持っている。主かどうかで落とす理由がそこには無い。"""
    try:
        return row["show_start"] is not None and row["show_end"] is not None
    except (KeyError, IndexError, TypeError):
        return False


def segment_owners(rows: list) -> dict:
    """``{segment_id: そのgift演出の主のidentity_key}``。主の居ないgift演出は入らない。

    **割れなかったgift演出は1つ = 見せ場1つ**である。montageのgift演出は平均6秒で、TikTokはそこに**1つのgiftの
    場面**を載せる。ところが窓が6秒もあると、その間に別の人のgiftが何件も飛ぶ ―― 実測で
    rukishirのSinging Mushroom 99💎、murakabaneriのStrong Finish 6000💎、onyanko102の
    Travel with You 999💎の3件が同じ6.0秒のgift演出に載っていた。画面に映っているのは
    6000💎の演出**1つだけ**である。

    主は照合側(:func:`tictok.media.highlight_match._mark_primary`)がgift演出ごとに1件だけ
    立てている。ここはそれを引くだけで、選び方をここへ書き写さない。

    **見せ場を割れたgift演出はここへ入れない。** 割れたgift演出では行ごとに自分の見せ場の窓が
    在り、他人の演出は窓の外である —— 主を立てて他の行を落とすと、**画面に映っている見せ場を
    持つ人が出力から消える**。落とす理由(他人の演出が入る)が消えたのだから、落とさない。"""
    owners: dict = {}
    split: set = set()
    for row in rows:
        if has_show(row):
            split.add(row.get("segment_id"))
    for row in rows:
        if not row.get("is_primary") or row.get("segment_id") in split:
            continue
        segment_id = row.get("segment_id")
        if segment_id is None:
            continue
        owners[segment_id] = row.get("identity_key")
    return owners


def owns_segment(row, owners: dict) -> bool:
    """その行のgifterが、そのgift演出の見せ場の主か。

    **偽の行を1本のfileへ入れてはいけない。** 出力は「この人が投げた分」として本人へ届く
    物なので、他人の演出が映っている6秒がそこに並ぶと、file全体が誰のものでもなくなる ――
    実測でrukishirの1本は、正しいHearts 199💎×6の窓の後ろに、murakabaneriの
    Strong Finish 6000💎の場面が2つ続いていた(本人のgiftはその6秒に同席していただけである)。

    **人が手で付け替えた行(``manual``)は主でなくても通す。** そこは人が「このgift演出はこの
    giftだ」と決めた行で、機械の主の判定より後に置かれた判断である。

    主が居ないgift演出(照合が主を立てられなかった場合)は落とさない ―― 判断の根拠が無いのに
    落とすと、理由の言えない欠落になる。**自分の見せ場を持つ行も落とさない** ――
    :func:`segment_owners` がそのgift演出を主無しにしてあるので、ここは何もしなくてよい。"""
    if row.get("manual"):
        return True
    segment_id = row.get("segment_id")
    if segment_id not in owners:
        return True
    owner = owners[segment_id]
    if owner is None:
        return True
    return row.get("identity_key") == owner


def _order_rows(rows: list, order: str) -> list:
    """1本の中の並び。**fileを分ける軸ではない**(それは gifter で、呼び出し側が先に分ける)。"""
    if order == ORDER_TIME:
        return sorted(rows, key=_order_key_time)
    return sorted(rows, key=_order_key_diamonds)


def select_segments(rows: list, *, min_diamonds: Optional[int] = None) -> dict:
    """**giftの行**から、出力に載せてよいものだけを残す。``(残り, 内訳)``をdictで返す。

    **数える単位はgiftである。** 1つのgift演出は複数のgiftを持ち(実測で最長8.3秒のgift演出に
    Hearts 199💎が6件)、行はgift 1件につき1つある(:func:`_fetch_segments`)。gift演出単位で
    数えると、連投した人のfileの件数が実際の見せ場の数と合わない。

    ここが落とすのは**gift 1件の資格**だけである。「その人ぶんのfileを作る価値があるか」は
    別の軸(週合計)で、:func:`plan_exports` が gifter の一覧を相手に判断する。

    ``excluded`` / ``dropped`` は**gift演出側とgift側の両方**を見る(行が既に両方を畳んである)。
    片方だけを見ると、gift 1件を外したつもりでgift演出ごと落ちる/gift演出を外したのにその中の
    giftが残る、のどちらかが起きる。

    ``min_diamonds`` は**gift 1個あたりの単価**の下限で、既定は設定の演出gift下限
    (:func:`tictok.core.config.get_highlight_effect_coin_floor`、98💎)。``None`` なら設定から
    引く ―― 引数の既定値に書くと、設定画面で変えた値がここを素通りする。0を渡せば全gift。
    ``None``(未指定)と0は違う意味なので埋めない。

    **合計ではなく単価で切る**(:func:`_unit_diamonds`)。30💎のgiftを9個まとめて投げた
    1 eventは合計270💎だが、画面に出るのは小さなbannerが9回で、切り抜きに載せる場面では
    ない。合計で判定していた頃は、この種のgiftが「270💎の見せ場」としてfileへ入っていた。

    **演出が映っているかでは落とさない。** かつて照合側が持っていた ``has_effect``(その
    giftが演出区間と重なるか)は**契約から外れた** —— 実物7本のgift 47件で真が立ったのは
    2件だけで、しかも**どちらもTikTok自身のワイプ**、gift演出に付いた真は1件も無かった。
    差分は全画素の平均を採るので、画面の15%しか覆わない花火(Fireworks 1088💎)は演出無しと
    同じ値になる。**当たりが0件の信号は判定に使えない。** 演出が映っているかを見る手段は
    代表frameの2枚並べ(highlight側と録画側)で、そこは人の目の方が確実に強い
    (``doc/HIGHLIGHT_MATCH.md``)。"""
    if min_diamonds is None:
        min_diamonds = config.get_highlight_effect_coin_floor()
    total = len(rows)
    # ``dropped`` は再照合で出なくなった行。人の入力(memo等)を失わないために行だけが
    # 残っているもので、いまのhighlightにその場面は無い。
    kept = [row for row in rows
            if not row.get("excluded") and not row.get("dropped")]
    excluded = total - len(kept)
    with_gift = [row for row in kept if row.get("gift_event_id") is not None]
    no_gift = len(kept) - len(with_gift)
    rich = [row for row in with_gift if _unit_diamonds(row) >= int(min_diamonds)]
    below = len(with_gift) - len(rich)
    # **そのgift演出の見せ場の主でない行を落とす**(:func:`owns_segment`)。主は照合側がgift演出ごとに
    # 1件だけ立てており、母集団は落とす前の ``rows`` 全部から採る —— 人が外した行(excluded)が
    # 主だったgift演出で、残った同席のgiftへ主の座が移らないようにするためである。
    owners = segment_owners(rows)
    mine = [row for row in rich if owns_segment(row, owners)]
    other_owner = len(rich) - len(mine)
    unique, duplicated = dedup_by_gift(mine)
    return {
        "rows": unique,
        "min_diamonds": int(min_diamonds),
        "counts": {"total": total, "excluded": excluded, "no_gift": no_gift,
                   "below_min_diamonds": below, "other_owner": other_owner,
                   "duplicated": duplicated, "selected": len(unique)},
    }


def _pad_window(row, pad_lead: float, pad_tail: float) -> tuple:
    """余白を足した切り出し窓。highlightの端は越えない。

    montageのgift演出は隣が無関係な場面なので、上限(:data:`MAX_PAD_SECONDS`)も併せて掛ける。

    **頭の余白は「映像の頭」から手前へ伸びる。** 既定の窓の頭は音の境目ではなく映像が
    切り替わり終わる秒なので(:func:`tictok.store.highlights.default_cut`)、``pad_lead`` を
    0より大きくすると、その分だけ切り替わりの演出と前のgiftの場面が戻ってくる。ここで
    映像の頭へ丸めはしない —— 余白は人が明示して指定する値で、指定を黙って無視すると
    「効かない設定」になる。既定は0.0である。"""
    duration = row.get("highlight_duration_seconds")
    start = max(0.0, float(row["start"]) - float(pad_lead))
    end = float(row["end"]) + float(pad_tail)
    if duration is not None:
        end = min(end, float(duration))
    return start, end


def clamp_to_segment(at, start, end) -> tuple:
    """giftの位置を**gift演出の窓へ丸める**。``(秒, 丸めたか)``。位置が無ければ ``(None, False)``。

    giftは ``gift_lead`` で手前へ伸ばした窓に入っただけのことがあり、そのときの位置
    (``store.highlights.gift_position``)はgift演出の頭より手前を指す。**そこにhighlightの映像は
    無い** —— montageなので、gift演出の頭より手前は「その配信の少し前」ではなく**まったく無関係な
    場面**である(別の時刻のgift演出が繋がっているだけ)。

    丸める先が要る場面は2つあり、**同じ規則で丸める**:

    - 代表frameの秒。丸めないと、下見にも検証の対応表にも**出力に入らない場面**の絵が並ぶ。
      検証の面ではそれが特に危険で、人が無関係な場面を見て「間違っている」と判定すると
      正しい照合が捨てられる。
    - giftから切り出し範囲を作る場合。窓の外の映像は存在しないので、範囲は必ずgift演出へ収める。

    **丸めたことは返り値の2つめが名乗る。** 黙って丸めると、人は絵を見て「この瞬間にこの
    giftが飛んだ」と読む。印が付いていれば「この行のgiftはgift演出の手前に在る」と判り、それ自体が
    その行を疑う手掛かりになる。"""
    if at is None:
        return None, False
    value = min(max(float(at), float(start)), float(end))
    return value, value != float(at)


def _item(row, pad_lead: float, pad_tail: float) -> dict:
    """**gift 1件**を表す行。素材pathの実在確認もここで済ませる。

    ``start``/``end`` は**そのgiftを切る窓**である。人がgiftごとに詰めていなければgift演出の窓と
    同じ値になるので、同じgift演出の複数のgiftは既定では同じ窓を持つ —— そのまま繋ぐと同じ映像が
    並ぶので、実際に切るのは窓を畳んだ :func:`build_cuts` の結果である。ここが持つのは
    「記録」で、あちらが持つのが「切り出し」。
    """
    src = _resolve_source(row)
    start, end = _pad_window(row, pad_lead, pad_tail)
    if end <= start:
        raise RuntimeError(f"gift演出の範囲が空です（{src.name} {start:.3f}-{end:.3f}秒）。")
    return {
        "src": src, "start": start, "end": end,
        "highlight_id": row.get("highlight_id"), "idx": row.get("segment_idx"),
        # **そのgift演出を信用してよいかを画面が名乗るための値。** 出力の中身が別人のgiftに
        # なっていた事故があり(照合側の取りこぼし)、押す前に気付ける材料が要る。
        # ``segment_id`` は照合結果tabの行へ飛ぶ鍵 —— ``idx`` は再照合で動くので使えない。
        "segment_id": row.get("segment_id"),
        "segment_idx": row.get("segment_idx"), "gift_idx": row.get("gift_idx"),
        "approved": row.get("approved"), "edited": row.get("edited"),
        "confidence": row.get("confidence"),
        # giftごとの印。**どれも落とす判断には使わない**(:func:`select_segments`)。
        # ``inside`` が偽のgiftは ``at`` がgift演出の頭より手前を指し、そこにhighlightの映像は
        # 無い(切り出しの窓はgift演出のままである)。
        #
        # **演出の印(``has_effect``)は持たない。** 照合側の契約から外れた —— 実測で本物の
        # 演出と演出無しを同じ値で返すことが判っており、当たりが0件の信号を運ぶと、画面が
        # それを警告として出して人が信じ始める。
        "inside": bool(row.get("inside", True)),
        "is_primary": bool(row.get("is_primary")),
        "manual": bool(row.get("manual")),
        "gift_event_id": row.get("gift_event_id"), "gift_id": row.get("gift_id"),
        "gift_name": row.get("gift_name"), "gift_image": row.get("gift_image"),
        "diamonds": _diamonds(row),
        # まとめ投げの個数と単価。**合計だけを出すと「270💎なのに演出が出ていない」が
        # 謎のまま残る。** 下限を判定しているのは単価の方である(:func:`_unit_diamonds`)。
        "gift_count": int(row.get("gift_count") or 1),
        "unit_diamonds": _unit_diamonds(row),
        "user_nickname": row.get("user_nickname"),
        "user_unique_id": row.get("user_unique_id"),
        "identity_key": row.get("identity_key"),
        "recording_id": row.get("recording_id"),
        "media_start": row.get("media_start"),
        "recording": row.get("recording"),
        # 素材のhighlightのfile名。切る前にDBと突き合わせる(:func:`verify_item`)ときの
        # 手掛かりであり、素性のJSONにも残る —— idだけでは、後から人が見て「どのfileの
        # 何秒か」を辿れない。
        "highlight_filename": row.get("filename"),
        # **余白を足す前の**gift演出の範囲。上の ``start``/``end`` は切り出す窓なので、余白の
        # 指定があるとDBの値と一致しない。突き合わせる相手はこちらである。
        # 余白を足す前の**gift演出の窓**。上の ``start``/``end`` は「このgiftを切る窓」なので、
        # 人がgiftごとに詰めていればgift演出の窓とは別の値になる。突き合わせる相手はこちら。
        "segment_start": float(row["segment_start"]),
        "segment_end": float(row["segment_end"]),
        # 余白を足す前の**このgiftの窓**。切る直前の照合(:func:`verify_item`)がDBと
        # 突き合わせる相手で、gift演出の窓だけを見ていると「人が1行だけ詰めた」変更を
        # 素通りさせてしまう(gift演出の窓は合っているので通る)。
        "gift_cut_start": float(row["start"]), "gift_cut_end": float(row["end"]),
        # 人がこのgiftだけの窓を持たせているか(素性のJSONに残る)。
        "cut_own": bool(row.get("cut_own")),
        # 映像の切り替わりの両端。人が詰めていない窓はここから来ているので、素性のJSONに
        # 残しておかないと「なぜgift演出の窓とずれているのか」を後から辿れない。
        "video_start": row.get("video_start"),
        "video_end": row.get("video_end"),
        "gift_media_time": row.get("gift_media_time"),
    }


def build_cuts(items: list, order: str) -> list:
    """gift 1件ずつの窓から、**実際に切る窓**を作る。重なる窓は1つへ畳む。

    **記録と切り出しは別物である。** 1つのgift演出に複数のgiftが乗るので(実測で Hearts 199💎が
    同じgift演出に6件)、gift 1件ごとに切ると**同じ6秒が6本並ぶ**。それは「連投をそのまま見せる」
    ことではなく、同じ場面の6回繰り返しである。畳めば1つの連続した6秒になり、連投が起きた
    とおりに続けて映る。**giftの記録は1件も落とさない**(:func:`dedup_by_gift` の項)。

    **畳むのは1本のfileの中だけである。** 出力はgifterごとに1本なので、同じgift演出で別人が
    投げた2件はそれぞれ別のfileへ入る。同じ映像が2人のfileに出るのは事実として正しい ――
    その場面で2人が投げたのだから、両方の見せ場である。**fileを跨いで畳まない。**

    連投を「同じ人の同じgiftが近い時刻」で畳む段は**作らない**(利用者の指示)。窓の重なりだけ
    で畳めば同じ結果になり、しかも記録は全件残る。

    素材(``src``)が違う窓は畳まない。別のhighlightのfileは、秒が重なっていても別の映像である。

    **畳み方は ``order`` で変わる。** 隣り合うgift演出を1つの窓へ畳むと、その塊の中は必ず時系列で
    流れる —— 高額順を指定していても畳まれた中だけは時系列に戻り、実測で 99💎 → 4999💎 →
    99💎 の3件のgift演出が0.0〜17.79秒の1つの窓になって「99💎から始まる高額順の1本」が出来た。
    よって高額順ではgift演出を跨いで畳まず(:func:`_priority_cuts`)、時系列順では従来どおり接した
    窓まで畳む(:func:`_merge_windows`) —— あちらは畳んでも並びが変わらず、繋ぎ目だけが減る。

    並びは ``order`` に従う。畳んだ窓の代表値は、高額順ならその窓が含むgiftの**最高額**
    (窓の値打ちは一番大きい見せ場で決まる)、時系列なら**最も早いgift**である。"""
    groups: dict = {}
    for item in items:
        groups.setdefault(item["src"], []).append(item)
    cuts: list = []
    for src, group in groups.items():
        made = (_merge_windows(src, group) if order == ORDER_TIME
                else _priority_cuts(src, group))
        cuts.extend(made)
    if order == ORDER_TIME:
        cuts.sort(key=lambda cut: min(_order_key_time(gift) for gift in cut["gifts"]))
    else:
        cuts.sort(key=lambda cut: min(_order_key_diamonds(gift)
                                      for gift in cut["gifts"]))
    for index, cut in enumerate(cuts):
        cut["index"] = index
    return cuts


def _finish_cuts(cuts: list) -> list:
    """窓の集計(素材・gift演出id・💎)を埋める。窓の作り方が2通りあるので、ここへ寄せる。"""
    for cut in cuts:
        cut["segment_ids"] = sorted({gift["segment_id"] for gift in cut["gifts"]
                                     if gift.get("segment_id") is not None})
        cut["highlight_id"] = cut["gifts"][0].get("highlight_id")
        cut["diamonds"] = sum(_diamonds(gift) for gift in cut["gifts"])
    return cuts


def _merge_windows(src: Path, group: list) -> list:
    """**時系列順の**窓の作り方。同じ素材の窓を、重なりで1つへ畳む。窓の順(start)で返す。

    端が触れているだけ(``前の終わり == 次の始まり``)も畳む。連続した2つのgift演出を続けて切ると
    接合点が1つ増えるだけで、映像としては同じ物になるためである。

    **高額順ではこれを使わない**(:func:`_priority_cuts`)。畳んだ塊の中は必ず時系列で流れる
    ので、高額順に並べたはずの1本が畳まれた場所だけ安いgiftから始まる。"""
    cuts: list = []
    for item in sorted(group, key=lambda i: (float(i["start"]), float(i["end"]))):
        start, end = float(item["start"]), float(item["end"])
        if cuts and start <= cuts[-1]["end"]:
            cuts[-1]["end"] = max(cuts[-1]["end"], end)
            cuts[-1]["gifts"].append(item)
            continue
        cuts.append({"src": src, "start": start, "end": end, "gifts": [item]})
    return _finish_cuts(cuts)


def _window_key(item) -> tuple:
    """同じ窓とみなす鍵。**gift演出1つ = 窓1つ**である。

    連投(同じgift演出に乗った複数のgift)は :func:`_item` が同じ ``start``/``end`` を返すので、
    ここで1つへ落ちる —— 落とさないと同じ6秒がgiftの数だけ並ぶ。gift演出が違えば秒が同じでも
    別の窓にする(実際には起きないが、畳む条件を「秒が同じ」にすると、余白の指定しだいで
    別のgift演出が黙って1つになる)。"""
    return (item.get("segment_id"), round(float(item["start"]), 3),
            round(float(item["end"]), 3))


def _free_span(start: float, end: float, claimed: list):
    """既に切ると決まった区間(``claimed``)を除いた、残りで一番長い連続部分。無ければ None。

    同じ映像を二度入れないための削りである。**削られる側は必ず安い方**になる
    (:func:`_priority_cuts` が高額な窓から先に場所を取る)ので、見せ場の本体は丸ごと残る。"""
    free = [(float(start), float(end))]
    for taken_start, taken_end in claimed:
        rest: list = []
        for span_start, span_end in free:
            if taken_end <= span_start or taken_start >= span_end:
                rest.append((span_start, span_end))
                continue
            if span_start < taken_start:
                rest.append((span_start, taken_start))
            if taken_end < span_end:
                rest.append((taken_end, span_end))
        free = rest
    free = [span for span in free if span[1] - span[0] > MIN_CUT_SECONDS]
    return max(free, key=lambda span: span[1] - span[0]) if free else None


def _priority_cuts(src: Path, group: list) -> list:
    """**高額順の**窓の作り方。💎の高い窓から場所を取り、その順のまま返す。

    gift演出を跨いで畳まない。畳むのは同じgift演出に乗った連投だけで、それは同じ窓だから畳んでも
    並びが変わらない。隣り合う別のgift演出まで畳むと塊の中が時系列で流れてしまい、高額順が
    その塊の中だけ壊れる(module docstringの実測)。

    余白(``pad_lead``/``pad_tail``)で窓が重なった分は、**高額な側を丸ごと残して安い側を削る**。
    削り切られた窓は落とすが、そのgiftは残した窓の中に映っている(重なっていたのだから)ので、
    記録はその窓へ移して素性から消さない。"""
    windows: dict = {}
    for item in group:
        key = _window_key(item)
        cut = windows.get(key)
        if cut is None:
            windows[key] = {"src": src, "start": float(item["start"]),
                            "end": float(item["end"]), "gifts": [item]}
            continue
        cut["gifts"].append(item)
    ordered = sorted(windows.values(),
                     key=lambda cut: min(_order_key_diamonds(gift)
                                         for gift in cut["gifts"]))
    claimed: list = []
    kept: list = []
    for cut in ordered:
        span = _free_span(cut["start"], cut["end"], claimed)
        if span is None:
            # 上位の窓に丸ごと吸われた。giftの記録は吸った窓へ預ける(映っているのはそこ)。
            host = next((k for k in kept
                         if k["start"] < cut["end"] and cut["start"] < k["end"]), None)
            if host is not None:
                host["gifts"].extend(cut["gifts"])
            continue
        cut["start"], cut["end"] = span
        claimed.append(span)
        kept.append(cut)
    return _finish_cuts(kept)


def _assert_no_overlap(cuts: list) -> None:
    """1本の中に同じ映像が二度入らないことを、切る前に確かめる。

    :func:`build_cuts` が畳んだ後なので通常は起き得ないが、**出来上がってから気付いても
    直せない**(mp4は既に出来ている)。窓の作り方を変えたときにここで落ちる。"""
    by_src: dict = {}
    for cut in cuts:
        by_src.setdefault(cut["src"], []).append(cut)
    for src, group in by_src.items():
        ordered = sorted(group, key=lambda cut: float(cut["start"]))
        for previous, current in zip(ordered, ordered[1:]):
            if float(current["start"]) < float(previous["end"]):
                raise RuntimeError(
                    f"同じ映像が2回入る切り出しになっています（{Path(src).name} "
                    f"{previous['start']:.3f}-{previous['end']:.3f}秒 と "
                    f"{current['start']:.3f}-{current['end']:.3f}秒）。")


def _resolve_source(row) -> Path:
    """そのgift演出を切り出す素材(highlightのmp4)のpath。

    ``highlight_videos.path`` が絶対pathならそのまま、相対なら置き場
    (``<work root>/<配信者>/highlights``)の下として解く。実在しなければここで失敗させる
    ―― 無い素材のまま切り出しへ進むと、ffmpegの失敗としてしか現れず、どのgift演出の話なのかが
    出力に残らない。

    相対pathは**配信者が判らなければ解けない**(置き場が配信者folderの下だからである)。
    その場で断るのは、``layout.highlight_dir`` の失敗をそのまま上げるとどのgift演出の話なのかが
    残らないためで、判断そのものはlayout側と同じである。"""
    value = row.get("path")
    if not value:
        raise RuntimeError(
            f"gift演出の素材pathがありません（highlight {row.get('highlight_id')} / "
            f"idx {row.get('idx')}）。")
    src = Path(value)
    if not src.is_absolute():
        streamer = row.get("unique_id")
        if not streamer:
            raise RuntimeError(
                f"gift演出の素材が相対pathですが配信者が判りません（highlight "
                f"{row.get('highlight_id')} / idx {row.get('idx')} / path {value}）。")
        src = layout.highlight_dir(streamer) / src
    if not src.is_file():
        raise RuntimeError(f"highlightのfileが存在しません: {src}")
    return src


def safe_display_name(nickname, *, budget: int = NICKNAME_MAX_CHARS) -> str:
    """表示名をfile名へ置ける形にする。**空になったら失敗させる。**

    表示名は利用者が自由に付けるもので、file名に置けない文字がそのまま入る。実データにも
    ``ありしゃ🐈‍⬛🐾``(ZWJ結合)や ``🟡むらたろう🍑🏌️‍♂️🍔``(ZWJ+異体字選択子)が在る。

    決めたこと:

    - **絵文字は残す。** NTFSはそのまま置けるし、落とすと ``ぽみ`` のように**別人に見える**。
      表示名を名乗る意味そのものが消える。
    - 置けない文字(``< > : " / \ | ? *``・制御文字)は ``_`` へ置き換える。落とさず置き換える
      のは、消すと ``a/b`` と ``ab`` が同じ名前になるためである(clipperのlabelと同じ規則)。
    - 前後の空白と**末尾のピリオド**を落とす。Windowsはこれらを黙って捨てるので、残すと
      「作ったつもりの名前」と実物が食い違う。
    - 長すぎる名前は切り詰めて末尾に :data:`TRUNCATION_MARK` を付ける。**切り詰めたことが
      判る形**にする ―― 黙って短くすると、別人の名前に化けても気付けない。
    - 切り詰めた末尾に結合用の符号(ZWJ・異体字選択子・肌色・結合文字)が残らないようにする。
      残すと「途中で切れた絵文字列」になり、環境によって描画が崩れる。
      ``🏌️‍♂️`` が ``🏌️`` になることはある ―― 絵文字1つとしては完結しているので許す。

    **Windowsの予約名(CON/PRN/AUX/NUL/COM1…)は個別に扱わない。** 予約名の判定は最初の
    ``.`` より前の全体に掛かるが、この関数の結果は必ず ``<日付>_coin<数>_`` の後ろに置かれ、
    後ろにも ``_story`` が付く。表示名がそのままstemになる経路が無いので、当たらない。

    空(または置換の結果が空)なら :class:`NoDisplayName` を送出する。**``unique_id`` へ
    差し替えない** ―― 名乗れないものを別の値で埋めると、file名が持ち主の嘘をつく。"""
    text = _UNSAFE_NAME_RE.sub("_", str(nickname or ""))
    # 切り詰めていなくても掛ける。ZWJだけで出来た表示名は目に見える字を1つも持たないので、
    # そのまま置くと中身の無いfile名になる。
    text = _strip_edges(_strip_dangling(_strip_edges(text)))
    if len(text) > budget:
        text = _strip_dangling(text[:max(0, budget - len(TRUNCATION_MARK))])
        text = _strip_edges(text)
        if text:
            text += TRUNCATION_MARK
    if not text:
        raise NoDisplayName(
            f"表示名がfile名に使える文字を含んでいません（{nickname!r}）。"
            "この人ぶんの書き出しはfile名を付けられません。")
    return text


def _strip_edges(text: str) -> str:
    """前後の空白を落とす。

    **ピリオドは落とさない。** Windowsが黙って捨てるのは*file名の末尾*の ``.`` であって、
    名前の途中のものではない。この関数の結果は必ず ``_story.mp4`` の手前に置かれるので
    末尾には来ない。落とすと ``...`` のような表示名が丸ごと消え、置ける名前を「置けない」
    と誤って判定する。"""
    return text.strip()


def _strip_dangling(text: str) -> str:
    """切り詰めた末尾に残ると壊れる符号だけを落とす(:data:`_ZWJ` / :data:`_REGIONAL`)。

    地域表示記号は**奇数個で終わったときに1つだけ**落とす。まとめて落とすと、旗だけで
    できた表示名が空になり「置ける名前を置けない」と誤判定する(実測で
    ``🇯🇵🇺🇸🇬🇧🇫🇷🇩🇪🇮🇹旗`` が空になった)。"""
    while text and text[-1] == _ZWJ:
        text = text[:-1]
    trailing = 0
    while trailing < len(text) and text[-1 - trailing] in _REGIONAL:
        trailing += 1
    if trailing % 2:
        text = text[:-1]
    while text and text[-1] == _ZWJ:
        text = text[:-1]
    return text


def _yymmdd(ts: float) -> str:
    """POSIX秒を ``yymmdd``(ローカル時刻)へ。file名の日付はこの1か所で組み立てる。"""
    return datetime.fromtimestamp(float(ts)).strftime("%y%m%d")


def segment_date(item) -> Optional[float]:
    """そのgift演出の映像が**実際に配信された時刻**(POSIX秒)。

    録画の開始時刻そのものではなく ``開始 + media_start`` を採る。録画は3時間級になるので、
    終盤のgift演出は録画の開始日とは別の日に写っている。

    **file名には使わない**(あちらは週の窓 —— :func:`export_filename`)。使うのは画面が
    「この1本には実際にいつの場面が入っているか」を出すためで、file名から落ちた情報を
    どこかで名乗れるようにしておく。

    録画が消えていると出せない。捏造せず ``None`` を返す。"""
    recording = item.get("recording") or {}
    started_at = recording.get("started_at")
    media_start = item.get("media_start")
    if started_at is None or media_start is None:
        return None
    return float(started_at) + float(media_start)


def name_position(position: Optional[int], total: Optional[int] = None) -> str:
    """file名の先頭に付く順位。``None`` なら空文字(prefixを付けない)。

    桁は**その週に出来るfile数**で決める。週の中で桁が揃っていないと ``10_`` が ``2_`` より
    前に来て、prefixを付けた意味が無くなる。週が違えば日付の部分が先に効くので、週をまたいで
    桁が揃っている必要は無い。"""
    if position is None:
        return ""
    width = max(2, len(str(int(total or 0))))
    return f"{int(position):0{width}d}_"


def export_filename(start_ts: float, end_ts: float, coin: int, display: str,
                    *, mark: str = "", verified: bool = True,
                    position: Optional[int] = None,
                    total: Optional[int] = None) -> str:
    """出力のfile名。``<順位>_yymmdd-yymmdd_coin<週合計>_<表示名>_story.mp4``。

    **日付もコイン数も同じ週を指す。** 日付は週の窓、コイン数はその週にその人がこの配信者へ
    投げた総額(``streamer_mention_week`` の ``gifters[].diamonds``)で、同じ週の書き出しなら
    **全fileが同じ日付範囲**になる。「この人はこの週に2,088コイン投げた」と1行で読める。

    **窓は半開区間 [土07:00, 次の土07:00) である。** 日付だけの名前では時刻が落ちるので、
    どちらの端をどう名乗ったかを書いておく:

    - 先頭は**開始の日付**(その週の土曜)。``260829`` は 08-29 07:00 から。
    - 末尾は**終端そのものの日付**(次の土曜)であって、終端の1秒前ではない。``260905`` は
      09-05 07:00 **まで**を意味し、9月5日を丸ごと含むわけではない。

    末尾を1日引いて ``260904`` としない理由は ``_post_range_label`` と同じで、「9月4日まで」と
    書くと土曜の朝7時までの分が抜けているように読めるためである。窓そのものの端を時刻付きで
    名乗るのは応答の ``start_label`` / ``end_label`` の役目で、file名は日付までしか持たない。

    ``coin`` に桁区切りは入れない(利用者の指定)。**したがってcoinの数字では額の順に並ばない**
    —— 文字列順では ``coin14611`` が ``coin3092`` より前に来る。額の順に並べるのは先頭の
    ``position``(その週の順位、01が一番多い人)の役目で、これが無いとfolderを開いた人には
    でたらめな順に見える。0詰めしたcoinで代用しないのは、それだと安い人から並ぶためである。

    ``position`` を渡さなければprefixは付かない(既に書き出したfileと同じ名前が出せる)。
    実際に付けるのは :func:`plan_exports` で、順位は**その計画の中の順**である。

    ``mark`` は表示名が衝突したときだけ付く識別子(:func:`_resolve_collisions`)。

    ``verified=False`` は検証用の経路(:func:`export_highlights` の ``verification_rows``)を
    通った出力で、``_story`` の後ろに :data:`UNVERIFIED_MARK` が入る。**製品の出力と同じ名前を
    名乗らせない** —— 中身がDBの実照合結果と突き合わせられていないので、後から見た人が
    成果物と取り違える。"""
    name = safe_display_name(display)
    if mark:
        name = f"{name}-{mark}"
    return (f"{name_position(position, total)}"
            f"{_yymmdd(start_ts)}-{_yymmdd(end_ts)}"
            f"_{COIN_PREFIX}{int(coin)}_{name}{STORY_SUFFIX}"
            f"{'' if verified else UNVERIFIED_MARK}{STORY_EXT}")


def _plan_filename(plan: dict, *, budget: int = NICKNAME_MAX_CHARS) -> str:
    """計画1件のfile名。**組み立てはここ1本にする。**

    file名を作る場所は3つある(最初の命名・衝突の解決・path長の詰め)。順位のprefixのような
    要素を足したとき、1箇所でも書き漏らすとその経路を通ったfileだけ別の名前になる。"""
    return export_filename(
        plan["start_ts"], plan["end_ts"], plan["coin"],
        safe_display_name(plan["nickname"], budget=budget),
        mark=plan.get("mark", ""), verified=plan["verified"],
        position=plan.get("position"), total=plan.get("position_total"))


def _collision_mark(identity_key) -> str:
    """表示名が衝突したときにfile名へ足す識別子。``identity_key`` から決まる。

    連番にしない。連番は「何本目に書き出したか」で決まるので、次の週に人が増減しただけで
    同じ人のfileが別の名前になる。identity_keyから作れば、その人の印は常に同じである。"""
    return hashlib.blake2s(str(identity_key).encode("utf-8"),
                           digest_size=3).hexdigest()


def _resolve_collisions(plans: list) -> None:
    """同じfile名になる書き出しへ、区別できる印を付ける(``plans`` を書き換える)。

    ``identity_key`` が違うのに表示名・週合計・日付範囲がすべて同じ2人が居ると、file名が
    衝突する。**黙って上書きさせない。** 衝突したときは**両方**に印を付ける ―― 片方だけに
    付けると、印の無い方が「元からの持ち主」に見えてしまう。

    **見るのは順位のprefixを外した名前である。** prefix(:func:`name_position`)は計画の中で
    必ず一意なので、それを含めて比べると文字列としては衝突しなくなり、この関数は何もしなく
    なる。だが順位はその週に誰が居たかで動く数字で、**人の印にはならない**
    (:func:`_collision_mark` の項)—— 同名の2人が ``01_`` と ``02_`` で並ぶだけになり、
    次の週には入れ替わる。区別が要るのは prefix より後ろである。

    衝突が無ければ印は付かない(利用者が指定した形のまま)。"""
    by_name: dict = {}
    for plan in plans:
        prefix = name_position(plan.get("position"), plan.get("position_total"))
        by_name.setdefault(plan["filename"][len(prefix):], []).append(plan)
    for colliding in by_name.values():
        if len(colliding) < 2:
            continue
        for plan in colliding:
            plan["mark"] = _collision_mark(plan["identity_key"])
            plan["filename"] = _plan_filename(plan)
        logger.warning(
            "表示名が同じgifterが居るためfile名へ識別子を付けます（%s）",
            "／".join(p["filename"] for p in colliding),
            extra={"event": "highlight_export.name_collision",
                   "ctx": {"filenames": [p["filename"] for p in colliding],
                           "identity_keys": [p["identity_key"] for p in colliding]}},
        )


def _fit_path(directory: Path, plan: dict) -> None:
    """path長の上限に収まるまで表示名を詰める(``plan`` を書き換える)。

    Windowsの既定APIはpath全体で260文字までである。置き場のpathは配信者名を含むので、
    どれだけ表示名へ使えるかは実行時にしか判らない。詰めた分は
    :data:`TRUNCATION_MARK` が名乗る(:func:`safe_display_name`)。

    1文字も入らないところまで詰まったら失敗させる ―― 名前を捨てて別の物にするより、
    置き場を短くしてほしいと言う方が直せる。"""
    room = MAX_PATH_CHARS - len(str(directory)) - 1
    budget = NICKNAME_MAX_CHARS
    while budget >= 1:
        name = _plan_filename(plan, budget=budget)
        if len(name) <= room:
            plan["filename"] = name
            return
        budget -= 4
    raise RuntimeError(
        f"file名がpath長の上限（{MAX_PATH_CHARS}文字）に収まりません"
        f"（置き場 {directory}）。置き場を短いpathへ移してください。")


# ===== 素性の照合 =====
#
# 切る直前にDBへ引き直して突き合わせる列。**切り出しの位置と持ち主を決めている値だけ**を
# 並べる —— votesやratioのような「どれくらい確からしいか」の値は、食い違っても出来上がる
# mp4の中身は変わらない(そこで失敗させると、照合の質だけが理由で書き出せない日が来る)。
#
# gift演出側とgift側で分ける。**片方の表の値をもう片方から確かめることはできない** ——
# 位置(どこを切るか)はgift演出が決め、持ち主(誰のfileか)はgiftが決める。
_VERIFY_SEGMENT_COLUMNS = ("recording_id", "media_start")
_VERIFY_GIFT_ROW_COLUMNS = ("gift_event_id", "gift_id", "gift_name", "diamonds",
                            "identity_key", "user_unique_id", "gift_media_time")

# giftのeventそのものと突き合わせる列。gift演出のgift列は機械が入れても人が差し替えても
# ``events`` の1行から丸ごと写されるので(``store.highlight_gift_event``)、ここが食い違う
# gift演出は**どちらの経路でも作られ得ない**。今回の事故(別人のfileに別人のgift)はここで落ちる。
_VERIFY_GIFT_COLUMNS = ("gift_id", "gift_name", "diamonds", "identity_key")


def _same(left, right) -> bool:
    """DBの値と手元の値が同じか。数値は型を跨いで比べる(INTEGER列とfloatが混ざる)。"""
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    return str(left) == str(right)


def verify_item(store, item: dict, identity_key) -> dict:
    """切る直前の1件をDBへ引き直して照合し、素性の記録を返す。食い違えば :class:`NotVerified`。

    **これが「実照合結果からしか書き出さない」を成り立たせている唯一の場所である。**
    :func:`plan_exports` が見ているのは渡された行だけなので、行そのものが偽物なら計画は
    正しく見える。ここでDBを引き直すことで、計画に何が載っていようと**出来上がるmp4は
    保存された照合結果と一致する**ようになる。

    確かめるのは5つ。

    1. 素材のhighlightが台帳に在り、``status`` が ``matched`` であること。
    2. **切ろうとしているfileが、そのgift演出が属するhighlightのfileそのもの**であること。
       事故はここで起きた —— 範囲はあるhighlightから、名前は別のhighlightの真値から
       採られていた。idとfileが別々に選べる限り、この照合が無ければ同じ事が起きる。
    3. gift演出の行が実在し、人が外して(``excluded``)も再照合で消えて(``dropped``)もおらず、
       範囲・録画・giftの列が渡された値と**1つ残らず一致する**こと。
    4. ``gift_event_id`` が ``events`` の実在するgiftを指し、💎・gift名・``identity_key``
       がgift演出の列と一致すること。
    5. そのgiftのgifterが**このfileの持ち主と同じ人**であること。file名は持ち主を名乗るので、
       ここが違うfileは名前が嘘をつく。

    ``identity_key`` はこのfileの持ち主(:func:`plan_exports` が束ねた鍵)。"""
    highlight_id, segment_id = item.get("highlight_id"), item.get("segment_id")
    if highlight_id is None or segment_id is None:
        raise NotVerified(
            f"gift演出がDBの行を指していません（highlight {highlight_id} / "
            f"segment {segment_id}）。照合結果からの書き出しではありません。")
    video = store.get_highlight(int(highlight_id))
    if video is None:
        raise NotVerified(f"highlightの行がありません（id {highlight_id}）。")
    if video.get("status") != HIGHLIGHT_STATUS_MATCHED:
        raise NotMatched(
            f"照合が終わっていないhighlightからは書き出せません"
            f"（{video.get('filename')} / status {video.get('status')}）。")
    expected_src = _resolve_source({**video, "highlight_id": highlight_id,
                                    "idx": item.get("idx")})
    if Path(item["src"]).resolve() != expected_src.resolve():
        raise NotVerified(
            f"切り出す素材がgift演出の属するhighlightと違います"
            f"（gift演出 {segment_id} は {expected_src.name} の物ですが "
            f"{Path(item['src']).name} を切ろうとしています）。")

    segment = store.get_highlight_segment(int(highlight_id), int(segment_id))
    if segment is None:
        raise NotVerified(
            f"gift演出の行がありません（highlight {highlight_id} / segment {segment_id}）。")
    if segment.get("excluded") or segment.get("dropped"):
        raise NotVerified(
            f"人が外したgift演出、または再照合で消えたgift演出です"
            f"（highlight {highlight_id} / segment {segment_id}）。")
    for name, value in (("start", item.get("segment_start")),
                        ("end", item.get("segment_end"))):
        if not _same(segment.get(name), value):
            raise NotVerified(
                f"gift演出の範囲がDBと違います（segment {segment_id} / {name}: "
                f"DB {segment.get(name)} と {value}）。")
    for column in _VERIFY_SEGMENT_COLUMNS:
        if not _same(segment.get(column), item.get(column)):
            raise NotVerified(
                f"gift演出の内容がDBと違います（segment {segment_id} / {column}: "
                f"DB {segment.get(column)!r} と {item.get(column)!r}）。")
    if segment.get("recording_id") is None:
        raise NotVerified(
            f"gift演出が録画に紐づいていません"
            f"（highlight {highlight_id} / segment {segment_id}）。")

    # **giftはそのgift演出の持ち物の中から引く。** 1つのgift演出が複数のgiftを持つので、
    # ``gift_event_id`` を鍵にして「このgift演出に実在するgift」だけを相手にする。gift演出の外から
    # 持ってきたgiftを、gift演出の映像へ結び付けさせない。
    gift_event_id = item.get("gift_event_id")
    if gift_event_id is None:
        raise NotVerified(
            f"giftを持たないgift演出は書き出せません"
            f"（highlight {highlight_id} / segment {segment_id}）。")
    gift = next((g for g in (segment.get("gifts") or [])
                 if _same(g.get("gift_event_id"), gift_event_id)), None)
    if gift is None:
        raise NotVerified(
            f"そのgift演出はこのgiftを持っていません"
            f"（segment {segment_id} / event {gift_event_id}）。")
    if gift.get("excluded") or gift.get("dropped"):
        raise NotVerified(
            f"人が外したgift、または再照合で消えたgiftです"
            f"（segment {segment_id} / event {gift_event_id}）。")
    for column in _VERIFY_GIFT_ROW_COLUMNS:
        if not _same(gift.get(column), item.get(column)):
            raise NotVerified(
                f"giftの内容がDBと違います（segment {segment_id} / "
                f"event {gift_event_id} / {column}: "
                f"DB {gift.get(column)!r} と {item.get(column)!r}）。")
    # **そのgiftの窓**もDBと合っていること。gift演出の窓しか見ないと、人が1行だけ詰めた後に
    # 古い下見(plan)から書き出したときに素通りする —— gift演出の窓は合っているからである。
    db_cut = gift_cut(segment.get("start"), segment.get("end"), gift,
                      segment.get("video_start"), segment.get("video_end"))
    for name, db_value, value in (("start", db_cut[0], item.get("gift_cut_start")),
                                  ("end", db_cut[1], item.get("gift_cut_end"))):
        if not _same(db_value, value):
            raise NotVerified(
                f"giftの区間がDBと違います（segment {segment_id} / "
                f"event {gift_event_id} / {name}: DB {db_value} と {value}）。"
                "画面で区間を直した後は、下見からやり直してください。")

    event = store.highlight_gift_event(int(gift["gift_event_id"]))
    if event is None:
        raise NotVerified(
            f"gift演出が指すgift eventがありません"
            f"（segment {segment_id} / event {gift['gift_event_id']}）。")
    for column in _VERIFY_GIFT_COLUMNS:
        if not _same(gift.get(column), event.get(column)):
            raise NotVerified(
                f"gift演出のgiftがDBのeventと違います（segment {segment_id} / "
                f"event {gift['gift_event_id']} / {column}: "
                f"DB {event.get(column)!r} と gift演出 {gift.get(column)!r}）。"
                "再照合してください。")
    if not _same(event.get("identity_key"), identity_key):
        raise NotVerified(
            f"このfileの持ち主と、gift演出のgiftを投げた人が違います"
            f"（file {identity_key!r} / gift {event.get('identity_key')!r} = "
            f"{event.get('user_nickname')!r} / event {gift['gift_event_id']}）。")

    return {
        "highlight_id": int(highlight_id),
        "highlight_filename": video.get("filename"),
        "highlight_path": str(expected_src),
        # **そのgift演出がどの条件の照合から出たか。** 既定値は動くので(下限も候補の日数も設定と
        # 引数で変わる)、後から見た人が「これは古い設定の出力だ」と気付ける手掛かりが要る。
        # 素性のJSONでは :func:`provenance_record` が ``sources`` へまとめる。
        "match_scope": video.get("scope"),
        "matched_at": video.get("matched_at"),
        "segment_id": int(segment_id), "idx": item.get("idx"),
        # highlight自身の時間軸。``segment_*`` が照合が出したgift演出の範囲で、``cut_*`` が
        # 実際に切った窓である(余白の指定があると広がる)。2つとも残すのは、出来上がった
        # 尺がgift演出の尺と違う理由がそこにしか無いからである。
        "segment_start": item.get("segment_start"), "segment_end": item.get("segment_end"),
        "cut_start": item.get("start"), "cut_end": item.get("end"),
        "confidence": segment.get("confidence"),
        "approved": int(segment.get("approved") or 0),
        "edited": int(segment.get("edited") or 0),
        # 録画側(media軸)の位置。highlightがどこから来たのかを人が辿る鍵で、
        # ``gift_media_time`` との差が「gift演出の何秒目でgiftが飛んだか」になる。
        "recording_id": segment.get("recording_id"),
        "media_start": segment.get("media_start"),
        "gift_media_time": gift.get("gift_media_time"),
        "gift_event_id": int(gift["gift_event_id"]),
        "gift_id": gift.get("gift_id"), "gift_name": gift.get("gift_name"),
        "diamonds": gift.get("diamonds"),
        # giftごとの印。**落とす判断には使っていない**が、素性には残す —— 後から
        # 「なぜこのgiftが入っているのか」を人が読むときの材料になる。
        "inside": bool(gift.get("inside")),
        "is_primary": bool(gift.get("is_primary")),
        "manual": bool(gift.get("manual")),
        # gift演出の中で検出した演出区間。**診断用**として残っているだけで、判断には使わない
        # (giftごとの印は契約から外れた)。素性へ写しておくのは、後から人が
        # 「そのとき検出器は何を見ていたか」を辿れるようにするためである。
        "effect": [list(span) for span in (segment.get("effect") or [])],
        "gifter": {"identity_key": event.get("identity_key"),
                   "nickname": event.get("user_nickname"),
                   "unique_id": event.get("user_unique_id")},
        "gift_event_at": event.get("at"),
    }


def verify_items(store, items: list, identity_key) -> list:
    """1本ぶんのgift演出を全部照合する。並びは ``items`` のまま(=出来上がる尺の順)。"""
    return [verify_item(store, item, identity_key) for item in items]


def _unverified_records(items: list) -> list:
    """検証用の経路で、DBを引かずに組む素性の記録。

    **確かめていない値をそのまま写す。** 照合済みの記録(:func:`verify_item`)と同じkeyで
    出すのは、後から読む側が同じ道具で読めるようにするためで、``verified: false`` が
    「この値はDBと突き合わせていない」ことを名乗る。"""
    return [{"highlight_id": item.get("highlight_id"),
             "highlight_filename": item.get("highlight_filename"),
             "highlight_path": str(item.get("src")),
             "segment_id": item.get("segment_id"), "idx": item.get("idx"),
             "segment_start": item.get("segment_start"),
             "segment_end": item.get("segment_end"),
             "cut_start": item.get("start"), "cut_end": item.get("end"),
             "confidence": item.get("confidence"),
             "recording_id": item.get("recording_id"),
             "media_start": item.get("media_start"),
             "gift_event_id": item.get("gift_event_id"),
             "gift_id": item.get("gift_id"), "gift_name": item.get("gift_name"),
             "diamonds": item.get("diamonds"),
             "gifter": {"identity_key": item.get("identity_key"),
                        "nickname": item.get("user_nickname"),
                        "unique_id": item.get("user_unique_id")}}
            for item in items]


# 素材のhighlightに1つしか無い値。素性のJSONでは ``sources`` へまとめ、gift演出からは落とす
# (gift演出の数だけ同じ値が並ぶ)。
_SOURCE_ONLY_KEYS = ("match_scope", "matched_at")


def provenance_record(entry: dict, checked: list, *, streamer: str, plan: dict,
                      verified: bool) -> dict:
    """出力1本の素性。mp4の隣へJSONとして置く(:func:`render_segments`)。

    **中身の素性を機械が確かめられる形で残すためのものである。** file名は「誰の・いつの・
    いくらぶんか」を名乗るが、名前の側には中身がそのとおりである保証が何も無い。ここには
    gift演出1つずつの出所(highlightのidとfile名・秒・gift eventのid・録画のidとmedia秒)が
    並ぶので、後から人がDBを引いて1件ずつ突き合わせられる。

    ``sources`` は素材のhighlightごとに1件で、**その照合がどの条件で走ったか**
    (``highlight_videos.scope_json``)と、いつ走ったかを持つ。既定値は動く(gift 1件の下限も
    候補の日数も設定と引数で変わる)ので、これが無いと後から見た人が「これは古い設定の
    出力だ」と気付けない。gift演出の側には置かない —— 1本のhighlightに1つの条件なので、
    gift演出の数だけ同じ値が並ぶことになる。

    ``verified`` は :func:`verify_item` を通ったかどうか。検証用の経路
    (``verification_rows``)では ``False`` になり、``checked`` はDBを引かずに組んだ記録に
    なる。**この2つを混ぜて読めないようにするための旗である。**"""
    sources: dict = {}
    segments: list = []
    for index, record in enumerate(checked):
        segments.append({"position": index + 1,
                         **{k: v for k, v in record.items()
                            if k not in _SOURCE_ONLY_KEYS}})
        highlight_id = record.get("highlight_id")
        if highlight_id is not None and highlight_id not in sources:
            sources[highlight_id] = {
                "highlight_id": highlight_id,
                "filename": record.get("highlight_filename"),
                "path": record.get("highlight_path"),
                "scope": record.get("match_scope"),
                "matched_at": record.get("matched_at"),
            }
    return {
        "schema": PROVENANCE_SCHEMA,
        "kind": "highlight_export",
        "verified": bool(verified),
        "created_at": time.time(),
        "streamer": streamer,
        "week": plan.get("week") or "",
        "week_label": plan.get("week_label") or "",
        "filename": entry.get("filename"),
        "gifter": {"identity_key": entry.get("identity_key"),
                   "nickname": entry.get("nickname"),
                   "unique_id": entry.get("unique_id"),
                   "week_diamonds": entry.get("coin"), "rank": entry.get("rank")},
        "order": plan.get("order"),
        "post_min": plan.get("post_min"), "min_diamonds": plan.get("min_diamonds"),
        "sources": list(sources.values()),
        # **記録(gift)と切り出し(窓)の両方を残す。** 1対1にならないので、片方だけでは
        # 「なぜgiftが6件なのに映像が1つなのか」を後から読む人が辿れない。
        "segments": segments,
        "cuts": [_cut_summary(cut) for cut in (entry.get("cuts") or [])],
    }


def _require_marked_name(out: Path, provenance: dict) -> None:
    """出力のfile名と、その素性の ``verified`` が食い違っていないことを確かめる。

    **両方向に縛る。** 検証していない中身が製品の名前で出るのを止めるのが主目的だが、
    逆(検証済みの中身が検証用の名前で出る)も止める —— どちらも「名前から中身を判断できる」
    という前提を壊す。名前の印は :data:`UNVERIFIED_MARK`。"""
    if not isinstance(provenance, dict) or "verified" not in provenance:
        raise NotVerified(
            f"出力の素性がありません（{out.name}）。素性の無いmp4は作れません。")
    marked = UNVERIFIED_MARK + STORY_EXT in out.name
    if provenance["verified"] and marked:
        raise NotVerified(
            f"照合済みの中身を検証用のfile名で書き出そうとしています（{out.name}）。")
    if not provenance["verified"] and not marked:
        raise NotVerified(
            f"DBの照合結果と突き合わせていない中身を、製品のfile名で書き出そうとしています"
            f"（{out.name}）。検証用の出力には {UNVERIFIED_MARK} が要ります。")


def provenance_path(out: Path) -> Path:
    """素性のJSONの置き場。``<file名>.mp4.json``。

    拡張子を差し替えず**後ろへ足す**のは、どのmp4の物かをfile名だけで言い切るためである
    (``.json`` へ差し替えると、同じ名前で別の版のmp4が在ったときにどちらの物か判らない)。
    切り出し一覧はこの拡張子を拾わないので画面には出ないが、mp4を消せば一緒に消える
    (``tictok.api.routes.clips``)。"""
    return out.parent / f"{out.name}{PROVENANCE_EXT}"


def _cut_summary(cut: dict) -> dict:
    """切った窓1つを、JSONへそのまま載る形にする(``Path`` も入れ子のdictも残さない)。"""
    return {
        "src": str(cut["src"]),
        "start": cut.get("start"), "end": cut.get("end"),
        "seconds": cut.get("seconds"), "lead_seconds": cut.get("lead_seconds"),
        "highlight_id": cut.get("highlight_id"),
        "segment_ids": list(cut.get("segment_ids") or []),
        "diamonds": cut.get("diamonds"),
        # この窓に含まれるgift。**連投はここで初めて1つの窓へ集まる**(記録は落とさない)。
        "gift_event_ids": [gift.get("gift_event_id")
                           for gift in (cut.get("gifts") or [])],
        # 窓1つの名乗り。書き出したfileを通しで観るとき、章の帯はこれだけを読む ——
        # event idから名前を引き直させると、画面が台帳へ問い合わせないと章が作れず、
        # 素材が消えた後のfileでは章が空になる。**素性のJSONだけで完結させる。**
        "gifts": [{"gift_event_id": gift.get("gift_event_id"),
                   "gift_name": gift.get("gift_name"),
                   "diamonds": gift.get("diamonds"),
                   "user_nickname": gift.get("user_nickname")}
                  for gift in (cut.get("gifts") or [])],
    }


def _write_provenance(out: Path, provenance: dict, info: dict) -> str:
    """素性を ``<file名>.mp4.json`` へ書く。書けなければ**書き出しごと失敗させる。**

    素性の無いmp4を残さない。「mp4は在るのに素性が無い」は、まさに今回の事故で起きた状態
    そのもの(中身の出所を誰も辿れないfileが7本)である。書けない理由(容量・権限)が在るなら
    mp4も作れていない方が正しい。"""
    path = provenance_path(out)
    record = {**provenance,
              "output": {"filename": out.name, "bytes": info["bytes"],
                         "parts": info["parts"], "encoder": info["encoder"],
                         "precise": info["precise"], "normalized": info["normalized"],
                         "requested_seconds": info["requested_seconds"],
                         "measured": info["measured"]}}
    try:
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        logger.error(
            "書き出しの素性を残せませんでした。出力を削除します: %s", path,
            exc_info=True,
            extra={"event": "highlight_export.provenance_failed",
                   "ctx": {"output": str(out), "provenance": str(path)}})
        out.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise
    return str(path)


def _encode_target(params: dict) -> dict:
    """全partを焼く先の1組。**素材ごとに別々の値で焼いてはいけない。**

    mp4のcodec設定(avcCと音声のrate/channel)は**先頭fileのものが1つだけ書かれる**ので、
    partごとに素材の値を継いで焼くと、繋いだ後は先頭以外が誤った設定で復号される。実測では
    480x854/48kHz/mono の素材を先頭に置いた回で、後続の 720x1280/44.1kHz/stereo のpartが
    「48kHz mono」として鳴る出力が rc=0 で出来た。揃えるのは解像度だけでは足りない。

    揃える先は「どの素材も情報を落とさずに入る所」。幅・高さ・sample rate・channel数は
    それぞれの最大を採り、残り(codec/pix_fmt/profile)は**面積が最大の素材**の値を継ぐ ――
    そこが素材の中で最も情報量の多い1本で、他はそこへ寄せる側だからである。

    幅と高さを独立に採るのは、切替でaspectまで変わる素材があるため。片方の組をそのまま枠に
    すると、もう一方は必ずはみ出すか余る(``hls_source.widest_resolution`` と同じ方針)。"""
    videos = [p["video"] for p in params.values()]
    audios = [p["audio"] for p in params.values()]
    base = max(params.values(),
               key=lambda p: int(p["video"]["width"]) * int(p["video"]["height"]))
    return {
        "video": {**base["video"],
                  "width": max(int(v["width"]) for v in videos),
                  "height": max(int(v["height"]) for v in videos)},
        "audio": {**base["audio"],
                  "sample_rate": max(int(a["sample_rate"]) for a in audios),
                  "channels": max(int(a["channels"]) for a in audios)},
    }


def _scale_filter(target: dict) -> str:
    """aspectを保ったままscaleし、余白をpadで埋めるfilter。

    ``force_original_aspect_ratio=decrease`` を外すと縦横比の違う素材が潰れる。``setsar=1``
    まで書くのは、padの後にsample aspectが残っていると連結後の再生で再び伸びるためである。"""
    w, h = int(target["video"]["width"]), int(target["video"]["height"])
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")


def _encode_part_args(src: Path, start: float, end: float, dst: Path, target: dict,
                      encoder: str, quality: int, scale: Optional[str]) -> list:
    """1つのgift演出をframe精度で切ってTS中間へ焼くffmpeg command。

    ``target`` は**全partで同じ1組**(:func:`_encode_target`)。素材ごとの値を継がないのは、
    mp4が先頭fileのcodec設定を1つだけ書くためである。

    ``-ss`` は ``-i`` の**後ろ**(出力側)に置く。復号して捨てる形なので開始位置に比例して
    遅くなるが、highlightは最長61秒のmp4なので上限がそこで閉じている。入力側 ``-ss`` は
    keyframe単位でしか着地せず、それではこの経路の目的(frame精度)が成り立たない。

    中間をTSにするのと ``-muxdelay 0 -muxpreload 0`` を付ける理由は
    :mod:`tictok.media.concat` にある。"""
    video, audio = target["video"], target["audio"]
    args = ["ffmpeg", "-v", "error", "-y", "-i", str(src),
            "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"]
    if scale:
        # 正規化する回だけ枠とfpsを明示する。揃っている素材へ ``-r`` を渡すと、素材が持つ
        # 微妙な間隔をffmpegがframeの複製・間引きで固定fpsへ均してしまう。
        args += ["-vf", scale, "-r", target["fps"]]
    args += _encoder_args(encoder, quality)
    if video.get("pix_fmt"):
        args += ["-pix_fmt", video["pix_fmt"]]
    args += ["-profile:v", _profile_arg(video["codec_name"], video.get("profile"))]
    # levelは渡さない。encoderが実際の解像度・fpsを満たす最小のlevelを選ぶ。理由は
    # clipper._head_args に実測付きで書いてある(源の宣言は源自身の内容を満たしておらず、
    # そのまま渡すとGPU encoderが拒否する)。
    args += ["-c:a", "aac"]
    if audio.get("sample_rate"):
        args += ["-ar", str(audio["sample_rate"])]
    if audio.get("channels"):
        args += ["-ac", str(audio["channels"])]
    return args + [*concat.MUX_NO_OFFSET, "-f", "mpegts", str(dst)]


def _rate_value(rate: str) -> float:
    """``30/1`` 形式のfpsを比較できる値へ。分母0は0として扱う(比較にしか使わない)。"""
    numerator, _, denominator = rate.partition("/")
    denom = float(denominator or 1)
    return float(numerator) / denom if denom else 0.0


async def _frame_rate(source) -> str:
    """先頭video streamの ``r_frame_rate``(``30/1`` のような分数のまま)。

    ``avg_frame_rate`` は使わない。実物のhighlightは7本とも公称30fpsだが、``avg_frame_rate``
    は ``30/1`` と ``135250000/4508333`` のように本ごとに違う値で出る(尺の端数を割った結果で
    あって、素材の公称fpsではない)。あれで揃いを判定すると、揃っている素材を毎回「混在」と
    誤診する。"""
    text = await concat._probe(
        ["ffprobe", "-v", "error", *source.input_args, "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(source.path)],
        source.path)
    value = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not value or value == "0/0":
        raise RuntimeError(f"fpsを読めませんでした: {Path(source.path).name}")
    return value


async def _inspect_sources(items: list) -> tuple:
    """素材ごとのstream parameterと、揃っていない項目を返す。``(params, reasons)``。

    ``reasons`` が空でなければ混在している。**失敗させない** ―― この経路は元々全gift演出を
    再encodeするので、揃える先を1つ決めれば繋げる(module docstring)。codec・解像度・音声の
    照合は :func:`tictok.media.concat.mismatch_reasons` に任せて、判定の規則を1箇所に保つ。

    **fpsだけはこちらで見る。** ``mismatch_reasons`` はfpsを見ない ―― あちらは原本のpacketを
    そのまま複製する連結(reel)のための照合で、そこでは公称fpsが違っても各packetは自分の
    timestampを持ったまま並ぶだけである。こちらは全gift演出を焼き直すので、揃える先のfpsを
    決めずに焼くと出力がgift演出ごとに別のfpsを持つ。判定に使うのは ``r_frame_rate``
    (:func:`_frame_rate`)。"""
    params: dict = {}
    rates: dict = {}
    async with contextlib.AsyncExitStack() as stack:
        for src in dict.fromkeys(item["src"] for item in items):
            source = await stack.enter_async_context(hls_source.ffmpeg_source_async(src))
            params[src] = await concat.probe_stream_params(source)
            rates[src] = await _frame_rate(source)
    first_src = next(iter(params))
    reasons = []
    for src, other in params.items():
        if src is first_src:
            continue
        for reason in concat.mismatch_reasons(params[first_src], other):
            reasons.append(f"{first_src.name} と {src.name}: {reason}")
        if rates[src] != rates[first_src]:
            reasons.append(
                f"{first_src.name} と {src.name}: fps {rates[first_src]} と {rates[src]}")
    return params, rates, reasons


async def _verify_output(out: Path, expected: float, tolerance: float) -> dict:
    """出来上がったfileを実測する。**containerの尺は見ない**。

    ``format=duration`` は長い方のstreamの尺なので、片側のtrackだけが途中で終わった出力を
    正常に見せる(過去にrc=0のまま片側が3〜4割で終わる事故がある)。video/audio両方のpacket
    時刻を測り、どちらも期待尺に届いていることを確かめる。"""
    spans = await concat.stream_spans(out)
    video, audio = spans["video"], spans["audio"]
    if video is None or audio is None:
        raise RuntimeError(
            f"書き出した動画に{'映像' if video is None else '音声'}が入っていません"
            f"（{out.name}）。")
    measured = {"video_seconds": round(video.end, 3), "audio_seconds": round(audio.end, 3),
                "video_packets": video.packets, "audio_packets": audio.packets,
                "expected_seconds": round(expected, 3),
                "container_seconds": await _duration_seconds(out)}
    short = [label for label, span in (("映像", video), ("音声", audio))
             if span.end < expected - tolerance]
    if short:
        logger.error(
            "書き出した動画の%sが期待より短く終わっています: %s",
            "と".join(short), out.name,
            extra={"event": "highlight_export.truncated",
                   "ctx": {"output": str(out), **measured}},
        )
        raise RuntimeError(
            f"書き出した動画の{'と'.join(short)}が途中で終わっています"
            f"（期待 {expected:.2f}秒 / 映像 {video.end:.2f}秒 / 音声 {audio.end:.2f}秒）。")
    return measured


async def render_segments(items: list, out: Path, *, provenance: dict,
                          precise: bool = DEFAULT_PRECISE,
                          progress: Optional[Callable] = None) -> dict:
    """並べ終えたgift演出を1本のmp4へ書き出す。``items`` の順が**そのまま尺の順**になる。

    各要素は ``{"src": Path, "start": 秒, "end": 秒}`` (他のkeyは持ち回るだけ)。並べ替えは
    しない ―― 何を先に置くかは :func:`plan_exports` が既に決めている。

    ``provenance`` は**省略できない**。中身の素性(:func:`provenance_record`)を隣のJSONへ
    残すためで、mp4を1本作るたびに必ず1つ出る。**素性の無いmp4をこの経路から出させない**
    ―― 出来上がったmp4だけを見ても、どのhighlightの何秒からどのgiftとして切ったのかは
    判らない。実際にそれで、別人の名前を持つfileに別人のgiftが入っている7本が出た。

    ``provenance["verified"]`` が真でない(=DBと突き合わせていない)なら、出力のfile名に
    :data:`UNVERIFIED_MARK` が入っていることを要求する。逆に、検証済みの素性で印の付いた
    名前へ書くことも認めない。**名前と中身の素性がここで必ず一致する。**

    ``precise=False`` はstream copyの経路(:mod:`tictok.media.reel` と同じ)。highlightの
    GOPは実測1.0秒で、2.5秒級のgift演出では頭に無関係な場面が付くので既定では使わない
    (module docstring)。原本画質をそのまま残したい場合の口として残してある。
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。書き出しにはffmpegのinstallが必要です。")
    if not items:
        raise NoSegments("書き出すgift演出がありません。")
    _require_marked_name(out, provenance)

    out.parent.mkdir(parents=True, exist_ok=True)
    # 中間fileは合計で出力とほぼ同容量になる。出力先と同じvolumeへ置いて、空き容量の判定と
    # 実際に消費する場所を一致させる。
    workdir = Path(tempfile.mkdtemp(prefix=".hlexport_", dir=out.parent))
    total = len(items)
    parts: list = []
    try:
        params, rates, reasons = await _inspect_sources(items)
        target = _encode_target(params)
        # 揃える先のfpsは**最も細かい素材**に合わせる。粗い方へ寄せるとframeを捨てることに
        # なり、演出の一番動く数frameがそこで落ちる。
        target["fps"] = max(rates.values(), key=_rate_value)
        if reasons:
            logger.warning(
                "highlightの形式が揃っていないため %dx%d / %sfps / %sHz %dch へ正規化して"
                "繋ぎます（%s）",
                target["video"]["width"], target["video"]["height"], target["fps"],
                target["audio"]["sample_rate"], target["audio"]["channels"],
                "／".join(reasons),
                extra={"event": "highlight_export.normalized",
                       "ctx": {"output": str(out), "reasons": reasons, "target": target}},
            )
            if not precise:
                # copy経路では揃えようが無い(再encodeしない)。黙って壊れた連結を出すより、
                # 揃える経路へ切り替えたことを残して続ける。
                logger.warning(
                    "形式が揃っていないためstream copyでは繋げません。再encodeへ切り替えます",
                    extra={"event": "highlight_export.precise_forced",
                           "ctx": {"output": str(out), "reasons": reasons}},
                )
                precise = True

        codec = target["video"]["codec_name"]
        if codec not in concat.ANNEXB_FILTERS:
            raise RuntimeError(f"書き出しに対応していない映像codecです: {codec}")

        encoder = "copy"
        quality = None
        if precise:
            encoder = await _smart_encoder(codec)
            # 保存用の正規化(cq17)を借りない。あちらの入力は配信のHLSで、こちらの入力は
            # TikTokが既に1.3〜1.5Mbpsまで圧縮し終えたmp4である
            # (:func:`tictok.core.config.get_highlight_export_quality` に実測)。
            quality = _mapped_quality(encoder, config.get_highlight_export_quality())
            # 揃っている素材にはscaleを掛けない。掛けても結果は同じだが、swscaleを1段
            # 通すぶんだけ画が甘くなる余地を作る意味が無い。
            scale = _scale_filter(target) if reasons else None
            for index, item in enumerate(items):
                if progress is not None:
                    # 件数は括弧に入れる。段階名に混ぜると、jobの段階履歴がgift演出の数だけ
                    # 別々の段階として並ぶ(media_queue.stage_phase が括弧の中を落とす)。
                    await progress(f"highlightを切り出し中（{index + 1} / {total}件）",
                                   int(index * 85 / total))
                dst = workdir / f"part{index:04d}.ts"
                await concat.run(
                    _encode_part_args(item["src"], float(item["start"]),
                                      float(item["end"]), dst,
                                      target, encoder, quality, scale),
                    "highlight_export.cut_failed",
                    {"src": str(item["src"]), "start": item["start"], "end": item["end"],
                     "output": str(dst), "encoder": encoder, "quality": quality,
                     "scale": scale},
                    f'highlightの切り出しに失敗しました（{item["src"].name} '
                    f'{item["start"]:.1f}-{item["end"]:.1f}秒）',
                )
                # 自分で焼いたpartは両streamが同じ位置から始まるので前置きが無い。始点を
                # 書くとconcat demuxerがそこでseekして先頭keyframeを落とす(concat.CutPart)。
                part = await concat.window_part(dst, keep_start=True)
                parts.append(part)
                item["seconds"] = round(part.seconds, 3)
                item["lead_seconds"] = 0.0
        else:
            async with contextlib.AsyncExitStack() as stack:
                sources = {
                    src: await stack.enter_async_context(
                        hls_source.ffmpeg_source_async(src))
                    for src in dict.fromkeys(item["src"] for item in items)}
                for index, item in enumerate(items):
                    if progress is not None:
                        await progress(f"highlightを切り出し中（{index + 1} / {total}件）",
                                       int(index * 85 / total))
                    dst = workdir / f"part{index:04d}.ts"
                    cut = await concat.cut_part(
                        sources[item["src"]], float(item["start"]), float(item["end"]),
                        dst, codec, event="highlight_export.cut_failed",
                        message=f'highlightの切り出しに失敗しました（{item["src"].name} '
                                f'{item["start"]:.1f}-{item["end"]:.1f}秒）')
                    parts.append(cut)
                    item["seconds"] = round(cut.seconds, 3)
                    item["lead_seconds"] = cut.lead_seconds

        if progress is not None:
            await progress("連結中", 85)
        if len(parts) > 1:
            # 焼き上がったpartそのものを照合する。素材側の照合(``reasons``)は「揃える必要が
            # あるか」を決めるためのもので、**揃え切れたかの証明にはならない**。mp4は先頭
            # fileのcodec設定を1つだけ書くので、ここを通さないと食い違いは再生して初めて
            # 分かる(実測で48kHz monoとして鳴る出力が rc=0 で出来た)。
            await concat.check_compatible(
                {part.path: hls_source.Source(part.path, (), False, 0.0)
                 for part in parts},
                event="highlight_export.incompatible")
        await concat.concat_parts(
            parts, out, workdir / "concat.txt",
            event="highlight_export.concat_failed",
            message="highlightの連結に失敗しました")
        expected = sum(part.seconds for part in parts)
        measured = await _verify_output(
            out, expected, config.get_clip_duration_tolerance_seconds())
    except BaseException:
        out.unlink(missing_ok=True)
        # 素性だけが残ると、次に一覧を見た人が「在るはずのmp4が消えた」と読む。中身の無い
        # 素性は素性ではないので、mp4と生死を共にさせる。
        provenance_path(out).unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if not out.is_file():
        raise RuntimeError("連結は成功しましたが出力fileがありません。")
    size = out.stat().st_size
    info = {
        "path": str(out),
        "filename": out.name,
        "bytes": size,
        "parts": len(parts),
        "sources": sorted({str(item["src"]) for item in items}),
        "precise": precise,
        "encoder": encoder,
        "normalized": bool(reasons),
        "requested_seconds": round(
            sum(float(i["end"]) - float(i["start"]) for i in items), 3),
        "expected_seconds": round(expected, 3),
        "measured": measured,
        # 切った窓1つずつ。中身のgiftはid だけにする —— gift 1件ずつの記録は素性のJSONが
        # 持っており(:func:`provenance_record`)、jobの結果へ二重に積む理由が無い。
        "segments": [_cut_summary(item) for item in items],
    }
    # 素性は**出来上がったmp4を測った後**に書く。先に書くと、切り出しが途中で落ちた回の
    # 素性だけが残る。実測値(尺・packet数・容量)まで入れておくと、後から見た人はfileを
    # 開かずに「この素性はこのfileの物か」を確かめられる。
    #
    # 窓の一覧も**ここで作り直す**。計画の段(:func:`provenance_record`)では窓ごとの尺が
    # まだ無い —— 切ってみるまで判らない値なので、あの時点の素性は ``seconds`` が全部
    # NULL である。書き出したfileを通しで観る画面は窓の位置をこの尺の累計で作るので、
    # NULLのままだと**章が1つも出せない**(実測: 書き出し済み8本すべてで出せなかった)。
    info["provenance"] = _write_provenance(
        out, {**provenance, "cuts": info["segments"]}, info)
    logger.info(
        "highlightの書き出しが完了しました: %s（%dgift演出 / %.2f秒 / %s）",
        out.name, len(parts), measured["video_seconds"], encoder,
        extra={"event": "highlight_export.exported",
               "ctx": {k: v for k, v in info.items() if k != "segments"}},
    )
    if progress is not None:
        await progress("完了", 100)
    return info


# 出力へ載らなかったgiftの、載らなかった理由。**画面へそのまま出す文言**で、画面側で
# 言い換えない —— 同じ判断の説明が2箇所にあると、片方だけが更新された日に理由と実物が
# 食い違う。
MISSING_EXCLUDED = "人が出力から外しました"
MISSING_DROPPED = "再照合でこの当たりが消えました"
MISSING_UNSELECTED = "別のハイライトに在りますが、素材に選んでいません"
MISSING_UNMATCHED = "どのハイライトにも出ていません"
MISSING_OTHER_OWNER = "そのgift演出は別の人のgiftの場面です"
MISSING_UNKNOWN = "出力に選ばれませんでした"


def _missing_reason(row: Optional[dict], highlight_ids: list,
                    selected: set, owners: Optional[dict] = None) -> str:
    """1件のgiftが1本へ載らなかった理由。``row`` は照合結果の行(無ければ None)。

    **「無い」を1種類に潰さない。** 人が外したのか、再照合で消えたのか、別のハイライトに
    在るだけなのか、そもそもTikTokが選ばなかったのかは、次に打つ手がまるで違う ——
    最後の1つだけが「照合の取りこぼしを疑う」場面である。"""
    if row is not None:
        if row.get("excluded"):
            return MISSING_EXCLUDED
        if row.get("dropped"):
            return MISSING_DROPPED
        if owners is not None and not owns_segment(row, owners):
            return MISSING_OTHER_OWNER
        return MISSING_UNKNOWN
    if highlight_ids and not (set(highlight_ids) & selected):
        return MISSING_UNSELECTED
    if highlight_ids:
        return MISSING_UNKNOWN
    return MISSING_UNMATCHED


def _missing_gifts(week_gifts: list, rows: list, placed: set,
                   selected: set, owners: Optional[dict] = None) -> dict:
    """``{identity_key: [出力へ載らなかったgift, ...]}``。時刻順。

    母集団は「その週に載るはずのgift全部」
    (:meth:`tictok.store.highlights.HighlightsMixin.highlight_week_gifts`)で、単価の下限も
    週の窓もあちらが掛けてある。ここでやるのは**出力に載ったものを差し引く**ことだけで、
    載る資格の規則をここへ書き写さない。"""
    by_event: dict = {}
    for row in rows:
        event_id = row.get("gift_event_id")
        if event_id is not None:
            by_event.setdefault(event_id, row)
    out: dict = {}
    for gift in week_gifts:
        event_id = gift.get("gift_event_id")
        if event_id in placed:
            continue
        highlight_ids = list(gift.get("highlight_ids") or [])
        out.setdefault(gift.get("identity_key") or "", []).append({
            **{k: gift.get(k) for k in
               ("gift_event_id", "time", "label", "gift_id", "gift_name", "gift_count",
                "diamonds", "unit_diamonds", "gift_image", "identity_key",
                "user_nickname", "user_unique_id")},
            "highlight_ids": highlight_ids,
            "reason": _missing_reason(by_event.get(event_id), highlight_ids, selected,
                                      owners),
        })
    for gifts in out.values():
        gifts.sort(key=lambda g: (-int(g.get("diamonds") or 0), g.get("time") or 0.0))
    return out


def plan_exports(rows: list, mention: dict, *, order: str = DEFAULT_ORDER,
                 min_diamonds: Optional[int] = None, pad_lead: float = 0.0,
                 pad_tail: float = 0.0, directory: Optional[Path] = None,
                 verified: bool = True, week_gifts: Optional[list] = None) -> dict:
    """gift演出の行と週のgifter一覧から、**gifterごとに1本**の計画を作る。ffmpegは動かさない。

    ``mention`` は :meth:`tictok.store.streamers.StreamersMixin.streamer_mention_week` の
    応答そのもの。**対象を自分で決めない** —— 週の境界(土曜7時〜次の土曜7時)も閾値も名寄せも
    あちらに実装済みで、ここで書き直すと配信者画面のメンション一覧と「誰が対象か」が
    食い違う。それがこの機能で最悪の結末である。

    載せるのは ``gifters`` のうち週合計が ``post_min`` **以上**の人だけ。閾値の数字は
    応答の ``post_min`` を使い、ここには書かない。``gifters`` は下の区分(100💎以上)まで
    含んでいるので、絞り込みは必ず要る ―― 「入っていない」と思って素通しにすると、
    99💎を1回投げただけの人まで1本ずつfileになる。

    **束ねる鍵は ``identity_key`` であって表示名ではない。** 同じ人が期間の途中で表示名を
    変えれば1人が2本に割れ、別人が同じ表示名を名乗れば別人が1本に混ざる。file名に出すのは
    表示名だが、束ねるのは不変の身元である。

    file名に出す表示名は ``mention`` の行が持つもの ―― users表の最新を主に、未書き込みの列
    だけevent記録値で補うという解決規則が既にあり、gift演出が持つ ``user_nickname``
    (照合した時点の値)を使うと**画面に出ている名前とfile名が食い違う**。「その人のgift演出の
    うち最も新しいもの」を採る規則も同じ結論になる ―― 古い名前で出すと、いまその人を
    探している利用者が見つけられない。

    ``order`` は**1本の中の並び**だけを決める。fileを分ける軸はgifterで、そこは選べない。

    **1本の計画は2つの列を持つ。** ``items`` がgift 1件ずつの**記録**で、``cuts`` が実際に
    切る**窓**である(:func:`build_cuts`)。1つのgift演出に複数のgiftが乗るので、この2つは1対1に
    ならない —— 同じgift演出のHearts 6件は記録6件・窓1つで、出来上がりは1つの連続した映像に
    なる。``count`` と ``diamonds`` は**giftの数と合計**(記録の側)、``seconds`` は**窓の合計**
    である。連投があると件数と尺は比例しない。

    ``week_gifts`` はその週に**載るはずのgift全部**
    (:meth:`tictok.store.highlights.HighlightsMixin.highlight_week_gifts` の ``gifts``)。
    渡すと、1本へ載らなかったgiftが ``missing`` として各計画に付き、1件も載らなかった
    対象gifterが ``uncovered`` に並ぶ。**出来上がるfileの中身は1frameも変わらない** ——
    「無い物を人へ見せる」ためだけの列である。渡さなければ両方とも空になる(書き出しの
    実行経路は素性のJSONにこれを書かないので、渡す必要が無い)。

    ``verified`` は「この計画の行がDBの実照合結果か」。偽なら全fileの名前に
    :data:`UNVERIFIED_MARK` が入る(:func:`export_filename`)。**ここでDBは引かない** ――
    引き直して突き合わせるのは切る直前(:func:`verify_item`)で、この関数はffmpegもDBも
    触らずに「誰の何がどの名前で出るか」だけを決める役目のままにしておく。
    """
    if order not in ORDER_CHOICES:
        raise RuntimeError(f"並びの指定が不正です: {order}")
    for name, value in (("前の余白", pad_lead), ("後ろの余白", pad_tail)):
        if not 0.0 <= float(value) <= MAX_PAD_SECONDS:
            raise RuntimeError(
                f"{name}は0〜{MAX_PAD_SECONDS:.1f}秒の範囲で指定してください（{value}）。")

    chosen = select_segments(rows, min_diamonds=min_diamonds)
    post_min = int(mention.get("post_min") or 0)
    week_key = mention.get("week") or ""
    if not week_key:
        raise NoSegments("この配信者にはGiftのある週がありません。")
    week_start, week_end = _period_bounds(week_key, WEEK_SATURDAY)
    targets = {g["identity_key"]: g for g in (mention.get("gifters") or [])
               if g.get("identity_key") and int(g.get("diamonds") or 0) >= post_min}

    bundles: dict = {}
    off_target = 0
    for row in chosen["rows"]:
        key = row.get("identity_key")
        if key not in targets:
            # 週合計が下限に届かない人(または名寄せの鍵を持たないgift演出)。file にしない。
            off_target += 1
            continue
        bundles.setdefault(key, []).append(row)

    plans: list = []
    skipped: list = []
    for key, group in bundles.items():
        gifter = targets[key]
        items = [_item(row, pad_lead, pad_tail) for row in _order_rows(group, order)]
        # 実際に切る窓。**同じ人の重なる窓だけ**を1つへ畳む(:func:`build_cuts`)。畳まないと
        # 連投したgiftの数だけ同じ映像が並ぶ。畳んだ後で重なりが残っていないことも確かめる
        # —— 出来上がってから気付いても、mp4は既に出来ている。
        cuts = build_cuts(items, order)
        _assert_no_overlap(cuts)
        # gift演出が実際にいつの場面かは画面が出す。file名には使わない(名前は週の窓で名乗る)ので、
        # 録画が消えていてもここで書き出しを見送ることはしない。
        stamps = [t for t in (segment_date(item) for item in items) if t is not None]
        plans.append({
            "identity_key": key,
            "nickname": gifter.get("nickname") or "",
            "user_nickname": gifter.get("nickname") or "",
            "unique_id": gifter.get("unique_id") or "",
            "user_unique_id": gifter.get("unique_id") or "",
            "coin": int(gifter.get("diamonds") or 0),
            "rank": gifter.get("rank"),
            "start_ts": week_start,
            "end_ts": week_end,
            # 中身が実際にいつの場面かは、file名から落ちるのでここで名乗る。
            "content_start": min(stamps) if stamps else None,
            "content_end": max(stamps) if stamps else None,
            # ``items`` はgift 1件ずつの記録、``cuts`` は実際に切る窓。1対1にならない。
            "items": items,
            "cuts": cuts,
            # **件数はgiftの数**である。連投(Hearts 199💎×6)は6と数える —— 1と数えると、
            # 画面の件数も💎の合計も実際に投げられた分と合わなくなる。
            "count": len(items),
            "cut_count": len(cuts),
            "diamonds": sum(item["diamonds"] for item in items),
            # 尺は**畳んだ後の窓**の合計。件数と比例しないのは連投を畳んだからである。
            "seconds": round(sum(cut["end"] - cut["start"] for cut in cuts), 3),
            "mark": "",
            # この計画の行がDBの実照合結果か。file名の印(:data:`UNVERIFIED_MARK`)も
            # 素性のJSONの ``verified`` も、1つのこの値から出る。
            "verified": bool(verified),
        })
    # コイン額の多い人から書き出す。落ちたときに、価値の高い方から出来上がっている。
    # 1本へ載らなかったgift。**出来上がるfileの中身には触らない。** 母集団は週のgift全部で、
    # 「TikTokが選ばなかった」「人が外した」「別のハイライトに在る」を人が切り分けられる
    # ようにする —— 照合結果だけを並べると、そこに無いgiftは画面から消えてしまう。
    placed = {item["gift_event_id"] for plan in plans for item in plan["items"]
              if item.get("gift_event_id") is not None}
    selected_highlights = {row.get("highlight_id") for row in rows
                           if row.get("highlight_id") is not None}
    missing = _missing_gifts(list(week_gifts or []), rows, placed, selected_highlights,
                             segment_owners(rows))
    for plan in plans:
        gifts = missing.get(plan["identity_key"], [])
        plan["missing"] = gifts
        plan["missing_count"] = len(gifts)
        plan["missing_diamonds"] = sum(int(g.get("diamonds") or 0) for g in gifts)
    # 週合計は下限を越えているのに、1件もhighlightに出ていない人。**黙って消さない** ——
    # 「1,000💎投げた人のfileが無い」は、画面に出ていなければ誰も気付けない。
    uncovered = []
    for key, gifter in targets.items():
        if key in bundles:
            continue
        gifts = missing.get(key, [])
        uncovered.append({
            "identity_key": key,
            "nickname": gifter.get("nickname") or "",
            "unique_id": gifter.get("unique_id") or "",
            "coin": int(gifter.get("diamonds") or 0),
            "rank": gifter.get("rank"),
            "missing": gifts,
            "missing_count": len(gifts),
            "missing_diamonds": sum(int(g.get("diamonds") or 0) for g in gifts),
        })
    uncovered.sort(key=lambda g: (-g["coin"], g["identity_key"]))

    plans.sort(key=lambda p: (-p["coin"], p["identity_key"]))
    # **この順をfile名にも刻む。** coinは桁区切りを持たないので、名前の文字列順では額の順に
    # ならない(``coin14611`` が ``coin3092`` より前に来る)。folderを開いた人が並べ替えずに
    # 高い順で見られるのは、先頭のこの数字だけである。番号を振るのは名前を作る**前**で、
    # 衝突の解決もpath長の詰めも同じ番号を使う(:func:`_plan_filename`)。
    for index, plan in enumerate(plans):
        plan["position"] = index + 1
        plan["position_total"] = len(plans)

    for plan in plans:
        try:
            plan["filename"] = _plan_filename(plan)
        except NoDisplayName as exc:
            skipped.append({"identity_key": plan["identity_key"],
                            "nickname": plan["nickname"],
                            "segments": len(plan["items"]), "reason": str(exc)})
            plan["filename"] = None
    plans = [plan for plan in plans if plan["filename"]]
    _resolve_collisions(plans)
    if directory is not None:
        for plan in plans:
            _fit_path(Path(directory), plan)

    if not plans:
        raise NoSegments(
            "書き出せるgifterが居ません"
            f"（gift演出 {chosen['counts']['total']}件 / 人が除外 "
            f"{chosen['counts']['excluded']}件 / gift無し {chosen['counts']['no_gift']}件 / "
            f"{chosen['min_diamonds']}💎未満 {chosen['counts']['below_min_diamonds']}件 / "
            f"別の人の見せ場 {chosen['counts']['other_owner']}件 / "
            f"重複 {chosen['counts']['duplicated']}件 / 週合計 {post_min}💎未満の人のgift演出 "
            f"{off_target}件 / 書き出せなかった人 {len(skipped)}人）。"
            + ("" if not skipped else
               "　内訳: " + "／".join(f'{s["nickname"]}: {s["reason"]}' for s in skipped)))
    return {
        "order": order,
        "week": mention.get("week") or "",
        "week_label": f"{mention.get('start_label') or ''}〜{mention.get('end_label') or ''}",
        "post_min": post_min,
        "min_diamonds": chosen["min_diamonds"],
        "files": plans,
        "skipped": skipped,
        # 週合計は届いているのに、1本も出来ない人。**0件も結果である。**
        "uncovered": uncovered,
        "counts": {**chosen["counts"], "off_target": off_target,
                   "gifters": len(plans), "skipped": len(skipped),
                   "uncovered": len(uncovered),
                   # 1本へ載らなかったgiftの総数(対象gifterぶんだけ)。
                   "missing": sum(len(g) for key, g in missing.items()
                                  if key in targets)},
        "diamonds": sum(plan["diamonds"] for plan in plans),
        "week_start": week_start,
        "week_end": week_end,
        # 下見の応答にも出す。画面が「これは検証用の書き出しである」と名乗れる唯一の値で、
        # 製品の口(``POST /api/highlights/export``)からは常に真になる。
        "verified": bool(verified),
    }


def _fetch_segments(store, highlight_ids: list) -> list:
    """指定したhighlightを読み、**gift 1件につき1行**へ展開する。

    読み出しは :class:`tictok.store.highlights.HighlightsMixin` を必ず通す。SQLをここへ
    書き下ろすと表の変更に片方だけが追従して黙って食い違う。台帳の行(``get_highlight``)を
    別に引くのは、gift演出が素材のpathを持たないためである ―― pathはhighlight 1本に1つで、
    gift演出ごとに持たせるとfileが移ったときに直す場所がgift演出の数だけ増える。

    **展開するのは、出力の単位がgiftだからである。** 1つのgift演出は複数のgiftを持ち、それぞれ
    別人のものであり得る(実測で最後のgift演出に Galaxy 1000💎 と Spartan Helmet 399💎)。gift演出を
    単位にすると、そのgift演出は1人ぶんのfileにしか入らず**もう一方の人の見せ場が消える**。
    展開しても切り出しが増えるわけではない —— 窓は :func:`build_cuts` が畳む。

    ``excluded`` / ``dropped`` は**gift演出側とgift側の論理和**にする。gift 1件だけを外したとき
    にgift演出ごと落ちてはいけないし、gift演出を外したのに中のgiftが残ってもいけない。元の値は
    ``segment_excluded`` / ``gift_excluded`` として残す(内訳を人へ出すため)。

    giftを1件も持たないgift演出も1行だけ残す(``gift_event_id`` は None)。:func:`select_segments`
    の ``no_gift`` がその数を名乗る —— 消してしまうと、選ばれなかったgift演出が内訳から消える。

    **照合が終わっていないhighlightはここで弾く。** ``status`` が ``matched`` でない行の
    gift演出は、照合の途中(``matching``)・未着手(``new``)・失敗(``failed``)・素材が見つからない
    (``missing``)のいずれかで、どれも「いまのfileのどこから来たか」を名乗れない。下見
    (``/export/plan``)もここを通るので、**画面が予告する前に**判る。"""
    ids = [int(value) for value in highlight_ids]
    if not ids:
        raise NoSegments("highlightが指定されていません。")
    rows: list = []
    for highlight_id in ids:
        video = store.get_highlight(highlight_id)
        if video is None:
            raise RuntimeError(f"highlightの行がありません（id {highlight_id}）。")
        if video.get("status") != HIGHLIGHT_STATUS_MATCHED:
            raise NotMatched(
                f"照合が終わっていないhighlightからは書き出せません"
                f"（{video.get('filename')} / status {video.get('status')}）。"
                "先に突き合わせを実行してください。")
        for segment in store.highlight_segments(highlight_id):
            gifts = segment.get("gifts") or []
            for gift in gifts or [None]:
                rows.append(_expand_row(video, segment, gift))
    return rows


def _expand_row(video: dict, segment: dict, gift: Optional[dict]) -> dict:
    """(gift演出, gift) 1組の行。**両方の列を平らに1つへ載せる。**

    同じ名前の列が両方に在る(``id`` / ``idx`` / ``excluded`` / ``dropped``)ので、辞書を
    そのまま重ねない —— 重ねるとどちらの値が残るかが辞書の順で決まり、gift 1件を外した
    つもりでgift演出ごと落ちるような誤りが黙って入る。

    ``start`` / ``end`` は**そのgiftを切り出す範囲**である(gift演出の窓ではない)。人が窓を
    持たせていなければgift演出の窓と同じ値になるので、誰も触っていないhighlightの出力は
    1frameも変わらない。gift演出の窓そのものは ``segment_start`` / ``segment_end`` に残す ——
    切った後の照合(:func:`verify_item`)はDBのgift演出と突き合わせるので、別に要る。"""
    gift = gift or {}
    segment_start = segment.get("start")
    segment_end = segment.get("end")
    video_start = segment.get("video_start")
    video_end = segment.get("video_end")
    cut_start, cut_end = gift_cut(segment_start, segment_end, gift, video_start,
                                  video_end)
    return {
        "highlight_id": segment.get("highlight_id"),
        "segment_id": segment.get("id"),
        "segment_idx": segment.get("idx"),
        "start": cut_start, "end": cut_end,
        "segment_start": segment_start, "segment_end": segment_end,
        # 映像の切り替わりの両端。人が窓を持たせていないgiftの窓はここから来る ——
        # 素性のJSONと検証がその出所を名乗れないと、「なぜgift演出の窓とずれているのか」を
        # 後から辿れない。
        "video_start": video_start,
        "video_end": video_end,
        # **そのgiftの見せ場**。割れているgift演出では、この行の窓は他人の演出を1 frameも
        # 含まない —— 主かどうかで落とす理由がそこには無い(:func:`segment_owners`)。
        "show_start": gift.get("show_start"),
        "show_end": gift.get("show_end"),
        # 人がこのgiftだけの窓を持たせているか。素性のJSONへ残す(後から「なぜこの長さか」を
        # 辿るときに、機械が出した窓と人が詰めた窓を見分ける唯一の手掛かりになる)。
        "cut_own": bool(gift.get("cut_own")),
        "recording_id": segment.get("recording_id"),
        "media_start": segment.get("media_start"),
        "confidence": segment.get("confidence"),
        "approved": segment.get("approved"), "edited": segment.get("edited"),
        "recording": segment.get("recording"),
        # gift演出の中で検出した演出区間。**診断用**である —— giftごとの印(``has_effect``)は
        # 契約から外れた(当たりが0件で、判定に使えないと実測で判った)。
        "effect": list(segment.get("effect") or []),
        "segment_excluded": bool(segment.get("excluded")),
        "segment_dropped": bool(segment.get("dropped")),
        "gift_row_id": gift.get("id"),
        "gift_idx": gift.get("idx"),
        "gift_event_id": gift.get("gift_event_id"),
        "gift_id": gift.get("gift_id"), "gift_name": gift.get("gift_name"),
        "diamonds": gift.get("diamonds"), "gift_count": gift.get("gift_count"),
        "gift_image": gift.get("gift_image"),
        "user_unique_id": gift.get("user_unique_id"),
        "user_nickname": gift.get("user_nickname"),
        "user_id": gift.get("user_id"),
        "identity_key": gift.get("identity_key"),
        "gift_media_time": gift.get("gift_media_time"),
        "at": gift.get("at"),
        "inside": bool(gift.get("inside", True)),
        "is_primary": bool(gift.get("is_primary")),
        "manual": bool(gift.get("manual")),
        # 人がこのgiftの当たりとして選んだ1本か。重複排除(:func:`dedup_by_gift`)が
        # **他のどの順位よりも先に**読む。
        "chosen": bool(gift.get("chosen")),
        "gift_excluded": bool(gift.get("excluded")),
        "gift_dropped": bool(gift.get("dropped")),
        "excluded": bool(segment.get("excluded")) or bool(gift.get("excluded")),
        "dropped": bool(segment.get("dropped")) or bool(gift.get("dropped")),
        "unique_id": video.get("unique_id"),
        "filename": video.get("filename"),
        "path": video.get("path"),
        "highlight_duration_seconds": video.get("duration_seconds"),
    }


async def export_highlights(store, highlight_ids: list, *, week: str = "",
                            order: str = DEFAULT_ORDER,
                            min_diamonds: Optional[int] = None,
                            pad_lead: float = DEFAULT_PAD_LEAD,
                            pad_tail: float = DEFAULT_PAD_TAIL,
                            precise: bool = DEFAULT_PRECISE,
                            progress: Optional[Callable] = None,
                            verification_rows: Optional[list] = None) -> dict:
    """照合済みhighlightから、**gifterごとに1本ずつ**mp4を書き出す。

    段は4つに分かれている。読み出し(:func:`_fetch_segments` と
    ``streamer_mention_week``)・選び方と並びと名前(:func:`plan_exports`)・**素性の照合**
    (:func:`verify_items`)・書き出し(:func:`render_segments`)で、判断は全部2段目に在る。
    分かれているので、誰の何がどの名前で出るのかは素材を1 byteも読まずに確かめられる。

    **3段目が事故の後に足した段である。** 2段目は渡された行しか見ないので、行そのものが
    偽物なら計画は正しく見える。切る直前にDBを引き直して、出来上がるmp4が保存された照合
    結果と一致することを1件ずつ確かめる。

    ``verification_rows`` は**検証専用の口**で、これを渡すとDBからは読まずにその行で計画を
    組む(素性の照合も行わない)。出力のfile名には :data:`UNVERIFIED_MARK` が入り、素性の
    JSONは ``verified: false`` を名乗る。**HTTPからはここへ届かない** ――
    ``HighlightExportRequest`` は未知のfieldを弾き(``extra="forbid"``)、jobが渡すのは
    ``EXPORT_OPTION_KEYS`` の6つだけである。素材や照合の当たり方をffmpegまで通して測る
    ためのもので、成果物を作る道ではない。

    **2つの下限が別々に効く。** 混同しないこと:

    - ``min_diamonds`` は**gift 1件あたり**の下限(既定98💎)。「その1発に演出が出るか」
    - 週合計の下限(``post_min``、1,000💎)は**その人ぶんのfileを作る価値があるか**。
      199💎を10回投げた人(合計1,990)は対象で、1発も1,000に届いていなくても入る

    ``week`` はその週の土曜の日付。未指定なら ``streamer_mention_week`` が最新の週へ
    落とす ―― その規則はあちらが持っているので、ここで再現しない。

    ``store`` は生のsqlite接続ではなく、``HighlightsMixin`` と ``StreamersMixin`` を持つ
    storageである。DBの読み出しをthreadへ出すのは、この関数がevent loopの上で呼ばれる
    ためで、loop上でsqliteを叩くとその間は全画面も収集WSも止まる。

    出来上がったfileが既に在れば**上書きする**(同じ人・同じ週・同じ中身なら同じ名前に
    なるので、作り直しは同じfileを更新するのが正しい)。ただし黙っては行わず、置き換えた
    ことをlogに残す。別人が同じ名前になる場合は上書きではなく識別子で分ける
    (:func:`_resolve_collisions`)。
    """
    verified = verification_rows is None
    if verification_rows is None:
        rows = await asyncio.to_thread(_fetch_segments, store, list(highlight_ids))
    else:
        rows = list(verification_rows)
        logger.warning(
            "検証用のgift演出から書き出します。**成果物ではありません**（%d件）", len(rows),
            extra={"event": "highlight_export.verification_run",
                   "ctx": {"highlight_ids": list(highlight_ids), "rows": len(rows)}},
        )
    streamer = next((row.get("unique_id") for row in rows if row.get("unique_id")), None)
    if not streamer:
        raise NoSegments("highlightに配信者が記録されていません。")
    mention = await asyncio.to_thread(store.streamer_mention_week, streamer, week)
    directory = layout.merged_highlight_dir(streamer)
    plan = plan_exports(rows, mention, order=order, min_diamonds=min_diamonds,
                        pad_lead=pad_lead, pad_tail=pad_tail, directory=directory,
                        verified=verified)
    logger.info(
        "highlightの書き出しを開始します: %s / %s（%d人 / gift演出 %d件 / %s順）",
        streamer, plan["week"], len(plan["files"]), plan["counts"]["selected"],
        plan["order"],
        extra={"event": "highlight_export.planned",
               "ctx": {"streamer": streamer, "week": plan["week"],
                       "directory": str(directory), "verified": verified,
                       "highlight_ids": list(highlight_ids), "order": plan["order"],
                       "post_min": plan["post_min"], "min_diamonds": plan["min_diamonds"],
                       "counts": plan["counts"], "skipped": plan["skipped"],
                       "files": [p["filename"] for p in plan["files"]]}},
    )
    directory.mkdir(parents=True, exist_ok=True)

    files: list = []
    total = len(plan["files"])
    for index, entry in enumerate(plan["files"]):
        out = directory / entry["filename"]
        if out.exists():
            # 黙って消さない。同じ人・同じ週なら作り直しとして正しいが、それでも
            # 「何を置き換えたか」は残す。
            logger.warning(
                "同じ名前の書き出しが既にあるため置き換えます: %s（%d byte）",
                out.name, out.stat().st_size,
                extra={"event": "highlight_export.replaced",
                       "ctx": {"output": str(out), "bytes": out.stat().st_size,
                               "identity_key": entry["identity_key"]}},
            )
        # **切る直前にDBを引き直す。** 計画を組んでから実際に切るまでの間に、人がgift演出を
        # 外したり(``excluded``)giftを差し替えたりできる ―― 下見で見た内容と違う物が出る
        # 事故は、計画の段だけで確かめても防げない。
        if verified:
            checked = await asyncio.to_thread(
                verify_items, store, entry["items"], entry["identity_key"])
        else:
            checked = _unverified_records(entry["items"])
        # **切るのは畳んだ窓、確かめるのはgift 1件ずつ。** 記録(gift)と切り出し(窓)は
        # 1対1にならないので、両方を素性へ残す。
        info = await render_segments(
            entry["cuts"], out, precise=precise,
            provenance=provenance_record(entry, checked, streamer=streamer,
                                         plan=plan, verified=verified),
            progress=_scoped_progress(progress, index, total, entry["nickname"]))
        files.append({k: v for k, v in entry.items()
                      if k not in ("items", "cuts")} | {
            "path": info["path"], "bytes": info["bytes"], "parts": info["parts"],
            "encoder": info["encoder"], "normalized": info["normalized"],
            "measured": info["measured"], "segments": info["segments"],
            "provenance": info["provenance"],
        })
    if progress is not None:
        await progress("完了", 100)
    logger.info(
        "highlightの書き出しが完了しました: %s / %s（%d本 / %d byte）",
        streamer, plan["week"], len(files), sum(f["bytes"] for f in files),
        extra={"event": "highlight_export.exported",
               "ctx": {"streamer": streamer, "week": plan["week"],
                       "directory": str(directory),
                       "files": [{k: f[k] for k in
                                  ("filename", "nickname", "coin", "parts", "bytes")}
                                 for f in files]}},
    )
    return {
        "streamer": streamer,
        "week": plan["week"],
        "week_label": plan["week_label"],
        "directory": str(directory),
        "order": plan["order"],
        "post_min": plan["post_min"],
        "min_diamonds": plan["min_diamonds"],
        "counts": plan["counts"],
        "skipped": plan["skipped"],
        "files": files,
        "bytes": sum(f["bytes"] for f in files),
        # 製品の口からは常に真。検証用の経路(``verification_rows``)だけが偽を返す。
        "verified": verified,
    }


def _scoped_progress(progress, index: int, total: int, nickname: str):
    """1人ぶんの進捗を、全体の何%かへ均して伝える。

    ``render_segments`` は自分が0〜100だと思って報告するので、そのまま流すと画面の%が
    人数ぶん行ったり来たりする。

    **変わる値は全部1つの全角括弧の中へ入れる。** jobの段階履歴は括弧の中を落として
    段階名を作る(``media_queue.stage_phase``、正規表現は入れ子を見ない)ので、名前や件数を
    括弧の外へ出すと**人数ぶん別々の段階として履歴に並ぶ**。内側の報告が持つ括弧も
    そこで畳んでから1つに組み直す。

    先に本数を出すのは、数十本を順に作る間「何本目か」だけが進んでいる実感になるからである。
    表示名の全角括弧は半角へ寄せる ―― 括弧の入れ子は履歴の段階名を壊す。"""
    if progress is None:
        return None
    label = str(nickname or "").replace("（", "(").replace("）", ")")

    async def report(message: str, percent: int) -> None:
        base = index * 100 / total
        phase = media_queue.stage_phase(message) or message
        await progress(
            f"highlightを書き出し中（{index + 1} / {total}本目 {label} — {phase}）",
            int(min(99, base + max(0, min(100, percent)) / total)))

    return report
