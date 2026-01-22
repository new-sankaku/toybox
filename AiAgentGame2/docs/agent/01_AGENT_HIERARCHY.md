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
| 責務 | Phase間の遷移判断、全体進捗の監視 |
| 管理対象 | 全DIRECTOR |
| 使用LLM | 思考型ハイパフォーマンス（Opus等） |

**具体的な責務:**
- プロジェクト開始時の初期化
- Phase遷移の判断（Phase N → Phase N+1）
- エラー発生時のエスカレーション受付
- 全体の進捗レポート生成

### DIRECTOR（ディレクター）

| 項目 | 内容 |
|------|------|
| 数 | Phase毎に1体 |
| 役割 | Phase全体の統括 |
| 責務 | Phase内のLEADER管理、Phase完了判定 |
| 管理対象 | 配下のLEADER群 |
| 使用LLM | 思考型ハイパフォーマンス（Opus等） |

**Phase毎のDIRECTOR:**
- Phase1 DIRECTOR: 企画フェーズ統括
- Phase2 DIRECTOR: 開発フェーズ統括
- Phase3 DIRECTOR: 品質フェーズ統括
- （将来的にPhaseが増える可能性あり）

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
| 責務 | WORKERへのタスク分解・割当、成果物の統合、Human承認の提出 |
| 管理対象 | 配下のWORKER群 |
| 使用LLM | 思考型ハイパフォーマンス（Opus等） |

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
- WORKER成果物の確認・再指示（最大3回）
- 成果物の統合
- **Human承認の提出**（WebUIへの承認依頼）
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

## Human承認フロー

Human承認はORCHESTRATORではなく、**各LEADERが提出**する。

```
LEADER
    │ 成果物完成
    v
WebUI承認画面に提出
    │
    v
Humanがレビュー
    │
    ├── 承認 → 次のステップへ
    │
    ├── 修正指示 → LEADERがWORKERに再指示
    │
    └── 追加指示 → LEADERが追加タスクを作成
```

### 承認画面の表示内容

| 表示項目 | 説明 |
|---------|------|
| LEADERの指示内容 | LEADERがWORKERに出した指示 |
| WORKERへの指示 | 個別WORKERへの具体的な指示 |
| 生成物 | WORKERが作成した成果物 |
| 指示履歴 | 修正指示があった場合の履歴 |

### 未承認時の操作

| 操作 | 説明 |
|------|------|
| 指示内容の書き換え | LEADERの指示を編集して再実行 |
| 追加指示 | 既存の指示に追加で指示を付与 |
| 却下 | 作業を中止 |

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
    │ 実行
    v
LEADER (確認)
    │
    ├── OK → 成果物を受領
    │
    └── NG → 再指示（最大3回）
              │
              v
            WORKER（再実行）
```

### 上向き（報告）

```
WORKER
    │ "アイデア3案完成"
    v
LEADER (Concept)
    │ 確認
    │
    ├── OK → Human承認を提出（WebUI）
    │          │
    │          v
    │        Human承認
    │          │
    │          v
    │        DIRECTORへ報告
    │
    └── NG → WORKERへ再指示（最大3回）
```

### 再確認処理

LEADER-WORKER間の再確認は無限ループを避けるため**最大3回**に制限。

```
LEADER → WORKER: 指示
WORKER → LEADER: 成果物提出
LEADER: 確認
    │
    ├── OK → 完了
    │
    └── NG (1回目) → 再指示
          │
          v
        WORKER: 再実行
        LEADER: 確認
            │
            ├── OK → 完了
            │
            └── NG (2回目) → 再指示
                  │
                  v
                WORKER: 再実行
                LEADER: 確認
                    │
                    ├── OK → 完了
                    │
                    └── NG (3回目) → エスカレーション（DIRECTORへ）
```

## 既存ファイルの統合方針

このドキュメントの内容に合わせて、以下の既存ファイルを更新・統合する:

| 対象 | 作業内容 |
|------|---------|
| AGENT_SYSTEM.md | 階層構造図を更新、DIRECTORの追加 |
| agents/_COMMON.md | AgentRole定義、共通プロンプトの更新 |
| agents/phase*_*_leader.md | LEADER定義として統一、Human承認提出の責務を追加 |
| agents/phase*_*_workers.md | WORKER定義として統一 |
| agents/directors/ | 新規作成：各Phase DIRECTORの定義 |
