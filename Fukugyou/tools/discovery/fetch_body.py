#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""段階A: 記事の全文を取得する（粗い一覧化の入力を作る）。

AUTOMATION.md §2 の制約:
  - 候補を生成しない。URL は人が書いた file から読む（制約1）
  - --limit を必須にする（制約2）
  - 取得日を出力に刻む（制約4）
  - 生 response を保存する（制約5）
  - 失敗は fallback せず失敗として記録する（制約6）

使い方:
  python tools/discovery/fetch_body.py --urls log/urls.txt --limit 20 --out log/bodies/
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "Fukugyou-discovery/1.0 (+doc/AUTOMATION.md)"
QIITA_ITEM = re.compile(r"^https?://qiita\.com/[^/]+/items/([0-9a-f]+)")


def strip_tags(raw: str) -> str:
    raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<style.*?</style>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<[^>]+>", "\n", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"[ \t　]{2,}", " ", raw)
    return re.sub(r"\n{2,}", "\n", raw).strip()


def fetch(url: str, timeout: int) -> tuple[str, str, dict]:
    """(本文, 取得経路, 生 response) を返す。失敗したら例外を上げる。"""
    m = QIITA_ITEM.match(url)
    if m:
        api = f"https://qiita.com/api/v2/items/{m.group(1)}"
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        return data["body"], "qiita_api", data

    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    return strip_tags(raw), "html", {"url": url, "bytes": len(raw)}


def main() -> int:
    p = argparse.ArgumentParser(description="記事全文の取得（doc/AUTOMATION.md §2）")
    p.add_argument("--urls", required=True, help="URL を1行1件で書いた file（人が書く）")
    p.add_argument("--limit", type=int, required=True, help="扱う URL の上限（全走査の禁止）")
    p.add_argument("--out", required=True, help="出力先 directory")
    p.add_argument("--timeout", type=int, default=40)
    p.add_argument("--sleep", type=float, default=1.0)
    a = p.parse_args()

    today = datetime.date.today().isoformat()
    urls = [ln.strip() for ln in Path(a.urls).read_text(encoding="utf-8").splitlines()]
    urls = [u for u in urls if u and not u.startswith("#")][: a.limit]

    out = Path(a.out)
    (out / "raw" / today).mkdir(parents=True, exist_ok=True)

    index, failures = [], []
    for i, url in enumerate(urls, 1):
        try:
            body, via, raw = fetch(url, a.timeout)
        except Exception as e:
            failures.append({"url": url, "error": repr(e)})
            print(f"  失敗: {url} — {e}", file=sys.stderr)
            continue
        slug = re.sub(r"[^A-Za-z0-9]", "_", url)[-70:]
        (out / f"{slug}.txt").write_text(body, encoding="utf-8")
        (out / "raw" / today / f"{slug}.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        index.append({"url": url, "slug": slug, "via": via, "chars": len(body),
                      "fetched_on": today})
        print(f"  [{i}/{len(urls)}] {len(body):>7} chars via {via:9s} {url}")
        time.sleep(a.sleep)

    (out / f"index-{today.replace('-', '')}.json").write_text(
        json.dumps({"fetched_on": today, "requested": len(urls),
                    "succeeded": len(index), "items": index, "failures": failures},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n取得 {today} / 依頼 {len(urls)}件 / 成功 {len(index)}件 / 失敗 {len(failures)}件")
    if failures:
        print("失敗した URL は index の failures に残しています（fallback していません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
