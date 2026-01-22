# コンテキスト圧縮

## 概要

計画が承認された後、探索過程の詳細などの不要なコンテキストを圧縮し、トークン消費を削減する。
圧縮のタイミングと対象を明確にし、必要な情報は保持しながら効率化する。

## 圧縮のタイミング

| タイミング | 圧縮対象 | トリガー |
|-----------|---------|---------|
| 計画承認後 | 探索・調査のコンテキスト | Human承認 |
| Phase完了後 | Phase内の中間成果物詳細 | Phase遷移 |
| イテレーション完了後 | 全体の詳細情報 | イテレーション遷移 |
| コンテキスト上限接近時 | 優先度の低い情報 | 使用率80%超 |

## 圧縮対象と保持対象

### 圧縮対象（削除または要約）

| 対象 | 処理 |
|------|------|
| 探索過程の詳細ログ | 結論のみ保持 |
| 却下された選択肢の詳細 | 理由のみ保持 |
| 試行錯誤の履歴 | 最終的なアプローチのみ保持 |
| 中間生成物 | 最終版のみ保持 |
| 冗長な説明 | 箇条書きに変換 |

### 保持対象（圧縮しない）

| 対象 | 理由 |
|------|------|
| 最終決定事項 | 実装に必要 |
| 重要な制約 | 品質に影響 |
| 依存関係 | タスク実行に必要 |
| Human承認内容 | 証跡として必要 |
| エラー情報 | 再発防止に必要 |

## 圧縮レベル

### Level 1: 軽量圧縮（通常時）

```python
def compress_level1(context: str) -> str:
    """軽量圧縮：冗長な部分のみ削除"""
    # 重複する説明を削除
    # 空行を削減
    # 長い引用を短縮
    pass
```

### Level 2: 標準圧縮（承認後）

```python
def compress_level2(context: str) -> str:
    """標準圧縮：探索過程を要約"""
    # 探索ログ → 「調査の結果、Xを採用」
    # 却下案 → 「A, B, Cは不採用（理由: ...）」
    # 試行履歴 → 「3回の試行後、Yで成功」
    pass
```

### Level 3: 強力圧縮（上限接近時）

```python
def compress_level3(context: str) -> str:
    """強力圧縮：必要最小限のみ保持"""
    # 決定事項のみ保持
    # 理由は1行に圧縮
    # コード例は省略（参照パスのみ）
    pass
```

## 圧縮フォーマット

### 圧縮前

```markdown
## 調査フェーズ

### ゲームエンジンの選定

まず、2Dアクションゲームに適したゲームエンジンを調査しました。

#### Unity
Unityは最も人気のあるゲームエンジンの1つです。2Dゲーム開発にも対応しており、
豊富なアセットストアがあります。C#で開発できるため、学習コストも比較的低いです。
ただし、ライセンス費用が発生する可能性があります。
（以下、500行の詳細な比較...）

#### Godot
Godotはオープンソースのゲームエンジンです。...
（以下、300行の詳細な比較...）

#### Phaser
Phaserはブラウザベースの2Dゲームエンジンです。...
（以下、200行の詳細な比較...）

### 結論
検討の結果、Unityを採用することにしました。理由は以下の通りです：
1. 開発者の経験
2. 豊富なリソース
3. 将来的な拡張性
```

### 圧縮後

```markdown
## 調査結果

### ゲームエンジン選定
- **決定**: Unity
- **理由**: 開発者経験、豊富なリソース、拡張性
- **却下**: Godot（リソース不足）、Phaser（パフォーマンス懸念）
- **詳細**: sessions/sess_xxx/exploration/engine_selection.md
```

## 実装

### コンテキストコンプレッサー

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class CompressionLevel(Enum):
    LIGHT = 1
    STANDARD = 2
    AGGRESSIVE = 3

@dataclass
class CompressionResult:
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    preserved_items: List[str]
    archived_path: Optional[str]

class ContextCompressor:
    def __init__(self):
        self.preserved_patterns = [
            r"## 決定事項",
            r"## 最終決定",
            r"## 承認済み",
            r"## エラー",
            r"## 依存関係",
        ]

    def compress(
        self,
        context: str,
        level: CompressionLevel,
        archive_path: Optional[str] = None
    ) -> CompressionResult:
        """コンテキストを圧縮"""

        original_tokens = self._count_tokens(context)

        # 保持すべき部分を抽出
        preserved = self._extract_preserved(context)

        # アーカイブに保存（必要な場合）
        if archive_path:
            self._save_archive(context, archive_path)

        # 圧縮実行
        if level == CompressionLevel.LIGHT:
            compressed = self._compress_light(context, preserved)
        elif level == CompressionLevel.STANDARD:
            compressed = self._compress_standard(context, preserved)
        else:
            compressed = self._compress_aggressive(context, preserved)

        compressed_tokens = self._count_tokens(compressed)

        return CompressionResult(
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compressed_tokens / original_tokens,
            preserved_items=[p["title"] for p in preserved],
            archived_path=archive_path
        )

    def _compress_standard(self, context: str, preserved: List[dict]) -> str:
        """標準圧縮"""
        sections = self._parse_sections(context)
        compressed_sections = []

        for section in sections:
            if self._should_preserve(section):
                compressed_sections.append(section)
            elif self._is_exploration(section):
                # 探索セクションは要約
                summary = self._summarize_exploration(section)
                compressed_sections.append(summary)
            else:
                # その他は大幅に短縮
                brief = self._make_brief(section)
                compressed_sections.append(brief)

        return "\n\n".join(compressed_sections)

    def _summarize_exploration(self, section: str) -> str:
        """探索セクションを要約"""
        # LLMを使用して要約（または簡易ルールベース）
        # 結論、決定事項、却下理由のみ抽出
        pass
```

### 自動圧縮トリガー

```python
class AutoCompressionManager:
    def __init__(self, threshold_percent: int = 80):
        self.threshold = threshold_percent
        self.compressor = ContextCompressor()

    def check_and_compress(self, state: GameDevState) -> Optional[CompressionResult]:
        """必要に応じて自動圧縮"""

        usage = self._calculate_context_usage(state)

        if usage >= self.threshold:
            # 圧縮レベルを決定
            if usage >= 95:
                level = CompressionLevel.AGGRESSIVE
            elif usage >= 90:
                level = CompressionLevel.STANDARD
            else:
                level = CompressionLevel.LIGHT

            # 圧縮実行
            result = self.compressor.compress(
                state.context,
                level,
                archive_path=f"sessions/{state.session_id}/archives/"
            )

            # 通知
            self._notify_compression(result)

            return result

        return None
```

## 圧縮通知

### 通知タイミング

| 状況 | 通知内容 |
|------|---------|
| コンテキスト80%到達 | 「圧縮を推奨します」 |
| 自動圧縮実行 | 「コンテキストを圧縮しました（XX% → YY%）」 |
| 圧縮後も90%超 | 「追加の圧縮が必要です」 |

### WebUI通知

```typescript
interface CompressionNotification {
  type: "warning" | "info" | "success";
  message: string;
  details: {
    before_tokens: number;
    after_tokens: number;
    compression_ratio: number;
    archived_items: string[];
  };
  actions: {
    view_archive: string;  // アーカイブ閲覧URL
    undo: string;          // 元に戻すURL（可能な場合）
  };
}
```

## 承認と圧縮の関係

### Human承認後の自動圧縮

```python
class ApprovalHandler:
    def on_approval(self, checkpoint: Checkpoint, approval: Approval):
        """承認後の処理"""

        # 1. 承認内容を記録
        self._record_approval(checkpoint, approval)

        # 2. 関連する探索コンテキストを圧縮
        compression_result = self.compressor.compress(
            checkpoint.exploration_context,
            CompressionLevel.STANDARD
        )

        # 3. 圧縮結果をログ
        self._log_compression(compression_result)

        # 4. 次のフェーズに必要な情報のみ保持
        return self._extract_next_phase_context(checkpoint, approval)
```

### 圧縮前の確認（オプション）

```yaml
# config/compression.yaml

compression:
  auto_compress_on_approval: true
  confirm_before_compress: false  # trueの場合、Human確認を要求
  preserve_exploration_days: 7    # 探索ログの保持日数
  archive_format: "markdown"      # markdown or json
```

## アーカイブ

### アーカイブ構造

```
sessions/{session_id}/archives/
├── phase1_exploration.md
├── phase1_decisions.md
├── phase2_exploration.md
└── compression_log.json
```

### compression_log.json

```json
{
  "compressions": [
    {
      "timestamp": "2024-01-15T14:00:00Z",
      "trigger": "approval",
      "checkpoint": "concept",
      "level": "standard",
      "original_tokens": 15000,
      "compressed_tokens": 2000,
      "archived_to": "phase1_exploration.md"
    }
  ]
}
```

## 復元

### アーカイブからの復元

```python
def restore_context(archive_path: str) -> str:
    """アーカイブからコンテキストを復元"""
    with open(archive_path) as f:
        return f.read()

def partial_restore(archive_path: str, section: str) -> str:
    """特定セクションのみ復元"""
    full_content = restore_context(archive_path)
    return extract_section(full_content, section)
```

### 復元が必要なケース

| ケース | 対応 |
|-------|------|
| Human修正指示で過去の検討が必要 | 該当セクションを復元 |
| バグ修正で過去のアプローチを確認 | failed approachesを復元 |
| 全体レビューで経緯確認 | 全体を一時的に復元 |
