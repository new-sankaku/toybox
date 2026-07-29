# 静的解析 (ruff / mypy) と CI

Python code に対する lint (ruff)、型検査 (mypy)、GitHub Actions での CI の構成と運用。
設定の実体は repository root の `pyproject.toml` に集約している。

## 使い方

venv の python から module として起動する。

```bash
venv/Scripts/python.exe -m ruff check .          # lint
venv/Scripts/python.exe -m ruff check --fix .    # 自動修正できるものだけ直す
venv/Scripts/python.exe -m mypy                  # 型検査 (対象は pyproject.toml の files)
venv/Scripts/python.exe -m pytest -q             # test
```

Linux/macOS では `venv/bin/python`。tool の version は `requirements-dev.txt` で固定している。
ruff は minor 版で新 rule が既定に入りうるため上限を固定してある。version を上げるときは
意図的に上げ、その版で baseline を取り直すこと。

## ruff

### rule 選定の考え方

**実 bug を示す rule だけを選ぶ。** 整形のみの rule は採用しない。
formatter を導入していない現状では、整形 rule は diff を増やすだけで得るものが無く、
既存 code の慣習 (56,000 行) を一括で書き換える正当性も無いため。

有効にしている group:

| 選択 | 内容 |
| --- | --- |
| `E4` / `E7` / `E9` | pycodestyle の error。`E722` bare except、`E741` 紛らわしい変数名を含む |
| `F` | pyflakes。未定義名、未使用 import、未使用局所変数 |
| `B` | flake8-bugbear。bug になりやすい pattern |
| `ASYNC` | async 固有の落とし穴 |
| `LOG` | logging API の誤用 |
| `T20` | `print()` 禁止 (CLAUDE.md: Backend で print() は禁止) |
| `SIM115` | context manager 無しの `open()` = file handle leak |
| `RUF006` | `create_task` の戻り値を保持しない (task が GC で消える) |
| `RUF013` | 暗黙の Optional |

### 個別に無効化したもの と その理由

| rule | 理由 |
| --- | --- |
| `E501` (行長) | 既存 code に 120 超が 1,500 行以上ある。formatter 未導入で一括整形もできないため非選択。`line-length` の値は formatter 導入時のためだけに置いてある |
| `B007` | 未使用の loop 変数。命名の趣味の範囲で bug を示さない |
| `B008` | 引数 default での関数呼び出し。FastAPI の `Depends()` / `Query()` がまさにこの形 |
| `B904` | `raise ... from err`。except 節からの `HTTPException` 送出が定型で、`from` は冗長 |
| `B905` | `zip(strict=)`。検出力はあるが既存 37 箇所。後述の後追い対象 |
| `ASYNC221` / `ASYNC230` / `ASYNC240` | async 関数内の blocking 呼び出し。重い I/O を `to_thread` へ逃がす方針が既にあり、残りは意図的な同期呼び出し。一律警告は雑音になる |

採用を見送った group (参考: 現状の指摘件数):

- `UP` (608件、うち `UP045` = `Optional[X]` → `X | None` が 504件) — codebase 全体の書き換えになる
- `RUF001` / `RUF002` / `RUF003` (1,091件) — 全角文字を「紛らわしい unicode」と見なすもの。
  日本語 message を持つこの codebase では全件が誤検知
- `I` (isort、36 file) — import 並べ替え。自動修正できるが全 file に diff が出るため、
  他の作業と衝突しない時点でまとめて掛ける
- `C4` / `PIE` / `SIM` (`SIM115` を除く) / `RET` / `TRY` / `EM` / `FBT` / `ARG` — 整形・語彙の趣味

### per-file-ignores の 2 種類

`pyproject.toml` の `[tool.ruff.lint.per-file-ignores]` は 2 つの節に分かれている。

**恒久的な例外** (仕様上正しいもの。消さない)

- `scripts/*` の `T20` — 運用 CLI。標準出力が成果物そのものなので print が正しい
- `tictok/record/stt_worker.py` の `T20` — `python -m` で起動する子 process。
  stdout は親との制御 channel 専用のため usage は stderr へ print する
  (logger 未初期化の時点で出る必要がある)

**暫定 baseline** (直り次第その行を削る) — 後述の一覧を参照。

## mypy

### 段階導入の設計

56,000 行に一度に厳格な型を課すのは非現実的なので、**既定は全 module 検査・未達 module だけ
明示的に除外する ratchet 方式**にした。逆 (opt-in の allowlist) にしなかったのは、
allowlist 方式だと新規 module が既定で無検査になり、負債が増える側に倒れるため。

**Stage 1 (現在)**

`tictok/` 全体に以下を掛ける。annotation の追記は強制せず、既に書かれている型の矛盾だけを見る。

```
check_untyped_defs   = true   # annotation の無い関数の中身も検査する
no_implicit_optional = true
strict_equality      = true
warn_redundant_casts = true
warn_unused_ignores  = true
```

この水準を選んだ根拠: `check_untyped_defs` を含むこの組み合わせは、素の既定設定と比べて
error が 7 件しか増えず、error を持つ file 数は 27 で変わらなかった。
**annotation がほとんど無い codebase でも、追加 cost ほぼ無しで最も検出力が上がる水準**が
ここだったため。

現時点で通らない module は `[[tool.mypy.overrides]]` に列挙して `ignore_errors = true` にしてある。
**この一覧は増やさない。新規 module は既定で検査対象になる。**

**Stage 2 以降 (今後)**

1. `ignore_errors` の一覧を 1 module ずつ潰して削る。
   優先順位は「他 module から広く import される順」 — `tictok/core/*` → `tictok/store/*` →
   `tictok/collect` / `tictok/record` / `tictok/media`。中核ほど型が下流へ効くため。
2. 一覧が空になったら、leaf module から `disallow_untyped_defs` を有効化していく。
   (試算: `tictok/core/` の主要 5 module に今かけると 22 件の annotation 追記が要る)

### 対象範囲

- `tictok/` のみ。`scripts/` は一回限りの保守 CLI で、型検査の見返りが小さい割に
  除外一覧が 11 file 増えるため対象外 (ruff は掛かる)。`tests/` も慣例どおり対象外。
- `tictok.store.*` だけは module 単位ではなく package 単位で除外している。
  全 module が mixin として書かれており `self._conn` / `self.flush` / `self._lock` は
  合成先の class が持つ。mypy は mixin 単体では解決できず `attr-defined` が 559 件出るが、
  これは個別の code 不備ではない。**共有属性を宣言した Protocol を各 mixin の base に
  置けば package 全体が一度に通る**ので、その時点で entry ごと削除する。

### 第三者 library の扱い

型を持たない / optional な依存は `follow_imports = "skip"` で Any に固定している
(`TikTokLive` `fontTools` `torch` `spandrel` `onnxruntime` `faster_whisper` `ctranslate2` `nvidia` `playwright`)。

`ignore_missing_imports` だけでは不十分な理由: torch 等は開発機には install されているが
CI には無い。install の有無で mypy の結果が変わると、手元で通るのに CI で落ちる (逆も) が起きる。
`follow_imports = "skip"` は install されていても中身を追わないため、**両環境で結果が一致する。**

Pillow だけは例外で `ignore_missing_imports` のみ。常に install される実行時依存だが、
`py.typed` の同梱が version で変わる (10.2 は無し / 12.2 は有り)。同梱されていれば実型で
検査し、無ければ Any に落ちるだけで CI が赤くならない。`follow_imports = "skip"` を付けると
新しい Pillow でも型検査が効かなくなるため付けていない。

## CI

`.github/workflows/ci.yml`。`main` への push、全 pull request、手動実行で起動する。
同一 branch へ連続 push した場合は古い実行を打ち切る (`concurrency`)。

| job | OS | 内容 |
| --- | --- | --- |
| `lint` | ubuntu-latest / windows-latest | `ruff check` と `mypy` |
| `test` | ubuntu-latest / windows-latest | `pytest -q -m "not requires_torch"` |

Python は 3.10 (開発 venv と同じ)。`fail-fast: false` で片方の OS が落ちても
もう片方の結果が取れるようにしている。

**lint を両 OS で回す理由**: mypy は `sys.platform` の分岐を評価するため、片方の OS だけでは
他方でしか通らない code が未検査になる。ruff は OS 非依存だが、job 数を増やさず同じ matrix に載せている。

**ffmpeg を install する理由**: `requires_ffmpeg` marker が付いていないのに実際に
ffmpeg/ffprobe を起動する test が 11 件ある (後述)。marker での deselect だけでは
runner で落ちるため、Linux は apt、Windows は choco で実体を入れる。
marker が付いた test も CI で実行される。

**`requires_torch` を除外する理由**: GPU (CUDA) と torch/spandrel が要る。
これらは `requirements.txt` で opt-in 扱い (既定では未 install) なので runner では実行しない。
現在この marker が付いた test は 0 件だが、将来のために除外指定を入れてある。

## 後追いで直すべき指摘

### A. ruff の暫定 baseline

`pyproject.toml` の per-file-ignores 「暫定 baseline」節。直したらその行を削る。

| file | rule | 内容 |
| --- | --- | --- |
| `tictok/search/semantic.py:625` | `B023` | **loop 変数 `embedded_hits` を束縛していない関数定義。実 bug の可能性が高く最優先** |
| `tictok/record/video_overlay.py` (6箇所) | `SIM115` | context manager 無しの `open()` (file handle leak) |
| `tictok/record/recorder.py:1461` | `SIM115` | 同上 |
| `tictok/record/video_overlay.py:2403` | `F841` | 未使用の局所変数 `n_seg` |
| `tictok/record/video_overlay.py` (2箇所) | `F401` | 未使用 import (`typing.Awaitable`, `OVERLAY_PHASES`) |
| `tictok/core/config.py:5` | `F401` | 未使用 import (`pathlib.Path`) |
| `tictok/record/backups.py:17` | `F401` | 未使用 import (`typing.Optional`) |
| `tictok/record/hls_pack.py:25` | `F401` | 未使用 import (`shutil`) |
| `tictok/record/upscale.py:20` | `F401` | 未使用 import (`os`) |
| `tictok/media/avatar_proxy.py:153` | `E741` | 紛らわしい変数名 `l` |
| `scripts/normalize_mixed_resolution.py:54` | `RUF013` | 暗黙の Optional |
| `tests/test_record_misc.py:1131-1132` | `E741` | 紛らわしい変数名 `l` |
| `tests/test_server.py:12-14` | `E402` | 定数定義が import 群の間にあるため。定数を import の下へ移せば消える |
| `tests/test_perf.py:303` | `ASYNC251` | async 関数内の `time.sleep` |
| `tests/test_record_queue.py:826` | `B009` | 定数 attribute に対する `getattr` |
| `tests/test_migration.py:165` | `F541` | placeholder の無い f-string |

`F401` / `F841` / `F541` / `B009` は `ruff check --fix` で自動修正できる。
ただし **`--fix` を無条件に掛けないこと** — `scripts/battle_event_probe.py` の
`from tictok.collect import collector` のように、副作用目的で import しているものを
消してしまう例がある (この file は `# noqa: E402,F401` で明示済み)。

### B. marker が付いていない ffmpeg 依存 test (11件)

ffmpeg を PATH から外して実行して判明したもの。`requires_ffmpeg` marker が漏れている。
現状は CI に ffmpeg を install することで回避しているが、marker を付ければ
ffmpeg 無しの環境でも test を回せるようになる。

```
tests/test_ffprobe.py::test_a_cancel_reaches_a_probe_that_is_already_running
tests/test_ffprobe.py::test_a_cancel_reaches_a_running_sync_probe
tests/test_overlay.py::test_clip_render_refuses_when_nothing_would_be_drawn
tests/test_record_queue.py::test_normalize_reprobes_when_concat_left_no_resolutions
tests/test_server.py::test_pack_job_runs_on_the_session_dir_and_reports_progress
tests/test_server.py::test_pack_job_is_idempotent_for_material_that_is_already_packed
tests/test_server.py::test_pack_job_surfaces_the_reason_it_could_not_pack
tests/test_server.py::test_pack_job_refuses_when_the_volume_cannot_hold_a_second_copy
tests/test_server.py::test_pack_job_waits_while_another_job_holds_the_recording
tests/test_server.py::test_pack_job_stops_at_a_cancel_before_anything_is_written
tests/test_server.py::test_pack_job_does_not_cancel_after_the_work_is_done
```

### C. mypy 未達 module

`pyproject.toml` の `ignore_errors = true` の一覧が唯一の source。
昇格の優先順位は「mypy > 段階導入の設計」の項を参照。

### D. rule set を広げるときの候補

- `B905` (`zip(strict=)`、37箇所) — 長さ違いの silent 切り捨てを防ぐ。検出力は本物
- `I` (isort、36 file) — 自動修正のみ。他の作業と衝突しない時点でまとめて掛ける
- `RUF100` (未使用 noqa) — 現在の絞った rule set では、有効化していない rule に対する
  正当な `# noqa` まで「未使用」と判定されるため入れていない。rule set を広げた後に検討する

## 注意

- ruff / mypy の baseline は codebase の現状に対して取ったもの。大規模な refactor
  (package 分割など) の直後は、per-file-ignores と `ignore_errors` の一覧に
  実体を失った entry が残る。`pyproject.toml` から該当節を外して実行すれば、
  今も必要な entry だけを洗い出せる。
