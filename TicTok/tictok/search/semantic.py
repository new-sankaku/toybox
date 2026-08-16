"""意味検索(dense retrieval)。search_hitsをpassageへ束ねて埋め込み、cos類似度で引く。

既存のsearch_scenesはtrigram FTSなので、語が一致しないと当たらない。ここでは
OpenAI互換の``/v1/embeddings``(Ollama / llama.cpp server / LM Studio)でvectorを作り、
語ではなく意味で近いsceneを返す。埋め込みserverの選定・endpoint・model名は全てconfig
(環境変数)経由で、hard-codeしない。

規約どおりfallbackは持たない。serverが無効・未設定・到達不能・次元不一致のときは
SemanticErrorを送出し、呼び出し側が「利用不可」として見せる。勝手にkeyword検索へ
落とすことはしない(意味検索の結果だと誤認されるため)。

== 行数を削減する設計 ==
search_hitsは現在約55,000行だが、全録画(5,195時間)を文字起こしすると約800万行になる。
1行ずつ埋め込むと768次元float32で約24GBになり、埋め込みcostも保存も破綻する。そこで
**同一recording・同一sourceの連続行をPASSAGE_SECONDS(既定25秒)の窓へ束ねてから**
埋め込む。文字起こしsegmentは1本あたり2-4秒なので概ね1/8前後まで落ち、5,195時間なら
18.7M秒 / 25秒 ≒ 75万passageになる。768次元float16なら約1.1GBで収まり、実測でも
brute-forceのcos計算が1秒未満で回る(下の「限界」を参照)。

束ねる単位をrecording+sourceで切るのは、passageが録画をまたぐと動画seek先が定まらない
ため。sourceを混ぜないのは、文字起こし(発話)とcomment(視聴者反応)で文体も語彙も別物で、
混ぜると片方の語がもう片方を薄めるだけになるため。

== 保存形式 ==
vectorは**生binary(``semantic_vectors.bin``)をnp.memmapで読む**。理由:
  - 生binary + memmap: 追記が``open(mode='ab')``だけで済む。.npyはheaderに形状を持つので
    追記のたびにheader書き換えが要る。memmapなのでprocess常駐分のRSSは増えず、検索時も
    chunk単位でしかRAMへ載らない。
  - 形状(次元)とdtypeはsidecar sqliteのmetaに持つ。生binaryは自己記述しないので必須。
  - dtypeの既定は**float32**。当初float16(容量半分)を選んだが、実測するとfloat16は
    BLASが直接扱えず、走査のたびfloat32へ起こす変換costが支配的だった:
        75万passage/768次元 -- float16 1,276ms vs float32 79ms (16倍)
        内訳(20万行あたり): f16->f32変換 302ms に対し dot積自体は 21ms
    容量は2.3GB vs 1.15GBだが、5,195時間の動画を抱えるprojectで1GBの差は誤差である一方、
    1.3秒の検索待ちはUIとして許容できない。容量が制約になる環境向けにdtypeはconfigで
    float16へ落とせる(TICTOK_SEMANTIC_DTYPE)。
== 秒はindexから返さない ==
passagesにもvideo_time/end_timeを持つが、これは**構築時のsnapshotであって回答ではない**。
文字起こしのやり直し(media軸への貼り直し)やcomment indexの張り直しでsearch_hits側の秒だけが
動くと、意味検索は古い軸を名乗り続ける。実測では331 groupのうち134 groupが取り残され、
中央値167秒・最大1,194秒(約20分)ずれていた。語で一致(search_scenes)はsearch_hitsを毎回読むので
無事で、意味検索だけがずれる — 症状が検索modeに依存するので原因が見えにくい。
そこで**位置はhit_id経由でsearch_hitsから都度引く**。indexが持つのは vector・本文・hit_idだけで、
時間軸の真実はDB側にしか無い。indexの秒はこのズレを検出する材料として残してある
(index_statusのstale判定)。

metadata(passage -> search_hitsのid群・時刻・unique_id)は**tictok.dbと同じdirectoryの
別sqlite file(``semantic_index.db``)**へ置く。tictok/storage.pyは他担当が編集中で触れない
ため自前permanenceを持つ必要があり、かつ別fileならindexの作り直しが本体DBに一切影響しない。

== 限界と、その先 ==
検索は総当たり(全passageとのdot積)。実測(float32 memmap, 768次元, page cache温間):
    10万passage(  694時間相当)  0.31GB   約 14ms
    75万passage(5,208時間相当)  2.30GB   約101ms   <- 全録画を文字起こしした場合の想定規模
   300万passage(2万時間相当)    9.22GB   約388ms
想定規模(75万)では総当たりで十分速く、ANNのindex構築cost・近似誤差・依存追加に見合わない。
**300万passage(=2万時間)を超えたあたりが総当たりの限界**で、そこからはANN
(hnswlib / faiss / sqlite-vec)へ移す。走査は``_scan_scores``へ閉じてあるので、公開APIを
変えずにこの関数の実装だけ差し替えれば済む。
"""

import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

import httpx
import numpy as np

from tictok.core import perf
from tictok.search.normalize import MentionNames, blank_mention

logger = logging.getLogger(__name__)


class SemanticError(RuntimeError):
    """意味検索が無効・未設定・到達不能、または埋め込み応答が不正なときに送出する。"""


# ===== 設定 =====
# TODO: ここのgetterはtictok/core/config.pyへ移す(他担当がconfig.pyを編集中のため、
# 一時的にmodule内に置いている)。移設時は名前をそのままconfig側へ移し、ここはimportに
# 差し替えるだけで済むよう、getterの外へ設定値を漏らさないこと。

def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def get_semantic_enabled() -> bool:
    return _env("TICTOK_SEMANTIC_ENABLED", "0").lower() in ("1", "true", "yes")


def get_semantic_base_url() -> str:
    """埋め込みserverのOpenAI互換base URL。未指定ならAI機能と同じserverを使う。"""
    explicit = _env("TICTOK_SEMANTIC_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    from tictok.core.config import get_ai_base_url

    return get_ai_base_url()


def get_semantic_model() -> str:
    """埋め込みmodel名。既定を持たない(chat modelを流用すると無言で精度が壊れるため)。"""
    return _env("TICTOK_SEMANTIC_MODEL")


def get_semantic_api_key() -> str:
    key = _env("TICTOK_SEMANTIC_API_KEY")
    if key:
        return key
    from tictok.core.config import get_ai_api_key

    return get_ai_api_key()


def get_semantic_timeout_seconds() -> float:
    return float(_env("TICTOK_SEMANTIC_TIMEOUT_SECONDS", "120"))


def get_semantic_batch_size() -> int:
    """1 requestへ載せるpassage数。大きいほど速いがserver側のVRAMを食う。"""
    return int(_env("TICTOK_SEMANTIC_BATCH_SIZE", "32"))


def get_semantic_passage_seconds() -> float:
    """passage1本が覆う動画時間の上限(秒)。"""
    return float(_env("TICTOK_SEMANTIC_PASSAGE_SECONDS", "25"))


def get_semantic_passage_max_chars() -> int:
    """passage1本の文字数上限。時間が短くてもcommentが密だと際限なく伸びるので併用する。"""
    return int(_env("TICTOK_SEMANTIC_PASSAGE_MAX_CHARS", "800"))


def get_semantic_query_prefix() -> str:
    """query側へ付ける指示prefix。model依存(例: EmbeddingGemmaは 'search_query: ')。
    既定は空。付けるべきかはmodelのcardに従うこと。"""
    return os.environ.get("TICTOK_SEMANTIC_QUERY_PREFIX", "")


def get_semantic_doc_prefix() -> str:
    """document側へ付ける指示prefix。query側と対で設定する(片方だけだと精度が落ちる)。"""
    return os.environ.get("TICTOK_SEMANTIC_DOC_PREFIX", "")


def get_semantic_dir() -> str:
    """indexの置き場。既定はtictok.dbと同じdirectory。"""
    explicit = _env("TICTOK_SEMANTIC_DIR")
    if explicit:
        return explicit
    from tictok.core.config import get_db_path

    return str(Path(get_db_path()).resolve().parent)


def get_semantic_scan_chunk() -> int:
    """総当たり走査でひとまとめにfloat32へ起こす行数。RAM上限とのtrade-off。"""
    return int(_env("TICTOK_SEMANTIC_SCAN_CHUNK", "200000"))


def get_semantic_dtype() -> str:
    """vectorの保存dtype。既定float32(検索が16倍速い)。容量優先ならfloat16。
    既存indexとの不一致はbuild/search時に検出して止める(混在すると類似度が壊れるため)。"""
    value = _env("TICTOK_SEMANTIC_DTYPE", "float32").lower()
    if value not in ("float32", "float16"):
        raise SemanticError(
            f"TICTOK_SEMANTIC_DTYPE は float32 か float16 のみ対応です（指定値: {value}）。"
        )
    return value


VECTOR_FILENAME = "semantic_vectors.bin"
META_FILENAME = "semantic_index.db"
SCHEMA_VERSION = 1


def vector_path() -> Path:
    return Path(get_semantic_dir()) / VECTOR_FILENAME


def meta_path() -> Path:
    return Path(get_semantic_dir()) / META_FILENAME


# ===== 埋め込みclient =====

class Embedder:
    """埋め込みの生成器。実装を差し替えられるようにprotocol代わりの基底を置く。

    ``embed(texts) -> np.ndarray[float32, (n, dim)]``。正規化はここでは行わず、
    呼び出し側(_normalize)で必ずL2正規化する(既に正規化済みのmodelでも冪等)。"""

    async def embed(self, texts: list) -> np.ndarray:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def name(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class HttpEmbedder(Embedder):
    """OpenAI互換の ``POST {base_url}/embeddings`` を叩く既定の実装。"""

    def __init__(self, base_url: str, model: str, api_key: str = "",
                 timeout: float = 120.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._model

    async def embed(self, texts: list) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        url = self._base_url + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {"model": self._model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("埋め込みendpointへ接続できません: %s", exc, exc_info=True)
            raise SemanticError(
                f"埋め込みエンドポイントへ接続できません（{self._base_url}）: {exc}"
            ) from exc
        if resp.status_code != 200:
            raise SemanticError(
                f"埋め込み応答エラー (HTTP {resp.status_code}): {resp.text[:300]}"
            )
        try:
            payload = resp.json()
            data = payload["data"]
        except (KeyError, ValueError) as exc:
            raise SemanticError(f"埋め込み応答の形式が不正です: {exc}") from exc
        if len(data) != len(texts):
            raise SemanticError(
                f"埋め込み件数が一致しません: 要求{len(texts)} 応答{len(data)}"
            )
        # OpenAI仕様ではdataのindexが入力順とは限らないので必ず並べ直す。
        try:
            data = sorted(data, key=lambda d: d.get("index", 0))
            vectors = [d["embedding"] for d in data]
        except (KeyError, TypeError) as exc:
            raise SemanticError(f"埋め込みvectorを取り出せません: {exc}") from exc
        try:
            arr = np.asarray(vectors, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise SemanticError(f"埋め込みvectorが数値配列になりません: {exc}") from exc
        if arr.ndim != 2 or arr.shape[0] != len(texts):
            raise SemanticError(f"埋め込みvectorの形状が不正です: {arr.shape}")
        return arr


_embedder_override: Optional[Embedder] = None


def set_embedder(embedder: Optional[Embedder]) -> None:
    """埋め込み生成器を差し替える。testで決定論的なfake embedderを注入するための口。
    Noneを渡すと既定のHTTP実装へ戻る。"""
    global _embedder_override
    _embedder_override = embedder


def get_embedder() -> Embedder:
    if _embedder_override is not None:
        return _embedder_override
    if not get_semantic_enabled():
        raise SemanticError("意味検索が無効です（TICTOK_SEMANTIC_ENABLED=1 を設定してください）。")
    model = get_semantic_model()
    if not model:
        raise SemanticError("埋め込みmodelが未設定です（TICTOK_SEMANTIC_MODEL を設定してください）。")
    return HttpEmbedder(get_semantic_base_url(), model, get_semantic_api_key(),
                        get_semantic_timeout_seconds())


def semantic_available() -> bool:
    """意味検索を試してよいか。到達性までは確認しない(接続testはbuild/search時に行う)。"""
    if _embedder_override is not None:
        return True
    return bool(get_semantic_enabled() and get_semantic_model())


# ===== index (sidecar sqlite + 生binary) =====

_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- passage 1行 = vector fileの1行(rowno = 0起点の行番号)。hit_idsはpassageへ束ねた
-- search_hits.idのJSON配列で、呼び出し側がsearch_hitsと突き合わせるための鍵。
CREATE TABLE IF NOT EXISTS passages (
    rowno INTEGER PRIMARY KEY,
    recording_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    session_id INTEGER,
    unique_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    video_time REAL NOT NULL,
    end_time REAL,
    hit_id INTEGER NOT NULL,
    hit_ids TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_passages_rec ON passages(recording_id, source);
CREATE INDEX IF NOT EXISTS idx_passages_uid ON passages(unique_id);
-- どのrecording/sourceを、search_hitsのどの状態で埋め込んだか。再buildの要否判定に使う。
CREATE TABLE IF NOT EXISTS indexed (
    recording_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    hit_count INTEGER NOT NULL,
    hit_max_id INTEGER NOT NULL,
    passage_count INTEGER NOT NULL,
    built_at REAL NOT NULL,
    PRIMARY KEY (recording_id, source)
);
"""

# buildだけが書き手なので、排他が要るのもbuild同士だけ。asyncio.Lockなのは build_index が
# 埋め込みの応答をawaitするため — ここでthreading.Lockを握るとevent loopのthreadごと止まり、
# build中のserver全体(検索・status・他のAPI)が応答不能になる。
#
# 読み手(search / index_status)はlockを取らない。vector fileは追記のみで、readerは先に
# rows_total(= file size)を確定させてから、それ未満のrownoだけを走査する。buildが並行して
# 追記しても、増えた行はrows_totalの外なので走査に入らない。これが読み取りの一貫性を保つ
# 不変条件で、lockはこれに何も足していなかった。
_build_lock = asyncio.Lock()


class SemanticBusy(SemanticError):
    """build実行中に再度buildを要求されたとき。

    待たせるのではなく即座に返す。10分待たされるより「走っている」と伝わる方が扱いやすく、
    userは待つか諦めるかを自分で選べる。"""


def _open_meta() -> sqlite3.Connection:
    path = meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_META_SCHEMA)
    conn.commit()
    return conn


def _get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def _normalize(arr: np.ndarray) -> np.ndarray:
    """L2正規化。以降のcos類似度をdot積1本で済ませるため、保存前に必ず通す。"""
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    # ゼロvectorはそのまま(0除算を避ける)。dot積は0になり、検索結果に浮かない。
    norms[norms == 0] = 1.0
    return arr / norms


def _dim(conn: sqlite3.Connection) -> Optional[int]:
    raw = _get_meta(conn, "dim")
    return int(raw) if raw else None


def _index_dtype(conn: sqlite3.Connection) -> str:
    """indexが実際に書かれているdtype。未記録(未構築)なら現在の設定値。"""
    return _get_meta(conn, "dtype") or get_semantic_dtype()


def _is_current(indexed_row, group: dict) -> bool:
    """そのgroupのindexが今のsearch_hitsを写しているか。

    件数と最大idで見る。search_hitsの張り直しは常に全行DELETE -> 再INSERTなので、
    行が入れ替われば必ずどちらかが動く(``replace_search_hits``)。逆に、秒だけをUPDATEする
    移行scriptではどちらも動かない — そちらは秒をDBから引き直すことで無害化してあるので、
    ここで検出する必要が無い(再埋め込みの対象は本文が変わったgroupだけでよい)。"""
    return (indexed_row["hit_count"] == group["n"]
            and indexed_row["hit_max_id"] == group["max_id"])


def _vector_rows(dim: int, dtype: str) -> int:
    path = vector_path()
    if not path.is_file() or dim <= 0:
        return 0
    return path.stat().st_size // (dim * np.dtype(dtype).itemsize)


# ===== passageへの束ね =====

def _flush_passage(group: list, names: Optional[MentionNames] = None) -> Optional[dict]:
    """束ねた行から passage を1つ作る。``body``は画面に出す形、``embed``は埋め込む形。

    分けてあるのは名前のため。誰の発言か・誰への返信かは画面では読めていなければ
    ならないが、埋め込みに混ぜると名前が語として効く(実測: commentのpassage本文の40.5%が
    話者名の繰り返しだった)。"""
    if not group:
        return None
    bodies = []
    embeds = []
    for row in group:
        nickname = row["nickname"]
        body = row["body"]
        # commentは話者が変わると意味も変わるので、誰の発言かをpassageへ残す。
        bodies.append(f"{nickname}: {body}" if nickname else body)
        stripped = blank_mention(body, names).lstrip()
        if stripped:
            embeds.append(stripped)
    if not embeds:
        # 宛先しか無いpassage(``@よい``だけの発言が並んだ窓)。埋め込む中身が無いものを
        # 空文字で埋め込むと、内容の無いvectorがどんな検索にも中途半端な近さで浮く。
        return None
    first = group[0]
    last = group[-1]
    end = last["end_time"] if last["end_time"] is not None else last["video_time"]
    return {
        "recording_id": first["recording_id"],
        "source": first["source"],
        "session_id": first["session_id"],
        "unique_id": first["unique_id"],
        "started_at": first["started_at"],
        "video_time": float(first["video_time"]),
        "end_time": float(end),
        "hit_id": int(first["id"]),
        "hit_ids": [int(r["id"]) for r in group],
        "body": "\n".join(bodies),
        "embed": "\n".join(embeds),
    }


def build_passages(rows: list, window_seconds: Optional[float] = None,
                   max_chars: Optional[int] = None,
                   names: Optional[MentionNames] = None) -> list:
    """search_hitsの行(同一recording/source、video_time昇順)をpassageへ束ねる。

    窓は「passage先頭からwindow_seconds以内」かつ「合計max_chars以内」で切る。時間だけで
    切るとcommentが殺到した瞬間に1 passageが巨大化してmodelのcontextを超え、文字数だけで
    切ると無音区間が1 passageへ融合して動画seek先が曖昧になるため、両方を見る。"""
    window = get_semantic_passage_seconds() if window_seconds is None else window_seconds
    limit = get_semantic_passage_max_chars() if max_chars is None else max_chars
    passages = []
    group: list = []
    group_chars = 0
    group_start = 0.0
    for row in rows:
        body = (row["body"] or "").strip()
        if not body:
            continue
        video_time = float(row["video_time"])
        if group and (video_time - group_start > window or group_chars + len(body) > limit):
            passage = _flush_passage(group, names)
            if passage:
                passages.append(passage)
            group, group_chars = [], 0
        if not group:
            group_start = video_time
        group.append(row)
        group_chars += len(body)
    passage = _flush_passage(group, names)
    if passage:
        passages.append(passage)
    return passages


# ===== index構築 =====

def _load_hits(storage, recording_id: int, source: str) -> list:
    return storage.search_hits_for(recording_id, source)


def _hit_groups(storage) -> list:
    return storage.search_hit_groups()


async def _embed_all(embedder: Embedder, texts: list, dim: Optional[int],
                     on_batch=None) -> tuple:
    """textsをbatchで埋め込み、正規化済みfloat32配列と次元を返す。"""
    batch_size = max(1, get_semantic_batch_size())
    out = []
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        arr = await embedder.embed(chunk)
        if dim is None:
            dim = int(arr.shape[1])
        elif arr.shape[1] != dim:
            # 次元が変わる = model差し替え。混在させると類似度が無意味になるので止める。
            raise SemanticError(
                f"埋め込み次元が既存indexと一致しません: index={dim} 応答={arr.shape[1]}。"
                " modelを戻すか、indexを作り直してください。"
            )
        out.append(_normalize(arr))
        if on_batch is not None:
            on_batch(len(chunk))
    if not out:
        return np.zeros((0, dim or 0), dtype=np.float32), dim
    return np.vstack(out), dim


def build_running() -> bool:
    """構築が走っているか。「受け付けました」を返す前の重複判定に使う。

    build_index自身も入口で同じ判定をしてSemanticBusyを投げるが、そちらはbackground
    taskの中で上がるためHTTPの応答には間に合わない。requestを弾くのはここ。"""
    return _build_lock.locked()


async def build_index(storage, on_progress: Optional[Callable] = None) -> dict:
    """search_hitsをpassageへ束ねて埋め込み、sidecar indexへ追記する。

    ``storage`` は Storage instance(読み取りのみ)。既にindex済みでsearch_hitsに変化が
    無いrecording/sourceはskipするので、再実行は差分だけになる。``on_progress`` は
    ``on_progress(dict)`` で呼ばれ、done/total/stage等を受け取る。"""
    embedder = get_embedder()
    started = time.time()

    def progress(**kwargs):
        if on_progress is not None:
            on_progress(kwargs)

    if _build_lock.locked():
        raise SemanticBusy("意味検索indexの構築が既に実行中です。完了までお待ちください。")

    async with _build_lock:
        conn = await asyncio.to_thread(_open_meta)
        try:
            _set_meta(conn, "schema_version", SCHEMA_VERSION)
            dim = _dim(conn)
            dtype = get_semantic_dtype()
            stored_dtype = _get_meta(conn, "dtype")
            if stored_dtype and stored_dtype != dtype:
                # dtypeが変わるとvector fileの行幅が変わり、既存行が読めなくなる。
                raise SemanticError(
                    f"index構築済みのdtype({stored_dtype})と現在の設定({dtype})が異なります。"
                    " 設定を戻すか、indexを削除して作り直してください。"
                )
            stored_model = _get_meta(conn, "model")
            if stored_model and stored_model != embedder.name:
                # 別modelのvectorと同じ空間で比較はできない。混ぜずに明示的に止める。
                raise SemanticError(
                    f"index構築済みのmodel({stored_model})と現在のmodel({embedder.name})が"
                    "異なります。indexを削除してから作り直してください。"
                )

            def _pending_groups() -> list:
                groups = _hit_groups(storage)
                done_rows = {
                    (row["recording_id"], row["source"]): row
                    for row in conn.execute("SELECT * FROM indexed").fetchall()
                }
                out = []
                for group in groups:
                    prev = done_rows.get((group["recording_id"], group["source"]))
                    if prev and _is_current(prev, group):
                        continue
                    out.append(group)
                return out

            # search_hitsの全groupを数える走査。件数に比例して伸びるのでloopから外す。
            pending = await asyncio.to_thread(_pending_groups)

            total_hits = sum(g["n"] for g in pending)
            progress(stage="start", groups=len(pending), hits=total_hits, done=0, total=total_hits)
            logger.info(
                "意味検索のindex作成を開始しました: groups=%d hits=%d model=%s",
                len(pending), total_hits, embedder.name,
                extra={"event": "search.semantic_build_start",
                       "ctx": {"groups": len(pending), "hits": total_hits,
                               "model": embedder.name}},
            )

            next_rowno = _vector_rows(dim, dtype) if dim else 0
            embedded_passages = 0
            embedded_hits = 0
            vector_file = vector_path()
            vector_file.parent.mkdir(parents=True, exist_ok=True)

            def _record_empty(recording_id: int, source: str, group: dict) -> None:
                conn.execute("DELETE FROM passages WHERE recording_id = ? AND source = ?",
                             (recording_id, source))
                conn.execute(
                    "INSERT INTO indexed (recording_id, source, hit_count, hit_max_id,"
                    " passage_count, built_at) VALUES (?, ?, ?, ?, 0, ?)"
                    " ON CONFLICT(recording_id, source) DO UPDATE SET"
                    " hit_count=excluded.hit_count, hit_max_id=excluded.hit_max_id,"
                    " passage_count=0, built_at=excluded.built_at",
                    (recording_id, source, group["n"], group["max_id"], time.time()),
                )
                conn.commit()

            def _write_group(recording_id: int, source: str, group: dict, passages: list,
                             vectors: np.ndarray, rowno: int, dim: int) -> None:
                """vectorの追記とmetadataの記録。file追記→INSERT→commitはこの順で不可分。

                追記が先なのは、readerがrows_total(file size)未満のrownoしか見ないため。
                逆順にすると、まだfileに無い行をmetadataが指す瞬間ができる。"""
                conn.execute("DELETE FROM passages WHERE recording_id = ? AND source = ?",
                             (recording_id, source))
                with open(vector_file, "ab") as handle:
                    handle.write(vectors.astype(dtype, copy=False).tobytes())
                conn.executemany(
                    "INSERT INTO passages (rowno, recording_id, source, session_id, unique_id,"
                    " started_at, video_time, end_time, hit_id, hit_ids, body)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (rowno + offset, p["recording_id"], p["source"], p["session_id"],
                         p["unique_id"], p["started_at"], p["video_time"], p["end_time"],
                         p["hit_id"], json.dumps(p["hit_ids"]), p["body"])
                        for offset, p in enumerate(passages)
                    ],
                )
                conn.execute(
                    "INSERT INTO indexed (recording_id, source, hit_count, hit_max_id,"
                    " passage_count, built_at) VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(recording_id, source) DO UPDATE SET"
                    " hit_count=excluded.hit_count, hit_max_id=excluded.hit_max_id,"
                    " passage_count=excluded.passage_count, built_at=excluded.built_at",
                    (recording_id, source, group["n"], group["max_id"], len(passages),
                     time.time()),
                )
                _set_meta(conn, "dim", dim)
                _set_meta(conn, "dtype", dtype)
                _set_meta(conn, "model", embedder.name)
                conn.commit()

            # 返信の宛先を埋め込みから外すための表示名。groupごとに引くと台帳の読み込みが
            # 録画の本数だけ走るので、buildの頭で一度だけ確定させる。
            names = await asyncio.to_thread(storage.mention_names)

            for group in pending:
                recording_id, source = group["recording_id"], group["source"]
                # sqliteもpassageの束ねもblocking。event loopで回すと、build中は検索も
                # 画面も止まる(まさにlockで起きていた問題を別経路で再現することになる)。
                rows = await asyncio.to_thread(_load_hits, storage, recording_id, source)
                passages = await asyncio.to_thread(build_passages, rows, None, None, names)
                if not passages:
                    await asyncio.to_thread(_record_empty, recording_id, source, group)
                    continue

                # 埋め込むのは名前を落とした側(p["embed"])。p["body"]は画面に出す形で、
                # 話者名と宛先を含む。
                texts = [get_semantic_doc_prefix() + p["embed"] for p in passages]
                # 進捗はhits単位(group跨ぎで比較できる唯一の尺度)。batchはpassage単位なので、
                # group内の消化率をそのgroupのhit数へ按分して滑らかな値にする。
                embedded_in_group = 0

                def on_batch(n: int, _total=len(passages), _hits=group["n"]) -> None:
                    nonlocal embedded_in_group
                    embedded_in_group += n
                    progress(stage="embed", total=total_hits,
                             done=embedded_hits + int(_hits * embedded_in_group / _total))

                vectors, dim = await _embed_all(embedder, texts, dim, on_batch=on_batch)

                # 旧passageは捨てて追記し直す。vector file側の旧行は参照されなくなるだけ
                # (穴が残る)。穴はrebuildで回収する方針で、追記の単純さを優先した。
                await asyncio.to_thread(_write_group, recording_id, source, group,
                                        passages, vectors, next_rowno, dim)
                next_rowno += len(passages)

                embedded_passages += len(passages)
                embedded_hits += group["n"]
                progress(stage="group_done", recording_id=recording_id, source=source,
                         passages=len(passages), done=embedded_hits, total=total_hits)

            elapsed = time.time() - started
            result = {
                "groups": len(pending),
                "hits": total_hits,
                "passages": embedded_passages,
                "dim": dim,
                "dtype": dtype,
                "model": embedder.name,
                "elapsed_seconds": round(elapsed, 2),
                "vector_bytes": vector_file.stat().st_size if vector_file.is_file() else 0,
            }
            logger.info(
                "意味検索のindex作成が完了しました: passages=%d hits=%d 所要 %.1fs model=%s",
                embedded_passages, total_hits, elapsed, embedder.name,
                extra={"event": "search.semantic_build_done", "ctx": result},
            )
            progress(stage="done", **result)
            return result
        finally:
            conn.close()


# ===== 検索 =====

def _scan_scores(vectors: np.memmap, query: np.ndarray, rownos: Optional[np.ndarray],
                 limit: int) -> tuple:
    """総当たりでcos類似度を出し、上位limit件の(rowno, score)を返す。

    vectorは保存時にL2正規化してあるのでdot積がそのままcos類似度。float16保存の場合は
    BLASが直接扱えないためchunkごとにfloat32へ起こす(この変換が支配的なので既定は
    float32保存。module docstringの実測を参照)。float32保存ならasarrayはno-copyで
    素通りする。ANNへ差し替えるときはこの関数だけを置き換えれば済む。"""
    chunk_size = max(1, get_semantic_scan_chunk())
    best_rownos: list = []
    best_scores: list = []
    if rownos is not None:
        # 絞り込みあり: 対象行だけをgatherして走査する。
        for start in range(0, len(rownos), chunk_size):
            idx = rownos[start : start + chunk_size]
            block = np.asarray(vectors[idx], dtype=np.float32)
            scores = block @ query
            best_rownos.append(idx)
            best_scores.append(scores)
    else:
        total = vectors.shape[0]
        for start in range(0, total, chunk_size):
            block = np.asarray(vectors[start : start + chunk_size], dtype=np.float32)
            scores = block @ query
            best_rownos.append(np.arange(start, start + len(block)))
            best_scores.append(scores)
    if not best_scores:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.float32)
    all_rownos = np.concatenate(best_rownos)
    all_scores = np.concatenate(best_scores)
    if limit < len(all_scores):
        top = np.argpartition(-all_scores, limit)[:limit]
    else:
        top = np.arange(len(all_scores))
    top = top[np.argsort(-all_scores[top])]
    return all_rownos[top], all_scores[top]


async def search(storage, query: str, limit: int = 50, unique_ids: Optional[list] = None,
                 sources: Optional[list] = None, since: Optional[float] = None,
                 until: Optional[float] = None) -> dict:
    """意味的に近いsceneを返す。``{"items": [...], "stale": 除外件数}``。

    itemsの各要素は search_hits の ``id`` と ``score`` を必ず持つ。passageは複数の
    search_hits行を束ねたものなので、``id`` はpassage先頭行のid、束ねた全idは
    ``hit_ids`` に入れてある(呼び出し側はどちらでもsearch_hitsと突き合わせられる)。

    **秒(video_time/end_time)は ``storage`` から引き直す**(理由はmodule docstring)。
    indexが指すsearch_hits行が既に無いpassageは、位置を名乗れないので結果から落とし、
    その件数を ``stale`` で返す。古い秒で返すより出さない方が良い — 数分ずれた場所へ飛ぶ
    結果は、無い結果より始末が悪い。``stale`` が立つのはindexの更新が要るときだけなので、
    呼び出し側はそれをuserへの案内に使う。

    ``sources``(stt/comment)・``since``/``until``(録画のstarted_at基準、keyword検索の
    search_scenesと同じ意味)はmetadata側で先に効かせる。総当たり走査の対象行がそのまま
    減るため、絞り込むほど検索は速くなる。``sources`` に空listを渡した場合は「どの種類も
    選ばれていない」であって全件ではないので、0件を返す。"""
    query = (query or "").strip()
    if not query:
        raise SemanticError("検索語を入力してください。")
    # 「1種類も選ばれていない」と「絞り込み無し」は別物。前者で全件を返すと、画面で
    # 種類checkを全部外したのに結果が出るという逆の挙動になる。
    if sources is not None and not sources:
        return {"items": [], "stale": 0}
    embedder = get_embedder()
    limit = max(1, int(limit))

    # buildと並行しても止めない。rows_totalを先に確定させ、それ未満のrownoしか触らないので、
    # 並行する追記は走査の外に出る(module冒頭の_build_lockの注記を参照)。
    def _prepare() -> tuple:
        conn = _open_meta()
        try:
            dim = _dim(conn)
            if not dim:
                raise SemanticError("意味検索のindexが未構築です。先にindexを作成してください。")
            # 読み出しはindexが実際に書かれたdtypeに従う(設定変更で行幅を誤読しないため)。
            dtype = _index_dtype(conn)
            stored_model = _get_meta(conn, "model")
            if stored_model and stored_model != embedder.name:
                raise SemanticError(
                    f"index構築済みのmodel({stored_model})と現在のmodel({embedder.name})が"
                    "異なります。indexを作り直してください。"
                )
            path = vector_path()
            if not path.is_file():
                raise SemanticError("意味検索のvector fileがありません。indexを作成してください。")
            rows_total = _vector_rows(dim, dtype)
            if rows_total == 0:
                raise SemanticError("意味検索のindexが空です。先にindexを作成してください。")

            # 絞り込みはmetadata側で先に効かせる。走査対象が減るほど検索は速くなる。
            clauses: list = []
            params: list = []
            if unique_ids:
                clauses.append("unique_id IN (%s)" % ",".join("?" * len(unique_ids)))
                params.extend(unique_ids)
            if sources:
                clauses.append("source IN (%s)" % ",".join("?" * len(sources)))
                params.extend(sources)
            if since is not None:
                clauses.append("started_at >= ?")
                params.append(since)
            if until is not None:
                clauses.append("started_at <= ?")
                params.append(until)
            rownos = None
            if clauses:
                picked = conn.execute(
                    "SELECT rowno FROM passages WHERE " + " AND ".join(clauses)
                    + " ORDER BY rowno",
                    params,
                ).fetchall()
                rownos = np.fromiter((r["rowno"] for r in picked), dtype=np.int64,
                                     count=len(picked))
                rownos = rownos[rownos < rows_total]
            return dim, dtype, path, rows_total, rownos
        finally:
            conn.close()

    dim, dtype, path, rows_total, rownos = await asyncio.to_thread(_prepare)
    if rownos is not None and len(rownos) == 0:
        return {"items": [], "stale": 0}

    # 埋め込みは外部のAI serverへのHTTP。走査(CPU)と足して1つにすると、遅い回の原因が
    # model側なのかindex走査なのか分けられない。
    with perf.timer("net.embed"):
        query_vec = await _embed_all(embedder, [get_semantic_query_prefix() + query], dim)
    vector = query_vec[0][0].astype(np.float32)

    def _scan() -> tuple:
        """memmapの走査もmetadataの引き当てもblocking。48k×768のdot積は今は一瞬でも、
        passage数に比例して伸びる — event loopに載せるとその分だけserverが固まる。"""
        started = time.time()
        with perf.phase("search.semantic_scan"):
            vectors = np.memmap(path, dtype=dtype, mode="r", shape=(rows_total, dim))
            # 削除されたpassageの穴(参照の無い行)も走査に混じるが、metadataに存在しない
            # rownoは下のSELECTで落ちるので結果には出ない。穴の分だけ多めに取る。
            fetch = (min(limit * 4, rows_total) if rownos is None
                     else min(limit * 4, len(rownos)))
            top_rownos, top_scores = _scan_scores(vectors, vector, rownos, max(fetch, limit))
        elapsed = time.time() - started

        score_by_rowno = {int(r): float(s) for r, s in zip(top_rownos, top_scores)}
        if not score_by_rowno:
            return {}, [], elapsed
        conn = _open_meta()
        try:
            placeholders = ",".join("?" * len(score_by_rowno))
            meta_rows = conn.execute(
                f"SELECT * FROM passages WHERE rowno IN ({placeholders})",
                list(score_by_rowno.keys()),
            ).fetchall()
        finally:
            conn.close()
        return score_by_rowno, meta_rows, elapsed

    score_by_rowno, meta_rows, elapsed = await asyncio.to_thread(_scan)
    if not score_by_rowno:
        return {"items": [], "stale": 0}

    # passageの端(先頭行と末尾行)のidだけを引く。中間行は本文がpassageに入っているので
    # 位置の決定には要らず、引く行数を結果数の2倍で頭打ちにできる。
    hit_spans = {}
    wanted: set = set()
    for row in meta_rows:
        ids = json.loads(row["hit_ids"])
        if not ids:
            continue
        hit_spans[row["rowno"]] = (int(ids[0]), int(ids[-1]))
        wanted.update(hit_spans[row["rowno"]])
    times = await asyncio.to_thread(storage.search_hit_times, sorted(wanted))

    items = []
    stale = 0
    for row in meta_rows:
        span = hit_spans.get(row["rowno"])
        head = times.get(span[0]) if span else None
        tail = times.get(span[1]) if span else None
        if head is None or tail is None:
            # indexが指す行が消えている = そのgroupは張り直された。今のindexは古い本文と
            # 古い秒しか持たないので、位置を名乗れない。indexを更新するまで出さない。
            stale += 1
            continue
        end = tail["end_time"] if tail["end_time"] is not None else tail["video_time"]
        items.append({
            "id": row["hit_id"],
            "score": round(score_by_rowno[row["rowno"]], 6),
            "hit_ids": json.loads(row["hit_ids"]),
            "source": row["source"],
            "recording_id": row["recording_id"],
            "session_id": row["session_id"],
            "unique_id": row["unique_id"],
            "started_at": row["started_at"],
            "video_time": head["video_time"],
            "end_time": end,
            "body": row["body"],
        })
    items.sort(key=lambda item: -item["score"])
    items = items[:limit]
    logger.info(
        "意味検索を実行しました: q_len=%d hits=%d 除外(index古い)=%d scan=%s 所要 %.3fs",
        len(query), len(items), stale, rows_total if rownos is None else len(rownos),
        elapsed,
        extra={"event": "search.semantic_query",
               "ctx": {"results": len(items), "stale": stale,
                       "scanned": rows_total if rownos is None
                       else int(len(rownos)), "elapsed_seconds": round(elapsed, 4)}},
    )
    return {"items": items, "stale": stale}


def index_status(storage=None) -> dict:
    """indexの現況。画面のbadge/構築ボタンの出し分け用。

    ``storage`` を渡すと「search_hitsが張り直されてindexが取り残されたgroup」と
    「一度もindexしていないgroup」も数える。userがindexの更新を押す動機は、押せるか否か
    ではなく**どれだけ検索から抜け落ちているか**なので、押せない理由と同じ場所で出す。"""
    status = {
        "available": semantic_available(),
        "enabled": get_semantic_enabled(),
        "model": get_semantic_model(),
        "base_url": get_semantic_base_url(),
        "dir": get_semantic_dir(),
        "built": False,
        "passages": 0,
        "recordings": 0,
        "dim": None,
        "dtype": None,
        "index_model": None,
        "vector_bytes": 0,
        "meta_bytes": 0,
        "last_built_at": None,
        # 画面がbuild中にbuttonを塞ぐための状態。これが無いと、userは押してみるまで
        # 実行中だと分からない。
        "building": _build_lock.locked(),
        "passage_seconds": get_semantic_passage_seconds(),
        # 検索に出せなくなっているpassage(index更新で戻る)と、まだindexしていないgroup。
        "stale_groups": 0,
        "stale_passages": 0,
        "unindexed_groups": 0,
    }
    path = meta_path()
    if not path.is_file():
        return status
    # 読み取りのみ。buildと並行しても、見えるのはcommit済みの断面になる。
    conn = _open_meta()
    try:
        status["dim"] = _dim(conn)
        status["dtype"] = _get_meta(conn, "dtype")
        status["index_model"] = _get_meta(conn, "model")
        row = conn.execute(
            "SELECT COUNT(*) AS n, COUNT(DISTINCT recording_id) AS recs FROM passages"
        ).fetchone()
        status["passages"] = row["n"]
        status["recordings"] = row["recs"]
        last = conn.execute("SELECT MAX(built_at) AS t FROM indexed").fetchone()
        status["last_built_at"] = last["t"]
        if storage is not None:
            groups = {(g["recording_id"], g["source"]): g
                      for g in storage.search_hit_groups()}
            counts = {(r["recording_id"], r["source"]): r["n"] for r in conn.execute(
                "SELECT recording_id, source, COUNT(*) AS n FROM passages"
                " GROUP BY recording_id, source")}
            indexed = set()
            for row in conn.execute("SELECT * FROM indexed"):
                key = (row["recording_id"], row["source"])
                indexed.add(key)
                group = groups.get(key)
                if group is None or _is_current(row, group):
                    continue
                status["stale_groups"] += 1
                status["stale_passages"] += counts.get(key, 0)
            status["unindexed_groups"] = len(set(groups) - indexed)
    finally:
        conn.close()
    vectors = vector_path()
    status["vector_bytes"] = vectors.stat().st_size if vectors.is_file() else 0
    status["meta_bytes"] = path.stat().st_size
    status["built"] = bool(status["passages"] and status["dim"])
    return status
