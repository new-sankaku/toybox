"""BGM除去を実行する子process。**別のvenvのpythonが、file pathで直接起動する。**

このfileは ``tictok`` を一切importしてはならない。動かすのはBGM除去用venvのpython
(``TICTOK_BGM_REMOVE_PYTHON``)で、そこにはtorchとclearvoiceしか入っていないためである。
親は :mod:`tictok.record.bgm_remove` 側に居る。

== なぜ別processなのか ==

3つとも実測で確かめた事情がある。

1. clearvoiceはtorchを**CPU版で上書きする**。本体venvへ入れるとUp出力(torch cu124)が
   GPUを失う。versionを揃え直しても、次のpip installでまた倒れる
2. 文字起こし(faster-whisper = CTranslate2)と同processに置けない。cuDNNの版が食い違う
   組で呼ばれるとprocessごとfail-fastで即死する(doc/STT_PROCESS_ISOLATION.md)
3. 子の死は親が終了codeとstderrで必ず観測できる。job毎にVRAMも必ず解放される

model loadは実測2.4〜3.0秒で、1件あたりの処理(60秒のclipで約6秒)に対して常駐させる
ほどの比率ではない。

== 親子の約束 ==

**標準出力はJSONLの制御channel専用**で、1行1 message:

    {"t": "result", "result": {"samples": 2880000, "seconds": 60.0}}
    {"t": "error",  "message": "...", "bgm": true}

logは標準errorへ出す。stdoutへ混ぜると制御channelが壊れて結果を読めなくなる。

== 出力の約束 ==

**入力と同じsample rate・同じsample数のmono wavを書く。** modelは48kHzのmonoしか
受け取らないので、入力もそれで渡す(親が変換する)。sample数がずれた出力を出力経路へ
流すと、焼き込みのcomment位置と同じ形で時刻が後ろへゆくほどずれる。ここで必ず揃える。
"""

import argparse
import contextlib
import json
import sys
import wave

import numpy as np


def emit(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def read_mono(path: str) -> tuple:
    with wave.open(path, "rb") as wav:
        if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
            raise ValueError(
                f"入力は16bit monoのwavである必要があります "
                f"(sampwidth={wav.getsampwidth()}, channels={wav.getnchannels()})")
        rate = wav.getframerate()
        frames = wav.getnframes()
        raw = wav.readframes(frames)
    return np.frombuffer(raw, dtype="<i2"), rate, frames


def write_mono(path: str, samples, rate: int, frames: int) -> None:
    mono = np.asarray(samples, dtype=np.float64).reshape(-1)
    peak = float(np.abs(mono).max()) if mono.size else 0.0
    if peak > 1.0:
        mono = mono / peak
    if len(mono) > frames:
        mono = mono[:frames]
    elif len(mono) < frames:
        mono = np.concatenate([mono, np.zeros(frames - len(mono))])
    pcm = np.clip(np.round(mono * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--model", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    try:
        import torch
        from clearvoice import ClearVoice
    except ImportError as exc:
        emit({"t": "error", "bgm": True,
              "message": f"BGM除去用venvにtorch/clearvoiceがありません: {exc}"})
        return 2

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        emit({"t": "error", "bgm": True,
              "message": "CUDAを使う設定ですがGPUを認識できません。"})
        return 2
    if device == "cpu":
        # CPUは実測で数十倍遅く、待てる時間で終わらない。黙って遅い経路へ倒さない。
        emit({"t": "error", "bgm": True,
              "message": "BGM除去はGPUが必要です(CPUでは実用速度になりません)。"})
        return 2

    try:
        samples, rate, frames = read_mono(args.input)
        print(f"BGM除去を開始します: {frames / rate:.1f}秒 {rate}Hz model={args.model}",
              file=sys.stderr, flush=True)
        # clearvoiceは進捗と状態を標準出力へ書く。**制御channelはJSONL専用**なので、
        # library側の出力はまとめて標準errorへ寄せる(親のlogには出る)。ここを外すと
        # 親は毎回「JSON以外の行」を警告しながら読み飛ばすことになる。
        with contextlib.redirect_stdout(sys.stderr):
            engine = ClearVoice(task=args.task, model_names=[args.model])
            result = engine(input_path=args.input, online_write=False)
        if isinstance(result, dict):
            result = next(iter(result.values()))
        write_mono(args.output, result, rate, frames)
    except Exception as exc:  # 子の失敗は必ず制御channelへ載せる(親はstderrも読む)
        import traceback
        traceback.print_exc(file=sys.stderr)
        emit({"t": "error", "bgm": True, "message": f"BGM除去に失敗しました: {exc}"})
        return 1

    emit({"t": "result", "result": {"samples": int(frames), "rate": int(rate),
                                    "seconds": frames / float(rate),
                                    "model": args.model, "task": args.task}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
