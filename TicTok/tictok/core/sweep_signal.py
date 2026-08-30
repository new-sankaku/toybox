"""確定した録画をsweepへ知らせる合図。

collectorとapi.startupは互いにimportできない(runtimeがcollectorをimportし、startupが
runtimeをimportする)ため、両方より下に居るここを置き場にする。

持つのは「録画がいつ終わったか」だけで、それがsweepの候補かどうかは決めない。静穏待ちも
ts結合待ちも失敗録画の除外も ``api.startup._sweep_candidates`` の1箇所に残す — ここで
一部でも判断すると、同じ規則が2箇所に分かれる。

これが無くてもsweepは定期の間隔で回る。合図が失われて困るのは**起きるのが早くなること**
だけで、録画そのものは次の周期と次回起動時のsweepが拾う。だからprocessが落ちれば中身も
消えてよく、DBにも残さない。
"""

from typing import Optional


# 溜め込む合図の上限。これを超えるのは、sweepが止まっている間に録画が確定し続けた場合で、
# そのときは古い合図から捨てる。捨てて失うのは起床の早さだけである。
MAX_PENDING = 256

_pending: list = []


def note_recording_finished(ended_at: float) -> None:
    """録画が1本確定した。``ended_at`` はepoch秒(``Recorder.ended_at``と同じ軸)。"""
    if not ended_at:
        return
    _pending.append(float(ended_at))
    if len(_pending) > MAX_PENDING:
        del _pending[:len(_pending) - MAX_PENDING]


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


def clear() -> None:
    """全部捨てる。testが前後の独立を保つために使う。"""
    _pending.clear()
