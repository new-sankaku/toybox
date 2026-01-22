# Agent階層構造

## 概要

Agentを4層の階層構造で管理する。各層は明確な責務を持ち、上位層が下位層を管理する。

## 階層構造

```
ORCHESTRATOR (1体)
    │
    ├── DIRECTOR (Phase毎に1体)
    │       │
    │       └── LEADER (機能単位で1体)
    │               │
    │               └── WORKER (タスク毎に1体)
```

## 各層の定義

### ORCHESTRATOR（オーケストレーター）

| 項目 | 内容 |
|------|------|
| 数 | 1体（全体で1つ） |
| 役割 | プロジェクト全体のPM |
| 責務 | Phase間の遷移、Human承認の管理、全体進捗の監視 |
| 管理対象 | 全DIRECTOR |
| 使用LLM | Opus（重要な判断が多い） |

**具体的な責務:**
- プロジェクト開始時の初期化
- Phase1→Phase2→Phase3の遷移判断
- Human承認待ち（interrupt）の管理
- エラー発生時のエスカレーション受付
- 全体の進捗レポート生成

### DIRECTOR（ディレクター）

| 項目 | 内容 |
|------|------|
| 数 | Phase毎に1体（計3体） |
| 役割 | Phase全体の統括 |
| 責務 | Phase内のLEADER管理、Phase完了判定 |
| 管理対象 | 配下のLEADER群 |
| 使用LLM | Sonnet（バランス型） |

**Phase毎のDIRECTOR:**
- Phase1 DIRECTOR: 企画フェーズ統括
- Phase2 DIRECTOR: 開発フェーズ統括
- Phase3 DIRECTOR: 品質フェーズ統括

**具体的な責務:**
- 配下LEADERへのタスク分配
- LEADER間の調整（依存関係の解決）
- Phase完了条件の判定
- ORCHESTRATORへの進捗報告

### LEADER（リーダー）

| 項目 | 内容 |
|------|------|
| 数 | 機能単位で1体 |
| 役割 | チームリーダー |
| 責務 | WORKERへのタスク分解・割当、成果物の統合 |
| 管理対象 | 配下のWORKER群 |
| 使用LLM | Sonnet（デフォルト）、複雑な場合はOpus |

**Phase1のLEADER:**
- Concept LEADER: 企画立案
- Design LEADER: ゲーム設計
- Scenario LEADER: シナリオ作成
- Character LEADER: キャラクター設計
- World LEADER: 世界観構築
- TaskSplit LEADER: タスク分解

**Phase2のLEADER:**
- Code LEADER: コード実装統括
- Asset LEADER: アセット制作統括

**Phase3のLEADER:**
- Integrator LEADER: 統合作業
- Tester LEADER: テスト実行
- Reviewer LEADER: レビュー実施

**具体的な責務:**
- 受け取ったタスクを単一タスクに分解
- WORKERの生成・割当
- WORKER成果物のレビュー・統合
- DIRECTORへの完了報告

### WORKER（ワーカー）

| 項目 | 内容 |
|------|------|
| 数 | タスク毎に動的生成 |
| 役割 | 単一タスクの実行者 |
| 責務 | 1タスク = 1成果物の生成 |
| 管理対象 | なし（末端） |
| 使用LLM | Haiku（デフォルト）、失敗時にSonnetへ昇格 |

**具体的な責務:**
- 割り当てられた単一タスクの実行
- 成果物の生成
- LEADERへの完了報告
- エラー発生時のLEADERへのエスカレーション

## 通信フロー

### 下向き（指示）

```
ORCHESTRATOR
    │ "Phase1を開始せよ"
    v
DIRECTOR (Phase1)
    │ "Conceptを作成せよ"
    v
LEADER (Concept)
    │ "アイデア3案を出せ"
    v
WORKER
```

### 上向き（報告）

```
WORKER
    │ "アイデア3案完成"
    v
LEADER (Concept)
    │ "Concept完成、レビュー依頼"
    v
DIRECTOR (Phase1)
    │ "Phase1完了、Human承認待ち"
    v
ORCHESTRATOR
    │ interrupt() → Human
```

## 実装時のクラス構造

```python
from abc import ABC, abstractmethod
from typing import List, Optional
from enum import Enum

class AgentRole(Enum):
    ORCHESTRATOR = "orchestrator"
    DIRECTOR = "director"
    LEADER = "leader"
    WORKER = "worker"

class BaseAgent(ABC):
    def __init__(self, agent_id: str, role: AgentRole):
        self.agent_id = agent_id
        self.role = role
        self.parent: Optional["BaseAgent"] = None
        self.children: List["BaseAgent"] = []

    @abstractmethod
    def execute(self, task: dict) -> dict:
        pass

    @abstractmethod
    def report(self, result: dict) -> None:
        pass

class Orchestrator(BaseAgent):
    def __init__(self):
        super().__init__("orchestrator_main", AgentRole.ORCHESTRATOR)
        self.directors: List[Director] = []
        self.current_phase: int = 1

class Director(BaseAgent):
    def __init__(self, phase: int):
        super().__init__(f"director_phase{phase}", AgentRole.DIRECTOR)
        self.phase = phase
        self.leaders: List[Leader] = []

class Leader(BaseAgent):
    def __init__(self, leader_type: str, phase: int):
        super().__init__(f"leader_{leader_type}", AgentRole.LEADER)
        self.leader_type = leader_type
        self.workers: List[Worker] = []

class Worker(BaseAgent):
    def __init__(self, task_id: str):
        super().__init__(f"worker_{task_id}", AgentRole.WORKER)
        self.task_id = task_id
```

## 既存ファイルとの対応

| 既存ファイル | 新しい役割 |
|-------------|-----------|
| AGENT_SYSTEM.md の Orchestrator | ORCHESTRATOR |
| phase1_concept_leader.md | LEADER (Concept) |
| phase1_concept_workers.md | WORKER群の定義 |
| phase2_code_leader.md | LEADER (Code) |
| phase2_asset_leader.md | LEADER (Asset) |
| phase3_integrator.md | LEADER (Integrator) |

## 変更が必要な既存ファイル

1. `AGENT_SYSTEM.md`: 階層構造の図を更新、DIRECTORを追加
2. `agents/_COMMON.md`: AgentRole enumを追加
3. `agents/phase*_*.md`: 役割名をLEADER/WORKERに統一
4. 新規作成: `agents/directors/` フォルダにDIRECTOR定義を追加
