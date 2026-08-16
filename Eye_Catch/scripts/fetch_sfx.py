"""CC0 の音源から必要な音だけを取り出して Eye_Catch/sfx/ へ整形出力する。

    python scripts/fetch_sfx.py

原本は残さず、頭出し・尺・fade・peak を揃えた 48kHz 16bit wav だけを置く。
出どころは VCSL（楽器・打楽器）と OpenGameArt の紙 foley の 2 つ。
"""

import array
import json
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import wave
from pathlib import Path

REPO = "sgossner/VCSL"
BRANCH = "master"
TREE_URL = "https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (REPO, BRANCH)
RAW = "https://raw.githubusercontent.com/%s/%s/" % (REPO, BRANCH)
RATE = 48000

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sfx"
CACHE = Path(tempfile.gettempdir()) / "eyecatch_sfx_cache"

# id, 探す語（すべて含む path が 1 本に定まること）, 尺, ch, 逆再生, 元の音高
INVENTORY = [
    ("hit_bassdrum_soft", ["/Bass Drum 1/", "BDrumNew_hit_v2_rr1"], 0.90, 1, 0, None),
    ("hit_bassdrum_hard", ["/Bass Drum 1/", "BDrumNew_hit_v7_rr1"], 1.10, 1, 0, None),
    ("hit_timpani",       ["/Timpani 1/", "Timpani1_Hit_v4_rr1"],   1.10, 1, 0, None),
    ("hit_anvil",         ["/Anvil/", "Anvil_Hit2_v3_rr1"],         0.90, 1, 0, None),
    ("hit_brakedrum",     ["/Brake Drum/", "BrakeDrum1_Hammer_v3_rr1"], 0.90, 1, 0, None),
    ("hit_woodblock",     ["/Woodblock/", "wood_click_ff"],         0.45, 1, 0, None),
    ("hit_logdrum",       ["/Slit Drum/", "LogDrumLo_MedM_v3_rr1"], 0.70, 1, 0, None),
    ("hit_framedrum",     ["/Frame Drum/", "HDrumL_Hit_v3_rr1"],    0.80, 1, 0, None),
    ("hit_tom",           ["/Tom 1/", "TomH_HitM_v4_rr1"],          0.70, 1, 0, None),
    ("hit_slapstick",     ["/Slapstick/", "slapstick_rr1"],         0.45, 1, 0, None),
    ("hit_marimba_low",   ["/Marimba/", "Marimba_hit_Outrigger_C2_loud_01"], 0.90, 1, 0, "C2"),

    ("air_cymbal_cresc",  ["/Suspended Cymbal 2/", "susCymb2_cresc_2.5s2"], 2.50, 2, 0, None),
    ("air_crash_rev",     ["/Clash Cymbals 1/", "cymbal_crash1_mf1"], 1.40, 2, 1, None),
    ("air_shaker_rev",    ["/Shaker, Small/", "Mid_Shaker_Roll_Fast_rr1"], 0.90, 1, 1, None),
    ("air_cabasa_rub",    ["/Cabasa/", "Cabasa1_Rub_v2_rr1"],       0.80, 1, 0, None),
    ("air_gong_rev",      ["/Gong 1/", "gong_mf"],                  2.00, 2, 1, None),

    ("deco_marimba",      ["/Marimba/", "Marimba_hit_Outrigger_C4_med_01"], 1.00, 1, 0, "C4"),
    ("deco_vibraphone",   ["/Vibraphone/", "Vibes_hard_C5_v2_rr1"], 1.60, 1, 0, "C5"),
    ("deco_kalimba",      ["/Kalimba, Kenya/", "MainSpirit_C#4_k2"], 1.20, 1, 0, "C#4"),
    ("deco_harp",         ["/Concert Harp/", "KSHarp_A4_mf1"],      1.50, 1, 0, "A4"),
    ("deco_balafon",      ["/Balafon/", "EthnicXylo_hardM_C4_vl2_rr1"], 0.90, 1, 0, "C4"),

    ("spark_windchime",   ["/Mark Trees/", "windchimes_asc1"],      2.00, 2, 0, None),
    ("spark_belltree",    ["/Bell Tree/", "BellTree_Stroke_3_Mid"], 1.80, 2, 0, None),
    ("spark_glockenspiel", ["/Glockenspiel/", "glock_loud_C7_01"],  1.20, 1, 0, "C7"),
    ("spark_triangle",    ["/Triangles/", "triangle2_hit_p.wav"],   1.80, 1, 0, None),
    ("spark_glass",       ["/Wine Glasses/", "glass4_D5_Fast_1_Main"], 1.40, 1, 0, "D5"),
    ("spark_tubularbell", ["/Tubular Bells 1/", "chimes_C4_p_rr1"], 2.00, 1, 0, "C4"),

    ("wipe_guiro",        ["/Guiro/", "guiro_long.wav"],            0.80, 1, 0, None),
    ("wipe_cabasa",       ["/Cabasa/", "Cabasa1_Rub_v1_rr1"],       0.70, 1, 0, None),
    ("wipe_shaker",       ["/Shaker, Small/", "Mid_Shaker_Roll_Fast_rr2"], 0.90, 1, 0, None),
    ("wipe_fingercymbal", ["/Finger Cymbals/", "Fing_Cymb"],        1.40, 1, 0, None),

    ("tick_woodblock",    ["/Woodblock/", "wood_click_mp.wav"],     0.28, 1, 0, None),
    ("tick_claves",       ["/Claves/", "claves_mf.wav"],            0.28, 1, 0, None),
    ("tick_cowbell",      ["/Cowbells/", "Cowbell1_Muted_v3_rr1"],  0.35, 1, 0, None),
    ("tick_agogo",        ["/Agogo Bells/", "Agogo_High_v2_rr1"],   0.45, 1, 0, None),

    ("flash_crash",       ["/Clash Cymbals 1/", "cymbal_crash1_short1"], 1.30, 2, 0, None),
    ("flash_suscymbal",   ["/Suspended Cymbal 2/", "susCymb2_hit_f1"], 1.60, 2, 0, None),
    ("flash_cymbalbell",  ["/Suspended Cymbal 2/", "susCymb2_hit_bell_f1"], 1.40, 2, 0, None),
    ("flash_triangle",    ["/Triangles/", "triangle1_hit_mp.wav"],  1.40, 1, 0, None),

    ("bed_oceandrum",     ["/Ocean Drum/", "OceanDrum_Sus_1_Mid"],  2.40, 2, 0, None),
    ("bed_gong",          ["/Gong 1/", "gong_p.wav"],               2.80, 2, 0, None),
    ("bed_glass",         ["/Wine Glasses/", "glass2_F#4_Slow_1_Main"], 2.40, 1, 0, "F#4"),

    ("exit_gong",         ["/Gong 1/", "gong_f.wav"],               2.80, 2, 0, None),
    ("exit_crash",        ["/Clash Cymbals 1/", "cymbal_crash1_ff3"], 2.40, 2, 0, None),
    ("exit_belltree",     ["/Bell Tree/", "BellTree_Stroke_10_Mid"], 2.20, 2, 0, None),
    ("exit_gongscrape",   ["/Gong 1/", "gong_scrape_mf"],           2.20, 2, 0, None),
]

LABELS = {
    "hit_bassdrum_soft": ("太鼓", "大太鼓の柔らかい一打"),
    "hit_bassdrum_hard": ("大太鼓", "大太鼓を強く叩く"),
    "hit_timpani": ("釜鼓", "釜型の太鼓。音程が残る"),
    "hit_anvil": ("鉄床", "金床を打つ硬い金属"),
    "hit_brakedrum": ("鉄輪", "鉄の輪を槌で叩く"),
    "hit_woodblock": ("木", "木片の乾いた当たり"),
    "hit_logdrum": ("木胴", "刳り貫いた木の胴"),
    "hit_framedrum": ("枠鼓", "枠張りの太鼓"),
    "hit_tom": ("筒鼓", "筒型の太鼓"),
    "hit_slapstick": ("拍子木", "板を打ち合わせる"),
    "hit_marimba_low": ("木琴低", "低い木琴の一音"),
    "hit_paper_crush": ("紙潰", "紙を握り潰す"),
    "hit_paper_rip": ("紙裂", "紙を裂く"),
    "air_cymbal_cresc": ("鈸増", "金物が膨らんで来る"),
    "air_crash_rev": ("逆合鈸", "合わせ鈸を逆に回す"),
    "air_shaker_rev": ("逆振", "振り物を逆に回す"),
    "air_cabasa_rub": ("擦粒", "玉を擦る"),
    "air_gong_rev": ("逆鑼", "銅鑼を逆に回す"),
    "air_paper_rev": ("逆紙", "紙を逆に回す"),
    "deco_marimba": ("木琴", "木琴の一音"),
    "deco_vibraphone": ("鉄琴", "金属板の柔らかい響き"),
    "deco_kalimba": ("親指琴", "指で弾く鉄片"),
    "deco_harp": ("竪琴", "弦を弾く"),
    "deco_balafon": ("瓢木琴", "瓢箪の付いた木琴"),
    "spark_windchime": ("風鈴", "細かい金属が連なる"),
    "spark_belltree": ("鈴段", "段状の鈴を撫でる"),
    "spark_glockenspiel": ("鉄琴高", "高い鉄琴の粒"),
    "spark_triangle": ("三角", "三角鉄の澄んだ余韻"),
    "spark_glass": ("硝子", "硝子の縁が鳴る"),
    "spark_tubularbell": ("管鐘", "管の鐘"),
    "wipe_guiro": ("刻擦", "刻みを擦る"),
    "wipe_cabasa": ("玉擦", "玉を擦る"),
    "wipe_shaker": ("振り", "振り物で掃く"),
    "wipe_fingercymbal": ("指鈸", "指の小鈸"),
    "wipe_paper": ("紙擦", "紙を擦る"),
    "wipe_paper_flip": ("紙捲", "紙を捲る"),
    "tick_woodblock": ("木打", "木の点"),
    "tick_claves": ("拍子", "拍子木の点"),
    "tick_cowbell": ("鈴打", "金属の点"),
    "tick_agogo": ("双鈴", "高い金属の点"),
    "flash_crash": ("合鈸", "合わせ鈸"),
    "flash_suscymbal": ("吊鈸", "吊り鈸を打つ"),
    "flash_cymbalbell": ("鈸芯", "鈸の中心を打つ"),
    "flash_triangle": ("三角光", "三角鉄の閃き"),
    "bed_oceandrum": ("波", "粒が転がる持続"),
    "bed_gong": ("鑼", "銅鑼の低い持続"),
    "bed_glass": ("硝子持", "硝子の持続"),
    "bed_paper": ("紙地", "紙の擦れが続く"),
    "exit_gong": ("鑼強", "銅鑼を強く打つ"),
    "exit_crash": ("合鈸強", "合わせ鈸を強く"),
    "exit_belltree": ("鈴流", "鈴を端から端まで"),
    "exit_gongscrape": ("鑼擦", "銅鑼を擦る"),
}

OGA = "https://opengameart.org/sites/default/files/"

# 紙は VCSL に無いので OpenGameArt から。id, file 名, 尺, ch, 逆再生
PAPER = [
    ("hit_paper_crush",  "paper_crushed_-_1.mp3", 0.60, 1, 0),
    ("hit_paper_rip",    "paper_ripped_-_1.mp3",  0.70, 1, 0),
    ("air_paper_rev",    "paper_sound_-_2.mp3",   0.80, 1, 1),
    ("wipe_paper",       "paper_sound_-_1.mp3",   0.70, 1, 0),
    ("wipe_paper_flip",  "paper_sound_-_4.mp3",   0.60, 1, 0),
    ("bed_paper",        "paper_sound_-_3.mp3",   1.60, 1, 0),
]

LICENSE_TEXT = """# Eye_Catch / sfx 素材の出どころ

いずれも **CC0 1.0 Universal (Public Domain Dedication)** です。表示義務・
使用料・再配布制限はありません。この file は出どころを辿れるようにする記録です。

## 楽器・打楽器（`hit_* air_* deco_* spark_* wipe_* tick_* flash_* bed_* exit_*`）

- **Versilian Community Sample Library (VCSL)** — Versilian Studios LLC
- https://github.com/sgossner/VCSL — branch `%s`

## 紙（`*_paper*`）

- **Various Paper Sound Effects** — Luckius
- https://opengameart.org/content/various-paper-sound-effects

## 原本からの加工内容（`scripts/fetch_sfx.py`）

頭の無音を落とす / 尺を切る / 末尾 fade / 48kHz 16bit へ変換 / peak を 0.97 へ揃える
""" % BRANCH


def fetch_tree():
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / "tree.json"
    if not p.exists():
        with urllib.request.urlopen(TREE_URL, timeout=120) as r:
            p.write_bytes(r.read())
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("truncated"):
        raise RuntimeError("tree が truncated。取得方法を変える必要があります")
    return [x["path"] for x in d["tree"] if x["type"] == "blob"]


def resolve(paths, words):
    hit = [p for p in paths if all(w in p for w in words)]
    if len(hit) != 1:
        raise RuntimeError("%s に一致する path が %d 本: %s" % (words, len(hit), hit[:5]))
    return hit[0]


def download(url, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    dst = CACHE / name.replace("/", "__")
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    req = urllib.request.Request(url, headers={"User-Agent": "eyecatch-fetch-sfx"})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    dst.write_bytes(data)
    return dst


def decode(src, ch):
    cmd = ["ffmpeg", "-v", "error", "-i", str(src), "-ac", str(ch),
           "-ar", str(RATE), "-f", "f32le", "-"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg 失敗: %s\n%s" % (src, p.stderr.decode("utf-8", "replace")))
    a = array.array("f")
    a.frombytes(p.stdout)
    if sys.byteorder == "big":
        a.byteswap()
    return a


def process(a, ch, dur, rev):
    n = len(a) // ch
    if rev:
        out = array.array("f", bytes(len(a) * 4))
        for i in range(n):
            j = n - 1 - i
            for c in range(ch):
                out[i * ch + c] = a[j * ch + c]
        a = out

    peak = max(abs(v) for v in a)
    if peak < 1e-6:
        raise RuntimeError("無音です")

    # 本当の無音だけを落とす。立ち上がりが緩い swell を削らないよう床は低く取る
    floor = max(peak * 0.004, 3e-5)
    start = 0
    for i in range(n):
        if max(abs(a[i * ch + c]) for c in range(ch)) > floor:
            start = max(0, i - int(RATE * 0.003))
            break

    end = min(n, start + int(RATE * dur))
    a = a[start * ch:end * ch]
    m = len(a) // ch
    if m < 16:
        raise RuntimeError("切り出し後が短すぎます")

    fi = min(int(RATE * 0.002), m // 4)
    fo = min(int(RATE * 0.030), m // 3)
    for i in range(fi):
        g = i / fi
        for c in range(ch):
            a[i * ch + c] *= g
    for i in range(fo):
        g = i / fo
        k = m - 1 - i
        for c in range(ch):
            a[k * ch + c] *= g

    peak = max(abs(v) for v in a) or 1.0
    k = 0.97 / peak
    out = array.array("h", bytes(len(a) * 2))
    for i in range(len(a)):
        v = int(a[i] * k * 32767)
        out[i] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
    return out


def emit(sid, src, ch, dur, rev, note, lib, origin, entries):
    a = process(decode(src, ch), ch, dur, rev)
    dst = OUT / (sid + ".wav")
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(a.tobytes())
    size = dst.stat().st_size
    entries.append({
        "id": sid, "file": sid + ".wav", "ch": ch, "rate": RATE,
        "dur": round(len(a) / ch / RATE, 4), "note": note,
        "reversed": bool(rev), "lib": lib, "source": origin,
        "text": LABELS[sid][0], "title": LABELS[sid][1],
    })
    print("%-22s %6.2fs %5dKB  %s" % (sid, len(a) / ch / RATE, size // 1024, origin))
    return size


def main():
    paths = fetch_tree()
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    total = 0
    for (sid, words, dur, ch, rev, note) in INVENTORY:
        origin = resolve(paths, words)
        src = download(RAW + urllib.parse.quote(origin), origin)
        total += emit(sid, src, ch, dur, rev, note, "VCSL", origin, entries)

    for (sid, name, dur, ch, rev) in PAPER:
        src = download(OGA + urllib.parse.quote(name), name)
        total += emit(sid, src, ch, dur, rev, None, "OGA-Luckius", name, entries)

    (OUT / "manifest.json").write_text(json.dumps({
        "license": "CC0-1.0",
        "libraries": {
            "VCSL": "https://github.com/%s" % REPO,
            "OGA-Luckius": "https://opengameart.org/content/various-paper-sound-effects",
        },
        "rate": RATE, "samples": entries,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "LICENSE.md").write_text(LICENSE_TEXT, encoding="utf-8")
    print("\n%d 本 / 合計 %.1fMB  -> %s" % (len(entries), total / 1e6, OUT))


if __name__ == "__main__":
    main()
