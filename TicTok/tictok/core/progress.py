"""長時間jobの進捗を段階の重み付き和として1本の%へ畳む共通部品。

焼き込み・再mp4化・保持policy・意味検索indexは、どれも「重い前処理が数分〜数十分あって
から本処理が始まる」構造をしている。各jobが独自にpercentを組み立てると、段階の抜けや
%の巻き戻りが箇所ごとに再発するため、reporterをここへ一本化する。
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from tictok.core import config

logger = logging.getLogger("tictok.progress")

# 段階名つきの進捗を受け取るcallback。serverはこれをjob台帳とWSへ中継する。
StageCb = Callable[[int, str], Awaitable[None]]
# ffmpeg 1本ぶんの進捗。(0-100%, 出力位置us)。位置はJobProgressが残り時間の表示に使う。
ProgressCb = Callable[[int, Optional[int]], Awaitable[None]]


class IntervalGate:
    """時間間隔で進捗logを間引くgate。DEBUG時は progress_interval_seconds が0を返すため
    毎回通り、DEBUG指定が実際に情報量を増やす。"""

    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._last = 0.0

    def ready(self) -> bool:
        now = time.monotonic()
        if self._interval > 0 and now - self._last < self._interval:
            return False
        self._last = now
        return True


# 焼き込み1本の段階表: (key, 表示名, 重み)。重みは4.65時間の実録画での実測所要の比で、
# 合計1.0。走らない段階(commentが1件も無い / 既にCFR)は disable() で重みから外し、
# 残りを正規化する — 0%のまま残すと全体%がその重みぶん永久に到達しなくなる。
OVERLAY_PHASES: tuple = (
    ("probe", "動画を解析中", 0.02),
    ("plan", "描画レイアウトを計算中", 0.03),
    ("assets", "アイコン・絵文字を取得中", 0.03),
    # CFR baseは中間fileを作らず合成へstream供給されるようになった(video_overlay
    # _base_pipe_cmd)ので、独立した段階としては存在しない。重みはencodeが吸収する。
    ("layer", "コメント層を描画中", 0.27),
    ("layer_encode", "コメント層を書き出し中", 0.08),
    ("encode", "焼き込み合成中", 0.57),
)

# 再mp4化(元の.tsからのfinalize再実行)。concatは全segmentを1本のffmpegで通すので、
# 実時間の大半をここが占める。normalizeは混在解像度のときだけ走るので、均一なら
# disable("normalize")で重みから外す(外さないと典型ケースが60%で頭打ちになる)。
REPROCESS_PHASES: tuple = (
    ("concat", "セグメントを結合中", 0.55),
    ("timing", "時刻mapを再生成中", 0.05),
    ("normalize", "単一解像度へ変換中", 0.40),
)

# ts結合。解像度はsegmentごとにffprobeを起こすので走査が最も長く(3時間の録画で1〜2分)、
# byte連結はGB規模のcopyでその次に来る。以前はこの全体が「素材を結合中」1段階で、しかも
# %は5→60→100の3点しか動かなかった — 数千件のffprobeを回している最中がずっと5%で、
# 止まっているのか進んでいるのかを画面から区別できなかった。
PACK_PHASES: tuple = (
    ("probe", "segmentの解像度を判定中", 0.45),
    ("measure", "結合前の内容を計測中", 0.10),
    ("write", "素材を束ね書き込み中", 0.30),
    ("verify", "結合後の内容と照合中", 0.10),
    # ここから先は取り消せない(元segmentを消し始めた後で止めると、束ねたfileと元が
    # 半端に同居する)。段階として分けておくと、その境目が画面からも読める。
    ("commit", "元segmentを削除中", 0.05),
)

# 保持policyの実行。planの構築は全録画×全root の stat と 全 .sidecars の scandir で、
# 削除そのものより時間がかかることがある。
RETENTION_PHASES: tuple = (
    ("transient", "中断renderの残骸を削除中", 0.2),
    ("derived", "派生fileを削除中", 0.4),
    ("source", "原本を削除中", 0.4),
)

# プレビューは窓ぶんだけを同じ3 passで通す。probe/planは全尺でも軽いので1段階に畳む。
PREVIEW_PHASES: tuple = (
    ("plan", "プレビュー範囲を準備中", 0.05),
    ("layer", "コメント層を描画中", 0.30),
    ("layer_encode", "コメント層を書き出し中", 0.10),
    ("encode", "プレビューを焼き込み中", 0.55),
)


def fmt_hms(seconds: Optional[float]) -> str:
    """秒を h:mm:ss へ。進捗の残り時間・位置表示用。"""
    if seconds is None or seconds < 0:
        return "-"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def pump_progress_sync(stream, total_seconds: float, progress: Callable, key: str) -> None:
    """worker thread内でffmpegの ``-progress pipe:1`` を読み進め、達成率を報告する。

    asyncio版(_pump_ffmpeg_progress)はloop上でしか動かない。コメント層のqtrle書き出しは
    to_threadの中で走るため、同じthreadで同期的に読み進めるこちらを使う。"""
    gate = IntervalGate(config.get_job_progress_min_interval_seconds())
    last = -1
    for raw in stream:
        text = raw.decode("ascii", "replace").strip()
        if not text.startswith("out_time_us="):
            continue
        value = text.split("=", 1)[1]
        if not value.isdigit():
            continue
        pos = int(value) / 1_000_000
        pct = int(min(99, max(0, pos / total_seconds * 100))) if total_seconds > 0 else 0
        if pct == last and not gate.ready():
            continue
        last = pct
        progress(key, pct / 100.0, f"{fmt_hms(pos)} / {fmt_hms(total_seconds)}")


class JobProgress:
    """長時間jobの進捗を、段階の重み付き和として1本の%へ畳むreporter。

    焼き込みは「本encodeの前にコメント層描画とCFRベース生成が数十分走る」構造で、
    encodeのffmpeg進捗だけを流すと全体の半分近くが0%のまま無言になる。段階ごとの
    達成率を保持して合成することで、その無言区間を無くす。

    段階は**並列に進む**(コメント層はCPU、CFRベースはGPUで同時に走る)ため、「今どの
    段階か」という単一の状態ではなく段階ごとのfracを持つ。表示は進行中の段階を全て
    併記する。

    ``sink`` は ``await sink(pct, stage)``。%は単調非減少を保証する: 段階の増減や
    再試行で数字が戻ると、userには壊れたものとしてしか見えない。
    """

    def __init__(self, sink: Optional[StageCb], phases: tuple = OVERLAY_PHASES,
                 ceiling: int = 99) -> None:
        self._sink = sink
        self._order = [key for key, _label, _w in phases]
        self._labels = {key: label for key, label, _w in phases}
        self._weights = {key: weight for key, _label, weight in phases}
        self._enabled = set(self._order)
        self._frac: dict = {}
        self._detail: dict = {}
        # 100%はjobの完了(queueがfinishで書く)専用。段階が全て終わっても、成果物のcheckや
        # 後段(upscale)が残っている段階で100%と描くと「終わったのに終わらない」に見える。
        self._ceiling = ceiling
        self._span = (0.0, float(ceiling))
        self._last_pct = 0
        self._last_text = ""
        self._last_emit = 0.0
        self._max_step = 0
        self._started = time.monotonic()

    @property
    def active(self) -> bool:
        return self._sink is not None

    # ---- 段階構成 ----

    def disable(self, *keys: str) -> None:
        """走らないと確定した段階を重みから外す。"""
        for key in keys:
            self._enabled.discard(key)

    def span(self, index: int, total: int) -> None:
        """複数variant(Mode A / Mode B比較出力)を1本の%へ載せるための持ち分を設定する。

        A・Bは同じ段階列を最初から流し直すので、持ち分を切らないと%が 0→99→0→99 と
        往復し、「終わったのに巻き戻った」ようにしか見えない。B が結局走らなかった場合は
        前進方向へ飛ぶだけで済む。"""
        if total <= 1:
            self._span = (0.0, float(self._ceiling))
        else:
            width = self._ceiling / total
            self._span = (width * index, width * (index + 1))
        self._frac.clear()
        self._detail.clear()
        self._enabled = set(self._order)
        self._max_step = 0

    # ---- 進捗 ----

    def _pct(self) -> int:
        total = sum(self._weights[k] for k in self._enabled)
        if total <= 0:
            return self._last_pct
        acc = sum(self._weights[k] * self._frac.get(k, 0.0) for k in self._enabled)
        lo, hi = self._span
        return int(lo + (acc / total) * (hi - lo))

    def _text(self) -> str:
        enabled = [k for k in self._order if k in self._enabled]
        running = [k for k in enabled if 0.0 < self._frac.get(k, 0.0) < 1.0]
        if not running:
            # まだ動き出していない段階の先頭を出す。空にすると「準備中」へ戻って見える。
            pending = [k for k in enabled if self._frac.get(k, 0.0) <= 0.0]
            running = pending[:1] or enabled[-1:]
        # 段階番号は後戻りさせない。段階は並列かつ順不同に進む(アイコン取得はコメント層の
        # 前後に分かれて走る)ため、素直に「最初の進行中」を採ると (6/7)→(3/7) と逆行して
        # 見える。%が単調なのに番号だけ戻ると、userには壊れて見える。
        step = max(self._max_step, enabled.index(running[-1]) + 1)
        self._max_step = step
        parts = []
        for key in running:
            detail = self._detail.get(key)
            parts.append(f"{self._labels[key]}{f'（{detail}）' if detail else ''}")
        return f"({step}/{len(enabled)}) " + " ＋ ".join(parts)

    async def set(self, key: str, frac: float, detail: Optional[str] = None) -> None:
        """段階``key``の達成率(0.0-1.0)を更新して全体%を押し出す。"""
        if self._sink is None:
            return
        self._frac[key] = max(0.0, min(1.0, frac))
        if detail is not None:
            self._detail[key] = detail
        await self._emit()

    async def done(self, key: str, detail: Optional[str] = None) -> None:
        await self.set(key, 1.0, detail)

    async def finish(self, stage: str) -> None:
        """全段階の完了。走らなかった段階(比較出力を作らなかった等)が持ち分を残していても、
        ここで上限まで押し上げる。100%はjobの完了側が書く。"""
        if self._sink is None:
            return
        self._last_pct, self._last_text = self._ceiling, stage
        self._last_emit = time.monotonic()
        try:
            await self._sink(self._ceiling, stage)
        except Exception:
            logger.exception("jobの進捗sinkが失敗しました")

    async def _emit(self, force: bool = False) -> None:
        if self._sink is None:
            return
        pct = max(self._last_pct, self._pct())
        text = self._text()
        now = time.monotonic()
        if not force and pct == self._last_pct:
            # %が動いていない間も詳細(frame数・encode位置)は動き続ける。全部流すと1 jobで
            # 数万回のDB writeとbroadcastになるので、%据え置きの更新だけ時間で間引く。
            if text == self._last_text:
                return
            if now - self._last_emit < config.get_job_progress_min_interval_seconds():
                return
        self._last_pct, self._last_text, self._last_emit = pct, text, now
        try:
            await self._sink(pct, text)
        except Exception:
            logger.exception("jobの進捗sinkが失敗しました")

    # ---- callback adapter ----

    def cb(self, key: str, total_seconds: Optional[float] = None) -> ProgressCb:
        """ffmpegの進捗(0-100%と出力位置)を、この段階の達成率として取り込むadapter。

        ``total_seconds`` を渡すと「1:23:45 / 4:39:10」の位置表示が付く。1%刻みの%だけでは
        4.65時間の録画で1目盛が2.8分になり、動いているかの確認に使えない。"""
        async def _cb(pct: int, out_us: Optional[int] = None) -> None:
            detail = None
            if total_seconds:
                pos = (out_us / 1_000_000) if out_us is not None else total_seconds * pct / 100
                detail = f"{fmt_hms(pos)} / {fmt_hms(total_seconds)}"
            await self.set(key, pct / 100.0, detail)
        return _cb

    def thread_cb_multi(self, loop) -> Callable[[str, float, Optional[str]], None]:
        """worker threadから呼ぶための同期bridge。コメント層の描画はto_threadの中で回る
        ため、そのthreadから直接awaitはできない。段階keyは呼び出し側が渡す(1つのthreadが
        描画→書き出しと2段階を跨ぐ)。

        戻り値のfutureは待たない: 進捗の1回ぶんが落ちても描画は続けるべきで、待てば
        描画threadがloopの都合で止まる。"""
        def _cb(key: str, frac: float, detail: Optional[str] = None) -> None:
            if self._sink is None:
                return
            asyncio.run_coroutine_threadsafe(self.set(key, frac, detail), loop)
        return _cb


async def pump_ffmpeg_progress(stream, total_us: int, on_progress: ProgressCb,
                                base_us: int = 0) -> None:
    """Parse ffmpeg ``-progress pipe:1`` output and report 0-99% by elapsed
    ``out_time_us`` over the source duration. 100% is reserved for the download
    phase, so encode tops out at 99%.

    ``base_us`` is the output timestamp the encode starts from. It is 0 for a whole
    recording, but the burn-in preview keeps the source's absolute timestamps (-copyts)
    so its window starts at the window's own offset; without subtracting it the preview
    would report itself as already finished."""
    last = -1
    # ffmpegは out_time_us を毎秒前後で吐く。%据え置きの間の位置更新はここで間引く。
    now_gate = IntervalGate(config.get_job_progress_min_interval_seconds())
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("ascii", "replace").strip()
        if not text.startswith("out_time_us="):
            continue
        value = text.split("=", 1)[1]
        if not value.isdigit():
            continue
        out_us = int(value) - base_us
        pct = min(99, max(0, int(out_us * 100 / total_us)))
        # %が同じでも出力位置は進む。位置は残り時間の表示に使うので、%据え置きの間も
        # 渡す(間引きはJobProgress側の時間gateが行う)。
        if pct != last or now_gate.ready():
            last = pct
            try:
                await on_progress(pct, max(0, out_us))
            except Exception:
                logger.exception("コメント焼き込みの進捗callbackが失敗しました")
