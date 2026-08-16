"""作品へ効果音を置く。

## 置ける場所しか使わない

効果音が浮くのは、**時刻・種類・量・音量**のどれかを外したときである。このうち時刻は
「引き金の検出精度」でしか決まらず、そこを外すと演出ではなく事故に聞こえる。効果音が
「その瞬間に鳴った」と感じられるのは数十msの精度なので、引き金に使えるのは**既にミリ秒で
時刻が分かっているものだけ**である。

実測した検出の刻み:

===================  ==========
検出                 時間の刻み
===================  ==========
盛り上がり候補       10秒(bucket)
笑い声               1秒(窓2秒/hop 1秒)
笑顔                 60秒
===================  ==========

どれも音を置ける精度ではない。**笑いの山に効果音を置かないのはこの理由による** — 立ち上がり
(onset)を別に取り直すまでは引き金にしない。ここが使うのは次の3つで、いずれも検出ではなく
**構造から**時刻が決まる:

* **シーンの継ぎ目** … 連結が自分で作る時刻
* **テロップの出現** … 文字起こしsegmentの開始
* **ギフト着弾・Battleの開始終了** … eventの時刻

## 素材は条件で機械的に選んだ

「いくつか作って、どうですか」と聞く形は採らない。先に数値の条件を宣言し、満たさない候補は
**聴く前に落とす**。実際に52候補を測って16件しか通っていない(:data:`ACCEPTANCE`)。

落ちた内容にも意味がある。UI音として配られている ``LQ_interface`` の一群は、尺800〜1100ms・
スペクトル重心175〜670Hz — つまり**人の声の帯域そのもの**で、敷けば喋りが濁る。名前が
「interface」であることは、配信の上に乗せてよいことを意味しない。

当初は「peak <= -1dBFS」も条件にしていたが、これは**測る対象を間違えていた**。peakは増幅で
幾らでも動く量で、素材が壊れているかどうかとは別である。full scaleへ張り付いたsampleの
割合(クリップ)へ置き換えた。

## 音量は素材ごとに実測から決める

素材の大きさはばらばらなので、同じ ``volume`` を掛けると鳴る音の大きさが揃わない。実測した
peakから :data:`TARGET_PEAK_DB` までのgainをmanifestへ焼いてある。本編を下げる処理
(ducking)は入れない — 配信音声は源がHE-AAC 67kで既に痩せており、下げると聞こえなくなる。
"""

import asyncio
import hashlib
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tictok.core import cancel
from tictok.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

SFX_DIR = PROJECT_ROOT / "assets" / "sfx"

# 素材の出所。repo全体がCC0 1.0(権利放棄済み)で、帰属表示の義務が無い。義務のあるlicenceを
# 混ぜないのは、投稿のたびに表記が要る形になり、それを機械が保証できないためである。
SOURCE_REPO = "https://github.com/lavenderdotpet/CC0-Public-Domain-Sounds"
RAW_BASE = "https://raw.githubusercontent.com/lavenderdotpet/CC0-Public-Domain-Sounds/main/"

# 採用条件。**候補を聴く前に**これで落とす。数値の根拠:
#   尺   … 短すぎると気付かれず、長すぎると次のシーンへ被る
#   立上り… 鈍いと「その瞬間に鳴った」と感じない
#   重心 … 人の声(300Hz〜3.4kHz)の中心と主成分がぶつからないこと
#   clip … full scale張り付きが0.1%を超える素材は既に壊れている
ACCEPTANCE = {
    "transition": {"min_ms": 120, "max_ms": 400, "attack_ms": 30, "centroid_hz": 2000},
    "telop": {"min_ms": 40, "max_ms": 200, "attack_ms": 15, "centroid_hz": 1500},
    "gift": {"min_ms": 150, "max_ms": 600, "attack_ms": 30, "centroid_hz": 2500},
}
MAX_CLIPPED_RATIO = 0.001

# 効果音を鳴らす大きさ(peak)。本編より明らかに下へ置く。
TARGET_PEAK_DB = -18.0

# 同じ種類の音が連続するときの最短間隔。入れすぎが品質を落とす主因で、上限が無いと
# ギフトが連続した区間で音が重なって潰れる。
MIN_GAP_SECONDS = 1.5

# **違う種類**の音が近すぎるときに片方を落とす間隔。これより近いと2つが1つの濁った塊に
# しか聞こえない。
#
# これは理屈ではなく実測から入れた。シーンの頭は発話の開始へ吸着させるので、**継ぎ目の
# 時刻と、そのシーン最初のテロップの時刻は一致する** — 成果物を測ったら計画12箇所のうち
# 2組が同一msに重なっていた。例外ではなく、シーンが増えるだけ必ず起きる。
MIN_CROSS_GAP_SECONDS = 0.25

# 近すぎるときに残す方の優先順。継ぎ出しが最優先なのは、それが**構造の区切り**を示す音で、
# 消すと画面の切り替わりに何も鳴らない一方、テロップは他にもたくさん出るためである。
SLOT_PRIORITY = ("transition", "gift", "telop")

# 1本の作品へ置ける総数の上限。密度の指定を間違えたときに、成果物が鳴りっぱなしになるのを
# 防ぐ最後の関門(超えた分は捨て、捨てた数を報告する)。
MAX_CUES = 60


@dataclass(frozen=True)
class Asset:
    """1つの効果音。``gain_db`` は実測peakから :data:`TARGET_PEAK_DB` までの差。"""

    slot: str
    rel: str
    sha256: str
    seconds: float
    peak_db: float
    label: str

    @property
    def path(self) -> Path:
        return SFX_DIR / f"{self.slot}{Path(self.rel).suffix}"

    @property
    def gain_db(self) -> float:
        return round(TARGET_PEAK_DB - self.peak_db, 2)


# 実測(52候補中16件が通過)から選んだ採用分。数値はすべて実測値で、推測は1つも無い。
MANIFEST = {
    "transition": Asset(
        "transition", "Micro Pack - Organic Wooshes/Swish 4.wav",
        "c921df277edabd240329fdd0f2022ad4c5fb379f883cdeacec118fd7c37ef9ff",
        0.2004, -10.65, "シーンの継ぎ目（swish）"),
    "telop": Asset(
        "telop", "50-CC0-retro-synth-SFX/synth_beep_03.ogg",
        "e4a0dd2d8c3f4b8d02dd43774e1621ec4282398c7f14dabc2759e98e3390ce86",
        0.152, 0.52, "テロップの出現（beep）"),
    "gift": Asset(
        "gift", "MMRetroArcadeSoundsPack1_0_5/Misc/wav/Bell4.wav",
        "64ff7d1faacfdbcf6d1ada437f98be49f7aeaf01d0bfc93aa573f479d462c0d0",
        0.2009, -4.55, "ギフト着弾（bell）"),
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_assets(slots=None) -> dict:
    """必要な素材をassets/sfxへ揃える。既に在って指紋が合うものは触らない。

    取得できない・指紋が違う素材があれば **RuntimeError**。別の音で代替はしない — 焼き込みの
    fontと同じで、代替すると「同じ設定なのに機械ごとに違う音が鳴る」ことになる。指紋を見るのは、
    上流が同じpathで別の物を配り始めたときに黙って別の音を焼かないためである。
    """
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    ready: dict = {}
    for slot in (slots or MANIFEST):
        asset = MANIFEST[slot]
        path = asset.path
        if path.is_file() and _digest(path) == asset.sha256:
            ready[slot] = asset
            continue
        url = RAW_BASE + urllib.parse.quote(asset.rel)
        try:
            with urllib.request.urlopen(url, timeout=60) as res:
                payload = res.read()
        except OSError as exc:
            raise RuntimeError(
                f"効果音「{asset.label}」を取得できませんでした（{url}）: {exc}") from exc
        got = hashlib.sha256(payload).hexdigest()
        if got != asset.sha256:
            raise RuntimeError(
                f"効果音「{asset.label}」の内容が想定と違います（配布元が差し替えた可能性が"
                f"あります）。期待 {asset.sha256[:12]} / 実際 {got[:12]}")
        path.write_bytes(payload)
        logger.info("効果音を取得しました: %s（%s）", asset.label, path.name,
                    extra={"event": "sfx.fetched",
                           "ctx": {"slot": slot, "rel": asset.rel, "url": url,
                                   "bytes": len(payload)}})
        ready[slot] = asset
    return ready


def plan_cues(*, joints=(), telops=(), gifts=(), duration: Optional[float] = None) -> dict:
    """鳴らす時刻を決める。すべて**作品の時刻軸**(0起点)で受ける。

    引き金の時刻をここで検出しないのは、この関数が知り得ないためである — 継ぎ目は連結が、
    テロップは焼き込みが、ギフトはeventが持っている。ここがやるのは並べ替えと間引きだけ。

    間引きは2段。まず**種類ごと**に連続を落とし(:data:`MIN_GAP_SECONDS`)、次に**種類を跨いで**
    近すぎる組から優先度の低い方を落とす(:data:`MIN_CROSS_GAP_SECONDS`)。2段目が要るのは、
    継ぎ目とテロップが同一msへ重なるのが常態だからである(定数のdocstring)。
    """
    dropped = {"gap": 0, "cross": 0, "overflow": 0, "outside": 0}
    cues: list = []
    for slot, times in (("transition", joints), ("telop", telops), ("gift", gifts)):
        last = None
        for t in sorted(float(x) for x in times):
            if t < 0 or (duration is not None and t >= duration):
                # 素材の外で鳴らす指定は捨てる。ffmpegは黙って無視するので、数えないと
                # 「置いたつもりの音が無い」理由が誰にも分からなくなる。
                dropped["outside"] += 1
                continue
            if last is not None and t - last < MIN_GAP_SECONDS:
                dropped["gap"] += 1
                continue
            cues.append({"at": round(t, 3), "slot": slot})
            last = t
    # 優先度の高い順に置いていき、既に置いた音へ近すぎるものは捨てる。時刻順に見て
    # 「後から来た方を落とす」形にすると、継ぎ目が先に来るか後に来るかで結果が変わる。
    cues.sort(key=lambda c: (SLOT_PRIORITY.index(c["slot"]), c["at"]))
    kept: list = []
    for cue in cues:
        if any(abs(cue["at"] - other["at"]) < MIN_CROSS_GAP_SECONDS
               and other["slot"] != cue["slot"] for other in kept):
            dropped["cross"] += 1
            continue
        kept.append(cue)
    kept.sort(key=lambda c: c["at"])
    if len(kept) > MAX_CUES:
        dropped["overflow"] = len(kept) - MAX_CUES
        kept = kept[:MAX_CUES]
    return {"cues": kept, "dropped": dropped}


def remap_to_output(seconds: float, keeps) -> Optional[float]:
    """原本の時刻を、間を詰めた後の時刻へ写す。落とされた区間に居るなら None。

    ``keeps`` は :func:`tictok.media.tighten.plan_keeps` が返す残す区間の並び。詰めた後の
    位置は「その時刻より前に残っている長さの合計」なので、写し替えに推測は要らない。
    詰めていない(``keeps`` が空)なら、そのままが答えである。
    """
    if not keeps:
        return float(seconds)
    offset = 0.0
    for start, end in keeps:
        if seconds < start:
            return None
        if seconds < end:
            return round(offset + (seconds - start), 3)
        offset += end - start
    return None


def filter_complex(cues: list, assets: dict) -> str:
    """cueをffmpegのfilter_complexへ。入力は素材1種につき1つで、``asplit`` で分ける。

    cueの数だけ入力を開かないのは、1本の作品で数十回鳴るとffmpegのinput上限と
    command長に近づくためである。
    """
    used = [slot for slot in ("transition", "telop", "gift")
            if any(c["slot"] == slot for c in cues)]
    lines = []
    labels = []
    for index, slot in enumerate(used, start=1):
        picks = [c for c in cues if c["slot"] == slot]
        outs = [f"{slot}{i}" for i in range(len(picks))]
        if len(outs) == 1:
            lines.append(f"[{index}:a]asplit=1[{outs[0]}]")
        else:
            lines.append(f"[{index}:a]asplit={len(outs)}[" + "][".join(outs) + "]")
        for out, cue in zip(outs, picks):
            ms = int(round(cue["at"] * 1000))
            # adelayはchannelごとの指定。allで全chへ同じ遅延を掛ける(ch数を数えずに済む)。
            lines.append(
                f"[{out}]adelay={ms}:all=1,volume={assets[slot].gain_db}dB[{out}d]")
            labels.append(f"[{out}d]")
    # 本編を先頭に置く。normalize=0にしないと、入力数が増えるほど本編の音が小さくなる。
    # durationはfirst(=本編)。効果音が末尾を越えても作品を伸ばさない。
    lines.append("[0:a]" + "".join(labels)
                 + f"amix=inputs={len(labels) + 1}:normalize=0:duration=first[mix]")
    return ";".join(lines)


async def apply(src: Path, dst: Path, cues: list, assets: dict) -> dict:
    """効果音を混ぜて ``dst`` を作る。映像は複製のまま(再encodeしない)。

    最終段で掛ける。高画質化の前に混ぜると、あちらのencodeで音がもう1世代重なる。
    """
    if not cues:
        raise RuntimeError("鳴らす効果音がありません。")
    used = [slot for slot in ("transition", "telop", "gift")
            if any(c["slot"] == slot for c in cues)]
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src)]
    for slot in used:
        cmd += ["-i", str(assets[slot].path)]
    cmd += ["-filter_complex", filter_complex(cues, assets),
            "-map", "0:v", "-map", "[mix]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(dst)]
    cancel.check_cancelled()
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    cancel.register_process(proc)
    try:
        _, stderr = await proc.communicate()
    finally:
        cancel.forget_process(proc)
    cancel.check_cancelled()
    if proc.returncode != 0:
        detail = (stderr or b"").decode("utf-8", "replace").strip()
        logger.error("効果音の合成に失敗しました",
                     extra={"event": "sfx.mix_failed",
                            "ctx": {"src": str(src), "output": str(dst),
                                    "cues": len(cues), "stderr": detail[:2000]}})
        raise RuntimeError(f"効果音の合成に失敗しました: {detail[:300]}")
    counts = {slot: sum(1 for c in cues if c["slot"] == slot) for slot in used}
    logger.info("効果音を入れました: %s（%d箇所）", Path(dst).name, len(cues),
                extra={"event": "sfx.mixed",
                       "ctx": {"output": str(dst), "cues": len(cues), "counts": counts}})
    return {"cues": len(cues), "counts": counts}
