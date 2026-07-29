# 文字起こしを別processで走らせる理由

## 症状: serverがlogを1行も残さず消える

2026-07-26、serverが3回、いずれも同じ場所で落ちた。shutdown logもtracebackも無く、
process自体が消えていた。

```
14:49:38.262  loading upscale model ... device=cuda
14:49:38.371  upscale model ready
14:49:39      (以降なにも無い)
```

Windowsのイベントログにだけ記録が残っていた。3回とも同じfault bucketである。

```
Faulting module: venv\lib\site-packages\ctranslate2\cudnn64_9.dll (9.10.2.21)
Exception code : 0xc0000409   (fail-fast)
Fault offset   : 0x000000000001586d
```

## 原因: 1 processに cuDNN が3系統

WindowsはDLLを**名前1つにつき1個**しかprocessへ載せない。cuDNN 9はその1個
(`cudnn64_9.dll`, 0.3MB)が実体を持たない振り分け役で、実体は別fileにある。

| 提供元 | version | 中身 |
|---|---|---|
| `ctranslate2/` | 9.10.2.21 | **振り分け役だけ**(実体を持たない) |
| `torch/lib/` | 9.1.0.70 | 一式 |
| `nvidia/cudnn/bin/` | 9.23.2.1 | 一式 |

1. 文字起こし(faster-whisper = CTranslate2)が先に走り、9.10.2の振り分け役が居座る
2. 後から焼き込みのupscale(torch)がcuDNNを要求するが、名前は埋まっているので同じ
   振り分け役を掴む
3. その振り分け役はctranslate2の隣に実体を持たないので、torch側の9.1.0へ繋がる
4. 版の食い違った組で呼ばれたcuDNNが整合性checkに失敗し、`0xc0000409` でprocess即死

`0xc0000409` はpythonの例外ではなく**プロセスの即時停止**なので、try/exceptで拾えず、
logも書けない。「最後の行の直後に無言で消える」という落ち方はこれである。

**`gpu_slot` では防げない。** あれが直列化するのは実行であって、DLLの常駐ではない。
一度でも文字起こしが走ったprocessにはcuDNNが残り続けるので、順番を空けても衝突は消えない。

## 対処: 同居させない

復号は `tictok/record/stt_worker.py` の子processで行い、**serverにはCTranslate2を一切
読み込ませない**。版を揃える対処(ctranslate2同梱のDLLを外す)も考えられるが、それは
torchかctranslate2を1回上げるたびに再発する。同居させないことが唯一の恒久策である。

```
親(server) ... stt_worker.run_transcribe(path, on_progress)
                 GPU枠(gpu_slot)を押さえ、子を起こし、stdoutのJSONLを読む
子          ... python -m tictok.record.stt_worker <path>
                 transcription.transcribe() を実行する
```

**子の標準出力はJSONLの制御channel専用**で、logは標準errorへ出す(親が読んでserverの
logへ流す)。stdoutへlogを混ぜると結果を読めなくなる。

    {"t": "progress", "done": 秒, "total": 秒}
    {"t": "result",   "result": {...}}
    {"t": "error",    "message": "..."}

### 守るべき点

- **`transcription.transcribe` を直接呼ばない。** 1箇所でも直接呼ぶと、そのprocessへ
  CTranslate2が入って対処が無効になる。入口は `stt_worker.run_transcribe` だけ
  (queue経由・単発API `POST /api/recordings/{id}/transcribe` の両方)
- **GPU枠は親が持つ。** `gpu_slot` はprocess内のsemaphoreで、子で取っても焼き込みとは
  噛み合わない
- **stderrは必ず読み続ける。** pipe(既定64KB)が埋まると子が書き込みでblockし、復号が
  無言で止まる
- **停止時は子を落とす。** Windowsは親の終了で子を道連れにしない。`TranscribeQueue.stop`
  が `stt_worker.terminate_all()` を呼ぶ

## 副次的に直ったこと

- **子の死を必ず観測できる**。native crashは例外にならないが、終了codeとstderrは残るので、
  jobのerrorとして記録される(今までは無言で消えた)
- **復号中の取り消しが効く**(processをkillすれば止まる)
- **job毎にVRAMが解放される**。以前はwhisper modelがserverに常駐し、焼き込みと食い合った

## costは無視できる

model loadは実測3.6秒(`stt.model_loaded duration_ms=3578`)。1件あたりの復号は数分〜
十数分なので、job毎に子を立て直しても1%未満である。常駐させる必要はない。
