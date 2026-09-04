"""テロップpresetの見本画像。

設定画面でpresetを選ぶとき、名前(「カワイイ」「ホラー」)だけでは何が変わるのか分からない。
ここは各presetを実際に **libassで1 frame焼いて** pngにする。CSSやSVGで似せて描くことも
できるが、そうすると見本と本番で別々の実装を持つことになり、片方を直したときに黙ってずれる
— 見本が嘘をつくくらいなら見本は無い方がましなので、本番と同じ ``telop_styles`` の
Style行・Dialogue tagをそのまま使う。

## 本番と違うのはfont sizeと背景だけ

font sizeは見本用に大きく固定する。縁の太さ・影・字間・blurは全て「font sizeとの比」で
持っているので、大きさを変えても見た目の比率は本番と同じになる。実際のfont sizeは利用者が
別の設定で決めるものなので、見本でそれを再現しても情報が増えない(むしろthumbnailでは
小さすぎて何も見えない)。

背景は暗→明のgradient。テロップの可読性は背後の明るさで決まるので、単色の板に置くと
「白文字に縁が要る理由」も「発光の効き」も見えない。1枚で明暗の両端を跨がせる。

生成物はwork rootのpoolへcacheし、presetの定義が変わったら別名になる(署名をfile名へ
畳む)ので、定義を触ったのに古い見本が出続けることはない。
"""

import asyncio
import hashlib
import logging
from pathlib import Path

from tictok.core import ffprobe, layout
from tictok.record import fonts, telop_styles
from tictok.record.recorder import ffmpeg_available

logger = logging.getLogger("tictok.telop_preview")

# 見本の寸法とfont size。帯だけを切り出した横長で、設定画面へ並べたときに書体が読める
# 大きさにしてある(本番のfont sizeとは無関係 — 上のdocstring参照)。
WIDTH = 720
HEIGHT = 200
FONT_SIZE = 54

# 見本の文言。ひらがな・漢字・カタカナ・英数を1行に含める(書体の差は仮名の形に出やすく、
# 英数が無いと欧文しか持たないfontを取り違えたときに気付けない)。
SAMPLE_TEXT = "ここが今日イチの盛り上がり！"

# 背景のgradient(暗→明)。両端の明るさを跨がせて、縁・影・発光の効きを見えるようにする。
BG_DARK = "#12141A"
BG_LIGHT = "#D8DCE4"
# ``gradients`` filterは**既定で乱数**である: seedの既定が-1(毎回ランダム)で、さらに
# speed=0.01でgradientが時間とともに回る。色と両端の座標を明示しても、これを止めない限り
# 描くたびに違う背景になる(実測: 同一commandの3回の描画が全て別hash)。presetごとに背景が
# 違うと、比べているのが書体なのか背景なのか分からなくなる。seedを固定しspeedを0にする。
BG_SEED = 7
BG_SPEED = 0

# 名前の実体は ``layout`` が持つ。root直下の共有dirは ``NON_STREAMER_DIRS`` にも載る必要が
# あり、名前が2箇所に在ると片方だけ直したときに容量の内訳と削除の対象が食い違う。
PREVIEW_DIRNAME = layout.TELOP_PREVIEW_DIRNAME


def preview_dir() -> Path:
    return layout.pool_root() / PREVIEW_DIRNAME


def signature(style: "telop_styles.TelopStyle", animate: bool) -> str:
    """presetの見た目を決める値ぜんぶの指紋。定義を1つでも触れば別名になる。"""
    h = hashlib.sha256()
    h.update(repr((style, animate, WIDTH, HEIGHT, FONT_SIZE, SAMPLE_TEXT,
                   BG_DARK, BG_LIGHT, BG_SEED, BG_SPEED)).encode("utf-8"))
    return h.hexdigest()[:12]


def preview_path(style: "telop_styles.TelopStyle", animate: bool) -> Path:
    return preview_dir() / f"{style.key}-{signature(style, animate)}.png"


def _ass_text(style: "telop_styles.TelopStyle", animate: bool) -> str:
    """本番と同じStyle行・Dialogue tagで組んだ見本用のASS。

    animationは静止画では見えないので、``\\fad`` を外した状態で描く(fadeの途中を焼くと、
    presetの色が薄く写って別物に見える)。popは終点の字形が本番の見た目なので、
    ``dialogue_tags`` が付ける ``\\t`` の到達値と一致する。"""
    events = [
        f"Dialogue: {layer},0:00:00.00,0:00:05.00,{name},,0,0,0,,{tags}{SAMPLE_TEXT}"
        for layer, name, tags in telop_styles.cue_layers(
            style, WIDTH // 2, HEIGHT // 2, FONT_SIZE, animate=False)
    ]
    return (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {WIDTH}\nPlayResY: {HEIGHT}\n"
        "ScaledBorderAndShadow: yes\nWrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + "\n".join(telop_styles.style_lines(style, FONT_SIZE)) + "\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(events) + "\n"
    )


def _render_sync(style: "telop_styles.TelopStyle", animate: bool, out: Path) -> None:
    """ffmpegを1回だけ回して見本を書く。ASSはcwdへ置いてbare nameで参照する(本番と同じく、
    Windowsのdrive付きpathをfilter graphへ渡さずに済ませるため)。"""
    from tictok.record.video_overlay import fontsdir_arg

    out.parent.mkdir(parents=True, exist_ok=True)
    ass_path = out.with_suffix(".ass")
    ass_path.write_text(_ass_text(style, animate), encoding="utf-8")
    vf = f"ass={ass_path.name}"
    if style.font_file:
        vf += f":fontsdir={fontsdir_arg(fonts.telop_font_dir(style.font_file))}"
    tmp = out.with_suffix(".part.png")
    try:
        proc = ffprobe.run_sync(
            ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
             "-f", "lavfi",
             "-i", (f"gradients=s={WIDTH}x{HEIGHT}:c0={BG_DARK}:c1={BG_LIGHT}"
                    f":x0=0:y0=0:x1={WIDTH}:y1={HEIGHT}:nb_colors=2"
                    f":seed={BG_SEED}:speed={BG_SPEED}:d=1"),
             "-vf", vf, "-frames:v", "1", tmp.name],
            timeout=ffprobe.SHORT_TIMEOUT_SECONDS, cwd=out.parent,
        )
        if not proc.ok or not tmp.is_file():
            raise RuntimeError(
                f"テロップ見本の描画に失敗しました（preset={style.key}）: "
                f"{(proc.stderr or '').strip()[-400:]}")
        # 描き切ってから置く。途中のfileが見本として配られると、半端な画像が
        # 「そういうpresetだ」と読まれる。
        tmp.replace(out)
    finally:
        ass_path.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)


_locks: dict = {}
_locks_guard = asyncio.Lock()


async def ensure_preview(style: "telop_styles.TelopStyle", animate: bool = True) -> Path:
    """見本pngを用意してpathを返す。既にあれば作らない。

    同じpresetへ同時に来ても1回しか描かないよう、preset単位でlockする(設定画面は
    全presetを一斉に読みに来る)。"""
    if not ffmpeg_available():
        raise RuntimeError("ffmpegが見つかりません。テロップ見本の生成にはffmpegが必要です。")
    out = preview_path(style, animate)
    if out.is_file():
        return out
    async with _locks_guard:
        lock = _locks.setdefault(out.name, asyncio.Lock())
    async with lock:
        if out.is_file():
            return out
        if style.font_file:
            # 見本のためにfontを落とす。本番の焼き込みと同じ書体でなければ見本の意味が無い。
            await asyncio.to_thread(fonts.ensure_telop_font, style.font_file)
        await asyncio.to_thread(_render_sync, style, animate, out)
        _prune_stale(style, out)
        logger.info(
            "テロップ見本を生成しました: %s", out.name,
            extra={"event": "telop.preview_rendered",
                   "ctx": {"style": style.key, "path": str(out),
                           "font_family": style.font_family}},
        )
    return out


def _prune_stale(style: "telop_styles.TelopStyle", keep: Path) -> None:
    """同じpresetの古い署名の見本を消す。定義を触るたびに増え続けるのを防ぐ。"""
    for old in keep.parent.glob(f"{style.key}-*.png"):
        if old != keep:
            old.unlink(missing_ok=True)
