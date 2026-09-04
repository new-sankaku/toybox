"""TikTok本体のhighlightを録画へ突き合わせ、gift演出ごとにgiftとgifterを割り出す。

highlightは「誰が投げたか」を持たない。こちらは同じ配信を録画し、gift eventをuser付きで
DBに持っている。**highlightが録画のどこから来たのかさえ判れば、その区間のgift eventを
引くだけでgifterが決まる。** 位置決めは音の指紋(:mod:`tictok.media.audio_fingerprint`)で
やる ―― highlightは再encode・拡大され、その上にギフト演出が重畳されているので、映像の
hashはそのどれにも弱い。

**実物のhighlightはmontageである。** ここがPOC(``scripts/highlight_poc.py`` の ``match``)
との決定的な違いで、clip全体を1つのoffsetへ当てる作りは原理的に当たらない。実測(60.8秒の
``v1c43ag5000cdab7s77og65i71rvmudg.mp4``)では、10個ほどのgift演出が**2本の録画**から繋がれて
いた。gift演出の平均は約6秒、短いものは2.5秒程度である。clip全体で当てると
votes 299 / ratio 1.4 / 相関 0.14 で不合格になる。

gift演出の境目は**音のalignmentのbase不連続からしか取れない**。映像のcut検出は使えない ――
同じ人物・同じ部屋の映像が繋がれているので ``scene`` scoreは最大0.45までしか上がらない。

段取りは5段である。

  1. **粗い走査**  highlightを :data:`COARSE_WINDOW` 秒 / :data:`COARSE_HOP` 秒刻みの窓へ
     割り、窓ごとに全候補録画へ :func:`audio_fingerprint.align` を掛ける。
  2. **roomの決定**  得票をLIVE room単位で合計し、1位のroomだけを残す(下記)。
  3. **細かい走査**  残った録画に対してだけ :data:`FINE_WINDOW` 秒 / :data:`FINE_HOP` 秒で
     もう一度走査する。2.5秒のgift演出を落とさないために窓はここまで短くする必要がある。
  4. **系列のlabeling**  窓ごとの仮説をViterbiで1本の列へ均し、``(録画, base)`` が連続する
     区間をsegmentにする。境目は :func:`_boundary` がhashの帰属の変化点で追い込む。
  5. **segmentごとの追い込みとgift**  :func:`audio_fingerprint.refine_offset` でmedia秒を
     詰め、そのmedia窓に居た**最も高額な**giftを採る。

**なぜLIVE roomで絞るのか。** 実測でぶつかった。配信者が同じ曲を別の日にも流していると、
その区間の音は2本の録画に同じ形で存在する ―― 60.8秒のhighlightの t=31.5〜37.5 で、正解の
録画1154を、6日前の録画1084が votes 159 対 70 で**上回った**。音だけでは切り分けられない
(envelopeの相関も 0.17 対 0.20 で差が無い)。映像を見れば白い服と黒い服で一目瞭然だが、
frameを引くのは高い。

構造の側に答えがある。**1本のhighlightはTikTokのLIVE replay 1本 = 配信1回から作られる。**
配信1回に対応するのは ``sessions.room_id`` である。**session ではない** ―― 接続断で1回の
配信が複数sessionに割れる(実測: pomiiiip 直近21日の25回中5回、DB全体で46 roomが複数session、
1 roomあたり最大9 session)。sessionで絞ると、montageがsessionの切れ目をまたいだときに片側の
gift演出が丸ごと落ちる。roomで絞れば、別の日の録画は候補から丸ごと消えて、同じ配信の録画は
sessionが割れていても残る。実物7本での実測(2026-09-02 / 候補32本・51.6時間)では、1位のroomが
2位の**5.4〜1214倍**の得票で決まった(倍率は ``ROOM_MARGIN`` が比べるのと同じ
``votes / max(1, runner_up)``。7本のうち2本は2位が0票で、その2本が上限側である)。
:func:`_pick_room` を参照。

**gift窓のsub-index。** 録画の指紋sidecarは**録画全体**で作る(実時間の401倍速・1本2.6MB
で、1本につき1回しか作らない)。scope="gift" の絞り込みは、cacheした ``hashes``/``times``
配列を時間でfilterするだけで作る ―― 再decodeは一切不要である。gift窓だけの指紋を別に作り
直すのは、同じ音を2度復号して2つ目のcacheを持つだけで、何も速くならない。実測
(pomiiiip 14日 = 33本 / 53.9時間 = 194,199秒 / hash 2,320万本):

  - 全gift(``min_diamonds=0``、2,098件) = 22,615秒 → 8.6倍。粗い走査 2.15秒 -> 1.28秒
  - **既定(設定値98💎、508件) = 6,221秒 → 31.2倍。粗い走査 0.84秒**
  - 1,000💎以上(63件) = 882秒 → 220倍。ただしこの線では99💎階層が丸ごと落ち、実測で
    gift演出10件中3つのgiftが消えた。下限は :func:`config.get_highlight_effect_coin_floor` が持つ。
  - 絞り込みそのものの費用は33本で **0.95秒**(再decodeなら1本17秒)

通しの所要はこれでは動かない。8〜9割はsegmentごとの演出区間(ffmpegのframe取り出し)で、
そちらはsegmentの本数で決まるからである(``timings`` を参照)。

置き場は ``<一時保存先>/<配信者>/highlights/``(:func:`tictok.core.layout.highlight_dir`)。
"""
from __future__ import annotations

import logging
import math
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

from tictok.core import config
from tictok.media import audio_fingerprint as afp
from tictok.media import highlight_switch
from tictok.media import hls_source
from tictok.record import recorder as rec
from tictok.search import indexer

logger = logging.getLogger(__name__)


# ===== 既定値 =====
# hard-codeを禁じているので、閾値・窓幅はすべてここに集約し、呼び出し側から差し替えられる
# ようにしてある。値を動かすときは、動かした理由を doc/HIGHLIGHT_MATCH.md へ残すこと。

DEFAULT_DAYS = 14.0
DEFAULT_SCOPE = "gift"
SCOPES = ("gift", "all")

# gift窓の張り方。演出はgift eventより後に出るので後ろを厚く取る。
GIFT_LEAD = 5.0
GIFT_TAIL = 15.0

# gift窓を張るgiftの下限💎は**ここに数字で持たない**。設定値
# (:func:`tictok.core.config.get_highlight_effect_coin_floor`、DB設定 > 環境変数 > 既定98)を
# 都度引く。moduleの定数や引数の既定値に書くと、設定画面で変えた値がそこを素通りする。
#
# ``min_diamonds=None``(未指定 → 設定値)と、明示の ``0``(下限なし = 全gift)は**別の意味**
# である。0を「未指定」と同じ扱いにすると、全giftを見たい呼び出しが設定値へ吸われる。

# 粗い走査。sessionを決めるためだけの段なので、窓は広く刻みは荒くてよい。
COARSE_WINDOW = 6.0
COARSE_HOP = 1.5

# 細かい走査。2.5秒のgift演出の中に窓が丸ごと収まる必要があるので、ここは短くする。
FINE_WINDOW = 2.0
FINE_HOP = 0.5

# roomの決定。1位が2位のこの倍数を超えなければ「絞れなかった」として全候補を残す。
# 黙って1位を採らないためのもので、絞れなかったことは戻り値の ``room`` に出る。
ROOM_MARGIN = 2.0

# 窓ごとの仮説として採る上限と、票の下限。偶然の一致で立つ票は実測で3〜5だが、下限を
# そこまで上げてはいけない ―― 実在する最も弱いgift演出が votes 7 だった。連続しない仮説は
# Viterbiの切り替え費用が弾くので、下限は雑音を全部消す高さでなくてよい。
HYPOTHESES_PER_WINDOW = 4
MIN_WINDOW_VOTES = 4

# 同じgift演出とみなす base のずれ。窓のまたぎで数十msずれる(実測30ms)ので、その倍以上を採る。
BASE_TOLERANCE = 0.25

# Viterbiの費用。emissionは「その窓の最良仮説に対する相対不一致」で 0〜1 に正規化してある。
# 切り替えの費用を1.0にするのは、**gift演出を1つ増やすなら窓1つぶんの完全な不一致を説明できる
# だけの得票差が要る**という意味である。0.6は「相対得票が4割を切る仮説より、どの録画でもない
# と言うほうがまし」という線。
LABEL_SWITCH_COST = 1.0
LABEL_NONE_COST = 0.6

# 境界の追い込み。粗い境界の前後をこの幅だけ取り出し、hashの帰属が入れ替わる点を採る。
BOUNDARY_SEARCH = 2.0
# 帰属を判定する時刻のずれ(frame)。指紋のframeは23.2msで、窓のまたぎで1 frame揺れる。
BOUNDARY_TOLERANCE_FRAMES = 1
# 区間に帰属の付くhashがこれだけ無ければ、境目は決められないものとして粗い位置を残す。
BOUNDARY_MIN_MARKS = 8

# これより短いsegmentはgift演出とみなさない。実測の最短が2.5秒なので、その半分を下限にする。
MIN_SEGMENT_SECONDS = 1.2

# 追い込み(refine_offset)で録画側を切り出す前後の余裕(秒)。**これは探索の幅そのもの**で、
# 広く取ってはいけない。追い込みの仕事は「指紋のframe(23.2ms)の格子を5msまで詰める」こと
# であって、位置を探し直すことではない。広く探すとenvelopeの相関は平気で別の山へ着地する
# ―― 探索幅2.0秒では2秒のgift演出で1.86秒ずれた位置を、0.30秒でも 0.17秒ずれた位置を返した。
# どちらも間違いであることはhashの帰属で確かめてある(正しいbaseの支持87本に対し、
# ずれた位置は0本)。±2 frameだけ動かせれば足りる。
REFINE_PAD = 0.05
REFINE_MAX_PROBE = 12.0

# 合否の線。POCから引き継ぐ。confidence="high" はこの3つを全部満たしたときだけ。
MIN_RATIO = 3.0
MIN_CORR = 0.5
MIN_SEGMENT_VOTES = 20

# 合否を1つの数へ直すときの目盛り(:func:`score_of`)。**線ちょうどが50**で、そこから
# 「1桁上」が100・「1桁下」が0になる。相関だけは値域が [0, 1] に決まっているので、桁では
# なく上端(1.0)を100・0を0に置く。50を割ることと ``confidence`` が "high" でないことは
# 同じ意味になる(下の :func:`_confidence` はこの数で判定している)。
SCORE_PASS = 50.0
SCORE_DECADE = 10.0
SCORE_CORR_TOP = 1.0

# gift演出1つが長すぎる線。実測(2026-09-04 / 突き合わせ済み86件のgift演出)でgift演出の長さは
# 中央値5.91秒・95%点8.22秒であり、10秒を超えたのは3件だけだった。そのうち**gifterが
# 1人しか居ない**1件(hl18 / 11.68〜22.25秒)は、繋ぎ(17.3〜18.5秒のワイプ)を跨いで2場面が
# 1つのgift演出になっていた実物である。長いgift演出そのものは正しいこともある(残る2件は
# gifterが3人・4人で、演出が続けて起きた区間だった)ので、**警告の条件は「長い」だけでは
# なく「長いのに投げた人が1人」**である。
LONG_SEGMENT_SECONDS = 10.0

# 演出区間。差分scanの解像度とfps ―― 演出は画面の広い面積を占めるので細かく見る意味は無い。
DIFF_WIDTH = 96
DIFF_HEIGHT = 171
DIFF_FPS = 5
DIFF_SHIFT = 3
# 演出とみなす閾値は**大津の方法**で採る。底を推定してから定数を足すのではなく、curveを
# 「演出の乗っていない画」と「乗っている画」の2つの山と見て、間の谷を閾値にする。
#
# **「底＋定数」を捨てたのは、底の推定が壊れていたからである。** 以前は底を中央値で採って
# いたが、highlightはgift地点だけを繋いだmontageなので**演出は素材の半分を超える**。中央値は
# 演出の台地の側へ寄り、閾値がその台地より高くなって区間が1つも出なかった —— この module の
# 以前の docstring が「実物の演出は1つも拾えない」と書いていたのはこの状態の観測である。
#
# 実測(2026-09-04 / 60.8秒の実物 ``v1c43ag5000cdab7s77og65i71rvmudg.mp4``)。以前の
# docstringが「1つも出ない」と名指しした3つが、閾値を替えるだけで**どれも出る**:
#
#   =====================  ===============  =========================
#   演出                   以前(中央値)     大津の方法
#   =====================  ===============  =========================
#   Flying Jets 5000💎     0区間            42.35〜44.95 / 45.95〜46.95
#   Fireworks 1088💎       0区間            47.42〜51.42
#   Swan 699💎             0区間            33.25〜35.45
#   閾値                   0.769            0.597
#   =====================  ===============  =========================
#
# 分ける物が2つ在るなら閾値は素材が決める。定数(sigma倍・底の何割)は1つも要らない。
#
# **見せ場を割ってよい素材かどうかの門**(:func:`_show_splits`)。差分の底(下位5%)が閾値の
# これ未満でなければ、curveが測っているのは演出ではなく**位置合わせの失敗**である ——
# highlightと録画の中身の置き方(黒帯の幅)が食い違うと、素の画面でも差分が下がらない。
# 実測20本の底/閾値: 位置の合っている10本は 0.03〜0.15、合っていない8本は 0.50〜1.15 で、
# 間は空いている。**この門は割る判断にだけ掛ける** —— :attr:`Segment.effect` は診断用なので、
# 位置が甘い素材でも「こう見えている」を出す方が人の役に立つ。
EFFECT_SPLIT_FLOOR_SHARE = 0.25
# 実物の演出は合成の重畳(6秒の定常な箱)と違って出入りがあり、全画面を覆うのは山の頂だけ
# である。1.0秒では実測の演出が1つも残らなかった。
EFFECT_MIN_SECONDS = 0.6
EFFECT_GAP_SECONDS = 0.8

# 穴(どの録画にも当たらなかった区間)を映像で埋める段。
#
# **音では埋められない。** 実測(highlight 27.0〜30.0秒 / 録画1154の同じ瞬間)で、録画側の
# 音量は rms 0.010〜0.017 ―― 配信者が喋っていない場面 ―― に対し、highlight側は 0.31〜0.67
# だった。乗っているのはTikTokが足したgiftの演出音で、**その下は無音**である。無音は無音と
# しか一致しないので、票の下限を下げても、両者の差分を取っても、この区間の票は増えない。
# 音が合ったのはその後ろの1秒(両方 rms 0.05〜0.10)だけで、それが votes 10 の2秒gift演出の正体
# である。
#
# 映像なら判る。giftのアニメは画面を覆うが配信者と背景は残るので、隣のgift演出の base を当てて
# highlightのframeと録画のframeを比べると、同じ場面のあいだ相関は保たれ、場面が変わった
# 瞬間に落ちる(実測: 同じ場面 0.34〜0.68 / 手前の繋ぎ -0.16 / 次の場面 -0.01)。
#
# **位置合わせには使わない。** 静止した配信では3秒ずらしても絵は似る(実測で同値だった)ので、
# 映像に決めさせるのは「同じ場面がどこまで続くか」だけであり、base は音で当てた隣から借りる。
# 場面の切れ目は、0.6秒ずらした自分自身との相関の谷で採る。同じ場面が続くあいだ、絵は0.6秒
# 前とよく似ている(実測7本で中央値0.83〜0.97、下から1/4でも0.72〜0.83)。繋ぎのワイプでは
# 板が滑って前後が別物になるので谷になる(実測 -0.25〜0.45)。谷に落ちるframeは実測で全体の
# 9〜14%で、これはmontageの繋ぎの数と合う。
SHOT_LAG_SECONDS = 0.6
SHOT_MIN_SIM = 0.5
# 谷がこの間隔以内で続くなら1つの繋ぎとみなす。ワイプの最中に一瞬だけ相関が戻ることがある。
SHOT_WALL_GAP_SECONDS = 0.4
# 1つの穴へ片側から伸ばせる上限。montageの1場面は実測6秒ほどなので、これを超えて「まだ同じ
# 場面」と言い続けるなら、判定の方が壊れていると見る。
EXTEND_MAX_SECONDS = 10.0
# 同じ場面に当たったgift演出が2つ居るとき、場面との重なりがこの割合を超えて競っているなら、
# どちらの場面とも言えないので伸ばさない。実測の食い違いは 2.00秒 対 0.25秒(12%)だった。
SHOT_RIVAL_SHARE = 0.4
# 壁と窓の端を比べるときの遊び。どちらも0.2秒刻みの測りから来るので、端どうしが
# 同じ点を指していても浮動小数の桁でずれる。
WALL_EPSILON = 0.05
# 両側から伸ばした後にこれ以下しか残らない穴は消す。1 frame(0.2秒)より短いgift演出は、切り出す
# 窓としても代表frameとしても意味を持たない。
EXTEND_MIN_GAP_SECONDS = 0.2

# 指紋のcache。録画1本の指紋作成は実測14秒/99分なので、1週間ぶんを何度も舐めるなら要る。
FINGERPRINT_SUFFIX = ".afp.npz"
FINGERPRINT_VERSION = 2


class HighlightMatchError(RuntimeError):
    """突き合わせが成立しなかった。素材が無い・候補が無い等、続けても意味が無い場合だけ。"""


class NoCandidates(HighlightMatchError):
    """その窓に突き合わせ先の録画が1本も無い。**窓を広げれば消える失敗である。**

    親と分けてあるのは、:func:`match_highlight` が段を広げる条件をこれ1つに絞るためである。
    ``HighlightMatchError`` をまとめて捕まえると、highlightのmp4そのものが無い場合まで段の
    数だけ再試行され、そのたびに「候補なし」というlogが出る —— 実際には素材が無いのだから、
    logの理由が事実と食い違う。"""


@dataclass
class Segment:
    """highlightの中の1つのgift演出と、それが対応する録画の位置。

    ``start``/``end`` はhighlight内の秒、``media_start`` はその先頭が対応する録画のmedia秒
    である。``recording_id`` が None のgift演出は「どの録画とも一致しなかった」で、
    scope="gift" では**giftの無いgift演出は必ずこうなる**(それが正しい結論であり、失敗ではない)。

    ``gifts`` は**このsegmentのmedia窓に入ったgiftを時刻順に全部**持つ。1件だけを持つ形
    (``gift``)から変えたのは、実物で破綻したためである ―― segmentは最長8.3秒あり、その中に
    演出を持つgiftが複数入る。実測で最後のgift演出(t=54–60)に Galaxy 1000💎(54.99s)と
    Spartan Helmet 399💎(57.43s)が入っており、画面に映っていたのは**後者**(t=59.0から兜)
    なのに、「窓の中で最も高額」の規則が範囲内の399💎を範囲外の1000💎に負けさせた。
    出力をgifterごとに1本ずつ作る以上、これは「giftが1件落ちる」だけでなく
    「別人の名前が付く」誤りになる。**成果物の単位はsegmentではなくgiftである。**

    ``gifts[i]`` の中身::

        {"event_id", "gift_id", "gift_name", "diamonds", "gift_image",
         "user_unique_id", "user_nickname", "user_id", "identity_key",
         "media_time",   # 録画のmedia秒
         "at",           # highlight内の秒。inside=False なら ``start`` より手前になる
         "inside",       # True = segmentの [start, end] の中
                         # False = ``gift_lead`` で手前へ伸ばした窓に入っただけ
         "primary"}      # True = このsegmentの主。**inside の中で**最も高額な1件。
                         #        inside が1件も無いときに限り lead窓の中で最も高額な1件

    同じ ``event_id`` が2つのsegmentに現れることはない(:func:`_assign_gifts`)。

    ``at`` は ``inside=False`` のとき ``start`` より手前を指す。**そこにhighlightの映像は
    無い**(別の時刻のgift演出が繋がっているだけ)ので、giftから切り出し範囲を作る側は
    ``[start, end]`` へclampすること。

    **giftは連投されるとその回数だけ並ぶ。** 同じ ``gift_id``・同じgifterの行が数msずつ
    離れて何件も入る(実測: Hearts 199💎 が6件、Galaxy/Swan/Fireworks が各2件)。これは
    接続の遡りによる重複**ではなく**、本当に複数回投げている ―― ``message_id`` が全部違い、
    ``fan_ticket_count`` が件数ぶんの合計になっている(6 x 199 = 1194)。**ここで畳まない。**
    記録は全件残し、映像として1本にまとめるのは出力側の「同じgifterの重なる窓を畳む」規則が
    やる(そうすると連投が起きたとおりの連続した映像になる)。

    **giftに演出の印は載せない。** 一度 ``has_effect`` を載せたが外した ―― 本物の演出
    (Fireworks 1088💎)と、演出が映っていないもの(Galaxy 1000💎)を同じ値で返すからである。
    区別できない印を画面に出すと人はそれを信じ始める。演出区間そのもの(``effect``)は
    **診断用として**残してあるが、giftの判定にも合否にも使わない(実測は :func:`_effects`)。
    """
    index: int
    start: float
    end: float
    recording_id: Optional[int]
    media_start: Optional[float]
    votes: int
    ratio: float
    corr: float
    confidence: str                     # "high" | "low" | "none"
    gifts: list = field(default_factory=list)
    effect: list = field(default_factory=list)
    # 映像の綺麗な区間(highlight自身の時間軸)。``start``/``end`` は**音**で決めた境目で、
    # montageは音を一瞬で切り替えながら映像には演出を掛ける ―― 演出は境目を跨ぐので、頭は
    # 境目より後ろ(実測で中央値0.60秒あと)、尻は境目より手前(実測で最大0.93秒手前)になる
    # (:mod:`tictok.media.highlight_switch`)。切り出しの既定の窓はこちらである。
    # **None は「測れなかった」**で、``start``/``end`` と同じ意味ではない。
    video_start: Optional[float] = None
    video_end: Optional[float] = None

    @property
    def seconds(self) -> float:
        return self.end - self.start

    @property
    def score(self) -> int:
        """当たり具合の点(:func:`score_of`)。**保存しない** —— 元になる
        ``votes``/``ratio``/``corr`` は表に在るので、点は読むたびに出せばよい。列にすると、
        目盛りを直した日に古い行だけが古い目盛りの点を名乗る。"""
        return match_score(self.votes, self.ratio, self.corr)


# ===== 候補と指紋 =====

def _source_path(recording: dict) -> Optional[Path]:
    """録画の入力path。mp4は既に消えていることが多く、実体は .ts である。無ければ None。"""
    path = Path(recording["path"])
    if path.is_file() or hls_source.has_hls_source(path):
        return path
    return None


def fingerprint_path(src: Path) -> Path:
    return rec.sidecar_path(src, FINGERPRINT_SUFFIX)


def fingerprint_of(src: Path, refresh: bool = False) -> afp.Fingerprint:
    """録画1本の指紋(**録画全体**)。sidecarへcacheし、2度目以降は読むだけにする。

    gift窓へ絞った指紋をここで作ってはいけない。sidecarは録画1本につき1回しか作らず、
    絞り込みの条件(``min_diamonds``・窓幅)は呼ぶたびに変わる。絞るのは読んだ後の配列を
    :func:`restrict_to_windows` で切るだけで済み、再decodeは要らない。"""
    cache = fingerprint_path(src)
    if cache.is_file() and not refresh:
        with np.load(cache) as data:
            if int(data["version"]) == FINGERPRINT_VERSION:
                return afp.sort_by_hash(afp.Fingerprint(
                    data["hashes"], data["times"], int(data["frames"]), int(data["peaks"])))
    started = time.time()
    with hls_source.ffmpeg_source(src) as source:
        fp = afp.fingerprint_stream(afp.decode_args(source.path, source.input_args))
    logger.info("%s の指紋を作りました（%.1f秒ぶん / %.1f秒）",
                src.stem, fp.seconds, time.time() - started)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, version=FINGERPRINT_VERSION, hashes=fp.hashes,
                        times=fp.times, frames=fp.frames, peaks=fp.peaks)
    return afp.sort_by_hash(fp)


def _query(conn, sql: str, params: Sequence) -> list:
    """列名付きのdictで返す。``conn.row_factory`` の設定を呼び出し側に要求しないため。"""
    cur = conn.execute(sql, params)
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def candidates(conn, streamer: str, days: float) -> list:
    """突き合わせ先の録画。配信者を指定しなければ全配信者を候補にする。

    実運用では「このhighlightがどの配信者のものか」は投入先のfolderで判っているので、
    配信者で絞るのが既定になる。"""
    since = time.time() - days * 86400
    # room_id を一緒に引く。候補をどの塊で絞るかの鍵はこれである(:func:`_pick_room`)。
    sql = ("select rec.*, s.room_id as room_id from recordings rec"
           " join sessions s on s.id = rec.session_id"
           " where rec.status='completed' and rec.started_at >= ?")
    if streamer:
        return _query(conn, sql + " and rec.unique_id=? order by rec.started_at",
                      (since, streamer))
    return _query(conn, sql + " order by rec.started_at", (since,))


def time_mapper(src: Path, recording: dict):
    """壁時計 -> 再生の時間軸(秒)。gift eventの秒はこれを通してしか作らない。

    自前で ``time - started_at`` を引いてはいけない。録画の時間軸は配信のmedia PTSで、
    捕捉の壁時計とは開始latency・再接続の穴のぶんずれ続ける。**尺を渡さないと media->pts が
    恒等へ落ちる**ので、``mapper_video_duration`` を通して渡すこと(mp4が実在する録画だけ尺を
    渡す、という条件込みで正しい値が出る)。"""
    return indexer.build_time_mapper_sync(
        src, recording["started_at"], recording.get("ended_at"),
        indexer.mapper_video_duration(src, recording))


# ===== gift =====

_GIFT_COLUMNS = ("id", "time", "gift_id", "gift_name", "diamonds", "gift_count", "gift_image",
                 "user_unique_id", "user_nickname", "user_id", "identity_key")


def gifts_of(conn, recording: dict, src: Path, min_diamonds: int = 0) -> list:
    """その録画の窓に居たgiftを、media秒付きで返す。

    **giftは必ずその録画自身の窓で絞る。** 1つのsessionは録画を複数本束ねる(実測で11本)ので、
    session全体からgiftを採ると別の録画のgiftが混ざり、時刻mapperが録画の終端へ丸めた位置に
    並ぶ(doc/HIGHLIGHT_MATCH.md の落とし穴)。"""
    span = float(recording.get("duration_seconds") or 0.0)
    lo = float(recording["started_at"])
    hi = float(recording.get("ended_at") or (lo + span))
    rows = _query(conn,
                  f"select {', '.join(_GIFT_COLUMNS)} from events"
                  " where session_id=? and kind='gift' and time between ? and ? order by time",
                  (recording["session_id"], lo, hi))
    to_media = time_mapper(src, recording)
    out = []
    for gift in rows:
        if (gift.get("diamonds") or 0) < min_diamonds:
            continue
        media = float(to_media(gift["time"]))
        if not 0.0 <= media <= span:
            continue
        gift["media_time"] = media
        out.append(gift)
    out.sort(key=lambda g: g["media_time"])
    return out


def gift_windows(gifts: Sequence[dict], lead: float, tail: float, span: float) -> list:
    """giftのmedia秒から、指紋を残す窓 ``[(lo, hi), ...]`` を作る。重なりは畳む。"""
    raw = sorted((max(0.0, g["media_time"] - lead), min(span, g["media_time"] + tail))
                 for g in gifts)
    merged: list = []
    for lo, hi in raw:
        if hi <= lo:
            continue
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [(a, b) for a, b in merged]


def restrict_to_windows(fp: afp.Fingerprint, windows: Sequence) -> afp.Fingerprint:
    """指紋を時間の窓へ絞る。**cacheした配列を切るだけ**で、再decodeはしない。

    窓の端を1本の昇順配列へ並べ、``searchsorted`` の落ち先の偶奇で「窓の中か」を決める。
    窓ごとにmaskを取ると窓数 x hash数になるが、これならhash数 x log(窓数)で済む
    (実測: 33本 / 833窓 / hash 2,320万本の絞り込みで 0.95秒)。"""
    if fp.hashes.size == 0:
        return fp
    if not windows:
        return fp._replace(hashes=fp.hashes[:0], times=fp.times[:0])
    edges = np.asarray([e for w in windows for e in w], dtype=np.float64) / afp.FRAME_SECONDS
    keep = (np.searchsorted(edges, fp.times, side="right") % 2) == 1
    return fp._replace(hashes=fp.hashes[keep], times=fp.times[keep])


# ===== 走査 =====

class _Candidate:
    """1本の録画と、その録画の(絞り込み済みの)指紋。"""

    def __init__(self, recording: dict, src: Path, index: afp.Fingerprint, seconds: float):
        self.recording = recording
        self.src = src
        self.index = index
        self.seconds = seconds

    @property
    def id(self) -> int:
        return int(self.recording["id"])

    @property
    def session_id(self) -> int:
        return int(self.recording["session_id"])

    @property
    def room_key(self) -> tuple:
        """候補を絞る塊の鍵。``("room", room_id)``、``room_id`` が空なら
        ``("session", session_id)``。

        空を1つの塊へまとめてはいけない ―― 中身は無関係な配信の集まりで、まとめると
        「1位のroom」が意味を失う。session_idへ黙って落とすのも禁止で、落ちたことが
        :func:`_pick_room` の戻り値に出るようにしてある。"""
        room_id = self.recording.get("room_id")
        room_id = str(room_id).strip() if room_id is not None else ""
        return ("room", room_id) if room_id else ("session", self.session_id)


def _slice_query(qfp: afp.Fingerprint, start: float, end: float) -> afp.Fingerprint:
    """highlightの指紋を時間で切る。**時刻は絶対のまま残す。**

    ここがこのmoduleの肝である。切った後も ``times`` がhighlightの先頭起点のframe番号の
    ままなので、:func:`audio_fingerprint.align` が返す ``offset_seconds`` は
    「highlightの0秒が録画の何秒か」= そのままbaseになる。窓ごとに音を切り出して指紋を
    作り直せば同じ答えは出るが、復号もspectrogramも窓の数だけ繰り返すことになる
    (実測: 60.8秒のhighlightの指紋は0.19秒。窓ごとに作ると39倍掛かる)。"""
    lo = int(round(start / afp.FRAME_SECONDS))
    hi = int(round(end / afp.FRAME_SECONDS))
    a = int(np.searchsorted(qfp.times, lo, side="left"))
    b = int(np.searchsorted(qfp.times, hi, side="left"))
    return afp.Fingerprint(qfp.hashes[a:b], qfp.times[a:b], hi - lo, 0)


def _scan(qfp: afp.Fingerprint, seconds: float, pool: Sequence[_Candidate],
          window: float, hop: float, keep: int, progress=None) -> list:
    """窓ごとに全候補へalignを掛け、上位 ``keep`` 件の仮説を返す。

    返り値は窓ごとの ``{"start", "hypotheses": [(recording_id, base, votes, ratio), ...]}``。"""
    out = []
    starts = _window_starts(seconds, window, hop)
    for i, start in enumerate(starts):
        sub = _slice_query(qfp, start, min(start + window, seconds))
        found = []
        for cand in pool:
            a = afp.align(sub, cand.index)
            if a is None or a.votes < MIN_WINDOW_VOTES:
                continue
            found.append((cand.id, a.offset_seconds, a.votes, a.ratio))
        found.sort(key=lambda h: -h[2])
        out.append({"start": start, "hypotheses": found[:keep]})
        if progress:
            progress()
    return out


def _window_starts(seconds: float, window: float, hop: float) -> list:
    """窓の開始位置。末尾は窓が入り切らなくても1つ残す ―― 落とすと最後のgift演出が消える。"""
    if seconds <= window:
        return [0.0]
    n = int(np.floor((seconds - window) / hop)) + 1
    starts = [i * hop for i in range(n)]
    if starts[-1] + window < seconds - 1e-6:
        starts.append(seconds - window)
    return starts


# ===== 系列のlabeling =====

def _cluster_bases(scans: Sequence[dict], tolerance: float) -> dict:
    """窓ごとの仮説の ``(録画, base)`` を、baseの近さでまとめて状態にする。

    baseは窓のまたぎで数十msずれるので、そのままkeyにすると同じgift演出が複数の状態へ割れる。"""
    seen: dict = {}
    for scan in scans:
        for rid, base, _votes, _ratio in scan["hypotheses"]:
            seen.setdefault(rid, []).append(base)
    table: dict = {}
    for rid, bases in seen.items():
        groups: list = []
        for base in sorted(bases):
            if groups and base - groups[-1][-1] <= tolerance:
                groups[-1].append(base)
            else:
                groups.append([base])
        table[rid] = [(g[0], g[-1], float(np.median(g))) for g in groups]
    return table


def _state_of(table: dict, rid: int, base: float):
    for i, (lo, hi, _mid) in enumerate(table.get(rid, ())):
        if lo - 1e-9 <= base <= hi + 1e-9:
            return (rid, i)
    return None


def _label(scans: Sequence[dict], table: dict, switch_cost: float, none_cost: float) -> list:
    """窓ごとの仮説を1本の列へ均す(Viterbi)。返り値は窓ごとの状態(Noneを含む)。

    窓を独立に argmax で採ると、同じ音が2か所に在る区間で列が飛ぶ。切り替えに費用を置けば
    「gift演出を1つ増やすだけの得票差があるか」で決まる ―― montageのgift演出は連続していて、
    途中で別の録画へ抜けて同じbaseへ戻ってくることは無い、という構造をそのまま費用にする。

    emissionは窓ごとに正規化する(その窓の最良仮説を0、票の無い仮説を1)。窓によって票の
    絶対数が10倍違うので、正規化しないと票の多い窓だけで列が決まる。"""
    states: list = [None]
    for rid, groups in table.items():
        states.extend((rid, i) for i in range(len(groups)))
    index = {s: i for i, s in enumerate(states)}
    order = np.arange(len(states))
    cost = np.zeros(len(states))
    back: list = []

    for scan in scans:
        votes = np.zeros(len(states))
        for rid, base, v, _ratio in scan["hypotheses"]:
            state = _state_of(table, rid, base)
            if state is not None:
                votes[index[state]] = max(votes[index[state]], v)
        best = float(votes.max())
        # 票がどこにも立たない窓では「どの録画でもない」が唯一の説明になる。
        emission = np.full(len(states), 1.0) if best <= 0 else 1.0 - votes / best
        emission[index[None]] = 0.0 if best <= 0 else none_cost

        source = int(np.argmin(cost))
        move = cost[source] + switch_cost
        stay = cost <= move
        back.append(np.where(stay, order, source))
        cost = np.where(stay, cost, move) + emission

    path = [0] * len(scans)
    here = int(np.argmin(cost))
    for i in range(len(scans) - 1, -1, -1):
        path[i] = here
        here = int(back[i][here])
    return [states[i] for i in path]


def _runs(labels: Sequence, scans: Sequence[dict], window: float, seconds: float) -> list:
    """同じ状態が続く窓をまとめ、highlight内の区間へ直す。

    窓の帰属はその**中心**で見る。窓は ``window`` 秒の幅を持つので、開始位置で切ると
    区間が窓の幅ぶん後ろへずれる。境目は隣り合う中心の中点に置き、あとで
    :func:`_boundary` が実波形で詰める。"""
    centers = [min(s["start"] + window / 2.0, seconds) for s in scans]
    runs: list = []
    for i, state in enumerate(labels):
        if runs and runs[-1]["state"] == state:
            runs[-1]["last"] = i
        else:
            runs.append({"state": state, "first": i, "last": i})
    out = []
    for k, run in enumerate(runs):
        start = 0.0 if k == 0 else (centers[runs[k - 1]["last"]] + centers[run["first"]]) / 2.0
        end = seconds if k == len(runs) - 1 else \
            (centers[run["last"]] + centers[runs[k + 1]["first"]]) / 2.0
        out.append({"state": run["state"], "start": start, "end": end,
                    "first": run["first"], "last": run["last"],
                    "center_first": centers[run["first"]], "center_last": centers[run["last"]]})
    return out


# ===== 境界の追い込み =====

def _support(query: afp.Fingerprint, db: afp.Fingerprint, base_frames: int,
             tolerance: int) -> np.ndarray:
    """queryの各hashが、``base_frames`` ずらした位置のdbで説明できるか(hashごとのbool)。

    :func:`audio_fingerprint.align` は「どのずれに票が集まるか」を出すが、ここで要るのは
    その逆 ―― **ずれは判っているので、どのhashがそれを支持しているか**である。hash1本ずつに
    帰属が付けば、境目は「支持の入れ替わる時刻」として指紋の分解能(23ms)で決まる。"""
    n = int(query.hashes.size)
    out = np.zeros(n, dtype=bool)
    if n == 0 or db.hashes.size == 0:
        return out
    lo = np.searchsorted(db.hashes, query.hashes, side="left")
    hi = np.searchsorted(db.hashes, query.hashes, side="right")
    counts = hi - lo
    counts[counts > afp.MAX_HASH_OCCURRENCES] = 0
    total = int(counts.sum())
    if total == 0:
        return out
    q_index = np.repeat(np.arange(n), counts)
    starts = np.repeat(lo, counts)
    within = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
    deltas = db.times[starts + within] - np.repeat(query.times, counts)
    hit = np.abs(deltas - base_frames) <= tolerance
    out[q_index[hit]] = True
    return out


def _boundary(qfp: afp.Fingerprint, left: dict, right: dict,
              lo: float, hi: float) -> Optional[float]:
    """2つのgift演出の境目を、hashの帰属が入れ替わる点で決める。

    粗い境目は窓の刻み(:data:`FINE_HOP`)でしか出ない。境目の前後だけを取り出し、その区間の
    hashを1本ずつ「左のgift演出でだけ説明できる」「右でだけ」「両方」「どちらでもない」に分け、
    **左だけのhashが後ろに残る数 + 右だけのhashが前に残る数**を最小にする1点を採る
    (変化点1つのsegmented regression)。両方で説明できるhash ―― 同じ音が両方の位置に在る
    ときのもの ―― は捨てるので、境目の判断には効かない。

    envelopeの相互相関で同じことをやろうとすると、両側の音をffmpegで復号し直す必要がある
    上に、実測では境目が探索範囲の端へ張り付いた(highlightにはギフト演出の音が重畳されて
    いて、波形の形が録画と揃わない)。指紋なら重畳された音は「一致しないhash」を増やすだけで、
    誤った側へ票を入れない。

    ``left``/``right`` は ``{"index": Fingerprint, "base": float}``。"""
    q = _slice_query(qfp, lo, hi)
    if q.hashes.size < BOUNDARY_MIN_MARKS:
        return None
    marks = []
    for side in (left, right):
        marks.append(_support(q, side["index"], int(round(side["base"] / afp.FRAME_SECONDS)),
                              BOUNDARY_TOLERANCE_FRAMES))
    only_left = marks[0] & ~marks[1]
    only_right = marks[1] & ~marks[0]
    if int(only_left.sum()) + int(only_right.sum()) < BOUNDARY_MIN_MARKS:
        return None
    n = q.times.size
    ca = np.concatenate(([0], np.cumsum(only_left)))
    cb = np.concatenate(([0], np.cumsum(only_right)))
    cost = (ca[n] - ca) + cb
    k = int(np.argmin(cost))
    # 切る位置は「k番目のhashの手前」。前後のhashの時刻の中点に置く。
    before = float(q.times[k - 1]) * afp.FRAME_SECONDS if k > 0 else lo
    after = float(q.times[k]) * afp.FRAME_SECONDS if k < n else hi
    return float(min(max((before + after) / 2.0, lo), hi))


# ===== 繋ぎでgift演出を割る =====

def _align_span(qfp: afp.Fingerprint, index: afp.Fingerprint,
                start: float, end: float):
    """``[start, end)`` の指紋を丸ごと当てる。票が立たなければ None。"""
    if end - start <= 0:
        return None
    found = afp.align(_slice_query(qfp, start, end), index)
    if found is None or found.votes < MIN_WINDOW_VOTES:
        return None
    return found


def _split_at_wall(qfp: afp.Fingerprint, run: dict, by_id: dict, walls: Sequence) -> list:
    """繋ぎ(壁)を跨いで1つになった run を、base の不連続で割る。

    **同じ録画の近い2箇所が繋がれると、labelingでは割れない。** 窓ごとの仮説は
    :func:`_cluster_bases` が base の近さでまとめるので、2場面の base が
    :data:`BASE_TOLERANCE` より近いと同じ状態になり、Viterbiは1本の run として通す。
    実測(2026-09-04 / hl18)がその形だった —— 11.68〜22.25秒の10.57秒が1つのgift演出として出ており、
    中は base 2604.884 の場面(〜17.62秒)と base 2604.768 の場面(18.02秒〜)の2つ、その差は
    わずか **0.116秒(指紋の5 frame)** で、間の 17.3〜18.5秒には繋ぎのワイプが在った。

    **割ってよいと言えるのは、繋ぎと base の不連続が同じ場所で揃ったときだけである。**
    繋ぎだけでは足りない —— 全画面のgift演出は :func:`_shot_walls` から見ると場面の
    切れ目と区別が付かない(実測 hl12 の21.5秒のgift演出には壁が5つ在るが、どれも両側の base が
    同一で、実際に1つの場面だった)。base の不連続だけでも足りない —— 追い込みの相関は
    探索窓の argmax を必ず返すので、合っていない位置でも値が立つ。両方を要求すれば、
    実測20本・run の中の壁22箇所のうち割れるのは hl18 の1箇所だけになる。

    判定そのものは :func:`_boundary` に任せる。両側の base が同じなら「片側だけで説明できる
    hash」が立たないので None が返り、割らない。"""
    if run["state"] is None:
        return [run]
    cand = by_id.get(run["state"][0])
    if cand is None:
        return [run]
    for a, b in walls:
        # 割った後の両側がgift演出として成り立つ壁だけを見る。端に寄った壁で割ると、
        # :data:`MIN_SEGMENT_SECONDS` に満たない欠片が出る。
        if a < run["start"] + MIN_SEGMENT_SECONDS or b > run["end"] - MIN_SEGMENT_SECONDS:
            continue
        left = _align_span(qfp, cand.index, run["start"], a)
        right = _align_span(qfp, cand.index, b, run["end"])
        if left is None or right is None:
            continue
        at = _boundary(qfp, {"index": cand.index, "base": left.offset_seconds},
                       {"index": cand.index, "base": right.offset_seconds},
                       max(run["start"], a - BOUNDARY_SEARCH),
                       min(run["end"], b + BOUNDARY_SEARCH))
        if at is None or at - run["start"] < MIN_SEGMENT_SECONDS                 or run["end"] - at < MIN_SEGMENT_SECONDS:
            continue
        halves = []
        for lo, hi in ((run["start"], at), (at, run["end"])):
            # base は**割った後の範囲で当て直す**。壁の外側だけで測った値を持ち越すと、
            # 境目に寄った側の base が壁の手前/奥の音だけで決まる。
            found = _align_span(qfp, cand.index, lo, hi)
            half = dict(run)
            half["start"], half["end"] = lo, hi
            half["base"] = found.offset_seconds if found is not None else run["base"]
            half["center_first"] = min(max(run["center_first"], lo), hi)
            half["center_last"] = max(min(run["center_last"], hi), lo)
            halves.append(half)
        logger.info(
            "繋ぎでgift演出を割りました（録画 %d / %.2f〜%.2f秒 → %.2f秒で2つ / "
            "base %.3f・%.3f）",
            cand.id, run["start"], run["end"], at, halves[0]["base"], halves[1]["base"],
            extra={"event": "highlight_match.segment_split",
                   "ctx": {"recording_id": cand.id,
                           "before": [round(run["start"], 3), round(run["end"], 3)],
                           "at": round(at, 3), "wall": [round(a, 3), round(b, 3)],
                           "bases": [round(halves[0]["base"], 3),
                                     round(halves[1]["base"], 3)]}})
        return (_split_at_wall(qfp, halves[0], by_id, walls)
                + _split_at_wall(qfp, halves[1], by_id, walls))
    return [run]


def split_runs_at_walls(qfp: afp.Fingerprint, runs: list, by_id: dict,
                        walls: Sequence) -> list:
    """繋ぎを跨いで1つになった run を全部割る。判断は :func:`_split_at_wall`。"""
    out: list = []
    for run in runs:
        out.extend(_split_at_wall(qfp, run, by_id, walls))
    return out


# ===== 追い込み =====

def _loudest_window(samples: np.ndarray, seconds: float) -> float:
    """``samples`` の中で最もよく鳴っている ``seconds`` 秒の窓の開始位置(秒)。

    窓を固定の場所(中ほど等)から採ってはいけない。**ギフトの瞬間に配信者が驚いて黙る**のは
    よくあることで、highlightはその瞬間を中心に切られている。実測では38秒のうち20秒を無音に
    した素材で、中央窓の相関が0.99から0.27へ落ち、位置が428msずれた。"""
    env = afp.envelope(samples)
    span = max(1, int(seconds * 1000.0 / afp.ENVELOPE_MS))
    if env.size <= span:
        return 0.0
    power = np.concatenate(([0.0], np.cumsum(env.astype(np.float64) ** 2)))
    energy = power[span:] - power[:-span]
    return float(np.argmax(energy)) * afp.ENVELOPE_MS / 1000.0


def _refine_base(whole: np.ndarray, start: float, end: float, base: float, pcm_at) -> tuple:
    """segmentのbaseを実波形で詰める。返り値は (base, 相関)。

    効かなかったときに粗い値を黙って返してはいけない。相関はそのまま戻し、
    :func:`_confidence` が ``MIN_CORR`` で落とす。"""
    head = int(start * afp.SAMPLE_RATE)
    tail = int(end * afp.SAMPLE_RATE)
    q_all = whole[head:tail]
    if q_all.size == 0:
        return base, 0.0
    probe = min(REFINE_MAX_PROBE, max(1.0, (end - start) * 0.6))
    at = _loudest_window(q_all, probe)
    q = q_all[int(at * afp.SAMPLE_RATE):int((at + probe) * afp.SAMPLE_RATE)]
    if q.size == 0:
        return base, 0.0
    db_start = max(0.0, base + start + at - REFINE_PAD)
    pcm = pcm_at(None, db_start, probe + 2 * REFINE_PAD)
    if pcm is None or pcm.size == 0:
        return base, 0.0
    media, corr = afp.refine_offset(q, pcm, db_start)
    # 効かなかった追い込みの位置を採ってはいけない。音の無い(あるいは演出音に覆われた)
    # gift演出では相関の山が立たず、出てくる位置は粗い位置(23ms刻み)より悪い。粗い位置を残し、
    # 相関は実測のまま返して :func:`_confidence` に落とさせる。
    if corr < MIN_CORR:
        return base, float(corr)
    return media - (start + at), float(corr)


def _score_decade(value: float, line: float) -> float:
    """線を50、線の10倍を100、線の1/10を0にする対数の目盛り(``votes``/``ratio`` 用)。

    票も比も上限の無い量なので、線からの距離は**桁**で測るほかない。差で測ると、票が
    600立つgift演出と60立つgift演出の違いが、20を割るgift演出との違いより大きく出る。"""
    if value <= 0:
        return 0.0
    span = math.log10(value / line) / math.log10(SCORE_DECADE)
    return SCORE_PASS + SCORE_PASS * max(-1.0, min(1.0, span))


def _score_bounded(value: float, line: float, top: float) -> float:
    """0を0、線を50、上端を100にする目盛り(``corr`` 用)。

    相関は値域が [0, 1] に決まっているので桁では測らない。負の相関は「合っていない」で
    あって「うんと合っていない」ではないので0で止める。"""
    if value <= 0:
        return 0.0
    if value <= line:
        return SCORE_PASS * (value / line)
    return SCORE_PASS + SCORE_PASS * min(1.0, (value - line) / (top - line))


def score_of(votes: int, ratio: float, corr: float) -> dict:
    """gift演出の当たり具合を1つの数へ。``{"score": 0〜100, "weakest": key, "parts": {...}}``。

    **意味は「3つの線のうち一番弱いものが、線からどれだけ離れているか」**である。最小を
    採るので、高い点が付くのは3つとも余裕で通ったときだけになり、**50を割ることは
    ``confidence`` が "high" でないことと同じ**になる(:func:`_confidence` はこの数で
    判定している)。丸めは切り捨てにする ―― 線を下回る値が四捨五入で50へ上がると、
    合否と点が食い違う。

    3つを平均してはいけない。票と比は同じ「baseが当たっているか」を別の角度から見た量で、
    相関だけが「5msの磨きが効いたか」という別の問いである。平均は、票と比の高さで相関の
    低さを覆い隠す ―― 実測 hl18 のgift演出(票237・比5.6・相関0.24)は平均なら62点だが、
    実際は繋ぎを跨いだ2場面が1つになったgift演出だった。

    **``weakest`` を「位置が怪しい理由」と読んではいけない。** ``votes``/``ratio`` は
    「baseが当たっているか」、``corr`` は「5msの磨きが効いたか」で、意味が違う。実測では
    segment #6 が base 516.249(正解)なのに ``corr`` −0.67 まで落ちた。位置の正誤を
    確かめたいなら :func:`_support` の支持本数を見ること ―― 正しいbaseは621本中87本が
    支持し、ずれたbaseは**0本**だった(``corr`` は探索窓のargmaxを必ず返すので、完全に
    間違った位置でも0.66〜0.70を出す)。"""
    parts = {
        "votes": _score_decade(float(votes or 0), MIN_SEGMENT_VOTES),
        "ratio": _score_decade(float(ratio or 0.0), MIN_RATIO),
        "corr": _score_bounded(float(corr or 0.0), MIN_CORR, SCORE_CORR_TOP),
    }
    weakest = min(parts, key=lambda key: parts[key])
    return {"score": int(max(0.0, min(100.0, parts[weakest]))),
            "weakest": weakest,
            "parts": {key: int(max(0.0, min(100.0, value)))
                      for key, value in parts.items()}}


def match_score(votes: int, ratio: float, corr: float) -> int:
    """:func:`score_of` の点だけ。読む側が点しか要らないときの口。"""
    return score_of(votes, ratio, corr)["score"]


def _confidence(votes: int, ratio: float, corr: float) -> str:
    """3つの線を全部満たしたときだけ ``"high"``。

    判定は :func:`score_of` の点で行う。線ちょうどが50・切り捨てなので、3つとも線に届く
    ことと点が50以上であることは同値である ―― 合否と点を別々の式で出すと、境目に居るgift演出
    だけが「点は50なのに低」という読めない形で並ぶ。

    **``"low"`` を「位置が怪しい」と読んではいけない**(理由は :func:`score_of`)。"""
    return "high" if match_score(votes, ratio, corr) >= SCORE_PASS else "low"


# ===== 演出区間 =====

def _gray_frames(path: Path, start: float, seconds: float) -> np.ndarray:
    """``start`` から ``seconds`` ぶんのgrey frameを (N, H, W) で読む。

    両側とも同じ ``fps`` と同じ ``scale`` を通す。縦横比が違っても同じ引き伸ばしが掛かる
    ので、差分の比較としては揃う。"""
    args = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-i", str(path),
            "-t", f"{seconds:.3f}",
            "-vf", f"fps={DIFF_FPS},scale={DIFF_WIDTH}:{DIFF_HEIGHT},format=gray",
            "-f", "rawvideo", "-"]
    out = subprocess.run(args, capture_output=True, check=True).stdout
    n = len(out) // (DIFF_WIDTH * DIFF_HEIGHT)
    return np.frombuffer(out[:n * DIFF_WIDTH * DIFF_HEIGHT], dtype=np.uint8) \
        .reshape(n, DIFF_HEIGHT, DIFF_WIDTH).astype(np.float32)


def rough_cut(src: Path, start: float, seconds: float, dst: Path) -> float:
    """録画の一部をstream copyでTS中間へ落とす。返り値は**中間の先頭のmedia軸の秒**。

    要求した ``start - lead`` を返してはいけない。stream copyの実際の開始は要求の直後の
    keyframeで、実測では要求より2.8秒後ろだった。さらに ``-copyts`` を付けているので中間の
    timestampはcontainer軸(media + ``media_offset``)のまま残る。0点は**中間を実測して**決める。

    0点は**映像streamではなくcontainer(format)の開始**で採る。mpegtsへstream copyすると
    音声は映像より手前のsegment境界から始まり、実測で音声が映像の2.096秒前に居た。"""
    lead = min(start, 20.0)
    with hls_source.ffmpeg_source(src) as source:
        args = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start - lead:.3f}",
                *source.input_args, "-i", str(source.path),
                "-to", f"{start + seconds + source.media_offset:.3f}", "-copyts",
                "-c", "copy", "-muxdelay", "0", "-muxpreload", "0",
                "-f", "mpegts", str(dst)]
        subprocess.run(args, check=True)
        media_offset = source.media_offset
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=start_time", "-of", "default=nw=1:nk=1", str(dst)],
        capture_output=True, text=True, check=True).stdout.strip().splitlines()
    if not probe or probe[0] in ("N/A", ""):
        raise HighlightMatchError(f"粗い中間の開始時刻が読めませんでした（{dst.name}）。")
    return float(probe[0]) - media_offset


def _normalize_frames(frames: np.ndarray) -> np.ndarray:
    """frameごとに平均0・分散1へ正規化する。

    highlightは再encodeされていて明るさもgammaも録画とは違う。生の画素差を取ると、その差が
    演出の差より大きく出て何も判らない。"""
    flat = frames.reshape(len(frames), -1)
    mean = flat.mean(axis=1, keepdims=True)
    std = flat.std(axis=1, keepdims=True)
    return (flat - mean) / np.maximum(std, 1e-6)


def _frame_diff(hi: np.ndarray, lo: np.ndarray, shift: int, n: int):
    """highlightの各frameと、録画側の**近傍frameのうち最も似ているもの**との差。

    同じ番号のframe同士を引くだけでは、動きのある場面で差分の底が上がる。5fpsの採取位相が
    両者で僅かに違うだけで、動いている被写体がそのぶんずれて写るからである。±1 frameの中の
    最小を採れば「録画のどのframeでも説明できない画素」だけが残る。演出は録画のどのframeにも
    無いので、そのまま残る。"""
    out = []
    width = 0
    for j in (-1, 0, 1):
        s = shift + j
        a = hi[max(0, s):n + min(0, s)]
        b = lo[max(0, -s):n - max(0, s)]
        m = min(len(a), len(b))
        if m < 2:
            return None
        out.append((np.abs(a[:m] - b[:m]).mean(axis=1), m))
    width = min(m for _, m in out)
    return np.min(np.stack([d[:width] for d, _ in out]), axis=0)


def _diff_curve(highlight: Path, src: Path, start: float, seconds: float,
                media_start: float, scratch: Path):
    """highlightの ``[start, start+seconds)`` と、録画の同じ場面のframe差分。"""
    scratch.parent.mkdir(parents=True, exist_ok=True)
    try:
        base = rough_cut(src, media_start, seconds, scratch)
        hi = _normalize_frames(_gray_frames(highlight, start, seconds))
        lo = _normalize_frames(_gray_frames(scratch, media_start - base, seconds))
    finally:
        scratch.unlink(missing_ok=True)
    n = min(len(hi), len(lo))
    if n < 2:
        return None
    best, shift = None, 0
    for s in range(-DIFF_SHIFT, DIFF_SHIFT + 1):
        d = _frame_diff(hi, lo, s, n)
        if d is None:
            continue
        if best is None or np.median(d) < np.median(best):
            best, shift = d, s
    return None if best is None else (best, shift)


def _spans(hot: np.ndarray, offset: float) -> list:
    """boolの列を秒の区間の列へ。短い切れ目は繋ぎ、短い区間は落とす。

    演出は出入りがあるので、1 frameの落ち込みで区間が割れる。``EFFECT_GAP_SECONDS`` 以内の
    切れ目は同じ演出として繋ぎ、``EFFECT_MIN_SECONDS`` に満たない区間は雑音として捨てる。"""
    runs: list = []
    start = None
    for i, value in enumerate(hot):
        if value and start is None:
            start = i
        elif not value and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(hot)))
    merged: list = []
    for run in runs:
        if merged and (run[0] - merged[-1][1]) <= EFFECT_GAP_SECONDS * DIFF_FPS:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return [(offset + a / DIFF_FPS, offset + b / DIFF_FPS) for a, b in merged
            if (b - a) >= EFFECT_MIN_SECONDS * DIFF_FPS]


# ===== 穴を映像で埋める =====

def _self_similarity(frames: np.ndarray, lag: int) -> np.ndarray:
    """``lag`` frame離れた自分自身との相関。場面が続いているあいだは高いままになる。

    :func:`_normalize_frames` を通した列はframeごとに平均0・分散1なので、内積を画素数で
    割ればそのまま相関である。"""
    count = len(frames) - lag
    if count <= 0:
        return np.zeros(0)
    return (frames[:count] * frames[lag:lag + count]).sum(axis=1) / frames.shape[1]


def _shot_walls(highlight: Path, seconds: float) -> list:
    """montageの繋ぎ(ワイプ)の区間。**highlightだけを見て決める。**

    録画と比べてはいけない。実測(hl2の27.75〜29.75秒の穴)で、両隣のgift演出は別の場面なのに
    録画との相関は 0.50〜0.59 と 0.51〜0.60 ―― 差 0.05 ―― でどちらとも言えなかった。
    配信者が動かない場面では、2分離れた瞬間どうしでも絵はほとんど同じだからである。
    **繋ぎだけは絵が別物になる**ので、highlightの中で完結する測り方に一本化する。"""
    lag = max(1, int(round(SHOT_LAG_SECONDS * DIFF_FPS)))
    frames = _normalize_frames(_gray_frames(highlight, 0.0, seconds))
    sim = _self_similarity(frames, lag)
    if sim.size == 0:
        return []
    # 谷のframeの時刻は、比べた2 frameの中点に置く。端に置くと壁が半lagずれる。
    times = (np.arange(sim.size) + lag / 2.0) / DIFF_FPS
    walls: list = []
    for at, value in zip(times, sim):
        if value >= SHOT_MIN_SIM:
            continue
        if walls and at - walls[-1][1] <= SHOT_WALL_GAP_SECONDS:
            walls[-1][1] = float(at)
        else:
            walls.append([float(at), float(at)])
    return [(a, b) for a, b in walls]


def shot_walls(highlight: Path, seconds: float) -> list:
    """繋ぎ(壁)を1回だけ測る口。測れなかったら空にして先へ進む。

    **1本につき1回**である。gift演出を割る段(:func:`split_runs_at_walls`)・穴を埋める段
    (:func:`_extend_gaps`)・切り替わりの検算(:func:`_guard_switch`)の3つが同じ物を見る
    必要があり、別々に測ると同じhighlightに対して食い違う壁が並ぶ。"""
    try:
        return _shot_walls(highlight, seconds)
    except (subprocess.CalledProcessError, OSError):
        logger.warning("場面の切れ目が測れませんでした（%s）", Path(highlight).name,
                       exc_info=True)
        return []


def _shots(walls: Sequence, seconds: float) -> list:
    """繋ぎ(壁)で区切った場面の列。壁の外側どうしが1つの場面である。"""
    out: list = []
    at = 0.0
    for a, b in walls:
        if a > at:
            out.append((at, a))
        at = max(at, b)
    if at < seconds:
        out.append((at, seconds))
    return out


def _overlap(span: tuple, other: tuple) -> float:
    return max(0.0, min(span[1], other[1]) - max(span[0], other[0]))


def _home_shot(shots: Sequence, span: tuple) -> Optional[tuple]:
    """そのgift演出が**最も長く居る**場面。どの場面とも重ならなければ None。

    **端で決めてはいけない。** 音の境目は場面の切れ目より中央値0.60秒あとなので、gift演出の端は
    次の場面へはみ出していることがある。端の居場所で決めると、はみ出した0.65秒だけを根拠に
    隣の場面をまるごと持って行く —— 実測で Strong Finish のgift演出が、次の場面(4.13秒)を吸収して
    5.57秒から10.61秒になり、後半4秒は別の場面(全画面のavatar)だった。"""
    best, score = None, 0.0
    for shot in shots:
        value = _overlap(shot, span)
        if value > score:
            best, score = shot, value
    return best


def _extend_gaps(prepared: list, walls: Sequence, seconds: float, on_done=None) -> list:
    """穴(どの録画にも当たらなかった区間)を、**同じ場面の隣のgift演出**へ吸収する。

    埋まり切った穴は消えるので、**残った物を返す**(``prepared`` の中身は直に書き換える)。

    伸ばせるのは、そのgift演出の家(:func:`_home_shot`)の中までである。家の外は、繋がって
    見えても別の場面である —— montageは無関係な時刻を繋いだ物なので、隣の場面へ伸ばすと
    「別の瞬間の映像が、このgiftの切り出しに入る」。

    穴の両隣が同じ家に居ることもある(音の境目が場面の中で切り替わった形)。そのときは
    **家との重なりが長い側**が全部を採る —— そのgift演出こそがこの場面の音を当てた本人である
    (実測 2.00秒 対 0.25秒)。重なりが競っているなら、どちらとも言えないので**伸ばさない**。"""
    shots = _shots(walls, seconds)
    for i, item in enumerate(prepared):
        if item["cand"] is not None:
            continue
        gap = item["run"]
        left = prepared[i - 1] if i > 0 and prepared[i - 1]["cand"] is not None else None
        right = prepared[i + 1] if i + 1 < len(prepared) \
            and prepared[i + 1]["cand"] is not None else None
        homes = [None if side is None
                 else _home_shot(shots, (side["run"]["start"], side["run"]["end"]))
                 for side in (left, right)]
        head, tail = gap["start"], gap["end"]
        if homes[0] is not None:
            head = max(gap["start"], min(gap["end"], homes[0][1],
                                         left["run"]["end"] + EXTEND_MAX_SECONDS))
        if homes[1] is not None:
            tail = min(gap["end"], max(gap["start"], homes[1][0],
                                       right["run"]["start"] - EXTEND_MAX_SECONDS))
        if head > tail:
            scores = [_overlap(home, (side["run"]["start"], side["run"]["end"]))
                      for home, side in zip(homes, (left, right))]
            if min(scores) > max(scores) * SHOT_RIVAL_SHARE:
                head, tail = gap["start"], gap["end"]
            elif scores[0] > scores[1]:
                tail = head
            else:
                head = tail
        gap["start"], gap["end"] = head, tail
        if left is not None:
            left["run"]["end"] = head
        if right is not None:
            right["run"]["start"] = tail
        if on_done is not None:
            on_done()
    return [item for item in prepared if item["cand"] is not None
            or item["run"]["end"] - item["run"]["start"] > EXTEND_MIN_GAP_SECONDS]


def _wall_within(walls: Sequence, lo: float, hi: float) -> bool:
    """``[lo, hi]`` に繋ぎ(壁)が掛かっているか。端どうしの丸め誤差ぶんだけ緩める。"""
    return any(a - WALL_EPSILON <= hi and b + WALL_EPSILON >= lo for a, b in walls)


def _guard_switch(walls: Sequence, run: dict, span: tuple) -> tuple:
    """切り替わりの測り(:mod:`highlight_switch`)を、繋ぎの裏付けが無ければ捨てる。

    あの測りは「前の場面が退き切る秒」を探すが、gift演出が画面を覆っていく途中も同じ形に
    見える。**繋ぎの無い所に切り替わりは無い** —— 実測で Future City のgift演出は27.75秒から
    始まるのに 29.10秒を「前の場面が退いた点」と答え、演出の頭を1.35秒切り落とした。同じ
    素材の他の11箇所はどれも繋ぎが裏付けたので、この線で落ちるのは演出を測った1件だけである。"""
    video_start, video_end = span
    if video_start is not None and not _wall_within(walls, run["start"], video_start):
        video_start = None
    if video_end is not None and not _wall_within(walls, video_end, run["end"]):
        video_end = None
    return video_start, video_end


def _extend_by_video(walls: Sequence, seconds: float, prepared: list, tick) -> list:
    """穴を場面の切れ目まで埋める段。判断は :func:`_extend_gaps`。"""
    gaps = [item for item in prepared if item["cand"] is None]
    if not gaps or not walls:
        return prepared
    tick("穴を映像で埋めます", add=len(gaps))
    before = [(item["run"]["start"], item["run"]["end"]) for item in prepared]
    out = _extend_gaps(prepared, walls, seconds,
                       lambda: tick("穴を映像で埋めます", done=1))
    for (start, end), item in zip(before, prepared):
        run = item["run"]
        if item["cand"] is None or (run["start"] == start and run["end"] == end):
            continue
        logger.info(
            "gift演出を場面の切れ目まで伸ばしました（録画 %d / %.2f〜%.2f秒 → %.2f〜%.2f秒）",
            item["cand"].id, start, end, run["start"], run["end"],
            extra={"event": "highlight_match.segment_extended",
                   "ctx": {"recording_id": item["cand"].id,
                           "before": [round(start, 3), round(end, 3)],
                           "after": [round(run["start"], 3), round(run["end"], 3)]}})
    # 消えた穴は、この後の段では回らない。段の総数は先に積んであるので、ここで数を合わせる
    # (合わせないと進捗が最後まで届かない)。
    if len(out) < len(prepared):
        tick("演出区間", done=len(prepared) - len(out))
    return out


def _otsu(values: np.ndarray, bins: int = 256) -> tuple:
    """2つの山を分ける閾値(大津の方法)と、その分離度 ``eta``(0〜1)。

    山が1つしか無ければ ``eta`` は0へ落ちる。閾値の当てにならなさが値で出るので、**分けて
    よい素材かどうかを呼び出し側が判断できる**。中央値や分位で底を推定する方法にはこれが
    無く、演出が素材の半分を超えたときに黙って演出側を底と呼ぶ。"""
    lo, hi = float(values.min()), float(values.max())
    if hi - lo < 1e-9:
        return hi, 0.0
    counts, edges = np.histogram(values, bins=bins, range=(lo, hi))
    weight = counts.astype(np.float64) / counts.sum()
    mids = (edges[:-1] + edges[1:]) / 2.0
    low = np.cumsum(weight)[:-1]
    high = 1.0 - low
    cumulative = np.cumsum(weight * mids)
    total = cumulative[-1]
    mean_low = np.divide(cumulative[:-1], low, out=np.zeros_like(low), where=low > 0)
    mean_high = np.divide(total - cumulative[:-1], high, out=np.zeros_like(high),
                          where=high > 0)
    between = low * high * (mean_low - mean_high) ** 2
    best = int(np.argmax(between))
    variance = float(((mids - total) ** 2 * weight).sum())
    return float(mids[best]), float(between[best] / variance) if variance > 0 else 0.0


def _effects(curves: dict) -> dict:
    """gift演出ごとの差分curveから、演出が乗っている区間を出すための閾値を決める。

    閾値は**highlight 1本ぶんのcurveをまとめて**採る(:func:`_otsu`)。gift演出単位で採ると、
    2.5秒のgift演出では5fpsで12 frameしか無く、しかも**丸ごと演出に覆われたgift演出では
    「乗っていない画」の山がそもそも無い**。底は「再encodeと拡大でどれだけ画素が動くか」と
    いうhighlight全体の性質なので、まとめて採るほうが素性がよい。

    返す ``floor`` は下位5%(素の画面の差分)である。**閾値と一対で読むこと** —— 位置合わせが
    失敗している素材ではここが下がらず、curveは演出ではなく置き方の食い違いを測っている
    (:data:`EFFECT_SPLIT_FLOOR_SHARE`)。

    区間そのものをgiftへ帰属させる規則はここには無い。**演出区間からgiftを決めてはいけない**
    —— TikTok自身のズーム/ワイプ遷移が演出と同じ大きさの差分を出すので、実測(60.8秒の実物・
    gift 47件)で当たりは0件だった。giftはgift演出のmedia窓から採る。ここで出した区間が効くのは
    「1つのgift演出に載った見せ場を数える」ところだけで、そちらは**数**しか使わない
    (:func:`_show_splits`)。"""
    if not curves:
        return {}
    pooled = np.concatenate([c for c, _shift in curves.values()])
    level, eta = _otsu(pooled)
    floor = float(np.percentile(pooled, 5))
    out = {}
    for key, (curve, shift) in curves.items():
        out[key] = {"floor": floor, "level": level, "eta": eta,
                    "peak": float(curve.max()), "shift": shift, "curve": curve}
    return out


def _show_bursts(gifts: Sequence) -> list:
    """giftを**見せ場の候補**の塊へ畳む。連投(同じ人の同じgiftが続く塊)は1つである。

    **数えるのはgiftの件数ではなく塊の数**である。実測(hl18)の ``Ramune 200💎`` ×4 は0.92秒の
    間に届いた1回の combo burst で、**画面に出る演出は1つ**だった。件数で数えると、演出の
    途中の落ち込みで4区間に割れたcurveと「4件」が一致してしまい、1つの演出を4つの見せ場へ
    割ることになる。

    畳む鍵は**同じ人・同じgift・時刻順で隣り合っていること**で、画面が連投を1行へ畳む鍵
    (``story.js`` の ``foldKey``)と同じである。隣り合っていることを要求するのは、間に別の人の
    giftが挟まればそこで演出が切り替わっているからである。"""
    out: list = []
    for gift in gifts:
        key = (gift.get("identity_key"), gift.get("gift_id"))
        if out and out[-1][0] == key:
            out[-1][1].append(gift)
            continue
        out.append((key, [gift]))
    return [group for _key, group in out]


def _show_splits(spans: Sequence, run: dict, count: int) -> list:
    """1つのgift演出を「見せ場」へ割る切れ目の秒。割れないと判断したら空を返す。

    **なぜ割るのか。** gift演出の境目は音でしか取れない(:func:`_boundary`)ので、TikTokが
    montageを切らずに繋いだ1続きの場面は1つのgift演出として出る。ところがTikTokのclientは
    全画面演出を**順番待ちで1つずつ**流すので、その1続きの中に別人の演出が何本も並ぶ ——
    実測(hl12 / 14.74〜35.69秒の20.9秒)で、4.2秒の間に飛んだ4件のgiftの演出が
    ``Lili the Leopard 6599💎`` → ``Ultra Transfer 2000💎`` → ``Starlight Sceptre 1200💎``
    → ``Forever Rosa 399💎`` の順に並んでいた。gift演出を丸ごと主の1人へ渡すと、**その人の
    1本に他人の見せ場が3つ続く**(利用者の報告)。

    **割ってよいのは、演出の数と載っているgiftの数が一致したときだけである。** 一致しない
    ときに前から詰めると、演出の途中の落ち込みで2つに割れた1つの演出を2人へ分けることに
    なる —— 実測で ``Flying Jets 5000💎`` の1つの演出が (42.35, 44.95) と (45.95, 46.95) の
    2区間に割れており、そのgift演出にgiftが2件載っていれば半分ずつ配ってしまう。数が合うことは
    「演出も落ち込みも無い」の十分条件ではないが、**手掛かりはこれしか無い**ので、合わない
    ものには手を出さない(今までどおり主の1人がgift演出を丸ごと持つ)。

    切れ目は**次の演出が出る直前の、素の画面の最後の標本**に置く。演出の頭そのものへ置くと、
    手前の見せ場の尻に次の演出が1 frame入る。ここは0.2秒(5fps)刻みの粗い位置で、
    :mod:`tictok.media.highlight_switch` が30fpsで詰め直す。"""
    if count < 2 or len(spans) != count:
        return []
    step = 1.0 / DIFF_FPS
    out = []
    edge = run["start"]
    for start, _end in spans[1:]:
        at = round(float(start) - step, 3)
        if at - edge < MIN_SEGMENT_SECONDS or run["end"] - at < MIN_SEGMENT_SECONDS:
            return []
        out.append(at)
        edge = at
    return out


def _show_order(bursts: Sequence) -> list:
    """見せ場を渡す順に並べた塊。**高額な順**である。

    TikTokのclientは全画面演出を順番待ちで流すが、その順は**届いた順ではない**。実測
    (hl12 / 4件)で ``Starlight Sceptre 1200💎`` は ``Ultra Transfer 2000💎`` より
    2.5ミリ秒**早く**届いていながら、画面には後から出た。並びは 6599 → 2000 → 1200 → 399 で
    額の降順に一致する。同じ形は別の素材にも在る —— ``Singing Mushroom 99💎`` の0.85秒後に
    届いた ``Strong Finish 6000💎`` の方が先に画面へ出ていた。

    **これは2例からの規則である。** 額の順と届いた順が大きく食い違う場面(例えば10秒離れて
    投げられた99💎と6000💎)は実測できていない。並び替えの基準を疑うときはここを見ること。
    順位付けを :func:`_mark_primary` と同じ形にしてあるのは、**主が持つ見せ場が必ず1番目に
    なる**ようにするためで、割った後も「主＝一番よく映っている人」が保たれる。

    塊の値は**中で最も高額な1件**で採る。連投の合計で採ると、安いgiftを何度も投げた塊が
    1発の高額giftを追い越す —— 順番待ちに並ぶのは1発ずつの演出である。"""
    def rank(burst):
        return (-max((g["diamonds"] or 0) for g in burst),
                min(g["media_time"] for g in burst))
    return sorted(bursts, key=rank)


def _worth_splitting(item: dict) -> bool:
    """そのgift演出を割る意味が在るか。**投げた人が2人以上のときだけ**である。

    割る目的は「別人の見せ場が1本の中で続く」ことを止めることなので、載っているのが1人
    だけなら止める物が無い。**割ってよい理由が無い所で割ると、発明した境目で人の切り出しを
    切ることになる** —— 実測(hl18)の ``Ramune 200💎`` ×4 のような1人の連投がその形で、
    curveが落ち込みで割れていれば数だけは合ってしまう。"""
    if item.get("cand") is None:
        return False
    return len({gift.get("identity_key") for gift in (item.get("gifts") or [])}) >= 2


def _split_allowed(effects: dict) -> bool:
    """このhighlightで見せ場を割ってよいか。**素の画面が素に見えているか**だけを見る。

    差分の底(:func:`_effects` の ``floor``)が閾値の :data:`EFFECT_SPLIT_FLOOR_SHARE` 未満で
    あることを求める。位置合わせが失敗している素材 —— highlightと録画で中身の置き方(黒帯の
    幅)が違う —— では素の画面でも差分が下がらず、curveの山谷は演出ではなく置き方の食い違い
    である。そこで割ると、**誰の見せ場でもない所で人の切り出しを切る**ことになる。"""
    if not effects:
        return False
    found = next(iter(effects.values()))
    level = float(found["level"])
    return level > 0 and float(found["floor"]) < level * EFFECT_SPLIT_FLOOR_SHARE


def _attach_shows(item: dict) -> None:
    """割った見せ場をgiftへ渡す。割っていないgift演出のgiftは ``show`` を持たない。

    ``show`` は **そのgiftを切り出す窓そのもの**(頭, 尻)で、映像の切り替わりを測った後の値で
    ある。台帳はこれをそのまま既定の窓として返す(:func:`tictok.store.highlights.default_cut`)
    —— 端を測れなかった側はここで見せ場の端のままにしてあり、**推測で埋めた秒は入っていない**。

    渡す順は :func:`_show_order`(高額順)で、見せ場は時間順である。"""
    pieces = item.get("pieces") or []
    gifts = item.get("gifts") or []
    for gift in gifts:
        gift["show"] = None
    bursts = _show_bursts(gifts)
    if len(pieces) < 2 or len(pieces) != len(bursts):
        return
    for burst, piece in zip(_show_order(bursts), pieces):
        video_start, video_end = piece["video"]
        show = [round(piece["start"] if video_start is None else video_start, 3),
                round(piece["end"] if video_end is None else video_end, 3)]
        # 塊の中のgiftは**全部が同じ窓**を持つ。連投は1つの演出なので、中で分けると同じ
        # 映像が同じ人のfileへ何度も入る(画面もその窓で1行へ畳む)。
        for gift in burst:
            gift["show"] = list(show)


# ===== 通し =====

def _scratch_dir() -> Path:
    path = Path(config.get_log_dir()) / "highlight_match"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _gift_view(gift: dict, base: float, inside: bool) -> dict:
    """DBのgift行を :attr:`Segment.gifts` の1件へ直す。"""
    out = {k: gift.get(k) for k in
           ("gift_id", "gift_name", "diamonds", "gift_count", "gift_image",
            "user_unique_id", "user_nickname", "user_id", "identity_key")}
    out["event_id"] = gift.get("id")
    out["media_time"] = gift["media_time"]
    out["at"] = gift["media_time"] - base
    out["inside"] = inside
    out["primary"] = False
    # そのgiftの見せ場(:func:`_attach_shows`)。gift演出を割らなかったときは None のままで、
    # **gift演出の窓と同じ意味ではない** —— 割っていないことと「窓がgift演出と同じ」ことを
    # 台帳が言い分けられるようにしてある。
    out["show"] = None
    return out


def _mark_primary(gifts: list) -> None:
    """このsegmentの主を1件だけ立てる。

    **「最も高額な1件を採る」規則は残す。** 演出を起こすのは全画面演出を持つ高額giftだけで、
    安価なgiftは小さなbannerしか出さない ―― 「一番近いgift」を採ると、演出の直前に10💎が
    挟まっただけで答えが入れ替わる(実測で6000💎が10💎に負けた)。

    **変えたのは比べる相手の範囲である。** ``inside`` が1件でもあれば、そこだけで比べる。
    ``gift_lead`` で手前へ伸ばした窓に入っただけのgiftは範囲内のgiftを押しのけられない ――
    実測で、範囲外の Galaxy 1000💎 が範囲内の Spartan Helmet 399💎 を負かし、兜の演出の区間に
    別人の名前が付いた。"""
    if not gifts:
        return
    pool = [g for g in gifts if g["inside"]] or gifts
    best = max(pool, key=lambda g: ((g["diamonds"] or 0), -g["media_time"]))
    best["primary"] = True


def _assign_gifts(prepared: Sequence[dict], gifts_of_recording: dict,
                  gift_lead: float) -> None:
    """segmentごとに ``gifts`` を割り当てる。同じgiftを2つのsegmentへ渡さない。

    2passで決める。**passA**で各segmentが自分のmedia範囲 ``[media_start, media_start + 長さ]``
    に入るgiftを取り、**passB**で ``gift_lead`` で手前へ伸ばした窓 ``[media_start - lead,
    media_start)`` のgiftのうち**まだ誰にも取られていないもの**だけを取る。

    この順序が2つを同時に保証する ―― 「範囲内」が常に「lead窓」に優先すること(passAが先)と、
    同じ ``event_id`` が二度現れないこと(取られたgiftはpassBの対象から外れる)。手前へ伸ばすのは
    **演出がgift eventより後に出る**からで、実測では演出がgiftの1〜2秒後に立ち上がる
    (Future Cityはgift 28.01sに対し演出が t≈27 から)。

    **どちらのpassも走査順は ``prepared`` の順 = segmentのindex昇順(highlightの時間順)に
    固定する。** 窓は隣り合うsegment同士で重なり得る(lead窓は特にそうだが、montageが同じ場面へ
    2度戻ればmedia範囲も重なる)ので、順序を決めないと「どちらが先に取るか」で帰属が変わる。
    時間順に走れば、窓を共有する2つのsegmentのうち**手前のsegment**が取る ―― highlightの中で
    そのgiftの演出が先に見えるのはそちらだからである。

    **giftの ``at`` はsegmentの範囲外に出る。** ``inside=False`` のgiftの ``at`` は
    ``segment.start`` より手前になるが、highlightにはその手前の映像が無い(別の時刻のgift演出が
    繋がっているだけ)。ここは範囲を返さないので、**giftから切り出し範囲を作る側が
    ``[segment.start, segment.end]`` へclampすること**を契約とする。"""
    claimed: set = set()
    for item in prepared:
        item["gifts"] = []
        if item["cand"] is None:
            continue
        rows = gifts_of_recording[item["cand"].id]
        lo = item["media_start"]
        hi = item["media_start"] + (item["run"]["end"] - item["run"]["start"])
        for gift in rows:
            if lo <= gift["media_time"] <= hi and gift.get("id") not in claimed:
                claimed.add(gift.get("id"))
                item["gifts"].append(_gift_view(gift, item["base"], True))
    for item in prepared:
        if item["cand"] is None:
            continue
        rows = gifts_of_recording[item["cand"].id]
        lo = item["media_start"] - gift_lead
        for gift in rows:
            if lo <= gift["media_time"] < item["media_start"] and gift.get("id") not in claimed:
                claimed.add(gift.get("id"))
                item["gifts"].append(_gift_view(gift, item["base"], False))
    for item in prepared:
        item["gifts"].sort(key=lambda g: g["media_time"])
        _mark_primary(item["gifts"])


def matched_recordings(result: dict) -> list:
    """その結果が**実際に当たった録画のid**。1本も無ければ空。

    「照合が空振りしたか」の判定はここ1つにする —— 段を広げるかどうか(:func:`match_highlight`)
    も、画面が「この窓では当たりませんでした」と名乗るかどうかも、同じ問いである。
    2箇所で数えると、片方だけ条件を変えた日に「広げたのに黙って空を返す」に戻る。"""
    return sorted({seg.recording_id for seg in result.get("segments") or []
                   if seg.recording_id is not None})


def match_highlight(conn, highlight: Path, streamer: str, *,
                    days: Optional[float] = None,
                    scope: str = DEFAULT_SCOPE,
                    gift_lead: float = GIFT_LEAD,
                    gift_tail: float = GIFT_TAIL,
                    min_diamonds: Optional[int] = None,
                    window: float = COARSE_WINDOW,
                    hop: float = COARSE_HOP,
                    progress: Optional[Callable] = None) -> dict:
    """highlight 1本を照合する。**候補の窓は狭い順に広げる。**

    ``days`` を渡さなければ設定の段(:func:`tictok.core.config.get_highlight_match_day_stages`、
    既定 14→30日)を狭い順に試し、**1本も当たらなかった段は捨てて次の段へ進む**。
    ``days`` を明示すればその1つだけで走る(画面から日数を指定したときの道)。

    段にしてよい理由は実測にある(2026-09-02 / pomiiiip):

    - 候補を14本→33本にしても通しは 18.0秒→19.9秒。**通しの8〜9割は候補の量と無関係**な
      「gift演出の詰め」(ffmpegでframeを出す段)で、候補に比例するのは読み込みと粗い走査だけ
      (録画1本あたり0.094秒)
    - **外れた段は1.0秒で終わる。** 当たりが無ければ詰めるgift演出も無いので、走るのは
      読み込みと走査だけである

    つまり「狭い窓で試して、外れたら広げてもう一度」は**ほぼ ただ**である。逆に最初から
    広い窓で走らせると、その日数ぶんの指紋を作る費用(実時間の401倍速)とsidecarの容量
    (1本2.3MB)だけが確実に増える。

    **窓は「今」から遡って張られる**(:func:`candidates`)ので、段を全部使っても当たらない
    ことはある —— 段の一番外より古い配信のハイライトである。そのときは黙って空を返さず、
    結果の ``scope`` が窓の実際の範囲(``window_start``/``window_end``)と試した段
    (``day_stages``)を名乗る。**「TikTokが選ばなかった」と「候補の窓の外だった」は
    別のことで、画面はその2つを言い分けられなければならない。**"""
    if days is not None:
        if not (float(days) > 0):
            raise ValueError(f"候補にする日数は正の値で指定してください: {days!r}")
        stages = (float(days),)
    else:
        stages = config.get_highlight_match_day_stages()
    # 段が空のまま進むと、1回も走らずに result が None のまま返る。既定へ落として
    # 取り繕わない —— 設定が空だと判っているのに黙って14日で走らせると、設定を直した
    # つもりの人が「効いていない」ことに気付けない。
    if not stages:
        raise HighlightMatchError(
            "照合の候補にする日数(highlight_match_day_stages)が設定されていません。")
    tried: list = []
    result = None
    for index, stage in enumerate(stages):
        last = index + 1 >= len(stages)
        try:
            result = _match_once(
                conn, highlight, streamer, days=stage, scope=scope,
                gift_lead=gift_lead, gift_tail=gift_tail, min_diamonds=min_diamonds,
                window=window, hop=hop, progress=progress,
                # **括弧を入れ子にしない。** jobの段階履歴は全角括弧の中を落として段階名を
                # 作るが、正規表現は入れ子を見ない(``media_queue.stage_phase``)。内側にも
                # 括弧が在ると畳み切れず、段の数だけ別々の段階が履歴へ並ぶ。
                stage_label=("" if len(stages) == 1
                             else f"候補 {stage:g}日 {index + 1}/{len(stages)}段目"))
        except NoCandidates:
            # **窓に録画が1本も無いのは、広げるべき合図そのものである。** ここで投げると、
            # 「しばらく配信していない配信者のhighlightを入れたら、広い段を持っているのに
            # 1段目で落ちる」になる。最後の段まで来ていれば、そのときは投げてよい。
            #
            # 捕まえるのは ``NoCandidates`` だけにする。``HighlightMatchError`` をまとめて
            # 捕まえると、highlightのmp4そのものが無い場合まで段の数だけ再試行され、その
            # たびに「候補なし」のlogが出る —— 素材が無いのだから、理由が事実と食い違う。
            tried.append(stage)
            if last:
                raise
            logger.info(
                "%s は候補 %g日に録画がありません。%g日へ広げて照合し直します",
                Path(highlight).name, stage, stages[index + 1],
                extra={"event": "highlight_match.widen",
                       "ctx": {"highlight": str(highlight), "streamer": streamer,
                               "days": stage, "next_days": stages[index + 1],
                               "reason": "候補なし"}},
            )
            continue
        tried.append(stage)
        if matched_recordings(result):
            break
        if not last:
            logger.info(
                "%s は候補 %g日では1本も当たりませんでした。%g日へ広げて照合し直します",
                Path(highlight).name, stage, stages[index + 1],
                extra={"event": "highlight_match.widen",
                       "ctx": {"highlight": str(highlight), "streamer": streamer,
                               "days": stage, "next_days": stages[index + 1],
                               "reason": "当たりなし", "pool": result["pool"],
                               "pool_hours": round(result["pool_hours"], 2)}},
            )
    # 試した段を結果へ残す。**画面が「広げても当たらなかった」と言えるのはこれだけである。**
    hits = matched_recordings(result)
    result["scope"]["day_stages"] = [float(d) for d in stages]
    result["scope"]["days_tried"] = [float(d) for d in tried]
    # **当たった録画も ``scope`` へ入れる。** 保存されるのは ``scope`` だけなので
    # (``store.highlights.save_highlight_match`` が ``scope_json`` へ書く)、ここへ
    # 入れておかないと、一覧を後から開いた人は「gift演出0件」からしか空振りを読めない ——
    # それは「gift地点でなかった」と見分けが付かない。
    result["scope"]["matched_recordings"] = hits
    result["matched_recordings"] = hits
    return result


def _match_once(conn, highlight: Path, streamer: str, *,
                days: float = DEFAULT_DAYS,
                scope: str = DEFAULT_SCOPE,
                gift_lead: float = GIFT_LEAD,
                gift_tail: float = GIFT_TAIL,
                min_diamonds: Optional[int] = None,
                window: float = COARSE_WINDOW,
                hop: float = COARSE_HOP,
                progress: Optional[Callable] = None,
                stage_label: str = "") -> dict:
    """1つの窓で1回だけ照合する。段を広げるのは :func:`match_highlight` の役目。

    highlight 1本をsegmentへ割り、segmentごとにgiftとgifterを割り出す。

    ``scope="gift"`` はgift窓だけを候補にする(``gift_lead``/``gift_tail``/``min_diamonds``
    で窓を張る)。giftの無いgift演出は ``recording_id=None`` / ``confidence="none"`` になる ――
    目的はgiftgift演出の同定なので、それが正しい結論であって失敗ではない。``scope="all"`` は
    録画全体を候補にし、gift演出がどこから来たかだけを見たいときに使う。

    ``min_diamonds`` は**gift窓を張る候補の下限**である(= 探す範囲を決める値。書き出し側の
    同名の引数は「出来上がりへ載せる下限」で別物)。``None`` なら設定値
    (:func:`tictok.core.config.get_highlight_effect_coin_floor`、既定98💎)を引く。
    **明示の ``0`` は「下限なし = 全gift」**で、未指定とは別の意味である。

    戻り値の ``scope`` には**実際に使った値**が入る。設定を変えて再照合したつもりで古い結果を
    読む、という取り違えを画面側が検出できるように、未指定を解決した後の値を入れること。

    ``window``/``hop`` は**粗い走査**の窓で、sessionを決めるためのものである。segmentへ
    割るのは :data:`FINE_WINDOW` / :data:`FINE_HOP` の細かい走査で、短いgift演出(実測2.5秒)を
    落とさないためにそちらは別に持つ。

    ``progress`` は ``progress(done, total, message)``。``total`` は段が進むほど増える
    (segmentの本数は走査を終えるまで判らない)。"""
    if scope not in SCOPES:
        raise ValueError(f"scope は {SCOPES} のいずれかです: {scope!r}")
    # 未指定なら設定値。明示の0(下限なし)と取り違えないよう ``is None`` で見る。
    if min_diamonds is None:
        min_diamonds = config.get_highlight_effect_coin_floor()
    min_diamonds = int(min_diamonds)
    started = time.time()
    highlight = Path(highlight)
    if not highlight.is_file():
        raise HighlightMatchError(f"highlightがありません: {highlight}")
    seconds = _probe_duration(highlight)

    # 候補の窓は**「今」から遡って**張られる(:func:`candidates`)。実際に張った範囲を
    # 結果へ残す —— 「当たらなかった」の理由が「窓の外の配信だった」ことは、この2つの
    # 時刻を画面が出せて初めて人に判る。
    window_end = time.time()
    window_start = window_end - float(days) * 86400.0
    rows = candidates(conn, streamer, days)
    if not rows:
        raise NoCandidates(
            f"候補の録画がありません（{streamer or 'すべての配信者'} / 直近{days:g}日）。")
    pool_hours = sum(r["duration_seconds"] or 0 for r in rows) / 3600.0

    state = {"done": 0, "total": 0}

    def tick(message: str, add: int = 0, done: int = 0):
        state["total"] += add
        state["done"] += done
        if progress:
            # 段の名乗りは**全角括弧の中**へ入れる。jobの段階履歴は括弧の中を落として
            # 段階名を作る(``media_queue.stage_phase``)ので、外へ出すと同じ段が窓の数だけ
            # 別々の段階として履歴に並ぶ。
            progress(state["done"], state["total"],
                     f"{message}（{stage_label}）" if stage_label else message)

    # --- 候補の指紋を用意する(scope="gift" ならここで窓へ絞る) ---
    tick("指紋を読み込みます", add=len(rows))
    pool: list = []
    skipped: list = []
    indexed_seconds = 0.0
    for row in rows:
        src = _source_path(row)
        if src is None:
            skipped.append({"recording_id": int(row["id"]), "reason": "素材がありません"})
            tick("指紋を読み込みます", done=1)
            continue
        fp = fingerprint_of(src)
        if scope == "gift":
            gifts = gifts_of(conn, row, src, min_diamonds)
            windows = gift_windows(gifts, gift_lead, gift_tail, fp.seconds)
            fp = restrict_to_windows(fp, windows)
            indexed_seconds += sum(b - a for a, b in windows)
        else:
            indexed_seconds += fp.seconds
        pool.append(_Candidate(row, src, fp, fp.seconds))
        tick("指紋を読み込みます", done=1)
    if not pool:
        raise NoCandidates(
            f"素材の在る候補がありません（{streamer or 'すべての配信者'} / 直近{days:g}日 / "
            f"候補 {len(rows)}本のうち素材が実在するもの 0本）。")

    qfp = afp.fingerprint_stream(afp.decode_args(highlight))

    # --- 1. 粗い走査 ---
    tick("粗い走査", add=len(_window_starts(seconds, window, hop)))
    coarse_at = time.time()
    coarse = _scan(qfp, seconds, pool, window, hop, HYPOTHESES_PER_WINDOW,
                   lambda: tick("粗い走査", done=1))
    coarse_seconds = time.time() - coarse_at

    # --- 2. roomの決定 ---
    room = _pick_room(coarse, pool)
    # 絞る先は ``recordings`` から作る。塊の鍵(``room_key``)は :func:`_pick_room` の中だけの
    # 都合で、戻り値へ出すと画面やstore層がtupleを読むことになる。
    keep = set(room["recordings"])
    shortlist = [c for c in pool if c.id in keep] if room["narrowed"] else list(pool)

    # --- 3. 細かい走査 ---
    tick("細かい走査", add=len(_window_starts(seconds, FINE_WINDOW, FINE_HOP)))
    fine_at = time.time()
    fine = _scan(qfp, seconds, shortlist, FINE_WINDOW, FINE_HOP, HYPOTHESES_PER_WINDOW,
                 lambda: tick("細かい走査", done=1))
    fine_seconds = time.time() - fine_at

    # --- 4. labeling ---
    table = _cluster_bases(fine, BASE_TOLERANCE)
    labels = _label(fine, table, LABEL_SWITCH_COST, LABEL_NONE_COST)
    runs = _runs(labels, fine, FINE_WINDOW, seconds)
    attach_bases(runs, table)

    by_id = {c.id: c for c in pool}
    # montageの繋ぎ(場面の切れ目)。**highlightだけで決まる**ので、当たったgift演出が在るかとは
    # 無関係に1回だけ測り、gift演出を割る段・穴を埋める段・切り替わりの検算が同じ物を見る。
    walls = shot_walls(highlight, seconds)
    whole = afp.decode_pcm(afp.decode_args(highlight))
    pcm_cache: dict = {}

    def pcm_at(recording_id, media_start: float, length: float):
        cand = by_id.get(recording_id) if recording_id is not None else None
        if cand is None:
            return None
        key = (cand.id, round(media_start, 3), round(length, 3))
        if key not in pcm_cache:
            with hls_source.ffmpeg_source(cand.src) as source:
                pcm_cache[key] = afp.decode_pcm(afp.decode_args(
                    source.path, source.input_args, start=max(0.0, media_start),
                    duration=length))
        return pcm_cache[key]

    # --- 5. 境界の追い込みと、繋ぎで割る段 ---
    _refine_boundaries(qfp, runs, by_id)
    # 繋ぎを跨いで1つになったgift演出を割る。**追い込みの後**である —— 割る位置は
    # :func:`_boundary` が決めるので、先に外側の境目を詰めておかないと、割った側の範囲が
    # 窓の刻みのままの端を引きずる。
    runs = split_runs_at_walls(qfp, runs, by_id, walls)

    # --- 6. segmentごとの追い込み・gift・演出 ---
    tick("segmentを詰めます", add=2 * len(runs))
    segment_at = time.time()
    segments = _build_segments(conn, highlight, seconds, qfp, runs, by_id, walls, whole,
                               pcm_at, gift_lead, min_diamonds, tick)
    segment_seconds = time.time() - segment_at

    return {"seconds": seconds, "segments": segments,
            "pool": len(pool), "pool_hours": pool_hours,
            "elapsed": time.time() - started,
            "scope": {"scope": scope, "days": days, "gift_lead": gift_lead,
                      "gift_tail": gift_tail, "min_diamonds": min_diamonds,
                      "window": window, "hop": hop,
                      "fine_window": FINE_WINDOW, "fine_hop": FINE_HOP,
                      "indexed_seconds": indexed_seconds, "streamer": streamer,
                      # 候補にした録画の窓そのもの。日数だけでは「いつからいつまでを
                      # 見たのか」が判らず、古い配信のハイライトが当たらない理由を
                      # 画面が言えない。
                      "window_start": window_start, "window_end": window_end,
                      "pool": len(pool)},
            "room": room, "skipped": skipped,
            # 段ごとの実測。``scope`` の効き目はここでしか見えない ―― gift窓へ絞ると
            # 縮むのは走査(coarse/fine)だけで、``segments`` はsegmentの本数で決まる
            # ffmpegの仕事(演出区間のframe取り出し)なので変わらない。実測では通しの
            # 8〜9割が ``segments`` である。
            "timings": {"coarse": coarse_seconds, "fine": fine_seconds,
                        "segments": segment_seconds}}


def defaults() -> dict:
    """``match_highlight`` を引数無しで呼んだときに**実際に効く**値。

    Serverが既定値を名乗る口はここ1つにする。route側が数字を書き写すと、設定画面で変えた
    値と画面が表示する既定が別々に動く。``min_diamonds`` だけは設定値なので、呼ぶたびに
    引き直す(module levelのdictにすると、設定を変えてもserverを再起動するまで古い値を
    名乗る)。"""
    # ``days`` は**1つに決まらない**(段で試す)。単数のkeyへ一番外の値を入れると、画面が
    # それを「効いている窓」として名乗り、狭い段で当たった結果まで30日で照合したように
    # 見える。単数は None にして、段そのものを ``day_stages`` で渡す。
    stages = config.get_highlight_match_day_stages()
    return {"days": None, "day_stages": [float(d) for d in stages],
            "scope": DEFAULT_SCOPE,
            "gift_lead": GIFT_LEAD, "gift_tail": GIFT_TAIL,
            "min_diamonds": config.get_highlight_effect_coin_floor(),
            "window": COARSE_WINDOW, "hop": COARSE_HOP,
            "fine_window": FINE_WINDOW, "fine_hop": FINE_HOP}


def _probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _pick_room(coarse: Sequence[dict], pool: Sequence[_Candidate]) -> dict:
    """得票をLIVE room単位で合計し、1位のroomを返す。

    **1本のhighlightはTikTokのLIVE replay 1本 = 配信1回から作られる。** 配信1回に対応するのは
    ``sessions.room_id`` であって session ではない ―― **接続断で1回の配信が複数sessionに割れる**
    (実測: pomiiiip 直近21日の25回中5回。DB全体では300 session中46 roomが複数sessionを持ち、
    1 roomあたり最大9 session)。sessionで絞ると、highlightのmontageがsessionの切れ目をまたいだ
    ときに片側のgift演出が丸ごと落ちる。

    絞る理由の方は変わらない。配信者が同じ曲を別の日にも流していると、その区間の音は2本の
    録画に同じ形で存在する ―― 実測で正解の録画1154を、6日前の録画1084が votes 159 対 70 で
    上回った(envelopeの相関も 0.17 対 0.20 で差が無く、音では切り分けられない)。塊で絞れば
    別の日の録画は候補から丸ごと消える。

    **時間の近さでまとめてはいけない。** 配信者が終了して立て直すと数分の間隔で別roomになる
    (実測: session 531/532/533 は 08-17 22:14 / 23:39 / 23:48 で全部別room)。時間で束ねると
    この3回を1回に潰す。``room_id`` はこれを正しく分ける。

    ``room_id`` が空のsession(実測5/300)は ``("session", session_id)`` を鍵にした**独立した
    塊**として扱う。他のroomへ混ぜず、session_idへ黙って落としもしない ―― 落ちたことは
    戻り値の ``label`` と ``session_id`` に出る。

    1位が2位の :data:`ROOM_MARGIN` 倍に届かなければ絞らない。黙って1位を採ると、録画して
    いない配信のhighlightを投げられたときに何かを名乗ってしまう。"""
    key_of = {c.id: c.room_key for c in pool}
    totals: dict = {}
    for scan in coarse:
        for rid, _base, votes, _ratio in scan["hypotheses"]:
            key = key_of[rid]
            totals[key] = totals.get(key, 0) + votes
    if not totals:
        return {"room_id": None, "session_id": None, "label": "", "votes": 0,
                "runner_up": 0, "narrowed": False, "recordings": [],
                "reason": "どの録画とも一致しませんでした"}
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    best_key, best_votes = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    narrowed = best_votes >= max(1, runner_up) * ROOM_MARGIN
    kind, value = best_key
    return {"room_id": value if kind == "room" else None,
            "session_id": value if kind == "session" else None,
            "label": (f"room:{value}" if kind == "room"
                      else f"session:{value}（room_id無し）"),
            "votes": best_votes, "runner_up": runner_up, "narrowed": narrowed,
            "recordings": sorted(c.id for c in pool if c.room_key == best_key),
            "reason": "" if narrowed else
                      f"1位のroomが2位の{ROOM_MARGIN}倍に届きませんでした"}


def attach_bases(runs: list, table: dict) -> None:
    """run に ``base`` を持たせる。**以後 base を引く口はここだけ**にする。

    ``table`` は窓ごとの仮説をbaseの近さでまとめた物で、群の代表値(中央値)しか持たない。
    繋ぎで割ったgift演出(:func:`_split_at_wall`)は群に無い自分だけのbaseを持つので、読む側が
    ``table[rid][group]`` を引き続けると、割った側のbaseが群の代表値へ戻ってしまう。"""
    for run in runs:
        if run["state"] is None:
            run["base"] = None
            continue
        rid, group = run["state"]
        run["base"] = table[rid][group][2]


def _refine_boundaries(qfp: afp.Fingerprint, runs: list, by_id: dict) -> None:
    """隣り合うsegmentの境目を hash の帰属で詰める。両側に録画が決まっている境目だけ。

    片側が「どの録画でもない」区間の境目は詰めない。比べる相手が無いので、そこは窓の刻みの
    ままである(戻り値の ``start``/``end`` がそう見える)。"""
    for i in range(len(runs) - 1):
        left, right = runs[i], runs[i + 1]
        if left["state"] is None or right["state"] is None:
            continue
        lo = max(left["start"], left["center_first"], left["end"] - BOUNDARY_SEARCH)
        hi = min(right["end"], right["center_last"], right["start"] + BOUNDARY_SEARCH)
        if hi <= lo:
            continue
        sides = [{"index": by_id[run["state"][0]].index, "base": run["base"]}
                 for run in (left, right)]
        at = _boundary(qfp, sides[0], sides[1], lo, hi)
        if at is None:
            continue
        left["end"] = at
        right["start"] = at


def _build_segments(conn, highlight: Path, seconds: float, qfp: afp.Fingerprint,
                    runs: list, by_id: dict, walls: Sequence, whole: np.ndarray, pcm_at,
                    gift_lead: float, min_diamonds: int, tick) -> list:
    """segmentごとに base を詰め、演出区間とgiftを付けて :class:`Segment` の列にする。"""
    scratch = _scratch_dir()
    prepared: list = []

    for run in runs:
        if run["state"] is None or run["end"] - run["start"] < MIN_SEGMENT_SECONDS:
            prepared.append({"run": run, "cand": None})
            tick("segmentを詰めます", done=1)
            continue
        cand = by_id[run["state"][0]]

        def local_pcm(_rid, media_start, length, _cand=cand):
            return pcm_at(_cand.id, media_start, length)

        base, corr = _refine_base(whole, run["start"], run["end"], run["base"],
                                  local_pcm)
        # segmentの得票は、その区間の指紋を丸ごと当て直して採る。窓ごとの票を足すと、窓が
        # 重なっているぶんだけ同じhashを何度も数えることになる。
        found = afp.align(_slice_query(qfp, run["start"], run["end"]), cand.index)
        prepared.append({"run": run, "cand": cand, "base": base, "corr": corr,
                         "votes": found.votes if found else 0,
                         "ratio": found.ratio if found else 0.0})
        tick("segmentを詰めます", done=1)

    # 音で当たったgift演出を、隣の穴へ場面の切れ目まで伸ばす。**baseを詰めた後、演出区間とgiftを
    # 付ける前**にここへ置く —— 詰め直し(:func:`_refine_base`)は音の一番大きい所を探すので、
    # 先に伸ばすと演出音を掴む。逆に、giftの帰属(:func:`_assign_gifts`)と切り出しの窓は
    # 伸ばした後の区間で決まらないと、アニメの始まりがgift演出の外に残ったままになる。
    prepared = _extend_by_video(walls, seconds, prepared, tick)

    curves: dict = {}
    for i, item in enumerate(prepared):
        cand, run = item["cand"], item["run"]
        if cand is None:
            tick("演出区間", done=1)
            continue
        media_start = item["base"] + run["start"]
        try:
            found = _diff_curve(highlight, cand.src, run["start"], run["end"] - run["start"],
                                media_start, scratch / f"rough_{uuid.uuid4().hex}.ts")
        except (subprocess.CalledProcessError, HighlightMatchError, OSError):
            logger.warning("segment %d の差分が取れませんでした（録画 %d / media %.2f秒）",
                           i, cand.id, media_start, exc_info=True)
            found = None
        if found is not None:
            curves[i] = found
        tick("演出区間", done=1)

    effects = _effects(curves)
    gifts_cache: dict = {}
    for i, item in enumerate(prepared):
        item["spans"] = (_spans(effects[i]["curve"] > effects[i]["level"], item["run"]["start"])
                         if i in effects else [])
        if item["cand"] is None:
            continue
        item["media_start"] = item["base"] + item["run"]["start"]
        if item["cand"].id not in gifts_cache:
            gifts_cache[item["cand"].id] = gifts_of(conn, item["cand"].recording,
                                                    item["cand"].src, min_diamonds)
    _assign_gifts(prepared, gifts_cache, gift_lead)

    # 1つのgift演出に順番待ちで並んだ見せ場を割る。**giftを割り当てた後**である —— 何本へ
    # 割ってよいかは、そのgift演出に何件のgiftが載ったかでしか決まらない(:func:`_show_splits`)。
    splittable = bool(effects) and _split_allowed(effects)
    for i, item in enumerate(prepared):
        item["splits"] = (_show_splits(item["spans"], item["run"],
                                       len(_show_bursts(item["gifts"])))
                          if splittable and _worth_splitting(item) else [])
        if item["splits"]:
            logger.info(
                "gift演出を見せ場へ割りました（%.2f〜%.2f秒 → %d本 / 切れ目 %s）",
                item["run"]["start"], item["run"]["end"], len(item["splits"]) + 1,
                ", ".join(f"{at:.2f}" for at in item["splits"]),
                extra={"event": "highlight_match.shows_split",
                       "ctx": {"span": [round(item["run"]["start"], 3),
                                        round(item["run"]["end"], 3)],
                               "splits": [round(at, 3) for at in item["splits"]],
                               "gifts": len(item["gifts"])}})

    # 映像の切り替わりの両端。**録画が当たっているかとは無関係**にすべてのgift演出で測る ——
    # 素材(highlightのmp4)だけを読む測定なので、当たらなかったgift演出でも切り出す窓は要る。
    # 測るのは**境目の数**で、gift演出の数ではない(境目1つが手前のgift演出の尻と後ろのgift演出の頭に
    # なる)。段の名乗りもそれに合わせる。**割った見せ場の境目もここで測る** —— 音の境目と
    # 同じ物差し(次の場面が現れ始める秒)でなければ、割った所だけ別の規則で切ることになる。
    pieces: list = []
    for index, item in enumerate(prepared):
        edges = [item["run"]["start"], *item["splits"], item["run"]["end"]]
        for lo, hi in zip(edges, edges[1:]):
            pieces.append({"owner": index, "start": lo, "end": hi})
    if len(pieces) > 1:
        # 境目が1つも無いときは名乗らない。段の履歴に「0件やった段」が並ぶと、どの段に
        # 時間がかかったかを読む側が段の数から数え直すことになる。
        tick("映像の切り替わり", add=len(pieces) - 1)
    measured = highlight_switch.video_spans(
        highlight, [(piece["start"], piece["end"]) for piece in pieces],
        on_done=lambda: tick("映像の切り替わり", done=1))
    for piece, span in zip(pieces, measured):
        piece["video"] = _guard_switch(walls, piece, span)
    for item in prepared:
        item["pieces"] = []
    for piece in pieces:
        prepared[piece["owner"]]["pieces"].append(piece)
    for item in prepared:
        _attach_shows(item)

    segments: list = []
    for item in prepared:
        video_start, video_end = item["pieces"][0]["video"][0], item["pieces"][-1]["video"][1]
        run, cand = item["run"], item["cand"]
        if cand is None:
            segments.append(Segment(index=len(segments), start=run["start"], end=run["end"],
                                    recording_id=None, media_start=None, votes=0, ratio=0.0,
                                    corr=0.0, confidence="none", gifts=[], effect=[],
                                    video_start=video_start, video_end=video_end))
            continue
        segments.append(Segment(
            index=len(segments), start=run["start"], end=run["end"], recording_id=cand.id,
            media_start=item["media_start"], votes=item["votes"], ratio=item["ratio"],
            corr=item["corr"], confidence=_confidence(item["votes"], item["ratio"],
                                                      item["corr"]),
            gifts=item["gifts"], effect=item["spans"], video_start=video_start,
            video_end=video_end))
    return segments
