# 戦略マップ (Strategy Map) 仕様書

## 概要

エージェントの活動状況を2Dマップ上でリアルタイム可視化するコンポーネント。
エージェント間の関係性、AIサービスへのリクエスト、ユーザー承認フローを視覚的に表現する。

---

## 機能要件

### 1. エージェント表示

| 状態 | 視覚表現 |
|------|----------|
| `running` | オレンジ色のグロー、上下に揺れるアニメーション |
| `waiting_approval` | 点線の円、ユーザーノード付近に配置 |
| `pending` | 半透明、「zzz」表示 |
| `completed` | 吹き出し「タスク完了!」 |
| `failed` / `blocked` | 50%透明度 |

### 2. 動的配置

- **スポーン**: パーティクルエフェクト付きで出現
- **デスポーン**: フェードアウト + パーティクル散布
- **移動**: バネ-ダンパー物理モデルによる滑らかな移動
- **回避**: 他エージェントを検出し、ステアリングで迂回

### 3. 通信の可視化

パケット（光の玉）による通信表現:

| 種別 | 色 | 用途 |
|------|-----|------|
| `instruction` | 青 (#5080B0) | リーダー → ワーカー |
| `confirm` | オレンジ (#C49060) | ワーカー → リーダー（確認） |
| `delivery` | 緑 (#60A060) | ワーカー → リーダー（納品） |
| `ai-request` | 紫 (#9060B0) | エージェント → AIサービス |
| `user-contact` | 赤 (#B05050) | エージェント → ユーザー |

### 4. ノード

#### AIサービスノード
- 画面上部に横並び配置
- パルスアニメーション
- アクティブエージェント数をバッジ表示

#### ユーザーノード
- 画面下部中央
- 承認待ちキューがある場合、赤いパルスで警告表示

### 5. インタラクション

- **ズーム**: マウスホイール (0.35x - 2.8x)
- **パン**: ドラッグで移動

---

## アーキテクチャ

```
src/components/strategy-map/
├── strategyMapConfig.ts   # 全定数定義
├── strategyMapTypes.ts    # 型定義
├── StrategyMapCanvas.tsx  # Canvas描画エンジン
└── SPECIFICATION.md       # 本ドキュメント

src/views/
└── StrategyMapView.tsx    # Viewコンポーネント
```

---

## 設定パラメータ

### PHYSICS（物理演算）

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| `SPRING_STIFFNESS` | 0.06 | バネ定数 |
| `DAMPING` | 0.88 | 減衰係数 |
| `MIN_VELOCITY` | 0.01 | 最小速度閾値 |
| `EPSILON` | 0.001 | 数値安定性用微小値 |
| `REPULSION_RADIUS` | 50 | 回避検出半径 (px) |
| `AVOIDANCE_STRENGTH` | 0.7 | 回避強度 (0-1) |
| `PARTICLE_FRICTION` | 0.98 | パーティクル摩擦係数 |

### LAYOUT（レイアウト）

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| `AI_ZONE_Y` | 0.12 | AIノードのY位置比率 |
| `USER_ZONE_Y` | 0.88 | ユーザーノードのY位置比率 |
| `WORK_ZONE_TOP` | 0.22 | 作業エリア上端比率 |
| `LEADER_SPACING_MAX` | 180 | リーダー間最大間隔 (px) |
| `CHILD_VERTICAL_GAP` | 70 | 親子間縦距離 (px) |
| `APPROVAL_QUEUE_SPACING` | 55 | 承認キュー間隔 (px) |
| `AI_ORBIT_RADIUS_BASE` | 65 | AI周囲配置の基本半径 |

### ANIMATION（アニメーション）

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| `AI_PULSE_SPEED` | 0.04 | AIノードパルス速度 |
| `AGENT_BOB_SPEED` | 0.08 | エージェント揺れ速度 |
| `BUBBLE_FLOAT_SPEED` | 0.055 | 吹き出し浮遊速度 |
| `WAITING_DASH_SPEED` | 0.25 | 待機円点線速度 |

### TIMING（タイミング）

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| `SPAWN_DURATION_MS` | 800 | スポーン演出時間 (ms) |
| `PACKET_SPAWN_INTERVAL` | 25 | パケット生成間隔 (frame) |
| `PACKET_SPEED` | 0.035 | パケット移動速度 |
| `PARTICLE_INITIAL_LIFE` | 35 | パーティクル寿命 (frame) |

---

## 計算ロジック

### エージェント位置決定 (`computeAgentTarget`)

優先順位:
1. `waiting_approval` → ユーザーノード上部にキュー配置
2. `running` + `aiTarget` → AIサービス周囲に扇状配置
3. `parentId`あり → 親エージェント下部にグリッド配置
4. それ以外（リーダー） → 画面中央上部に横並び

### 障害物回避 (`findAvoidanceDirection`)

1. 進行方向前方の全エージェントをスキャン
2. 最も近い障害物を検出（距離の二乗で比較、sqrt削減）
3. 外積で回避方向（左/右）を決定
4. 進行方向と垂直方向をブレンド

```
回避後の方向 = 元方向 × (1 - strength) + 垂直方向 × strength
```

### 物理シミュレーション (`updatePhysics`)

```
加速度 = (目標位置 - 現在位置) × SPRING_STIFFNESS
速度 += 加速度
速度 *= DAMPING
位置 += 速度
```

---

## パフォーマンス考慮

- **障害物検出**: 距離の二乗で比較、必要時のみ`sqrt`
- **AIカウント**: 1回のループでMap集計 (O(n))
- **ソート**: Y座標のみ抽出してソート
- **定数**: 全て`as const`で型安全かつ最適化

---

## 型定義

```typescript
interface MapAgent {
  readonly id: string
  readonly type: AgentType
  readonly status: AgentStatus
  readonly parentId: string | null
  readonly aiTarget: AIServiceId | null
  readonly bubble: string | null
  readonly bubbleType: BubbleType | null
  readonly spawnProgress: number
}

interface AgentPositionState {
  x: number
  y: number
  vx: number
  vy: number
  targetX: number
  targetY: number
}

type ConnectionType =
  | 'instruction'
  | 'confirm'
  | 'delivery'
  | 'ai-request'
  | 'user-contact'
```

---

## 依存関係

- React 18+
- Canvas 2D API
- `pixelCharacters.ts` (エージェント描画)
- `agentStore` / `projectStore` (Zustand)
