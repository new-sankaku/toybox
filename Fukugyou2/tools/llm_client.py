#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM の呼び出し。provider と model は config/llm.yaml からのみ読みます。

  - provider / model / endpoint を code に埋めません
  - API key は環境変数から読みます（config に書かせません）
  - 設定が欠けていたら、代替の provider に切り替えず、その場で落とします

単体確認:
  python tools/llm_client.py --prompt "1行で自己紹介してください"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import casebase as cb

REQUIRED = ("provider", "endpoint", "model", "api_key_env", "max_tokens", "timeout_seconds")


def load_config(config_path: str) -> dict:
    conf = cb.load_yaml(config_path)
    missing = [k for k in REQUIRED if not conf.get(k)]
    if missing:
        raise SystemExit(f"{config_path} の設定が空です: {missing}。"
                         "provider と model を書いてから実行してください。")
    key = os.environ.get(conf["api_key_env"])
    if not key:
        raise SystemExit(f"環境変数 {conf['api_key_env']} に API key がありません。"
                         "key は config file に書かず、環境変数で渡してください。")
    conf["_api_key"] = key
    return conf


def _request(conf: dict, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(
        conf["endpoint"],
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": cb.UA, **headers},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=int(conf["timeout_seconds"])) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        detail = e.read().decode("utf-8", "replace")[:400] if hasattr(e, "read") else ""
        raise cb.SourceError(f"LLM 呼び出しに失敗しました（{conf['provider']} / {conf['model']}）: {e} {detail}") from e


def complete(conf: dict, system: str, user: str) -> str:
    provider = conf["provider"]
    body = {"model": conf["model"], "max_tokens": int(conf["max_tokens"]),
            "temperature": float(conf.get("temperature", 0.3))}
    if provider == "anthropic":
        version = conf.get("api_version")
        if not version:
            raise SystemExit("provider: anthropic には api_version が必要です（config/llm.yaml）。")
        data = _request(conf, {"x-api-key": conf["_api_key"], "anthropic-version": version},
                        {**body, "system": system, "messages": [{"role": "user", "content": user}]})
        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        if not blocks:
            raise cb.SourceError(f"応答に text がありません: {str(data)[:300]}")
        return "".join(blocks)
    if provider in ("openrouter", "openai_compatible"):
        data = _request(conf, {"Authorization": f"Bearer {conf['_api_key']}"},
                        {**body, "messages": [{"role": "system", "content": system},
                                              {"role": "user", "content": user}]})
        choices = data.get("choices") or []
        if not choices:
            raise cb.SourceError(f"応答に choices がありません: {str(data)[:300]}")
        return choices[0]["message"]["content"]
    raise SystemExit(f"未対応の provider です: {provider}。"
                     "対応は anthropic / openrouter / openai_compatible です。")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="LLM 設定の疎通確認")
    ap.add_argument("--config", default=cb.path("config", "llm.yaml"))
    ap.add_argument("--prompt", required=True)
    ns = ap.parse_args(argv)
    conf = load_config(ns.config)
    print(f"provider {conf['provider']} / model {conf['model']}")
    print(complete(conf, "簡潔に日本語で答えてください。", ns.prompt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
