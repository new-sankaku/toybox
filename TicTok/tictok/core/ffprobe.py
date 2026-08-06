"""ffprobeを起こす経路を1本にまとめる。

ffprobeは「すぐ返る軽い問い合わせ」に見えるが、**返らないことがある**。終端されていない
HLS playlist(``#EXT-X-ENDLIST`` の無い録画中のindex)を渡すとlive streamと見なして次の
segmentを永久に待ち、混んだdiskの上でのkeyframe全走査は分単位まで伸びる。

固まったときの被害は「そのprobeが遅い」では済まない。probeはどの経路でもframe loopの
**前**に置かれているので、そこで止まったjobは ``cancel.check_cancelled()`` に一度も触れ
られない。userが取り消しを押しても job は running のまま永久に残り、次のjobも詰まる。

よってこのmoduleを通る全てのprobeは

1. **timeoutを持つ** — 破れた約束(終端されていないplaylist)を黙って待ち続けるより、
   打ち切って失敗として扱う。
2. **走っているprocessを ``cancel`` へ登録する** — 取り消しがprobeへ直接届く唯一の道。

の両方を満たす。片方では足りない: timeoutだけでは取り消しが最大 ``DEFAULT_TIMEOUT_SECONDS``
のあいだ効かず、登録だけでは取り消しを押さない限り永久に待つ。

timeoutは例外にせず ``ProbeResult.returncode is None`` として返す。呼び出し側は既に
「exit codeが0でなければ測れなかった」という分岐を持っており、timeoutをそこへ合流させれば
経路が増えない。区別が要る側は ``timed_out`` を見る(3回まで再試行する走査は、timeoutを
再試行すると待ち時間が3倍になるので必ず見ること)。

``proc.ffprobe`` の計測もここで囲む。request contextの外ではContextVarがNoneで素通り
するので、囲む場所を1つにしても計測の意味は変わらない。
"""

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional

from tictok.core import cancel, perf

logger = logging.getLogger("tictok.ffprobe")

# 既定の上限。長尺HLSの全走査でも実測は数十秒で、ここへ触れるのは「返らなくなった」場合
# だけである。短くすると正常な長時間走査を落とす。
DEFAULT_TIMEOUT_SECONDS = 600.0
# 単一streamのheaderを読むだけの軽い問い合わせ向け。全走査を伴わないので長く待つ理由がない。
SHORT_TIMEOUT_SECONDS = 60.0
# HLS segment 1本ごとに払う問い合わせ向け。3時間の録画では5,000回を超えるので、1本あたりの
# 待ちは短くする(取りこぼしは呼び出し側が集計して1度だけ報告する)。
SEGMENT_TIMEOUT_SECONDS = 30.0


class ProbeResult(NamedTuple):
    """1回のprobeの結果。``returncode`` が ``None`` はtimeoutを表す。"""

    args: tuple
    returncode: Optional[int]
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def timed_out(self) -> bool:
        return self.returncode is None


def available() -> bool:
    return shutil.which("ffprobe") is not None


def _decode(raw) -> str:
    return (raw or b"").decode("utf-8", "replace")


def _log_timeout(args: list, timeout: float) -> None:
    logger.error(
        "ffprobeが %.0fs でtimeoutしました: %s", timeout, Path(args[-1]).name,
        extra={"event": "process.ffprobe_timeout",
               "ctx": {"cmd": " ".join(args), "timeout_seconds": timeout}},
    )


async def run(args, *, timeout: float = DEFAULT_TIMEOUT_SECONDS, cwd=None) -> ProbeResult:
    """ffprobeを1本走らせる。起動に失敗したときだけOSErrorを送出する。

    取り消しはprocessの登録と、走らせる前後の ``check_cancelled`` の両方で見る。登録だけ
    だとprobeの列(segmentごとに1本)が最後まで走り切ってしまい、取り消しが次のphaseまで
    届かない。"""
    args = [str(a) for a in args]
    cancel.check_cancelled()
    extra = {"cwd": str(cwd)} if cwd is not None else {}
    # awaitを跨ぐ区間なので ``phase`` ではなく ``timer``(perf側の使い分けを参照)。
    with perf.timer("proc.ffprobe"):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **extra,
        )
        cancel.register_process(proc)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            # killした子のpipeは読み切らないと閉じない。``wait`` だけで済ませると、途中で
            # 打ち切ったreadのtransportがGCまで残る(loopを跨ぐと閉じられずに例外を出す)。
            await proc.communicate()
            _log_timeout(args, timeout)
            return ProbeResult(tuple(args), None, "", "")
        finally:
            cancel.forget_process(proc)
    return ProbeResult(tuple(args), proc.returncode, _decode(out), _decode(err))


def run_sync(args, *, timeout: float = DEFAULT_TIMEOUT_SECONDS, cwd=None) -> ProbeResult:
    """``run`` の同期版。GPUに張り付いたblocking経路(Up出力・笑顔検出)から使う。

    ``subprocess.run`` ではなく ``Popen`` を直に使うのは、走っているprocess objectが要る
    ため — ``run`` は返るまでprocessを渡してくれないので、``cancel`` へ登録できない。"""
    args = [str(a) for a in args]
    cancel.check_cancelled()
    with perf.phase("proc.ffprobe"):
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=(str(cwd) if cwd is not None else None),
        )
        cancel.register_process(proc)
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            # killした子のpipeは読み切らないと閉じない。放置するとzombieとhandleが残る。
            proc.communicate()
            _log_timeout(args, timeout)
            return ProbeResult(tuple(args), None, "", "")
        finally:
            cancel.forget_process(proc)
    return ProbeResult(tuple(args), proc.returncode, _decode(out), _decode(err))


# ---------------------------------------------------------------------------
# 尺(duration)
# ---------------------------------------------------------------------------


def duration_args(path, input_args=()) -> list:
    """containerの尺を1行で吐かせるargv。

    出力形式を全経路で揃える。以前はjsonと素の1行が混在しており、同じ「尺を取る」処理が
    parse・error型・timeoutのどれも別々に3つ在った。"""
    return ["ffprobe", "-v", "error", *input_args, "-show_entries", "format=duration",
            "-of", "default=nokey=1:noprint_wrappers=1", str(path)]


def parse_duration(text: str) -> Optional[float]:
    """``duration_args`` の出力から秒を読む。読めなければNone。

    ``0`` や負値はそのまま返す。「読めなかった」と「0だった」は呼び出し側で意味が違う
    (前者はprobeの失敗、後者は素材の異常)ので、ここで同じNoneへ潰さない。"""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            return float(line)
        except ValueError:
            return None
    return None


async def duration_seconds(path, *, input_args=(),
                           timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Optional[float]:
    """containerの尺(秒)。測れなければNone。"""
    return parse_duration((await run(duration_args(path, input_args),
                                     timeout=timeout)).stdout)


def duration_seconds_sync(path, *, input_args=(),
                          timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Optional[float]:
    """``duration_seconds`` の同期版。"""
    return parse_duration(run_sync(duration_args(path, input_args),
                                   timeout=timeout).stdout)


# ---------------------------------------------------------------------------
# 解像度
# ---------------------------------------------------------------------------


def keyframe_resolution_args(path, input_args=()) -> list:
    """その素材に現れる解像度をkeyframe単位で吐かせるargv。

    ``stream=width,height`` を1組読む書き方をしてはいけない — 混在解像度の録画では、その
    1組は開いた所の値でしかなく全編を代表しない。解像度の変更は必ず新しいSPS(=keyframe)を
    伴うので、keyframeだけを読めば取りこぼさない。"""
    return ["ffprobe", "-v", "error", *input_args, "-select_streams", "v:0",
            "-skip_frame", "nokey", "-show_entries", "frame=width,height",
            "-of", "csv=p=0", str(path)]


def parse_resolution_csv(text: str) -> list:
    """``width,height`` 形式のcsvを (w, h) の出現順listにする(連続する重複は畳む)。

    先頭から数える。ffprobeのcsvは行によって末尾にseparatorを1つ余分に付けることがあり
    (実測: 同じfileでも1行目だけ ``160,120,`` で2行目は ``160,120``)、末尾から数えると
    その行だけ空文字をintに掛けて落ちる。落ちた行は「解像度不明」として扱われ、そのsegmentは
    束ねられずに隔離される — **失敗ではなく静かな取りこぼし**として現れるので、3段の検証も
    素通りする。

    種類だけが要る呼び出し側は ``set(...)`` で畳む。順序が要るのは束ね(hls_pack)だけだが、
    parseを2本持つと片方だけが実出力の癖に追随して静かに食い違う。"""
    seen: list = []
    for line in text.splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            wh = (int(parts[0]), int(parts[1]))
        except ValueError:
            continue
        if not seen or seen[-1] != wh:
            seen.append(wh)
    return seen
