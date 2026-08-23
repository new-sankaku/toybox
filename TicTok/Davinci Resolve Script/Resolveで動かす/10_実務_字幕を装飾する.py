# -*- coding: utf-8 -*-
"""
【Resolve の Console に貼る】Workspace > Console > Py3。手元で動かしても何も出ません。
字幕を Text+ にして装飾する。貼れば走る。選ぶところは無い。

  Text+ が無い timeline   … 字幕トラックの各行を、同じ位置・同じ尺の Text+ にして装飾する
  Text+ が在る timeline   … その本文を読み直して装飾を当て直す

字幕そのものは Scripting API から装飾できない（フォント・縁・影のキーが無い）。
本文も書き替えられない（`SetName` が効かない。doc/わかったこと.md）。触れるのは Text+ だけなので、
まず Text+ にする。目印を書き替えたら、もう一度これを貼れば当て直る。

行頭の目印で装飾が変わる。目印は1文字の記号（`!嘘でしょ`）と `[名前]`（`[筆文字]墨で書く`）の
2通りで、どちらでも同じものを呼べる。見本は 装飾プリセットを選ぶ.html で確認する。
行ごとに変えたい行は、字幕の行頭へ手で打つ（画面の札を押すとクリップボードに入る）。
`MARKER` は **まだ何も選んでいない行をまとめてその装飾にする**もの。`触らない` と書けば、
目印を名乗る行だけ装飾して残りは既定のままになる。

目印は装飾になった時点で本文から外れるので、効いた目印は Text+ の Comments に控える。
当てる順は 本文の行頭 → Comments の控え → `MARKER` で、一度選んだ行は `MARKER` を
書き替えても動かない。全部まとめて塗り替えるときだけ `KEEP_MARKS = False` と書く。

置き場所:
  %APPDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Fusion\\Scripts\\Utility\\
  へ置くと Workspace > Scripts のメニューに出る（`手元で動かす/導入_Resolveのメニューへ登録.py` が入れる）。
  装飾の表は隣の 装飾データ.json が持つので、2つを対で置く。

Media Pool に Text+ を1つ用意しておく（1回だけ・手作業）。尺を指定して置けるのは
Media Pool のクリップだけで、それを script から作る道は無い（doc/わかったこと.md）。
中身も尺もそのままでよく、本文と装飾は置いたあとに script が書き込む。
Text+ はジェネレータなので、元の尺より長い字幕にも合わせて置ける。1つを全行で使い回す。
"""

import difflib
import io
import json
import os
import re
import traceback

# ---------------------------------------------------------------- 設定
# --- 目印が付いていない行をどうするか
NO_MARKER = "触らない"         # MARKER にこう書くと「当てない」という意思表示になる

MARKER = NO_MARKER             # 装飾名     … まだ何も選んでいない行をその装飾にする
                               # "触らない" … 目印か控えを名乗る行だけ装飾する
                               # 名前は 装飾プリセットを選ぶ.html に在るものだけ。
                               # 打ち間違いは近い候補を出して止まる。
                               # 空欄は書き忘れと見分けが付かないので、止まる。
                               # 効くのは字幕から作ったトラックだけ。他トラックの Text+ は
                               # 目印か控えを名乗ったものしか触らない。

KEEP_MARKS = False              # True  … 一度当てた行（Comments に控えの在る行）は
                               #         MARKER で塗り替えない
                               # False … 控えを捨てて当て直す。行ごとに選んだ装飾は消え、
                               #         字幕トラックの行は MARKER、他トラックは既定になる

RULE_TAG = "装飾: "            # 効いた目印を Text+ の Comments に控える印。
                               # 目印は本文から外れるので、控えが無いと貼り直しで既定へ戻る。

BRACKETS = [("[", "]"), ("［", "］"), ("「", "」"), ("【", "】")]



TEXT_PLUS_NAME = "Text+"       # Media Pool に置く Text+ 素材の名前
FUSION_TITLE = "Text+"         # Effects > Titles での Fusion Title の名前
TRACK_NAME = ""                # 目印が無くても装飾するトラック名。空なら CONVERTED_TRACK
CONVERTED_TRACK = "字幕Text+"  # 字幕から作った Text+ を並べるトラックの名前
                               # 当て直しは全ビデオトラックの Text+ を見る。この2つの外に
                               # 在るものは、目印か控えを名乗る Text+ だけ触る。

SUBTITLE_TRACK_INDEX = 1       # 変換元の字幕トラック番号
DISABLE_SUBTITLE_TRACK = True  # 変換後に元の字幕トラックを非表示にするか
PROBE_LENGTH = 10              # endFrame仕様の判定に使うフレーム数

LOOK = ""                      # 土台にするプリセット。空なら既定のまま

WRAP = 1                       # 1=折り返す / 0=折り返さない。
                               # 1行に載る文字数は装飾ごとに違う（実測で10〜32字）。
                               # 装飾データ.json が装飾ごとに持っているので、
                               # ここで文字数を決めない。字幕トラックは Resolve が
                               # 勝手に折り返すが、Text+ は折り返さない。


# 装飾の表を持つ file。この script の隣に置く。
# Console へ貼って動かすときだけ、在り処をここに書く（__file__ が無いため）。
# 書いてあるとこちらが優先されるので、Workspace > Scripts へ入れた写しも
# この在り処の JSON を読む。写しと元表がずれない代わりに、この path が
# 無くなると止まる（そのときは空に戻すと、隣の JSON を読むようになる）。
DATA_NAME = "装飾データ.json"
DATA_PATH = r"C:\01_work\00_Git\toybox\TicTok\Davinci Resolve Script\装飾データ.json"
DATA_VERSION = 2               # 装飾データ.json の版。合わないと止まる

# ---------------------------------------------------------------- 生成される表
# 中身は隣の 装飾データ.json が持つ。手元で動かす/道具_装飾プリセットを生成.py が両方を書き出す。
# ここを空の入れ物にしてあるのは、画面（装飾プリセットを選ぶ.html）が配る script は
# この5つを実体で埋めた形で出てくるためで、そのまま貼れば JSON が無くても動く。
# file として置いたものは JSON を読んで埋める。手で直さない。
MARKER_CHARS = ""

BASE_CHARS = 0

# 装飾を作ったときの画面。これと違う画面で使うと、文字の大きさが変わる。
# Size は画面の幅に対する比なので、横1920で使うと実寸が1.78倍になり、
# 画面の高さは半分なので見た目で約3.2倍になる。
FIT_FRAME = [1080, 1920]

BASE_PRESET = {
}

RULES = [
]

LOOKS = [
]

SWATCH_CASES = [
]


def stop(message):
    """理由を名乗って止める。分からない値を推し量って動き続けない。"""
    note(message)
    raise SystemExit(1)


def data_file():
    """装飾データ.json の在り処を返す。分からなければ空を返す。

    Workspace > Scripts から動かすと __file__ があるので、その隣を見る。
    Console へ貼ったときは __file__ が無いので、DATA_PATH に書いてもらう。
    在り処を推し量ると、別の場所の古い JSON を掴んでも気づけない。
    """
    if DATA_PATH:
        return os.path.abspath(os.path.expanduser(DATA_PATH))
    if "__file__" in globals():
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), DATA_NAME)
    return ""


LOG_NAME = "実行ログ.txt"


def log_path():
    """log を書く先。装飾データ.json の隣、分からなければ利用者のフォルダ。"""
    path = data_file()
    folder = os.path.dirname(path) if path else os.path.expanduser("~")
    return os.path.join(folder, LOG_NAME)


def note(message):
    """Console と log file の両方へ書く。

    Workspace > Scripts から動かすと Console に何も出ないことがあり、
    Resolve ごと落ちると出したはずの文字も消える。file にも書いて、
    毎回閉じておけば、黙って終わっても「どこまで進んだか」が残る。
    """
    print(message)
    try:
        with io.open(log_path(), "a", encoding="utf-8", newline="") as handle:
            handle.write(message + os.linesep)
    except Exception as error:
        # log が書けないことで本題は止めない。ただし黙ると「落ちた」と見分けが付かないので
        # 理由を1度だけ名乗る。file が無いことと、書けないことは別物。
        if not getattr(note, "told", False):
            note.told = True
            print("log を書けません（%s: %s）。Console の文字だけが頼りになります。"
                  % (type(error).__name__, error))


note("==== 貼られました ====")


def load_data():
    """装飾データ.json を読んで、上の5つの表を埋める。

    LOOKS と SWATCH_CASES の装飾は RULES と同じ中身なので、JSON では持たずに
    RULES の key で指している（同じ値を3か所に書くと、直したときにずれる）。
    LOOKS は指した rule の装飾そのもの、SWATCH_CASES は BASE_PRESET に
    指した rule を並び順どおり重ねたもので、ここで組み直す。
    """
    global MARKER_CHARS, BASE_CHARS, FIT_FRAME, BASE_PRESET, RULES, LOOKS, SWATCH_CASES

    path = data_file()
    if not path:
        stop("%s の在り処が分かりません（__file__ がありません）。\n"
             "Console へ貼って動かすときは、この script の設定欄に\n"
             "  DATA_PATH = r\"<%s の在り処>\"\n"
             "と書いてください。\n"
             "装飾プリセットを選ぶ.html の「コピー」で取った script なら、"
             "装飾の表が入っているので DATA_PATH は要りません。" % (DATA_NAME, DATA_NAME))
    if not os.path.isfile(path):
        stop("%s がありません: %s\n"
             "手元で動かす/道具_装飾プリセットを生成.py を実行すると作られます。" % (DATA_NAME, path))
    try:
        with io.open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError as error:
        stop("%s を読めません（JSON として壊れています）: %s\n%s"
             % (DATA_NAME, path, error))

    version = data.get("version")
    if version != DATA_VERSION:
        stop("%s の版が合いません（script は %r、file は %r）: %s\n"
             "手元で動かす/道具_装飾プリセットを生成.py を実行し直してください。"
             % (DATA_NAME, DATA_VERSION, version, path))
    lack = [name for name in ("MARKER_CHARS", "BASE_CHARS", "FIT_FRAME", "BASE_PRESET",
                              "RULES", "LOOKS", "SWATCH_CASES") if name not in data]
    if lack:
        stop("%s に %s がありません: %s" % (DATA_NAME, "・".join(lack), path))

    MARKER_CHARS = data["MARKER_CHARS"]
    BASE_CHARS = data["BASE_CHARS"]
    FIT_FRAME = data["FIT_FRAME"]
    BASE_PRESET = data["BASE_PRESET"]
    RULES = data["RULES"]
    by_key = {}
    for rule in RULES:
        if rule["key"] in by_key:
            stop("%s の RULES に同じ key が2つあります: %r（%s）"
                 % (DATA_NAME, rule["key"], path))
        by_key[rule["key"]] = rule

    def rule_preset(key, where):
        """key の指す rule の装飾を返す。指し先が無ければ止める。"""
        if key not in by_key:
            stop("%s の %s が、RULES に無い %r を指しています: %s"
                 % (DATA_NAME, where, key, path))
        return by_key[key]["preset"]

    looks = []
    for look in data["LOOKS"]:
        entry = dict(look)
        key = entry.pop("rule")
        entry["preset"] = dict(rule_preset(key, "LOOKS %r" % look.get("key", "")))
        looks.append(entry)
    LOOKS = looks

    cases = []
    for case in data["SWATCH_CASES"]:
        entry = dict(case)
        preset = dict(BASE_PRESET)
        for key in entry.pop("rules"):
            preset.update(rule_preset(key, "SWATCH_CASES %r" % case.get("name", "")))
        entry["preset"] = preset
        cases.append(entry)
    SWATCH_CASES = cases


# ---------------------------------------------------------------- Resolve を掴む
def get_resolve_obj():
    """Resolve内部実行時に用意されているResolveオブジェクトを取得する。"""
    g = globals()
    if "resolve" in g and g["resolve"] is not None:
        return g["resolve"]
    if "app" in g and g["app"] is not None:
        return g["app"].GetResolve()
    return None


def current(resolve):
    """(project, timeline, media_pool) を返す。"""
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        return None, None, None
    return project, project.GetCurrentTimeline(), project.GetMediaPool()


# ---------------------------------------------------------------- 目印の判定
def find_look(name):
    """名前からプリセットの装飾を返す。見つからなければNone。"""
    if not name:
        return {}
    for look in LOOKS:
        if look["name"] == name:
            return look["preset"]
    return None


def find_rule(name):
    """名前から目印の装飾を返す。"""
    for rule in RULES:
        if rule["name"] == name:
            return rule["preset"]
    return {}


def find_rule_by_key(name):
    """[名前] の中身からruleを引く。短い名前でも表示名でも引ける。"""
    if not name:
        return None
    for rule in RULES:
        if rule.get("key") and (name == rule["key"] or name == rule["name"]):
            return rule
    return None


def split_marker(text):
    """行頭の目印と本文に分ける。

    目印は2種類ある。1文字の記号（話者・感情など）と、[名前] で書くもの。
    括弧は中身が既知の名前のときだけ食べるので、「【耳かき】…」のような本文は素通りする。
    本文が空になる場合は目印なしとして扱う。
    """
    index = 0
    symbols = []
    names = []
    while index < len(text):
        char = text[index]
        bracket = next((pair for pair in BRACKETS if pair[0] == char), None)
        if bracket:
            close = text.find(bracket[1], index + 1)
            if close < 0:
                break
            inner = text[index + 1:close].strip()
            if not find_rule_by_key(inner):
                break
            names.append(inner)
            index = close + 1
            continue
        if char in MARKER_CHARS:
            symbols.append(char)
            index += 1
            continue
        break
    body = text[index:].strip()
    if not body:
        return "", [], text.strip()
    return "".join(symbols), names, body


def rule_hits(rule, symbols, names, body):
    """このruleが効くかを返す。1文字の記号と [名前] のどちらで書いても効く。"""
    by_name = bool(rule.get("key")) and (rule["key"] in names or rule["name"] in names)
    by_mark = bool(rule["marker"]) and bool(symbols) and bool(re.search(rule["marker"], symbols))
    if rule["pattern"] and not re.search(rule["pattern"], body):
        return False
    if rule["marker"] or rule.get("key"):
        return by_name or by_mark
    return bool(rule["pattern"])


def resolve_style(text, marks=None):
    """本文から (表示する本文, 装飾, 素材名, 効いた目印) を決める。

    marks を渡すと、本文の行頭に書かれた目印の代わりにそれを使う。設定の MARKER や、
    Comments に控えてある目印を当てるための道。効いた目印は短い名前（key）で返す。
    """
    symbols, names, body = split_marker(text)
    if marks is not None:
        names = list(marks)
    preset = dict(BASE_PRESET)
    preset.update(find_look(LOOK) or {})
    source = TEXT_PLUS_NAME
    matched = []
    for rule in RULES:
        if not rule_hits(rule, symbols, names, body):
            continue
        matched.append(rule["key"])
        preset.update(rule["preset"])
        if rule.get("source"):
            source = rule["source"]
    return body, preset, source, matched


def near_names(name):
    """打ち間違いに近い目印の名前を挙げる。"""
    keys = [rule["key"] for rule in RULES if rule.get("key")]
    close = difflib.get_close_matches(name, keys, n=6, cutoff=0.4)
    for key in keys:
        if len(close) >= 6:
            break
        if name and (name in key or key in name) and key not in close:
            close.append(key)
    return close


def check_marker(name):
    """設定の MARKER が実在するかを確かめる。(rule, 断り) を返す。

    在るかどうかを確かめずに当てにいくと、打ち間違えた行だけ黙って既定の装飾になる。
    空欄は受けない。「当てないと決めた」のか「書き忘れた」のかを file から見分けられず、
    そのまま動かすと、どちらのつもりだったかが分からないまま結果だけが残るため。
    """
    inner = (name or "").strip()
    for pair in BRACKETS:
        if len(inner) >= 2 and inner[0] == pair[0] and inner[-1] == pair[1]:
            inner = inner[1:-1].strip()
    if not inner:
        return None, ("MARKER が空です。まだ何も選んでいない行に当てる装飾名か、"
                      "%r と書いてください。" % NO_MARKER)
    if inner == NO_MARKER:
        return None, ""
    rule = find_rule_by_key(inner)
    if rule is not None:
        return rule, ""
    close = near_names(inner)
    if close:
        return None, "目印 %r は表にありません。近いのは: %s" % (inner, " / ".join(close))
    return None, ("目印 %r は表にありません（%d件の中に見当たりません）。"
                  "装飾プリセットを選ぶ.html で名前を確かめてください。" % (inner, len(RULES)))


NO_HEAD = "、。，．！？）」』】〕〉》・ー…ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ"
NO_TAIL = "（「『【〔〈《"


def cell(char):
    """その文字が占める幅。全角を1、半角を0.5として数える。"""
    return 0.5 if ord(char) < 0x3000 else 1.0


def wrap_line(line, limit):
    """1行を limit（全角換算）で折り返して、行の並びにする。

    行頭に来てはいけない字（句読点・閉じ括弧・小書き・長音）は前の行へ残し、
    行末に来てはいけない字（開き括弧）は次の行へ送る。字数だけで切ると
    「、」が行頭に来て読みにくくなるため。
    """
    lines = []
    now = ""
    width = 0.0
    for char in line:
        if width + cell(char) > limit and now:
            if char in NO_HEAD:
                now += char           # 追い出さずに、はみ出しても前の行へ残す
                lines.append(now)
                now, width = "", 0.0
                continue
            while now and now[-1] in NO_TAIL:
                char, now = now[-1] + char, now[:-1]
            lines.append(now)
            now, width = "", 0.0
        now += char
        width += cell(char)
    if now:
        lines.append(now)
    return lines


def wrap_body(text, limit):
    """本文を折り返す。もとから入っている改行は残す。"""
    if not WRAP or not limit:
        return text
    out = []
    for line in text.splitlines() or [text]:
        out.extend(wrap_line(line, limit) or [""])
    return chr(10).join(out)


def line_chars(matched):
    """効いた目印から、1行に載る文字数を決める。分からなければ 0。

    幅は装飾ごとに違うので、重ねた中でいちばん狭いものに合わせる。広いほうに
    合わせると、狭い装飾がはみ出す。どれも当たっていなければ既定の装飾の値。
    実測していない書体（縦書きなど）は None を持つので、そこは折り返さない。
    """
    limits = []
    for key in matched:
        rule = find_rule_by_key(key)
        if rule is None:
            continue
        if rule.get("chars"):
            limits.append(rule["chars"])
        elif "chars" in rule:
            return 0          # 実測が無い装飾。字数で切らない
    if limits:
        return min(limits)
    return BASE_CHARS or 0


# ---------------------------------------------------------------- Text+ を触る
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


def tool_inputs(tool):
    """その Text+ が持っているInput名の集合。"""
    ids = set()
    for inp in (tool.GetInputList() or {}).values():
        ids.add(inp.GetAttrs().get("INPS_ID"))
    return ids


def marked_rules(tool):
    """Comments に控えた目印を読む。控えが無ければ空。"""
    text = tool.GetInput("Comments") or ""
    if not text.startswith(RULE_TAG):
        return []
    return [name for name in text[len(RULE_TAG):].split(",") if name]


def marks_for(text, recorded, forced):
    """その行に当てる目印を決める。resolve_style へ渡す形で返す（None なら本文のまま）。

    強い順に 本文の行頭 → Comments の控え → 設定の MARKER。

    手で選んだものがいちばん強い。目印は装飾になった時点で本文から外れて控えだけになるので、
    控えが MARKER より強くないと、後から MARKER を書いただけで行ごとに選んだ装飾が
    黙って消える。MARKER は「まだ何も選んでいない行」を埋めるものに徹する。
    まとめて塗り替えたいときは KEEP_MARKS を False にして、控えを捨てると宣言する。

    記号の目印（`!` など）は話者・感情で役目が別なので、ここでは見ない。
    本文に残っている記号は MARKER と重なって両方効く。
    """
    _symbols, names, _body = split_marker(text)
    if names:
        return None
    if KEEP_MARKS and recorded:
        return recorded
    if forced is not None:
        return [forced["key"]]
    return None


def converted_track(timeline):
    """字幕から作った Text+ のトラック番号。無ければ 0。

    「Text+ が在るかどうか」で変換済みを判じない。Media Pool へ入れるために置いた
    Text+ がタイムラインに残っているだけで「変換済み」と読み違えるため（実際に起きた）。
    見るのは、変換したときに自分で付けたトラック名だけ。
    """
    for index in range(1, (timeline.GetTrackCount("video") or 0) + 1):
        if timeline.GetTrackName("video", index) == CONVERTED_TRACK:
            return index
    return 0


def collect_targets(timeline):
    """当て直す先を全ビデオトラックから集める。(クリップ, comp, ツール, 自前か) を返す。

    自前 = 字幕から作ったトラック（TRACK_NAME か CONVERTED_TRACK）に載っているもの。
    そこは字幕1行が1本ずつ載っている前提なので、目印が無くても装飾する。
    それ以外のトラックの Text+ は、目印か控えの在るものだけ触る（action_restyle が判じる）。
    無関係なタイトルまで BASE_PRESET で塗り替えないため、線は「トラック名」ではなく
    「触ってよいと名乗っているか」で引く。
    """
    want = TRACK_NAME or CONVERTED_TRACK
    targets = []
    skipped = []
    for index in range(1, (timeline.GetTrackCount("video") or 0) + 1):
        track = timeline.GetTrackName("video", index)
        owned = track == want
        items = timeline.GetItemListInTrack("video", index) or []
        found = 0
        for item in items:
            comp = item.GetFusionCompByIndex(1) if item.GetFusionCompCount() >= 1 else None
            tool = find_text_tool(comp)
            if tool is None:
                if owned:
                    skipped.append(item.GetStart())
                continue
            found += 1
            targets.append((item, comp, tool, owned))
        if found or owned:
            note("  %s: %d件のうち Text+ %d本%s"
                 % (track, len(items), found, "（字幕から作ったトラック）" if owned else ""))
    if skipped:
        note("%r で Text+ が見つからず飛ばした開始フレーム: %s" % (want, skipped))
    return targets


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


# ---------------------------------------------------------------- 素材を用意する
def iter_media_items(folder):
    """Media Pool のフォルダを再帰的に辿ってクリップを列挙する。"""
    for clip in folder.GetClipList() or []:
        yield clip
    for sub in folder.GetSubFolderList() or []:
        for clip in iter_media_items(sub):
            yield clip


def find_media_item(media_pool, name):
    """名前で Media Pool のクリップを引く。"""
    for clip in iter_media_items(media_pool.GetRootFolder()):
        if clip.GetName() == name:
            return clip
    return None


def find_media_items(media_pool, names):
    """名前の集合に一致する Media Pool クリップを名前引きで返す。"""
    wanted_names = set(names)
    found = {}
    for clip in iter_media_items(media_pool.GetRootFolder()):
        name = clip.GetName()
        if name in wanted_names and name not in found:
            found[name] = clip
    return found


def timeline_fps(timeline):
    """タイムラインのフレームレート。読めなければ推し量らずに止める。"""
    rate = timeline.GetSetting("timelineFrameRate")
    try:
        return float(rate)
    except (TypeError, ValueError):
        stop("タイムラインのフレームレートを読めません（%r）。" % rate)


def manual_steps(name):
    """素材の作り方を案内する。要る尺は実際の字幕から測って言う。

    script では作れない。Fusion Title は置けるが Media Pool のクリップを持たず
    （GetMediaPoolItem が None）、Fusion clip にまとめた素材は置いても Fusion comp を
    持たない（どちらも実機で確認。doc/わかったこと.md）。尺を指定して置けるのは
    Media Pool の素材だけなので、ここだけは手で用意してもらう。

    要る尺は「いちばん長い字幕より長いこと」だけ。決め打ちの秒数には根拠が無い。
    """
    note("Media Pool に %r がありません。1度だけ手で用意してください。" % name)
    note("  1. Effects > Titles の Text+ をタイムラインに置く")
    note("  2. そのクリップを Media Pool へドラッグし、名前を %r にする" % name)
    note("  3. この script をもう一度貼る")
    note("尺は伸ばさなくて構いません。置くときに字幕の尺へ合わせます。")
    note("中身は空で構いません。本文と装飾は置いたあとに script が書き込みます。")
    note("1つあれば全行で使い回します。")


# ---------------------------------------------------------------- 1. 置き換える
def find_text_tool_anywhere(item, label):
    """置いたクリップが持つ Fusion comp を全部当たって TextPlus を探す。

    index 1 が None でも、comp を持っていないとは限らない。何本持っていて
    どんな名前かを名乗ってから探す。名乗らせるのは、次に同じ所で詰まったときに
    推し量らずに済むようにするため。
    """
    count = item.GetFusionCompCount()
    names = item.GetFusionCompNameList()
    note("%r の Fusion comp: %s本 %s" % (label, count, names))
    for index in range(1, (count or 0) + 1):
        tool = find_text_tool(item.GetFusionCompByIndex(index))
        if tool is not None:
            note("  %d本目に TextPlus がありました。" % index)
            return tool
    for name in names or []:
        tool = find_text_tool(item.GetFusionCompByName(name))
        if tool is not None:
            note("  %r に TextPlus がありました。" % name)
            return tool
    return None


def first_placed(placed):
    """AppendToTimeline の戻りから、実体のある1本目を返す。無ければ None。

    リストは返るのに中身が None、という戻り方をすることがある（実機で確認）。
    `if not placed` だけでは通り抜けて落ちる。
    """
    for item in placed or []:
        if item is not None:
            return item
    return None


def probe_sources(project, media_pool, items, restore_timeline):
    """endFrame の仕様と、中に TextPlus が在るかを仮タイムラインで実測する。

    置き方はテストで通った形に揃える（startFrame / endFrame / trackIndex を渡す）。
    何も渡さずに丸ごと置くと、リストは返るのに中身が None になる（実機で確認）。

    尺は測らない。Text+ はジェネレータで元の尺に縛られないことが分かったので、
    字幕の尺と比べる必要が無い（doc/わかったこと.md）。
    """
    probe = media_pool.CreateEmptyTimeline("__probe_textplus__")
    if probe is None:
        return None
    project.SetCurrentTimeline(probe)
    if (probe.GetTrackCount("video") or 0) < 1:
        probe.AddTrack("video")

    facts = {}
    try:
        for name, item in items.items():
            placed = first_placed(media_pool.AppendToTimeline([{
                "mediaPoolItem": item,
                "startFrame": 0,
                "endFrame": PROBE_LENGTH - 1,
                "trackIndex": 1,
                "mediaType": 1,
            }]))
            if placed is None:
                note("Text+ %r をタイムラインへ置けません。" % name)
                continue
            tool = find_text_tool(placed.GetFusionCompByIndex(1))
            if tool is None:
                # 1本目が None でも comp を持たないとは限らない。何本あるか見てから言う。
                tool = find_text_tool_anywhere(placed, name)
            if tool is None:
                note("Text+ %r を置いても、中に TextPlus が見つかりません。" % name)
                continue
            # inclusive なら PROBE_LENGTH、exclusive なら1つ短くなる
            got = int(placed.GetDuration())
            facts[name] = {
                "item": item,
                "inclusive": got == PROBE_LENGTH,
                "inputs": tool_inputs(tool),
            }
    finally:
        # 途中で何が起きても仮タイムラインは片付ける。現在のタイムラインは消せないので先に戻る。
        project.SetCurrentTimeline(restore_timeline)
        media_pool.DeleteTimelines([probe])
    return facts


def action_convert(resolve, forced):
    """字幕トラックの各行を Text+ に置き換える。"""
    project, timeline, media_pool = current(resolve)
    if timeline is None:
        return "タイムラインが開かれていません。"
    if find_look(LOOK) is None:
        return "プリセット %r がありません。" % LOOK
    if timeline.GetTrackCount("subtitle") < SUBTITLE_TRACK_INDEX:
        return "字幕トラック %d がありません。" % SUBTITLE_TRACK_INDEX
    subtitles = timeline.GetItemListInTrack("subtitle", SUBTITLE_TRACK_INDEX) or []
    if not subtitles:
        return "字幕トラック %d にクリップがありません。" % SUBTITLE_TRACK_INDEX
    note("字幕 %d行を読みました。" % len(subtitles))

    plans = []
    marks_at = {}
    for item in subtitles:
        text = item.GetName() or ""
        marks = marks_for(text, [], forced)
        marks_at[item.GetStart()] = marks
        _body, _preset, source, _matched = resolve_style(text, marks)
        plans.append((item, source))

    needed = sorted({source for _item, source in plans})
    note("使う Text+ 素材: %s" % "・".join(needed))
    items = find_media_items(media_pool, needed)
    missing = [name for name in needed if name not in items]
    if TEXT_PLUS_NAME in missing:
        manual_steps(TEXT_PLUS_NAME)
        return "Text+ が無いので何もしていません。用意してから貼り直してください。"
    if missing:
        note("動きを付けた素材は、その名前で手で用意してください。")
        return "Media Pool に次の Text+ 素材がありません: %s" % "・".join(missing)

    note("素材の尺を仮タイムラインで測ります。")
    facts = probe_sources(project, media_pool, items, timeline)
    if not facts or len(facts) != len(needed):
        return "置いた Text+ の中に TextPlus がありません。中身を確かめてください。"
    for name in needed:
        note("Text+ %r: endFrame は %s"
             % (name, "inclusive" if facts[name]["inclusive"] else "exclusive"))

    # Text+ の尺と字幕の尺は比べない。Text+ はジェネレータなので、元の尺より長くも置ける
    # （120フレームのものを600フレームで置けることを実機で確認。doc/わかったこと.md）。
    # 代わりに、置いたあとで頼んだ尺になっているかを1本ずつ見る。

    new_timeline = timeline.DuplicateTimeline(timeline.GetName() + "_textplus")
    if new_timeline is None:
        return "タイムラインを複製できません。"
    if not new_timeline.AddTrack("video"):
        return "ビデオトラックを追加できません。"
    track_index = new_timeline.GetTrackCount("video")
    new_timeline.SetTrackName("video", track_index, "字幕Text+")

    texts = {}
    wants = {}
    infos = []
    for item, source in plans:
        start = item.GetStart()
        duration = item.GetDuration()
        texts[start] = item.GetName()
        wants[start] = int(duration)
        infos.append({
            "mediaPoolItem": facts[source]["item"],
            "startFrame": 0,
            "endFrame": duration - 1 if facts[source]["inclusive"] else duration,
            "recordFrame": start,
            "trackIndex": track_index,
            "mediaType": 1,  # 1=ビデオのみ
        })

    note("複製 %r を作りました。%d件を配置します。" % (new_timeline.GetName(), len(infos)))
    project.SetCurrentTimeline(new_timeline)
    created = [item for item in (media_pool.AppendToTimeline(infos) or []) if item is not None]
    if len(created) != len(infos):
        note("配置できたのは %d/%d 件です。" % (len(created), len(infos)))
    note("配置しました。装飾を書き込みます。")

    failed = []
    short_placed = []
    hits = {}
    for item in created:
        text = texts.get(item.GetStart())
        comp = item.GetFusionCompByIndex(1)
        tool = find_text_tool(comp) if comp is not None else None
        if text is None or tool is None:
            failed.append(item.GetStart())
            continue
        want = wants.get(item.GetStart())
        if want is not None and int(item.GetDuration()) != want:
            # 字幕と尺が違えば、そこだけ表示時間がずれる。黙って進めない。
            short_placed.append((item.GetStart(), want, int(item.GetDuration())))
        body, preset, _source, matched = resolve_style(text, marks_at.get(item.GetStart()))
        # 目印は本文から消えるので、次に貼ったとき既定へ戻らないよう控えておく
        report_missing(write_tool(comp, tool, wrap_body(body, line_chars(matched)), preset,
                                  RULE_TAG + ",".join(matched)))
        for name in matched:
            hits[name] = hits.get(name, 0) + 1

    note("装飾を書き込みました（%d本）。" % (len(created) - len(failed)))
    if DISABLE_SUBTITLE_TRACK:
        new_timeline.SetTrackEnable("subtitle", SUBTITLE_TRACK_INDEX, False)

    print_hits(hits)
    if failed:
        note("本文/装飾を書き込めなかった開始フレーム: %s" % failed)
    if short_placed:
        note("字幕と尺が違うものが %d件あります（開始 / 頼んだ尺 / 実際）:" % len(short_placed))
        for start, want, got in short_placed[:5]:
            note("  %d  %d  %d" % (start, want, got))
    return "%d クリップを %s に配置しました。" % (len(created), new_timeline.GetName())


_told = set()


def report_missing(missing):
    """書けなかったInput名を、同じものは1回だけ報せる。"""
    fresh = [key for key in missing if key not in _told]
    if not fresh:
        return
    _told.update(fresh)
    print("書けなかったInput名: %s" % ", ".join(sorted(fresh)))
    print("手元で動かす/診断_字幕とText+を調べる.py でInput一覧を確認してください。")


def print_hits(hits):
    """効いた目印の内訳を出す。"""
    for rule in RULES:
        count = hits.get(rule["key"], 0)
        if count:
            print("  %s: %d件" % (rule["name"], count))


# ---------------------------------------------------------------- 2. 作り直す
def action_restyle(resolve, forced):
    """すでにある Text+ の本文を読み直して装飾を書き直す。"""
    _project, timeline, _media_pool = current(resolve)
    if timeline is None:
        return "タイムラインが開かれていません。"
    if find_look(LOOK) is None:
        return "プリセット %r がありません。" % LOOK
    targets = collect_targets(timeline)
    if not targets:
        return "タイムラインに Text+ がありません。"
    note("タイムライン %r の Text+ %d本を見ます。" % (timeline.GetName(), len(targets)))

    hits = {}
    touched = 0
    passed = 0
    for item, comp, tool, owned in targets:
        text = tool.GetInput("StyledText") or ""
        recorded = marked_rules(tool)
        _symbols, names, _body = split_marker(text)
        if not owned and not names and not recorded:
            # 自前のトラックの外に居て、目印も控えも名乗らない Text+。素通りする
            passed += 1
            continue
        # MARKER は「字幕の目印を打っていない行」を埋めるものなので、自前のトラックにだけ効かせる。
        # 外のトラックにも効かせると、タイムライン上のタイトルが全部その装飾になる。
        marks = marks_for(text, recorded, forced if owned else None)
        body, preset, _source, matched = resolve_style(text, marks)
        note("  %s | %s | 本文 %r → 目印 %s / 控え %s"
             % (item.GetStart(), "自前" if owned else "他トラック",
                text[:16].replace(chr(10), "/"), matched or "無し", recorded or "無し"))
        wrapped = wrap_body(body, line_chars(matched))
        report_missing(write_tool(comp, tool, wrapped if wrapped != text else None, preset,
                                  RULE_TAG + ",".join(matched)))
        touched += 1
        for name in matched:
            hits[name] = hits.get(name, 0) + 1
    print_hits(hits)
    if passed:
        note("目印も控えも無い Text+ %d本は触っていません。" % passed)
    return "%d クリップの装飾を更新しました。" % touched


def check_frame(timeline):
    """画面の大きさが、装飾を作ったときと同じかを確かめる。違えば断りを返す。

    Size は画面の幅に対する比なので、違う画面で使うと文字の大きさが変わる。
    横1920で縦向けの装飾を使うと、実寸が1.78倍・画面の高さは半分で、見た目は
    約3.2倍になる。装飾の値は正しいのに「文字が大きすぎる」ことになるので、
    そのまま置かずにここで止める。
    """
    got = (timeline.GetSetting("timelineResolutionWidth"),
           timeline.GetSetting("timelineResolutionHeight"))
    try:
        got = (int(got[0]), int(got[1]))
    except (TypeError, ValueError):
        return "タイムラインの大きさを読めません（%r）。" % (got,)
    want = (int(FIT_FRAME[0]), int(FIT_FRAME[1]))
    if got == want:
        return ""
    note("画面の大きさが %dx%d ですが、装飾は %dx%d 向けに作ってあります。"
         % (got[0], got[1], want[0], want[1]))
    note("このまま置くと文字の大きさが変わります（幅の比が %.2f倍）。"
         % (float(got[0]) / want[0]))
    return ("Project Settings > Master Settings > Timeline resolution を %dx%d に"
            "してください。" % (want[0], want[1]))


def main():
    note("---- 実行開始 ----")
    note("log: %s" % log_path())
    if not RULES:
        note("装飾の表がありません。手元で動かす/道具_装飾プリセットを生成.py を実行してください。")
        return
    resolve = get_resolve_obj()
    if resolve is None:
        note("Resolveオブジェクトを取得できません。")
        return
    project, timeline, _pool = current(resolve)
    if project is None:
        note("プロジェクトが開かれていません。")
        return
    if timeline is None:
        note("タイムラインが開かれていません。")
        return

    error = check_frame(timeline)
    if error:
        note(error)
        return

    forced, error = check_marker(MARKER)
    if error:
        note(error)
        return
    if forced is not None:
        note("まだ何も選んでいない行は [%s] にします。" % forced["key"])
    else:
        note("目印か控えを名乗る行だけ装飾します。")
    if KEEP_MARKS:
        note("一度当てた行は控えのとおりに当て直します。")
    else:
        note("控えを捨てて当て直します。行ごとに選んだ装飾は消えます。")

    # 字幕から作ったトラックが在るかどうかで、作るのか当て直すのかが決まる。訊かない。
    if converted_track(timeline):
        note("%r トラックが在るので、本文を読み直して装飾を当て直します。" % CONVERTED_TRACK)
        note(action_restyle(resolve, forced))
        return
    note("%r トラックが無いので、字幕から作ります。" % CONVERTED_TRACK)
    note(action_convert(resolve, forced))


def guarded():
    """何が起きても、理由を Console と log file に残してから投げ直す。

    黙って終わると、どこまで進んだのかも分からない。ここで握りつぶさずに
    投げ直すのは、Resolve 側の表示にも出させるため。
    """
    try:
        if not RULES:
            # 画面が配る script は表を持っているので、そのときは読まない。
            # ここで読むのは、表が壊れていても記録が残るようにするため。
            note("装飾の表を読みます。")
            load_data()
            note("装飾の表を読みました（%d件）。" % len(RULES))
        main()
    except SystemExit:
        raise           # stop() が理由を名乗ってから来る道。二重に書かない
    except BaseException:
        note("落ちました:")
        note(traceback.format_exc())
        raise


guarded()
