# WebUI Design Specification

## NieR:Automata Inspired Design System

本ドキュメントはLangGraph Game Development Systemのための、NieR:Automata風UIデザインシステムを定義する。

---

## 1. Design Philosophy

### 1.1 Core Principles

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│    "美しさは機能に従う。すべての要素に意味がある。"              │
│                                                                 │
│    - Minimalism: 不要な装飾を排除                               │
│    - Geometry: 円・線・グリッドによる構成                       │
│    - Monochrome: モノクロ/セピアを基調                          │
│    - Glitch: デジタル的な揺らぎとノイズ                         │
│    - Machine: 機械的・アンドロイド的な美学                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Visual Identity

NieR:Automataの特徴的なUI要素：
- **透過パネル**: 背景が透けて見える半透明レイヤー
- **スキャンライン**: CRTモニターを模したライン効果
- **幾何学模様**: 円形ゲージ、六角形グリッド、平行線
- **グリッチエフェクト**: データ破損を模した視覚効果
- **タイポグラフィ**: 機械的で角ばったフォント

---

## 2. Color System

### 2.1 Primary Palette

```
┌────────────────────────────────────────────────────────────────┐
│  COLOR PALETTE - NieR:Automata Style                           │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ■ Background                                                  │
│    --bg-primary:      #0D0D0D    /* 深い黒 */                  │
│    --bg-secondary:    #1A1A1A    /* パネル背景 */              │
│    --bg-tertiary:     #262626    /* 浮き上がり要素 */          │
│                                                                │
│  ■ Text                                                        │
│    --text-primary:    #DAD4BB    /* メインテキスト(セピア) */  │
│    --text-secondary:  #8B8678    /* サブテキスト */            │
│    --text-muted:      #4A473D    /* 非活性テキスト */          │
│                                                                │
│  ■ Accent                                                      │
│    --accent-gold:     #C9B77D    /* ゴールド(重要) */          │
│    --accent-red:      #8B0000    /* 警告・エラー */            │
│    --accent-white:    #F5F5DC    /* ハイライト */              │
│                                                                │
│  ■ Status                                                      │
│    --status-success:  #4A5D45    /* 成功(くすんだ緑) */        │
│    --status-warning:  #8B7355    /* 警告(くすんだオレンジ) */  │
│    --status-error:    #8B3A3A    /* エラー(くすんだ赤) */      │
│    --status-info:     #4A5568    /* 情報(くすんだ青) */        │
│                                                                │
│  ■ Borders & Lines                                             │
│    --border-primary:  #3D3D3D    /* 主要ボーダー */            │
│    --border-glow:     #DAD4BB33  /* 発光ボーダー(透過) */      │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 Color Usage Rules

| 用途 | カラー | 備考 |
|------|--------|------|
| 通常テキスト | `--text-primary` | セピア調の白 |
| 重要な情報 | `--accent-gold` | ゴールドで強調 |
| エラー・警告 | `--accent-red` | 控えめな赤 |
| 成功状態 | `--status-success` | くすんだ緑 |
| インタラクティブ要素 | `--accent-white` | ホバー時に使用 |

---

## 3. Typography

### 3.1 Font Stack

```css
/* Primary Font - 機械的なサンセリフ */
--font-primary: 'Rajdhani', 'Noto Sans JP', sans-serif;

/* Monospace - コード・ログ表示 */
--font-mono: 'Share Tech Mono', 'Source Code Pro', monospace;

/* Display - 大きな見出し */
--font-display: 'Orbitron', 'Rajdhani', sans-serif;
```

### 3.2 Type Scale

```
┌─────────────────────────────────────────────────────────────┐
│  TYPE SCALE                                                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  DISPLAY     48px / 3rem     Page titles, Hero text         │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ │
│  H1          32px / 2rem     Section headers                │
│  ──────────────────────────────────────────────────────     │
│  H2          24px / 1.5rem   Subsection headers             │
│  ─────────────────────────────────────────                  │
│  H3          18px / 1.125rem Card titles                    │
│  ────────────────────────────                               │
│  BODY        16px / 1rem     Body text                      │
│  ─────────────────────                                      │
│  SMALL       14px / 0.875rem Secondary info                 │
│  ──────────────────                                         │
│  CAPTION     12px / 0.75rem  Labels, timestamps             │
│  ────────────                                               │
│                                                             │
│  Letter Spacing: 0.05em (通常) / 0.1em (見出し)             │
│  Line Height: 1.6 (本文) / 1.2 (見出し)                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Visual Effects

### 4.1 Scanline Effect

```css
/* CRTスキャンライン効果 */
.scanlines::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: repeating-linear-gradient(
    0deg,
    rgba(0, 0, 0, 0.15),
    rgba(0, 0, 0, 0.15) 1px,
    transparent 1px,
    transparent 2px
  );
  pointer-events: none;
}
```

### 4.2 Glitch Effect

```
┌─────────────────────────────────────────────────────────────┐
│  GLITCH EFFECT TRIGGERS                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ● エラー発生時                                             │
│    - テキストの水平ズレ (2-4px)                             │
│    - RGB分離効果                                            │
│    - 0.1秒間のフリッカー                                    │
│                                                             │
│  ● ページ遷移時                                             │
│    - 画面全体のノイズオーバーレイ                           │
│    - 0.3秒のフェード                                        │
│                                                             │
│  ● 重要通知時                                               │
│    - ボーダーのグリッチ揺れ                                 │
│    - パルス効果                                             │
│                                                             │
│  ● Human Checkpoint待機時                                   │
│    - 緩やかなスキャンライン移動                             │
│    - 待機インジケータの点滅                                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 Geometric Decorations

```
円形ゲージ (Progress)          六角形グリッド (Background)
      ╭─────╮                      ⬡ ⬡ ⬡ ⬡ ⬡
    ╭─┤ 75% ├─╮                   ⬡ ⬡ ⬡ ⬡ ⬡
   │  ╰─────╯  │                   ⬡ ⬡ ⬡ ⬡ ⬡
   │    ○→     │                  ⬡ ⬡ ⬡ ⬡ ⬡
    ╰─────────╯

交差する線 (Decorative)        ターゲットマーカー
    ╲     ╱                         ┌──┐
     ╲   ╱                       ───┤  ├───
      ╲ ╱                           └──┘
       ╳                             ↑
      ╱ ╲                        フォーカス要素
     ╱   ╲
    ╱     ╲
```

---

## 5. Component Design

### 5.1 Panel / Card

```
┌─────────────────────────────────────────────────────────────────┐
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│ │
│ │░┌───────────────────────────────────────────────────────┐░░░│ │
│ │░│  PANEL HEADER                                    [×]  │░░░│ │
│ │░├───────────────────────────────────────────────────────┤░░░│ │
│ │░│                                                       │░░░│ │
│ │░│  Panel content goes here.                             │░░░│ │
│ │░│  Semi-transparent background with                     │░░░│ │
│ │░│  subtle border glow effect.                           │░░░│ │
│ │░│                                                       │░░░│ │
│ │░│  ─────────────────────────────────                    │░░░│ │
│ │░│                                                       │░░░│ │
│ │░│  [  ACTION BUTTON  ]                                  │░░░│ │
│ │░│                                                       │░░░│ │
│ │░└───────────────────────────────────────────────────────┘░░░│ │
│ │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Properties:                                                    │
│  - Background: rgba(26, 26, 26, 0.85)                          │
│  - Border: 1px solid #3D3D3D                                   │
│  - Border-radius: 0 (角は丸めない)                              │
│  - Box-shadow: 0 0 20px rgba(218, 212, 187, 0.1)               │
│  - Backdrop-filter: blur(10px)                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Buttons

```
┌─────────────────────────────────────────────────────────────────┐
│  BUTTON VARIANTS                                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────┐                                        │
│  │   PRIMARY ACTION    │  Primary Button                        │
│  └─────────────────────┘  - Border: 2px solid #DAD4BB           │
│                           - Background: transparent              │
│                           - Text: #DAD4BB                        │
│                           - Hover: Background #DAD4BB10          │
│                                                                 │
│  ┌─────────────────────┐                                        │
│  │   SECONDARY ACTION  │  Secondary Button                      │
│  └─────────────────────┘  - Border: 1px solid #3D3D3D           │
│                           - Background: transparent              │
│                           - Text: #8B8678                        │
│                                                                 │
│  ┌─────────────────────┐                                        │
│  │   ⚠ DANGER ACTION   │  Danger Button                         │
│  └─────────────────────┘  - Border: 1px solid #8B0000           │
│                           - Background: rgba(139,0,0,0.1)        │
│                           - Text: #8B3A3A                        │
│                                                                 │
│  ┌─────────────────────┐                                        │
│  │   ● APPROVE         │  Approval Button (Human Checkpoint)    │
│  └─────────────────────┘  - Border: 2px solid #C9B77D           │
│                           - Glow effect on hover                 │
│                           - Pulse animation when active          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Progress Indicators

```
┌─────────────────────────────────────────────────────────────────┐
│  PROGRESS INDICATORS                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Linear Progress                                                │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                    45%          │
│                                                                 │
│  Circular Progress (Agent Status)                               │
│                                                                 │
│         ╭───────────╮           ╭───────────╮                   │
│       ╭─┤  CONCEPT  ├─╮       ╭─┤  DESIGN   ├─╮                 │
│      │  ╰───────────╯  │     │  ╰───────────╯  │                │
│     ◐│    COMPLETE    │◑   ◐│   IN PROGRESS  │◑                │
│      │    ✓ 100%      │     │      67%       │                  │
│       ╰───────────────╯       ╰───────────────╯                 │
│                                                                 │
│  Phase Progress (Multi-step)                                    │
│                                                                 │
│    ●━━━━━━━●━━━━━━━◐━━━━━━━○━━━━━━━○                            │
│    P1      P1       P2      P3      P3                          │
│  Concept  Design   Code   Test   Review                         │
│                    ↑                                            │
│               Current                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.4 Status Indicators

```
┌─────────────────────────────────────────────────────────────────┐
│  STATUS BADGES                                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Agent Status                                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │ ◉ RUNNING      │  │ ◯ IDLE         │  │ ◈ WAITING      │     │
│  └────────────────┘  └────────────────┘  └────────────────┘     │
│    Pulsing glow        Dim, static        Slow pulse            │
│                                                                 │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │ ✓ COMPLETE     │  │ ✕ FAILED       │  │ ⧗ TIMEOUT      │     │
│  └────────────────┘  └────────────────┘  └────────────────┘     │
│    Success color       Error + glitch     Warning color         │
│                                                                 │
│  Human Checkpoint Status                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  ◈ AWAITING HUMAN APPROVAL                              │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │    │
│  │  Phase 1: Concept Review                                │    │
│  │  Waiting: 2h 34m                                        │    │
│  │                                                         │    │
│  │  [ APPROVE ]  [ REQUEST CHANGES ]  [ REJECT ]           │    │
│  └─────────────────────────────────────────────────────────┘    │
│    Golden border, slow pulse animation                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.5 Log Display

```
┌─────────────────────────────────────────────────────────────────┐
│  LOG VIEWER                                                     │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │  SYSTEM LOG                                    [Filter ▾]   │ │
│ ├─────────────────────────────────────────────────────────────┤ │
│ │                                                             │ │
│ │  14:23:01.234  [INFO ]  ConceptAgent started               │ │
│ │  14:23:01.567  [DEBUG]  Loading prompt template...         │ │
│ │  14:23:02.891  [INFO ]  Generating game concept...         │ │
│ │  14:23:15.432  [INFO ]  Concept generation complete        │ │
│ │  14:23:15.433  [WARN ]  Token usage: 2,847 / 4,096         │ │
│ │  14:23:15.500  [INFO ]  → Output saved to state            │ │
│ │  14:23:15.501  [CHECKPOINT] Awaiting human approval        │ │
│ │  ▌                                                         │ │
│ │                                                             │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
│  Styling:                                                       │
│  - Font: Share Tech Mono, 14px                                 │
│  - [INFO ]: #DAD4BB                                            │
│  - [DEBUG]: #4A473D                                            │
│  - [WARN ]: #C9B77D                                            │
│  - [ERROR]: #8B3A3A                                            │
│  - [CHECKPOINT]: #C9B77D with glow                             │
│  - Timestamps: #8B8678                                         │
│  - Auto-scroll with pause on hover                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Page Layouts

### 6.1 Dashboard (Main View)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  ≡  LANGGRAPH GAME STUDIO                              user ◉ ⚙ │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                                                                     │    │
│  │   PROJECT: Untitled RPG                           STATUS: ACTIVE   │    │
│  │   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │    │
│  │                                                                     │    │
│  │   ●━━━━━━━●━━━━━━━◐━━━━━━━○━━━━━━━○━━━━━━━○━━━━━━━○               │    │
│  │   Concept  Design   Code   Assets   Test   Review                  │    │
│  │                      ↑                                              │    │
│  │                  PHASE 2                                           │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌──────────────────────────────┐  ┌──────────────────────────────────┐    │
│  │  ACTIVE AGENTS               │  │  PENDING APPROVALS               │    │
│  │  ────────────────────────    │  │  ────────────────────────────    │    │
│  │                              │  │                                  │    │
│  │  ◉ CodeLeader    [Running]   │  │  ◈ Design Document Review        │    │
│  │    └─ CodeWorker #1          │  │    Waiting: 1h 23m               │    │
│  │    └─ CodeWorker #2          │  │    [ VIEW ] [ APPROVE ]          │    │
│  │                              │  │                                  │    │
│  │  ◉ AssetLeader   [Running]   │  │  ◈ Character Designs             │    │
│  │    └─ ArtWorker #1           │  │    Waiting: 45m                  │    │
│  │                              │  │    [ VIEW ] [ APPROVE ]          │    │
│  │  ◯ Tester        [Idle]      │  │                                  │    │
│  │  ◯ Reviewer      [Idle]      │  │                                  │    │
│  │                              │  │                                  │    │
│  └──────────────────────────────┘  └──────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  RECENT ACTIVITY                                                    │    │
│  │  ───────────────────────────────────────────────────────────────    │    │
│  │  14:23  CodeLeader  → Generated implementation plan for UI module  │    │
│  │  14:21  ArtWorker   → Completed character sprite: player_idle.png  │    │
│  │  14:18  CodeWorker  → Implemented player movement controller       │    │
│  │  14:15  System      → Phase 2 started                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Agent Detail View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ← Back                                                                     │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                                                                     │    │
│  │      ╭───────────────╮                                              │    │
│  │    ╭─┤  CODE LEADER  ├─╮     Status: ◉ RUNNING                     │    │
│  │   │  ╰───────────────╯  │    Runtime: 00:45:23                      │    │
│  │  ◐│                    │◑   Tasks: 12/28 complete                   │    │
│  │   │       43%          │    Sub-agents: 3 active                    │    │
│  │    ╰──────────────────╯                                             │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌──────────────────────────────┐  ┌──────────────────────────────────┐    │
│  │  CURRENT TASK                │  │  SUB-AGENTS                      │    │
│  │  ────────────────────────    │  │  ──────────────────────          │    │
│  │                              │  │                                  │    │
│  │  Implementing UI Components  │  │  ◉ CodeWorker #1                 │    │
│  │                              │  │    Task: PlayerController.ts     │    │
│  │  Progress:                   │  │    Progress: 78%                 │    │
│  │  ████████████░░░░░░░░ 60%   │  │                                  │    │
│  │                              │  │  ◉ CodeWorker #2                 │    │
│  │  Files modified:             │  │    Task: GameState.ts            │    │
│  │  - src/ui/Menu.tsx          │  │    Progress: 45%                 │    │
│  │  - src/ui/Button.tsx        │  │                                  │    │
│  │  - src/ui/styles.css        │  │  ◉ CodeWorker #3                 │    │
│  │                              │  │    Task: AssetLoader.ts          │    │
│  └──────────────────────────────┘  └──────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  AGENT LOG                                          [Filter ▾]      │    │
│  │  ───────────────────────────────────────────────────────────────    │    │
│  │  14:45:23  [INFO ]  Starting task: UI Components                   │    │
│  │  14:45:24  [INFO ]  Spawning CodeWorker for PlayerController       │    │
│  │  14:45:25  [DEBUG]  Analyzing dependencies...                      │    │
│  │  14:46:01  [INFO ]  CodeWorker #1 progress: 25%                    │    │
│  │  ▌                                                                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.3 Human Checkpoint Review

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                                                                     │    │
│  │  ◈ CHECKPOINT: Design Document Review                              │    │
│  │  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │    │
│  │                                                                     │    │
│  │  Agent: DesignAgent                                                │    │
│  │  Phase: 1 - Planning                                               │    │
│  │  Submitted: 2024-01-15 14:23:00                                    │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  OUTPUT PREVIEW                                                     │    │
│  │  ───────────────────────────────────────────────────────────────    │    │
│  │                                                                     │    │
│  │  # Technical Design Document                                        │    │
│  │                                                                     │    │
│  │  ## Architecture Overview                                          │    │
│  │  The game will use a component-based architecture with...          │    │
│  │                                                                     │    │
│  │  ## Technology Stack                                               │    │
│  │  - Engine: Phaser 3.60                                             │    │
│  │  - Language: TypeScript 5.0                                        │    │
│  │  - Build: Vite 5.0                                                 │    │
│  │                                                                     │    │
│  │  [Show Full Document...]                                           │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  FEEDBACK                                                           │    │
│  │  ───────────────────────────────────────────────────────────────    │    │
│  │  ┌───────────────────────────────────────────────────────────────┐ │    │
│  │  │                                                               │ │    │
│  │  │  Enter feedback for the agent...                              │ │    │
│  │  │                                                               │ │    │
│  │  └───────────────────────────────────────────────────────────────┘ │    │
│  │                                                                     │    │
│  │  ┌─────────────────┐  ┌─────────────────────┐  ┌───────────────┐   │    │
│  │  │   ✓ APPROVE     │  │  ↻ REQUEST CHANGES  │  │   ✕ REJECT    │   │    │
│  │  └─────────────────┘  └─────────────────────┘  └───────────────┘   │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.4 Project Creation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                    ╭─────────────────────────────────╮                      │
│                    │                                 │                      │
│                    │    CREATE NEW PROJECT           │                      │
│                    │                                 │                      │
│                    ╰─────────────────────────────────╯                      │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                                                                     │    │
│  │  Project Name                                                       │    │
│  │  ┌───────────────────────────────────────────────────────────────┐ │    │
│  │  │  My Awesome RPG                                               │ │    │
│  │  └───────────────────────────────────────────────────────────────┘ │    │
│  │                                                                     │    │
│  │  Game Concept                                                       │    │
│  │  ┌───────────────────────────────────────────────────────────────┐ │    │
│  │  │                                                               │ │    │
│  │  │  A 2D pixel art RPG where players explore a post-apocalyptic │ │    │
│  │  │  world filled with mysterious androids and ancient machines.  │ │    │
│  │  │  The combat system combines real-time action with strategic   │ │    │
│  │  │  pod-based abilities...                                       │ │    │
│  │  │                                                               │ │    │
│  │  └───────────────────────────────────────────────────────────────┘ │    │
│  │                                                                     │    │
│  │  Target Platform                                                    │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │    │
│  │  │ ◉ Web       │  │ ◯ Desktop   │  │ ◯ Mobile    │                 │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │    │
│  │                                                                     │    │
│  │  Scope                                                              │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │    │
│  │  │ ◉ MVP       │  │ ◯ Standard  │  │ ◯ Full      │                 │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │    │
│  │                                                                     │    │
│  │                                                                     │    │
│  │              ┌───────────────────────────────┐                      │    │
│  │              │      BEGIN DEVELOPMENT        │                      │    │
│  │              └───────────────────────────────┘                      │    │
│  │                                                                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Animations & Transitions

### 7.1 Animation Timing

```
┌─────────────────────────────────────────────────────────────────┐
│  ANIMATION TIMING FUNCTIONS                                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  --ease-smooth:     cubic-bezier(0.4, 0.0, 0.2, 1)             │
│  --ease-decelerate: cubic-bezier(0.0, 0.0, 0.2, 1)             │
│  --ease-accelerate: cubic-bezier(0.4, 0.0, 1, 1)               │
│                                                                 │
│  Duration Guidelines:                                           │
│  - Micro interactions: 100-150ms                               │
│  - Standard transitions: 200-300ms                             │
│  - Page transitions: 300-500ms                                 │
│  - Complex animations: 500-800ms                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Key Animations

| アニメーション | トリガー | 説明 |
|---------------|----------|------|
| Fade In | ページ読み込み | 0.3秒フェード + 軽いスキャンライン |
| Panel Slide | パネル開閉 | 左/右からスライド + フェード |
| Pulse Glow | 待機状態 | ボーダーの発光が緩やかに明滅 |
| Glitch Flash | エラー発生 | 0.1秒のRGB分離 + ノイズ |
| Progress Fill | 進捗更新 | 滑らかなバー伸長 |
| Status Change | 状態変更 | フェード + 軽いスケール |

### 7.3 Loading States

```
┌─────────────────────────────────────────────────────────────────┐
│  LOADING INDICATORS                                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Spinner (Small operations)                                     │
│                                                                 │
│         ◜                                                       │
│        ◝ ◞                                                      │
│         ◟                                                       │
│                                                                 │
│  Progress Bar (Known duration)                                  │
│                                                                 │
│    LOADING ████████████░░░░░░░░░░░░░░░░░░░░ 35%                │
│                                                                 │
│  Skeleton (Content loading)                                     │
│                                                                 │
│    ┌─────────────────────────────────────────────────┐         │
│    │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │         │
│    │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░           │         │
│    │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │         │
│    └─────────────────────────────────────────────────┘         │
│    Shimmer effect moves left to right                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Responsive Design

### 8.1 Breakpoints

```
┌─────────────────────────────────────────────────────────────────┐
│  BREAKPOINTS                                                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  --bp-mobile:   320px   /* 最小サポート幅 */                    │
│  --bp-tablet:   768px   /* タブレット */                        │
│  --bp-desktop:  1024px  /* デスクトップ */                      │
│  --bp-wide:     1440px  /* ワイドスクリーン */                  │
│                                                                 │
│  Layout Behavior:                                               │
│                                                                 │
│  Mobile (< 768px):                                              │
│  - Single column layout                                         │
│  - Collapsible sidebar                                          │
│  - Stacked cards                                                │
│  - Bottom navigation                                            │
│                                                                 │
│  Tablet (768px - 1024px):                                       │
│  - Two column layout                                            │
│  - Condensed sidebar                                            │
│  - Side-by-side cards                                           │
│                                                                 │
│  Desktop (> 1024px):                                            │
│  - Full layout                                                  │
│  - Expanded sidebar                                             │
│  - Grid-based cards                                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. Accessibility

### 9.1 Contrast Requirements

- すべてのテキストはWCAG AA基準を満たす
- 重要な情報は色だけでなくアイコンでも示す
- フォーカス状態は明確なアウトラインで表示

### 9.2 Keyboard Navigation

```
Tab         : 次のインタラクティブ要素へ
Shift+Tab   : 前のインタラクティブ要素へ
Enter/Space : ボタン/リンクの実行
Escape      : モーダル/パネルを閉じる
Arrow Keys  : リスト/メニュー内の移動
```

### 9.3 Screen Reader Support

- すべての画像にalt属性
- 適切なARIAラベル
- ライブリージョンで動的更新を通知

---

## 10. Design Tokens (CSS Variables)

```css
:root {
  /* Colors */
  --color-bg-primary: #0D0D0D;
  --color-bg-secondary: #1A1A1A;
  --color-bg-tertiary: #262626;
  --color-text-primary: #DAD4BB;
  --color-text-secondary: #8B8678;
  --color-text-muted: #4A473D;
  --color-accent-gold: #C9B77D;
  --color-accent-red: #8B0000;
  --color-accent-white: #F5F5DC;
  --color-status-success: #4A5D45;
  --color-status-warning: #8B7355;
  --color-status-error: #8B3A3A;
  --color-status-info: #4A5568;
  --color-border-primary: #3D3D3D;
  --color-border-glow: rgba(218, 212, 187, 0.2);

  /* Typography */
  --font-primary: 'Rajdhani', 'Noto Sans JP', sans-serif;
  --font-mono: 'Share Tech Mono', 'Source Code Pro', monospace;
  --font-display: 'Orbitron', 'Rajdhani', sans-serif;

  /* Spacing */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;
  --space-2xl: 48px;

  /* Border Radius */
  --radius-none: 0;
  --radius-sm: 2px;
  --radius-md: 4px;

  /* Shadows */
  --shadow-glow: 0 0 20px rgba(218, 212, 187, 0.1);
  --shadow-panel: 0 4px 20px rgba(0, 0, 0, 0.5);

  /* Transitions */
  --transition-fast: 150ms ease;
  --transition-normal: 300ms ease;
  --transition-slow: 500ms ease;

  /* Z-Index Scale */
  --z-base: 0;
  --z-dropdown: 100;
  --z-sticky: 200;
  --z-modal: 300;
  --z-toast: 400;
  --z-tooltip: 500;
}
```

---

## Appendix: Asset Requirements

### Fonts to Include
- Rajdhani (Google Fonts)
- Noto Sans JP (Google Fonts)
- Share Tech Mono (Google Fonts)
- Orbitron (Google Fonts)

### Required Images/Icons
- Logo (SVG)
- Agent status icons (SVG sprite)
- Phase icons (SVG sprite)
- Loading spinner (CSS animation or SVG)

### Sound Effects (Optional)
- UI click: subtle mechanical click
- Notification: soft chime
- Error: low warning tone
- Approval: confirmation tone
