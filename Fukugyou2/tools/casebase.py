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
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
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
    for attempt in range(retries + 1):
        if budget is not None:
            budget.spend(url)
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


def http_text(url: str, timeout: int = 30, max_bytes: int = 2_000_000) -> tuple[str, str, int]:
    """HTML などを取得して (text, 最終 URL, status) を返す。失敗は SourceError。"""
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
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def write_jsonl(file_path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


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


def write_json(file_path: str, obj) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def latest(out_dir: str, pattern: str, hint: str) -> str:
    """log/ の中で最も新しい該当 file を返す。無ければ落とす（代替値を作らない）。"""
    found = sorted(glob.glob(os.path.join(out_dir, pattern)))
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
    return t


def tokenize_en(text: str, stopwords: set[str]) -> list[str]:
    return [w for w in WORD.findall(strip_noise(text).lower()) if w not in stopwords]


def ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def log_likelihood(a: int, b: int, c: int, d: int) -> float:
    """Dunning の G^2。target に偏るほど正、background に偏るほど負を返します。

    a: target での出現数 / b: background での出現数 / c,d: それぞれの総語数。
    corpus 比較の keyness としては業界標準の指標で、低頻度語に強い点で
    単純な頻度差や TF-IDF より適しています。
    """
    if c <= 0 or d <= 0 or (a + b) <= 0:
        return 0.0
    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    g = 0.0
    if a > 0 and e1 > 0:
        g += a * math.log(a / e1)
    if b > 0 and e2 > 0:
        g += b * math.log(b / e2)
    g *= 2.0
    return g if (a / c) >= (b / d) else -g


def keyness(target_docs: list[list[str]], background_docs: list[list[str]],
            min_count: int = 3, top_k: int = 40, min_docs: int = 1) -> list[dict]:
    """target を background から分ける語を G^2 の降順で返します。

    min_docs は「いくつの文書に現れたか」の下限です。1件の文書にだけ出る語
    （製品名・作者名などの固有名詞）を落とすために使います。
    """
    t = Counter(w for doc in target_docs for w in doc)
    b = Counter(w for doc in background_docs for w in doc)
    t_docs = Counter(w for doc in target_docs for w in set(doc))
    c, d = sum(t.values()), sum(b.values())
    rows = []
    for w, a in t.items():
        if a < min_count or t_docs[w] < min_docs:
            continue
        g = log_likelihood(a, b.get(w, 0), c, d)
        if g <= 0:
            continue
        rows.append({"term": w, "g2": round(g, 2), "target_count": a,
                     "background_count": b.get(w, 0), "target_docs": t_docs[w]})
    rows.sort(key=lambda r: -r["g2"])
    return rows[:top_k]
