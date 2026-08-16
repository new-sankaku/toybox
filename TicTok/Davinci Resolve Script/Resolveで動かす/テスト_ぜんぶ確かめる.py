# -*- coding: utf-8 -*-
"""
【Resolve の Console に貼る】Workspace > Console > Py3。これ1本で全部確かめます。

    1. この環境で使える API（無料版で止まるものが無いか）
    2. 装飾が書いたとおりに入るか（装飾データ.json の全件）
    3. いま開いているタイムラインの下調べ

**結果はファイルに残る。** Console からcopyする必要は無い。

    doc/テスト結果.txt     人が読む形
    doc/テスト結果.json    機械が読む形。装飾データの版と件数が入っている

**毎回やらなくてよい。** 装飾データ.json の版が変わっていなければ、前回の結果が
そのまま生きている。手元で 手元で動かす/道具_装飾プリセットを生成.py を実行すると、
いまの版が確かめ済みかどうかを教える。

確かめ用に作ったタイムラインは最後に消す。開いているタイムラインには書き込まない。
"""

import json
import os
import tempfile

# 生成側（手元で動かす/道具_装飾プリセットを生成.py）が書き替える。手で直さない。
PROJECT = r"C:\01_work\00_Git\toybox\TicTok\Davinci Resolve Script"
DATA_NAME = "装飾データ.json"

FUSION_TITLE = "Text+"
PROBE_TIMELINE = "__test_probe__"
WANT_FRAMES = 30               # 尺を指定して置けるかを確かめるときに頼む長さ
LONG_FRAMES = 600              # 元の尺より長く置けるかを確かめるときに頼む長さ
TEXT_PLUS_NAME = "Text+"       # 本番が使う Media Pool の Text+ の名前
# 1 にすると、前に通った件も含めて全部やり直す。
FORCE = 0


# ---------------------------------------------------------------- 本体と同じ手順
# ここから下の関数は 実務_字幕を装飾する.py の中身そのもの。
# 手元で動かす/道具_装飾プリセットを生成.py が実行のたびに写す。手で直さない。
# 写しにするのは、確かめる手順と本番の手順がずれないようにするため。
# @COPY@
def get_resolve_obj():
    """Resolve内部実行時に用意されているResolveオブジェクトを取得する。"""
    g = globals()
    if "resolve" in g and g["resolve"] is not None:
        return g["resolve"]
    if "app" in g and g["app"] is not None:
        return g["app"].GetResolve()
    return None


def set_input(tool, key, value):
    """Point（[x, y]）はFusionのtable形式に直してから渡す。

    グラデーションは preset をJSONにする都合で [[位置, r, g, b, a], ...] という
    リストのリストで持っている（辞書のままだと数値キーが文字列に化ける）。
    Fusion が要るのは {位置: {1: r, 2: g, 3: b, 4: a}} なので、書き込む直前のここで組む。
    """
    if key.startswith("ShadingGradient") and isinstance(value, (list, tuple)):
        stops = {}
        for stop in value:
            stops[stop[0]] = {1: stop[1], 2: stop[2], 3: stop[3], 4: stop[4]}
        tool.SetInput(key, stops)
    elif isinstance(value, (list, tuple)):
        tool.SetInput(key, {1: value[0], 2: value[1]})
    else:
        tool.SetInput(key, value)


def find_text_tool(comp):
    """Fusionコンポジションから TextPlus ツールを探す。無ければ None。

    comp が None で呼ばれることがある。Fusion comp を持たないクリップ（Fusion clip など）は
    GetFusionCompByIndex(1) が None を返すため。探し先が無いのは「見つからない」であって
    落ちる理由ではないので、ここで受ける。
    """
    if comp is None:
        return None
    for tool in (comp.GetToolList() or {}).values():
        if tool.GetAttrs().get("TOOLS_RegID") == "TextPlus":
            return tool
    return None


def write_tool(comp, tool, text, preset, comment):
    """1本の Text+ に本文と装飾を書き込む。書けなかったInput名を返す。

    Text+ は要素（塗り・縁・帯…）のパラメータを、その要素を有効にするまで持たない。
    入れたばかりの Text+ には Thickness2 も Red2 も無く、Enabled2 だけがある（実機で確認）。
    そこで、いったん全要素を有効にしてパラメータを出してから値を書き、
    最後に本来の On/Off へ戻す。書けたかどうかは読み返して確かめる。

    読み返した値は LAST_READ に残す。要素を切ったあとでは読めなくなる値があるので、
    確かめるなら全要素が有効なうちに読むしかない。

    ShadingGradient は読み返しが PyRemoteObject で中身を比べられないため、
    ここでも「読み返しが None でないか」しか確かめていない。
    """
    enables = [key for key in preset if key.startswith("Enabled")]
    comp.Lock()
    if text is not None:
        tool.SetInput("StyledText", text)
    for key in enables:
        tool.SetInput(key, 1)
    for key, value in preset.items():
        if key not in enables:
            set_input(tool, key, value)
    LAST_READ.clear()
    for key in preset:
        LAST_READ[key] = tool.GetInput(key)
    if text is not None:
        LAST_READ["StyledText"] = tool.GetInput("StyledText")
    for key in enables:
        tool.SetInput(key, preset[key])
        LAST_READ[key] = tool.GetInput(key)
    if comment is not None:
        tool.SetInput("Comments", comment)
    comp.Unlock()
    return [key for key in preset if LAST_READ.get(key) is None]


# write_tool が最後に読み返した値。確かめる処理だけが使う。
LAST_READ = {}


def as_pair(value):
    """Point の読み返しを (x, y) に直す。Fusion は table で返す。"""
    if isinstance(value, (list, tuple)):
        return (value[0], value[1]) if len(value) >= 2 else None
    if isinstance(value, dict):
        keys = sorted(value.keys())
        return (value[keys[0]], value[keys[1]]) if len(keys) >= 2 else None
    for pair in ((1, 2), (1.0, 2.0)):
        try:
            return (value[pair[0]], value[pair[1]])
        except Exception:
            continue
    return None


def same_value(want, got, key=""):
    """書いた値と読み返した値が同じかどうか。"""
    if key.startswith("ShadingGradient"):
        # グラデーションの読み返しは PyRemoteObject で、書いた値と比べようがない。
        # 照合していないことが分からないと、通ったのか見ていないのか区別できないので1度だけ言う。
        if not getattr(same_value, "gradient_notified", False):
            same_value.gradient_notified = True
            print("この環境ではグラデーションの中身を読み返せません。"
                  "ShadingGradient は入ったかどうかだけを見ています。")
        return got is not None
    if got is None:
        return False
    if isinstance(want, (list, tuple)):
        pair = as_pair(got)
        if pair is None:
            return False
        return all(abs(float(a) - float(b)) <= 1e-3 for a, b in zip(want, pair))
    if isinstance(want, str):
        return str(got) == want
    try:
        return abs(float(got) - float(want)) <= 1e-3
    except (TypeError, ValueError):
        return False


def diff_preset(preset, text):
    """読み返した値と食い違ったものを (Input名, 書いた値, 読めた値) で返す。"""
    out = []
    for key, want in preset.items():
        got = LAST_READ.get(key)
        if not same_value(want, got, key):
            out.append((key, want, got))
    if text is not None and not same_value(text, LAST_READ.get("StyledText")):
        out.append(("StyledText", text, LAST_READ.get("StyledText")))
    return out
# @/COPY@


def short(value):
    """1行に収まる形にする。"""
    if isinstance(value, bool):
        return "True"
    text = repr(value)
    if len(text) > 70:
        text = text[:67] + "..."
    return text


def data_path():
    """装飾データ.json の在り処。"""
    return os.path.join(PROJECT, DATA_NAME)


def load_data():
    """装飾データ.json を読む。無ければ (None, 理由) を返す。"""
    path = data_path()
    if not os.path.isfile(path):
        return None, ("%s が見つかりません: %s\n"
                      "手元で 手元で動かす/道具_装飾プリセットを生成.py を実行してください。"
                      % (DATA_NAME, path))
    with open(path, encoding="utf-8") as handle:
        return json.load(handle), None


# ---------------------------------------------------------------- 1 使えるAPI
def check_api(project, media_pool, out):
    """3_装飾ツール.py が使う API を1つずつ試す。落ちても止めない。"""
    rows = []
    made = []

    def check(label, func):
        try:
            value = func()
        except Exception as error:
            rows.append((label, "NG", "%s: %s" % (type(error).__name__, error)))
            return None
        if value is None or value is False:
            rows.append((label, "NG", "返り値 %r" % value))
            return None
        rows.append((label, "OK", short(value)))
        return value

    def spec(label, func, why):
        """引けないことが分かっている API。落ちたのではないので NG に数えない。"""
        value = check(label, func)
        if value is None and rows[-1][2].startswith("返り値"):
            rows[-1] = (label, "仕様", why)   # 例外で落ちたときは NG のまま残す
        return value

    check("プロジェクト設定の読み取り", lambda: "%sx%s %sfps" % (
        project.GetSetting("timelineResolutionWidth"),
        project.GetSetting("timelineResolutionHeight"),
        project.GetSetting("timelineFrameRate")))

    timeline = check("タイムラインを作る",
                     lambda: media_pool.CreateEmptyTimeline(PROBE_TIMELINE))
    if timeline is None:
        out.extend(format_api(rows))
        return rows, made
    made.append(timeline)
    check("作ったタイムラインへ切り替え", lambda: project.SetCurrentTimeline(timeline))
    check("ビデオトラックを足す", lambda: timeline.AddTrack("video"))
    check("トラック名を付ける", lambda: timeline.SetTrackName("video", 1, "確かめ"))

    item = check("Fusion Title を入れる",
                 lambda: timeline.InsertFusionTitleIntoTimeline(FUSION_TITLE))
    source = None
    if item is not None:
        source = spec("Media Pool の素材として引く", item.GetMediaPoolItem,
                      "Fusion Title は Media Pool のクリップを持たない")
        comp = check("Fusion コンポジション", lambda: item.GetFusionCompByIndex(1))
        if comp is not None:
            tool = check("Text+ ツールを探す", lambda: find_text_tool(comp))
            if tool is not None:
                check("本文を書く", lambda: write_read(tool, "StyledText", "確かめ"))
                check("数値を書く", lambda: write_read(tool, "Size", 0.08))
                check("位置(Point)を書く", lambda: write_read(tool, "Center", [0.5, 0.3]))
                check("Comments を書く", lambda: write_read(tool, "Comments", "確かめ"))
        check("クリップの色", lambda: item.SetClipColor("Blue"))

    # ここから下が本番だけが通っていた道。Fusion Title は Media Pool のクリップを持たないので、
    # 上の source はいつも None になり、「尺を指定して置く」まで届いていなかった。
    # 本番が使うのは Media Pool に置いた Text+ のほうなので、それで確かめる。
    pool_text = find_pool_clip(media_pool, TEXT_PLUS_NAME)
    if pool_text is None:
        rows.append(("Media Pool の %s" % TEXT_PLUS_NAME, "無し",
                     "置いてあれば、尺を指定して置けるかまで確かめます"))
    else:
        source = pool_text
        check("Media Pool の Text+ の尺", lambda: source.GetClipProperty("Frames"))
        for want in (WANT_FRAMES, LONG_FRAMES):
            placed = check("%dフレームで置く" % want,
                           lambda w=want: media_pool.AppendToTimeline([{
                               "mediaPoolItem": source, "startFrame": 0, "endFrame": w,
                               "trackIndex": 1, "mediaType": 1,
                           }]))
            # 置けたことと、頼んだ尺で置けたことは別。
            # 元の尺より長く置けるかは、ここでしか分からない（Text+ はジェネレータなので
            # 動画ファイルと違って伸びる見込みがあるが、見込みでは決めない）。
            if placed:
                check("  頼んだ尺になったか",
                      lambda p=placed, w=want: got_length(p[0], w))
                check("  置いたものに Text+ が在るか",
                      lambda p=placed: find_text_tool(p[0].GetFusionCompByIndex(1)))

    check("マーカーを打つ", lambda: timeline.AddMarker(0, "Blue", "確かめ", "", 1))
    copy = check("タイムラインを複製",
                 lambda: timeline.DuplicateTimeline(PROBE_TIMELINE + "_copy"))
    if copy is not None:
        made.append(copy)
    check("字幕トラックの本数", lambda: timeline.GetTrackCount("subtitle") + 1)
    check("静止画を書き出す", lambda: project.ExportCurrentFrameAsStill(
        os.path.join(tempfile.gettempdir(), "resolve_api_probe.png")))
    check("再生ヘッドを動かす", lambda: playhead_to(timeline, timeline.GetStartTimecode()))
    check("クリップの位置と尺",
          lambda: "開始%s 尺%s" % (item.GetStart(), item.GetDuration()) if item else None)

    out.extend(format_api(rows))
    return rows, made


def find_pool_clip(media_pool, name):
    """Media Pool を辿って名前でクリップを引く。無ければ None。"""

    def walk(folder):
        for clip in folder.GetClipList() or []:
            if clip.GetName() == name:
                return clip
        for sub in folder.GetSubFolderList() or []:
            found = walk(sub)
            if found is not None:
                return found
        return None

    return walk(media_pool.GetRootFolder())


def got_length(item, want):
    """置いたクリップが頼んだ尺になっているかを、実際の尺つきで返す。

    endFrame が inclusive の環境では want、exclusive では want-1 になる。
    どちらでも「決めた尺で置けている」ので通す。それ以外は違う長さなので落とす。
    """
    got = int(item.GetDuration())
    if got not in (want, want - 1):
        return None
    return "%dフレーム（頼んだのは %d / %s）" % (
        got, want, "inclusive" if got == want else "exclusive")


def write_read(tool, key, value):
    """書いてから読み返す。読めた値を返す。"""
    set_input(tool, key, value)
    return tool.GetInput(key)


def playhead_to(timeline, timecode):
    """再生ヘッドを動かして、動いた先を返す。

    SetCurrentTimecode は既にその位置に居ると False を返す。返り値では
    「動かせない」と「動く必要が無い」を見分けられないので、読み返した位置で見る。
    """
    timeline.SetCurrentTimecode(timecode)
    now = timeline.GetCurrentTimecode()
    if now is None or now.replace(";", ":") != timecode.replace(";", ":"):
        return None
    return now


def format_api(rows):
    lines = ["== 1 使える API ==", ""]
    for label, verdict, note in rows:
        lines.append("  %-4s %-24s %s" % (verdict, label, note))
    bad = [row for row in rows if row[1] == "NG"]
    known = [row for row in rows if row[1] == "仕様"]
    lines.append("")
    lines.append("  %d件中 %d件 OK・%d件 仕様・%d件 NG"
                 % (len(rows), len(rows) - len(bad) - len(known), len(known), len(bad)))
    lines.append("")
    return lines


# ---------------------------------------------------------------- 2 装飾
def preset_of(data, case):
    """割り当ての名前から、書き込む値をひと揃い組み立てる。"""
    preset = dict(data["BASE_PRESET"])
    by_key = dict((rule.get("key") or rule["name"], rule) for rule in data["RULES"])
    for name in case.get("rules") or []:
        rule = by_key.get(name)
        if rule is None:
            return None, "割り当て %r が 装飾データ.json にありません" % name
        preset.update(rule["preset"])
    return preset, None


def passed_before():
    """前に通った件の印を読む。無ければ空。"""
    path = os.path.join(PROJECT, "doc", "テスト結果.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle).get("通った件", {}) or {}
    except (ValueError, OSError):
        return {}


def check_looks(project, media_pool, data, out, force):
    """装飾データ.json の全件を書いて読み返す。

    前に通っていて、中身が1つも変わっていない件は飛ばす。
    飛ばした数は必ず出す（黙って減らすと「全部通った」に見える）。
    """
    cases = data["SWATCH_CASES"]
    known = {} if force else passed_before()
    timeline = media_pool.CreateEmptyTimeline(PROBE_TIMELINE + "_looks")
    if timeline is None:
        out.append("== 2 装飾 ==  タイムラインを作れませんでした")
        return [], [], None, {}, 0
    project.SetCurrentTimeline(timeline)

    ng, gradient, skipped, marks = [], False, [], {}
    for case in cases:
        preset, trouble = preset_of(data, case)
        if preset is None:
            ng.append((case["name"], [("装飾データ", trouble, "")]))
            continue
        # 中身の印は 装飾データ.json に入っている（作るのは生成側だけ）
        mark = case.get("印")
        if mark and known.get(case["name"]) == mark:
            skipped.append(case["name"])
            marks[case["name"]] = mark
            continue
        if any(key.startswith("ShadingGradient") for key in preset):
            gradient = True
        item = timeline.InsertFusionTitleIntoTimeline(FUSION_TITLE)
        comp = item.GetFusionCompByIndex(1) if item else None
        tool = find_text_tool(comp) if comp else None
        if tool is None:
            ng.append((case["name"], [("Text+", "あるはず", "見つからない")]))
            continue
        write_tool(comp, tool, case.get("text"), preset, None)
        bad = [(key, short(want), short(got))
               for key, want, got in diff_preset(preset, case.get("text"))]
        if item is not None:
            item.SetClipColor("Red" if bad else "Blue")
        if bad:
            ng.append((case["name"], bad))
        else:
            marks[case["name"]] = mark

    lines = ["== 2 装飾 ==  装飾データ.json 版%s / %d件" % (data.get("version"), len(cases)), ""]
    for name, bad in ng:
        lines.append("  NG %s" % name)
        for key, want, got in bad[:6]:
            lines.append("       %s 書いた %s → 読めた %s" % (key, want, got))
        if len(bad) > 6:
            lines.append("       ほか %d個" % (len(bad) - 6))
    lines.append("  試した %d件 / 飛ばした %d件 / 食い違った %d件"
                 % (len(cases) - len(skipped), len(skipped), len(ng)))
    if skipped:
        lines.append("  飛ばしたのは、前に通っていて中身も変わっていない件"
                     "（全部やり直すなら FORCE = 1 にする）。")
    if gradient:
        lines.append("  グラデーションは読み返しが PyRemoteObject のため、"
                     "入ったかどうかだけを見ています。")
    lines.append("")
    out.extend(lines)
    return cases, ng, timeline, marks, len(skipped)


# ---------------------------------------------------------------- 3 下調べ
def survey_timeline(timeline, media_pool, out):
    """いま開いているタイムラインの状態を控える。書き込みはしない。"""
    lines = ["== 3 いまのタイムラインの下調べ ==", ""]
    if timeline is None:
        lines.append("  タイムラインが開かれていません。")
        out.extend(lines + [""])
        return
    lines.append("  名前: %s" % timeline.GetName())
    for kind in ("video", "subtitle"):
        count = timeline.GetTrackCount(kind) or 0
        lines.append("  %s トラック: %d本" % (kind, count))
        for index in range(1, count + 1):
            items = timeline.GetItemListInTrack(kind, index) or []
            lines.append("    %d: %d件" % (index, len(items)))
            if kind == "subtitle":
                for item in items[:5]:
                    lines.append("       %s" % short(item.GetName()))
    root = media_pool.GetRootFolder()
    names = [clip.GetName() for clip in (root.GetClipList() or [])]
    lines.append("  Media Pool の直下: %d件 %s"
                 % (len(names), " ".join(names[:5])))
    out.extend(lines + [""])


# ---------------------------------------------------------------- 4 設定キー
# Fusion Title を入れたときの既定の尺を決めるキーを探すために見る。
# 書き替えられるなら、字幕1行ごとの尺で Text+ を入れられる（Media Pool の Text+ が要らない）。
# 公式 doc に「GetSetting を引数なしで呼ぶと引ける property が全部返る」とあるので、
# 一覧に載っていないキーもここに出る。在るか無いかを、見てから言うために置いてある。
DURATION_HINTS = ["dur", "Dur", "generator", "Generator", "title", "Title",
                  "still", "Still", "transition", "Transition"]


def first_video_item(timeline):
    """いまのタイムラインの最初のビデオクリップ。無ければ None。読むだけ。"""
    if timeline is None:
        return None
    for index in range(1, (timeline.GetTrackCount("video") or 0) + 1):
        for item in timeline.GetItemListInTrack("video", index) or []:
            return item
    return None


def grab(label, getter):
    """引数なしで呼ぶと全部返る getter を叩く。(名前, 辞書, 断り) を返す。

    公式 doc に「引数なしで呼ぶと引ける property が全部返る」とある。
    一覧に載っていないキーもここに出るので、絞らずに丸ごと控える。
    """
    if getter is None:
        return (label, None, "対象がありません")
    try:
        data = getter()
    except Exception as error:
        return (label, None, "%s: %s" % (type(error).__name__, error))
    if not isinstance(data, dict):
        return (label, None, "辞書ではありません（%s）" % type(data).__name__)
    return (label, data, "")


def survey_settings(project, timeline, out):
    """引ける設定・property を全部控える。絞らない。

    尺に関わりそうなものは頭に並べるが、それは目印であって選別ではない。
    本体は下の全件。何度も走らせずに済むよう、ここで取れるものは全部取る。
    """
    item = first_video_item(timeline)
    clip = item.GetMediaPoolItem() if item is not None else None
    tables = [
        grab("Project 設定", project.GetSetting),
        grab("Timeline 設定", timeline.GetSetting if timeline else None),
        grab("TimelineItem property", item.GetProperty if item is not None else None),
        grab("MediaPoolItem property", clip.GetClipProperty if clip is not None else None),
    ]

    hits = []
    for label, data, _trouble in tables:
        for key in sorted(data or {}):
            if any(hint in key for hint in DURATION_HINTS):
                hits.append("  %-22s %-40s %s" % (label, key, short(data[key])))

    lines = ["== 4 引ける設定・property を全部 ==", ""]
    lines.append("  尺に関わりそうなキー（目印。本体は下の全件）:")
    lines.extend(hits or ["    ありません"])
    for label, data, trouble in tables:
        lines.append("")
        if data is None:
            lines.append("  %s: %s" % (label, trouble))
            continue
        lines.append("  %s（%d件）" % (label, len(data)))
        for key in sorted(data):
            lines.append("    %-40s %s" % (key, short(data[key])))
    out.extend(lines + [""])
    return tables, hits


# ---------------------------------------------------------------- まとめ
def put(name, lines):
    """結果を書く。"""
    folder = os.path.join(PROJECT, "doc")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def main():
    resolve = get_resolve_obj()
    if resolve is None:
        print("Resolve の中から実行してください（Workspace > Console > Py3）。")
        return
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        print("プロジェクトが開かれていません。")
        return
    if not os.path.isdir(PROJECT):
        print("置き場が見当たりません: %s" % PROJECT)
        return
    data, trouble = load_data()
    if trouble:
        print(trouble)
        return

    media_pool = project.GetMediaPool()
    keep = project.GetCurrentTimeline()
    out = ["# 確かめた結果", ""]

    survey_timeline(keep, media_pool, out)
    setting_tables, setting_hits = survey_settings(project, keep, out)
    api_rows, made = check_api(project, media_pool, out)
    cases, ng, looks_timeline, marks, skipped = check_looks(
        project, media_pool, data, out, FORCE)
    if looks_timeline is not None:
        made.append(looks_timeline)

    if keep is not None:
        project.SetCurrentTimeline(keep)     # 現在のタイムラインは消せない
        media_pool.DeleteTimelines([t for t in made if t is not None])
    elif made:
        out.append("元のタイムラインが無いので、確かめ用のタイムラインを残しました。")

    api_ng = [row for row in api_rows if row[1] == "NG"]
    api_spec = [row for row in api_rows if row[1] == "仕様"]
    put("テスト結果.txt", out)
    put("テスト結果.json", [json.dumps({
        "version": data.get("version"),
        "尺に関わりそうな設定キー": [" ".join(line.split()) for line in setting_hits],
        "引ける設定": dict((label, data if data is not None else trouble)
                           for label, data, trouble in setting_tables),
        "api": {"全部": len(api_rows), "NG": len(api_ng), "仕様": len(api_spec),
                "落ちたもの": [row[0] for row in api_ng],
                "仕様で引けないもの": [row[0] for row in api_spec]},
        "装飾": {"全部": len(cases), "NG": len(ng),
                 "試した": len(cases) - skipped, "飛ばした": skipped,
                 "落ちたもの": [name for name, _ in ng]},
        "通った件": marks,
    }, ensure_ascii=False, indent=1)])

    print("")
    print("API %d件 NG %d件（ほか仕様 %d件） / 装飾 %d件（試した %d・飛ばした %d・NG %d）"
          % (len(api_rows), len(api_ng), len(api_spec), len(cases),
             len(cases) - skipped, skipped, len(ng)))
    print("結果を書きました: doc/テスト結果.txt と doc/テスト結果.json")
    if ng or api_ng:
        print("落ちたものは doc/テスト結果.txt を見てください。")


main()
