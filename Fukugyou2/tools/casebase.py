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
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

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


def http_json(url: str, headers: dict | None = None, timeout: int = 30) -> tuple[object, str, dict]:
    """JSON を取得して (解析済み, 生 text, response header) を返す。失敗は SourceError。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            head = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        raise SourceError(f"HTTP {e.code} {url}", status=e.code) from e
    except Exception as e:
        raise SourceError(f"{type(e).__name__}: {e} {url}") from e
    try:
        return json.loads(raw), raw, head
    except json.JSONDecodeError as e:
        raise SourceError(f"JSON として解釈できません: {url} ({e})") from e


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
