# -*- coding: utf-8 -*-
"""
【Resolve の Console に貼る】Workspace > Console > Py3。これ1本で終わります。

Text+ の値が実際に何pxになるかを、Resolve に描かせて測る。
測った値は 手元で動かす/道具_装飾プリセットを生成.py へ書き戻し、見本帳まで作り直す。
手元でコマンドを打つ必要はない。

    Workspace > Console > Py3 にこれを貼って実行するだけ

やっていること:
    1. Text+ ほかの Input を全部書き出す（名前・型・いまの値）
    2. 要素1〜8が何を持っているかを書き出す
    3. 値を書いて読み返し、入るもの・入らないもの・そもそも無いものを判定する
    4. 換算を測る画像を書き出す（大きさ・縁の太さ・ぼかし・帯の余白・角丸）
    5. 書体ごとの送り幅を測る画像を書き出す（全角1文字が横にどれだけ進むか）
    6. 手元の python を呼んで画像を測り、生成側へ書き戻して見本帳を作り直す

**結果は全部ファイルに残る。** Console からcopyする必要は無い。

    doc/測定/Input一覧.txt       1 の結果
    doc/測定/要素の中身.txt      2 の結果
    doc/測定/書き込み結果.txt    3 の結果
    doc/測定/換算と送り幅.txt    4〜6 の結果
    doc/測定/実測.json           上の全部を機械が読める形で
    doc/測定/画像/               書き出した静止画そのもの

Console に出るのは要約だけ。6 は Pillow と numpy が要る。
PROJECT と PYTHON と FRAME は 手元で動かす/道具_装飾プリセットを生成.py が実行のたびに書き替える。

測定用のタイムラインは書き出したあと消す。既存のタイムラインには触らない。
"""

import json
import os
import shutil
import subprocess
import sys

# 生成側（手元で動かす/道具_装飾プリセットを生成.py）が書き替える。手で直さない。
PROJECT = r"C:\01_work\00_Git\toybox\TicTok\Davinci Resolve Script"
PYTHON = r"C:\Users\sanka\AppData\Local\Programs\Python\Python310\python.exe"
FACES = [
    ["Noto Sans JP", "Bold"],
    ["BIZ UDPGothic", "Bold"],
    ["Noto Sans JP Medium", "Regular"],
    ["Noto Sans JP Black", "Regular"],
    ["HGMaruGothicMPRO", "Regular"],
    ["HGPSoeiKakupoptai", "Regular"],
    ["RocknRoll One", "Regular"],
    ["Mochiy Pop One", "Regular"],
    ["Zen Maru Gothic Black", "Regular"],
    ["Zen Maru Gothic", "Bold"],
    ["UD Digi Kyokasho NP-B", "Bold"],
    ["HGPKyokashotai", "Medium"],
    ["Yusei Magic", "Regular"],
    ["Hachi Maru Pop", "Regular"],
    ["Yomogi", "Regular"],
    ["Noto Serif JP", "Regular"],
    ["Yu Mincho Demibold", "Bold"],
    ["Shippori Mincho B1 ExtraBold", "Regular"],
    ["Klee One SemiBold", "Regular"],
    ["Zen Old Mincho Black", "Regular"],
    ["Noto Sans JP DemiLight", "Regular"],
    ["Zen Antique", "Regular"],
    ["HGPMinchoE", "Regular"],
    ["HGPGothicE", "Regular"],
    ["Noto Serif JP Black", "Regular"],
    ["HGSGyoshotai", "Medium"],
    ["Yu Gothic UI", "Bold"],
    ["Noto Sans JP Light", "Regular"],
    ["HGPSoeiPresenceEB", "Extra-Bold"],
    ["Train One", "Regular"],
    ["Rampart One", "Regular"],
    ["Dela Gothic One", "Regular"],
    ["Reggae One", "Regular"],
    ["HGSSoeiPresenceEB", "Extra-Bold"],
    ["HGPSoeiKakugothicUB", "Regular"],
    ["HGPGyoshotai", "Medium"],
    ["HGSeikaishotaiPRO", "Regular"],
    ["HGSKyokashotai", "Medium"],
    ["Noto Serif JP Bold", "Regular"],
    ["Noto Sans JP", "Regular"],
    ["DotGothic16", "Regular"],
    ["MS Gothic", "Regular"],
]

FUSION_TITLE = "Text+"     # Effects > Titles にある Fusion Title の名前
PROBE_TIMELINE = "__probe__"
ELEMENTS = (1, 2, 3, 4, 5, 6)

# 測るときの画面の大きさ。字幕を出すのと同じ縦画面でなければならない。
# 開いているプロジェクトが横画面（1920x1080）のこともあるので、測定用の
# タイムラインだけ自前の設定に切り替えてここへ合わせる。プロジェクトには触らない。
# 横で測った値をそのまま縦で使うと、Size が画面の幅と高さのどちらを基準に
# しているか次第で1.8倍ずれる。
FRAME = (1080, 1920)

# 自分自身の在り処。Console に貼ると __file__ が無いので PROJECT から組み立てる。
HERE = "Resolveで動かす"
NAME = "道具_Text+の実寸と書体の字幅を測ってサンプルデータを変更する.py"

# Input を書き出すツール。Text+ に無い値がどこに在るのかを毎回控えておく。
REGS = ["TextPlus", "Background", "RectangleMask", "EllipseMask", "Merge", "Transform"]
SHADING = (1, 2, 3, 4, 5, 6, 7, 8)     # 装飾の層は8つ

# 書いて読み返す確かめ。(ツール, Input名, 書く値, 覚え書き)
# 「入るはず」も「無いはず」も両方入れておく。無いものが在るようになったら
# それも変化なので、毎回ここで分かるようにしておく。
WRITE_CHECKS = [
    ("TextPlus", "Size", 0.07, "文字の大きさ"),
    ("TextPlus", "CharacterSpacing", 1.2, "字送り"),
    ("TextPlus", "AngleZ", 12.5, "文字全体の回転"),
    ("TextPlus", "Angle", 12.5, "Text+ には無いはず（回転は AngleZ）"),
    ("TextPlus", "Type1", 2, "塗りをグラデーションにする"),
    ("TextPlus", "ShadingGradient1", "@gradient", "グラデーションの中身"),
    ("TextPlus", "ShadingMappingAngle1", 30.0, "グラデーションの角度"),
    ("TextPlus", "AngleZ2", 4.0, "縁だけ回す"),
    ("TextPlus", "SizeX2", 1.06, "縁だけ広げる"),
    ("TextPlus", "Offset2", [0.004, -0.002], "縁だけずらす（Point）"),
    ("TextPlus", "ElementShape7", 3, "帯の縁"),
    ("TextPlus", "Thickness7", 0.02, "帯の縁の太さ"),
    ("TextPlus", "MergeOperator1", 1, "無いはず"),
    ("TextPlus", "Extrusion1", 0.1, "無いはず"),
    ("TextPlus", "ElementPosition1", 1, "無いはず"),
    ("Background", "Type", "Solid", "文字列で渡す（FuID）"),
    ("Background", "Type", "Horizontal", "文字列で渡す（FuID）"),
    ("Background", "Type", 1, "数値では入らないはず"),
    ("Background", "GradientType", "Radial", "文字列で渡す（FuID）"),
    ("Merge", "Angle", 15.0, "Merge には在る"),
    ("RectangleMask", "Angle", 15.0, "RectangleMask には在る"),
    ("Transform", "Angle", 15.0, "Transform には在る"),
]

# 上の "@gradient" に入れる中身。位置0.0が下。
GRADIENT = {0.0: {1: 0.72, 2: 0.53, 3: 0.17, 4: 1.0},
            0.5: {1: 1.00, 2: 0.96, 3: 0.81, 4: 1.0},
            1.0: {1: 0.79, 2: 0.57, 3: 0.18, 4: 1.0}}

# --- 換算を測る側 ---
LOOK_TEXT = "■"    # 塗りつぶしの四角。輪郭が直線なので測りやすい
LOOK_FONT = "Noto Sans JP"
LOOK_STYLE = "Bold"
S = 0.15     # 基準サイズ。小さく測ると縁の太さが数pxしか無く、
             # 1px の丸めがそのまま1割の誤差になる（当て馬で確認）
T = 0.06     # 基準の縁の太さ
SOFT = 5.0   # 基準のぼかし量

# --- 送り幅を測る側 ---
GLYPH = "■"
CHARS = 6      # 2行目に並べる文字数
WS = 0.05      # 基準サイズ。Size が画面の幅と高さのどちらを基準にしているかが
               # 未確定なので、高さ基準でも2行目がはみ出さない値にしてある

LOOK_OFF = {
    "Font": LOOK_FONT, "Style": LOOK_STYLE, "Size": S,
    "CharacterSpacing": 1.0, "LineSpacing": 1.0,
    "Wrap": 0, "VerticalTopCenterBottom": 1,
    "VerticalJustificationNew": 3, "HorizontalJustificationNew": 3,
    "Center": [0.5, 0.5],
    "Enabled1": 0, "Enabled2": 0, "Enabled3": 0,
    "Enabled4": 0, "Enabled5": 0, "Enabled6": 0,
}

WIDTH_OFF = {
    "Size": WS, "CharacterSpacing": 1.0, "LineSpacing": 1.6,
    "Wrap": 0, "VerticalTopCenterBottom": 1,
    "VerticalJustificationNew": 3, "HorizontalJustificationNew": 3,
    "Center": [0.5, 0.5], "Direction": 0, "LineDirection": 0,
    "Enabled1": 1, "ElementShape1": 0, "Type1": 0,
    "Red1": 1.0, "Green1": 1.0, "Blue1": 1.0, "Alpha1": 1.0,
    "Opacity1": 1.0, "Softness1": 1, "SoftnessX1": 0.0, "SoftnessY1": 0.0,
    "Enabled2": 0, "Enabled3": 0, "Enabled4": 0, "Enabled5": 0, "Enabled6": 0,
}

WHITE = {"Red": 1.0, "Green": 1.0, "Blue": 1.0, "Alpha": 1.0}
BLACK = {"Red": 0.0, "Green": 0.0, "Blue": 0.0, "Alpha": 1.0}


def color(index, rgba):
    """色の4成分を要素番号付きのキーに直す。"""
    return dict(("%s%d" % (key, index), value) for key, value in rgba.items())


def fill(index, rgba, softness=0.0):
    """塗り（Text Fill）の要素を作る。"""
    out = {
        "Enabled%d" % index: 1, "ElementShape%d" % index: 0,
        "Softness%d" % index: 1, "Opacity%d" % index: 1.0,
        "SoftnessX%d" % index: softness, "SoftnessY%d" % index: softness,
        "SoftnessGlow%d" % index: 0.0,
    }
    out.update(color(index, rgba))
    return out


def outline(index, rgba, thickness):
    """縁（Text Outline）の要素を作る。"""
    out = {
        "Enabled%d" % index: 1, "ElementShape%d" % index: 1,
        "Thickness%d" % index: thickness, "JoinStyle%d" % index: 0,
        "OutsideOnly%d" % index: 1, "Softness%d" % index: 1,
        "SoftnessX%d" % index: 0.0, "SoftnessY%d" % index: 0.0,
        "SoftnessGlow%d" % index: 0.0, "Opacity%d" % index: 1.0,
    }
    out.update(color(index, rgba))
    return out


def band(index, rgba, extend_h, extend_v, round_amount):
    """帯（Border Fill）の要素を作る。"""
    out = {
        "Enabled%d" % index: 1, "ElementShape%d" % index: 2, "Level%d" % index: 0,
        "ExtendHorizontal%d" % index: extend_h, "ExtendVertical%d" % index: extend_v,
        "Round%d" % index: round_amount, "Opacity%d" % index: 1.0,
        "Softness%d" % index: 1, "Shear%d" % index: 1, "ShearX%d" % index: 0.0,
    }
    out.update(color(index, rgba))
    return out


def look_cases():
    """換算を測るcase。1caseにつき画像を1枚。"""
    rows = [
        ("glyph", {"Size": S}, fill(1, WHITE)),
        ("glyph_big", {"Size": S * 2}, fill(1, WHITE)),
        ("edge", {}, dict(fill(1, BLACK), **outline(2, WHITE, T))),
        ("edge_thick", {}, dict(fill(1, BLACK), **outline(2, WHITE, T * 2))),
        # ぼかしは塗りに掛けて測る。細い縁をぼかすと薄くなりすぎて拾えない
        ("soft0", {}, fill(1, WHITE, softness=0.0)),
        ("soft5", {}, fill(1, WHITE, softness=SOFT)),
        ("band", {}, dict(fill(1, BLACK), **band(6, WHITE, 0.30, 0.30, 0.0))),
        ("band_round", {}, dict(fill(1, BLACK), **band(6, WHITE, 0.30, 0.30, 1.0))),
    ]
    cases = []
    for number, (name, base, elements) in enumerate(rows, start=1):
        preset = dict(LOOK_OFF)
        preset.update(base)
        preset.update(elements)
        cases.append({"name": name, "preset": preset, "text": LOOK_TEXT,
                      "file": "probe_%d_%s.png" % (number, name)})
    return cases


def width_cases():
    """送り幅を測るcase。1枚に2行を書き、横幅の差から送り幅を出す。"""
    text = GLYPH + "\n" + GLYPH * CHARS
    cases = []
    for number, pair in enumerate(FACES, start=1):
        preset = dict(WIDTH_OFF)
        preset["Font"] = pair[0]
        preset["Style"] = pair[1]
        cases.append({"name": "face", "font": pair[0], "style": pair[1],
                      "size": WS, "tracking": 1.0, "chars": CHARS,
                      "preset": preset, "text": text,
                      "file": "width_%03d.png" % number})
    if not FACES:
        return cases

    # 確かめ用。字送りと大きさが、素直に比例するかどうかを見る。
    for name, extra in (("tracking", {"CharacterSpacing": 1.3}),
                        ("double", {"Size": WS * 2})):
        preset = dict(WIDTH_OFF)
        preset["Font"] = FACES[0][0]
        preset["Style"] = FACES[0][1]
        preset.update(extra)
        cases.append({"name": name, "font": FACES[0][0], "style": FACES[0][1],
                      "size": preset["Size"], "tracking": preset["CharacterSpacing"],
                      "chars": CHARS, "preset": preset, "text": text,
                      "file": "check_%s.png" % name})
    return cases


def get_resolve_obj():
    """Resolve内部実行時に用意されているResolveオブジェクトを取得する。"""
    g = globals()
    if "resolve" in g and g["resolve"] is not None:
        return g["resolve"]
    if "app" in g and g["app"] is not None:
        return g["app"].GetResolve()
    return None


def set_input(tool, key, value):
    """Point（[x, y]）はFusionのtable形式に直してから渡す。"""
    if isinstance(value, (list, tuple)):
        tool.SetInput(key, {1: value[0], 2: value[1]})
    else:
        tool.SetInput(key, value)


def frames_to_tc(frame, fps):
    """フレーム番号をタイムコードに直す。"""
    rate = int(round(fps))
    total = int(frame)
    return "%02d:%02d:%02d:%02d" % (total // (3600 * rate),
                                    total // (60 * rate) % 60,
                                    total // rate % 60,
                                    total % rate)


def tc_to_frames(timecode, fps):
    """タイムコードをフレーム番号に直す。"""
    parts = [int(x) for x in timecode.replace(";", ":").split(":")]
    rate = int(round(fps))
    return ((parts[0] * 60 + parts[1]) * 60 + parts[2]) * rate + parts[3]


def move_playhead(timeline, frame, fps):
    """再生ヘッドを動かす。着いたかどうかを返す。

    SetCurrentTimecode は既にその位置に居ると False を返す。返り値で判定すると、
    先頭から並べ始める処理が1件目で必ず止まる。読み返した位置で判定する。
    """
    timeline.SetCurrentTimecode(frames_to_tc(frame, fps))
    now = timeline.GetCurrentTimecode()
    return now is not None and tc_to_frames(now, fps) == int(frame)


def find_text_tool(comp):
    """Fusionコンポジションから TextPlus ツールを探す。"""
    for tool in (comp.GetToolList() or {}).values():
        if tool.GetAttrs().get("TOOLS_RegID") == "TextPlus":
            return tool
    return None


def apply_preset(comp, tool, preset, text):
    """1件分の値を書く。書けなかったInput名を返す。

    Text+ は要素を有効にするまでその要素のパラメータを持たない。
    先に全要素を点けてパラメータを出し、値を書いてから、本来のOn/Offへ戻す。

    在るかどうかは GetInputList では見ない。Lock 中は一覧が古いままで、
    書けている帯の値まで「無い」と言う（実機で確認）。書いた直後に
    読み返して None かどうかで見る。
    """
    enables = ["Enabled%d" % index for index in ELEMENTS]
    comp.Lock()
    tool.SetInput("StyledText", text)
    for key in enables:
        tool.SetInput(key, 1)
    for key, value in preset.items():
        if key not in enables:
            set_input(tool, key, value)
    bad = [key for key in preset if key not in enables and tool.GetInput(key) is None]
    for key in enables:
        tool.SetInput(key, preset.get(key, 0))
    comp.Unlock()
    return bad


def record_folder():
    """記録の置き場。Console からcopyしなくて済むよう、ここへ全部書く。"""
    folder = os.path.join(PROJECT, "doc", "測定")
    for path in (folder, os.path.join(folder, "画像")):
        if not os.path.isdir(path):
            os.makedirs(path)
    return folder


def put(folder, name, lines):
    """記録を1つ書く。"""
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def short(value):
    """読み返した値を、記録に収まる長さの文字にする。"""
    text = repr(value)
    if len(text) > 70:
        text = text[:67] + "..."
    return text


def input_rows(tool):
    """このツールが持つ Input を (名前, 型, いまの値) で全部返す。

    一覧は comp.Lock() の間は古いままなので、必ず Unlock してから呼ぶこと。
    """
    rows = []
    for inp in (tool.GetInputList() or {}).values():
        attrs = inp.GetAttrs() or {}
        name = attrs.get("INPS_ID")
        if not name:
            continue
        rows.append((name, attrs.get("INPS_DataType"), tool.GetInput(name)))
    rows.sort()
    return rows


def split_tail(name):
    """末尾の数字を切り離す。Thickness2 なら ("Thickness", "2")。"""
    cut = len(name)
    while cut > 0 and name[cut - 1].isdigit():
        cut -= 1
    return name[:cut], name[cut:]


def survey_elements(rows):
    """要素1〜8がそれぞれ何を持っているかに分ける。"""
    by_element, plain = {}, []
    for name, kind, value in rows:
        base, tail = split_tail(name)
        if tail.isdigit() and int(tail) in SHADING:
            by_element.setdefault(int(tail), {})[base] = (kind, value)
        else:
            plain.append((name, kind, value))
    return by_element, plain


def check_writes(comp, tools):
    """値を書いて読み返す。(ツール, Input名, 書いた値, 読めた値, 判定, 覚え書き)。"""
    out = []
    for reg, key, value, note in WRITE_CHECKS:
        tool = tools.get(reg)
        if tool is None:
            out.append((reg, key, value, None, "ツールが無い", note))
            continue
        if value == "@gradient":
            value = GRADIENT
        before = tool.GetInput(key)
        set_input(tool, key, value)
        got = tool.GetInput(key)
        if before is None and got is None:
            verdict = "Input が無い"
        elif got is None:
            verdict = "捨てられた"
        elif key.startswith("ShadingGradient"):
            # 読み返しが PyRemoteObject で、書いた値と比べようがない
            verdict = "入った（中身は照合できない）"
        elif same(value, got):
            verdict = "入った"
        else:
            verdict = "違う値になった"
        out.append((reg, key, value, got, verdict, note))
    return out


def same(want, got):
    """書いた値と読み返した値が同じか。Point は table で返ってくる。"""
    if isinstance(want, (list, tuple)):
        pair = got
        if isinstance(got, dict):
            keys = sorted(got.keys())
            pair = [got[keys[0]], got[keys[1]]] if len(keys) >= 2 else None
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            return False
        return all(abs(float(a) - float(b)) <= 1e-3 for a, b in zip(want, pair))
    if isinstance(want, str):
        return str(got) == want
    try:
        return abs(float(got) - float(want)) <= 1e-3
    except (TypeError, ValueError):
        return False


def survey(project, media_pool, folder):
    """Input を全部書き出し、書き込みの可否も確かめる。記録を返す。"""
    keep = project.GetCurrentTimeline()
    probe = media_pool.CreateEmptyTimeline(PROBE_TIMELINE)
    if probe is None:
        return None, "調べる用のタイムラインを作れません。%s が残っていませんか。" % PROBE_TIMELINE
    project.SetCurrentTimeline(probe)
    item = probe.InsertFusionTitleIntoTimeline(FUSION_TITLE)
    if item is None:
        return None, "Fusion Title %r を入れられません。" % FUSION_TITLE
    comp = item.GetFusionCompByIndex(1)
    text_tool = find_text_tool(comp) if comp else None
    if text_tool is None:
        return None, "Text+ が見つかりません。"

    # 要素は有効にするまでパラメータを持たない。一覧を取る前に Unlock しておく
    comp.Lock()
    for number in SHADING:
        text_tool.SetInput("Enabled%d" % number, 1)
    comp.Unlock()

    tools = {"TextPlus": text_tool}
    dump = {}
    for reg in REGS:
        tool = text_tool if reg == "TextPlus" else comp.AddTool(reg)
        if tool is None:
            dump[reg] = []
            continue
        tools[reg] = tool
        dump[reg] = input_rows(tool)

    checks = check_writes(comp, tools)

    lines = ["# Text+ ほかの Input を全部並べたもの",
             "# 名前 / 型 / いまの値", ""]
    for reg in REGS:
        rows = dump.get(reg) or []
        lines.append("== %s ==  %d個" % (reg, len(rows)))
        for name, kind, value in rows:
            lines.append("   %-30s %-12s %s" % (name, kind, short(value)))
        lines.append("")
    put(folder, "Input一覧.txt", lines)

    by_element, plain = survey_elements(dump.get("TextPlus") or [])
    lines = ["# 装飾の層（要素）が持っているもの", ""]
    lines.append("要素の数: %d / 要素に属さない Input: %d個" % (len(by_element), len(plain)))
    lines.append("")
    first = by_element.get(1, {})
    lines.append("== 要素1 が持つもの（%d個） ==" % len(first))
    for base in sorted(first):
        lines.append("   %-30s %-12s %s" % (base, first[base][0], short(first[base][1])))
    lines.append("")
    lines.append("== 要素1 との違い ==")
    for number in sorted(by_element):
        if number == 1:
            continue
        here = set(by_element[number])
        only_here = sorted(here - set(first))
        only_first = sorted(set(first) - here)
        lines.append("   要素%d: %d個 / 増えたもの %s / 無いもの %s"
                     % (number, len(here),
                        " ".join(only_here) or "なし", " ".join(only_first) or "なし"))
    put(folder, "要素の中身.txt", lines)

    lines = ["# 値を書いて読み返した結果", "", "%-14s %-22s %-10s %s"
             % ("ツール", "Input名", "判定", "書いた値 → 読めた値")]
    for reg, key, wrote, got, verdict, note in checks:
        lines.append("%-14s %-22s %-10s %s → %s   （%s）"
                     % (reg, key, verdict, short(wrote), short(got), note))
    put(folder, "書き込み結果.txt", lines)

    if keep is not None:
        project.SetCurrentTimeline(keep)
        media_pool.DeleteTimelines([probe])

    return {"inputs": dict((reg, [[n, k, short(v)] for n, k, v in rows])
                           for reg, rows in dump.items()),
            "elements": dict((str(number), sorted(names))
                             for number, names in by_element.items()),
            "checks": [[reg, key, short(wrote), short(got), verdict, note]
                       for reg, key, wrote, got, verdict, note in checks]}, None


def force_frame(timeline):
    """測定用タイムラインだけを縦画面に切り替える。できなければ理由を返す。

    プロジェクトの設定には触らない。開いているプロジェクトが横画面でも、
    このタイムラインだけ自前の設定を持たせて FRAME に合わせる。
    切り替わったかどうかは読み返して確かめる（黙って横で測ると、
    出来上がる値が全部ずれる）。
    """
    timeline.SetSetting("useCustomSettings", "1")
    timeline.SetSetting("timelineResolutionWidth", str(FRAME[0]))
    timeline.SetSetting("timelineResolutionHeight", str(FRAME[1]))
    got = (int(timeline.GetSetting("timelineResolutionWidth") or 0),
           int(timeline.GetSetting("timelineResolutionHeight") or 0))
    if got != FRAME:
        return ("測定用タイムラインを %dx%d にできません（いまは %dx%d）。"
                "プロジェクトの解像度を %dx%d にしてから、もう一度貼ってください。"
                % (FRAME[0], FRAME[1], got[0], got[1], FRAME[0], FRAME[1]))
    return None


def shoot(project, media_pool, cases, folder):
    """caseを並べて値を書き、1枚ずつ静止画に書き出す。"""
    keep = project.GetCurrentTimeline()
    probe = media_pool.CreateEmptyTimeline(PROBE_TIMELINE)
    if probe is None:
        return "測定用タイムラインを作れません。%s が残っていませんか。" % PROBE_TIMELINE
    project.SetCurrentTimeline(probe)

    trouble = force_frame(probe)
    if trouble:
        return trouble

    fps = float(project.GetSetting("timelineFrameRate") or 30)
    at = probe.GetStartFrame()
    placed = []
    for case in cases:
        if not move_playhead(probe, at, fps):
            return "再生ヘッドを動かせません。"
        item = probe.InsertFusionTitleIntoTimeline(FUSION_TITLE)
        if item is None:
            return "Fusion Title %r を入れられません。" % FUSION_TITLE
        placed.append((item, case))
        at = int(item.GetEnd())

    missing = set()
    for item, case in placed:
        comp = item.GetFusionCompByIndex(1)
        if comp is None:
            return "%s の Fusion を開けません。" % case["name"]
        tool = find_text_tool(comp)
        if tool is None:
            return "%s の Text+ が見つかりません。" % case["name"]
        missing.update(apply_preset(comp, tool, case["preset"], case["text"]))
    if missing:
        return "書き込めなかったInput名: %s" % ", ".join(sorted(missing))

    failed = []
    for item, case in placed:
        middle = (int(item.GetStart()) + int(item.GetEnd())) // 2
        probe.SetCurrentTimecode(frames_to_tc(middle, fps))
        if not project.ExportCurrentFrameAsStill(os.path.join(folder, case["file"])):
            failed.append(case["file"])

    if keep is not None:
        project.SetCurrentTimeline(keep)  # 現在のタイムラインは消せない
        media_pool.DeleteTimelines([probe])
    else:
        print("元のタイムラインが無いので %s は残します。手で消してください。" % PROBE_TIMELINE)

    if failed:
        return "書き出せなかった画像: %s" % ", ".join(failed)
    return None


def write_look_sidecar(folder, cases, width, height):
    """換算側が読む一覧を書く。"""
    with open(os.path.join(folder, "cases.txt"), "w", encoding="utf-8") as handle:
        handle.write("# frame\t%d\t%d\n" % (width, height))
        handle.write("# size_base\t%.6f\n" % S)
        handle.write("# thickness_base\t%.6f\n" % T)
        handle.write("# softness_base\t%.6f\n" % SOFT)
        for case in cases:
            handle.write("%s\t%s\t%.6f\n"
                         % (case["name"], case["file"], case["preset"]["Size"]))


def write_width_sidecar(folder, cases, width, height):
    """送り幅側が読む一覧を書く。"""
    with open(os.path.join(folder, "cases.txt"), "w", encoding="utf-8") as handle:
        handle.write("# frame\t%d\t%d\n" % (width, height))
        handle.write("# glyph\t%s\n" % GLYPH)
        for case in cases:
            handle.write("%s\t%s\t%s\t%s\t%.6f\t%.6f\t%d\n"
                         % (case["name"], case["file"], case["font"], case["style"],
                            case["size"], case["tracking"], case["chars"]))


def run_local(args):
    """手元の python を呼ぶ。出力をそのまま返す。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    done = subprocess.run([PYTHON] + args, cwd=PROJECT, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return done.returncode, done.stdout.decode("utf-8", "replace")


# ==========================================================================
# ここから下は「測る側」。手元の python が --measure 付きで呼ぶときだけ動く。
# Resolve の中の python には Pillow と numpy が無いので、画像を読むのは
# こちら側の役目。同じファイルに入れてあるのは、測る道具を1つに保つため。
# ==========================================================================

INK = 128        # これ以上の明るさを「描かれている」とみなす（0-255）
FAINT = 26       # ぼかしの裾を拾うしきい値（10%）
# 段差をσでぼかすと、10%まで落ちる位置は約1.27σ外側。裾の広がりからσに戻す係数。
FAINT_TO_SIGMA = 1.27


def pixels():
    """画像を読む道具。無ければここで止める。"""
    try:
        import numpy
        from PIL import Image
    except ImportError:
        raise SystemExit("Pillow と numpy が要ります: pip install pillow numpy")
    return numpy, Image


def look_read_cases(folder):
    """換算側の cases.txt を読む。"""
    path = os.path.join(folder, "cases.txt")
    if not os.path.isfile(path):
        raise SystemExit("cases.txt がありません: %s" % path)
    frame = size_base = thickness_base = softness_base = None
    cases = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if parts[0] == "# frame":
                frame = (int(parts[1]), int(parts[2]))
            elif parts[0] == "# size_base":
                size_base = float(parts[1])
            elif parts[0] == "# thickness_base":
                thickness_base = float(parts[1])
            elif parts[0] == "# softness_base":
                softness_base = float(parts[1])
            elif not parts[0].startswith("#") and len(parts) == 3:
                cases.append({"name": parts[0], "file": parts[1], "size": float(parts[2])})
    if frame is None or not cases:
        raise SystemExit("cases.txt を読めません。")
    return frame, size_base, thickness_base, softness_base or 5.0, cases


def box_of(numpy, mask):
    """真の画素を囲む矩形を (左, 上, 幅, 高さ) で返す。無ければ None。"""
    rows = numpy.where(mask.any(axis=1))[0]
    cols = numpy.where(mask.any(axis=0))[0]
    if not len(rows) or not len(cols):
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1)


def hole_of(numpy, mask, box):
    """外周の内側にある「描かれていない」矩形を返す（縁の内側を測る）。"""
    left, top, width, height = box
    inner = ~mask[top:top + height, left:left + width]
    # 外周に接している未描画部分は背景なので、中央行・中央列から測る
    xs = numpy.where(inner[height // 2])[0]
    ys = numpy.where(inner[:, width // 2])[0]
    if not len(xs) or not len(ys):
        return None
    return int(xs[0]), int(ys[0]), int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1)


def radius_from_area(numpy, square_area, round_area):
    """角丸なしとありの面積差から半径を出す。

    角を半径rで丸めると、4隅で合わせて (4 - pi) * r^2 だけ面積が減る。
    輪郭を1本たどるより、面積のほうがラスタライズのゆらぎに強い。
    """
    lost = square_area - round_area
    if lost <= 0:
        return 0.0
    return float(numpy.sqrt(lost / (4.0 - numpy.pi)))


def look_measure(folder):
    """換算用の画像から寸法を測る。"""
    numpy, Image = pixels()
    frame, size_base, thickness_base, softness_base, cases = look_read_cases(folder)
    found = {}
    width = height = None
    for case in cases:
        path = os.path.join(folder, case["file"])
        if not os.path.isfile(path):
            raise SystemExit("%s がありません: %s" % (case["file"], folder))
        gray = numpy.asarray(Image.open(path).convert("L"), dtype=numpy.int16)
        height, width = gray.shape
        if (width, height) != frame:
            # 測るはずだった大きさで撮れていない。黙って画像の側で計算すると、
            # 縦画面のつもりで横画面の値が入る。止める。
            raise SystemExit("%s は %dx%d で、測るはずだった %dx%d と違います。"
                             % (case["file"], width, height, frame[0], frame[1]))
        ink = gray >= INK
        row = {"size": case["size"], "ink": box_of(numpy, ink),
               "faint": box_of(numpy, gray >= FAINT), "hole": None, "area": 0}
        if row["ink"] is not None:
            row["hole"] = hole_of(numpy, ink, row["ink"])
            left, top, wide, high = row["ink"]
            row["area"] = int(ink[top:top + high, left:left + wide].sum())
        found[case["name"]] = row
    return numpy, width, size_base, thickness_base, softness_base, found


def need(found, name, key="ink"):
    """測れなかったcaseがあれば止める。ぼかしたcaseは薄い側で測る。"""
    case = found.get(name)
    if case is None or case[key] is None:
        raise SystemExit("case %r を画像から見つけられません。" % name)
    return case


def look_factors(numpy, width, size_base, thickness_base, softness_base, found):
    """測った寸法から、プレビューの換算係数を出す。"""
    glyph = need(found, "glyph")
    big = need(found, "glyph_big")
    edge = need(found, "edge")
    thick = need(found, "edge_thick")
    soft0 = need(found, "soft0", "faint")
    soft5 = need(found, "soft5", "faint")
    plate = need(found, "band")
    round_plate = need(found, "band_round")

    lines = []
    glyph_h = glyph["ink"][3]
    lines.append("文字の高さ: Size %.3f -> %dpx / Size %.3f -> %dpx（比 %.2f 倍、値の比は %.2f 倍）"
                 % (glyph["size"], glyph_h, big["size"], big["ink"][3],
                    big["ink"][3] / float(glyph_h), big["size"] / glyph["size"]))

    # すべて「文字の実寸（■の塗りの高さ）」を基準にする
    size_to_px = glyph_h / (size_base * width)

    if not edge["hole"] or not thick["hole"]:
        raise SystemExit("縁の内側を測れません。画像を確かめてください。")
    edge_px = (edge["ink"][3] - edge["hole"][3]) / 2.0
    thick_px = (thick["ink"][3] - thick["hole"][3]) / 2.0
    lines.append("縁の太さ: Thickness %.3f -> %.1fpx / %.3f -> %.1fpx（比 %.2f 倍）"
                 % (thickness_base, edge_px, thickness_base * 2, thick_px,
                    thick_px / edge_px if edge_px else 0.0))
    thick_to_px = edge_px / (thickness_base * glyph_h)

    spread = (soft5["faint"][3] - soft0["faint"][3]) / 2.0
    sigma = spread / FAINT_TO_SIGMA
    lines.append("ぼかし: Softness 0 -> %dpx / Softness %.1f -> %dpx（裾が片側 %.1fpx = σ %.1fpx）"
                 % (soft0["faint"][3], softness_base, soft5["faint"][3], spread, sigma))
    soft_to_px = sigma / (softness_base * glyph_h)

    extend_x = (plate["ink"][2] - glyph["ink"][2]) / 2.0
    extend_y = (plate["ink"][3] - glyph["ink"][3]) / 2.0
    lines.append("帯の余白: ExtendH 0.300 -> 片側 %.1fpx / ExtendV 0.300 -> 片側 %.1fpx"
                 % (extend_x, extend_y))

    radius = radius_from_area(numpy, plate["area"], round_plate["area"])
    lines.append("帯の角丸: Round 1.000 -> 半径 %.1fpx（帯の高さの %.2f 倍）"
                 % (radius, radius / plate["ink"][3] if plate["ink"][3] else 0.0))

    return lines, {
        "measured": 1,
        "sizeToPx": size_to_px,
        "thickToPx": thick_to_px,
        "softToPx": soft_to_px,
        "extendXToPx": extend_x / (0.30 * glyph_h),
        "extendYToPx": extend_y / (0.30 * glyph_h),
        "roundToPx": radius / (1.0 * glyph_h) if radius else 0.0,
        "offsetToW": 1.0,
    }


def width_read_cases(folder):
    """送り幅側の cases.txt を読む。"""
    path = os.path.join(folder, "cases.txt")
    if not os.path.isfile(path):
        raise SystemExit("cases.txt がありません: %s" % path)
    frame, cases = None, []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if parts[0] == "# frame":
                frame = (int(parts[1]), int(parts[2]))
            elif not parts[0].startswith("#") and len(parts) == 7:
                cases.append({"name": parts[0], "file": parts[1],
                              "font": parts[2], "style": parts[3],
                              "size": float(parts[4]), "tracking": float(parts[5]),
                              "chars": int(parts[6])})
    if frame is None or not cases:
        raise SystemExit("cases.txt を読めません。")
    return frame, cases


def rows_of(mask):
    """描かれている行のまとまりを、上から順に (上, 下) で返す。"""
    hit = mask.any(axis=1)
    bands, start = [], None
    for index, on in enumerate(hit):
        if on and start is None:
            start = index
        elif not on and start is not None:
            bands.append((start, index - 1))
            start = None
    if start is not None:
        bands.append((start, len(hit) - 1))
    return bands


def band_box(numpy, mask, band):
    """行のまとまりの中で、描かれている画素を囲む矩形を (左, 幅, 高さ) で返す。"""
    top, bottom = band
    cols = numpy.where(mask[top:bottom + 1].any(axis=0))[0]
    if not len(cols):
        return None
    return int(cols[0]), int(cols[-1] - cols[0] + 1), int(bottom - top + 1)


def width_measure_one(numpy, Image, path, case, frame):
    """1枚から、1文字の幅・高さと、送り幅を測る。"""
    gray = numpy.asarray(Image.open(path).convert("L"), dtype=numpy.int16)
    height, width = gray.shape
    if (width, height) != frame:
        raise SystemExit("%s は %dx%d で、測るはずだった %dx%d と違います。"
                         % (case["file"], width, height, frame[0], frame[1]))
    mask = gray >= INK
    bands = rows_of(mask)
    if len(bands) != 2:
        raise SystemExit("%s は行が %d本です（2本のはず）。行間が足りないか、"
                         "文字が画面からはみ出しています。" % (case["file"], len(bands)))
    first = band_box(numpy, mask, bands[0])
    second = band_box(numpy, mask, bands[1])
    if first is None or second is None:
        raise SystemExit("%s の文字を測れません。" % case["file"])
    one_left, one_width, one_height = first
    many_left, many_width, _ = second
    if many_left <= 1 or many_left + many_width >= width - 1:
        raise SystemExit("%s は2行目が画面の端に接しています。測れません。" % case["file"])
    return {"one_width": one_width, "one_height": one_height,
            "advance": (many_width - one_width) / float(case["chars"] - 1)}


def width_measure(folder):
    """送り幅用の画像を測る。"""
    numpy, Image = pixels()
    frame, cases = width_read_cases(folder)
    out = []
    for case in cases:
        path = os.path.join(folder, case["file"])
        if not os.path.isfile(path):
            raise SystemExit("%s がありません: %s" % (case["file"], folder))
        row = dict(case)
        row.update(width_measure_one(numpy, Image, path, case, frame))
        out.append(row)
    return frame, out


def per_size(row, frame_width):
    """Size 1・画面幅1 あたりの値に直す。

    字送り（CharacterSpacing）は送り幅を掛けない。1.0 との差を、
    「Size 1・画面幅1」そのままの量で**足す**（実測で確認）。
    なので素の送り幅へ戻すには、掛けた分を割るのではなく足した分を引く。
    """
    unit = row["size"] * frame_width
    return (row["advance"] / unit - (row["tracking"] - 1.0),
            row["one_width"] / unit,
            row["one_height"] / unit)


def width_report(frame, rows):
    """測った値を並べて、Size が何を決めているのかを見る。"""
    width, height = frame
    faces = [row for row in rows if row["name"] == "face"]
    if not faces:
        raise SystemExit("書体のcaseがありません。")

    table, lines = {}, []
    for row in faces:
        advance, one_width, one_height = per_size(row, width)
        table["%s|%s" % (row["font"], row["style"])] = (advance, one_width, one_height)
        lines.append("  %-34s 送り %.4f / 字幅 %.4f / 字高 %.4f"
                     % (row["font"] + " " + row["style"], advance, one_width, one_height))

    advances = [value[0] for value in table.values()]
    heights = [value[2] for value in table.values()]

    def spread(values):
        return (max(values) - min(values)) / (sum(values) / len(values))

    notes = ["書体ごとのばらつき: 送り幅 %.1f%% / 字の高さ %.1f%%"
             % (spread(advances) * 100, spread(heights) * 100)]
    # どちらかが「ほぼ揃っている」ときだけ言い切る。両方ばらけているなら、
    # Size が何を決めているのかはこの測り方では決まらない。幅の判定には
    # 書体ごとの値をそのまま使うので、決まらなくても困らない。
    flat = 0.03
    ref_px = sum(advances) / len(advances) * width
    if spread(advances) < flat <= spread(heights):
        notes.append("送り幅が書体によらず揃っている → Size は「文字の大きさ（em）」を決めている。")
        notes.append("  Size 1 あたり %.1fpx。画面の幅は %d、高さは %d。基準は %s。"
                     % (ref_px, width, height,
                        "幅" if abs(ref_px - width) < abs(ref_px - height) else "高さ"))
    elif spread(heights) < flat <= spread(advances):
        notes.append("字の高さが書体によらず揃っている → Size は「文字の実寸（塗りの高さ）」を決めている。")
    else:
        notes.append("送り幅も字の高さも書体でばらついている。"
                     "Size が何を決めているかはここでは決まらないが、"
                     "幅の判定は書体ごとの実測値をそのまま使うので支障は無い。")

    for row in rows:
        base = table.get("%s|%s" % (row["font"], row["style"]))
        if base is None:
            continue
        if row["name"] == "tracking":
            added = row["advance"] / (row["size"] * width) - base[0]
            notes.append("字送り%.2fの確かめ: 足された分 %.4f（%.4f のはず、ずれ %.4f）"
                         % (row["tracking"], added, row["tracking"] - 1.0,
                            added - (row["tracking"] - 1.0)))
        if row["name"] == "double":
            got = per_size(row, width)[0]
            notes.append("大きさ2倍の確かめ: 送り幅 %.4f（基準 %.4f、比 %.3f 倍。1.000 なら比例）"
                         % (got, base[0], got / base[0]))
    return table, lines, notes


def swap(text, pattern, value, what):
    """生成側の1ブロックを差し替える。前と同じ中身でも「無い」と言わない。"""
    import re
    new, hits = re.subn(pattern, lambda m: value, text, count=1, flags=re.M)
    if not hits:
        raise SystemExit("%s のブロックを見つけられません。" % what)
    return new


def write_back(preview, table, frame):
    """手元で動かす/道具_装飾プリセットを生成.py へ、測った値を書き戻す。"""
    generator = os.path.join(PROJECT, "手元で動かす", "道具_装飾プリセットを生成.py")
    with open(generator, encoding="utf-8") as handle:
        text = handle.read()

    block = ["PREVIEW = OrderedDict(["]
    for key in ("measured", "sizeToPx", "thickToPx", "softToPx",
                "extendXToPx", "extendYToPx", "roundToPx", "offsetToW"):
        block.append('    ("%s", %s),' % (key, 1 if key == "measured"
                                          else "%.4f" % preview[key]))
    block.append("])")
    text = swap(text, r"^PREVIEW = OrderedDict\(\[[\s\S]*?\n\]\)", "\n".join(block), "PREVIEW")

    block = ["FONT_WIDTH = {"]
    for key in sorted(table):
        block.append('    "%s": (%.4f, %.4f, %.4f),' % ((key,) + tuple(table[key])))
    block.append("}")
    text = swap(text, r"^FONT_WIDTH = \{[\s\S]*?\n\}", "\n".join(block), "FONT_WIDTH")
    text = swap(text, r"^FONT_WIDTH_FRAME = .*$",
                "FONT_WIDTH_FRAME = (%d, %d)" % frame, "FONT_WIDTH_FRAME")

    with open(generator, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def main_measure(look_dir, width_dir):
    """画像を測って生成側へ書き戻し、見本帳まで作り直す。"""
    numpy, width, size_base, thickness_base, softness_base, found = look_measure(look_dir)
    lines, preview = look_factors(numpy, width, size_base, thickness_base,
                                  softness_base, found)
    print("== 換算 ==")
    for line in lines:
        print("  " + line)
    print("")
    for key in ("sizeToPx", "thickToPx", "softToPx",
                "extendXToPx", "extendYToPx", "roundToPx"):
        print("  %-12s %.4f" % (key, preview[key]))

    frame, rows = width_measure(width_dir)
    table, lines, notes = width_report(frame, rows)
    print("")
    print("== 送り幅 ==  %dx%d / 書体 %d件" % (frame[0], frame[1], len(table)))
    for line in lines:
        print(line)
    print("")
    for note in notes:
        print(note)

    write_back(preview, table, frame)
    print("")
    print("== 作り直し ==")
    code, text = run_local([os.path.join("手元で動かす", "道具_装飾プリセットを生成.py")])
    print(text.rstrip())
    if code != 0:
        raise SystemExit("見本帳を作り直せませんでした（終了コード %d）。" % code)


def main():
    resolve = get_resolve_obj()
    if resolve is None:
        print("Resolve の中から実行してください（Workspace > Console > Py3）。")
        return
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("プロジェクトが開かれていません。")
        return
    media_pool = project.GetMediaPool()
    if not os.path.isdir(PROJECT):
        print("記録の置き場が見当たりません: %s" % PROJECT)
        print("手元で 手元で動かす/道具_装飾プリセットを生成.py を実行してから、貼り直してください。")
        return

    folder = record_folder()
    width, height = FRAME
    print("測る画面の大きさ: %dx%d（開いているプロジェクトは %sx%s）"
          % (width, height, project.GetSetting("timelineResolutionWidth"),
             project.GetSetting("timelineResolutionHeight")))

    print("Input を調べています...")
    found, trouble = survey(project, media_pool, folder)
    if trouble:
        print(trouble)
        return
    counts = dict((reg, len(rows)) for reg, rows in found["inputs"].items())
    verdicts = {}
    for row in found["checks"]:
        verdicts[row[4]] = verdicts.get(row[4], 0) + 1
    print("  Text+ の Input %d個 / 要素 %d / 確かめ %d件（%s）"
          % (counts.get("TextPlus", 0), len(found["elements"]), len(found["checks"]),
             " ".join("%s%d" % (name, number) for name, number in sorted(verdicts.items()))))

    shots = os.path.join(folder, "画像")
    look_dir = os.path.join(shots, "換算")
    width_dir = os.path.join(shots, "送り幅")
    for path in (look_dir, width_dir):
        if os.path.isdir(path):
            shutil.rmtree(path)     # 前回の画像が混ざると測り間違える
        os.makedirs(path)

    looks = look_cases()
    print("換算を測る画像を %d枚 書き出します..." % len(looks))
    trouble = shoot(project, media_pool, looks, look_dir)
    if trouble:
        print(trouble)
        return
    write_look_sidecar(look_dir, looks, width, height)

    widths = width_cases()
    print("送り幅を測る画像を %d枚 書き出します..." % len(widths))
    trouble = shoot(project, media_pool, widths, width_dir)
    if trouble:
        print(trouble)
        return
    write_width_sidecar(width_dir, widths, width, height)

    # 画像を読むのは手元の python の役目（Resolve の python には Pillow が無い）。
    # 呼ぶ先はこのファイル自身。測る道具を2つに分けないため。
    print("測っています...")
    code, text = run_local([os.path.join(HERE, NAME), "--measure", look_dir, width_dir])
    found["測った結果"] = text
    put(folder, "換算と送り幅.txt", [text.rstrip()])
    stopped = "測る側が止まりました（終了コード %d）" % code if code else None

    with open(os.path.join(folder, "実測.json"), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(found, handle, ensure_ascii=False, indent=1)

    print("")
    print("記録しました: %s" % folder)
    for name in ("Input一覧.txt", "要素の中身.txt", "書き込み結果.txt",
                 "換算と送り幅.txt", "実測.json"):
        print("   %s" % name)
    if stopped:
        print("")
        print(stopped + "。中身は 換算と送り幅.txt に入っています。")
        return
    print("")
    print("終わりました。装飾プリセットを選ぶ.html を開き直してください。")


# Resolve に貼られたときは調べて測る。手元の python から --measure 付きで
# 呼ばれたときは、書き出された画像を測って生成側へ書き戻す。同じファイル。
if "--measure" in sys.argv:
    spot = sys.argv.index("--measure")
    main_measure(sys.argv[spot + 1], sys.argv[spot + 2])
else:
    main()
