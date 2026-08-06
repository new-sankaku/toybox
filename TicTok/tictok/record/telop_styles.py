"""焼き込み字幕(テロップ)の見た目preset。

これまで字幕は「Sans・白・黒縁1本・動きなし」の1種類しか無く、しかも ``Sans`` は
libassがhostのfont設定で解決するため、実際に何で描かれるかはmachine任せだった(この
machineでの実測: ``Sans`` は ArialMT + YuGothicUI-Semibold へ落ちる)。日本語のshort動画
のテロップは書体そのものが表現なので、書体を決め打ちできないことが品質の上限になっていた。

ここでは preset を「同梱fontのfamily名 + 色 + 縁 + 影 + 動き」の値として持ち、ASSの
Style行とDialogueの上書きtagを組み立てる。fontはassets/fontsへ落として ``ass`` filterの
``fontsdir`` で読ませるので、host に何が入っていても出力は同じになる。

## 2層で描く

ASSのstyleは縁を1本しか持てない。日本語のテロップで標準的な「本文＋細い縁＋外側の太い縁
(または滲む発光)」は、同じ文字列を2つのDialogueで重ねて出す:

* 下層(``SubtitleEdge``) … 塗りも縁も *glow色* の塊。太い縁とblurはここだけに掛ける。
* 上層(``Subtitle``)     … 本来の塗りと細い縁。下層の塊を覆い隠す。

下層の塗りを縁と同色にするのは、上層のanti-aliasの縁から下層の塗りが別の色として
にじみ出るのを防ぐため。``glow_ratio`` が0のpresetは下層を作らない(1層のまま)。

## 縁の太さは書体の線の太さに合わせる

同じ ``edge_ratio`` でも、書体によって結果はまるで違う。極太のdisplay体(Reggae One)や
線の細い手書き体(Hachi Maru Pop)では、縁が字画そのものを食い潰して塗りの色が消える
(実測でどちらも一度そうなった)。太さで見せたいときは内側の縁ではなく **外側の縁**
(``glow_ratio``)を太くすること — 外側は字画を侵食しない。

## 寸法は全てfont sizeとの比

縁の太さ・影・字間・blurは全て「font sizeに対する比」で持つ。字幕のfont sizeは動画の
解像度に比例して決まるので(``video_overlay_subtitle_font_size``)、比で持てば解像度が
変わっても見た目が変わらない。絶対pxで持つと1080pと720pで別物になる。

## font familyは実測値

``font_family`` はlibassが名乗る家族名で、fileの名前でもGoogle Fontsのfamily名でもない。
実際に ``fontselect:`` のlogで解決先を確認して決めている — 例えば Shippori Mincho B1 の
ExtraBoldは、家族名 ``Shippori Mincho B1`` では **一致せず** 既定fontへ落ち、
``Shippori Mincho B1 ExtraBold`` で初めて当たる。ここを推測で書くと、fontsdirを渡している
のに黙って別のfontで焼ける。
"""

from dataclasses import dataclass
from typing import Optional

# 同梱fontを使わないpreset用の家族名。libassがhostのfont設定で解決する。
HOST_SANS = "Sans"


def ass_colour(hex_rgb: str, alpha: int = 0) -> str:
    """``#RRGGBB`` -> Style欄の ``&HAABBGGRR``。alphaは0が不透明・255が透明。"""
    h = hex_rgb.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"colour must be #RRGGBB: {hex_rgb!r}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


@dataclass(frozen=True)
class Ghost:
    """本体の下へ**ずらして**敷く影武者。

    ずらさない下層(``glow_*``)は縁や発光にしかならない。位置をずらせるとベタ影(漫画の
    ように硬く落ちる影)や色ずれ(グリッチ)が作れる — ASSのShadowは1方向1色しか持てず、
    色を変えることも複数置くこともできないので、これは層でしか表現できない。

    ずれ幅はfont sizeとの比。``edge_ratio`` はghost自身の縁で、0なら塗りだけになる。
    """

    colour: str
    dx_ratio: float
    dy_ratio: float
    alpha: int = 0x00
    blur_ratio: float = 0.0
    edge_ratio: float = 0.0


@dataclass(frozen=True)
class TelopStyle:
    """1つのテロップpreset。比の基準は全て字幕のfont size。"""

    key: str
    label: str
    # 同梱font。font_fileがNoneのpresetはhostのfontで描く(fontsdirを必要としない)。
    font_file: Optional[str]
    font_family: str
    bold: bool = False
    italic: bool = False
    # 本文と細い縁。``box`` がTrueのときは縁ではなく**背景の帯**になる(BorderStyle 3):
    # edgeが帯の色、edge_ratioが帯の余白、edge_alphaが帯の透け具合。
    fill: str = "#FFFFFF"
    edge: str = "#000000"
    edge_ratio: float = 0.10
    edge_alpha: int = 0x00
    box: bool = False
    # 影(右下へのずらし)。色は影専用でBackColourへ入る。
    shadow_ratio: float = 0.05
    shadow: str = "#000000"
    shadow_alpha: int = 0x80
    # 下層(外側の縁 / 発光)。glow_ratioが0なら下層を作らない。
    glow: str = "#000000"
    glow_ratio: float = 0.0
    glow_blur_ratio: float = 0.0
    glow_alpha: int = 0x00
    # 位置をずらして敷く層(下から順)。ベタ影・色ずれ用。
    ghosts: tuple = ()
    # 字間と字形。scaleは縦長/横長、shearは斜体風の傾き(\fax)、angleは行ごとの回転。
    spacing_ratio: float = 0.0
    scale_x: int = 100
    scale_y: int = 100
    shear_x: float = 0.0
    angle: float = 0.0
    # 出入りのfade(ms)と、出だしの拡大pop(開始倍率%と到達までのms)。
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    pop_percent: int = 100
    pop_ms: int = 0

    @property
    def has_glow(self) -> bool:
        # 帯presetは下層を持たない。帯の上にもう1枚帯を敷いても濃くなるだけで、
        # 帯の縁として見えるものは何も増えない。
        return self.glow_ratio > 0 and not self.box

    @property
    def animated(self) -> bool:
        return bool(self.fade_in_ms or self.fade_out_ms or self.pop_percent != 100)


# 並び順がそのまま設定画面の選択肢の順になる。値(1始まり)は設定へ保存される識別子なので、
# 既存の設定値の意味が変わらないよう **並べ替えても既存styleの値は動かさない** こと。
TELOP_STYLES: tuple[TelopStyle, ...] = (
    TelopStyle(
        key="normal",
        label="通常（太ゴシック・白＋黒縁）",
        font_file="NotoSansCJKjp-Bold.otf",
        font_family="Noto Sans CJK JP",
        bold=True,
        fill="#FFFFFF",
        edge="#000000",
        edge_ratio=0.11,
        shadow_ratio=0.05,
        shadow_alpha=0x80,
        fade_in_ms=100,
        fade_out_ms=80,
    ),
    TelopStyle(
        key="variety",
        label="バラエティ（極太・黄色＋白フチ）",
        font_file="ReggaeOne-Regular.ttf",
        font_family="Reggae One",
        fill="#FFE13F",
        # 極太のdisplay体なので、縁を太くすると字面が縁で埋まって塗りが見えなくなる
        # (実測: 0.09では黄色がほぼ潰れた)。黒は輪郭線程度に留め、太さは外側の白で稼ぐ。
        edge="#20160A",
        edge_ratio=0.05,
        glow="#FFFFFF",
        glow_ratio=0.20,
        shadow_ratio=0.07,
        shadow_alpha=0x60,
        pop_percent=86,
        pop_ms=110,
        fade_in_ms=60,
        fade_out_ms=60,
    ),
    TelopStyle(
        key="cute",
        label="カワイイ（丸ポップ体・白＋ピンクフチ）",
        font_file="MochiyPopOne-Regular.ttf",
        font_family="Mochiy Pop One",
        fill="#FFFFFF",
        edge="#FF5FA2",
        edge_ratio=0.13,
        glow="#FFFFFF",
        glow_ratio=0.26,
        shadow="#FF9CC6",
        shadow_ratio=0.06,
        shadow_alpha=0x50,
        spacing_ratio=0.02,
        pop_percent=84,
        pop_ms=150,
        fade_in_ms=90,
        fade_out_ms=90,
    ),
    TelopStyle(
        key="horror",
        label="ホラー（極太明朝・血色の滲み）",
        font_file="ShipporiMinchoB1-ExtraBold.ttf",
        # 家族名が"Shippori Mincho B1"ではないのは冒頭のdocstringの通り(実測)。
        font_family="Shippori Mincho B1 ExtraBold",
        fill="#E6E2E2",
        # 血色の滲みが見えるよう、内側の黒は細く。暗すぎる赤(#6E0A0A)は明るい映像の上で
        # ただの黒い染みになったので、彩度と明度を上げてある(実測)。
        edge="#12080A",
        edge_ratio=0.06,
        glow="#B01414",
        glow_ratio=0.26,
        glow_blur_ratio=0.13,
        shadow="#000000",
        shadow_ratio=0.09,
        shadow_alpha=0x40,
        spacing_ratio=0.05,
        fade_in_ms=280,
        fade_out_ms=240,
    ),
    TelopStyle(
        key="neon",
        label="ネオン（太ゴシック・水色の発光）",
        font_file="NotoSansCJKjp-Bold.otf",
        font_family="Noto Sans CJK JP",
        bold=True,
        fill="#FFFFFF",
        edge="#0A3A4C",
        edge_ratio=0.07,
        glow="#25E0FF",
        glow_ratio=0.20,
        glow_blur_ratio=0.14,
        shadow_ratio=0.0,
        spacing_ratio=0.05,
        fade_in_ms=140,
        fade_out_ms=140,
    ),
    TelopStyle(
        key="retro",
        label="レトロ（ドット体・白＋黒縁）",
        font_file="DotGothic16-Regular.ttf",
        font_family="DotGothic16",
        fill="#FFFFFF",
        edge="#000000",
        edge_ratio=0.12,
        shadow="#000000",
        shadow_ratio=0.10,
        shadow_alpha=0x00,
        spacing_ratio=0.03,
    ),
    TelopStyle(
        key="band",
        label="ニュース帯（半透明の黒帯・白文字）",
        font_file="NotoSansCJKjp-Bold.otf",
        font_family="Noto Sans CJK JP",
        bold=True,
        fill="#FFFFFF",
        # 縁ではなく帯。edgeが帯の色、edge_ratioが余白、edge_alphaが透け具合になる。
        box=True,
        edge="#0A0A0C",
        edge_ratio=0.30,
        edge_alpha=0x40,
        shadow_ratio=0.0,
        spacing_ratio=0.02,
        fade_in_ms=120,
        fade_out_ms=100,
    ),
    TelopStyle(
        key="cinema",
        label="映画字幕（明朝・細字・控えめ）",
        font_file="ShipporiMincho-Regular.ttf",
        font_family="Shippori Mincho",
        fill="#F2F0EC",
        # 劇場字幕は縁で囲わない。輪郭は最小限にして、可読性は影で確保する。ただし縁も影も
        # 削りすぎると明るい映像の上で消える(実測: 0.04 + 薄い影では白背景で読めなかった)。
        edge="#000000",
        edge_ratio=0.06,
        shadow="#000000",
        shadow_ratio=0.07,
        shadow_alpha=0x30,
        spacing_ratio=0.06,
        fade_in_ms=180,
        fade_out_ms=180,
    ),
    TelopStyle(
        key="handwritten",
        label="手書き（マーカー風・少し傾く）",
        font_file="YuseiMagic-Regular.ttf",
        font_family="Yusei Magic",
        fill="#FFFFFF",
        edge="#243042",
        edge_ratio=0.10,
        glow="#FFFFFF",
        glow_ratio=0.20,
        shadow="#243042",
        shadow_ratio=0.06,
        shadow_alpha=0x60,
        angle=1.8,
        fade_in_ms=90,
        fade_out_ms=90,
        pop_percent=90,
        pop_ms=120,
    ),
    TelopStyle(
        key="marshmallow",
        label="ゆるふわ（丸手書き・パステル）",
        font_file="HachiMaruPop-Regular.ttf",
        font_family="Hachi Maru Pop",
        fill="#FF6BA6",
        # 線の細い書体なので白フチは細く(実測: 0.17では白がピンクを食い潰した)。
        # 外側は淡色にしない。パステルで固めると明るい映像の上で輪郭が消える。
        # 白フチの外へ濃い薔薇色を1枚置くと、暗い映像でも明るい映像でも形が残る。
        edge="#FFFFFF",
        edge_ratio=0.06,
        glow="#B33A6B",
        glow_ratio=0.20,
        glow_blur_ratio=0.03,
        shadow="#B33A6B",
        shadow_ratio=0.05,
        shadow_alpha=0x50,
        spacing_ratio=0.03,
        fade_in_ms=140,
        fade_out_ms=140,
        pop_percent=80,
        pop_ms=180,
    ),
    TelopStyle(
        key="japanese",
        label="和風（筆書体・墨＋朱）",
        font_file="YujiSyuku-Regular.ttf",
        font_family="Yuji Syuku",
        fill="#F5F0E6",
        edge="#14100E",
        edge_ratio=0.08,
        glow="#8C1B1B",
        glow_ratio=0.20,
        glow_blur_ratio=0.03,
        shadow="#14100E",
        shadow_ratio=0.07,
        shadow_alpha=0x50,
        spacing_ratio=0.08,
        fade_in_ms=220,
        fade_out_ms=200,
    ),
    TelopStyle(
        key="impact",
        label="インパクト（極太・縦長・赤フチ）",
        font_file="RocknRollOne-Regular.ttf",
        font_family="RocknRoll One",
        fill="#FFFFFF",
        edge="#C81428",
        edge_ratio=0.07,
        glow="#1A0508",
        glow_ratio=0.20,
        # 縦へ伸ばして横を締めると、同じ幅により大きい字が入る(叫び系のテロップの作法)。
        scale_x=94,
        scale_y=118,
        shadow_ratio=0.06,
        shadow_alpha=0x70,
        pop_percent=78,
        pop_ms=100,
        fade_in_ms=50,
        fade_out_ms=60,
    ),
    TelopStyle(
        key="cyber",
        label="サイバー（二重線・紫＋水色の発光）",
        font_file="TrainOne-Regular.ttf",
        font_family="Train One",
        fill="#F2E9FF",
        # 字画が二重線で抜けた書体なので、発光を強くすると抜けが埋まって普通の太字に見える。
        # 光は形が読める範囲に留める(実測: blur 0.16では二重線が潰れた)。
        edge="#2B0A4A",
        edge_ratio=0.05,
        glow="#B44BFF",
        glow_ratio=0.13,
        glow_blur_ratio=0.09,
        shadow_ratio=0.0,
        spacing_ratio=0.07,
        shear_x=-0.12,
        fade_in_ms=110,
        fade_out_ms=110,
    ),
    TelopStyle(
        key="pop",
        label="ポップ（丸ゴシック・橙＋白フチ・傾く）",
        font_file="ZenMaruGothic-Bold.ttf",
        font_family="Zen Maru Gothic",
        bold=True,
        fill="#FF8A1F",
        edge="#3A1C00",
        edge_ratio=0.07,
        glow="#FFFFFF",
        glow_ratio=0.24,
        shadow="#3A1C00",
        shadow_ratio=0.07,
        shadow_alpha=0x50,
        angle=-2.2,
        pop_percent=82,
        pop_ms=140,
        fade_in_ms=70,
        fade_out_ms=70,
    ),
    TelopStyle(
        key="news_intl",
        label="海外ニュース（不透明の赤ブロック・白文字）",
        font_file="NotoSansCJKjp-Bold.otf",
        font_family="Noto Sans CJK JP",
        bold=True,
        fill="#FFFFFF",
        # 海外局の下段テロップは「透けない色板」。日本の帯のように背景を透かさないので、
        # ニュース帯presetと違って alpha は0(完全不透明)にする。
        box=True,
        edge="#C8102E",
        edge_ratio=0.26,
        edge_alpha=0x00,
        shadow_ratio=0.0,
        spacing_ratio=0.03,
        # 出入りは切り替えで、淡く消えない。
        fade_in_ms=0,
        fade_out_ms=0,
    ),
    TelopStyle(
        key="streaming",
        label="配信字幕（白・フチ無し・柔らかい影）",
        font_file="NotoSansCJKjp-Bold.otf",
        font_family="Noto Sans CJK JP",
        bold=True,
        fill="#FFFFFF",
        # 海外の配信serviceの字幕は縁を持たない。可読性は「ぼかした影を斜め下へ落とす」で
        # 稼ぐ。ASSのShadowは硬い1色なので、ぼかしはghostでしか作れない。
        edge="#000000",
        edge_ratio=0.02,
        shadow_ratio=0.0,
        ghosts=(
            Ghost(colour="#000000", dx_ratio=0.02, dy_ratio=0.05,
                  alpha=0x30, blur_ratio=0.10, edge_ratio=0.06),
        ),
        fade_in_ms=100,
        fade_out_ms=100,
    ),
    TelopStyle(
        key="minimal",
        label="ミニマル（細字・広い字間・装飾なし）",
        font_file="NotoSansCJKjp-Regular.otf",
        font_family="Noto Sans CJK JP",
        bold=False,
        fill="#FFFFFF",
        edge="#000000",
        edge_ratio=0.03,
        # 字間を大きく開けるのがこの系統の要。日本の実況テロップではまず見ないが、
        # 海外のvlog/documentaryの定番。開けすぎると1行に入る字数が目に見えて減るので
        # (実測: 0.24では見本の14字が画面幅いっぱいになった)、この辺りが上限。
        spacing_ratio=0.17,
        shadow="#000000",
        shadow_ratio=0.05,
        shadow_alpha=0x40,
        fade_in_ms=200,
        fade_out_ms=200,
    ),
    TelopStyle(
        key="sports",
        label="スポーツ中継（紺のブロック・斜体・幅詰め）",
        font_file="NotoSansCJKjp-Bold.otf",
        font_family="Noto Sans CJK JP",
        bold=True,
        fill="#FFFFFF",
        box=True,
        edge="#0B2540",
        edge_ratio=0.24,
        edge_alpha=0x10,
        shadow_ratio=0.0,
        # 前傾させて横幅を詰める。速度感を出す海外スポーツ中継の作法。
        shear_x=0.22,
        scale_x=92,
        spacing_ratio=0.02,
        fade_in_ms=60,
        fade_out_ms=60,
    ),
    TelopStyle(
        key="comic",
        label="アメコミ（黄色・太フチ・硬いベタ影）",
        font_file="RocknRollOne-Regular.ttf",
        font_family="RocknRoll One",
        fill="#FFD23F",
        edge="#111013",
        edge_ratio=0.07,
        glow="#FFFFFF",
        glow_ratio=0.18,
        # ぼかさず真後ろへずらす黒。印刷物のベタ影で、ASSのShadowでは色も距離も足りない。
        ghosts=(
            Ghost(colour="#111013", dx_ratio=0.07, dy_ratio=0.08, edge_ratio=0.18),
        ),
        pop_percent=80,
        pop_ms=120,
        fade_in_ms=40,
        fade_out_ms=50,
    ),
    TelopStyle(
        key="glitch",
        label="グリッチ（白＋シアン/マゼンタの色ずれ）",
        font_file="NotoSansCJKjp-Bold.otf",
        font_family="Noto Sans CJK JP",
        bold=True,
        fill="#FFFFFF",
        edge="#0A0A0F",
        edge_ratio=0.04,
        shadow_ratio=0.0,
        # 色ずれは左上へシアン・右下へマゼンタ。1色1方向しか持てないShadowでは作れない。
        ghosts=(
            Ghost(colour="#00E5FF", dx_ratio=-0.05, dy_ratio=-0.035, edge_ratio=0.03),
            Ghost(colour="#FF00A8", dx_ratio=0.05, dy_ratio=0.035, edge_ratio=0.03),
        ),
        spacing_ratio=0.04,
        fade_in_ms=40,
        fade_out_ms=40,
    ),
)

# 設定に保存される値 -> preset。1始まりなのは、0が「未設定/OFF」に見えるのを避けるため。
STYLE_VALUES: dict[int, TelopStyle] = {i: s for i, s in enumerate(TELOP_STYLES, start=1)}
DEFAULT_STYLE_VALUE = 1


def settings_options() -> list:
    """設定画面の選択肢。presetの並びと1対1で、ここ以外に一覧を持たない。"""
    return [{"value": value, "label": style.label} for value, style in STYLE_VALUES.items()]


def style_for(value) -> TelopStyle:
    """設定値からpresetを引く。未知の値は落とす — 知らないstyleを既定へ読み替えると、
    利用者が選んだのと違う見た目で恒久的に焼き込まれる(取り返しがつかない)。"""
    try:
        key = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"unknown telop style: {value!r}") from None
    if key not in STYLE_VALUES:
        raise ValueError(f"unknown telop style: {value!r}")
    return STYLE_VALUES[key]


def font_files() -> tuple:
    """全presetが使う同梱fontのfile名(重複なし)。"""
    seen: list = []
    for style in TELOP_STYLES:
        if style.font_file and style.font_file not in seen:
            seen.append(style.font_file)
    return tuple(seen)


# ASSのStyle行の名前。上層が本来の字幕で、下層は外側の縁/発光、その下がghost。
STYLE_NAME = "Subtitle"
EDGE_STYLE_NAME = "SubtitleEdge"
GHOST_STYLE_PREFIX = "SubtitleGhost"
# Dialogueのlayer。数が大きいほど上に描かれる。Comment(4,5)・Gift(6)・Battle(6,7)より
# 上に出す — 字幕が他の要素の下に潜ると読めなくなる。
GHOST_LAYER = 8
EDGE_LAYER = 9
TEXT_LAYER = 10


def _px(ratio: float, font_size: int, minimum: int = 0) -> int:
    return max(minimum, int(round(ratio * font_size)))


def _offset_px(ratio: float, font_size: int) -> int:
    """符号を保つ換算。ghostのずれは負にもなる(左上へずらす色ずれ)ので、``_px`` の
    下限clampを通してはならない — 通すと片側のghostだけ本体へ吸い付く。"""
    return int(round(ratio * font_size))


def style_lines(style: TelopStyle, font_size: int) -> list:
    """このpresetの ``[V4+ Styles]`` 行。glowが無いpresetは1行だけ返す。

    ``box`` のpresetは BorderStyle 3(不透明box)で、縁の代わりに文字の後ろへ帯を敷く。
    ASSでは帯の色はOutlineColour・帯の余白はOutlineの値で決まるので、縁と同じfieldが
    別の意味になる(BorderStyleを切り替えるだけで両者を書き分けられる)。"""
    spacing = round(style.spacing_ratio * font_size, 2)
    bold = -1 if style.bold else 0
    italic = -1 if style.italic else 0
    border_style = 3 if style.box else 1
    common = f"{style.font_family},{font_size}"
    tail = (f"{bold},{italic},0,0,{style.scale_x},{style.scale_y},{spacing},"
            f"{style.angle:g},{border_style}")
    lines = []
    for index, ghost in enumerate(style.ghosts):
        colour = ass_colour(ghost.colour, ghost.alpha)
        lines.append(
            f"Style: {GHOST_STYLE_PREFIX}{index},{common},{colour},{colour},{colour},{colour},"
            f"{tail},{_px(ghost.edge_ratio, font_size)},0,5,0,0,0,1"
        )
    if style.has_glow:
        glow = ass_colour(style.glow, style.glow_alpha)
        lines.append(
            f"Style: {EDGE_STYLE_NAME},{common},{glow},{glow},{glow},{glow},{tail},"
            f"{_px(style.glow_ratio, font_size, 1)},0,5,0,0,0,1"
        )
    lines.append(
        f"Style: {STYLE_NAME},{common},{ass_colour(style.fill)},{ass_colour(style.fill)},"
        f"{ass_colour(style.edge, style.edge_alpha)},"
        f"{ass_colour(style.shadow, style.shadow_alpha)},{tail},"
        f"{_px(style.edge_ratio, font_size, 1)},{_px(style.shadow_ratio, font_size)},5,0,0,0,1"
    )
    return lines


def dialogue_tags(style: TelopStyle, x: int, y: int, font_size: int, *,
                  animate: bool = True, edge_layer: bool = False,
                  blur_ratio: float = 0.0) -> str:
    """1行ぶんのDialogueの先頭に付く上書きtag。

    ``animate`` がFalseならfadeもpopも付けない(動きを嫌う用途のための設定)。重ねる層は
    全て同じ動きtagを持たせる — 片方だけ動かすと層がずれて縁が剥がれる。

    popの到達先はpresetの縦横比(``scale_x``/``scale_y``)であって100%ではない。100%へ
    戻すと、縦長のpresetがpopの最後で普通の字形へ化ける。"""
    tags = [f"\\an5\\pos({x},{y})"]
    if style.shear_x:
        tags.append(f"\\fax{style.shear_x:g}")
    blur = blur_ratio or (style.glow_blur_ratio if edge_layer else 0.0)
    if blur > 0:
        tags.append(f"\\blur{round(blur * font_size, 1)}")
    if animate:
        if style.fade_in_ms or style.fade_out_ms:
            tags.append(f"\\fad({style.fade_in_ms},{style.fade_out_ms})")
        if style.pop_percent != 100 and style.pop_ms > 0:
            sx = round(style.scale_x * style.pop_percent / 100)
            sy = round(style.scale_y * style.pop_percent / 100)
            tags.append(
                f"\\fscx{sx}\\fscy{sy}"
                f"\\t(0,{style.pop_ms},\\fscx{style.scale_x}\\fscy{style.scale_y})"
            )
    return "{" + "".join(tags) + "}"


def cue_layers(style: TelopStyle, x: int, y: int, font_size: int, *,
               animate: bool = True) -> list:
    """字幕1件を描くのに要る ``(layer, Style名, tag)`` を下から順に返す。

    重ね方の正解をここ1箇所に置く。焼き込みと設定画面の見本は別々のmoduleだが、どちらも
    これを回してDialogueを作る — 層の数や順序を各々が組み立てると、見本と成果物で重なりが
    違うという最悪の食い違い方をする(見本は嘘をつくが、誰も気付けない)。"""
    layers = []
    for index, ghost in enumerate(style.ghosts):
        layers.append((
            GHOST_LAYER,
            f"{GHOST_STYLE_PREFIX}{index}",
            dialogue_tags(style,
                          x + _offset_px(ghost.dx_ratio, font_size),
                          y + _offset_px(ghost.dy_ratio, font_size),
                          font_size, animate=animate, blur_ratio=ghost.blur_ratio),
        ))
    if style.has_glow:
        layers.append((EDGE_LAYER, EDGE_STYLE_NAME,
                       dialogue_tags(style, x, y, font_size,
                                     animate=animate, edge_layer=True)))
    layers.append((TEXT_LAYER, STYLE_NAME,
                   dialogue_tags(style, x, y, font_size, animate=animate)))
    return layers
