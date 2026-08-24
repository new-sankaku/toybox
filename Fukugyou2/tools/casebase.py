#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事例 record の schema と、共通の入出力。

tools/ の各 program はこの module のみを共有し、互いには依存しません。
doc/METHOD.md §5 の規律を code 側で強制します。

  - 取得日を record と file 名の両方に刻む
  - 生 response を log/raw/ に そのまま残す
  - 取得に失敗しても代替値で埋めない。失敗として記録し、全滅なら落とす
  - 全走査しない。--limit を超える入力は明示的な引き上げを要求する
  - 平均を出さない。分布（p25 / 中央値 / p75）で出す
"""
from __future__ import annotations

import datetime
import email.utils
import glob
import html
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Fukugyou2-case-research/1.0 (+https://github.com/new-sankaku/toybox Fukugyou2/doc/SOURCES.md)"

CASE_FIELDS = (
    "case_id", "source", "source_id", "kind", "title", "product_name", "tagline",
    "url", "discussion_url", "points", "num_comments", "created_at", "author",
    "story_text", "query", "fetched_on",
)


class SourceError(RuntimeError):
    """情報源からの取得に失敗した。呼び出し側は握り潰さず、失敗として記録すること。"""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def path(*parts) -> str:
    return os.path.join(ROOT, *parts)


def today() -> datetime.date:
    return datetime.date.today()


def stamp(d: datetime.date | None = None) -> str:
    return (d or today()).strftime("%Y%m%d")


def load_yaml(file_path: str) -> dict:
    try:
        import yaml
    except ImportError:
        raise SystemExit("PyYAML が必要です。`pip install -r requirements.txt` を実行してください。")
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"{file_path} が dict として読めません。")
    return data


def load_terms(file_path: str, limit: int, what: str) -> list[str]:
    """1行1語の file を読む。重複は落とす。limit 超過は落とす（全走査の禁止）。"""
    if not os.path.exists(file_path):
        raise SystemExit(f"{file_path} がありません。")
    seen, terms = set(), []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            t = line.strip()
            if not t or t.startswith("#") or t in seen:
                continue
            seen.add(t)
            terms.append(t)
    if not terms:
        raise SystemExit(f"{file_path} に {what} が1件もありません。")
    if len(terms) > limit:
        raise SystemExit(
            f"{file_path} の {what} が {len(terms)} 件あり、--limit {limit} を超えました。"
            f"全走査は禁止です（doc/METHOD.md §5 規律2）。意図的に上げる場合のみ --limit を明示してください。")
    return terms


TRANSIENT_STATUS = (408, 425, 429, 500, 502, 503, 504)


class Budget:
    """host ごとの request 数を数え、上限で止めます。上限超過は例外です（黙って続けません）。"""

    def __init__(self, limits: dict[str, int] | None = None):
        self.limits = dict(limits or {})
        self.used: Counter = Counter()

    def spend(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc.lower()
        self.used[host] += 1
        cap = self.limits.get(host)
        if cap is not None and self.used[host] > cap:
            raise SystemExit(f"{host} への request が上限 {cap} 件を超えました。"
                             "上限は config/*.yaml にあります。意図的に上げる場合のみ変更してください。")

    def report(self) -> dict:
        return dict(self.used)


def _retry_wait(attempt: int, base: float, retry_after: str | None) -> float:
    """Retry-After は秒数と HTTP-date の両方を取り得ます。負値・NaN は使いません。"""
    if retry_after:
        try:
            v = float(retry_after)
            if math.isfinite(v):
                return min(max(v, 0.0), 60.0)
        except ValueError:
            try:
                when = email.utils.parsedate_to_datetime(retry_after)
                delta = (when - datetime.datetime.now(when.tzinfo)).total_seconds()
                return min(max(delta, 0.0), 60.0)
            except (TypeError, ValueError):
                pass
    return base * (2 ** attempt)


def http_json(url: str, headers: dict | None = None, timeout: int = 30,
              retries: int = 2, backoff: float = 1.0, budget: "Budget | None" = None
              ) -> tuple[object, str, dict]:
    """JSON を取得して (解析済み, 生 text, response header) を返す。

    一時的な失敗（429・5xx・通信断）だけ指数 backoff で再送します。同じ request の
    やり直しであり、代替値での穴埋めではありません。恒久的な失敗は即座に SourceError です。
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    last: Exception | None = None
    if budget is not None:
        budget.spend(url)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", errors="replace")
                head = {k.lower(): v for k, v in r.headers.items()}
            try:
                return json.loads(raw), raw, head
            except json.JSONDecodeError as e:
                raise SourceError(f"JSON として解釈できません: {url} ({e})") from e
        except urllib.error.HTTPError as e:
            last = SourceError(f"HTTP {e.code} {url}", status=e.code)
            if e.code not in TRANSIENT_STATUS or attempt == retries:
                raise last from e
            time.sleep(_retry_wait(attempt, backoff, e.headers.get("Retry-After") if e.headers else None))
        except SourceError:
            raise
        except Exception as e:
            last = SourceError(f"{type(e).__name__}: {e} {url}")
            if attempt == retries:
                raise last from e
            time.sleep(_retry_wait(attempt, backoff, None))
    raise last if last else SourceError(f"取得できませんでした: {url}")


def http_text(url: str, timeout: int = 30, max_bytes: int = 2_000_000,
              budget: "Budget | None" = None) -> tuple[str, str, int]:
    """HTML などを取得して (text, 最終 URL, status) を返す。失敗は SourceError。"""
    if budget is not None:
        budget.spend(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(max_bytes)
            charset = r.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace"), r.geturl(), r.status
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP {e.code} {url}", status=e.code) from e
    except Exception as e:
        raise SourceError(f"{type(e).__name__}: {e} {url}") from e


def save_raw(kind: str, name: str, text: str, day_stamp: str, out_dir: str, ext: str = "json") -> str:
    d = os.path.join(out_dir, "raw", kind, day_stamp)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"{slug(name)}.{ext}")
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


def _atomic_write(file_path: str, text: str) -> None:
    """同じ directory に書いてから置換します。中断しても既存 file を壊しません。"""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    tmp = f"{file_path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, file_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def write_jsonl(file_path: str, rows: list[dict]) -> None:
    _atomic_write(file_path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def read_jsonl(file_path: str) -> list[dict]:
    if not os.path.exists(file_path):
        raise SystemExit(f"{file_path} がありません。先に前段の program を実行してください。")
    rows = []
    with open(file_path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{file_path}:{i} が JSON として読めません（{e}）。")
    return rows


def merge_cases(file_path: str, rows: list[dict]) -> tuple[int, int, list[dict]]:
    """事例を既存 file に併合します。重複は case_id と正規化 URL で落とします。

    戻り値は (追加数, 重複数, 併合後の全件)。同じ日に何度実行しても増えるだけです。
    """
    existing = read_jsonl(file_path) if os.path.exists(file_path) else []
    if any("case_id" not in r for r in existing):
        raise SystemExit(f"{file_path} に case_id を持たない行があります。形式の違う file です。")
    by_id = {r["case_id"]: r for r in existing}
    seen = {norm_url(r.get("url")) for r in existing if norm_url(r.get("url"))}
    added = dup = 0
    for c in rows:
        key = norm_url(c.get("url"))
        if c["case_id"] in by_id or (key and key in seen):
            dup += 1
            continue
        by_id[c["case_id"]] = c
        if key:
            seen.add(key)
        added += 1
    out = sorted(by_id.values(), key=lambda r: (r.get("kind", ""), -(r.get("points") or 0)))
    write_jsonl(file_path, out)
    return added, dup, out


def write_text_file(file_path: str, text: str) -> None:
    _atomic_write(file_path, text)


def write_json(file_path: str, obj) -> None:
    _atomic_write(file_path, json.dumps(obj, ensure_ascii=False, indent=1))


def latest(out_dir: str, pattern: str, hint: str) -> str:
    """log/ の中で最も新しい該当 file を返す。無ければ落とす（代替値を作らない）。"""
    found = sorted(glob.glob(os.path.join(glob.escape(out_dir), pattern)))
    if not found:
        raise SystemExit(f"{os.path.join(out_dir, pattern)} が見つかりません。先に {hint} を実行してください。")
    return found[-1]


def pctl(values: list[float], q: float):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def distribution(values: list[float]) -> dict | None:
    """分布のみを返す。平均は返さない（doc/METHOD.md §5 規律7）。"""
    if not values:
        return None
    return {
        "n": len(values),
        "min": round(min(values), 2),
        "p25": round(pctl(values, .25), 2),
        "p50": round(pctl(values, .50), 2),
        "p75": round(pctl(values, .75), 2),
        "max": round(max(values), 2),
    }


def slug(text: str, limit: int = 80) -> str:
    t = unicodedata.normalize("NFKC", text).strip().lower()
    t = re.sub(r"[^\w\-.]+", "-", t, flags=re.UNICODE).strip("-")
    return (t or "untitled")[:limit]


def norm_url(url: str | None) -> str | None:
    """重複判定用の key。scheme・www・末尾 slash・query を落とす。"""
    if not url:
        return None
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    host = (u.netloc or "").lower().removeprefix("www.")
    p = (u.path or "").rstrip("/").lower()
    return f"{host}{p}" if host else None


def new_case(**kw) -> dict:
    missing = [f for f in CASE_FIELDS if f not in kw]
    if missing:
        raise ValueError(f"case record に必須 field がありません: {missing}")
    return {f: kw[f] for f in CASE_FIELDS}


def eprint(*a) -> None:
    print(*a, file=sys.stderr)


def git_commit() -> str | None:
    try:
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except Exception:
        return None


class Manifest:
    """実行の記録。同じ結果を再現するために要るものを1 file に残します。"""

    def __init__(self, tool: str, params: dict):
        self.data = {
            "tool": tool,
            "started_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "git_commit": git_commit(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "params": {k: v for k, v in params.items() if not k.startswith("_")},
            "counts": {},
            "failures": [],
            "outputs": [],
        }

    def count(self, **kw) -> None:
        self.data["counts"].update(kw)

    def add(self, **kw) -> None:
        """同じ key を複数回記録する場合に累算します（上書きしません）。"""
        for k, v in kw.items():
            self.data["counts"][k] = self.data["counts"].get(k, 0) + v

    def fail(self, **kw) -> None:
        self.data["failures"].append(kw)

    def output(self, p: str) -> None:
        self.data["outputs"].append(p)

    def write(self, out_dir: str, budget: "Budget | None" = None) -> str:
        self.data["ended_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        if budget is not None:
            self.data["requests"] = budget.report()
        d = os.path.join(out_dir, "runs")
        os.makedirs(d, exist_ok=True)
        name = self.data["started_at"].replace(":", "").replace("-", "")[:15]
        p = os.path.join(d, f"{name}-{self.data['tool']}.json")
        write_json(p, self.data)
        return p


WORD = re.compile(r"[a-z][a-z0-9+#\-]{2,}")
APOSTROPHE = re.compile(r"[\u2019']")
URL = re.compile(r"https?://\S+|www\.\S+|\b[\w.\-]+\.(?:com|io|dev|org|net|ai|co|app|sh)\b")
HTML_TAG = re.compile(r"<[^>]+>")
PERCENT = re.compile(r"%[0-9a-fA-F]{2}")


def strip_noise(text: str) -> str:
    """URL・HTML tag・実体参照・percent encode を落とします。

    これらは keyness で上位に来ますが、検索語としては使えません
    （x2f や quot のような断片が候補に混ざる原因になります）。
    """
    t = html.unescape(text or "")
    t = HTML_TAG.sub(" ", t)
    t = URL.sub(" ", t)
    t = PERCENT.sub(" ", t)
    return APOSTROPHE.sub("", t)


def tokenize_en(text: str, stopwords: set[str]) -> list[str]:
    return [w for w in WORD.findall(strip_noise(text).lower()) if w not in stopwords]


def ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def log_likelihood(a: int, b: int, c: int, d: int) -> float:
    """Dunning (1993) の G^2。2x2 の4 cell すべてを足す完全形です。

    a: target での出現数 / b: background での出現数 / c,d: それぞれの総語数。
    target に偏るほど正、background に偏るほど負を返します。

    2 cell の Poisson 近似（語 cell のみ）を使う実装もありますが、a/c が大きい
    短い文書（tag の集合など）で過小評価します。実測で a=500,b=100,c=d=10000 のとき
    近似 291.10 に対し完全形は 299.35 でした。ここでは完全形を使います。

    G^2 は漸近的に chi^2(1) に従います。臨界値は 3.841 (p=.05) / 6.635 (p=.01) /
    10.828 (p=.001) です。**有意性であって効果量ではない**ため、log_ratio と併用します。
    """
    if c <= 0 or d <= 0 or (a + b) <= 0:
        raise ValueError(f"log_likelihood の母数が不正です: a={a} b={b} c={c} d={d}")
    n = c + d
    cells = ((a, c * (a + b) / n), (b, d * (a + b) / n),
             (c - a, c * (n - a - b) / n), (d - b, d * (n - a - b) / n))
    g = 2.0 * sum(o * math.log(o / e) for o, e in cells if o > 0 and e > 0)
    return g if (a / c) >= (b / d) else -g


def log_ratio(a: int, b: int, c: int, d: int, smoothing: float = 0.5) -> float:
    """Hardie (2014) の Log Ratio（効果量）。相対頻度が何倍かを log2 で返します。

    G^2 は corpus が大きいほど機械的に増えるため、順位付けには効果量が必要です。
    0 割りを避けるため両側に smoothing を足します。
    """
    if c <= 0 or d <= 0:
        raise ValueError(f"log_ratio の母数が不正です: c={c} d={d}")
    return math.log2(((a + smoothing) / c) / ((b + smoothing) / d))


def keyness(target_docs: list[list[str]], background_docs: list[list[str]],
            min_count: int = 3, top_k: int = 40, min_docs: int = 1,
            min_g2: float = 10.828, min_log_ratio: float = 1.0) -> list[dict]:
    """target を background から分ける語を返します。有意性と効果量の両方で足切りします。

    min_docs  : いくつの文書に現れたかの下限。1文書だけに出る固有名詞を落とします
    min_g2    : G^2 の下限。既定 10.828 は chi^2(1) の p=.001
    min_log_ratio: 効果量の下限。既定 1.0 は「相対頻度が2倍以上」

    **有意性だけで切らない理由**: G^2 は標本が大きいほど機械的に大きくなるため、
    corpus 言語学では G^2 と効果量（Log Ratio）の併記が標準です。
    """
    if not target_docs or not background_docs:
        raise ValueError("keyness には target と background の両方が必要です。")
    t = Counter(w for doc in target_docs for w in doc)
    b = Counter(w for doc in background_docs for w in doc)
    t_docs = Counter(w for doc in target_docs for w in set(doc))
    c, d = sum(t.values()), sum(b.values())
    if c <= 0 or d <= 0:
        raise ValueError(f"語が0件です（target {c}語 / background {d}語）。母集団を広げてください。")
    rows = []
    for w, a in t.items():
        if a < min_count or t_docs[w] < min_docs:
            continue
        g = log_likelihood(a, b.get(w, 0), c, d)
        lr = log_ratio(a, b.get(w, 0), c, d)
        if g < min_g2 or lr < min_log_ratio:
            continue
        rows.append({"term": w, "g2": round(g, 2), "log_ratio": round(lr, 2),
                     "target_count": a, "background_count": b.get(w, 0),
                     "target_docs": t_docs[w]})
    rows.sort(key=lambda r: -r["g2"])
    return rows[:top_k]


def wilson_lower(successes: int, trials: int, z: float = 1.96) -> float:
    """Wilson score interval の下限。小標本の適合率を点推定で判定しないために使います。

    n=20 で 4/20 を採ると点推定 0.20 ですが、下限は 0.081 です。
    点推定で閾値 0.20 を判定すると、本来 棄却すべき語を採用します。
    """
    if trials <= 0:
        raise ValueError("trials は1以上が必要です。測定できなかった場合は None を使ってください。")
    p = successes / trials
    z2 = z * z
    centre = p + z2 / (2 * trials)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * trials)) / trials)
    return max(0.0, (centre - margin) / (1 + z2 / trials))
