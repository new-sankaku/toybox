# -*- coding: utf-8 -*-
"""
【手元のターミナルで動かす】ダブルクリックでは窓がすぐ閉じて何も見えません。
装飾の元表を1つ持ち、そこから次の2つを作り直す。

  装飾プリセットを選ぶ.html          画面（entries・fonts・埋め込みscript）
  装飾データ.json                      MARKER_CHARS / BASE_PRESET / RULES / LOOKS / SWATCH_CASES

10_実務_字幕を装飾する.py は表を持たず、隣の 装飾データ.json を読む。画面へ埋め込む写しにだけ
表を流し込むので、画面からコピーした script は JSON が無くても動く。
画面とscriptで装飾がずれないよう、2つとも同じ表から書き出す。
Resolveは不要。`python 手元で動かす/道具_装飾プリセットを生成.py` で実行する。

装飾の値は Resolve 同梱の Fusion テンプレート
（Fusion/Templates/Templates.drfx 内の165本、うち字幕用17本）から
実在する Input 名と実値を取り出して合わせてある。
"""

import ast
import io
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)   # 手元で動かす/ の1つ上（ふだん使うものが並ぶ場所）
HTML_PATH = os.path.join(ROOT, "装飾プリセットを選ぶ.html")
TOOL_PATH = os.path.join(ROOT, "Resolveで動かす", "10_実務_字幕を装飾する.py")
DATA_PATH = os.path.join(ROOT, "装飾データ.json")

# 装飾データ.json の版。読む側（3_装飾ツール.py の DATA_VERSION）と合わないと止まる。
# 表の持ち方（keyでの指し方など）を変えたら1つ上げる。値を足しただけなら上げない。
DATA_VERSION = 2   # 2 で RULES に chars（1行に載る文字数）が入った

# 行頭に置く1文字の目印。話者・感情など「よく打つもの」だけに使う。
# 見た目のプリセットは数が多く記号が尽きるので、[名前] で書く（LOOK_KEYS）。
MARKER_CHARS = "!！*＊?？>＞#＃:：$＄=＝\"”^＾_＿~〜wｗ"

# [名前] の括弧として認める組。日本語入力では [ が 「 になるため両方を受ける。
BRACKETS = [("[", "]"), ("［", "］"), ("「", "」"), ("【", "】")]

# 画面のプレビューが、Text+ の値をpxへ直すときの係数。
# measured が 0 のうちはマニュアルの記述からの推定値で、実測していない。
# Resolve で Resolveで動かす/道具_Text+の実寸と書体の字幅を測ってサンプルデータを変更する.py を実行するとここが書き換わる。
# すべて「文字の実寸（塗りの高さ）」を基準にする。emを基準にすると、書体ごとの
# em と実寸の比が測定側と描画側の両方に要り、堂々巡りになるため。
PREVIEW = OrderedDict([
    ("measured", 1),
    ("sizeToPx", 0.5309),
    ("thickToPx", 0.9690),
    ("softToPx", 0.0073),
    ("extendXToPx", 3.1395),
    ("extendYToPx", 2.7326),
    ("roundToPx", 1.3171),
    ("offsetToW", 1.0000),
])

# 書体ごとの「字面の穴の広さ」。漢字の内側の隙間に入る最大の円の半径（px）で、
# 文字の実寸を200pxに揃えて測った中央値。無理本番緊急速報展開驚 の11字が対象。
# 縁取りは字の輪郭から外へ伸びるので、漢字の内側の隙間も同じだけ埋まる。
# 隙間の半径より太い縁を引くと内側が塗り潰れる。測り方は画面側の counterRadius() と同じ。
FONT_COUNTER = {
    "HGPSoeiKakugothicUB|Regular": 4.8,
    "HGPSoeiKakupoptai|Regular": 5,
    "HGPSoeiPresenceEB|Extra-Bold": 6,
    "HGPGothicE|Regular": 8,
    "Noto Sans JP|Bold": 9,
    "Yu Gothic UI|Bold": 10,
    "Noto Sans JP Medium|Regular": 11,
    "BIZ UDPGothic|Bold": 11,
    "Meiryo|Bold": 12,
    "HGPMinchoE|Regular": 12,
    "Noto Sans JP|Regular": 13,
    "Noto Sans JP DemiLight|Regular": 13,
    "Yu Mincho Demibold|Bold": 13,
    "Noto Sans JP Black|Regular": 6,
    "HGPGyoshotai|Medium": 6.7,
    "UD Digi Kyokasho NP-B|Bold": 9,
    "HGSeikaishotaiPRO|Regular": 11.8,
    "HGPKyokashotai|Medium": 12.4,
    "BIZ UDPGothic|Regular": 13,
    "DotGothic16|Regular": 13,
    "Noto Serif JP|Regular": 15,
    "HGMaruGothicMPRO|Regular": 17,

    # fonts/ から入れた書体（手元で動かす/導入_書体を入れる.py）。測り方は上と同じ。
    "Dela Gothic One|Regular": 4.8,
    "Rampart One|Regular": 19.4,
    "Reggae One|Regular": 7.8,
    "Train One|Regular": 4.8,
    "RocknRoll One|Regular": 8,
    "Mochiy Pop One|Regular": 9,
    "Zen Maru Gothic|Bold": 7,
    "Zen Maru Gothic Black|Regular": 5.2,
    "Yusei Magic|Regular": 9,
    "Yomogi|Regular": 14.1,
    "Hachi Maru Pop|Regular": 18,
    "Zen Old Mincho Black|Regular": 10,
    "Zen Antique|Regular": 10,
    "Shippori Mincho B1 ExtraBold|Regular": 11,
    "Klee One SemiBold|Regular": 10,
}

# 隙間の半径の何倍まで縁を許すか。1.0だと隙間がちょうど閉じる太さ。
# 1.3 は、大きい穴は開いたまま・画数の多い字の細い穴だけ埋まる境目で、見比べて決めた。
COUNTER_ALLOW = 1.3
COUNTER_INK = 200.0

# 1枚の字幕に載る全角の文字数。装飾によって書体・大きさ・字送りが違うので、
# 同じ文字数でも幅が変わる。ここを超えて広がる装飾は作らせない。
# TicTok 側の設定 subtitle_chars_per_line から余白を引いた値と揃えること。
# 実機は subtitle_chars_per_line=10（DBのsettings表が既定16を上書き）・安全余白6%で
# 9.4字/行。小数は切り捨てられるので、字幕fileが送ってくる最大の行は9字。
# ここは10のまま。9字ぶんに詰めると、余白6%の上にもう1字ぶん余白を重ねることになる。
FIT_CHARS = 10
# Size はこの字数が横幅いっぱいになる値を、装飾ごとに1件ずつ解いて決める。
# 送り幅は書体で 0.5481〜0.8000 とばらつくので、同じ Size でも大きさは揃わない。
# 一律の倍率では原理的に揃わない。装飾ごとに狙いを変えることもしない。
# 折り返すのは字幕file側（TicTok の subtitle_chars_per_line から安全余白を引いた値）
# なので、この値はそれと必ず同じにする。食い違うと、装飾が幅を決め直して端が切れる。
FIT_TARGET_CHARS = FIT_CHARS
# 字幕に使ってよい画面幅の割合。縦動画は右端に操作の列が重なるので端まで使えない。
FIT_WIDTH = 0.86
# 1行に載せる全角の文字数の上限。幅は足りていても、読み手が目で追える長さで頭を打つ。
# 幅の関門（FIT_WIDTH）とは別の理由なので、別の値として持つ。
WRAP_MAX = 20
# 字幕を出す画面の大きさ。送り幅はこの大きさで測ったものだけを使う。
# 横画面で測った値をそのまま縦で使うと、Size が画面の幅と高さのどちらを
# 基準にしているか次第で1.8倍ずれる（どちらなのかはまだ確かめていない）。
FIT_FRAME = (1080, 1920)

# 書体ごとの (全角1文字の送り幅, 全角1文字の字幅, 全角1文字の字高)。
# いずれも「Size 1・画面幅1」あたり。Resolve で 道具_Text+の実寸と書体の字幅を測ってサンプルデータを変更する.py を
# 実行するとここが埋まる。空のうちは幅の関門が働かない。
FONT_WIDTH = {
    "BIZ UDPGothic|Bold": (0.8000, 0.6296, 0.6481),
    "Dela Gothic One|Regular": (0.5556, 0.3704, 0.3704),
    "DotGothic16|Regular": (0.5556, 0.4815, 0.4815),
    "HGMaruGothicMPRO|Regular": (0.8000, 0.5926, 0.5741),
    "HGPGothicE|Regular": (0.8000, 0.6296, 0.6111),
    "HGPGyoshotai|Medium": (0.8000, 0.5926, 0.5741),
    "HGPKyokashotai|Medium": (0.8000, 0.5926, 0.5741),
    "HGPMinchoE|Regular": (0.8000, 0.5926, 0.5926),
    "HGPSoeiKakugothicUB|Regular": (0.8000, 0.6852, 0.6852),
    "HGPSoeiKakupoptai|Regular": (0.8000, 0.7407, 0.7222),
    "HGPSoeiPresenceEB|Extra-Bold": (0.8000, 0.7037, 0.7037),
    "HGSGyoshotai|Medium": (0.8000, 0.5926, 0.5741),
    "HGSKyokashotai|Medium": (0.8000, 0.5926, 0.5741),
    "HGSSoeiPresenceEB|Extra-Bold": (0.8000, 0.7037, 0.7037),
    "HGSeikaishotaiPRO|Regular": (0.8000, 0.5926, 0.5926),
    "Hachi Maru Pop|Regular": (0.5481, 0.4074, 0.4074),
    "Klee One SemiBold|Regular": (0.5556, 0.4815, 0.4815),
    "MS Gothic|Regular": (0.8000, 0.5741, 0.5741),
    "Mochiy Pop One|Regular": (0.5556, 0.4074, 0.5000),
    "Noto Sans JP Black|Regular": (0.6667, 0.5185, 0.5370),
    "Noto Sans JP DemiLight|Regular": (0.6667, 0.5185, 0.5370),
    "Noto Sans JP Light|Regular": (0.6667, 0.5185, 0.5370),
    "Noto Sans JP Medium|Regular": (0.6667, 0.5185, 0.5370),
    "Noto Sans JP|Bold": (0.6667, 0.5185, 0.5370),
    "Noto Sans JP|Regular": (0.6667, 0.5185, 0.5370),
    "Noto Serif JP Black|Regular": (0.5556, 0.4444, 0.4444),
    "Noto Serif JP Bold|Regular": (0.5556, 0.4444, 0.4444),
    "Noto Serif JP|Regular": (0.5556, 0.4444, 0.4444),
    "Rampart One|Regular": (0.5519, 0.4630, 0.5370),
    "Reggae One|Regular": (0.5556, 0.4815, 0.4815),
    "RocknRoll One|Regular": (0.5556, 0.4815, 0.4815),
    "Shippori Mincho B1 ExtraBold|Regular": (0.5481, 0.4815, 0.4630),
    "Train One|Regular": (0.5556, 0.4815, 0.4815),
    "UD Digi Kyokasho NP-B|Bold": (0.6889, 0.5185, 0.5185),
    "Yomogi|Regular": (0.5556, 0.4074, 0.4444),
    "Yu Gothic UI|Bold": (0.6000, 0.4444, 0.4630),
    "Yu Mincho Demibold|Bold": (0.7259, 0.5556, 0.5556),
    "Yusei Magic|Regular": (0.5519, 0.4074, 0.4259),
    "Zen Antique|Regular": (0.5481, 0.4815, 0.4630),
    "Zen Maru Gothic Black|Regular": (0.5481, 0.4815, 0.4630),
    "Zen Maru Gothic|Bold": (0.5481, 0.4815, 0.4630),
    "Zen Old Mincho Black|Regular": (0.5481, 0.4815, 0.4630),
}
FONT_WIDTH_FRAME = (1080, 1920)

# Text+ の要素番号。番号が小さいほど手前に描かれる。
# 1=塗り 2=縁取り 3=二重縁取り 4=グロー 5=影 6=帯 7=帯の縁
ELEMENT_LABEL = OrderedDict([
    ("1", "塗り"),
    ("2", "縁取り"),
    ("3", "二重縁取り"),
    ("4", "グロー"),
    ("5", "影"),
    ("6", "帯"),
    ("7", "帯の縁"),
])

# 既定の見た目。TikTokの縦動画（1080x1920）を想定した値。
#   size      持たない。FIT_TARGET_CHARS が横幅いっぱいになる値を書体ごとに逆算する。
#             装飾ごとに大きさを変えると、字幕fileが文字数で折り返した結果と食い違う。
#             折り返しの権威は字幕file（TicTok の subtitle_chars_per_line）1つに置く。
#   edgeW     Thicknessは文字の実寸に対する比。0.035 で 1.9px（黒縁2〜4pxの定番）
#   glow*     距離0・大きめのぼかしで文字の周りに敷く暗い光。背景から文字を持ち上げる
#   cy        0が画面下端、1が上端。0.30はTikTokのUIより上
BASE = OrderedDict([
    ("font", "Noto Sans JP"),
    ("style", "Bold"),
    ("tracking", 0.98),
    ("leading", 0.90),
    ("cx", 0.500),
    ("cy", 0.300),
    ("vertical", 0),   # 0=自動（横書き） 1=縦書き
    ("lineDir", 0),    # 行の進む向き。0=Top Down 1=Bottom Up

    ("fill", "#ffffff"),
    ("fillA", 1.00),

    ("edgeOn", 1),
    ("edgeC", "#000000"),
    ("edgeW", 0.035),
    ("edgeRound", 1),
    ("edgeOutside", 1),

    ("edge2On", 0),
    ("edge2C", "#ffffff"),
    ("edge2W", 0.062),

    ("glowOn", 1),
    ("glowC", "#000000"),
    ("glowW", 0.060),
    ("glowBlur", 4.0),
    ("glowSpread", 0.00),
    ("glowOpacity", 0.55),

    ("shadowOn", 0),
    ("shadowC", "#000000"),
    ("shadowX", 0.006),
    ("shadowY", -0.010),
    ("shadowBlur", 1.5),
    ("shadowOpacity", 0.60),

    ("bandOn", 0),
    ("bandC", "#000000"),
    ("bandOpacity", 0.50),
    ("bandLevel", 1),
    ("bandPadX", 0.18),
    ("bandPadY", 0.12),
    ("bandRound", 0.30),
    ("bandShearX", 0.00),

    # 塗りのグラデーション。色は2〜4つ。並びの先頭が下、末尾が上。
    ("fillGradOn", 0),
    ("fillGradC", ["#b8862b", "#fff6cf", "#c9922f"]),
    ("fillGradAngle", 0.0),

    # 縁のグラデーション
    ("edgeGradOn", 0),
    ("edgeGradC", ["#6b4a12", "#f7e08a"]),
    ("edgeGradAngle", 0.0),

    # 縁だけの変形
    ("edgeAngle", 0.0),     # 度。反時計回りが正（Fusion と同じ向き）
    ("edgeScale", 1.0),     # 1.0 で等倍
    ("edgeOffX", 0.0),      # 画面幅に対する比
    ("edgeOffY", 0.0),      # 正で上へ

    # 帯の縁（要素7）
    ("bandEdgeOn", 0),
    ("bandEdgeC", "#ffffff"),
    ("bandEdgeW", 0.02),
])

# 行頭の目印ごとの上書き。上から順に判定し、一致したものを重ねる（後が勝つ）。
# marker は目印に対する正規表現。文字クラスに \ を入れるとJS側で壊れるため使わない。
ENTRIES = [
    dict(name="相手・ゲスト", marker="[>＞]", sample=">それは違うでしょ", over=dict(
        edgeC="#123a8c", edgeW=0.040, glowC="#08163a")),
    dict(name="もう一人", marker="[>＞]{2,}", sample=">>こっちも見てよ", over=dict(
        edgeC="#0d5c3a", edgeW=0.040, glowC="#04221a")),

    dict(name="驚き", marker="[!！]", sample="!嘘でしょ", over=dict(
        fill="#ffe14a", edgeW=0.040,
        glowW=0.070, glowBlur=5.0, glowOpacity=0.60)),
    dict(name="絶叫", marker="[!！]{2,}", sample="!!無理無理無理", over=dict(
        font="BIZ UDPGothic", style="Bold",
        fill="#ff3320", tracking=1.02,
        edgeC="#ffffff", edgeW=0.026,
        edge2On=1, edge2C="#1a0000", edge2W=0.048,
        glowC="#ff2000", glowW=0.090, glowBlur=7.0, glowOpacity=0.50)),

    dict(name="笑い", marker="[wｗ]", sample="wそれはずるい", over=dict(
        font="HGPSoeiKakupoptai", style="Regular",
        fill="#ffd400", edgeC="#3a2000", edgeW=0.023,
        glowC="#241400")),
    dict(name="大爆笑", marker="[wｗ]{2,}", sample="wwやめてくれ", over=dict(
        font="HGPSoeiKakupoptai", style="Regular",
        fill="#ff9c1a", edgeC="#2b1200", edgeW=0.012,
        edge2On=1, edge2C="#ffffff", edge2W=0.023,
        glowC="#ff7a00", glowW=0.095, glowBlur=6.0, glowOpacity=0.50)),

    dict(name="小声", marker="[*＊]", sample="*これ言っていいのかな", over=dict(
        font="HGMaruGothicMPRO", style="Regular",
        fill="#e3ecf5", fillA=0.88, tracking=1.02,
        edgeW=0.022, glowW=0.050, glowBlur=6.0, glowOpacity=0.45)),
    dict(name="心の声", marker="[*＊]{2,}", sample="**絶対勝てない", over=dict(
        font="HGMaruGothicMPRO", style="Regular",
        fill="#cdd9ff", fillA=0.82, tracking=1.06,
        edgeC="#0a1230", edgeW=0.024,
        glowC="#2a3f8a", glowW=0.065, glowBlur=8.0, glowOpacity=0.50)),
    dict(name="困惑", marker="[?？]", sample="?どういうこと", over=dict(
        fill="#b9c6d6", tracking=1.08,
        glowBlur=5.0)),

    dict(name="見出し", marker="[#＃]", sample="#ここから本番", over=dict(
        font="HGPSoeiKakugothicUB", style="Regular",
        tracking=1.00, edgeW=0.018,
        glowW=0.070, glowBlur=6.0, glowOpacity=0.50,
        bandOn=1, bandC="#0b0e14", bandOpacity=0.55,
        bandPadX=0.18, bandPadY=0.12, bandRound=0.25,
        cy=0.780)),
    dict(name="ニュース風", marker="[#＃]{2,}", sample="##緊急速報", over=dict(
        font="HGPGothicE", style="Regular",
        tracking=1.06,
        edgeOn=0, glowOn=0,
        bandOn=1, bandC="#0a1f52", bandOpacity=0.95,
        bandPadX=0.24, bandPadY=0.16, bandRound=0.05,
        cy=0.820)),
    dict(name="煽り", marker="[#＃]{3,}", sample="###まさかの展開", over=dict(
        font="BIZ UDPGothic", style="Bold",
        fill="#ffe600", tracking=1.00,
        edgeC="#8c0000", edgeW=0.026,
        edge2On=1, edge2C="#ffffff", edge2W=0.048,
        glowC="#ff0000", glowW=0.095, glowBlur=8.0, glowOpacity=0.55,
        cy=0.620)),

    dict(name="リスナーのコメント", marker="[:：]", sample=":それ知ってる", over=dict(
        style="Regular", fillA=0.96,
        edgeOn=0,
        glowW=0.035, glowBlur=5.0, glowOpacity=0.45,
        bandOn=1, bandC="#000000", bandOpacity=0.42,
        bandPadX=0.22, bandPadY=0.18, bandRound=1.00,
        cy=0.660)),
    dict(name="ギフト", marker="[$＄]", sample="$バラをありがとう", over=dict(
        fill="#ffe08a",
        edgeOn=0, glowC="#4a2a00", glowW=0.040, glowOpacity=0.50,
        bandOn=1, bandC="#4a1b7a", bandOpacity=0.72,
        bandPadX=0.24, bandPadY=0.18, bandRound=1.00,
        cy=0.700)),

    dict(name="ナレーション", marker="[=＝]", sample="=このあと事件が起きる", over=dict(
        font="Yu Mincho Demibold", style="Bold",
        tracking=1.14, fill="#f3f3f0",
        edgeW=0.020, glowBlur=6.0, glowOpacity=0.50,
        cy=0.240)),
    dict(name="引用・回想", marker="[\"”]", sample="\"あの時こう言った", over=dict(
        font="Noto Serif JP", style="Regular",
        tracking=1.10, fill="#ece5d6", fillA=0.92,
        edgeW=0.020, glowBlur=7.0, glowOpacity=0.45)),

    dict(name="弾む", marker="[~〜]", sample="~うわあ", source="Text+ 弾む", over={}),
    dict(name="揺れる", marker="[~〜]{2,}", sample="~~ぐらぐらする", source="Text+ 揺れ", over={}),

    # ^ は文字集合の先頭に置くと「それ以外」の打ち消しになり、!でもwでも当たってしまう。
    # 半角を先に書く並びは他の目印と揃えたいので、escape して打ち消しを止める。
    dict(name="画面の上へ", marker=r"[\^＾]", sample="^ここは上に出す", over=dict(cy=0.800)),
    dict(name="画面の下へ", marker="[_＿]", sample="_ここは下に出す", over=dict(cy=0.150)),
]

# 見た目のプリセット。装飾の割り当てを選んでから当てる。
# サイズと位置は割り当て側の持ち物なので、ここでは触らない。
# 模様（ストライプ・水玉）・グラデーション・飾り（ハート等）はText+のInputだけでは作れないため入れていない。
def _look(name, cat, origin="", **over):
    """見た目のプリセット1つ。

    origin は「この見た目の元にした実在のゲームの題字」。装飾の名前は見た目を表す
    日本語にしてあるため、名前だけでは何を見て作ったのかが辿れない。画面と表に
    元のタイトル名を残しておくと、色や縁を直すときに何へ寄せるのかが分かる。
    """
    return dict(name=name, cat=cat, origin=origin, over=over)


LOOKS = [
    # ---- 定番（5件）
    _look("標準（白・黒縁・ぼかし）", "定番",
          font="Noto Sans JP", style="Bold", tracking=0.98, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#000000", edgeW=0.035, edgeRound=1, edgeOutside=1,
          edge2On=0, glowOn=1, glowC="#000000", glowW=0.060, glowBlur=4.0,
          glowSpread=0.00, glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("極太・二重縁", "定番",
          font="BIZ UDPGothic", style="Bold", tracking=1.00, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#000000", edgeW=0.028, edgeRound=1,
          edge2On=1, edge2C="#ffffff", edge2W=0.050,
          glowOn=1, glowC="#000000", glowW=0.100, glowBlur=6.0, glowSpread=0.00,
          glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("縁なし・ぼかしだけ", "定番",
          font="Noto Sans JP", style="Bold", tracking=0.98, fill="#ffffff", fillA=1.00,
          edgeOn=0, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.070, glowBlur=9.0, glowSpread=0.00,
          glowOpacity=0.70, shadowOn=0, bandOn=0),
    _look("ミニマル（ごく薄い影）", "定番",
          font="Noto Sans JP Medium", style="Regular", tracking=1.06, fill="#ffffff", fillA=1.00,
          edgeOn=0, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.040, glowBlur=7.0, glowSpread=0.00,
          glowOpacity=0.28, shadowOn=0, bandOn=0),
    # Noto Sans JP Black は実在の太い face。合成太字ではないので字面が潰れない。
    _look("ドン！（超極太）", "定番",
          font="Noto Sans JP Black", style="Regular", tracking=0.94,
          fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#000000", edgeW=0.0335, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.090, glowBlur=5.0, glowSpread=0.00,
          glowOpacity=0.60, shadowOn=0, bandOn=0),

    # ---- かわいい・ポップ（13件）
    _look("かわいい（丸ゴシック）", "かわいい・ポップ",
          font="HGMaruGothicMPRO", style="Regular", tracking=1.04, fill="#ff6f9c", fillA=1.00,
          edgeOn=1, edgeC="#ffffff", edgeW=0.050, edgeRound=1,
          edge2On=1, edge2C="#ffd9e6", edge2W=0.078,
          glowOn=1, glowC="#b8305c", glowW=0.100, glowBlur=6.0, glowSpread=0.00,
          glowOpacity=0.45, shadowOn=0, bandOn=0),
    # 塗りを白にして、色は縁だけが持つ。薄い塗り＋白縁だと境目が消えて濁る。
    _look("パステル", "かわいい・ポップ",
          font="HGMaruGothicMPRO", style="Regular", tracking=1.06, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#f7a8d0", edgeW=0.046, edgeRound=1,
          edge2On=1, edge2C="#c9b4f0", edge2W=0.078,
          glowOn=1, glowC="#6d4b8f", glowW=0.100, glowBlur=8.0, glowSpread=0.00,
          glowOpacity=0.40, shadowOn=0, bandOn=0),
    _look("ポップ（創英角ポップ）", "かわいい・ポップ",
          font="HGPSoeiKakupoptai", style="Regular", tracking=1.00, fill="#ffe600", fillA=1.00,
          edgeOn=1, edgeC="#1b1b1b", edgeW=0.023, edgeRound=1,
          edge2On=0, edge2C="#ffffff", edge2W=0.080,
          glowOn=1, glowC="#000000", glowW=0.105, glowBlur=5.0, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0, bandOn=0),
    _look("アメコミ風", "かわいい・ポップ",
          font="BIZ UDPGothic", style="Bold", tracking=1.02, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#000000", edgeW=0.030, edgeRound=0,
          edge2On=1, edge2C="#ff2b2b", edge2W=0.050,
          glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.010, shadowY=-0.014,
          shadowBlur=0.0, shadowOpacity=1.00, bandOn=0),
    _look("落ちもの（まる文字・弾む）", "かわいい・ポップ",
          font="HGMaruGothicMPRO", style="Regular", tracking=1.06, fill="#ff7a1a", fillA=1.00,
          edgeOn=1, edgeC="#ffffff", edgeW=0.046, edgeRound=1, edge2On=1, edge2C="#1b3fa0",
          edge2W=0.072, glowOn=0, shadowOn=1, shadowC="#1b3fa0", shadowX=0.006, shadowY=-0.01,
          shadowBlur=0.00, shadowOpacity=0.9, bandOn=0),
    _look("ほのぼの（太い白縁）", "かわいい・ポップ",
          font="HGMaruGothicMPRO", style="Regular", tracking=1.04, fill="#7a4a1e", fillA=1.00,
          edgeOn=1, edgeC="#fffaf0", edgeW=0.052, edgeRound=1, edge2On=1, edge2C="#9ccf6a",
          edge2W=0.074, glowOn=1, glowC="#3a2a10", glowW=0.09, glowBlur=7.00, glowSpread=0.00,
          glowOpacity=0.45, shadowOn=0, bandOn=0),
    _look("はずむ", "かわいい・ポップ",
          font="RocknRoll One", style="Regular", tracking=0.98, leading=0.9,
          fill="#ff9a2b", fillA=1.00, fillGradOn=0, edgeOn=1, edgeC="#ffffff", edgeW=0.022,
          edgeRound=1, edgeOutside=1, edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00,
          edgeOffX=0.00, edgeOffY=0.00, edge2On=1, edge2C="#123a8a", edge2W=0.036, glowOn=0,
          shadowOn=1, shadowC="#0b1c40", shadowX=0.005, shadowY=-0.005, shadowBlur=5.00,
          shadowOpacity=0.5, bandOn=0, bandEdgeOn=0),
    _look("シトラス", "かわいい・ポップ",
          font="Mochiy Pop One", style="Regular", tracking=0.96, leading=0.88,
          fill="#ffc93c", fillA=1.00, fillGradOn=1,
          fillGradC=["#ff7a18", "#ffc93c", "#fff0b0"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#3d1a00", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#2a1200", shadowX=0.004, shadowY=-0.004, shadowBlur=4.00,
          shadowOpacity=0.45, bandOn=0, bandEdgeOn=0),
    _look("まる座布団", "かわいい・ポップ",
          font="Zen Maru Gothic Black", style="Regular", tracking=1.00,
          leading=1.00, fill="#ffffff", fillA=1.00, fillGradOn=0, edgeOn=1, edgeC="#062733",
          edgeW=0.01, edgeRound=1, edgeOutside=1, edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00,
          edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=0, shadowOn=1, shadowC="#04161d",
          shadowX=0.004, shadowY=-0.004, shadowBlur=6.00, shadowOpacity=0.4, bandOn=1,
          bandC="#0e4d5c", bandOpacity=0.95, bandLevel=1, bandPadX=0.03, bandPadY=0.018,
          bandRound=1.00, bandShearX=0.00, bandEdgeOn=1, bandEdgeC="#ffffff", bandEdgeW=0.006),
    _look("シール", "かわいい・ポップ",
          font="Zen Maru Gothic", style="Bold", tracking=1.00, leading=0.92,
          fill="#ffffff", fillA=1.00, fillGradOn=0, edgeOn=1, edgeC="#1d7f74", edgeW=0.028,
          edgeRound=1, edgeOutside=1, edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00,
          edgeOffX=0.005, edgeOffY=-0.005, edge2On=1, edge2C="#0d3b36", edge2W=0.03, glowOn=0,
          shadowOn=1, shadowC="#082523", shadowX=0.008, shadowY=-0.008, shadowBlur=6.00,
          shadowOpacity=0.45, bandOn=0, bandEdgeOn=0),





    # 🐢 の3件。色は絵文字の🐢を描いて画素を数えた3色だけから採る
    # （#008060 甲羅 62.9% / #c0e030 手足と頭 17.5% / #00d060 甲羅の筋 9.6%）。
    # 甲羅の六角模様は Text+ では出せないので、亀らしさは配色と丸みで作る。
    _look("甲羅うら（濃緑に黄緑の輪）", "かわいい・ポップ", origin="絵文字の🐢",
          font="Zen Maru Gothic", style="Bold", tracking=1.02, leading=0.94,
          fill="#008060", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#d8ee66", edgeW=0.032, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#00432f", edge2W=0.046, glowOn=0,
          shadowOn=1, shadowC="#00251a", shadowX=0.005, shadowY=-0.006,
          shadowBlur=3.00, shadowOpacity=0.50, bandOn=0, bandEdgeOn=0),
    _look("若緑（明るい緑に濃緑）", "かわいい・ポップ", origin="絵文字の🐢",
          font="RocknRoll One", style="Regular", tracking=1.00, leading=0.94,
          fill="#00d060", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#00381f", edgeW=0.026, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#eaf5c0", edge2W=0.044, glowOn=0,
          shadowOn=1, shadowC="#00251a", shadowX=0.006, shadowY=-0.007,
          shadowBlur=2.00, shadowOpacity=0.60, bandOn=0, bandEdgeOn=0),
    _look("甲羅座布団（緑の帯）", "かわいい・ポップ", origin="絵文字の🐢",
          font="Zen Maru Gothic", style="Bold", tracking=1.02, leading=0.96,
          fill="#f2f7d8", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#00432f", edgeW=0.014, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#00251a", shadowX=0.004, shadowY=-0.005,
          shadowBlur=6.00, shadowOpacity=0.40,
          bandOn=1, bandC="#008060", bandOpacity=0.95, bandLevel=1,
          bandPadX=0.03, bandPadY=0.018, bandRound=1.00, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#c0e030", bandEdgeW=0.007),

    # ---- こども・ベビー（8件）
    _look("教科書体", "こども・ベビー",
          font="UD Digi Kyokasho NP-B", style="Bold", tracking=1.06, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#1a2230", edgeW=0.036, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.060, glowBlur=5.0, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0, bandOn=0),
    _look("こども向け", "こども・ベビー",
          font="HGPKyokashotai", style="Medium", tracking=1.08, fill="#ffdf4a", fillA=1.00,
          edgeOn=1, edgeC="#ffffff", edgeW=0.038, edgeRound=1,
          edge2On=1, edge2C="#5a4410", edge2W=0.056,
          glowOn=1, glowC="#3a2a00", glowW=0.090, glowBlur=6.0, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0, bandOn=0),
    # 子どもの見た目は「太い白縁＋その外に暗い縁」で作る。原色の塗りだけだと
    # 明るい背景で消えるので、外側の暗い縁が可読性を持つ。
    _look("子供っぽい（クレヨン）", "こども・ベビー",
          font="Yusei Magic", style="Regular", tracking=1.02, leading=0.94,
          fill="#ff7a3c", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#ffffff", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=1, edge2C="#3a1c00", edge2W=0.046, glowOn=0, shadowOn=1, shadowC="#2a1400",
          shadowX=0.005, shadowY=-0.005, shadowBlur=4.00, shadowOpacity=0.45, bandOn=0,
          bandEdgeOn=0),
    _look("赤ちゃん（ミルク）", "こども・ベビー",
          font="Hachi Maru Pop", style="Regular", tracking=1.06, leading=1.00,
          fill="#fff8ef", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#f2b8c6", edgeW=0.032, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=1, edge2C="#7a5a52", edge2W=0.046, glowOn=1, glowC="#6b5148", glowW=0.06,
          glowBlur=8.00, glowSpread=0.00, glowOpacity=0.40, shadowOn=0, bandOn=0,
          bandEdgeOn=0),
    _look("よちよち（水色）", "こども・ベビー",
          font="Zen Maru Gothic", style="Bold", tracking=1.04, leading=0.96,
          fill="#eaf7ff", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#7ec8e8", edgeW=0.036, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=1, edge2C="#2a4a5e", edge2W=0.05, glowOn=0, shadowOn=1, shadowC="#17323f",
          shadowX=0.004, shadowY=-0.004, shadowBlur=5.00, shadowOpacity=0.45, bandOn=0,
          bandEdgeOn=0),
    _look("おえかき（クレヨン線）", "こども・ベビー",
          font="Yomogi", style="Regular", tracking=1.06, leading=0.98,
          fill="#fff6d8", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#e0562a", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=1, edge2C="#2e1a10", edge2W=0.048, glowOn=0, shadowOn=1, shadowC="#2e1a10",
          shadowX=0.004, shadowY=-0.004, shadowBlur=4.00, shadowOpacity=0.40, bandOn=0,
          bandEdgeOn=0),
    _look("つみき（原色）", "こども・ベビー",
          font="Mochiy Pop One", style="Regular", tracking=1.00, leading=0.9,
          fill="#ffd400", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#ffffff", edgeW=0.028, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=1, edge2C="#1a3fa0", edge2W=0.044, glowOn=0, shadowOn=1, shadowC="#1a3fa0",
          shadowX=0.006, shadowY=-0.008, shadowBlur=0.00, shadowOpacity=0.90, bandOn=0,
          bandEdgeOn=0),
    # Zen Maru Gothic Black は穴が狭く、縁の上限が 0.039。二重縁はそこに収める。
    _look("ほっぺ（もちもち）", "こども・ベビー",
          font="Zen Maru Gothic Black", style="Regular", tracking=1.00,
          leading=0.94, fill="#ff8fa8", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#ffffff", edgeW=0.026, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=1, edge2C="#7a2a40", edge2W=0.036, glowOn=0, shadowOn=1, shadowC="#4a1526",
          shadowX=0.004, shadowY=-0.004, shadowBlur=5.00, shadowOpacity=0.45, bandOn=0,
          bandEdgeOn=0),


    # ---- 手書き・ゆるい（3件）
    _look("手書きツッコミ", "手書き・ゆるい",
          font="Yusei Magic", style="Regular", tracking=1.02, leading=0.92,
          fill="#d93b30", fillA=1.00, fillGradOn=0, edgeOn=1, edgeC="#ffffff", edgeW=0.02,
          edgeRound=1, edgeOutside=1, edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00,
          edgeOffX=0.00, edgeOffY=0.00, edge2On=1, edge2C="#17212e", edge2W=0.034, glowOn=0,
          shadowOn=1, shadowC="#12161d", shadowX=0.004, shadowY=-0.004, shadowBlur=4.00,
          shadowOpacity=0.45, bandOn=0, bandEdgeOn=0),
    _look("ひとりごと", "手書き・ゆるい",
          font="Yomogi", style="Regular", tracking=1.06, leading=0.98,
          fill="#fffdf6", fillA=1.00, fillGradOn=0, edgeOn=1, edgeC="#2e2a24", edgeW=0.026,
          edgeRound=1, edgeOutside=1, edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00,
          edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=1, glowC="#201d18", glowW=0.06,
          glowBlur=9.00, glowSpread=0.00, glowOpacity=0.55, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("ゆるふわ実況", "手書き・ゆるい",
          font="Hachi Maru Pop", style="Regular", tracking=1.00, leading=0.94,
          fill="#fff4d2", fillA=1.00, fillGradOn=0, edgeOn=1, edgeC="#10504c", edgeW=0.032,
          edgeRound=1, edgeOutside=1, edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00,
          edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=1, glowC="#07211f", glowW=0.05,
          glowBlur=7.00, glowSpread=0.00, glowOpacity=0.45, shadowOn=0, bandOn=0, bandEdgeOn=0),


    # ---- 自然・やわらか（2件）
    _look("森", "自然・やわらか",
          font="HGMaruGothicMPRO", style="Regular", tracking=1.06, fill="#eaffd8", fillA=1.00,
          edgeOn=1, edgeC="#1e4a1e", edgeW=0.042, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#0d2a0d", glowW=0.085, glowBlur=6.0, glowSpread=0.00,
          glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("夕暮れ", "自然・やわらか",
          font="HGMaruGothicMPRO", style="Regular", tracking=1.06, fill="#ffe0b0", fillA=1.00,
          edgeOn=1, edgeC="#6b2a10", edgeW=0.042, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#3a1405", glowW=0.085, glowBlur=7.0, glowSpread=0.00,
          glowOpacity=0.55, shadowOn=0, bandOn=0),





    # ---- 色気・大人（7件）
    # 色気は「明朝の細い字＋広い字送り＋暗いにじみ」で作る。塗りを濃い赤にすると
    # 安っぽくなるので、赤は縁とにじみ側に置き、塗りは肌の色に寄せる。
    _look("セクシー（艶）", "色気・大人",
          font="Noto Serif JP", style="Regular", tracking=1.22, leading=1.00,
          fill="#f6dfe4", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#2a0d18", edgeW=0.02, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=1, glowC="#7a0f3a", glowW=0.09, glowBlur=10.00, glowSpread=0.25,
          glowOpacity=0.55, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("色っぽい（紅）", "色気・大人",
          font="Yu Mincho Demibold", style="Bold", tracking=1.18, leading=0.98,
          fill="#d4405f", fillA=1.00, fillGradOn=1,
          fillGradC=["#7a0e2e", "#d4405f", "#ffc9d4"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#2a0810", edgeW=0.024, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=1, glowC="#3d0616", glowW=0.085, glowBlur=9.00, glowSpread=0.10,
          glowOpacity=0.60, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 塗りが暗いので、明るい層は金の縁だけが持つ。外側に暗い層を足すと金が挟まれて沈む。
    _look("アダルト（黒に金）", "色気・大人",
          font="Shippori Mincho B1 ExtraBold", style="Regular", tracking=1.20,
          leading=0.96, fill="#141013", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#d8b878", edgeW=0.026, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=0, shadowOn=1, shadowC="#000000", shadowX=0.004, shadowY=-0.005,
          shadowBlur=6.00, shadowOpacity=0.55, bandOn=0, bandEdgeOn=0),
    _look("女性的（桜）", "色気・大人",
          font="Klee One SemiBold", style="Regular", tracking=1.10, leading=0.98,
          fill="#fff4f7", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#c0728f", edgeW=0.026, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=1, edge2C="#4a2233", edge2W=0.04, glowOn=1, glowC="#5e2a3f", glowW=0.07,
          glowBlur=8.00, glowSpread=0.00, glowOpacity=0.45, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("ルージュ（口紅）", "色気・大人",
          font="Zen Old Mincho Black", style="Regular", tracking=1.06, leading=0.92,
          fill="#d81e4a", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#ffffff", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=1, edge2C="#2a0009", edge2W=0.046, glowOn=0, shadowOn=1, shadowC="#2a0009",
          shadowX=0.005, shadowY=-0.005, shadowBlur=5.00, shadowOpacity=0.50, bandOn=0,
          bandEdgeOn=0),
    _look("シルク（艶の階調）", "色気・大人",
          font="Noto Sans JP DemiLight", style="Regular", tracking=1.30,
          leading=1.02, fill="#e6d2dc", fillA=1.00, fillGradOn=1,
          fillGradC=["#6a4a5e", "#e6d2dc", "#fff8fb"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#241a20", edgeW=0.018, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=1, glowC="#120c10", glowW=0.07, glowBlur=9.00, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("妖艶（桃のネオン）", "色気・大人",
          font="Zen Antique", style="Regular", tracking=1.10, leading=0.92,
          fill="#ffeaf4", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#3a0a24", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=1, glowC="#ff2f8a", glowW=0.105, glowBlur=11.00, glowSpread=0.70,
          glowOpacity=0.85, shadowOn=0, bandOn=0, bandEdgeOn=0),

    # ---- こわがり・弱気（5件）
    # 弱気は「小さい・薄い・冷たい色」で作る。字を細くするだけだと読めないので、
    # 大きさを落とすぶん暗いにじみを厚めに敷いて背景から離す。
    _look("おびえている（ふるえ）", "こわがり・弱気",
          font="Yomogi", style="Regular", tracking=1.08, leading=1.00,
          fill="#dfe9f2", fillA=0.95, fillGradOn=0,
          edgeOn=1, edgeC="#101a2a", edgeW=0.024, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=1, glowC="#1b3a6b", glowW=0.085, glowBlur=11.00, glowSpread=0.35,
          glowOpacity=0.60, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("おどおど（小さく）", "こわがり・弱気",
          font="Klee One SemiBold", style="Regular", tracking=1.02, leading=1.00,
          fill="#e8e4dc", fillA=0.88, fillGradOn=0,
          edgeOn=1, edgeC="#22201c", edgeW=0.02, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=1, glowC="#0e0d0b", glowW=0.055, glowBlur=9.00, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("泣きそう（うるむ）", "こわがり・弱気",
          font="Zen Maru Gothic", style="Bold", tracking=1.04, leading=0.98,
          fill="#eaf6ff", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#2a4a66", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=1, glowC="#1a5f9e", glowW=0.095, glowBlur=13.00, glowSpread=0.45,
          glowOpacity=0.65, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("冷や汗（血の気が引く）", "こわがり・弱気",
          font="Noto Sans JP Medium", style="Regular", tracking=1.14,
          leading=1.00, fill="#cfe0e8", fillA=0.94, fillGradOn=0,
          edgeOn=1, edgeC="#0d1a22", edgeW=0.022, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edge2On=0, glowOn=1, glowC="#0a2230", glowW=0.08, glowBlur=10.00, glowSpread=0.20,
          glowOpacity=0.60, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 消え入りそうに見せるため塗りを透かす。縁を引くと輪郭が残って消えないので、
    # 背景から離す役は暗いにじみだけに持たせる。
    _look("消え入りそう（薄れる）", "こわがり・弱気",
          font="Noto Sans JP DemiLight", style="Regular", tracking=1.20,
          leading=1.02, fill="#ffffff", fillA=0.70, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=1, glowC="#000000", glowW=0.075, glowBlur=9.00,
          glowSpread=0.00, glowOpacity=0.85, shadowOn=0, bandOn=0, bandEdgeOn=0),


    # ---- こわい・不穏（4件）
    _look("ホラー（にじむ赤）", "こわい・不穏",
          font="HGPMinchoE", style="Regular", tracking=1.12, fill="#d8d2c8", fillA=1.00,
          edgeOn=1, edgeC="#0a0000", edgeW=0.030, edgeRound=0, edge2On=0,
          glowOn=1, glowC="#8b0000", glowW=0.115, glowBlur=14.0, glowSpread=0.35,
          glowOpacity=0.75, shadowOn=0, bandOn=0),
    _look("血染め（にじむ血）", "こわい・不穏",
          font="HGPGothicE", style="Regular", tracking=0.94, leading=0.95, fill="#c3bbab",
          fillA=1.00, edgeOn=1, edgeC="#0a0806", edgeW=0.026, edgeRound=0, edge2On=1,
          edge2C="#6b1410", edge2W=0.036, glowOn=1, glowC="#8e120b", glowW=0.115,
          glowBlur=12.00, glowSpread=0.5, glowOpacity=0.7, shadowOn=0, bandOn=0),
    _look("暗闇（沈む赤）", "こわい・不穏",
          font="Noto Serif JP Black", style="Regular", tracking=1.16, leading=1.00,
          fill="#574a47", fillA=0.96, edgeOn=1, edgeC="#140000", edgeW=0.022, edgeRound=0,
          edge2On=0, glowOn=1, glowC="#5e0000", glowW=0.12, glowBlur=12.00, glowSpread=0.55,
          glowOpacity=0.85, shadowOn=0, bandOn=0),
    _look("怪談（にじむ黒）", "こわい・不穏",
          font="HGSGyoshotai", style="Medium", tracking=1.1, leading=0.95, fill="#cfc6b4",
          fillA=1.00, edgeOn=1, edgeC="#050403", edgeW=0.026, edgeRound=0, edge2On=0, glowOn=1,
          glowC="#000000", glowW=0.115, glowBlur=12.00, glowSpread=0.1, glowOpacity=0.85,
          shadowOn=1, shadowC="#7a0b0b", shadowX=0.006, shadowY=-0.009, shadowBlur=3.00,
          shadowOpacity=0.85, bandOn=0),









    # ---- 光る・目立つ（12件）
    _look("ネオン（発光）", "光る・目立つ",
          font="Noto Sans JP", style="Bold", tracking=1.02, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#1b0b3a", edgeW=0.028, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#00e5ff", glowW=0.110, glowBlur=10.0, glowSpread=0.70,
          glowOpacity=0.85, shadowOn=0, bandOn=0),
    _look("キラキラ", "光る・目立つ",
          font="Noto Sans JP", style="Bold", tracking=1.04, fill="#ffffff", fillA=1.00,
          edgeOn=0, edge2On=0,
          glowOn=1, glowC="#ffe9a8", glowW=0.100, glowBlur=12.0, glowSpread=0.85,
          glowOpacity=0.80, shadowOn=0, bandOn=0),
    _look("熱血（三重縁）", "光る・目立つ",
          font="BIZ UDPGothic", style="Bold", tracking=1.00, fill="#ffe600", fillA=1.00,
          edgeOn=1, edgeC="#8c0000", edgeW=0.028, edgeRound=1,
          edge2On=1, edge2C="#ffffff", edge2W=0.050,
          glowOn=1, glowC="#ff2000", glowW=0.105, glowBlur=8.0, glowSpread=0.20,
          glowOpacity=0.60, shadowOn=0, bandOn=0),
    _look("サイバー", "光る・目立つ",
          font="Noto Sans JP DemiLight", style="Regular", tracking=1.34, leading=1.05,
          fill="#eafcff", fillA=1.00,
          edgeOn=1, edgeC="#062f40", edgeW=0.020, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#00e5ff", glowW=0.100, glowBlur=11.0, glowSpread=0.75,
          glowOpacity=0.80, shadowOn=0, bandOn=0),
    _look("氷", "光る・目立つ",
          font="Noto Sans JP", style="Bold", tracking=1.04, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#bfe9ff", edgeW=0.032, edgeRound=1,
          edge2On=1, edge2C="#1f6fa8", edge2W=0.042,
          glowOn=1, glowC="#0d3f6b", glowW=0.100, glowBlur=7.0, glowSpread=0.10,
          glowOpacity=0.55, shadowOn=0, bandOn=0),
    # 数字を叩きつける見た目。縁は Noto Sans JP Black の穴の上限(0.028)まで。
    # 見本の 1.9cqw 相当(≒0.09)は漢字が潰れるので、太さではなく色と発光で出す。
    _look("ダメージ数字", "光る・目立つ",
          font="Noto Sans JP Black", style="Regular", tracking=0.96,
          fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#a41414", edgeW=0.026, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#4a0b00", glowW=0.100, glowBlur=6.0, glowSpread=0.25,
          glowOpacity=0.70, shadowOn=0, bandOn=0),
    _look("蛍光（黒縁）", "光る・目立つ",
          font="Yu Gothic UI", style="Bold", tracking=0.94, fill="#c8ff2e", fillA=1.00,
          edgeOn=1, edgeC="#0a0a0a", edgeW=0.038, edgeRound=1, edge2On=1, edge2C="#ff6a00",
          edge2W=0.046, glowOn=1, glowC="#101400", glowW=0.09, glowBlur=6.00, glowSpread=0.15,
          glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("リズム（白×蛍光）", "光る・目立つ",
          font="Noto Sans JP Medium", style="Regular", tracking=1.22, leading=1.00,
          fill="#ffffff", fillA=1.00, edgeOn=1, edgeC="#1a0620", edgeW=0.021, edgeRound=1,
          edge2On=1, edge2C="#3affe0", edge2W=0.028, glowOn=1, glowC="#ff2fd0", glowW=0.08,
          glowBlur=9.00, glowSpread=0.5, glowOpacity=0.7, shadowOn=0, bandOn=0),
    _look("宇宙（冷たい白青）", "光る・目立つ",
          font="Noto Sans JP Light", style="Regular", tracking=1.32, leading=1.05,
          fill="#e6eef8", fillA=1.00, edgeOn=1, edgeC="#0a1626", edgeW=0.024, edgeRound=0,
          edge2On=0, glowOn=1, glowC="#7fb2ff", glowW=0.07, glowBlur=11.00, glowSpread=0.2,
          glowOpacity=0.45, shadowOn=0, bandOn=0),
    _look("毒色（マゼンタ×シアン）", "光る・目立つ",
          font="Noto Sans JP", style="Bold", tracking=1.14, fill="#f7f0ff", fillA=1.00,
          edgeOn=1, edgeC="#16001f", edgeW=0.024, edgeRound=0, edge2On=1, edge2C="#00e0ff",
          edge2W=0.036, glowOn=1, glowC="#ff2bd6", glowW=0.11, glowBlur=8.00, glowSpread=0.55,
          glowOpacity=0.85, shadowOn=0, bandOn=0),
    _look("加速（斜め帯・蛍光）", "光る・目立つ",
          font="Noto Sans JP Black", style="Regular", tracking=0.96, fill="#eaff00",
          fillA=1.00, edgeOn=1, edgeC="#0a0c00", edgeW=0.018, edgeRound=0, edge2On=0, glowOn=1,
          glowC="#b6ff00", glowW=0.075, glowBlur=7.00, glowSpread=0.45, glowOpacity=0.55,
          shadowOn=0, bandOn=1, bandC="#0e1014", bandOpacity=0.92, bandLevel=1, bandPadX=0.22,
          bandPadY=0.14, bandRound=0.02, bandShearX=0.3),
    _look("投影（半透明）", "光る・目立つ",
          font="Noto Sans JP Medium", style="Regular", tracking=1.26, leading=1.02,
          fill="#bfe8ff", fillA=0.55, edgeOn=1, edgeC="#2ea8ff", edgeW=0.028, edgeRound=1,
          edge2On=1, edge2C="#04121f", edge2W=0.042, glowOn=1, glowC="#6fd8ff", glowW=0.105,
          glowBlur=12.00, glowSpread=0.7, glowOpacity=0.6, shadowOn=0, bandOn=0),








    # ---- 迫力・極太（13件）
    _look("荒野（無彩色・極太）", "迫力・極太",
          font="HGPSoeiPresenceEB", style="Extra-Bold", tracking=0.88, leading=0.92,
          fill="#cfc9bb", fillA=1.00, edgeOn=1, edgeC="#0c0b09", edgeW=0.018, edgeRound=0,
          edge2On=1, edge2C="#4a463d", edge2W=0.027, glowOn=1, glowC="#000000", glowW=0.105,
          glowBlur=9.00, glowSpread=0.2, glowOpacity=0.65, shadowOn=0, bandOn=0),
    _look("決勝（傾き帯）", "迫力・極太",
          font="Yu Gothic UI", style="Bold", tracking=0.96, fill="#ff5a14", fillA=1.00,
          edgeOn=1, edgeC="#ffffff", edgeW=0.03, edgeRound=0, edge2On=1, edge2C="#0b1424",
          edge2W=0.04, glowOn=0, shadowOn=0, bandOn=1, bandC="#0b1424", bandOpacity=0.92,
          bandLevel=1, bandPadX=0.22, bandPadY=0.13, bandRound=0.02, bandShearX=0.18),
    _look("必殺（黄×赤・斜め帯）", "迫力・極太",
          font="HGPSoeiPresenceEB", style="Extra-Bold", tracking=1.00, fill="#ffd400",
          fillA=1.00, edgeOn=1, edgeC="#1a0000", edgeW=0.019, edgeRound=0, edge2On=1,
          edge2C="#ffffff", edge2W=0.027, glowOn=0, shadowOn=1, shadowC="#1a0000",
          shadowX=0.012, shadowY=-0.014, shadowBlur=0.00, shadowOpacity=1.00, bandOn=1,
          bandC="#a80f0f", bandOpacity=0.95, bandLevel=1, bandPadX=0.22, bandPadY=0.14,
          bandRound=0.00, bandShearX=0.26),
    _look("鋼鉄（角・赤縁）", "迫力・極太",
          font="Noto Sans JP Black", style="Regular", tracking=1.06, fill="#c6ccd6",
          fillA=1.00, edgeOn=1, edgeC="#080b10", edgeW=0.02, edgeRound=0, edge2On=1,
          edge2C="#b41220", edge2W=0.027, glowOn=1, glowC="#04060a", glowW=0.095,
          glowBlur=4.00, glowSpread=0.00, glowOpacity=0.65, shadowOn=0, bandOn=0),
    _look("戦場（砂・無彩色）", "迫力・極太",
          font="Yu Gothic UI", style="Bold", tracking=1.22, fill="#cfc6ac", fillA=1.00,
          edgeOn=1, edgeC="#13140e", edgeW=0.026, edgeRound=0, edge2On=0, glowOn=1,
          glowC="#000000", glowW=0.07, glowBlur=3.00, glowSpread=0.00, glowOpacity=0.6,
          shadowOn=1, shadowC="#0b0c08", shadowX=0.006, shadowY=-0.008, shadowBlur=0.00,
          shadowOpacity=0.85, bandOn=0),
    _look("大看板", "迫力・極太",
          font="Train One", style="Regular", tracking=1.02, leading=0.88,
          fill="#fff6e8", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#0a0a0a", edgeW=0.022, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.007, shadowY=-0.007, shadowBlur=0.00,
          shadowOpacity=0.85, bandOn=0, bandEdgeOn=0),
    _look("立体抜き", "迫力・極太",
          font="Rampart One", style="Regular", tracking=1.04, leading=0.96,
          fill="#16233f", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#fdfdfb", edgeW=0.046, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=0,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("地響き", "迫力・極太",
          font="Dela Gothic One", style="Regular", tracking=0.88, leading=0.86,
          fill="#ffffff", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#000000", edgeW=0.013, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=1,
          edge2C="#2b0705", edge2W=0.022, glowOn=1, glowC="#000000", glowW=0.06, glowBlur=8.00,
          glowSpread=0.00, glowOpacity=0.58, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("うねり", "迫力・極太",
          font="Reggae One", style="Regular", tracking=0.96, leading=0.9,
          fill="#ffd24a", fillA=1.00, fillGradOn=1,
          fillGradC=["#ff6a12", "#ffb028", "#ffe98a"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#231005", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#3a1400", shadowX=0.004, shadowY=-0.005, shadowBlur=4.00,
          shadowOpacity=0.7, bandOn=0, bandEdgeOn=0),
    _look("段差", "迫力・極太",
          font="Train One", style="Regular", tracking=1.00, leading=0.9,
          fill="#ffffff", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#1f4fd8", edgeW=0.013, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.005, edgeOffY=-0.005, edge2On=1,
          edge2C="#000000", edge2W=0.022, glowOn=0, shadowOn=1, shadowC="#000000",
          shadowX=0.00, shadowY=0.00, shadowBlur=7.00, shadowOpacity=0.75, bandOn=0,
          bandEdgeOn=0),
    _look("傾き縁", "迫力・極太",
          font="Reggae One", style="Regular", tracking=0.98, leading=0.9,
          fill="#fff3d6", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#17120c", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=4.00, edgeScale=1.06, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.003, shadowY=-0.003, shadowBlur=6.00,
          shadowOpacity=0.65, bandOn=0, bandEdgeOn=0),
    _look("額縁", "迫力・極太",
          font="Dela Gothic One", style="Regular", tracking=0.96, leading=1.02,
          fill="#ffffff", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#000000", edgeW=0.02, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=0,
          shadowOn=0, bandOn=1, bandC="#14161c", bandOpacity=0.92, bandLevel=1, bandPadX=0.02,
          bandPadY=0.012, bandRound=0.1, bandShearX=0.00, bandEdgeOn=1, bandEdgeC="#e9e2cf",
          bandEdgeW=0.006),
    _look("禁止（赤）", "迫力・極太",
          font="BIZ UDPGothic", style="Bold", tracking=1.00, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#c9151f", edgeW=0.030, edgeRound=1,
          edge2On=1, edge2C="#2a0000", edge2W=0.050,
          glowOn=1, glowC="#8b0000", glowW=0.100, glowBlur=6.0, glowSpread=0.15,
          glowOpacity=0.55, shadowOn=0, bandOn=0),















    # ---- 金属・つや（11件）
    _look("メタル", "金属・つや",
          font="HGPSoeiPresenceEB", style="Extra-Bold", tracking=1.00, fill="#dfe6ee", fillA=1.00,
          edgeOn=1, edgeC="#1b2027", edgeW=0.019, edgeRound=1,
          edge2On=1, edge2C="#8f9aa8", edge2W=0.028,
          glowOn=1, glowC="#05070a", glowW=0.095, glowBlur=5.0, glowSpread=0.00,
          glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("黒金（沈んだ金）", "金属・つや",
          font="Noto Serif JP", style="Regular", tracking=1.2, leading=0.95, fill="#c9a44c",
          fillA=1.00, edgeOn=1, edgeC="#0a0806", edgeW=0.026, edgeRound=0, edge2On=1,
          edge2C="#6b5a2e", edge2W=0.04, glowOn=1, glowC="#000000", glowW=0.1, glowBlur=10.00,
          glowSpread=0.1, glowOpacity=0.75, shadowOn=0, bandOn=0),
    _look("白銀（明朝）", "金属・つや",
          font="Yu Mincho Demibold", style="Bold", tracking=1.16, leading=1.00, fill="#f2f6ff",
          fillA=1.00, edgeOn=1, edgeC="#9db6d8", edgeW=0.03, edgeRound=1, edge2On=1,
          edge2C="#16264f", edge2W=0.046, glowOn=1, glowC="#0a1330", glowW=0.08, glowBlur=7.00,
          glowSpread=0.05, glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("神威（紫金）", "金属・つや",
          font="HGSSoeiPresenceEB", style="Extra-Bold", tracking=1.08, leading=0.95,
          fill="#efd68a", fillA=1.00, edgeOn=1, edgeC="#2a1358", edgeW=0.02, edgeRound=0,
          edge2On=1, edge2C="#0b0620", edge2W=0.029, glowOn=1, glowC="#6a2ec8", glowW=0.095,
          glowBlur=10.00, glowSpread=0.45, glowOpacity=0.65, shadowOn=0, bandOn=0),
    _look("純金（表彰）", "金属・つや",
          font="Dela Gothic One", style="Regular", tracking=0.96, leading=0.9,
          fill="#d9a52e", fillA=1.00, fillGradOn=1,
          fillGradC=["#6b4a12", "#d9a52e", "#fff4d0", "#7a5417"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#2a1a05", edgeW=0.02, edgeRound=1, edgeOutside=1, edgeGradOn=1,
          edgeGradC=["#1c1103", "#6d4a12", "#2a1a05"], edgeGradAngle=0.00, edgeAngle=0.00,
          edgeScale=1.00, edgeOffX=0.00, edgeOffY=-0.002, edge2On=0, glowOn=1, glowC="#000000",
          glowW=0.075, glowBlur=6.00, glowSpread=0.00, glowOpacity=0.55, shadowOn=0, bandOn=0,
          bandEdgeOn=0),
    _look("白金（記録）", "金属・つや",
          font="Noto Sans JP Black", style="Regular", tracking=0.98, leading=0.9,
          fill="#c3ced9", fillA=1.00, fillGradOn=1,
          fillGradC=["#4e5763", "#b9c4cf", "#ffffff", "#68727e"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#12161c", edgeW=0.022, edgeRound=1, edgeOutside=1, edgeGradOn=1,
          edgeGradC=["#0d1016", "#3b4552", "#12161c"], edgeGradAngle=0.00, edgeAngle=0.00,
          edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=1, glowC="#000000",
          glowW=0.07, glowBlur=6.00, glowSpread=0.00, glowOpacity=0.5, shadowOn=0, bandOn=0,
          bandEdgeOn=0),
    _look("古銅（殿堂）", "金属・つや",
          font="HGPGothicE", style="Regular", tracking=0.98, leading=0.9,
          fill="#b3773a", fillA=1.00, fillGradOn=1,
          fillGradC=["#4a2a12", "#b3773a", "#f2d8ab", "#5c3418"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#1e1006", edgeW=0.024, edgeRound=1, edgeOutside=1, edgeGradOn=1,
          edgeGradC=["#160b04", "#4a2a12", "#1e1006"], edgeGradAngle=0.00, edgeAngle=0.00,
          edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=0, shadowOn=1,
          shadowC="#000000", shadowX=0.004, shadowY=-0.006, shadowBlur=4.00, shadowOpacity=0.6,
          bandOn=0, bandEdgeOn=0),
    _look("玉虫（記念）", "金属・つや",
          font="Mochiy Pop One", style="Regular", tracking=0.98, leading=0.9,
          fill="#ffd24d", fillA=1.00, fillGradOn=1,
          fillGradC=["#ff4d8d", "#ffd24d", "#5cf0b4", "#6a7dff"], fillGradAngle=18.00,
          edgeOn=1, edgeC="#1a0b2e", edgeW=0.026, edgeRound=1, edgeOutside=1, edgeGradOn=1,
          edgeGradC=["#2a0a3c", "#0b2f4a", "#2a0a3c"], edgeGradAngle=18.00, edgeAngle=0.00,
          edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=1, glowC="#140428",
          glowW=0.085, glowBlur=8.00, glowSpread=0.00, glowOpacity=0.45, shadowOn=0, bandOn=0,
          bandEdgeOn=0),
    _look("茜空（夕景）", "金属・つや",
          font="Zen Maru Gothic Black", style="Regular", tracking=0.98,
          leading=0.9, fill="#ff6a8f", fillA=1.00, fillGradOn=1,
          fillGradC=["#ffb45c", "#ff6a8f", "#c05cf0", "#6a3ce0"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#241040", edgeW=0.02, edgeRound=1, edgeOutside=1, edgeGradOn=1,
          edgeGradC=["#3a1414", "#241040"], edgeGradAngle=0.00, edgeAngle=0.00, edgeScale=1.00,
          edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=1, glowC="#4a1030", glowW=0.09,
          glowBlur=8.00, glowSpread=0.00, glowOpacity=0.45, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("鏡面（クローム）", "金属・つや",
          font="HGPSoeiKakugothicUB", style="Regular", tracking=0.96, leading=0.9,
          fill="#b4a48a", fillA=1.00, fillGradOn=1,
          fillGradC=["#2b2620", "#b4a48a", "#e6f3ff", "#3f86c4"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#0b1016", edgeW=0.019, edgeRound=1, edgeOutside=1, edgeGradOn=1,
          edgeGradC=["#070b10", "#2f3b48", "#0b1016"], edgeGradAngle=0.00, edgeAngle=0.00,
          edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=0, glowOn=1, glowC="#000000",
          glowW=0.07, glowBlur=6.00, glowSpread=0.00, glowOpacity=0.5, shadowOn=0, bandOn=0,
          bandEdgeOn=0),
    _look("黒鉄（ガンメタ）", "金属・つや",
          font="Noto Sans JP", style="Bold", tracking=0.98, leading=0.9,
          fill="#3a4048", fillA=1.00, fillGradOn=1,
          fillGradC=["#141619", "#3a4048", "#98a2ad", "#20242a"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#05070a", edgeW=0.018, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00, edge2On=1,
          edge2C="#8f9aa6", edge2W=0.03, glowOn=0, shadowOn=1, shadowC="#000000",
          shadowX=0.005, shadowY=-0.006, shadowBlur=5.00, shadowOpacity=0.55, bandOn=0,
          bandEdgeOn=0),











    # ---- 和・レトロ印刷（11件）
    _look("和風（墨）", "和・レトロ印刷",
          font="HGPMinchoE", style="Regular", tracking=1.10, leading=0.95,
          fill="#f7f3ea", fillA=1.00,
          edgeOn=1, edgeC="#14100c", edgeW=0.034, edgeRound=0, edge2On=0,
          glowOn=1, glowC="#14100c", glowW=0.078, glowBlur=5.0, glowSpread=0.00,
          glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("筆文字（行書）", "和・レトロ印刷",
          font="HGPGyoshotai", style="Medium", tracking=1.06, leading=0.95,
          fill="#f7f3ea", fillA=1.00,
          edgeOn=1, edgeC="#14100c", edgeW=0.028, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#14100c", glowW=0.080, glowBlur=5.0, glowSpread=0.00,
          glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("賞状（正楷書）", "和・レトロ印刷",
          font="HGSeikaishotaiPRO", style="Regular", tracking=1.16, leading=1.00,
          fill="#f2d98a", fillA=1.00,
          edgeOn=1, edgeC="#16224a", edgeW=0.038, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#0a1230", glowW=0.075, glowBlur=6.0, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0, bandOn=0),
    _look("朱印（金字・朱縁）", "和・レトロ印刷",
          font="HGPMinchoE", style="Regular", tracking=1.14, leading=0.95, fill="#edc86b",
          fillA=1.00, edgeOn=1, edgeC="#a01b12", edgeW=0.034, edgeRound=0, edge2On=1,
          edge2C="#17110c", edge2W=0.05, glowOn=1, glowC="#17110c", glowW=0.085, glowBlur=6.00,
          glowSpread=0.00, glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("大河（墨帯に金）", "和・レトロ印刷",
          font="HGSKyokashotai", style="Medium", tracking=1.18, leading=1.00, fill="#e3bf6d",
          fillA=1.00, edgeOn=1, edgeC="#1a140c", edgeW=0.022, edgeRound=1, edge2On=0, glowOn=0,
          shadowOn=0, bandOn=1, bandC="#0d0b08", bandOpacity=0.92, bandLevel=1, bandPadX=0.26,
          bandPadY=0.18, bandRound=0.02, bandShearX=0.00),
    _look("昭和看板", "和・レトロ印刷",
          font="Zen Antique", style="Regular", tracking=1.02, leading=0.92,
          fill="#b03a26", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#f0e2c2", edgeW=0.026, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeGradAngle=0.00, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#3b2416", edge2W=0.04, glowOn=0, glowC="#000000", glowW=0.00,
          glowBlur=0.00, glowSpread=0.00, glowOpacity=0.00, shadowOn=1, shadowC="#2a1a10",
          shadowX=0.004, shadowY=-0.004, shadowBlur=2.00, shadowOpacity=0.55, bandOn=0,
          bandEdgeOn=0),
    _look("墨臙脂", "和・レトロ印刷",
          font="Zen Old Mincho Black", style="Regular", tracking=0.96, leading=0.88,
          fill="#14121a", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#ece4d6", edgeW=0.026, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeGradAngle=0.00, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00, glowOn=1, glowC="#3a0d12", glowW=0.052,
          glowBlur=8.00, glowSpread=0.00, glowOpacity=0.6, shadowOn=0, shadowC="#000000",
          shadowX=0.00, shadowY=0.00, shadowBlur=0.00, shadowOpacity=0.00, bandOn=0,
          bandEdgeOn=0),
    _look("和綴じ", "和・レトロ印刷",
          font="Shippori Mincho B1 ExtraBold", style="Regular", tracking=1.04,
          leading=0.94, fill="#241f1a", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#e9dfc7", edgeW=0.032, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeGradAngle=0.00, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00, glowOn=1, glowC="#ded1b2", glowW=0.07,
          glowBlur=11.00, glowSpread=0.00, glowOpacity=0.5, shadowOn=1, shadowC="#4a3a26",
          shadowX=0.003, shadowY=-0.003, shadowBlur=4.00, shadowOpacity=0.4, bandOn=0,
          bandEdgeOn=0),
    _look("献立札", "和・レトロ印刷",
          font="Shippori Mincho B1 ExtraBold", style="Regular", tracking=1.08,
          leading=0.92, fill="#f3ead6", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#101a14", edgeW=0.02, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeGradAngle=0.00, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00, glowOn=0, glowC="#000000", glowW=0.00,
          glowBlur=0.00, glowSpread=0.00, glowOpacity=0.00, shadowOn=0, shadowC="#000000",
          shadowX=0.00, shadowY=0.00, shadowBlur=0.00, shadowOpacity=0.00, bandOn=1,
          bandC="#1d3026", bandOpacity=0.88, bandLevel=1, bandPadX=0.03, bandPadY=0.018,
          bandRound=0.06, bandShearX=0.00, bandEdgeOn=1, bandEdgeC="#c2a15a", bandEdgeW=0.005),
    _look("版ズレ", "和・レトロ印刷",
          font="Zen Old Mincho Black", style="Regular", tracking=1.00, leading=0.9,
          fill="#1c3050", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#f0e7d1", edgeW=0.028, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeGradAngle=0.00, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.004, edgeOffY=-0.004,
          edge2On=0, edge2C="#000000", edge2W=0.00, glowOn=0, glowC="#000000", glowW=0.00,
          glowBlur=0.00, glowSpread=0.00, glowOpacity=0.00, shadowOn=1, shadowC="#b8402c",
          shadowX=-0.006, shadowY=0.006, shadowBlur=1.00, shadowOpacity=0.85, bandOn=0,
          bandEdgeOn=0),
    _look("暁藤", "和・レトロ印刷",
          font="Zen Antique", style="Regular", tracking=1.02, leading=0.92,
          fill="#7a6bb0", fillA=1.00, fillGradOn=1,
          fillGradC=["#2b2350", "#7a6bb0", "#f2d4de"], fillGradAngle=0.00, edgeOn=1,
          edgeC="#17122b", edgeW=0.03, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeGradAngle=0.00, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00, glowOn=0, glowC="#000000", glowW=0.00,
          glowBlur=0.00, glowSpread=0.00, glowOpacity=0.00, shadowOn=1, shadowC="#120e22",
          shadowX=0.004, shadowY=-0.004, shadowBlur=5.00, shadowOpacity=0.7, bandOn=0,
          bandEdgeOn=0),



    # ---- 上質・現代（12件）
    _look("おしゃれ（細ゴシック）", "上質・現代",
          font="Noto Sans JP DemiLight", style="Regular", tracking=1.28, leading=1.00,
          fill="#ffffff", fillA=1.00, edgeOn=0, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.050, glowBlur=8.0, glowSpread=0.00,
          glowOpacity=0.45, shadowOn=0, bandOn=0),
    _look("高級感（明朝）", "上質・現代",
          font="Noto Serif JP", style="Regular", tracking=1.24, leading=1.00,
          fill="#f4ead6", fillA=1.00, edgeOn=0, edge2On=0,
          glowOn=1, glowC="#2a1d0c", glowW=0.055, glowBlur=8.0, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0, bandOn=0),
    _look("モノトーン", "上質・現代",
          font="Noto Sans JP Medium", style="Regular", tracking=1.14, leading=1.00,
          fill="#d8dde3", fillA=1.00, edgeOn=0, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.055, glowBlur=8.0, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0, bandOn=0),
    # 映画の字幕は主張しない。細めの字を小さく下に置き、縁ではなく薄いぼかしで浮かせる。
    _look("シネマ字幕", "上質・現代",
          font="Noto Sans JP Medium", style="Regular", tracking=1.10, leading=1.00,
          fill="#f2f2f0", fillA=1.00, edgeOn=0, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.050, glowBlur=6.0, glowSpread=0.00,
          glowOpacity=0.55, shadowOn=0, bandOn=0, cy=0.160),
    _look("遺跡（砂色・古紙）", "上質・現代",
          font="Noto Serif JP Bold", style="Regular", tracking=1.12, leading=1.00,
          fill="#e8d9b5", fillA=1.00, edgeOn=1, edgeC="#3a2c18", edgeW=0.026, edgeRound=1,
          edge2On=0, glowOn=1, glowC="#2a1e0e", glowW=0.08, glowBlur=8.00, glowSpread=0.1,
          glowOpacity=0.55, shadowOn=0, bandOn=0),
    _look("鉛筆手帳", "上質・現代",
          font="Klee One SemiBold", style="Regular", tracking=1.06, leading=0.96,
          fill="#3f4650", fillA=1.00, fillGradOn=0, fillGradAngle=0.00, edgeOn=1,
          edgeC="#f5f1e6", edgeW=0.022, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeGradAngle=0.00, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00, glowOn=0, glowC="#000000", glowW=0.00,
          glowBlur=0.00, glowSpread=0.00, glowOpacity=0.00, shadowOn=1, shadowC="#7d7466",
          shadowX=0.002, shadowY=-0.002, shadowBlur=3.00, shadowOpacity=0.5, bandOn=0,
          bandEdgeOn=0),
    # 現代的な字幕は縁を引かない。縁取りは「無料アプリの既定」に見えるため、
    # 背景から離す役は帯に持たせ、帯の濃さだけで明るい背景に耐えさせる。
    _look("現代的（うすい帯）", "上質・現代",
          font="Noto Sans JP Medium", style="Regular", tracking=1.10,
          leading=1.05, fill="#ffffff", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#101418", bandOpacity=0.60, bandLevel=1, bandPadX=0.16,
          bandPadY=0.12, bandRound=0.60, bandShearX=0.00, bandEdgeOn=0),
    _look("上質（余白の細字）", "上質・現代",
          font="Noto Sans JP Light", style="Regular", tracking=1.36, leading=1.10,
          fill="#f7f5f0", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#0e1014", bandOpacity=0.62, bandLevel=1, bandPadX=0.16,
          bandPadY=0.14, bandRound=0.08, bandShearX=0.00, bandEdgeOn=0),
    _look("最先端（画面の表示）", "上質・現代",
          font="Noto Sans JP", style="Regular", tracking=1.42, leading=1.05,
          fill="#f2fbff", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#0a1016", bandOpacity=0.70, bandLevel=1, bandPadX=0.14,
          bandPadY=0.12, bandRound=0.18, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#3affe0", bandEdgeW=0.005),
    # 黒い字を明るい帯に載せる。上下の帯もの（ニュース・注意）と逆で、紙面の見え方になる。
    _look("雑誌（白地に黒）", "上質・現代",
          font="Noto Serif JP", style="Regular", tracking=1.30, leading=1.08,
          fill="#16130f", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.003, shadowY=-0.004, shadowBlur=6.00,
          shadowOpacity=0.35,
          bandOn=1, bandC="#f2efe8", bandOpacity=0.96, bandLevel=1, bandPadX=0.14,
          bandPadY=0.12, bandRound=0.00, bandShearX=0.00, bandEdgeOn=0),
    _look("モード（広い字送り）", "上質・現代",
          font="Noto Sans JP DemiLight", style="Regular", tracking=1.70, leading=1.20,
          fill="#ffffff", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=1, glowC="#000000", glowW=0.045, glowBlur=8.00,
          glowSpread=0.00, glowOpacity=0.50, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("カード（白い錠剤）", "上質・現代",
          font="Noto Sans JP", style="Bold", tracking=1.04, leading=0.98,
          fill="#101418", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#ffffff", bandOpacity=0.92, bandLevel=1, bandPadX=0.18,
          bandPadY=0.14, bandRound=1.00, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#101418", bandEdgeW=0.004),












    # ---- 帯・テロップ（7件）
    _look("帯（行ごと・角丸）", "帯・テロップ",
          font="Noto Sans JP", style="Bold", tracking=0.98, fill="#ffffff", fillA=1.00,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#000000", bandOpacity=0.55, bandLevel=1,
          bandPadX=0.20, bandPadY=0.14, bandRound=0.30, bandShearX=0.00),
    _look("ニュース（紺帯）", "帯・テロップ",
          font="HGPGothicE", style="Regular", tracking=1.06, fill="#ffffff", fillA=1.00,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#0a1f52", bandOpacity=0.95, bandLevel=1,
          bandPadX=0.24, bandPadY=0.16, bandRound=0.05, bandShearX=0.00),
    _look("ゲーム実況（青帯）", "帯・テロップ",
          font="BIZ UDPGothic", style="Bold", tracking=1.00, fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#06213f", edgeW=0.030, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#06213f", glowW=0.060, glowBlur=4.0, glowSpread=0.00,
          glowOpacity=0.50, shadowOn=0,
          bandOn=1, bandC="#0d4f8c", bandOpacity=0.80, bandLevel=1,
          bandPadX=0.20, bandPadY=0.14, bandRound=0.45, bandShearX=0.00),
    _look("斜め帯", "帯・テロップ",
          font="Noto Sans JP", style="Bold", tracking=1.00, fill="#101418", fillA=1.00,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#ffe600", bandOpacity=1.00, bandLevel=1,
          bandPadX=0.22, bandPadY=0.14, bandRound=0.00, bandShearX=0.23),
    _look("注意（黄帯）", "帯・テロップ",
          font="BIZ UDPGothic", style="Bold", tracking=1.02, fill="#12161c", fillA=1.00,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#ffd400", bandOpacity=1.00, bandLevel=1,
          bandPadX=0.22, bandPadY=0.14, bandRound=0.05, bandShearX=0.00),
    # Level は帯を切る単位。2=単語ごと、3=文字ごと。行ごと(1)しか無かった枠を埋める。
    _look("帯（単語ごと）", "帯・テロップ",
          font="Noto Sans JP", style="Bold", tracking=1.00, fill="#ffffff", fillA=1.00,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#0b0e14", bandOpacity=0.55, bandLevel=2,
          bandPadX=0.16, bandPadY=0.12, bandRound=0.30, bandShearX=0.00),
    _look("帯（文字ごと）", "帯・テロップ",
          font="Noto Sans JP", style="Bold", tracking=1.10, fill="#ffffff", fillA=1.00,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#0b0e14", bandOpacity=0.60, bandLevel=3,
          bandPadX=0.10, bandPadY=0.10, bandRound=0.30, bandShearX=0.00),








    # ---- レトロ・ゲーム（6件）
    _look("レトロ・落ち影", "レトロ・ゲーム",
          font="HGPSoeiKakugothicUB", style="Regular", tracking=1.00, fill="#ffe14a", fillA=1.00,
          edgeOn=1, edgeC="#1a1000", edgeW=0.018, edgeRound=1, edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.008, shadowY=-0.012,
          shadowBlur=0.0, shadowOpacity=1.00, bandOn=0),
    # DotGothic16 は字そのものが四角い点の集まりで、大きくしても点のまま出る。
    # 縁取りを掛けると点がつながって潰れるので、硬い落ち影だけにする。
    _look("ドット絵（8bit）", "レトロ・ゲーム",
          font="DotGothic16", style="Regular", tracking=1.08, leading=1.10,
          fill="#ffffff", fillA=1.00,
          edgeOn=0, edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.007, shadowY=-0.011,
          shadowBlur=0.0, shadowOpacity=1.00, bandOn=0),
    # フィルムカメラの焼き込み風。画面の右下に小さく置く。
    _look("日付スタンプ", "レトロ・ゲーム",
          font="MS Gothic", style="Regular", tracking=1.12,
          cx=0.780, cy=0.120, fill="#ff9a3c", fillA=1.00,
          edgeOn=0, edge2On=0,
          glowOn=1, glowC="#ff7a00", glowW=0.090, glowBlur=10.0, glowSpread=0.60,
          glowOpacity=0.80, shadowOn=0, bandOn=0),
    # 端末の画面。等幅の書体に緑の字、下に黒い帯を敷く。
    _look("ターミナル", "レトロ・ゲーム",
          font="MS Gothic", style="Regular", tracking=1.06, leading=1.20,
          fill="#7ddc9a", fillA=1.00,
          edgeOn=0, edge2On=0, shadowOn=0,
          glowOn=1, glowC="#00ff88", glowW=0.070, glowBlur=9.0, glowSpread=0.55,
          glowOpacity=0.60,
          bandOn=1, bandC="#04120a", bandOpacity=0.78, bandLevel=1,
          bandPadX=0.14, bandPadY=0.14, bandRound=0.05, bandShearX=0.00),
    _look("原色ドット（画面枠つき）", "レトロ・ゲーム",
          font="DotGothic16", style="Regular", tracking=1.1, leading=1.15, fill="#ffd800",
          fillA=1.00, edgeOn=0, edge2On=0, glowOn=0, shadowOn=1, shadowC="#c81010",
          shadowX=0.008, shadowY=-0.012, shadowBlur=0.00, shadowOpacity=1.00, bandOn=1,
          bandC="#0a0a2a", bandOpacity=0.92, bandLevel=1, bandPadX=0.18, bandPadY=0.14,
          bandRound=0.00, bandShearX=0.00),
    _look("筐体（蛍光・硬い斜め影）", "レトロ・ゲーム",
          font="HGPGothicE", style="Regular", tracking=1.02, fill="#ff2fa0", fillA=1.00,
          edgeOn=1, edgeC="#ffffff", edgeW=0.024, edgeRound=0, edge2On=1, edge2C="#12002a",
          edge2W=0.034, glowOn=0, shadowOn=1, shadowC="#00d8ff", shadowX=0.014, shadowY=-0.018,
          shadowBlur=0.00, shadowOpacity=1.00, bandOn=0),



    # ---- 縦書き（2件）
    # Text+ の Direction を Vertical にすると縦組みになる（plugin の制御表で確認）。
    # 行の位置は Center で決めるので、右端に寄せて上から始める。
    _look("縦書き", "縦書き",
          font="Noto Sans JP", style="Bold", tracking=1.06, leading=1.00,
          vertical=1, cx=0.820, cy=0.560,
          fill="#ffffff", fillA=1.00,
          edgeOn=1, edgeC="#000000", edgeW=0.032, edgeRound=1, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.070, glowBlur=6.0, glowSpread=0.00,
          glowOpacity=0.60, shadowOn=0, bandOn=0),
    _look("縦書き（明朝）", "縦書き",
          font="Noto Serif JP", style="Regular", tracking=1.14, leading=1.05,
          vertical=1, cx=0.820, cy=0.560,
          fill="#f3f1ea", fillA=1.00,
          edgeOn=0, edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.060, glowBlur=8.0, glowSpread=0.00,
          glowOpacity=0.60, shadowOn=0, bandOn=0),

    # ---- ゲームの題字（90件）
    # 実在の題字1本につき1件。ロゴ画像の画素を数えた色から起こしてある。
    # 出自の分類なので、気分の分類（上の16）とは別に置く。
    _look("白のにじみ（黒字）", "ゲームの題字", origin="大乱闘スマッシュブラザーズ SPECIAL（2018年・Nintendo Switch）",
          font="Noto Serif JP Bold", style="Regular", tracking=0.98, leading=0.94,
          fill="#0b0b0b", fillA=1.00, fillGradOn=0, fillGradAngle=0.00,
          edgeOn=0, edgeC="#000000", edgeW=0.00, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00,
          glowOn=1, glowC="#ffffff", glowW=0.105, glowBlur=7.00, glowSpread=0.60,
          glowOpacity=0.85,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    # 手描きの白い文字に黒い輪郭、影だけが赤くずれる。玩具の箱絵の作り。
    _look("玩具箱（赤いズレ影）", "ゲームの題字", origin="Poppy Playtime（2021年・PC／家庭用）",
          font="Yusei Magic", style="Regular", tracking=1.00, leading=0.94,
          fill="#f2f0ee", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#0d0b0b", edgeW=0.026, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#d81111", shadowX=0.010, shadowY=-0.012, shadowBlur=0.00,
          shadowOpacity=1.00,
          bandOn=0, bandEdgeOn=0),
    # 下だけ金に沈む塗り＋金の細い輪＋青の太い外縁。青は濃紺のぼかしで受ける。
    _look("金の輪（青の外縁）", "ゲームの題字", origin="星のカービィ ディスカバリー（2022年・Nintendo Switch）",
          font="Zen Maru Gothic Black", style="Regular", tracking=1.02, leading=0.96,
          fill="#ffffff", fillA=1.00,
          fillGradOn=1, fillGradC=["#f09000", "#ffe07a", "#ffffff"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#e08a00", edgeW=0.020, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#2050f0", edge2W=0.033,
          glowOn=1, glowC="#001d70", glowW=0.075, glowBlur=5.00, glowSpread=0.10,
          glowOpacity=0.55,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 水色の階調の丸文字を、桃の輪と黄の外輪で二重に囲む。
    _look("水風船（桃の輪・黄の外）", "ゲームの題字", origin="Fall Guys（2020年・PC / 家庭用）",
          font="Zen Maru Gothic", style="Bold", tracking=1.02, leading=0.96,
          fill="#5fd8ef", fillA=1.00,
          fillGradOn=1, fillGradC=["#0f79a8", "#4fd0e6", "#7ce4f5"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#b00080", edgeW=0.028, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#f0c010", edge2W=0.046,
          glowOn=0,
          shadowOn=1, shadowC="#2a2560", shadowX=0.004, shadowY=-0.005,
          shadowBlur=5.00, shadowOpacity=0.45,
          bandOn=0, bandEdgeOn=0),
    # 水色の塗り＋白縁＋濃紺の外輪。既存のポップは暖色ばかりなので寒色の極太を足す。
    _look("空色（白縁・濃紺の外輪）", "ゲームの題字", origin="フォートナイト（2017年・PC/PS/Xbox/Switch）",
          font="Reggae One", style="Regular", tracking=1.02, leading=0.95,
          fill="#6cb4f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#ffffff", edgeW=0.030, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#16406e", edge2W=0.048,
          glowOn=1, glowC="#0b2a4a", glowW=0.085, glowBlur=5.0, glowSpread=0.00,
          glowOpacity=0.45,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 丸ゴシックの琥珀色を、濃い葡萄酒色の太い縁1本だけで締める。影も発光も足さない。
    _look("琥珀（葡萄酒の太縁）", "ゲームの題字", origin="It Takes Two（2021年・PC・PS・Xbox）",
          font="Zen Maru Gothic", style="Bold", tracking=1.00, leading=0.94,
          fill="#f0b030", fillA=1.00, fillGradOn=1,
          fillGradC=["#e09020", "#f0b030", "#f0c040"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#600000", edgeW=0.042, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 下が濃く上が白い階調で艶を出し、深い紅の縁1本で締める。丸ゴシックの太い字。
    _look("粘体（桃の艶・紅の縁）", "ゲームの題字", origin="Slime Rancher 2（2022年・PC・Xbox）",
          font="HGMaruGothicMPRO", style="Regular", tracking=1.02, leading=0.94,
          fill="#f02080", fillA=1.00, fillGradOn=1,
          fillGradC=["#f01070", "#f02080", "#f0f0f0"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#a00010", edgeW=0.040, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 白い丸文字に水色の太い輪、その外へ濃紺。丸ゴシックで泡のように。
    _look("しゃぼん（白に水の輪）", "ゲームの題字", origin="ぷよぷよテトリス2（2020年・Nintendo Switch）",
          font="HGMaruGothicMPRO", style="Regular", tracking=1.06, leading=1.00,
          fill="#ffffff", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#00b8dc", edgeW=0.040, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#121f52", edge2W=0.062,
          glowOn=0,
          shadowOn=1, shadowC="#0b1436", shadowX=0.004, shadowY=-0.005,
          shadowBlur=5.00, shadowOpacity=0.45,
          bandOn=0, bandEdgeOn=0),
    # 金→白→朱の三重。内側が白で外側が朱という、既存「熱血」と逆の並びにする。
    _look("陽金（白と朱の三重縁）", "ゲームの題字", origin="牧場物語 再会のミネラルタウン（2019年・Switch・PC）",
          font="Hachi Maru Pop", style="Regular", tracking=1.00, leading=0.96,
          fill="#f0b000", fillA=1.00, fillGradOn=1,
          fillGradC=["#f0b000", "#f0d040", "#f0e060"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#f0f0f0", edgeW=0.045, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#c04010", edge2W=0.070,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 生成りの丸い手書き字に煉瓦色の輪、外は白。橙の硬い影を右下へ落とす。
    _look("窯出し（生成りに煉瓦の輪）", "ゲームの題字", origin="Overcooked! 2（2018年・PC / 家庭用）",
          font="Hachi Maru Pop", style="Regular", tracking=1.00, leading=0.96,
          fill="#f4efe4", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#9a3020", edgeW=0.036, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#ffffff", edge2W=0.058,
          glowOn=0,
          shadowOn=1, shadowC="#f0a000", shadowX=0.008, shadowY=-0.010,
          shadowBlur=0.00, shadowOpacity=1.00,
          bandOn=0, bandEdgeOn=0),
    # 1930年代の漫画映画の題字。手描きの黒インク線＋真下右への硬い黒影＋黄色の地。
    _look("戯画（黄地に白抜き）", "ゲームの題字", origin="Cuphead（2017年・PC・Xbox One）",
          font="Yusei Magic", style="Regular", tracking=1.00, leading=0.94,
          fill="#f2f2f2", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#101010", edgeW=0.030, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#101010", shadowX=0.010, shadowY=-0.013,
          shadowBlur=0.00, shadowOpacity=1.00,
          bandOn=1, bandC="#f0c010", bandOpacity=1.00, bandLevel=1,
          bandPadX=0.18, bandPadY=0.13, bandRound=0.04, bandShearX=0.00,
          bandEdgeOn=0),
    _look("淡雪（淡青の明朝）", "ゲームの題字", origin="聖剣伝説3 トライアルズ オブ マナ（2020年・Switch/PS4/PC）",
          font="Shippori Mincho B1 ExtraBold", style="Regular", tracking=1.10, leading=0.96,
          fill="#c0d8f2", fillA=1.00,
          fillGradOn=1, fillGradC=["#e8ecf7", "#c0d8f2", "#7ccef4"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#0c1420", edgeW=0.028, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#0a2340", glowW=0.070, glowBlur=8.00, glowSpread=0.05,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 文字ごとの緑札。白い丸文字を1字ずつ緑の角丸札に載せる。
    _look("若葉札（文字ごとの緑札）", "ゲームの題字", origin="あつまれ どうぶつの森（2020年・Nintendo Switch）",
          font="Mochiy Pop One", style="Regular", tracking=1.12, leading=1.04,
          fill="#ffffff", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#06381f", edgeW=0.016, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#05301c", shadowX=0.004, shadowY=-0.005,
          shadowBlur=4.00, shadowOpacity=0.45,
          bandOn=1, bandC="#0a9a55", bandOpacity=0.96, bandLevel=3,
          bandPadX=0.12, bandPadY=0.12, bandRound=0.35, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#ffffff", bandEdgeW=0.007),
    # 木の看板の題字。金茶の板＋濃茶の彫り＋薄い木肌の下地、という3層だけで作る。
    _look("実り（金茶・木札の帯）", "ゲームの題字", origin="Stardew Valley（2016年・PC 他）",
          font="RocknRoll One", style="Regular", tracking=1.02, leading=0.98,
          fill="#e0a000", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#302010", edgeW=0.040, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#f0d080", bandOpacity=0.94, bandLevel=1,
          bandPadX=0.14, bandPadY=0.12, bandRound=0.16, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#a06050", bandEdgeW=0.008),
    # 氷の塊を積んだ題字。氷色の面／黒に近い輪郭／真下右にずれた菫色の硬い影。
    _look("雪嶺（氷色・紫の落ち影）", "ゲームの題字", origin="Celeste（2018年・PC・Switch 他）",
          font="Zen Maru Gothic Black", style="Regular", tracking=1.00, leading=0.96,
          fill="#70c0e0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#101020", edgeW=0.030, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#605080", shadowX=0.007, shadowY=-0.011,
          shadowBlur=0.00, shadowOpacity=1.00,
          bandOn=0, bandEdgeOn=0),
    # 土色の面に草の緑を巻き、その外へ濃い緑をもう一周。色の順が土→明るい草→暗い草。
    _look("草土（土色・草の二重縁）", "ゲームの題字", origin="Terraria（2011年・PC 他）",
          font="Mochiy Pop One", style="Regular", tracking=1.02, leading=0.94,
          fill="#a06040", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#20e060", edgeW=0.036, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#308050", edge2W=0.054,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("菫閃（桃の細罫）", "ゲームの題字", origin="ベヨネッタ3（2022年・Nintendo Switch）",
          font="Zen Old Mincho Black", style="Regular", tracking=1.04, leading=0.94,
          fill="#180f22", fillA=1.00, fillGradOn=0, fillGradAngle=0.00,
          edgeOn=1, edgeC="#f2c6e4", edgeW=0.030, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#3a1050", edge2W=0.046,
          glowOn=1, glowC="#5c2fc0", glowW=0.105, glowBlur=10.00, glowSpread=0.55,
          glowOpacity=0.70,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    # 手で描いた細長い白。縁だけをわずかに回して拡げ、なぞり線がずれた感じを作る。
    _look("宵闇（手描きの白）", "ゲームの題字", origin="リトルナイトメア2（2021年・PC／家庭用）",
          font="Yomogi", style="Regular", tracking=1.18, leading=1.02,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#15130f", edgeW=0.030, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=2.50, edgeScale=1.05, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#0a0908", shadowX=0.004, shadowY=-0.005, shadowBlur=6.00,
          shadowOpacity=0.55,
          bandOn=0, bandEdgeOn=0),
    # 痩せた明朝を広く空けて置き、縁は髪の毛ほどに留める。暗い層はにじみが持つ。
    _look("夜道（細い明朝）", "ゲームの題字", origin="夜廻（2015年・PS Vita／PC／Switch）",
          font="Noto Serif JP", style="Regular", tracking=1.30, leading=1.04,
          fill="#f0f0f0", fillA=0.96, fillGradOn=0,
          edgeOn=1, edgeC="#131313", edgeW=0.016, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.070, glowBlur=9.00, glowSpread=0.00,
          glowOpacity=0.55,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("厳粛（広い字送りの黒）", "ゲームの題字", origin="ダークソウルIII（2016年・PS4/Xbox One/PC）",
          font="Noto Serif JP", style="Regular", tracking=1.30, leading=1.02,
          fill="#0f0d0b", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#f2efe8", edgeW=0.038, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#6e6a63", glowW=0.080, glowBlur=11.00, glowSpread=0.05,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 白しか使っていない題字。字送りを広く取り、灰の細縁と淡いもやで「欠けた白」を作る。
    _look("白錆（欠けた白の字）", "ゲームの題字", origin="SILENT HILL 2（2024年・PS5／PC）",
          font="Noto Sans JP Medium", style="Regular", tracking=1.30, leading=1.02,
          fill="#efefef", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#d0d0d0", edgeW=0.022, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#1a1c1e", edge2W=0.034,
          glowOn=1, glowC="#cfd4d6", glowW=0.090, glowBlur=9.00, glowSpread=0.30,
          glowOpacity=0.45,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 黒い明朝の外側だけが白く光る、明暗を裏返した題字。
    _look("逆光（黒字に白い光）", "ゲームの題字", origin="SIREN（2003年・PS2）",
          font="Yu Mincho Demibold", style="Bold", tracking=1.16, leading=1.00,
          fill="#12100e", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#e8dcb4", edgeW=0.030, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#f0f0f0", glowW=0.105, glowBlur=9.00, glowSpread=0.50,
          glowOpacity=0.70,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 影を真下だけに落とす。横へずらさないので、字が浮かずに沈んで見える。
    _look("霊障（真下に落ちる影）", "ゲームの題字", origin="Phasmophobia（2020年・PC）",
          font="Shippori Mincho B1 ExtraBold", style="Regular", tracking=1.10, leading=0.98,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#0b0b0b", edgeW=0.028, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#0b0b0b", shadowX=0.000, shadowY=-0.012, shadowBlur=0.00,
          shadowOpacity=0.95,
          bandOn=0, bandEdgeOn=0),
    # 刷毛で塗った一色の暗赤。塗りが暗いので、明るい層は骨色の縁だけが持つ。
    _look("刷毛の赤", "ゲームの題字", origin="Layers of Fear（2016年・PC／家庭用）",
          font="HGPGyoshotai", style="Medium", tracking=1.06, leading=0.96,
          fill="#8e1408", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#efe8e2", edgeW=0.030, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#1a0603", shadowX=0.004, shadowY=-0.005, shadowBlur=5.00,
          shadowOpacity=0.55,
          bandOn=0, bandEdgeOn=0),
    # 塗りを持たせず、黒の輪と白の外輪だけで字の形を出す。中は背景が透ける。
    _look("空洞（中抜きの輪郭）", "ゲームの題字", origin="Among Us（2018年・PC / スマホ / 家庭用）",
          font="Yusei Magic", style="Regular", tracking=1.12, leading=0.98,
          fill="#ffffff", fillA=0.00, fillGradOn=0,
          edgeOn=1, edgeC="#0b0b0f", edgeW=0.024, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#f2f2f2", edge2W=0.042,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 黒の塗りに赤の細い輪を1本だけ通し、外は白。にじませない不穏。
    _look("血線（黒字に赤の輪）", "ゲームの題字", origin="Call of Duty: Modern Warfare III（2023年・PC/PS/Xbox）",
          font="HGPGothicE", style="Regular", tracking=0.94, leading=0.95,
          fill="#101216", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#e01414", edgeW=0.024, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#f0f0f0", edge2W=0.038,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 骨色の塗り、錆色の輪、外に淡い青緑。赤も黒もにじませずに不穏を出す。
    _look("錆霜（骨色・錆の輪）", "ゲームの題字", origin="Escape from Tarkov（2017年・PC）",
          font="BIZ UDPGothic", style="Bold", tracking=1.06, leading=0.95,
          fill="#cdd0c9", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#2b1e18", edgeW=0.026, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#7d8a80", edge2W=0.042,
          glowOn=1, glowC="#1a120e", glowW=0.080, glowBlur=6.0, glowSpread=0.10,
          glowOpacity=0.55,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 暗い塗りに明るい縁という逆の組み。にじませず、角のまま平たく置く。
    _look("深紅（白の角縁）", "ゲームの題字", origin="INSIDE（2016年・PC・Xbox One 他）",
          font="Noto Sans JP Black", style="Regular", tracking=1.06, leading=0.96,
          fill="#900010", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#f2f2f2", edgeW=0.030, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.070, glowBlur=7.00, glowSpread=0.00,
          glowOpacity=0.55,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("溶岩（鋼に熾火）", "ゲームの題字", origin="ディアブロIV（2023年・PC/PS5/Xbox Series X|S）",
          font="HGPSoeiPresenceEB", style="Extra-Bold", tracking=1.02, leading=0.92,
          fill="#a8adb2", fillA=1.00,
          fillGradOn=1, fillGradC=["#565b60", "#a8adb2", "#e2e6ea"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#0c0a0a", edgeW=0.022, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#8c1206", edge2W=0.034,
          glowOn=1, glowC="#f03000", glowW=0.105, glowBlur=10.00, glowSpread=0.45,
          glowOpacity=0.60,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 暗視カメラの緑。文字は白のまま、色はもや（グロー）の側だけが持つ。
    _look("暗視（緑のもや）", "ゲームの題字", origin="Outlast（2013年・PC／PS4／Xbox One）",
          font="Yu Gothic UI", style="Bold", tracking=1.06, leading=0.96,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#0b120b", edgeW=0.024, edgeRound=1, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#5e8a46", glowW=0.105, glowBlur=9.00, glowSpread=0.55,
          glowOpacity=0.70,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("蒼鉄（青緑の光）", "ゲームの題字", origin="デビル メイ クライ 5（2019年・PS4／Xbox One／PC）",
          font="HGPGothicE", style="Regular", tracking=1.00, leading=0.92,
          fill="#93a2b4", fillA=1.00,
          fillGradOn=1, fillGradC=["#3f4a58", "#93a2b4", "#e2e8f0"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#101c26", edgeW=0.026, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#8c1418", edge2W=0.038,
          glowOn=1, glowC="#10788a", glowW=0.100, glowBlur=9.00, glowSpread=0.45,
          glowOpacity=0.65,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    _look("水明（淡い水色の光）", "ゲームの題字", origin="グランブルーファンタジー ヴァーサス（2020年・PS4／PC）",
          font="Noto Serif JP", style="Regular", tracking=1.22, leading=1.02,
          fill="#eaf6fa", fillA=1.00,
          fillGradOn=1, fillGradC=["#bfe4ef", "#eaf6fa", "#ffffff"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#0a1018", edgeW=0.026, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00,
          glowOn=1, glowC="#a8dcec", glowW=0.105, glowBlur=11.00, glowSpread=0.70,
          glowOpacity=0.75,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    # 白字＋黒の硬い縁＋蛍光黄の外縁、その後ろへ紫の硬い落ち影を1層だけずらす。
    _look("塗りたて（白×蛍光黄・紫の落ち影）", "ゲームの題字", origin="スプラトゥーン3（2022年・Nintendo Switch）",
          font="Dela Gothic One", style="Regular", tracking=1.00, leading=0.92,
          fill="#f2f2f2", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#0d0d0d", edgeW=0.020, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#ece63d", edge2W=0.030,
          glowOn=0,
          shadowOn=1, shadowC="#4a20d6", shadowX=0.010, shadowY=-0.013,
          shadowBlur=0.00, shadowOpacity=1.00,
          bandOn=0, bandEdgeOn=0),
    # 桃・水・黄を通す塗りに白い太い輪、外は濃紺。舞台の照明をぼかしで足す。
    _look("彩舞台（白縁・多色の塗り）", "ゲームの題字", origin="プロジェクトセカイ カラフルステージ！（2020年・iOS / Android）",
          font="HGPSoeiKakugothicUB", style="Regular", tracking=1.02, leading=0.94,
          fill="#38c6dc", fillA=1.00,
          fillGradOn=1, fillGradC=["#f05090", "#38c6dc", "#f0c000"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#ffffff", edgeW=0.018, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#004a78", edge2W=0.030,
          glowOn=1, glowC="#00b0c0", glowW=0.090, glowBlur=8.00, glowSpread=0.35,
          glowOpacity=0.55,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 黄の塗りに水色の輪。水色は測った #40b0d0 の側で、蛍光の水色まで上げない。
    _look("黄電（黄に水色の輪）", "ゲームの題字", origin="サイバーパンク2077（2020年・PC/PS/Xbox）",
          font="HGPSoeiPresenceEB", style="Extra-Bold", tracking=1.04, leading=0.95,
          fill="#f0e412", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#0c1016", edgeW=0.018, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#3fb2d6", edge2W=0.033,
          glowOn=1, glowC="#050a10", glowW=0.085, glowBlur=5.0, glowSpread=0.10,
          glowOpacity=0.55,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 黄の面に水色の輪を回し、その外へ暗い青緑をもう一周。硬い影は使わない。
    _look("潜水灯（黄・水色の輪）", "ゲームの題字", origin="DAVE THE DIVER（2023年・PC・Switch 他）",
          font="Yu Gothic UI", style="Bold", tracking=1.02, leading=0.94,
          fill="#f0c020", fillA=1.00, fillGradOn=1,
          fillGradC=["#f0b000", "#f0c020", "#f0d020"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#10c0f0", edgeW=0.030, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#063243", edge2W=0.044,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("黒曜（白縁に朱）", "ゲームの題字", origin="ゼノブレイド3（2022年・Nintendo Switch）",
          font="BIZ UDPGothic", style="Bold", tracking=0.94, leading=0.90,
          fill="#141414", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#f5f5f3", edgeW=0.034, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#c41414", edge2W=0.056,
          glowOn=1, glowC="#0a0000", glowW=0.080, glowBlur=6.00, glowSpread=0.00,
          glowOpacity=0.40,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("冒険（青に真鍮縁）", "ゲームの題字", origin="ドラゴンクエストXI（2017年・PS4/3DS）",
          font="HGPGothicE", style="Regular", tracking=0.98, leading=0.90,
          fill="#3080d0", fillA=1.00,
          fillGradOn=1, fillGradC=["#204fae", "#3080d0", "#62b2f0"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#cf7208", edgeW=0.036, edgeRound=1, edgeOutside=1,
          edgeGradOn=1, edgeGradC=["#93300a", "#cf7208", "#f0c000"], edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#1b1206", edge2W=0.050,
          glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.005, shadowY=-0.007, shadowBlur=4.00,
          shadowOpacity=0.55,
          bandOn=0, bandEdgeOn=0),
    _look("一閃（白に朱の走り）", "ゲームの題字", origin="ウィッチャー3 ワイルドハント（2015年・PS4/Xbox One/PC）",
          font="Noto Sans JP Black", style="Regular", tracking=1.24, leading=0.94,
          fill="#f2f2f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#131316", edgeW=0.028, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.060, glowBlur=5.00, glowSpread=0.00,
          glowOpacity=0.45,
          shadowOn=1, shadowC="#d02020", shadowX=-0.009, shadowY=-0.011, shadowBlur=0.00,
          shadowOpacity=0.95,
          bandOn=0, bandEdgeOn=0),
    # 白い極太に深紅が食い込む二色構成。赤を塗りではなく縁に置いたのが実物の割合に近い。
    _look("惨劇（白に深紅の縁）", "ゲームの題字", origin="バイオハザード RE:4（2023年・PS5／Xbox Series／PC）",
          font="HGPSoeiPresenceEB", style="Extra-Bold", tracking=0.90, leading=0.88,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#b01020", edgeW=0.022, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#16070a", edge2W=0.032,
          glowOn=1, glowC="#0d0709", glowW=0.075, glowBlur=4.00, glowSpread=0.00,
          glowOpacity=0.55,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 角を落とした工業体。丸みをすべて捨て、縁も影も角のまま重ねる。
    _look("工業（角を落とした白）", "ゲームの題字", origin="Dead Space（2023年・PS5／Xbox Series／PC）",
          font="HGPSoeiKakugothicUB", style="Regular", tracking=1.04, leading=0.92,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#0c0f12", edgeW=0.020, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#5a6068", edge2W=0.030,
          glowOn=0,
          shadowOn=1, shadowC="#0c0f12", shadowX=0.008, shadowY=-0.009, shadowBlur=0.00,
          shadowOpacity=0.95,
          bandOn=0, bandEdgeOn=0),
    # 白い極太の外へ朱の輪を一本。朱は塗りに使わず、輪の側だけが持つ。
    _look("残響（白に朱の輪）", "ゲームの題字", origin="The Last of Us Part II（2024年・PS5／PC）",
          font="HGPGothicE", style="Regular", tracking=0.92, leading=0.90,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#1a1512", edgeW=0.020, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#e05030", edge2W=0.032,
          glowOn=0,
          shadowOn=1, shadowC="#140f0c", shadowX=0.006, shadowY=-0.007, shadowBlur=3.00,
          shadowOpacity=0.55,
          bandOn=0, bandEdgeOn=0),
    _look("亀裂（黒地に朱の段差）", "ゲームの題字", origin="鉄拳8（2024年・PS5／Xbox Series／PC）",
          font="BIZ UDPGothic", style="Bold", tracking=1.00, leading=0.90,
          fill="#0e1117", fillA=1.00, fillGradOn=0, fillGradAngle=0.00,
          edgeOn=1, edgeC="#d8304e", edgeW=0.030, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=5.00, edgeScale=1.06, edgeOffX=0.005, edgeOffY=-0.005,
          edge2On=1, edge2C="#f2f3f5", edge2W=0.052,
          glowOn=0, glowC="#000000", glowW=0.00, glowBlur=0.00, glowSpread=0.00,
          glowOpacity=0.00,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    _look("朱縁（白のうろこ字）", "ゲームの題字", origin="GUILTY GEAR -STRIVE-（2021年・PS4／PS5／PC）",
          font="HGPMinchoE", style="Regular", tracking=1.16, leading=0.94,
          fill="#f2f0ec", fillA=1.00, fillGradOn=0, fillGradAngle=0.00,
          edgeOn=1, edgeC="#901020", edgeW=0.042, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#23070d", edge2W=0.058,
          glowOn=0, glowC="#000000", glowW=0.00, glowBlur=0.00, glowSpread=0.00,
          glowOpacity=0.00,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    _look("筆朱（白の太縁）", "ゲームの題字", origin="DRAGON BALL FighterZ（2018年・PS4／Xbox One／PC／Nintendo Switch）",
          font="Reggae One", style="Regular", tracking=0.98, leading=0.90,
          fill="#a8121e", fillA=1.00,
          fillGradOn=1, fillGradC=["#2a0508", "#a8121e", "#d8202c"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#f4f2ee", edgeW=0.030, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#150506", edge2W=0.048,
          glowOn=1, glowC="#f09020", glowW=0.100, glowBlur=9.00, glowSpread=0.40,
          glowOpacity=0.60,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    # 橙から赤へ落ちる階調に白い輪、外は黒。硬い落ち影で重みを出す。
    _look("熔岩（橙の階調・白の輪）", "ゲームの題字", origin="パズル&ドラゴンズ（2012年・iOS / Android）",
          font="Train One", style="Regular", tracking=0.98, leading=0.90,
          fill="#f07000", fillA=1.00,
          fillGradOn=1, fillGradC=["#f05000", "#f07800", "#f0a800"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#ffffff", edgeW=0.020, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#0a0604", edge2W=0.031,
          glowOn=0,
          shadowOn=1, shadowC="#0a0604", shadowX=0.008, shadowY=-0.010,
          shadowBlur=0.00, shadowOpacity=0.95,
          bandOn=0, bandEdgeOn=0),
    # 深緑から黄緑へ抜ける階調、黒の輪、その外へ白。角ゴシックで硬く。
    _look("緑閃（黒縁に白外）", "ゲームの題字", origin="モンスターストライク（2013年・iOS / Android）",
          font="HGPGothicE", style="Regular", tracking=1.00, leading=0.92,
          fill="#2f9a42", fillA=1.00,
          fillGradOn=1, fillGradC=["#84c246", "#3aa244", "#1d7a3c"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#000000", edgeW=0.024, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#ffffff", edge2W=0.044,
          glowOn=1, glowC="#000000", glowW=0.075, glowBlur=5.00, glowSpread=0.00,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 平らな一色の朱赤を、白い細輪と暗い外輪で挟む。角は落とさない（edgeRound=0）。
    _look("紅刃（角・平塗り）", "ゲームの題字", origin="VALORANT（2020年・PC）",
          font="BIZ UDPGothic", style="Bold", tracking=1.08, leading=0.95,
          fill="#ef4a56", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#ffffff", edgeW=0.022, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#1a0a10", edge2W=0.040,
          glowOn=1, glowC="#000000", glowW=0.070, glowBlur=4.0, glowSpread=0.00,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 冷たい白の角字に鋼の細輪、右下へ硬い落ち影。ぼかしを一切使わない層構成。
    _look("号令（白の型・硬い影）", "ゲームの題字", origin="HELLDIVERS 2（2024年・PC/PS5）",
          font="HGPSoeiKakugothicUB", style="Regular", tracking=1.14, leading=0.95,
          fill="#eceef6", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#0f1220", edgeW=0.024, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#7a8296", edge2W=0.030,
          glowOn=0,
          shadowOn=1, shadowC="#05060c", shadowX=0.010, shadowY=-0.012,
          shadowBlur=0.00, shadowOpacity=1.00,
          bandOn=0, bandEdgeOn=0),
    # 黒の極太を広く送り、鋼→白の二重の輪と硬い落ち影。角は落とさない。
    _look("黒角（鋼の輪・硬い影）", "ゲームの題字", origin="レインボーシックス シージ（2015年・PC/PS/Xbox）",
          font="Noto Sans JP Black", style="Regular", tracking=1.20, leading=0.95,
          fill="#121212", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#9aa0a8", edgeW=0.022, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#f4f4f4", edge2W=0.034,
          glowOn=0,
          shadowOn=1, shadowC="#050505", shadowX=0.010, shadowY=-0.012,
          shadowBlur=0.00, shadowOpacity=1.00,
          bandOn=0, bandEdgeOn=0),
    # 白い明朝を朱の細線で囲い、その外に黒赤を巻く。発光も影も持たせず乾いた見え方にする。
    _look("朱裂（白の明朝・朱の細縁）", "ゲームの題字", origin="Hades（2020年・PC・Switch 他）",
          font="Noto Serif JP Black", style="Regular", tracking=1.04, leading=0.94,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#b00000", edgeW=0.018, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#200000", edge2W=0.029,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("鋼青（銀の片光）", "ゲームの題字", origin="ファイナルファンタジーVII リメイク（2020年・PS4）",
          font="HGPMinchoE", style="Regular", tracking=1.16, leading=0.98,
          fill="#2c3a42", fillA=1.00,
          fillGradOn=1, fillGradC=["#0a0f12", "#2c3a42", "#66787f"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#eef3f5", edgeW=0.026, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=-0.004, edgeOffY=0.004,
          edge2On=1, edge2C="#0b1418", edge2W=0.040,
          glowOn=1, glowC="#7fb3c4", glowW=0.075, glowBlur=9.00, glowSpread=0.15,
          glowOpacity=0.45,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("褪金（枯れた金）", "ゲームの題字", origin="エルデンリング（2022年・PS5/Xbox Series X|S/PC）",
          font="Zen Old Mincho Black", style="Regular", tracking=1.14, leading=0.96,
          fill="#c0a070", fillA=1.00,
          fillGradOn=1, fillGradC=["#8f7440", "#c0a070", "#e8d6ac"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#2a2118", edgeW=0.026, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#000810", shadowX=0.006, shadowY=-0.008, shadowBlur=0.00,
          shadowOpacity=0.85,
          bandOn=0, bandEdgeOn=0),
    _look("鉛金（石金に鉛縁）", "ゲームの題字", origin="バルダーズ・ゲート3（2023年・PC/PS5/Xbox Series X|S）",
          font="Klee One SemiBold", style="Regular", tracking=1.06, leading=0.94,
          fill="#a06c3c", fillA=1.00,
          fillGradOn=1, fillGradC=["#4a2a14", "#a06c3c", "#d2b28a"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#5b6165", edgeW=0.032, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#14171a", edge2W=0.048,
          glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.004, shadowY=-0.006, shadowBlur=5.00,
          shadowOpacity=0.50,
          bandOn=0, bandEdgeOn=0),
    # 煤から骨の色へ一方向に上がるだけの階調。金属の照り返し（暗→明→暗）にはしない。
    _look("錆鉄（煤から骨へ）", "ゲームの題字", origin="Amnesia: The Bunker（2023年・PC／家庭用）",
          font="Dela Gothic One", style="Regular", tracking=0.94, leading=0.88,
          fill="#a07040", fillA=1.00, fillGradOn=1,
          fillGradC=["#302010", "#805030", "#b08050", "#efefe6"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#1a1008", edgeW=0.020, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#0f0a05", shadowX=0.005, shadowY=-0.006, shadowBlur=4.00,
          shadowOpacity=0.60,
          bandOn=0, bandEdgeOn=0),
    _look("錆鋼（明朝）", "ゲームの題字", origin="SEKIRO: SHADOWS DIE TWICE（2019年・PS4／Xbox One／PC）",
          font="Shippori Mincho B1 ExtraBold", style="Regular", tracking=1.06, leading=0.96,
          fill="#b8b4ab", fillA=1.00,
          fillGradOn=1, fillGradC=["#4f4b45", "#b8b4ab", "#e4e0d4", "#b08a40"],
          fillGradAngle=0.00,
          edgeOn=1, edgeC="#12100d", edgeW=0.026, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00,
          glowOn=0, glowC="#000000", glowW=0.00, glowBlur=0.00, glowSpread=0.00,
          glowOpacity=0.00,
          shadowOn=1, shadowC="#0b0a08", shadowX=0.008, shadowY=-0.010, shadowBlur=6.00,
          shadowOpacity=0.70,
          bandOn=0, bandEdgeOn=0),
    _look("双炎（青と朱の縁）", "ゲームの題字", origin="THE KING OF FIGHTERS XV（2022年・PS4／PS5／Xbox Series／PC）",
          font="HGPSoeiPresenceEB", style="Extra-Bold", tracking=1.02, leading=0.92,
          fill="#b0b0c0", fillA=1.00,
          fillGradOn=1, fillGradC=["#4c4c60", "#b0b0c0", "#e6e6f0"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#12121c", edgeW=0.020, edgeRound=0, edgeOutside=1,
          edgeGradOn=1, edgeGradC=["#8c0c0c", "#12121c", "#1c1cb0"], edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#08080e", edge2W=0.030,
          glowOn=0, glowC="#000000", glowW=0.00, glowBlur=0.00, glowSpread=0.00,
          glowOpacity=0.00,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    _look("鈍銀（朱の縁・燃え影）", "ゲームの題字", origin="仁王2（2020年・PS4／PC）",
          font="Dela Gothic One", style="Regular", tracking=0.98, leading=0.88,
          fill="#a0a0a0", fillA=1.00,
          fillGradOn=1, fillGradC=["#4a4a4a", "#a0a0a0", "#e0e0e0"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#180404", edgeW=0.019, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#c40000", edge2W=0.029,
          glowOn=0, glowC="#000000", glowW=0.00, glowBlur=0.00, glowSpread=0.00,
          glowOpacity=0.00,
          shadowOn=1, shadowC="#401000", shadowX=0.010, shadowY=-0.012, shadowBlur=0.00,
          shadowOpacity=0.90,
          bandOn=0, bandEdgeOn=0),
    # 紅玉の面のような赤い階調に、金の細い輪。外は黒に近い赤茶で締める。
    _look("紅玉（金の縁）", "ゲームの題字", origin="ポケットモンスター スカーレット・バイオレット（2022年・Nintendo Switch）",
          font="HGPSoeiPresenceEB", style="Extra-Bold", tracking=0.98, leading=0.92,
          fill="#c01018", fillA=1.00,
          fillGradOn=1, fillGradC=["#8a0a14", "#c01018", "#e04828"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#e8dc10", edgeW=0.022, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#1a0208", edge2W=0.038,
          glowOn=1, glowC="#000000", glowW=0.070, glowBlur=6.00, glowSpread=0.00,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 細い字を広く送り、下だけ青みの灰へ落とす。既存の金属は全部が太字なので、薄い金属を足す。
    _look("冷銀（細字・青み）", "ゲームの題字", origin="Halo Infinite（2021年・PC/Xbox）",
          font="Noto Sans JP Medium", style="Regular", tracking=1.28, leading=1.05,
          fill="#f2f4f8", fillA=1.00,
          fillGradOn=1, fillGradC=["#7c8492", "#c4cad6", "#f2f4f8"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#0e141c", edgeW=0.020, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#0b1119", glowW=0.070, glowBlur=7.0, glowSpread=0.05,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 太い明朝を黒で置き、鋼色と白の二重の輪。金属の枠で唯一の明朝＋暗い塗り。
    _look("黒銘（明朝・鋼の輪）", "ゲームの題字", origin="ARMORED CORE VI（2023年・PC/PS/Xbox）",
          font="Shippori Mincho B1 ExtraBold", style="Regular", tracking=1.12, leading=1.00,
          fill="#14161a", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#b9c0c8", edgeW=0.026, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#f2f4f6", edge2W=0.040,
          glowOn=0,
          shadowOn=1, shadowC="#05070a", shadowX=0.006, shadowY=-0.008,
          shadowBlur=0.00, shadowOpacity=0.90,
          bandOn=0, bandEdgeOn=0),
    # 金は発光ではなく、下が濃く上が淡い階調と、ほぼ硬い黒赤の落ち影で出す。
    _look("金焔（金の階調・黒赤の落ち影）", "ゲームの題字", origin="Vampire Survivors（2022年・PC・Switch 他）",
          font="Zen Old Mincho Black", style="Regular", tracking=1.02, leading=0.92,
          fill="#f0c000", fillA=1.00, fillGradOn=1,
          fillGradC=["#e07000", "#f0c000", "#f0f060"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#401010", edgeW=0.028, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#200000", shadowX=0.008, shadowY=-0.011,
          shadowBlur=1.00, shadowOpacity=0.95,
          bandOn=0, bandEdgeOn=0),
    # 黒いにじみが面積の四割を占める題字。金は縁の一本だけに置く。
    _look("金蝕（黒にじみに金の縁）", "ゲームの題字", origin="零 〜月蝕の仮面〜（2023年・Switch／PS／Xbox／PC）",
          font="Zen Old Mincho Black", style="Regular", tracking=1.08, leading=0.94,
          fill="#efeae0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#6b5322", edgeW=0.026, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#000000", glowW=0.110, glowBlur=8.00, glowSpread=0.35,
          glowOpacity=0.70,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("金罫（濃紺の光）", "ゲームの題字", origin="モンスターハンターライズ（2021年・Nintendo Switch／PC）",
          font="Zen Antique", style="Regular", tracking=1.08, leading=0.96,
          fill="#f0efe0", fillA=1.00, fillGradOn=0, fillGradAngle=0.00,
          edgeOn=1, edgeC="#08090c", edgeW=0.024, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#c9b071", edge2W=0.036,
          glowOn=1, glowC="#103080", glowW=0.100, glowBlur=8.00, glowSpread=0.30,
          glowOpacity=0.60,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    # 朱の太字に生成り黄の縁、外は焦げ茶。落ち影は硬いまま右下へ。
    _look("祭囃子（朱に生成りの縁）", "ゲームの題字", origin="太鼓の達人 ドンカッ！と大盛り 七代目（2023年・アーケード）",
          font="Reggae One", style="Regular", tracking=1.00, leading=0.92,
          fill="#e01a10", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#f7efb8", edgeW=0.028, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#3a0c04", edge2W=0.046,
          glowOn=0,
          shadowOn=1, shadowC="#2a0a02", shadowX=0.008, shadowY=-0.010,
          shadowBlur=0.00, shadowOpacity=0.95,
          bandOn=0, bandEdgeOn=0),
    _look("苔石（琥珀の縁）", "ゲームの題字", origin="モンスターハンターワイルズ（2025年・PS5/Xbox Series X|S/PC）",
          font="Zen Antique", style="Regular", tracking=1.12, leading=0.98,
          fill="#c6c8bc", fillA=1.00,
          fillGradOn=1, fillGradC=["#8b8f80", "#c6c8bc", "#f0f0e6"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#2d3128", edgeW=0.030, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#c07a12", edge2W=0.046,
          glowOn=1, glowC="#141810", glowW=0.075, glowBlur=7.00, glowSpread=0.05,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("金線（白に金の細縁）", "ゲームの題字", origin="真・女神転生V（2021年・Nintendo Switch）",
          font="Noto Serif JP Bold", style="Regular", tracking=1.20, leading=1.00,
          fill="#eceae4", fillA=1.00,
          fillGradOn=1, fillGradC=["#dcd8cf", "#eceae4", "#fbfaf7"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#b0a070", edgeW=0.020, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#332c19", edge2W=0.030,
          glowOn=1, glowC="#2a2415", glowW=0.080, glowBlur=9.00, glowSpread=0.10,
          glowOpacity=0.60,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("灰重ね（淡灰の落ち影）", "ゲームの題字", origin="オクトパストラベラーII（2023年・Nintendo Switch/PS5/PS4/PC）",
          font="Yu Mincho Demibold", style="Bold", tracking=1.10, leading=0.98,
          fill="#14120f", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#f4f2ec", edgeW=0.030, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#b6b6b6", shadowX=0.012, shadowY=-0.014, shadowBlur=0.00,
          shadowOpacity=1.00,
          bandOn=0, bandEdgeOn=0),
    # 極太なのに色を一切張らない題字。灰緑一色の平らな塗りだけで作る。
    # 塗りが中間の明るさなので、白背景に耐える暗い層は細い縁とにじみが持つ。
    _look("灰緑（平らな極太）", "ゲームの題字", origin="アラン ウェイク 2（2023年・PS5／Xbox Series／PC）",
          font="BIZ UDPGothic", style="Bold", tracking=0.96, leading=0.88,
          fill="#9fb0aa", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#0d1211", edgeW=0.024, edgeRound=0, edgeOutside=1, edgeGradOn=0,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#0d1211", glowW=0.075, glowBlur=7.00, glowSpread=0.10,
          glowOpacity=0.55,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("白刃（鋼青の細縁）", "ゲームの題字", origin="Mortal Kombat 1（2023年・PS5／Xbox Series／Nintendo Switch／PC）",
          font="Yu Mincho Demibold", style="Bold", tracking=1.12, leading=0.98,
          fill="#f6f7f8", fillA=1.00, fillGradOn=0, fillGradAngle=0.00,
          edgeOn=1, edgeC="#2c5a7d", edgeW=0.018, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#0b1017", edge2W=0.028,
          glowOn=0, glowC="#000000", glowW=0.00, glowBlur=0.00, glowSpread=0.00,
          glowOpacity=0.00,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=0, bandEdgeOn=0),
    # 生成りの石色に、翡翠色の縁を1本。外は深い緑で締める。
    _look("翠石（生成りに翡翠の縁）", "ゲームの題字", origin="ゼルダの伝説 ティアーズ オブ ザ キングダム（2023年・Nintendo Switch）",
          font="Zen Old Mincho Black", style="Regular", tracking=1.08, leading=0.98,
          fill="#f2f0d2", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#35bd86", edgeW=0.028, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#0e3b2a", edge2W=0.048,
          glowOn=1, glowC="#08251a", glowW=0.070, glowBlur=7.00, glowSpread=0.00,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 濃い青灰の塗りに橙の輪、その外に白。暗い塗りなので明るい層を2枚持たせる。
    _look("炭青（橙の輪）", "ゲームの題字", origin="オーバーウォッチ2（2022年・PC/PS/Xbox/Switch）",
          font="Noto Sans JP", style="Bold", tracking=1.12, leading=1.00,
          fill="#333a48", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#e86a14", edgeW=0.026, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#f2f4f6", edge2W=0.038,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 塗りを透かして（fillA<1）背景を薄く通す。色ではなく不透明度で2つ目の階調を作る。
    _look("薄墨（透ける濃色・広い送り）", "ゲームの題字", origin="Destiny 2（2017年・PC/PS/Xbox）",
          font="Noto Sans JP", style="Regular", tracking=1.30, leading=1.05,
          fill="#221426", fillA=0.85, fillGradOn=0,
          edgeOn=1, edgeC="#e6e4ea", edgeW=0.022, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#9a94a2", edge2W=0.034,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 極細を目一杯広く送り、暗い暈だけを敷く。二重縁を持たない静かな層構成。
    _look("静墨（極細・広い送り）", "ゲームの題字", origin="Starfield（2023年・PC/Xbox）",
          font="Noto Sans JP Light", style="Regular", tracking=1.34, leading=1.08,
          fill="#14161a", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#f0f2f5", edgeW=0.020, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#0a0c10", glowW=0.060, glowBlur=8.0, glowSpread=0.00,
          glowOpacity=0.45,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 高低差の大きい明朝を広く送り、彫り込んだ銀の細線と黒の外周だけで立たせる。
    _look("骨白（細い明朝・銀の線）", "ゲームの題字", origin="Hollow Knight（2017年・PC・Switch 他）",
          font="HGPMinchoE", style="Regular", tracking=1.30, leading=1.06,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#808080", edgeW=0.012, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=1, edge2C="#101010", edge2W=0.026,
          glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 白い飾り明朝を、冷たい灰の細縁と同じ色のやわらかい影だけで浮かせる。
    _look("銀葉（白の飾り明朝・灰の影）", "ゲームの題字", origin="パルワールド（2024年・PC・Xbox）",
          font="Shippori Mincho B1 ExtraBold", style="Regular", tracking=1.10, leading=1.00,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#607070", edgeW=0.024, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#607070", shadowX=0.006, shadowY=-0.010,
          shadowBlur=5.00, shadowOpacity=0.85,
          bandOn=0, bandEdgeOn=0),
    # 角を落とした四角い字を上限まで広く送り、細い角の黒縁1本だけで持たせる。
    _look("白角（極広の字送り）", "ゲームの題字", origin="Journey（2012年・PS3・PC 他）",
          font="MS Gothic", style="Regular", tracking=1.34, leading=1.08,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#101010", edgeW=0.020, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    _look("号外（紅の帯）", "ゲームの題字", origin="ペルソナ5（2016年・PS4/PS3）",
          font="Dela Gothic One", style="Regular", tracking=0.96, leading=0.92,
          fill="#f4f4f2", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#1a0e0e", edgeW=0.024, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=0,
          shadowOn=1, shadowC="#180a0a", shadowX=0.010, shadowY=-0.013, shadowBlur=0.00,
          shadowOpacity=1.00,
          bandOn=1, bandC="#b8000f", bandOpacity=0.90, bandLevel=1, bandPadX=0.22,
          bandPadY=0.14, bandRound=0.00, bandShearX=0.00, bandEdgeOn=0),
    _look("罫札（白地に黒枠）", "ゲームの題字", origin="オクトパストラベラー（2018年・Nintendo Switch）",
          font="Noto Serif JP Black", style="Regular", tracking=1.22, leading=1.00,
          fill="#111111", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0,
          glowOn=0,
          shadowOn=0,
          bandOn=1, bandC="#f2f0ea", bandOpacity=0.94, bandLevel=1, bandPadX=0.10,
          bandPadY=0.08, bandRound=0.00, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#111111", bandEdgeW=0.010),
    # 縁も影も一切持たない平らな白を、隙の無い黒い板に載せる。板が暗い層を全部持つ。
    _look("黒札（黒帯に白の極太）", "ゲームの題字", origin="Dead by Daylight（2016年・PC／家庭用）",
          font="Noto Sans JP Black", style="Regular", tracking=0.94, leading=0.86,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#0a0a0a", bandOpacity=0.90, bandLevel=1, bandPadX=0.16,
          bandPadY=0.08, bandRound=0.00, bandShearX=0.00, bandEdgeOn=0),
    _look("炭板（橙の細罫）", "ゲームの題字", origin="ストリートファイター6（2023年・PS5／Xbox Series／PC）",
          font="HGPSoeiKakugothicUB", style="Regular", tracking=0.96, leading=0.94,
          fill="#e6e6e6", fillA=1.00, fillGradOn=0, fillGradAngle=0.00,
          edgeOn=1, edgeC="#0e0f11", edgeW=0.022, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeGradAngle=0.00,
          edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, edge2C="#000000", edge2W=0.00,
          glowOn=0, glowC="#000000", glowW=0.00, glowBlur=0.00, glowSpread=0.00,
          glowOpacity=0.00,
          shadowOn=0, shadowC="#000000", shadowX=0.00, shadowY=0.00, shadowBlur=0.00,
          shadowOpacity=0.00,
          bandOn=1, bandC="#15171b", bandOpacity=0.92, bandLevel=1, bandPadX=0.16,
          bandPadY=0.11, bandRound=0.05, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#f06000", bandEdgeW=0.007),
    # 傾いた黒い座に白い丸文字を載せ、座のまわりへ白い細枠を1本回す。
    _look("黒座（傾いた黒の台）", "ゲームの題字", origin="スーパーマリオパーティ（2018年・Nintendo Switch）",
          font="RocknRoll One", style="Regular", tracking=1.04, leading=0.98,
          fill="#ffffff", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#050505", bandOpacity=0.94, bandLevel=1,
          bandPadX=0.22, bandPadY=0.16, bandRound=0.45, bandShearX=-0.12,
          bandEdgeOn=1, bandEdgeC="#ffffff", bandEdgeW=0.010),
    # 橙の板に濃紺の字。帯は行ごとではなく全体（bandLevel=0）で1枚の板にし、白の細い枠を回す。
    _look("橙板（濃紺の字）", "ゲームの題字", origin="Counter-Strike 2（2023年・PC）",
          font="Yu Gothic UI", style="Bold", tracking=1.10, leading=1.00,
          fill="#111c28", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#e08414", bandOpacity=1.00, bandLevel=0,
          bandPadX=0.22, bandPadY=0.16, bandRound=0.08, bandShearX=0.10,
          bandEdgeOn=1, bandEdgeC="#f2f4f6", bandEdgeW=0.006),
    # 黒に近い帯へ細い白字。枠だけ淡い水色にして、暗い板の輪郭を1本だけ立てる。
    _look("暗幕（細字・水色の枠）", "ゲームの題字", origin="タイタンフォール2（2016年・PC/PS4/Xbox One）",
          font="Noto Sans JP DemiLight", style="Regular", tracking=1.26, leading=1.08,
          fill="#f2f4f6", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#101215", bandOpacity=0.90, bandLevel=1,
          bandPadX=0.18, bandPadY=0.13, bandRound=0.02, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#b6d6e6", bandEdgeW=0.006),
    # 角の立った板に黒字を置く。縁は引かず、板の色と細い枠線だけで成立させる。
    _look("標示（山吹の板・黒字）", "ゲームの題字", origin="8番出口（2023年・PC・Switch 他）",
          font="Noto Sans JP Medium", style="Regular", tracking=1.22, leading=1.06,
          fill="#101010", fillA=1.00, fillGradOn=0,
          edgeOn=0, edge2On=0, glowOn=0, shadowOn=0,
          bandOn=1, bandC="#e0c030", bandOpacity=1.00, bandLevel=1,
          bandPadX=0.18, bandPadY=0.14, bandRound=0.00, bandShearX=0.00,
          bandEdgeOn=1, bandEdgeC="#202000", bandEdgeW=0.008),
    # 古い遊技場の看板。生成りの面を深い碧の太縁で囲い、下にわずかに滲む影を敷く。
    _look("深碧（生成り・太い縁）", "ゲームの題字", origin="Balatro（2024年・PC・Switch 他）",
          font="Reggae One", style="Regular", tracking=0.98, leading=0.94,
          fill="#f0f0e0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#305050", edgeW=0.046, edgeRound=1, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#000000", shadowX=0.006, shadowY=-0.010,
          shadowBlur=3.00, shadowOpacity=0.80,
          bandOn=0, bandEdgeOn=0),
    # 点で組んだ字を太い角の黒縁で囲うだけ。落ち影は使わず、縁だけで背景から切る。
    _look("角ドット（白・太い黒縁）", "ゲームの題字", origin="UNDERTALE（2015年・PC・Switch 他）",
          font="DotGothic16", style="Regular", tracking=1.06, leading=1.08,
          fill="#f0f0f0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#000000", edgeW=0.042, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0, shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 灰の角字＋黒の角縁＋真下右へ硬く落ちる濃灰。石を積んだ看板の見え方。
    _look("石塊（灰の角字・黒の角縁）", "ゲームの題字", origin="Minecraft（2011年・PC 他）",
          font="HGPSoeiKakugothicUB", style="Regular", tracking=1.00, leading=0.94,
          fill="#c0b0b0", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#000000", edgeW=0.028, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0, glowOn=0,
          shadowOn=1, shadowC="#303030", shadowX=0.009, shadowY=-0.013,
          shadowBlur=0.00, shadowOpacity=1.00,
          bandOn=0, bandEdgeOn=0),
    _look("刻碑（縦・彫りの灰）", "ゲームの題字", origin="The Elder Scrolls V: Skyrim（2011年・PS3/Xbox 360/PC）",
          font="Yu Mincho Demibold", style="Bold", tracking=1.14, leading=1.04,
          vertical=1, cx=0.820, cy=0.560,
          fill="#4a4d50", fillA=1.00,
          fillGradOn=1, fillGradC=["#1a1c1e", "#4a4d50", "#8b9094"], fillGradAngle=0.00,
          edgeOn=1, edgeC="#c9ced2", edgeW=0.030, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=-0.003, edgeOffY=0.003,
          edge2On=1, edge2C="#0b0c0d", edge2W=0.046,
          glowOn=1, glowC="#000000", glowW=0.070, glowBlur=7.00, glowSpread=0.00,
          glowOpacity=0.50,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
    # 縦に高い極太を黒のまま置き、白の輪と白い暈で浮かせる。縦組みの枠は太い字が2件目。
    _look("黒柱（縦・白く光る）", "ゲームの題字", origin="Apex Legends（2019年・PC/PS/Xbox）",
          font="Dela Gothic One", style="Regular", tracking=0.92, leading=0.92, vertical=1,
          fill="#0d0d0d", fillA=1.00, fillGradOn=0,
          edgeOn=1, edgeC="#f4f4f4", edgeW=0.026, edgeRound=0, edgeOutside=1,
          edgeGradOn=0, edgeAngle=0.00, edgeScale=1.00, edgeOffX=0.00, edgeOffY=0.00,
          edge2On=0,
          glowOn=1, glowC="#ffffff", glowW=0.070, glowBlur=6.0, glowSpread=0.10,
          glowOpacity=0.45,
          shadowOn=0, bandOn=0, bandEdgeOn=0),
]

LOOK_SAMPLE = "サンプル"

# 割り当ての分類。画面でもこの順に並べる。
# 当たる順でもあるため、下にあるものほど強い（後のruleが前のruleを上書きする）。
CAT_ORDER = ["定番", "かわいい・ポップ", "こども・ベビー", "手書き・ゆるい",
             "自然・やわらか", "色気・大人", "こわがり・弱気", "こわい・不穏",
             "光る・目立つ", "迫力・極太", "金属・つや", "和・レトロ印刷",
             "上質・現代", "帯・テロップ", "レトロ・ゲーム", "縦書き",
             "ゲームの題字",
             "話者", "感情", "画面の役割", "動き",
             "位置"]

# 意味の目印にも [名前] で呼べる短い名前を付ける。記号のほうが速いが、
# 思い出せないときに名前で書けると表を見に行かずに済む。
RULE_KEYS = {
    "相手・ゲスト": "相手", "もう一人": "もう一人",
    "驚き": "驚き", "絶叫": "絶叫", "笑い": "笑い", "大爆笑": "大爆笑",
    "小声": "小声", "心の声": "心の声", "困惑": "困惑",
    "見出し": "見出し", "ニュース風": "ニュース風", "煽り": "煽り",
    "リスナーのコメント": "コメント", "ギフト": "ギフト",
    "ナレーション": "ナレーション", "引用・回想": "引用",
    "弾む": "弾む", "揺れる": "揺れる",
    "画面の上へ": "上", "画面の下へ": "下",
}

CATS = {
    "相手・ゲスト": "話者", "もう一人": "話者",
    "驚き": "感情", "絶叫": "感情", "笑い": "感情", "大爆笑": "感情",
    "小声": "感情", "心の声": "感情", "困惑": "感情",
    "見出し": "画面の役割", "ニュース風": "画面の役割", "煽り": "画面の役割",
    "リスナーのコメント": "画面の役割", "ギフト": "画面の役割",
    "ナレーション": "画面の役割", "引用・回想": "画面の役割",
    "弾む": "動き", "揺れる": "動き",
    "画面の上へ": "位置", "画面の下へ": "位置",
}

# 見た目のプリセットは [名前] で呼ぶ。記号だと数が足りず、繰り返しの回数も数えにくい。
# 括弧の中に書く短い名前をここで決める。表示名（丸括弧つき）でも呼べる。
LOOK_KEYS = {
    "標準（白・黒縁・ぼかし）": "標準",
    "極太・二重縁": "極太",
    "縁なし・ぼかしだけ": "縁なし",
    "ミニマル（ごく薄い影）": "ミニマル",
    "ドン！（超極太）": "ドン",
    "かわいい（丸ゴシック）": "かわいい",
    "パステル": "パステル",
    "ポップ（創英角ポップ）": "ポップ",
    "アメコミ風": "アメコミ",
    "ネオン（発光）": "ネオン",
    "キラキラ": "キラキラ",
    "熱血（三重縁）": "熱血",
    "サイバー": "サイバー",
    "氷": "氷",
    "おしゃれ（細ゴシック）": "おしゃれ",
    "高級感（明朝）": "高級感",
    "和風（墨）": "和風",
    "モノトーン": "モノトーン",
    "シネマ字幕": "シネマ",
    "筆文字（行書）": "筆文字",
    "賞状（正楷書）": "賞状",
    "教科書体": "教科書",
    "こども向け": "こども",
    "森": "森",
    "夕暮れ": "夕暮れ",
    "帯（行ごと・角丸）": "帯",
    "ニュース（紺帯）": "ニュース",
    "ゲーム実況（青帯）": "ゲーム",
    "斜め帯": "斜め帯",
    "注意（黄帯）": "注意",
    "帯（単語ごと）": "帯単語",
    "帯（文字ごと）": "帯文字",
    "縦書き": "縦書き",
    "縦書き（明朝）": "縦明朝",
    "レトロ・落ち影": "レトロ",
    "メタル": "メタル",
    "ホラー（にじむ赤）": "ホラー",
    "ドット絵（8bit）": "ドット絵",
    "ダメージ数字": "ダメージ",
    "日付スタンプ": "日付",
    "ターミナル": "端末",
    "禁止（赤）": "禁止",
    "荒野（無彩色・極太）": "荒野",
    "血染め（にじむ血）": "血染め",
    "決勝（傾き帯）": "決勝",
    "暗闇（沈む赤）": "暗闇",
    "蛍光（黒縁）": "蛍光",
    "遺跡（砂色・古紙）": "遺跡",
    "原色ドット（画面枠つき）": "原色ドット",
    "筐体（蛍光・硬い斜め影）": "筐体",
    "落ちもの（まる文字・弾む）": "落ちもの",
    "リズム（白×蛍光）": "リズム",
    "ほのぼの（太い白縁）": "ほのぼの",
    "必殺（黄×赤・斜め帯）": "必殺",
    "宇宙（冷たい白青）": "宇宙",
    "毒色（マゼンタ×シアン）": "毒色",
    "鋼鉄（角・赤縁）": "鋼鉄",
    "戦場（砂・無彩色）": "戦場",
    "加速（斜め帯・蛍光）": "加速",
    "投影（半透明）": "投影",
    "黒金（沈んだ金）": "黒金",
    "朱印（金字・朱縁）": "朱印",
    "白銀（明朝）": "白銀",
    "怪談（にじむ黒）": "怪談",
    "大河（墨帯に金）": "大河",
    "神威（紫金）": "神威",
    "純金（表彰）": "純金",
    "白金（記録）": "白金",
    "古銅（殿堂）": "古銅",
    "玉虫（記念）": "玉虫",
    "茜空（夕景）": "茜空",
    "鏡面（クローム）": "鏡面",
    "黒鉄（ガンメタ）": "黒鉄",
    "大看板": "大看板",
    "立体抜き": "立体",
    "地響き": "地響き",
    "うねり": "うねり",
    "段差": "段差",
    "傾き縁": "傾き縁",
    "額縁": "額縁",
    "手書きツッコミ": "ツッコミ",
    "ひとりごと": "ひとりごと",
    "ゆるふわ実況": "ゆるふわ",
    "はずむ": "はずむ",
    "シトラス": "シトラス",
    "まる座布団": "座布団",
    "シール": "シール",
    "昭和看板": "昭和看板",
    "墨臙脂": "墨臙脂",
    "和綴じ": "和綴じ",
    "鉛筆手帳": "鉛筆",
    "献立札": "献立",
    "版ズレ": "版ズレ",
    "暁藤": "暁藤",
    "セクシー（艶）": "セクシー",
    "色っぽい（紅）": "色っぽい",
    "アダルト（黒に金）": "アダルト",
    "女性的（桜）": "女性的",
    "ルージュ（口紅）": "ルージュ",
    "シルク（艶の階調）": "シルク",
    "妖艶（桃のネオン）": "妖艶",
    "子供っぽい（クレヨン）": "子供",
    "赤ちゃん（ミルク）": "赤ちゃん",
    "よちよち（水色）": "よちよち",
    "おえかき（クレヨン線）": "おえかき",
    "つみき（原色）": "つみき",
    "ほっぺ（もちもち）": "ほっぺ",
    "おびえている（ふるえ）": "おびえ",
    "おどおど（小さく）": "おどおど",
    "泣きそう（うるむ）": "泣きそう",
    "冷や汗（血の気が引く）": "冷や汗",
    "消え入りそう（薄れる）": "消え入り",
    "現代的（うすい帯）": "現代的",
    "上質（余白の細字）": "上質",
    "最先端（画面の表示）": "最先端",
    "雑誌（白地に黒）": "雑誌",
    "モード（広い字送り）": "モード",
    "カード（白い錠剤）": "カード",

    # ---- ゲームの題字から起こした第2弾（90件）
    "号外（紅の帯）": "号外",
    "罫札（白地に黒枠）": "罫札",
    "黒曜（白縁に朱）": "黒曜",
    "冒険（青に真鍮縁）": "冒険",
    "一閃（白に朱の走り）": "一閃",
    "溶岩（鋼に熾火）": "溶岩",
    "厳粛（広い字送りの黒）": "厳粛",
    "鋼青（銀の片光）": "鋼青",
    "褪金（枯れた金）": "褪金",
    "鉛金（石金に鉛縁）": "鉛金",
    "苔石（琥珀の縁）": "苔石",
    "金線（白に金の細縁）": "金線",
    "灰重ね（淡灰の落ち影）": "灰重ね",
    "淡雪（淡青の明朝）": "淡雪",
    "刻碑（縦・彫りの灰）": "刻碑",
    "惨劇（白に深紅の縁）": "惨劇",
    "白錆（欠けた白の字）": "白錆",
    "黒札（黒帯に白の極太）": "黒札",
    "工業（角を落とした白）": "工業",
    "暗視（緑のもや）": "暗視",
    "金蝕（黒にじみに金の縁）": "金蝕",
    "逆光（黒字に白い光）": "逆光",
    "宵闇（手描きの白）": "宵闇",
    "霊障（真下に落ちる影）": "霊障",
    "錆鉄（煤から骨へ）": "錆鉄",
    "残響（白に朱の輪）": "残響",
    "灰緑（平らな極太）": "灰緑",
    "玩具箱（赤いズレ影）": "玩具",
    "夜道（細い明朝）": "夜道",
    "刷毛の赤": "刷毛",
    "炭板（橙の細罫）": "炭板",
    "亀裂（黒地に朱の段差）": "亀裂",
    "錆鋼（明朝）": "錆鋼",
    "蒼鉄（青緑の光）": "蒼鉄",
    "菫閃（桃の細罫）": "菫閃",
    "朱縁（白のうろこ字）": "朱縁",
    "双炎（青と朱の縁）": "双炎",
    "白のにじみ（黒字）": "白にじみ",
    "金罫（濃紺の光）": "金罫",
    "鈍銀（朱の縁・燃え影）": "鈍銀",
    "白刃（鋼青の細縁）": "白刃",
    "筆朱（白の太縁）": "筆朱",
    "水明（淡い水色の光）": "水明",
    "若葉札（文字ごとの緑札）": "若葉札",
    "塗りたて（白×蛍光黄・紫の落ち影）": "塗りたて",
    "金の輪（青の外縁）": "金の輪",
    "翠石（生成りに翡翠の縁）": "翠石",
    "祭囃子（朱に生成りの縁）": "祭囃子",
    "黒座（傾いた黒の台）": "黒座",
    "紅玉（金の縁）": "紅玉",
    "しゃぼん（白に水の輪）": "しゃぼん",
    "熔岩（橙の階調・白の輪）": "熔岩",
    "緑閃（黒縁に白外）": "緑閃",
    "彩舞台（白縁・多色の塗り）": "彩舞台",
    "水風船（桃の輪・黄の外）": "水風船",
    "空洞（中抜きの輪郭）": "空洞",
    "窯出し（生成りに煉瓦の輪）": "窯出し",
    "紅刃（角・平塗り）": "紅刃",
    "黄電（黄に水色の輪）": "黄電",
    "冷銀（細字・青み）": "冷銀",
    "橙板（濃紺の字）": "橙板",
    "号令（白の型・硬い影）": "号令",
    "黒柱（縦・白く光る）": "黒柱",
    "空色（白縁・濃紺の外輪）": "空色",
    "炭青（橙の輪）": "炭青",
    "薄墨（透ける濃色・広い送り）": "薄墨",
    "暗幕（細字・水色の枠）": "暗幕",
    "静墨（極細・広い送り）": "静墨",
    "黒銘（明朝・鋼の輪）": "黒銘",
    "黒角（鋼の輪・硬い影）": "黒角",
    "血線（黒字に赤の輪）": "血線",
    "錆霜（骨色・錆の輪）": "錆霜",
    "実り（金茶・木札の帯）": "実り",
    "戯画（黄地に白抜き）": "戯画",
    "雪嶺（氷色・紫の落ち影）": "雪嶺",
    "骨白（細い明朝・銀の線）": "骨白",
    "深碧（生成り・太い縁）": "深碧",
    "角ドット（白・太い黒縁）": "角ドット",
    "朱裂（白の明朝・朱の細縁）": "朱裂",
    "石塊（灰の角字・黒の角縁）": "石塊",
    "草土（土色・草の二重縁）": "草土",
    "銀葉（白の飾り明朝・灰の影）": "銀葉",
    "金焔（金の階調・黒赤の落ち影）": "金焔",
    "潜水灯（黄・水色の輪）": "潜水灯",
    "琥珀（葡萄酒の太縁）": "琥珀",
    "白角（極広の字送り）": "白角",
    "深紅（白の角縁）": "深紅",
    "標示（山吹の板・黒字）": "標示",
    "粘体（桃の艶・紅の縁）": "粘体",
    "陽金（白と朱の三重縁）": "陽金",

    # ---- 🐢 から起こした3件
    "甲羅うら（濃緑に黄緑の輪）": "甲羅うら",
    "若緑（明るい緑に濃緑）": "若緑",
    "甲羅座布団（緑の帯）": "甲羅座布団",
}


def _merge_entries():
    """プリセットも割り当てとして1つの表にする。

    先に当たったruleの上に後のruleが重なるので、見た目のプリセットを先に置き、
    話者や感情など意味を持つ目印が上書きする側になるよう並べる。
    """
    rows = []
    for look in LOOKS:
        key = LOOK_KEYS[look["name"]]
        rows.append(dict(
            name=look["name"], cat=look["cat"], marker="", key=key, pattern="", source="",
            origin=look.get("origin", ""),
            sample="[" + key + "]" + LOOK_SAMPLE, over=look["over"], look=True,
        ))
    for entry in ENTRIES:
        entry.setdefault("pattern", "")
        entry.setdefault("source", "")
        entry.setdefault("origin", "")
        entry.setdefault("key", RULE_KEYS[entry["name"]])
        entry["cat"] = CATS[entry["name"]]
        entry["look"] = False
        rows.append(entry)
    return rows


def marker_sample(marker):
    """目印の正規表現から、見本に付ける文字を作る（[!！]{2,} なら !!）。

    先頭が \\ のときはescapeなので、その次の1文字を採る（[\\^＾] なら ^）。
    escapeごと採ると見本の目印が \\ になり、行頭に貼っても何にも当たらなくなる。
    """
    if not marker:
        return ""
    char = marker[2] if marker[1] == "\\" else marker[1]
    count = re.search(r"\{(\d+),", marker)
    return char * (int(count.group(1)) if count else 1)


def split_sample(sample):
    """見本の文から、行頭の目印を取り除いた本文だけを返す。"""
    index = 0
    while index < len(sample):
        char = sample[index]
        bracket = next((pair for pair in BRACKETS if pair[0] == char), None)
        if bracket:
            close = sample.find(bracket[1], index + 1)
            if close < 0:
                break
            index = close + 1
            continue
        if char in MARKER_CHARS:
            index += 1
            continue
        break
    return sample[index:].strip()


ENTRIES = _merge_entries()

# 判定テストの既定文
TEST_LINES = [
    "普通の字幕です",
    "!嘘でしょ",
    "!!無理無理無理",
    ">それは違うでしょ",
    ">!まさかそんな",
    "wそれはずるい",
    "wwやめてくれ",
    "*これ言っていいのかな",
    "**絶対勝てない",
    "?どういうこと",
    "#ここから本番",
    "##緊急速報",
    "###まさかの展開",
    ":それ知ってる",
    "$バラをありがとう",
    "=このあと事件が起きる",
    "\"あの時こう言った",
    "^ここは上に出す",
    "_ここは下に出す",
    "ｗｗｗ",
    "+かわいく出す",
    "+++ポップに出す",
    "%ネオンで出す",
    "||ニュース風の帯",
    "+!かわいい上に驚き",
    "%%%>熱血で相手のせりふ",
]

INT_KEYS = set()
for _n in ELEMENT_LABEL:
    INT_KEYS.update([
        "Enabled" + _n, "ElementShape" + _n, "JoinStyle" + _n,
        "OutsideOnly" + _n, "Level" + _n, "Softness" + _n, "Shear" + _n,
        "Type" + _n,
    ])
INT_KEYS.update([
    "Wrap", "VerticalTopCenterBottom", "Direction", "LineDirection",
    "VerticalJustificationNew", "HorizontalJustificationNew",
])

POINT_KEYS = ("Center", "Offset2", "Offset5")

# Red/Green/Blue はどれか1つが変わったら3つとも書き出す（重ね合わせで色が混ざるのを防ぐ）
COLOR_GROUPS = [("Red" + n, "Green" + n, "Blue" + n) for n in ELEMENT_LABEL]

# 色を1つでなく並びで持つ設定。1色ぶんの色見本では編集できないため画面側で分ける。
GRAD_KEYS = tuple(key for key, value in BASE.items() if isinstance(value, list))


def hex_rgb(value):
    """#rrggbb を 0〜1 の3成分に直す。"""
    text = value.lstrip("#")
    return (int(text[0:2], 16) / 255.0,
            int(text[2:4], 16) / 255.0,
            int(text[4:6], 16) / 255.0)


def grad_stops(colors):
    """色の並びを ShadingGradient の値に直す。位置は色の数で等分する。

    Fusionが要るのは {位置: {1: r, ...}} の辞書だが、その形はJSONにすると
    数値キーが文字列に化ける。辞書へ直すのは書き込む直前（set_input）で行う。
    """
    last = max(len(colors) - 1, 1)
    stops = []
    for index, color in enumerate(colors):
        red, green, blue = hex_rgb(color)
        stops.append([index / float(last), red, green, blue, 1.0])
    return stops


def to_preset(style):
    """見た目の設定を Text+ のInput名の辞書に直す。"""
    preset = OrderedDict()
    preset["Font"] = style["font"]
    preset["Style"] = style["style"]
    preset["Size"] = style["size"]
    preset["CharacterSpacing"] = style["tracking"]
    preset["LineSpacing"] = style["leading"]
    preset["Center"] = [style["cx"], style["cy"]]
    # Text+ の列挙値は plugin の文字列表の逆順。ElementShape と Level で裏取りした。
    #   Direction     0=Automatic 1=Horizontal 2=Reversed Horizontal 3=Vertical 4=Reversed Vertical
    #   LineDirection 0=Top Down  1=Bottom Up
    #   JoinStyle     0=Bevel     1=Round      2=Miter                3=Miter Clip
    preset["Direction"] = 3 if style["vertical"] else 0
    preset["LineDirection"] = style["lineDir"]
    preset["Wrap"] = 1
    preset["VerticalTopCenterBottom"] = 1
    preset["VerticalJustificationNew"] = 3
    preset["HorizontalJustificationNew"] = 3

    red, green, blue = hex_rgb(style["fill"])
    preset["Enabled1"] = 1
    preset["ElementShape1"] = 0
    # Type は塗り方の切り替え。0=単色 2=グラデーション。
    # off でも書き出すのは、前に当てた装飾のグラデーションが残るのを防ぐため。
    preset["Type1"] = 2 if style["fillGradOn"] else 0
    preset["Red1"] = red
    preset["Green1"] = green
    preset["Blue1"] = blue
    preset["Alpha1"] = style["fillA"]
    preset["Softness1"] = 1
    if style["fillGradOn"]:
        preset["ShadingGradient1"] = grad_stops(style["fillGradC"])
        preset["ShadingMappingAngle1"] = style["fillGradAngle"]

    red, green, blue = hex_rgb(style["edgeC"])
    preset["Enabled2"] = style["edgeOn"]
    preset["ElementShape2"] = 1
    preset["Type2"] = 2 if style["edgeGradOn"] else 0
    preset["Thickness2"] = style["edgeW"]
    preset["JoinStyle2"] = 1 if style["edgeRound"] else 3
    preset["OutsideOnly2"] = style["edgeOutside"]
    preset["AngleZ2"] = style["edgeAngle"]
    preset["SizeX2"] = style["edgeScale"]
    preset["SizeY2"] = style["edgeScale"]
    preset["Offset2"] = [style["edgeOffX"], style["edgeOffY"]]
    preset["Red2"] = red
    preset["Green2"] = green
    preset["Blue2"] = blue
    preset["Alpha2"] = 1.0
    preset["Softness2"] = 1
    if style["edgeGradOn"]:
        preset["ShadingGradient2"] = grad_stops(style["edgeGradC"])
        preset["ShadingMappingAngle2"] = style["edgeGradAngle"]

    red, green, blue = hex_rgb(style["edge2C"])
    preset["Enabled3"] = style["edge2On"]
    preset["ElementShape3"] = 1
    preset["Thickness3"] = style["edge2W"]
    preset["JoinStyle3"] = 1
    preset["OutsideOnly3"] = 1
    preset["Red3"] = red
    preset["Green3"] = green
    preset["Blue3"] = blue
    preset["Alpha3"] = 1.0
    preset["Softness3"] = 1

    red, green, blue = hex_rgb(style["glowC"])
    preset["Enabled4"] = style["glowOn"]
    preset["ElementShape4"] = 1
    preset["Thickness4"] = style["glowW"]
    preset["JoinStyle4"] = 1
    preset["OutsideOnly4"] = 1
    preset["Red4"] = red
    preset["Green4"] = green
    preset["Blue4"] = blue
    preset["Alpha4"] = 1.0
    preset["Opacity4"] = style["glowOpacity"]
    preset["Softness4"] = 1
    preset["SoftnessX4"] = style["glowBlur"]
    preset["SoftnessY4"] = style["glowBlur"]
    preset["SoftnessGlow4"] = style["glowSpread"]

    red, green, blue = hex_rgb(style["shadowC"])
    preset["Enabled5"] = style["shadowOn"]
    preset["ElementShape5"] = 0
    preset["Offset5"] = [style["shadowX"], style["shadowY"]]
    preset["Red5"] = red
    preset["Green5"] = green
    preset["Blue5"] = blue
    preset["Alpha5"] = 1.0
    preset["Opacity5"] = style["shadowOpacity"]
    preset["Softness5"] = 1
    preset["SoftnessX5"] = style["shadowBlur"]
    preset["SoftnessY5"] = style["shadowBlur"]

    red, green, blue = hex_rgb(style["bandC"])
    preset["Enabled6"] = style["bandOn"]
    preset["ElementShape6"] = 2
    preset["Level6"] = style["bandLevel"]
    preset["ExtendHorizontal6"] = style["bandPadX"]
    preset["ExtendVertical6"] = style["bandPadY"]
    preset["Round6"] = style["bandRound"]
    preset["Red6"] = red
    preset["Green6"] = green
    preset["Blue6"] = blue
    preset["Alpha6"] = 1.0
    preset["Opacity6"] = style["bandOpacity"]
    preset["Softness6"] = 1
    preset["Shear6"] = 1
    preset["ShearX6"] = style["bandShearX"]

    # ElementShape 3 は帯の縁。帯と同じ大きさを持たせないと縁がずれる。
    preset["Enabled7"] = style["bandEdgeOn"]
    if style["bandEdgeOn"]:
        red, green, blue = hex_rgb(style["bandEdgeC"])
        preset["ElementShape7"] = 3
        preset["Level7"] = style["bandLevel"]
        preset["ExtendHorizontal7"] = style["bandPadX"]
        preset["ExtendVertical7"] = style["bandPadY"]
        preset["Round7"] = style["bandRound"]
        preset["Thickness7"] = style["bandEdgeW"]
        preset["Red7"] = red
        preset["Green7"] = green
        preset["Blue7"] = blue
        preset["Alpha7"] = 1.0
        preset["Softness7"] = 1
    return preset


def diff_preset(base, target):
    """既定と違うところだけを、色は3成分そろえて取り出す。"""
    out = OrderedDict()
    for key, value in target.items():
        if base.get(key) != value:
            out[key] = value
    for group in COLOR_GROUPS:
        if any(key in out for key in group):
            for key in group:
                out[key] = target[key]
    return OrderedDict((k, v) for k, v in target.items() if k in out)


def look_keys(base_preset):
    """見た目のプリセットが触るInput名を全部集める。

    プリセット同士は重なりうる（+++ は + と ++ にも一致する）。差分だけを書くと
    前のプリセットの色や書体が残って混ざるため、どのプリセットも同じキー一式を書く。
    """
    keys = set()
    for entry in ENTRIES:
        if not entry["look"]:
            continue
        style = merged(entry["over"])
        keys.update(diff_preset(base_preset, to_preset(style)))
    return keys


def look_preset(base_preset, keys, over):
    """プリセット1つぶんを、共通のキー一式で書き出す。"""
    style = merged(over)
    full = to_preset(style)
    return OrderedDict((k, v) for k, v in full.items() if k in keys)


def fmt_value(key, value):
    """Pythonの値をscriptに書く形に直す。"""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            return "[%s]" % ", ".join(
                "[%s]" % ", ".join("%.4f" % number for number in stop) for stop in value)
        return "[%.4f, %.4f]" % (value[0], value[1])
    if key in INT_KEYS:
        return "%d" % int(value)
    return "%.4f" % value


def fmt_block(preset, indent):
    """{...} のブロック文字列を作る。キーの幅をそろえる。"""
    if not preset:
        return "{}"
    width = max(len(key) for key in preset) + 3
    lines = ["{"]
    for key, value in preset.items():
        label = ('"%s":' % key).ljust(width)
        lines.append("%s%s %s," % (indent + "    ", label, fmt_value(key, value)))
    lines.append(indent + "}")
    return "\n".join(lines)


def python_blocks():
    """script に差し込む MARKER_CHARS / BASE_PRESET / RULES / LOOKS を作る。"""
    base_preset = to_preset(merged({}))
    marker_line = "MARKER_CHARS = " + json.dumps(MARKER_CHARS, ensure_ascii=False)
    base_chars_line = "BASE_CHARS = %r" % fit_chars(merged({}))
    base_block = "BASE_PRESET = " + fmt_block(base_preset, "")

    keys = look_keys(base_preset)
    rules = ["RULES = ["]
    for entry in ENTRIES:
        if entry["look"]:
            preset = look_preset(base_preset, keys, entry["over"])
        else:
            style = merged(entry["over"])
            preset = diff_preset(base_preset, to_preset(style))
        rules.append("    {")
        rules.append('        "name":    %s,' % json.dumps(entry["name"], ensure_ascii=False))
        rules.append('        "marker":  %s,' % json.dumps(entry["marker"], ensure_ascii=False))
        rules.append('        "key":     %s,' % json.dumps(entry.get("key", ""), ensure_ascii=False))
        rules.append('        "pattern": %s,' % json.dumps(entry.get("pattern", ""), ensure_ascii=False))
        rules.append('        "source":  %s,' % json.dumps(entry.get("source", ""), ensure_ascii=False))
        # json.dumps だと None が null になり、script 側で literal として読めない
        rules.append('        "chars":   %r,' % fit_chars(style_of(entry)))
        rules.append('        "preset":  %s,' % fmt_block(preset, "        "))
        rules.append("    },")
    rules.append("]")

    looks = ["LOOKS = ["]
    for entry in ENTRIES:
        if not entry["look"]:
            continue
        preset = look_preset(base_preset, keys, entry["over"])
        looks.append("    {")
        looks.append('        "name":   %s,' % json.dumps(entry["name"], ensure_ascii=False))
        looks.append('        "key":    %s,' % json.dumps(entry["key"], ensure_ascii=False))
        looks.append('        "cat":    %s,' % json.dumps(entry["cat"], ensure_ascii=False))
        looks.append('        "origin": %s,' % json.dumps(entry.get("origin", ""),
                                                          ensure_ascii=False))
        looks.append('        "preset": %s,' % fmt_block(preset, "        "))
        looks.append("    },")
    looks.append("]")
    return (marker_line, base_block, "\n".join(rules), "\n".join(looks),
            base_chars_line)


def swatch_cases():
    """Resolveに見本を描かせるための、割り当てごとの本文と装飾を作る。

    重ねた割り当ての key も "rules" に残す。装飾データ.json は装飾の実体を持たず
    この key で RULES を指すので、どれを何番目に重ねたかが要る。
    """
    base_preset = to_preset(merged({}))
    keys = look_keys(base_preset)
    rows = [{"name": "通常（既定）", "mark": "", "kind": "既定",
             "text": "普通の字幕です", "preset": base_preset, "rules": []}]
    for entry in ENTRIES:
        preset = dict(base_preset)
        used = []
        symbols = marker_sample(entry["marker"])
        for other in ENTRIES:
            if other["look"]:
                if not entry["look"] or other["key"] != entry["key"]:
                    continue
                preset.update(look_preset(base_preset, keys, other["over"]))
            else:
                if not other["marker"] or not symbols:
                    continue
                if not re.search(other["marker"], symbols):
                    continue
                style = merged(other["over"])
                preset.update(diff_preset(base_preset, to_preset(style)))
            used.append(other["key"])
        mark = "[" + entry["key"] + "]" if entry["look"] else symbols
        rows.append({"name": entry["name"], "mark": mark,
                     "kind": "プリセット" if entry["look"] else "目印",
                     "text": split_sample(entry["sample"]), "preset": preset,
                     "rules": used})
    return rows


def case_mark(text, preset):
    """この1件の中身を表す短い印。値が1つでも変われば必ず変わる。

    確かめ側（Resolveで動かす/テスト_ぜんぶ確かめる.py）は、この印を
    そのまま使う。同じ計算を両方に置くと、片方だけ直したときに
    「変わっていない」と誤判定するため、作るのはここだけにする。
    """
    seed = repr(text) + "|" + repr(sorted((key, repr(value))
                                          for key, value in preset.items()))
    number = 0
    for char in seed:
        number = (number * 131 + ord(char)) & 0xFFFFFFFF
    return "%08x" % number


def swatch_block():
    """3_装飾ツール.py に差し込む SWATCH_CASES を作る。"""
    lines = ["SWATCH_CASES = ["]
    for case in swatch_cases():
        lines.append("    {")
        lines.append('        "name":   %s,' % json.dumps(case["name"], ensure_ascii=False))
        lines.append('        "mark":   %s,' % json.dumps(case["mark"], ensure_ascii=False))
        lines.append('        "kind":   %s,' % json.dumps(case["kind"], ensure_ascii=False))
        lines.append('        "text":   %s,' % json.dumps(case["text"], ensure_ascii=False))
        lines.append('        "preset": %s,' % fmt_block(case["preset"], "        "))
        lines.append("    },")
    lines.append("]")
    return "\n".join(lines)


def js_data():
    """画面に差し込む BASE / ENTRIES / LOOKS / TEST_LINES を作る。"""
    def dump(value):
        return json.dumps(value, ensure_ascii=False)

    base = "const BASE = " + dump(BASE) + ";"
    entries = ["let entries = ["]
    for entry in ENTRIES:
        entries.append("  " + dump(OrderedDict([
            ("name", entry["name"]),
            ("cat", entry["cat"]),
            ("marker", entry["marker"]),
            ("key", entry.get("key", "")),
            ("pattern", entry.get("pattern", "")),
            ("source", entry.get("source", "")),
            ("origin", entry.get("origin", "")),
            ("sample", entry["sample"]),
            ("look", entry["look"]),
            ("over", entry["over"]),
        ])) + ",")
    entries.append("];")
    looks = "const CAT_ORDER = " + dump(CAT_ORDER) + ";"
    looks += "\nconst PREVIEW = " + dump(PREVIEW) + ";"
    looks += "\nconst FONT_WEIGHT = " + dump(font_weights(font_faces()) if sys.platform == "win32" else {}) + ";"
    looks += "\nconst FONT_WIDTH = " + dump(dict((k, list(v)) for k, v in FONT_WIDTH.items())) + ";"
    looks += "\nconst FIT = " + dump({"chars": FIT_CHARS, "width": FIT_WIDTH,
                                      "note": width_frame_note()}) + ";"
    tests = "const TEST_LINES = " + dump(TEST_LINES) + ";"
    labels = "const ELEMENT_LABEL = " + dump(ELEMENT_LABEL) + ";"
    ints = "const INT_KEYS = " + dump(sorted(INT_KEYS)) + ";"
    points = "const POINT_KEYS = " + dump(list(POINT_KEYS)) + ";"
    points += "\nconst GRAD_KEYS = " + dump(list(GRAD_KEYS)) + ";"
    groups = "const COLOR_GROUPS = " + dump([list(g) for g in COLOR_GROUPS]) + ";"
    markers = "const MARKER_CHARS = " + dump(MARKER_CHARS) + ";"
    markers += "\nconst BRACKETS = " + dump([list(pair) for pair in BRACKETS]) + ";"
    return "\n".join([labels, ints, points, groups, markers, base, looks,
                      tests, "", "\n".join(entries)])


def installed_fonts():
    """Windowsに入っている書体名を集める。取れない環境では空を返す。"""
    if sys.platform != "win32":
        return []
    # PowerShell は既定でANSI（日本語環境ではCP932）で吐くため、UTF-8にしてから受け取る。
    # 指定しないと「HG創英角ｺﾞｼｯｸUB」などの日本語名が文字化けして一覧に並ぶ。
    command = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
               "Add-Type -AssemblyName System.Drawing; "
               "(New-Object System.Drawing.Text.InstalledFontCollection)."
               "Families | ForEach-Object { $_.Name }")
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", command],
            stderr=subprocess.DEVNULL)
    except Exception:
        return []
    names = [line.strip() for line in out.decode("utf-8", "ignore").splitlines()]
    return sorted({name for name in names if name})


def font_faces():
    """入っている書体ファイルを読み、使える (書体名, スタイル名) の組を集める。

    Resolve は書体をこの2つで引く。スタイル名が違うと
    「Could not find font: HGPGyoshotai: Regular」のように弾かれる。

    名前の持ち方は書体で違う。
      ・普通の書体   name 1=書体名 2=スタイル名
      ・4種類を超える書体 name 16=まとめ名 17=スタイル名（1は「まとめ名+スタイル」）
      ・可変書体     fvar の名前付きインスタンスがスタイルになる
    どれで書かれていても引けるよう、3通りとも組にして集める。
    """
    import glob
    import struct

    folders = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        folders.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))

    def face_names(data, offset):
        """1つの face から、name表とfvarの名前を取り出す。"""
        tables = {}
        for i in range(struct.unpack(">H", data[offset + 4:offset + 6])[0]):
            spot = offset + 12 + i * 16
            tag = data[spot:spot + 4].decode("latin1")
            start_at, _length = struct.unpack(">II", data[spot + 8:spot + 16])
            tables[tag] = start_at
        if "name" not in tables:
            return {}
        base = tables["name"]
        total, strings = struct.unpack(">HH", data[base + 2:base + 6])
        by_id = {}
        for i in range(total):
            rec = base + 6 + i * 12
            pid, _eid, lid, nid, length, off = struct.unpack(">HHHHHH", data[rec:rec + 12])
            if pid != 3 or lid != 0x409:
                continue
            spot = base + strings + off
            by_id.setdefault(nid, data[spot:spot + length].decode("utf-16-be", "ignore"))
        family = by_id.get(1)
        if not family:
            return {}
        style = by_id.get(2, "Regular")
        group = by_id.get(16, family)
        group_style = by_id.get(17, style)
        pairs = {(family, style), (group, group_style), (family, group_style), (group, style)}
        weight = 400
        if "OS/2" in tables:
            spot = tables["OS/2"]
            weight = struct.unpack(">H", data[spot + 4:spot + 6])[0]

        found = dict.fromkeys(pairs, weight)
        if "fvar" in tables:
            # 可変書体は名前付きインスタンスがスタイルになる。太さは OS/2 ではなく
            # wght 軸の値。OS/2 には既定インスタンスの太さしか入っていない。
            spot = tables["fvar"]
            axes_off, _pad, axis_count, axis_size, count, size = struct.unpack(
                ">HHHHHH", data[spot + 4:spot + 16])
            axes = []
            for i in range(axis_count):
                rec = spot + axes_off + i * axis_size
                axes.append(data[rec:rec + 4].decode("latin1"))
            first = spot + axes_off + axis_count * axis_size
            by_label = {}
            for i in range(count):
                rec = first + i * size
                name_id = struct.unpack(">H", data[rec:rec + 2])[0]
                label = by_id.get(name_id)
                if not label:
                    continue
                value = weight
                for k, tag in enumerate(axes):
                    if tag != "wght":
                        continue
                    fixed = struct.unpack(">i", data[rec + 4 + k * 4:rec + 8 + k * 4])[0]
                    value = int(round(fixed / 65536.0))
                by_label[label] = value
                found[(group, label)] = value
                found[(group + " " + label, "Regular")] = value
            for pair in pairs:
                found[pair] = by_label.get(pair[1], by_label.get("Regular", weight))
        return found

    def read(path):
        with open(path, "rb") as handle:
            data = handle.read()
        if data[:4] == b"ttcf":
            count = struct.unpack(">I", data[8:12])[0]
            offsets = [struct.unpack(">I", data[12 + 4 * i:16 + 4 * i])[0] for i in range(count)]
        else:
            offsets = [0]
        found = {}
        for offset in offsets:
            found.update(face_names(data, offset))
        return found

    faces = {}
    for folder in folders:
        if not os.path.isdir(folder):
            continue
        for pattern in ("*.ttf", "*.ttc", "*.otf", "*.TTF", "*.TTC", "*.OTF"):
            for path in glob.glob(os.path.join(folder, pattern)):
                try:
                    faces.update(read(path))
                except Exception:
                    continue
    return faces


def font_weights(faces):
    """割り当てが使う (書体, スタイル) の本当の太さを返す。

    プレビューはこれを font-weight に使う。書体名に太さが入っている書体
    （HGPSoeiPresenceEB など）に 700 を足すと、ブラウザが合成太字を掛けて
    Resolve より太く出てしまう。
    """
    out = OrderedDict()
    for entry in ENTRIES:
        style = merged(entry["over"])
        pair = (style["font"], style["style"])
        if pair in faces:
            out["%s|%s" % pair] = faces[pair]
    return out


def check_fonts():
    """割り当てが使う (書体, スタイル) が実在するか調べる。"""
    if sys.platform != "win32":
        return []
    faces = font_faces()
    if not faces:
        return []
    families = {name for name, _style in faces}
    bad = []
    for entry in ENTRIES:
        style = merged(entry["over"])
        pair = (style["font"], style["style"])
        if pair in faces:
            continue
        if style["font"] not in families:
            bad.append((entry["name"], pair, "書体が無い"))
            continue
        have = sorted(s for f, s in faces if f == style["font"])
        bad.append((entry["name"], pair, "スタイルは %s" % " / ".join(have)))
    return bad


def look_faces():
    """見た目のプリセットが使っている (書体名, スタイル名) を、出てくる順に集める。"""
    seen, out = set(), []
    for entry in ENTRIES:
        style = merged(entry["over"])
        pair = (style["font"], style["style"])
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    return out


def fit_width(style, chars):
    """この装飾で全角 chars 文字を並べたときの、画面幅に対する幅を返す。

    実測していない書体は None。推定値で代わりに答えると、はみ出すものを
    見逃したか、収まるものを刈ったかが、どちらも分からなくなる。

    値は「Size 1・画面幅1 あたり」で持っている。文字の並びは
    （文字数 - 1）× 送り幅 + 1文字の字幅。最後の1文字だけは
    送り幅ではなく実際の字幅で見る（送り幅より外へ張り出す書体があるため）。

    字送り（CharacterSpacing）は送り幅を**掛けない**。1.0 との差に
    「Size 1・画面幅1」をそのまま掛けた分を**足す**（実測: 字送り1.3 で
    送り幅が 64.0px から 92.8px へ。差の 28.8px は 0.3 × Size × 画面幅 ちょうど）。
    掛け算だと、字面の狭い書体ほど広く見積もる側へ最大45%ずれる。
    """
    if tuple(FONT_WIDTH_FRAME) != FIT_FRAME:
        return None
    measured = FONT_WIDTH.get(style["font"] + "|" + style["style"])
    if measured is None:
        return None
    advance, one_width, one_height = measured
    step = advance + (style["tracking"] - 1.0)
    text = ((chars - 1) * step + one_width) * style["size"]

    # 縁・帯は文字の実寸を基準にした値なので、実寸に直してから足す。
    ink = one_height * style["size"]
    edge = max([style["edgeW"] * style["edgeScale"] if style["edgeOn"] else 0.0,
                style["edge2W"] if style["edge2On"] else 0.0]) * ink * PREVIEW["thickToPx"]
    edge += abs(style["edgeOffX"])
    band = 0.0
    if style["bandOn"]:
        band = style["bandPadX"] * ink * PREVIEW["extendXToPx"]
        if style["bandEdgeOn"]:
            band += style["bandEdgeW"] * ink * PREVIEW["thickToPx"]
    return text + 2 * max(edge, band)


def size_for(style):
    """狙いの字数がちょうど収まる Size を、その装飾の中身から1件ずつ解く。

    同じ Size でも書体で送り幅が 1.5倍違い、字送り・縁・帯も幅を押し広げる。
    だから全体に同じ倍率を掛けても大きさは揃わない。装飾ごとにここで解く。

    実測していない書体は解けない。見当で埋めると、はみ出したのか余らせたのかが
    どちらも分からなくなるので、書体の名前を挙げて止める。
    """
    probe = dict(style)
    probe["size"] = 1.0
    if fit_width(probe, FIT_TARGET_CHARS) is None:
        raise SystemExit(
            "書体 %r スタイル %r の送り幅が未実測です。%s"
            % (style["font"], style["style"], width_frame_note()))
    low, high = 0.0, 1.0
    for _ in range(60):
        mid = (low + high) / 2.0
        probe["size"] = mid
        if fit_width(probe, FIT_TARGET_CHARS) <= FIT_WIDTH:
            low = mid
        else:
            high = mid
    return int(low * 10000) / 10000.0


def merged(over):
    """既定に上書きを重ね、横幅いっぱいになる Size を逆算した見た目を返す。"""
    style = dict(BASE)
    style.update(over)
    style["size"] = size_for(style)
    return style


def style_of(entry):
    """その割り当ての、既定に重ねた後の見た目。幅を測るのに使う。"""
    return merged(entry["over"])


def fit_chars(style):
    """この装飾で1行に載る全角の文字数。実測していない書体は None。

    幅は装飾ごとに違う（書体・大きさ・字送り・縁・帯で変わる）。1つの数字を
    全部に当てると、狭い装飾では余らせ、広い装飾でははみ出す。
    Resolve 側はこの値で折り返すので、装飾ごとに1つ持たせる。

    縦書きは高さで決まるので、ここでは数えない（None を返す）。

    幅が足りていても WRAP_MAX で頭を打つ。幅は 32文字まで入る装飾があるが、
    1行が長いと読み手が目で追えない。幅の限界と読める長さは別の話。
    """
    if style["vertical"]:
        return None
    last = None
    for chars in range(1, WRAP_MAX + 1):
        width = fit_width(style, chars)
        if width is None:
            return None
        if width > FIT_WIDTH:
            break
        last = chars
    return min(last, WRAP_MAX) if last else last


def check_widths():
    """全角 FIT_CHARS 文字が画面に収まらない割り当てを洗い出す。

    (名前, 書体, 幅, 収めるための大きさ) を返す。未実測の書体は別に返す。
    """
    over, unknown = [], []
    for entry in ENTRIES:
        style = merged(entry["over"])
        if style["vertical"]:
            continue
        width = fit_width(style, FIT_CHARS)
        if width is None:
            pair = (style["font"], style["style"])
            if pair not in unknown:
                unknown.append(pair)
            continue
        if width > FIT_WIDTH:
            over.append((entry["name"], style["font"], width,
                         style["size"] * FIT_WIDTH / width))
    return over, unknown


def test_note():
    """いまの装飾が確かめ済みかどうかを1行で返す。

    Resolveで動かす/テスト_ぜんぶ確かめる.py が残した結果と、いまの中身の印を
    突き合わせるだけ。印が1つでも違えば、その件は確かめ直しが要る。
    """
    path = os.path.join(ROOT, "doc", "テスト結果.json")
    cases = swatch_cases()
    if not os.path.isfile(path):
        return "確かめ: まだ一度も通していません（%d件）。" % len(cases)
    try:
        done = json.loads(read(path)).get("通った件", {}) or {}
    except ValueError:
        return "確かめ: 前回の結果を読めません。"
    stale = [case["name"] for case in cases
             if done.get(case["name"]) != case_mark(case["text"], case["preset"])]
    if not stale:
        return "確かめ: %d件すべて確かめ済み。Resolve で流し直す必要はありません。" % len(cases)
    return ("確かめ: %d件中 %d件が未確認（%s%s）。"
            "Resolve の Console で Resolveで動かす/テスト_ぜんぶ確かめる.py を実行してください。"
            % (len(cases), len(stale), " ".join(stale[:3]),
               " ほか" if len(stale) > 3 else ""))


def width_frame_note():
    """送り幅がどの大きさで測られているか。使えないときだけ文を返す。"""
    frame = tuple(FONT_WIDTH_FRAME)
    if frame == FIT_FRAME:
        return ""
    if frame == (0, 0):
        return "送り幅がまだ測られていません。"
    return ("送り幅は %dx%d で測られています。字幕を出すのは %dx%d なので使えません。"
            % (frame[0], frame[1], FIT_FRAME[0], FIT_FRAME[1]))


def counter_limit(font, style):
    """この書体で引ける縁の太さの上限を返す。測っていない書体は None。"""
    radius = FONT_COUNTER.get(font + "|" + style)
    if radius is None:
        return None
    return radius * COUNTER_ALLOW / (COUNTER_INK * PREVIEW["thickToPx"])


def check_counters():
    """漢字の内側が塗り潰れる割り当てを洗い出す。"""
    over = []
    for entry in ENTRIES:
        style = merged(entry["over"])
        limit = counter_limit(style["font"], style["style"])
        if limit is None:
            continue
        # 縁を拡大すると外へ出る量も増えるので、素の太さではなく拡大後で見る。
        widest = max([style["edgeW"] * style["edgeScale"] if style["edgeOn"] else 0.0,
                      style["edge2W"] if style["edge2On"] else 0.0])
        if widest > limit:
            over.append((entry["name"], style["font"], widest, limit))
    return over


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def filled_script(path, blocks):
    """script の空の表に中身を流し込んだ写しを返す（file は書き替えない）。

    3_装飾ツール.py 自身は表を持たず 装飾データ.json を読むが、画面に埋め込む写しは
    表を持っていないと Console へ貼れない。そこで、埋め込む分だけここで埋める。
    画面の buildScript() は同じ場所を同じ形で差し替えるので、調整欄で値を動かした
    ぶんはそこで上書きされる。
    """
    marker_line, base_block, rules_block, looks_block, base_chars_line = blocks
    text = read(path)
    swaps = [
        (r"^MARKER_CHARS = .*$", marker_line),
        (r"^BASE_CHARS = .*$", base_chars_line),
        (r"^BASE_PRESET = \{[\s\S]*?\n\}", base_block),
        (r"^RULES = \[[\s\S]*?\n\]", rules_block),
        (r"^LOOKS = \[[\s\S]*?\n\]", looks_block),
        (r"^SWATCH_CASES = \[[\s\S]*?\n\]", swatch_block()),
    ]
    for pattern, value in swaps:
        text, hits = re.subn(pattern, lambda m: value, text, count=1, flags=re.M)
        if not hits:
            raise SystemExit("%s に %r がありません。" % (os.path.basename(path), pattern))
    return text


def literal(block):
    """`NAME = ...` の形の文字列から、値だけを取り出す。"""
    return ast.literal_eval(block.split(" = ", 1)[1])


def data_json(blocks):
    """装飾データ.json の中身を組み立てる。

    script へ書いていた表をそのまま持つが、LOOKS と SWATCH_CASES の装飾だけは
    持たない。どちらも RULES の装飾と同じ値なので、key で指して読む側で組み直す。
    同じ値を3か所に書くと、直したときにどこか1か所が古いまま残る。

    値は script へ書く文字列（blocks）から literal_eval で取る。%.4f で丸めた
    あとの値になるので、画面が配る script と JSON がずれない。
    """
    marker_line, base_block, rules_block, _looks_block, base_chars_line = blocks
    marker = literal(marker_line)
    base = literal(base_block)
    rules = literal(rules_block)

    known = set()
    for rule in rules:
        if rule["key"] in known:
            raise SystemExit("RULES に同じ key が2つあります: %r" % rule["key"])
        known.add(rule["key"])

    looks = []
    for entry in ENTRIES:
        if not entry["look"]:
            continue
        if entry["key"] not in known:
            raise SystemExit("LOOKS の %r に当たる RULES がありません。" % entry["key"])
        looks.append(OrderedDict([("name", entry["name"]), ("key", entry["key"]),
                                  ("cat", entry["cat"]),
                                  ("origin", entry.get("origin", "")),
                                  ("rule", entry["key"])]))

    cases = []
    for case in swatch_cases():
        for key in case["rules"]:
            if key not in known:
                raise SystemExit("SWATCH_CASES の %r が、RULES に無い %r を指しています。"
                                 % (case["name"], key))
        cases.append(OrderedDict([("name", case["name"]), ("mark", case["mark"]),
                                  ("kind", case["kind"]), ("text", case["text"]),
                                  ("rules", case["rules"]),
                                  ("印", case_mark(case["text"], case["preset"]))]))

    return OrderedDict([("version", DATA_VERSION), ("MARKER_CHARS", marker),
                        ("FIT_FRAME", list(FIT_FRAME)),
                        ("BASE_CHARS", literal(base_chars_line)),
                        ("BASE_PRESET", base), ("RULES", rules),
                        ("LOOKS", looks), ("SWATCH_CASES", cases)])


def check_data(data, blocks):
    """JSON から組み直した5つが、script へ書く表と同じ値になることを確かめる。

    画面側とscript側で装飾がずれていないことの保証は、これまで「同じ blocks を
    2か所へ書く」ことで成り立っていた。script 側が JSON になったので、
    組み直した結果が blocks と同じであることをここで確かめ直す。
    """
    marker_line, base_block, rules_block, looks_block, _base_chars = blocks
    want = {
        "MARKER_CHARS": literal(marker_line),
        "BASE_PRESET": literal(base_block),
        "RULES": literal(rules_block),
        "LOOKS": literal(looks_block),
        "SWATCH_CASES": literal(swatch_block()),
    }
    # 読む側と同じ手順で組み直す（3_装飾ツール.py の load_data と同じ）。
    by_key = dict((rule["key"], rule) for rule in data["RULES"])
    got = {
        "MARKER_CHARS": data["MARKER_CHARS"],
        "BASE_PRESET": data["BASE_PRESET"],
        "RULES": data["RULES"],
        "LOOKS": [],
        "SWATCH_CASES": [],
    }
    for look in data["LOOKS"]:
        entry = dict(look)
        entry["preset"] = dict(by_key[entry.pop("rule")]["preset"])
        got["LOOKS"].append(entry)
    for case in data["SWATCH_CASES"]:
        entry = dict(case)
        preset = dict(data["BASE_PRESET"])
        for key in entry.pop("rules"):
            preset.update(by_key[key]["preset"])
        entry["preset"] = preset
        # 中身の印は確かめ側だけが使う。装飾そのものではないので突き合わせから外す。
        entry.pop("印", None)
        got["SWATCH_CASES"].append(entry)

    for name in ("MARKER_CHARS", "BASE_PRESET", "RULES", "LOOKS", "SWATCH_CASES"):
        if got[name] != want[name]:
            raise SystemExit("装飾データ.json から組み直した %s が、"
                             "画面へ渡す表と違います。" % name)


def write_data(blocks):
    """装飾データ.json を書き出す。"""
    data = data_json(blocks)
    check_data(data, blocks)
    write(DATA_PATH, json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    return data


# 確かめる側へ写す関数。本体（10_実務_字幕を装飾する.py）に在るものだけを挙げる。
# 写しにするのは、確かめる手順と本番の手順がずれないようにするため。
COPY_FUNCS = ["get_resolve_obj", "set_input", "find_text_tool",
              "write_tool", "as_pair", "same_value", "diff_preset"]


def grab_funcs(source, names):
    """script から、名前を挙げた関数の本文をそのまま取り出す。"""
    out, missing = [], []
    for name in names:
        spot = source.find("\ndef %s(" % name)
        if spot < 0:
            missing.append(name)
            continue
        body = source[spot + 1:]
        end = len(body)
        for mark in ("\ndef ", "\nclass ", "\n# ---"):
            here = body.find(mark, 1)
            if 0 <= here < end:
                end = here
        out.append(body[:end].rstrip())
    if missing:
        raise SystemExit("本体に %s がありません。" % " / ".join(missing))
    return "\n\n\n".join(out)


def patch_tester(tool_source):
    """確かめる側へ、置き場と、本体から写した関数を差し込む。"""
    path = os.path.join(ROOT, "Resolveで動かす", "テスト_ぜんぶ確かめる.py")
    if not os.path.isfile(path):
        return
    text = read(path)
    text, hits = re.subn(r"^PROJECT = r\".*\"$", lambda m: "PROJECT = r\"%s\"" % ROOT,
                         text, count=1, flags=re.M)
    if not hits:
        raise SystemExit("テスト_ぜんぶ確かめる.py の PROJECT を見つけられません。")
    # LAST_READ は write_tool の直後に本体が持っているので、写しに付いてくる。
    block = "# @COPY@\n" + grab_funcs(tool_source, COPY_FUNCS) + "\n# @/COPY@"
    text, hits = re.subn(r"# @COPY@[\s\S]*?# @/COPY@", lambda m: block,
                         text, count=1)
    if not hits:
        raise SystemExit("テスト_ぜんぶ確かめる.py の写し場所を見つけられません。")
    write(path, text)


def patch_probe():
    """Resolveで動かす/ の script へ、置き場と書体の一覧を差し込む。"""
    path = os.path.join(ROOT, "Resolveで動かす", "道具_Text+の実寸と書体の字幅を測ってサンプルデータを変更する.py")
    if not os.path.isfile(path):
        return 0
    faces = look_faces()
    block = ["FACES = ["]
    for font, style in faces:
        block.append("    [%s, %s]," % (json.dumps(font, ensure_ascii=False),
                                        json.dumps(style, ensure_ascii=False)))
    block.append("]")

    # Resolve の Console に貼る script なので、__file__ が無い。手元の場所と
    # python の在り処は、ここで実物を埋め込む。sys.executable はいま生成を
    # 動かしている python そのもの（venv）なので、そのまま渡せる。
    text = read(path)
    swaps = [
        (r"^PROJECT = r\".*\"$", "PROJECT = r\"%s\"" % ROOT),
        (r"^PYTHON = r\".*\"$", "PYTHON = r\"%s\"" % sys.executable),
        (r"^FRAME = \(.*\)$", "FRAME = (%d, %d)" % FIT_FRAME),
        # 差し替えた結果が元と同じこともある（書体が変わっていないとき）。
        # 「変わらなかった」を「見つからなかった」と取り違えないよう、当たった数で見る。
        (r"^FACES = \[[\s\S]*?\n\]", "\n".join(block)),
    ]
    for pattern, value in swaps:
        text, hits = re.subn(pattern, lambda m: value, text, count=1, flags=re.M)
        if not hits:
            raise SystemExit("実測して直す.py の %r を見つけられません。" % pattern)
    write(path, text)
    return len(faces)


def build_html(js, fonts, sources):
    """画面のHTMLを組み立てる。"""
    template = read(os.path.join(HERE, "装飾プリセットを選ぶ.template.html"))
    template = template.replace("<!--@FONTS@-->",
                                "".join('<option value="%s">' % name for name in fonts))
    template = template.replace("// @DATA@", js)
    for mark, name in (("TOOL", "3_装飾ツール.py"),):
        source = sources[mark]
        if "</script" in source:
            raise SystemExit("%s に </script が含まれるため埋め込めません。" % name)
        template = template.replace("<!--@TPL_%s@-->" % mark, source)
    write(HTML_PATH, template)


def main():
    blocks = python_blocks()
    data = write_data(blocks)
    sources = {"TOOL": filled_script(TOOL_PATH, blocks)}
    patch_tester(read(TOOL_PATH))
    fonts = installed_fonts()
    build_html(js_data(), fonts, sources)
    print("割り当て %d件（うち見た目のプリセット %d件）/ 書体 %d件 を書き出しました。"
          % (len(ENTRIES), sum(1 for e in ENTRIES if e["look"]), len(fonts)))
    print("装飾データ.json: RULES %d件 / LOOKS %d件 / SWATCH_CASES %d件（版 %d）"
          % (len(data["RULES"]), len(data["LOOKS"]), len(data["SWATCH_CASES"]),
             DATA_VERSION))
    for name, pair, note in check_fonts():
        print("注意: %s の書体 %r スタイル %r が見つかりません（%s）。"
              % (name, pair[0], pair[1], note))
    for name, font, width, limit in check_counters():
        print("注意: %s は縁が %.3f で、%s の上限 %.3f を超えます（漢字の内側が塗り潰れます）。"
              % (name, width, font, limit))

    print(test_note())

    faces = patch_probe()
    over, unknown = check_widths()
    for name, font, width, size in over:
        print("注意: %s は全角%d文字で画面の %.0f%% を占めます（上限 %.0f%%）。"
              "大きさを %.4f 以下にするか、字送りを詰めてください。"
              % (name, FIT_CHARS, width * 100, FIT_WIDTH * 100, size))
    if unknown:
        print("幅の関門が %d書体ぶん働いていません。%s"
              % (len(unknown), width_frame_note()))
        print("  Resolve の Console で Resolveで動かす/道具_Text+の実寸と書体の字幅を測ってサンプルデータを変更する.py を実行してください（書体 %d件）。" % faces)


main()
