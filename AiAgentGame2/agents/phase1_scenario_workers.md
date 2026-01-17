# Scenario Workers（シナリオワーカー）

## 概要

Scenario Leaderの配下で動作するWorker群。ストーリー、ダイアログ、イベント設計を担当。

---

## Story Worker（ストーリーワーカー）

### 役割
メインストーリーと章構成を作成

### 出力スキーマ
```typescript
interface StoryWorkerOutput {
  main_story: {
    premise: string;
    theme: string;
    plot_summary: string;
  };
  chapters: Array<{
    number: number;
    title: string;
    summary: string;
    key_events: string[];
  }>;
}
```

---

## Dialog Worker（ダイアログワーカー）

### 役割
キャラクターの会話・ダイアログを作成

### 出力スキーマ
```typescript
interface DialogWorkerOutput {
  dialogs: Array<{
    id: string;
    scene: string;
    participants: string[];
    lines: Array<{
      speaker: string;
      text: string;
      emotion: string;
    }>;
  }>;
}
```

---

## Event Worker（イベントワーカー）

### 役割
ゲームイベントと分岐を設計

### 出力スキーマ
```typescript
interface EventWorkerOutput {
  events: Array<{
    id: string;
    type: "story" | "side" | "random";
    trigger: string;
    branches: Array<{
      choice: string;
      outcome: string;
      next_event: string;
    }>;
  }>;
}
```

---

## Worker間連携

```
Story Worker ──► Dialog Worker ──► Event Worker
      │                │               │
      ▼                ▼               ▼
  ストーリー      ダイアログ      イベント設計
      │                │               │
      └────────────────┴───────────────┘
                       │
                       ▼
                 Scenario Leader
                (統合・品質管理)
```
