"""確定した録画をsweepへ知らせる合図。

collectorとapi.startupは互いにimportできない(runtimeがcollectorをimportし、startupが
runtimeをimportする)ため、両方より下に居るここを置き場にする。

持つのは「録画がいつ終わったか」と「そのsegment dirへ書く者がもう居ないか」だけで、それが
sweepの候補かどうかは決めない。静穏待ちもts結合待ちも失敗録画の除外も
``api.startup._sweep_candidates`` の1箇所に残す — ここで一部でも判断すると、同じ規則が
2箇所に分かれる。

これが無くてもsweepは定期の間隔で回る。合図が失われて困るのは**起きるのが早くなること**
だけで、録画そのものは次の周期と次回起動時のsweepが拾う。だからprocessが落ちれば中身も
消えてよく、DBにも残さない。

2種類の合図:
  - 終了時刻(``_pending``): 静穏待ち(pack_sweep_quiet_minutes)が明けた時点で起こす。
  - 綺麗に終わったdir(``_clean``): serverが自分で捕捉ffmpegの終了を見届けた録画。その
    dirへ書く者は居ないので、静穏待ち(fileの更新時刻から「まだ書いている者が居ないか」を
    推定する代理)は要らず、確定直後にts結合の候補にできる。crash後の復旧や中断録画は
    serverが終了を見届けていないので、この合図を持たず従来の静穏待ちのまま。
"""

from pathlib import Path
from typing import Optional


MAX_PENDING = 256

_pending: list = []

# str(segment dir) -> [ended_at, woken]。wokenは「この合図でsweepを起こし済み」の印で、
# 起こした後も候補判定(is_clean)には使い続ける — 起こした回でpackを積めなかった(上限や
# 先客のjob)ときに次の回で拾うため。捨てるのは静穏待ちが明けた後(その先は従来の規則で
# 同じ答えになる)。
_clean: dict = {}


def _dir_key(hls_dir) -> str:
    return str(Path(hls_dir))


def note_recording_finished(ended_at: float, hls_dir=None) -> None:
    """録画が1本確定した。``ended_at`` はepoch秒(``Recorder.ended_at``と同じ軸)。

    ``hls_dir`` を渡すのは、serverが自分で捕捉ffmpegの終了を見届けた録画だけ。"""
    if not ended_at:
        return
    _pending.append(float(ended_at))
    if len(_pending) > MAX_PENDING:
        del _pending[:len(_pending) - MAX_PENDING]
    if hls_dir is not None:
        _clean[_dir_key(hls_dir)] = [float(ended_at), False]
        if len(_clean) > MAX_PENDING:
            for key in sorted(_clean, key=lambda k: _clean[k][0])[:len(_clean) - MAX_PENDING]:
                del _clean[key]


def earliest() -> Optional[float]:
    """未処理の合図のうち最も古い終了時刻。無ければNone。"""
    return min(_pending) if _pending else None


def consume(upto: float) -> int:
    """``upto`` 以前に終わった録画の合図を捨て、捨てた件数を返す。

    sweepを1回走らせたら全部捨てる、にはしない。静穏待ちが明けていない録画の合図まで消えると、
    その録画は「早く起きる」対象から外れて次の定期まで待つことになる — 合図を置いた意味が
    そこで消える。捨てるのは、もう候補として見られた(=静穏待ちが明けている)ぶんだけにする。"""
    before = len(_pending)
    _pending[:] = [at for at in _pending if at > upto]
    return before - len(_pending)


def is_clean(hls_dir) -> bool:
    """そのsegment dirの捕捉が、serverの見ている前で終わったか。"""
    return _dir_key(hls_dir) in _clean


def earliest_clean_unwoken() -> Optional[float]:
    """まだsweepを起こしていない「綺麗に終わった」合図のうち最も古い終了時刻。"""
    times = [at for at, woken in _clean.values() if not woken]
    return min(times) if times else None


def mark_clean_woken(upto: float) -> int:
    """``upto`` 以前に終わった「綺麗に終わった」合図を起こし済みにする。捨てはしない
    (候補判定には使い続ける)。"""
    n = 0
    for entry in _clean.values():
        if not entry[1] and entry[0] <= upto:
            entry[1] = True
            n += 1
    return n


def prune_clean(upto: float) -> int:
    """``upto`` 以前に終わった「綺麗に終わった」合図を捨てる。静穏待ちが明けた録画は
    従来の規則で同じ答えになるので、持ち続ける理由が無い。"""
    stale = [key for key, (at, _) in _clean.items() if at <= upto]
    for key in stale:
        del _clean[key]
    return len(stale)


def clear() -> None:
    """全部捨てる。testが前後の独立を保つために使う。"""
    _pending.clear()
    _clean.clear()
