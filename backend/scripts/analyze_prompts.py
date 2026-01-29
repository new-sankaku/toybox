"""
プロンプトテンプレート分析スクリプト
41ファイルの文字数・推定トークン数を集計し、最適化の判断材料を提供する
"""

import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from config_loader import get_all_prompts


def estimate_tokens(text: str) -> int:
    return int(len(text) / 3.5)


def find_common_patterns(prompts: dict, min_length: int = 50) -> list:
    texts = list(prompts.values())
    pattern_counts = Counter()
    for i, t1 in enumerate(texts):
        for j in range(i + 1, len(texts)):
            t2 = texts[j]
            common = _longest_common_substring(t1, t2)
            if len(common) >= min_length:
                trimmed = common.strip()
                if len(trimmed) >= min_length:
                    pattern_counts[trimmed[:200]] += 1
    return pattern_counts.most_common(10)


def _longest_common_substring(s1: str, s2: str) -> str:
    if len(s1) > 5000:
        s1 = s1[:5000]
    if len(s2) > 5000:
        s2 = s2[:5000]
    m = len(s1)
    n = len(s2)
    longest = 0
    end_pos = 0
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                curr[j] = prev[j - 1] + 1
                if curr[j] > longest:
                    longest = curr[j]
                    end_pos = i
            else:
                curr[j] = 0
        prev, curr = curr, [0] * (n + 1)
    return s1[end_pos - longest : end_pos]


def main():
    prompts = get_all_prompts()
    if not prompts:
        print("プロンプトファイルが見つかりません")
        return

    print("=" * 70)
    print("プロンプトテンプレート分析レポート")
    print("=" * 70)

    stats = []
    total_chars = 0
    total_tokens = 0
    for name, content in prompts.items():
        chars = len(content)
        tokens = estimate_tokens(content)
        total_chars += chars
        total_tokens += tokens
        stats.append((name, chars, tokens))

    print(f"\nファイル数: {len(stats)}")
    print(f"合計文字数: {total_chars:,}")
    print(f"推定合計トークン数: {total_tokens:,}")
    print(f"平均文字数: {total_chars // len(stats):,}")
    print(f"平均推定トークン数: {total_tokens // len(stats):,}")

    stats.sort(key=lambda x: x[1], reverse=True)

    print(f"\n{'─' * 70}")
    print("TOP 10 最大プロンプト")
    print(f"{'─' * 70}")
    print(f"{'#':>3} {'ファイル':<35} {'文字数':>10} {'推定トークン':>12}")
    print(f"{'─' * 70}")
    for i, (name, chars, tokens) in enumerate(stats[:10], 1):
        print(f"{i:>3} {name:<35} {chars:>10,} {tokens:>12,}")

    print(f"\n{'─' * 70}")
    print("全ファイル一覧")
    print(f"{'─' * 70}")
    print(f"{'ファイル':<35} {'文字数':>10} {'推定トークン':>12}")
    print(f"{'─' * 70}")
    for name, chars, tokens in stats:
        print(f"{name:<35} {chars:>10,} {tokens:>12,}")

    print(f"\n{'─' * 70}")
    print("共通パターン検出中...")
    print(f"{'─' * 70}")
    patterns = find_common_patterns(prompts)
    if patterns:
        for i, (pattern, count) in enumerate(patterns, 1):
            preview = pattern.replace("\n", " ")[:80]
            print(f'{i:>3}. 出現: {count + 1}ファイル | "{preview}..."')
    else:
        print("(長い共通パターンは検出されませんでした)")

    print(f"\n{'=' * 70}")
    print("分析完了")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
